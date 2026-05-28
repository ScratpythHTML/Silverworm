"""
Unit tests for AppState — the central state machine that mediates between
PUI events, GUI input, and SPI motor commands.

Covers the PUI-precedence rule and end-to-end signal flow from PUI message
through state mutation to motor packet.
"""

import pytest

from app_state import AppState, Mode, rpm_to_units, mms_to_units
from comms.pui import DialChange, ModeSwitch, PUIMode, DetentSize
from comms.motor_spi import (
    MockSPITransport, MotorController,
    CommandPrefix, StopType,
)
from config import AppConfig, DetentConfig


# qapp fixture is provided by pytest-qt via conftest.py.


@pytest.fixture
def config():
    """Config with the placeholder detent values from the spec."""
    return AppConfig(
        detent_config=DetentConfig(
            dial1_small_rpm=0.1, dial1_medium_rpm=0.5, dial1_large_rpm=1.0,
            dial2_small_mms=0.01, dial2_medium_mms=0.05, dial2_large_mms=0.1,
        )
    )


@pytest.fixture
def state_with_motors(qapp, config):
    wrap_t = MockSPITransport()
    feed_t = MockSPITransport()
    wrap_mc = MotorController(wrap_t)
    feed_mc = MotorController(feed_t)
    wrap_mc.open()
    feed_mc.open()
    state = AppState(config, wrap_motor=wrap_mc, feed_motor=feed_mc)
    return state, wrap_t, feed_t


# ============================================================================
# Test 1, 2: dial events apply configured increments, not absolute values
# ============================================================================

class TestDialEventsApplyIncrements:

    def test_d1_minus_two_in_manual_decreases_wrap_by_medium(self, state_with_motors):
        """Test 1: D1-2 in manual mode subtracts the medium dial-1 increment."""
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)
        state.gui_set_wrap_speed(5.0)

        state.apply_dial_change(DialChange(1, -1, DetentSize.MEDIUM))

        # Medium increment for dial 1 = 0.5 rpm, direction = -1
        assert state.wrap_speed_rpm == pytest.approx(4.5)

    def test_d1_plus_two_applies_increment_not_absolute(self, state_with_motors):
        """Test 2: D1+2 must NOT set speed to 2; it adds the medium increment (+0.5)."""
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)
        state.gui_set_wrap_speed(3.0)

        state.apply_dial_change(DialChange(1, +1, DetentSize.MEDIUM))

        assert state.wrap_speed_rpm == pytest.approx(3.5)
        assert state.wrap_speed_rpm != 2.0  # would be wrong (treating N as value)

    def test_d2_applies_increment_to_feed(self, state_with_motors):
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)
        state.gui_set_feed_speed(0.5)

        state.apply_dial_change(DialChange(2, +1, DetentSize.LARGE))

        assert state.feed_speed_mms == pytest.approx(0.6)

    def test_small_medium_large_distinct_increments(self, state_with_motors):
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)

        for size, expected in [
            (DetentSize.SMALL, 0.1),
            (DetentSize.MEDIUM, 0.5),
            (DetentSize.LARGE, 1.0),
        ]:
            state.gui_set_wrap_speed(0.0)
            state.apply_dial_change(DialChange(1, +1, size))
            assert state.wrap_speed_rpm == pytest.approx(expected)

    def test_dial_change_in_auto_mode_is_ignored(self, state_with_motors):
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.AUTO)
        state.gui_set_wrap_speed(5.0)

        state.apply_dial_change(DialChange(1, +1, DetentSize.MEDIUM))

        assert state.wrap_speed_rpm == 5.0


# ============================================================================
# Test 3, 4, 6: mode-switch PUI events override GUI-set mode
# ============================================================================

