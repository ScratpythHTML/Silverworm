"""
Central application state.

Single source of truth for:
  - mode (AUTO / MANUAL)
  - machine_on (machine power state)
  - wrap_speed_rpm  (dial 1 / D1 — wrap motor)
  - feed_speed_mms  (dial 2 / D2 — feed motor)

Receives events from two places:
  - PUI (Physical UI, via PUIListener signals or direct apply_* calls)
  - GUI (via gui_set_* methods)

PUI precedence rule
-------------------
PUI is the source of truth for `mode`. We track the last-known state of
the physical auto/manual switch in `_pui_in_manual` (set by AS0/AS1).

  - PUI mode-switch events always win: AS0/AS1 immediately change the mode.
  - GUI → MANUAL is always allowed (covers low-confidence auto-trigger
    and operator overrides "into" manual).
  - GUI → AUTO is REJECTED while `_pui_in_manual` is True. The operator
    must flip the physical switch to AUTO first. A `mode_change_blocked`
    signal carries the reason so the UI can warn the user.

Speeds and machine_on follow simple "last write wins" — only mode has
a hard PUI lock, because manual mode gates access to the dial-driven
speed inputs.

Routing to motors
-----------------
AppState holds two MotorControllers (wrap, feed) and forwards:
  - machine_on transitions   → start(speed) or stop(RAMP_DOWN)
  - speed changes while on   → set_speed(units)
Speed changes while the machine is off do not transmit; they update
state only and will be applied on the next start.

Tests can construct AppState without motors (pass None) — speed/power
changes still update state and emit signals, just without any I/O.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from comms.pui import DialChange, ModeSwitch, PUIMode, DetentSize
from comms.motor_spi import MotorController, StopType, SPEED_MAX
from config import AppConfig


class Mode(Enum):
    AUTO = "auto"
    MANUAL = "manual"


# Default safety bounds. The motor itself enforces real limits; these
# are application-side clamps to prevent obvious nonsense from PUI dial
# accumulation. Tune once we know the real motor specs.
WRAP_SPEED_MIN_RPM = 0.0
WRAP_SPEED_MAX_RPM = 2000.0
FEED_SPEED_MIN_MMS = 0.0
FEED_SPEED_MAX_MMS = 10.0


# Physical → SPI integer scaling. Confirm with Arduino firmware once
# the units they expect are pinned down.
WRAP_RPM_UNITS_PER = 10        # 1 unit = 0.1 RPM  → up to 6553.5 RPM
FEED_MMS_UNITS_PER = 1000      # 1 unit = 0.001 mm/s → up to 65.535 mm/s


def _scale_to_units(value: float, units_per: int) -> int:
    return max(0, min(SPEED_MAX, int(round(value * units_per))))


def rpm_to_units(rpm: float) -> int:
    return _scale_to_units(rpm, WRAP_RPM_UNITS_PER)


def mms_to_units(mms: float) -> int:
    return _scale_to_units(mms, FEED_MMS_UNITS_PER)


class AppState(QObject):
    """Central mutable state + signal hub + motor routing."""

    mode_changed = pyqtSignal(object)            # Mode
    machine_power_changed = pyqtSignal(bool)
    wrap_speed_changed = pyqtSignal(float)       # rpm
    feed_speed_changed = pyqtSignal(float)       # mm/s
    motor_error = pyqtSignal(str)                # SPI / hardware error message
    mode_change_blocked = pyqtSignal(str)        # human-readable rejection reason

    def __init__(
        self,
        config: AppConfig,
        wrap_motor: Optional[MotorController] = None,
        feed_motor: Optional[MotorController] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._config = config
        self._wrap_motor = wrap_motor
        self._feed_motor = feed_motor

        self._mode: Mode = Mode.AUTO
        self._machine_on: bool = False
        self._wrap_speed_rpm: float = 0.0
        self._feed_speed_mms: float = 0.0
        # Last-known position of the PUI auto/manual switch. While True,
        # GUI requests to leave manual mode are rejected. Edge-triggered
        # from AS0/AS1; if the PUI boots in MANUAL but never sends AS0,
        # this stays False (a hardware-sync limitation, not solvable here).
        self._pui_in_manual: bool = False

    # ----- read-only accessors ------------------------------------------

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def machine_on(self) -> bool:
        return self._machine_on

    @property
    def wrap_speed_rpm(self) -> float:
        return self._wrap_speed_rpm

    @property
    def feed_speed_mms(self) -> float:
        return self._feed_speed_mms

    @property
    def config(self) -> AppConfig:
        return self._config

    # ----- PUI event handlers -------------------------------------------

    def apply_dial_change(self, change: DialChange) -> None:
        """
        Apply a dial detent event. The dial sends an *increment*, not an
        absolute value — we look up (dial, size) in DetentConfig and add.

        Dial events only mutate speed in MANUAL mode. In AUTO the vision
        pipeline owns speed, so dial events are ignored. (Confirm with
        PUI firmware author whether dial events should also be ignored
        on the panel side while in auto — for now we just drop them.)
        """
        if self._mode != Mode.MANUAL:
            return

        delta = self._increment_for(change)
        if change.dial == 1:
            self._set_wrap_speed(self._wrap_speed_rpm + delta)
        elif change.dial == 2:
            self._set_feed_speed(self._feed_speed_mms + delta)

    def apply_mode_switch(self, switch: ModeSwitch) -> None:
        new_mode = Mode.MANUAL if switch.mode == PUIMode.MANUAL else Mode.AUTO
        self._pui_in_manual = (new_mode == Mode.MANUAL)
        self._set_mode(new_mode)

    def apply_power_toggle(self) -> None:
        self._set_machine_on(not self._machine_on)

    # ----- GUI mutators (same setters — PUI just wins by overwriting) ---

    def gui_set_mode(self, mode: Mode) -> None:
        # PUI lock: while the physical switch is in MANUAL, the GUI cannot
        # leave manual mode. GUI → MANUAL is always allowed (covers low-
        # confidence auto-trigger).
        if mode == Mode.AUTO and self._pui_in_manual:
            self.mode_change_blocked.emit(
                "PUI is in MANUAL — flip the panel switch to leave manual mode"
            )
            return
        self._set_mode(mode)

    def gui_set_wrap_speed(self, rpm: float) -> None:
        self._set_wrap_speed(rpm)

    def gui_set_feed_speed(self, mms: float) -> None:
        self._set_feed_speed(mms)

    def gui_set_machine_on(self, on: bool) -> None:
        self._set_machine_on(on)

    # ----- internal setters ---------------------------------------------

    def _set_mode(self, mode: Mode) -> None:
        if self._mode == mode:
            return
        self._mode = mode
        self.mode_changed.emit(mode)

    def _motor_call(self, fn, *args) -> None:
        """Call a motor method, catch hardware errors and emit motor_error."""
        try:
            fn(*args)
        except Exception as e:
            self.motor_error.emit(str(e))

    def _set_wrap_speed(self, rpm: float) -> None:
        rpm = max(WRAP_SPEED_MIN_RPM, min(WRAP_SPEED_MAX_RPM, rpm))
        if self._wrap_speed_rpm == rpm:
            return
        self._wrap_speed_rpm = rpm
        self.wrap_speed_changed.emit(rpm)
        if self._machine_on and self._wrap_motor is not None:
            self._motor_call(self._wrap_motor.set_speed, rpm_to_units(rpm))

    def _set_feed_speed(self, mms: float) -> None:
        mms = max(FEED_SPEED_MIN_MMS, min(FEED_SPEED_MAX_MMS, mms))
        if self._feed_speed_mms == mms:
            return
        self._feed_speed_mms = mms
        self.feed_speed_changed.emit(mms)
        if self._machine_on and self._feed_motor is not None:
            self._motor_call(self._feed_motor.set_speed, mms_to_units(mms))

    def _set_machine_on(self, on: bool) -> None:
        if self._machine_on == on:
            return
        self._machine_on = on
        self.machine_power_changed.emit(on)
        if on:
            if self._wrap_motor is not None:
                self._motor_call(self._wrap_motor.start, rpm_to_units(self._wrap_speed_rpm))
            if self._feed_motor is not None:
                self._motor_call(self._feed_motor.start, mms_to_units(self._feed_speed_mms))
        else:
            if self._wrap_motor is not None:
                self._motor_call(self._wrap_motor.stop, StopType.RAMP_DOWN)
            if self._feed_motor is not None:
                self._motor_call(self._feed_motor.stop, StopType.RAMP_DOWN)

    # ----- detent → increment lookup ------------------------------------

    def _increment_for(self, change: DialChange) -> float:
        d = self._config.detent_config
        sign = float(change.direction)
        if change.dial == 1:
            mapping = {
                DetentSize.SMALL: d.dial1_small_rpm,
                DetentSize.MEDIUM: d.dial1_medium_rpm,
                DetentSize.LARGE: d.dial1_large_rpm,
            }
        else:
            mapping = {
                DetentSize.SMALL: d.dial2_small_mms,
                DetentSize.MEDIUM: d.dial2_medium_mms,
                DetentSize.LARGE: d.dial2_large_mms,
            }
        return sign * mapping[change.size]
