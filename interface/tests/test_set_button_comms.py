"""
Tests for the SET button → controller → comms → overlay flow.

Validates:
- Speeds are only sent to comms when SET is explicitly triggered (not on typing).
- Successful comms send shows overlay message on camera widget.
- Failed comms send does NOT show overlay (error is logged instead).
- SET button does nothing when not in MANUAL mode.
"""

import pytest
from comms.transport import MockTransport
from controller import SetpointController, OperatingMode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def system():
    """Full controller + transport system mimicking MainWindow wiring."""
    transport = MockTransport()
    transport.open()

    ctrl = SetpointController()
    last_comms_ok = {"value": True}
    overlay_messages = []

    def on_setpoints_changed(sp):
        last_comms_ok["value"] = True
        try:
            transport.send_speeds(sp.speed_a, sp.speed_b)
        except IOError:
            last_comms_ok["value"] = False

    ctrl.on_setpoints_changed = on_setpoints_changed

    def set_feed_motor(value):
        """Simulates _on_feed_motor_set in MainWindow."""
        if ctrl.set_manual_speed_a(value):
            if last_comms_ok["value"]:
                overlay_messages.append(f"Feed motor speed set to {value:.1f} RPM")
                return True
        return False

    def set_wrapper_motor(value):
        """Simulates _on_wrapper_motor_set in MainWindow."""
        if ctrl.set_manual_speed_b(value):
            if last_comms_ok["value"]:
                overlay_messages.append(f"Wrapper motor speed set to {value:.1f} RPM")
                return True
        return False

    return {
        "ctrl": ctrl,
        "transport": transport,
        "overlay_messages": overlay_messages,
        "set_feed_motor": set_feed_motor,
        "set_wrapper_motor": set_wrapper_motor,
    }


# ---------------------------------------------------------------------------
# SET button only triggers comms when explicitly called
# ---------------------------------------------------------------------------

class TestSetButtonTriggersComms:
    def test_no_comms_before_set_clicked(self, system):
        """Just entering MANUAL mode sends the mode-change setpoints,
        but no individual motor SET has fired yet."""
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        initial_count = len(system["transport"].sent_packets)

        # Simulate user typing in field (no SET click) — nothing should be sent
        # We just don't call set_feed_motor/set_wrapper_motor
        assert len(system["transport"].sent_packets) == initial_count

    def test_comms_sent_on_set_click_feed(self, system):
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["transport"].clear()

        system["set_feed_motor"](3.5)

        assert len(system["transport"].sent_packets) == 1
        a, b = system["transport"].decode_last_speeds()
        assert a == pytest.approx(3.5)

    def test_comms_sent_on_set_click_wrapper(self, system):
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["transport"].clear()

        system["set_wrapper_motor"](1200.0)

        assert len(system["transport"].sent_packets) == 1
        a, b = system["transport"].decode_last_speeds()
        assert b == pytest.approx(1200.0)

    def test_set_rejected_in_auto_mode(self, system):
        """SET button does nothing when not in MANUAL mode."""
        assert system["ctrl"].mode == OperatingMode.AUTO
        system["transport"].clear()

        result = system["set_feed_motor"](5.0)

        assert result is False
        assert len(system["transport"].sent_packets) == 0


# ---------------------------------------------------------------------------
# Overlay message on successful comms
# ---------------------------------------------------------------------------

class TestOverlayOnSuccess:
    def test_overlay_shown_on_feed_motor_set(self, system):
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["overlay_messages"].clear()

        system["set_feed_motor"](2.5)

        assert len(system["overlay_messages"]) == 1
        assert "Feed motor" in system["overlay_messages"][0]
        assert "2.5" in system["overlay_messages"][0]

    def test_overlay_shown_on_wrapper_motor_set(self, system):
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["overlay_messages"].clear()

        system["set_wrapper_motor"](900.0)

        assert len(system["overlay_messages"]) == 1
        assert "Wrapper motor" in system["overlay_messages"][0]
        assert "900.0" in system["overlay_messages"][0]

    def test_no_overlay_on_comms_failure(self, system):
        """If transport is closed/broken, no success overlay is shown."""
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["transport"].close()  # Simulate broken transport
        system["overlay_messages"].clear()

        result = system["set_feed_motor"](5.0)

        assert result is False
        assert len(system["overlay_messages"]) == 0

    def test_multiple_set_clicks_produce_multiple_overlays(self, system):
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["overlay_messages"].clear()

        system["set_feed_motor"](1.0)
        system["set_wrapper_motor"](500.0)

        assert len(system["overlay_messages"]) == 2

    def test_overlay_contains_actual_speed_value(self, system):
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["overlay_messages"].clear()

        system["set_feed_motor"](7.3)

        assert "7.3" in system["overlay_messages"][0]


# ---------------------------------------------------------------------------
# Comms packet correctness after SET
# ---------------------------------------------------------------------------

class TestCommsPacketAfterSet:
    def test_feed_motor_speed_in_packet(self, system):
        """After SET on feed motor, the packet contains the correct speed_a."""
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        system["transport"].clear()

        system["set_feed_motor"](4.0)

        a, b = system["transport"].decode_last_speeds()
        assert a == pytest.approx(4.0)

    def test_wrapper_motor_speed_in_packet(self, system):
        """After SET on wrapper motor, the packet contains the correct speed_b."""
        system["ctrl"].set_mode(OperatingMode.MANUAL)
        # Set feed first so both have values
        system["set_feed_motor"](1.5)
        system["transport"].clear()

        system["set_wrapper_motor"](1800.0)

        a, b = system["transport"].decode_last_speeds()
        assert a == pytest.approx(1.5)  # feed from earlier
        assert b == pytest.approx(1800.0)

    def test_consecutive_set_updates_value(self, system):
        """Clicking SET twice with different values sends the latest."""
        system["ctrl"].set_mode(OperatingMode.MANUAL)

        system["set_feed_motor"](2.0)
        system["set_feed_motor"](8.0)

        a, _ = system["transport"].decode_last_speeds()
        assert a == pytest.approx(8.0)