class TestModePrecedence:

    def test_as0_forces_manual_even_if_gui_was_auto(self, state_with_motors):
        """Test 3."""
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.AUTO)
        assert state.mode == Mode.AUTO

        state.apply_mode_switch(ModeSwitch(PUIMode.MANUAL))
        assert state.mode == Mode.MANUAL

    def test_as1_forces_auto_even_if_gui_was_manual(self, state_with_motors):
        """Test 4."""
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)
        assert state.mode == Mode.MANUAL

        state.apply_mode_switch(ModeSwitch(PUIMode.AUTO))
        assert state.mode == Mode.AUTO

    def test_gui_change_then_pui_overrides(self, state_with_motors):
        """Test 6: GUI can change mode, but a later AS0/AS1 from ESP32 overrides."""
        state, _, _ = state_with_motors

        state.gui_set_mode(Mode.MANUAL)
        assert state.mode == Mode.MANUAL

        # PUI sends AS1 → overrides
        state.apply_mode_switch(ModeSwitch(PUIMode.AUTO))
        assert state.mode == Mode.AUTO

        # GUI puts it back to manual
        state.gui_set_mode(Mode.MANUAL)
        assert state.mode == Mode.MANUAL

        # PUI sends AS0 → still manual (no observable change but no rejection)
        state.apply_mode_switch(ModeSwitch(PUIMode.MANUAL))
        assert state.mode == Mode.MANUAL


class TestPUIManualLock:
    """While PUI is in MANUAL, GUI cannot leave manual mode."""

    def test_gui_auto_blocked_when_pui_in_manual(self, state_with_motors):
        state, _, _ = state_with_motors
        state.apply_mode_switch(ModeSwitch(PUIMode.MANUAL))
        assert state.mode == Mode.MANUAL

        state.gui_set_mode(Mode.AUTO)
        # Lock holds — state must remain MANUAL.
        assert state.mode == Mode.MANUAL

    def test_blocked_change_emits_signal_with_reason(self, qapp, state_with_motors):
        state, _, _ = state_with_motors
        state.apply_mode_switch(ModeSwitch(PUIMode.MANUAL))

        captured: list[str] = []
        state.mode_change_blocked.connect(captured.append)
        state.gui_set_mode(Mode.AUTO)

        assert len(captured) == 1
        assert "MANUAL" in captured[0].upper()

    def test_pui_releases_lock_then_gui_auto_works(self, state_with_motors):
        state, _, _ = state_with_motors
        state.apply_mode_switch(ModeSwitch(PUIMode.MANUAL))
        state.gui_set_mode(Mode.AUTO)  # blocked
        assert state.mode == Mode.MANUAL

        state.apply_mode_switch(ModeSwitch(PUIMode.AUTO))  # PUI releases
        assert state.mode == Mode.AUTO

        state.gui_set_mode(Mode.AUTO)  # now allowed (already auto)
        assert state.mode == Mode.AUTO

        # And GUI can flip-flop freely.
        state.gui_set_mode(Mode.MANUAL)
        assert state.mode == Mode.MANUAL
        state.gui_set_mode(Mode.AUTO)
        assert state.mode == Mode.AUTO

    def test_gui_manual_allowed_when_pui_in_manual(self, state_with_motors):
        """Auto-trigger fires gui_set_mode(MANUAL) — must succeed regardless of lock."""
        state, _, _ = state_with_motors
        state.apply_mode_switch(ModeSwitch(PUIMode.MANUAL))

        state.gui_set_mode(Mode.MANUAL)  # no conflict
        assert state.mode == Mode.MANUAL

    def test_gui_auto_allowed_when_pui_never_set(self, state_with_motors):
        """Initial state — no PUI events seen — GUI can do anything."""
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)
        state.gui_set_mode(Mode.AUTO)
        assert state.mode == Mode.AUTO


# ============================================================================
# Test 5: TP toggles machine_on and triggers start/stop on the motors
# ============================================================================

