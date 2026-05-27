"""
State manager for the Silverworm control system.

Manages AUTO/MANUAL mode, setpoint selection, and command routing.
All motor speed decisions flow through this controller.

Arrow flow:
    UI actions → controller (mode select) → setpoint selection → comms layer
    Vision pipeline → auto setpoints → controller → comms layer
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, List


class OperatingMode(Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


@dataclass
class Setpoints:
    """Motor speed setpoints (RPM)."""
    speed_a: float = 0.0  # Feed motor
    speed_b: float = 0.0  # Wrapper motor


# Bounds for manual speed input validation
SPEED_A_MIN = 0.0
SPEED_A_MAX = 10.0    # Feed motor: 0-10 RPM
SPEED_B_MIN = 0.0
SPEED_B_MAX = 3000.0  # Wrapper motor: 0-3000 RPM


class SetpointController:
    """
    Central controller for mode management and setpoint routing.

    Enforces the data-handling rule:
    - MANUAL mode: only manual_setpoints are used/transmitted.
    - AUTO mode: only auto_setpoints are used/transmitted.

    Usage:
        controller = SetpointController()
        controller.on_setpoints_changed = lambda sp: comms.send_speeds(sp)
        controller.set_mode(OperatingMode.MANUAL)
        controller.set_manual_speeds(1.5, 1200.0)
    """

    def __init__(self):
        self._mode: OperatingMode = OperatingMode.AUTO
        self._auto_setpoints = Setpoints()
        self._manual_setpoints = Setpoints()
        self._manual_ack_required = False
        self._manual_ack_done = False

        # Callback fired whenever the active setpoints change.
        # Signature: (Setpoints) -> None
        self.on_setpoints_changed: Optional[Callable[[Setpoints], None]] = None

        # Callback fired when mode changes.
        # Signature: (OperatingMode) -> None
        self.on_mode_changed: Optional[Callable[[OperatingMode], None]] = None

    # --- Properties ---

    @property
    def mode(self) -> OperatingMode:
        return self._mode

    @property
    def active_setpoints(self) -> Setpoints:
        """Return the setpoints that should be transmitted to hardware."""
        if self._mode == OperatingMode.MANUAL:
            return Setpoints(
                speed_a=self._manual_setpoints.speed_a,
                speed_b=self._manual_setpoints.speed_b,
            )
        return Setpoints(
            speed_a=self._auto_setpoints.speed_a,
            speed_b=self._auto_setpoints.speed_b,
        )

    @property
    def manual_setpoints(self) -> Setpoints:
        return self._manual_setpoints

    @property
    def auto_setpoints(self) -> Setpoints:
        return self._auto_setpoints

    @property
    def manual_ack_required(self) -> bool:
        """True if manual mode was auto-triggered and not yet acknowledged."""
        return self._manual_ack_required and not self._manual_ack_done

    # --- Mode control ---

    def set_mode(self, mode: OperatingMode):
        """Switch operating mode. Fires callbacks."""
        old_mode = self._mode
        self._mode = mode

        if mode == OperatingMode.MANUAL and old_mode != OperatingMode.MANUAL:
            # Clear ack state for user-initiated toggle (no ack needed)
            self._manual_ack_required = False
            self._manual_ack_done = False

        if old_mode != mode:
            if self.on_mode_changed:
                self.on_mode_changed(mode)
            self._notify_setpoints()

    def trigger_manual_from_low_confidence(self):
        """
        Auto-trigger manual mode due to low confidence.
        Sets the ack-required flag so the UI can show a banner/dialog.
        """
        self._manual_ack_required = True
        self._manual_ack_done = False
        self._mode = OperatingMode.MANUAL

        if self.on_mode_changed:
            self.on_mode_changed(OperatingMode.MANUAL)
        self._notify_setpoints()

    def acknowledge_manual_mode(self):
        """User acknowledged the auto-triggered manual mode banner."""
        self._manual_ack_done = True

    def toggle_mode(self):
        """Toggle between AUTO and MANUAL."""
        if self._mode == OperatingMode.AUTO:
            self.set_mode(OperatingMode.MANUAL)
        else:
            self.set_mode(OperatingMode.AUTO)

    # --- Setpoint updates ---

    def set_manual_speeds(self, speed_a: float, speed_b: float) -> bool:
        """
        Set manual motor speeds. Only effective when in MANUAL mode.

        Returns True if values were accepted (valid and in MANUAL mode).
        """
        if self._mode != OperatingMode.MANUAL:
            return False

        # Validate and clamp
        speed_a = max(SPEED_A_MIN, min(SPEED_A_MAX, speed_a))
        speed_b = max(SPEED_B_MIN, min(SPEED_B_MAX, speed_b))

        self._manual_setpoints.speed_a = speed_a
        self._manual_setpoints.speed_b = speed_b
        self._notify_setpoints()
        return True

    def set_manual_speed_a(self, speed: float) -> bool:
        """Set manual feed motor speed only."""
        if self._mode != OperatingMode.MANUAL:
            return False
        speed = max(SPEED_A_MIN, min(SPEED_A_MAX, speed))
        self._manual_setpoints.speed_a = speed
        self._notify_setpoints()
        return True

    def set_manual_speed_b(self, speed: float) -> bool:
        """Set manual wrapper motor speed only."""
        if self._mode != OperatingMode.MANUAL:
            return False
        speed = max(SPEED_B_MIN, min(SPEED_B_MAX, speed))
        self._manual_setpoints.speed_b = speed
        self._notify_setpoints()
        return True

    def update_auto_setpoints(self, speed_a: float, speed_b: float):
        """
        Update auto-computed setpoints from vision pipeline.
        If in AUTO mode, this triggers a setpoints-changed notification.
        """
        self._auto_setpoints.speed_a = speed_a
        self._auto_setpoints.speed_b = speed_b
        if self._mode == OperatingMode.AUTO:
            self._notify_setpoints()

    # --- Internal ---

    def _notify_setpoints(self):
        if self.on_setpoints_changed:
            self.on_setpoints_changed(self.active_setpoints)
