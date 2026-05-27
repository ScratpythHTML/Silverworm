"""Unit tests for the motor SPI protocol — packet encoding/decoding + MotorController."""

import sys
from types import SimpleNamespace

import pytest

from comms.motor_spi import (
    CommandPrefix, ResponsePrefix, StopType, SPEED_MAX,
    build_start, build_stop, build_set_speed, build_test_movement,
    parse_arduino_response,
    CurrentSpeed, ErrorResponse, SequenceStatus,
    MockSPITransport, MotorController, SPIMotorTransport,
)


class TestSetSpeedPacket:
    """Test 7: 16-bit speed encodes correctly into speedL, speedH."""

    def test_set_speed_low_byte_then_high_byte(self):
        # 0x1234 → low byte 0x34 first, high byte 0x12 second (little-endian)
        packet = build_set_speed(0x1234)
        assert packet == bytes([CommandPrefix.SET_SPEED, 0x34, 0x12])

    def test_set_speed_zero(self):
        assert build_set_speed(0) == bytes([CommandPrefix.SET_SPEED, 0x00, 0x00])

    def test_set_speed_max(self):
        assert build_set_speed(SPEED_MAX) == bytes([CommandPrefix.SET_SPEED, 0xFF, 0xFF])

    def test_set_speed_one(self):
        assert build_set_speed(1) == bytes([CommandPrefix.SET_SPEED, 0x01, 0x00])

    def test_set_speed_256_crosses_byte_boundary(self):
        # 256 = 0x0100 → low=0x00, high=0x01
        assert build_set_speed(256) == bytes([CommandPrefix.SET_SPEED, 0x00, 0x01])

    def test_set_speed_out_of_range_raises(self):
        with pytest.raises(ValueError):
            build_set_speed(SPEED_MAX + 1)
        with pytest.raises(ValueError):
            build_set_speed(-1)


class TestStartPacket:
    def test_start_includes_initial_speed(self):
        packet = build_start(500)
        # 500 = 0x01F4 → low=0xF4, high=0x01
        assert packet == bytes([CommandPrefix.START, 0xF4, 0x01])

    def test_start_at_max_speed(self):
        assert build_start(SPEED_MAX) == bytes([CommandPrefix.START, 0xFF, 0xFF])


class TestStopPacket:
    """Test 8: Stop command encodes the correct stop type."""

    def test_stop_ramp_down(self):
        assert build_stop(StopType.RAMP_DOWN) == bytes([CommandPrefix.STOP, 1])

    def test_stop_emergency(self):
        assert build_stop(StopType.EMERGENCY) == bytes([CommandPrefix.STOP, 2])

    def test_stop_power_off(self):
        assert build_stop(StopType.POWER_OFF) == bytes([CommandPrefix.STOP, 3])


class TestTestMovementPacket:
    def test_basic(self):
        assert build_test_movement(0x05) == bytes([CommandPrefix.TEST_MOVEMENT, 0x05])

    def test_max(self):
        assert build_test_movement(0xFF) == bytes([CommandPrefix.TEST_MOVEMENT, 0xFF])

    def test_out_of_range(self):
        with pytest.raises(ValueError):
            build_test_movement(0x100)


class TestResponseParsing:
    """Test 9: Arduino response packets parse correctly."""

    def test_current_speed(self):
        # CURRENT_SPEED=1, speed 0x1234 → low 0x34, high 0x12
        resp = parse_arduino_response(bytes([ResponsePrefix.CURRENT_SPEED, 0x34, 0x12]))
        assert resp == CurrentSpeed(speed=0x1234)

    def test_current_speed_zero(self):
        resp = parse_arduino_response(bytes([ResponsePrefix.CURRENT_SPEED, 0x00, 0x00]))
        assert resp == CurrentSpeed(speed=0)

    def test_current_speed_max(self):
        resp = parse_arduino_response(bytes([ResponsePrefix.CURRENT_SPEED, 0xFF, 0xFF]))
        assert resp == CurrentSpeed(speed=0xFFFF)

    def test_error_response(self):
        assert parse_arduino_response(bytes([ResponsePrefix.ERROR, 0x07])) \
            == ErrorResponse(error_code=7)

    def test_status_response(self):
        assert parse_arduino_response(bytes([ResponsePrefix.SEQUENCE_STATUS, 0x02])) \
            == SequenceStatus(status=2)

    def test_short_current_speed_returns_none(self):
        # Only one byte of payload — not enough
        assert parse_arduino_response(bytes([ResponsePrefix.CURRENT_SPEED, 0x00])) is None

    def test_empty_bytes_returns_none(self):
        assert parse_arduino_response(b"") is None

    def test_unknown_prefix_returns_none(self):
        assert parse_arduino_response(bytes([0xFF, 0, 0])) is None