class TestPowerToggle:

    def test_tp_toggles_machine_on(self, state_with_motors):
        state, _, _ = state_with_motors
        assert state.machine_on is False

        state.apply_power_toggle()
        assert state.machine_on is True

        state.apply_power_toggle()
        assert state.machine_on is False

    def test_tp_on_sends_start_to_both_motors(self, state_with_motors):
        state, wrap_t, feed_t = state_with_motors
        state.gui_set_wrap_speed(2.0)        # 2.0 rpm × 10 = 20 units
        state.gui_set_feed_speed(0.5)        # 0.5 mm/s × 1000 = 500 units
        wrap_t.sent.clear()
        feed_t.sent.clear()

        state.apply_power_toggle()  # → on

        assert wrap_t.sent[0] == bytes([CommandPrefix.START]) + (20).to_bytes(2, "little")
        assert feed_t.sent[0] == bytes([CommandPrefix.START]) + (500).to_bytes(2, "little")

    def test_tp_off_sends_stop_to_both_motors(self, state_with_motors):
        state, wrap_t, feed_t = state_with_motors
        state.apply_power_toggle()  # on
        wrap_t.sent.clear()
        feed_t.sent.clear()

        state.apply_power_toggle()  # off

        assert wrap_t.sent[0] == bytes([CommandPrefix.STOP, StopType.RAMP_DOWN])
        assert feed_t.sent[0] == bytes([CommandPrefix.STOP, StopType.RAMP_DOWN])


# ============================================================================
# Speed change while running propagates to motor; while off it does not
# ============================================================================

class TestSpeedChangePropagation:

    def test_dial_change_while_running_sends_set_speed(self, state_with_motors):
        state, wrap_t, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)
        state.apply_power_toggle()  # on
        wrap_t.sent.clear()

        state.apply_dial_change(DialChange(1, +1, DetentSize.LARGE))  # +1.0 rpm

        # 0 + 1.0 rpm → 10 units
        assert wrap_t.sent[-1] == bytes([CommandPrefix.SET_SPEED]) + (10).to_bytes(2, "little")

    def test_dial_change_while_off_does_not_send(self, state_with_motors):
        state, wrap_t, _ = state_with_motors
        state.gui_set_mode(Mode.MANUAL)
        wrap_t.sent.clear()

        state.apply_dial_change(DialChange(1, +1, DetentSize.LARGE))

        # State updated but no SPI packet emitted
        assert state.wrap_speed_rpm == pytest.approx(1.0)
        assert wrap_t.sent == []


# ============================================================================
# Signal emissions
# ============================================================================

class TestSignals:

    def test_mode_change_emits_signal(self, state_with_motors):
        state, _, _ = state_with_motors
        received = []
        state.mode_changed.connect(received.append)

        state.apply_mode_switch(ModeSwitch(PUIMode.MANUAL))
        state.apply_mode_switch(ModeSwitch(PUIMode.AUTO))

        assert received == [Mode.MANUAL, Mode.AUTO]

    def test_machine_power_emits_signal(self, state_with_motors):
        state, _, _ = state_with_motors
        received = []
        state.machine_power_changed.connect(received.append)

        state.apply_power_toggle()
        state.apply_power_toggle()

        assert received == [True, False]

    def test_no_signal_for_no_op_mode_change(self, state_with_motors):
        state, _, _ = state_with_motors
        state.gui_set_mode(Mode.AUTO)  # already auto by default; should be no-op
        received = []
        state.mode_changed.connect(received.append)

        state.apply_mode_switch(ModeSwitch(PUIMode.AUTO))

        assert received == []


# ============================================================================
# AppState without motors (state-only mode for unit tests)
# ============================================================================

class TestNoMotors:

    def test_state_updates_without_motors(self, qapp, config):
        state = AppState(config)  # no motors
        state.gui_set_mode(Mode.MANUAL)
        state.apply_dial_change(DialChange(1, +1, DetentSize.MEDIUM))

        assert state.wrap_speed_rpm == pytest.approx(0.5)
        # No exception even with no motor configured

    def test_power_toggle_without_motors(self, qapp, config):
        state = AppState(config)
        state.apply_power_toggle()
        assert state.machine_on is True


# ============================================================================
# Scaling helpers
# ============================================================================

class TestScaling:

    def test_rpm_to_units_clamps_to_max(self):
        assert rpm_to_units(99999.0) == 0xFFFF

    def test_rpm_to_units_clamps_to_min(self):
        assert rpm_to_units(-5.0) == 0

    def test_rpm_to_units_rounds(self):
        # 2.5 rpm × 10 = 25 units
        assert rpm_to_units(2.5) == 25

    def test_mms_to_units(self):
        assert mms_to_units(0.5) == 500
