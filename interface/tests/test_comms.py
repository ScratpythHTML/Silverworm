"""
Tests for the comms transport layer.

Validates:
- Command packet construction (framing, checksum).
- MockTransport records sent data correctly.
- Correct speeds are transmitted via the transport.
- Integration: controller → comms sends correct values.
"""

import struct
import pytest
from comms.transport import (
    Transport, MockTransport, CommandID,
    build_command, build_set_speeds_command,
    START_BYTE, _xor_checksum,
)
from controller import SetpointController, OperatingMode


# ---------------------------------------------------------------------------
# Packet construction
# ---------------------------------------------------------------------------

class TestBuildCommand:
    def test_start_byte(self):
        pkt = build_command(CommandID.START)
        assert pkt[0] == START_BYTE

    def test_command_id_in_packet(self):
        pkt = build_command(CommandID.STOP)
        assert pkt[1] == CommandID.STOP

    def test_payload_length_byte(self):
        payload = b"\x01\x02\x03"
        pkt = build_command(CommandID.SET_SPEEDS, payload)
        assert pkt[2] == 3

    def test_checksum_correct(self):
        payload = b"\x01\x02"
        pkt = build_command(CommandID.SET_SPEEDS, payload)
        inner = pkt[1:-1]  # cmd + len + payload
        assert pkt[-1] == _xor_checksum(inner)

    def test_empty_payload(self):
        pkt = build_command(CommandID.START)
        assert pkt[2] == 0  # payload len = 0
        assert len(pkt) == 4  # start + cmd + len + checksum

    def test_set_speeds_command_structure(self):
        pkt = build_set_speeds_command(1.0, 1000.0)
        assert pkt[0] == START_BYTE
        assert pkt[1] == CommandID.SET_SPEEDS
        assert pkt[2] == 8  # two float32 = 8 bytes
        payload = pkt[3:11]
        a, b = struct.unpack("<ff", payload)
        assert a == pytest.approx(1.0)
        assert b == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# MockTransport
# ---------------------------------------------------------------------------

class TestMockTransport:
    def test_open_close(self):
        t = MockTransport()
        assert not t.is_open()
        t.open()
        assert t.is_open()
        t.close()
        assert not t.is_open()

    def test_send_raises_when_closed(self):
        t = MockTransport()
        with pytest.raises(IOError):
            t.send(b"\x00")

    def test_send_records_data(self):
        t = MockTransport()
        t.open()
        t.send(b"\xAA\x01")
        assert len(t.sent_packets) == 1
        assert t.sent_packets[0] == b"\xAA\x01"

    def test_last_packet(self):
        t = MockTransport()
        t.open()
        t.send(b"\x01")
        t.send(b"\x02")
        assert t.last_packet() == b"\x02"

    def test_last_packet_none_when_empty(self):
        t = MockTransport()
        assert t.last_packet() is None

    def test_clear(self):
        t = MockTransport()
        t.open()
        t.send(b"\x01")
        t.clear()
        assert len(t.sent_packets) == 0

    def test_send_speeds(self):
        t = MockTransport()
        t.open()
        t.send_speeds(2.0, 500.0)
        assert len(t.sent_packets) == 1
        a, b = t.decode_last_speeds()
        assert a == pytest.approx(2.0)
        assert b == pytest.approx(500.0)

    def test_decode_last_speeds_none_for_non_speed_cmd(self):
        t = MockTransport()
        t.open()
        t.send_command(CommandID.START)
        assert t.decode_last_speeds() is None

    def test_send_command_convenience(self):
        t = MockTransport()
        t.open()
        t.send_command(CommandID.PAUSE)
        pkt = t.last_packet()
        assert pkt[1] == CommandID.PAUSE


# ---------------------------------------------------------------------------
# Controller → Comms integration
# ---------------------------------------------------------------------------

class TestControllerCommsIntegration:
    def test_manual_speeds_transmitted_via_mock(self):
        """Full path: controller in MANUAL → set speeds → comms sends correct values."""
        transport = MockTransport()
        transport.open()

        ctrl = SetpointController()
        ctrl.on_setpoints_changed = lambda sp: transport.send_speeds(sp.speed_a, sp.speed_b)

        ctrl.set_mode(OperatingMode.MANUAL)
        ctrl.set_manual_speeds(3.5, 1200.0)

        a, b = transport.decode_last_speeds()
        assert a == pytest.approx(3.5)
        assert b == pytest.approx(1200.0)

    def test_auto_speeds_transmitted_via_mock(self):
        """Full path: controller in AUTO → update auto setpoints → comms sends correct values."""
        transport = MockTransport()
        transport.open()

        ctrl = SetpointController()
        ctrl.on_setpoints_changed = lambda sp: transport.send_speeds(sp.speed_a, sp.speed_b)

        ctrl.update_auto_setpoints(1.0, 1000.0)

        a, b = transport.decode_last_speeds()
        assert a == pytest.approx(1.0)
        assert b == pytest.approx(1000.0)

    def test_mode_switch_transmits_correct_source(self):
        """Switching modes must transmit the new mode's setpoints, not the old ones."""
        transport = MockTransport()
        transport.open()

        ctrl = SetpointController()
        ctrl.on_setpoints_changed = lambda sp: transport.send_speeds(sp.speed_a, sp.speed_b)

        # Set auto values
        ctrl.update_auto_setpoints(1.0, 1000.0)

        # Set manual values (directly, before switching)
        ctrl._manual_setpoints.speed_a = 5.0
        ctrl._manual_setpoints.speed_b = 500.0

        # Switch to manual — should transmit manual values
        ctrl.set_mode(OperatingMode.MANUAL)

        a, b = transport.decode_last_speeds()
        assert a == pytest.approx(5.0)
        assert b == pytest.approx(500.0)