class TestMockSPITransportAndController:
    """Test 10: mock transports let us drive MotorController without hardware."""

    def test_send_is_recorded(self):
        t = MockSPITransport()
        t.open()
        t.send(b"\x01\x34\x12")
        assert t.sent == [b"\x01\x34\x12"]

    def test_inject_then_read_then_drained(self):
        t = MockSPITransport()
        t.open()
        t.inject_response(b"\x01\x00\x01")
        assert t.read() == [b"\x01\x00\x01"]
        assert t.read() == []  # drained

    def test_motor_controller_set_speed_emits_packet(self):
        t = MockSPITransport()
        mc = MotorController(t)
        mc.open()
        mc.set_speed(0x1234)
        assert t.sent == [bytes([CommandPrefix.SET_SPEED, 0x34, 0x12])]

    def test_motor_controller_stop_emergency(self):
        t = MockSPITransport()
        mc = MotorController(t)
        mc.open()
        mc.stop(StopType.EMERGENCY)
        assert t.sent == [bytes([CommandPrefix.STOP, 2])]

    def test_motor_controller_start(self):
        t = MockSPITransport()
        mc = MotorController(t)
        mc.open()
        mc.start(0x0100)
        assert t.sent == [bytes([CommandPrefix.START, 0x00, 0x01])]

    def test_motor_controller_poll_emits_current_speed(self, qapp):
        t = MockSPITransport()
        mc = MotorController(t)
        mc.open()

        received = []
        mc.current_speed.connect(received.append)

        t.inject_response(bytes([ResponsePrefix.CURRENT_SPEED, 0x10, 0x00]))
        mc.poll()

        assert received == [0x0010]

    def test_motor_controller_poll_emits_error(self, qapp):
        t = MockSPITransport()
        mc = MotorController(t)
        mc.open()
        errors = []
        mc.error_received.connect(errors.append)
        t.inject_response(bytes([ResponsePrefix.ERROR, 0x42]))
        mc.poll()
        assert errors == [0x42]

    def test_motor_controller_poll_emits_status(self, qapp):
        t = MockSPITransport()
        mc = MotorController(t)
        mc.open()
        statuses = []
        mc.sequence_status.connect(statuses.append)
        t.inject_response(bytes([ResponsePrefix.SEQUENCE_STATUS, 0x03]))
        mc.poll()
        assert statuses == [0x03]


class TestSPIMotorTransport:
    def test_send_clocks_packet_and_queues_parseable_response(self, monkeypatch):
        spi_instances = []

        class FakeSpiDev:
            def __init__(self):
                self.transfers = []
                self.max_speed_hz = None
                spi_instances.append(self)

            def open(self, bus, device):
                self.bus = bus
                self.device = device

            def close(self):
                self.closed = True

            def xfer2(self, data):
                self.transfers.append(data)
                return [ResponsePrefix.CURRENT_SPEED, 0x34, 0x12]

        monkeypatch.setitem(sys.modules, "spidev", SimpleNamespace(SpiDev=FakeSpiDev))

        transport = SPIMotorTransport(bus=1, device=2, max_speed_hz=123_000)
        transport.open()
        transport.send(bytes([CommandPrefix.SET_SPEED, 0x34, 0x12]))

        assert spi_instances[0].bus == 1
        assert spi_instances[0].device == 2
        assert spi_instances[0].max_speed_hz == 123_000
        assert spi_instances[0].transfers == [[CommandPrefix.SET_SPEED, 0x34, 0x12]]
        assert transport.read() == [
            bytes([ResponsePrefix.CURRENT_SPEED, 0x34, 0x12]),
            bytes([ResponsePrefix.CURRENT_SPEED, 0x34, 0x12]),
        ]

    def test_read_polls_with_zeroes(self, monkeypatch):
        class FakeSpiDev:
            def open(self, bus, device):
                pass

            def close(self):
                pass

            def xfer2(self, data):
                self.last_transfer = data
                return [ResponsePrefix.CURRENT_SPEED, 0x10, 0x00]

        fake = FakeSpiDev()
        monkeypatch.setitem(sys.modules, "spidev", SimpleNamespace(SpiDev=lambda: fake))

        transport = SPIMotorTransport(read_length=3)
        transport.open()

        assert transport.read() == [bytes([ResponsePrefix.CURRENT_SPEED, 0x10, 0x00])]
        assert fake.last_transfer == [0, 0, 0]


# qapp fixture is provided by pytest-qt via conftest.py.
