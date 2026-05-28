"""
Tests for SetpointController — manual mode logic, setpoint routing, mode toggling.

Validates the core data-handling rule:
    MANUAL mode → only manual_setpoints used/transmitted.
    AUTO mode   → only auto_setpoints used/transmitted.
"""

import pytest
from controller import (
    SetpointController, OperatingMode, Setpoints,
    SPEED_A_MIN, SPEED_A_MAX, SPEED_B_MIN, SPEED_B_MAX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ctrl():
    return SetpointController()


@pytest.fixture
def ctrl_with_recorder():
    """Controller with callbacks that record every change."""
    c = SetpointController()
    record = {"setpoints": [], "modes": []}
    c.on_setpoints_changed = lambda sp: record["setpoints"].append(sp)
    c.on_mode_changed = lambda m: record["modes"].append(m)
    return c, record


# ---------------------------------------------------------------------------
# Manual mode ON — setpoint selection
# ---------------------------------------------------------------------------

class TestManualModeOn:
    def test_manual_mode_on_uses_manual_speeds(self, ctrl):
        ctrl.set_mode(OperatingMode.MANUAL)
        ctrl._manual_setpoints.speed_a = 2.5
        ctrl._manual_setpoints.speed_b = 800.0

        sp = ctrl.active_setpoints
        assert sp.speed_a == 2.5
        assert sp.speed_b == 800.0

    def test_set_manual_speeds_accepted_in_manual_mode(self, ctrl):
        ctrl.set_mode(OperatingMode.MANUAL)
        assert ctrl.set_manual_speeds(3.0, 1500.0) is True
        assert ctrl.active_setpoints.speed_a == 3.0
        assert ctrl.active_setpoints.speed_b == 1500.0

    def test_set_manual_speeds_rejected_in_auto_mode(self, ctrl):
        """Manual speeds must NOT be accepted when mode is AUTO."""
        assert ctrl.mode == OperatingMode.AUTO
        assert ctrl.set_manual_speeds(3.0, 1500.0) is False
        # active setpoints should still be auto (default 0s)
        assert ctrl.active_setpoints.speed_a == 0.0

    def test_manual_speed_a_only(self, ctrl):
        ctrl.set_mode(OperatingMode.MANUAL)
        assert ctrl.set_manual_speed_a(4.5) is True
        assert ctrl.manual_setpoints.speed_a == 4.5

    def test_manual_speed_b_only(self, ctrl):
        ctrl.set_mode(OperatingMode.MANUAL)
        assert ctrl.set_manual_speed_b(2200.0) is True
        assert ctrl.manual_setpoints.speed_b == 2200.0

    def test_manual_speed_clamped_to_bounds(self, ctrl):
        ctrl.set_mode(OperatingMode.MANUAL)
        ctrl.set_manual_speeds(-5.0, 9999.0)
        assert ctrl.manual_setpoints.speed_a == SPEED_A_MIN
        assert ctrl.manual_setpoints.speed_b == SPEED_B_MAX

    def test_manual_mode_active_setpoints_independent_of_auto(self, ctrl):
        """In MANUAL, auto setpoints must not leak into active setpoints."""
        ctrl.update_auto_setpoints(1.0, 1000.0)
        ctrl.set_mode(OperatingMode.MANUAL)
        ctrl.set_manual_speeds(5.0, 500.0)

        sp = ctrl.active_setpoints
        assert sp.speed_a == 5.0   # manual, NOT auto
        assert sp.speed_b == 500.0

    def test_auto_update_does_not_notify_in_manual_mode(self, ctrl_with_recorder):
        ctrl, record = ctrl_with_recorder
        ctrl.set_mode(OperatingMode.MANUAL)
        record["setpoints"].clear()

        ctrl.update_auto_setpoints(1.0, 1000.0)
        # No notification because we're in MANUAL
        assert len(record["setpoints"]) == 0


# ---------------------------------------------------------------------------
# Manual mode toggle
# ---------------------------------------------------------------------------

class TestManualModeToggle:
    def test_toggle_on(self, ctrl):
        assert ctrl.mode == OperatingMode.AUTO
        ctrl.toggle_mode()
        assert ctrl.mode == OperatingMode.MANUAL

    def test_toggle_off(self, ctrl):
        ctrl.set_mode(OperatingMode.MANUAL)
        ctrl.toggle_mode()
        assert ctrl.mode == OperatingMode.AUTO

    def test_manual_mode_available_with_high_confidence(self, ctrl):
        """User can always enable manual mode regardless of confidence."""
        # Simulate high confidence scenario (auto mode working fine)
        ctrl.update_auto_setpoints(1.0, 1000.0)
        ctrl.set_mode(OperatingMode.MANUAL)
        assert ctrl.mode == OperatingMode.MANUAL

    def test_mode_change_fires_callback(self, ctrl_with_recorder):
        ctrl, record = ctrl_with_recorder
        ctrl.set_mode(OperatingMode.MANUAL)
        assert record["modes"] == [OperatingMode.MANUAL]

    def test_setpoints_callback_fires_on_mode_change(self, ctrl_with_recorder):
        ctrl, record = ctrl_with_recorder
        ctrl._manual_setpoints.speed_a = 2.0
        ctrl._manual_setpoints.speed_b = 600.0
        ctrl.set_mode(OperatingMode.MANUAL)
        assert len(record["setpoints"]) == 1
        assert record["setpoints"][0].speed_a == 2.0


# ---------------------------------------------------------------------------
# Confidence-triggered manual mode
# ---------------------------------------------------------------------------

class TestConfidenceTriggeredManualMode:
    def test_low_confidence_triggers_manual_mode(self, ctrl):
        ctrl.trigger_manual_from_low_confidence()
        assert ctrl.mode == OperatingMode.MANUAL

    def test_low_confidence_requires_ack(self, ctrl):
        ctrl.trigger_manual_from_low_confidence()
        assert ctrl.manual_ack_required is True

    def test_ack_clears_flag(self, ctrl):
        ctrl.trigger_manual_from_low_confidence()
        ctrl.acknowledge_manual_mode()
        assert ctrl.manual_ack_required is False

    def test_user_toggle_does_not_require_ack(self, ctrl):
        ctrl.set_mode(OperatingMode.MANUAL)
        assert ctrl.manual_ack_required is False

    def test_low_confidence_fires_mode_callback(self, ctrl_with_recorder):
        ctrl, record = ctrl_with_recorder
        ctrl.trigger_manual_from_low_confidence()
        assert OperatingMode.MANUAL in record["modes"]


# ---------------------------------------------------------------------------
# Setpoint selection rule (transmitted values)
# ---------------------------------------------------------------------------

class TestSetpointSelection:
    def test_transmitted_values_are_manual_in_manual_mode(self, ctrl_with_recorder):
        ctrl, record = ctrl_with_recorder
        ctrl.set_mode(OperatingMode.MANUAL)
        ctrl.set_manual_speeds(3.5, 1200.0)

        last = record["setpoints"][-1]
        assert last.speed_a == 3.5
        assert last.speed_b == 1200.0

    def test_transmitted_values_are_auto_in_auto_mode(self, ctrl_with_recorder):
        ctrl, record = ctrl_with_recorder
        ctrl.update_auto_setpoints(1.0, 1000.0)

        last = record["setpoints"][-1]
        assert last.speed_a == 1.0
        assert last.speed_b == 1000.0

    def test_switching_to_manual_transmits_manual_values(self, ctrl_with_recorder):
        ctrl, record = ctrl_with_recorder
        ctrl.update_auto_setpoints(1.0, 1000.0)
        ctrl._manual_setpoints.speed_a = 5.0
        ctrl._manual_setpoints.speed_b = 750.0
        ctrl.set_mode(OperatingMode.MANUAL)

        last = record["setpoints"][-1]
        assert last.speed_a == 5.0
        assert last.speed_b == 750.0
