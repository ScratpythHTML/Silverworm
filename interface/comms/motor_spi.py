"""
Motor controller SPI communication layer — RPi to Arduino.

Protocol (RPi → Arduino):
    Prefix 1: Start          payload: speedL, speedH       (2 bytes, LE)
    Prefix 2: Stop           payload: stop_type            (1 byte)
                              1 = ramp-down gently
                              2 = emergency sudden stop
                              3 = cut off power
    Prefix 3: Set speed      payload: speedL, speedH       (2 bytes, LE)
    Prefix 4: Test movement  payload: movement_type        (1 byte)

Protocol (Arduino → RPi):
    Prefix 1: Current speed     payload: speedL, speedH
    Prefix 2: Error             payload: error_code (1 byte)
    Prefix 3: Sequence status   payload: status (1 byte)

Speed is a 16-bit unsigned integer (0..65535). Mapping physical units
(RPM, mm/s) to integer counts is the application's job; this module
deals only in 16-bit speeds.
"""

from __future__ import annotations

import struct
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional, Union

from PyQt6.QtCore import QObject, pyqtSignal


# ----- enums -----------------------------------------------------------------

class CommandPrefix(IntEnum):
    START = 0x01
    STOP = 0x02
    SET_SPEED = 0x03
    TEST_MOVEMENT = 0x04
    REQUEST_SPEED = 0x05  # RPi asks Arduino to reply with current speed


class ResponsePrefix(IntEnum):
    CURRENT_SPEED = 0x01
    ERROR = 0x02
    SEQUENCE_STATUS = 0x03


class StopType(IntEnum):
    RAMP_DOWN = 1
    EMERGENCY = 2
    POWER_OFF = 3


SPEED_MAX = 0xFFFF


# ----- packet builders -------------------------------------------------------

def _pack_speed(speed: int) -> bytes:
    if not 0 <= speed <= SPEED_MAX:
        raise ValueError(f"speed must be 0..{SPEED_MAX}, got {speed}")
    return struct.pack("<H", speed)  # little-endian: speedL, speedH


def build_start(speed: int) -> bytes:
    return bytes([CommandPrefix.START]) + _pack_speed(speed)


def build_stop(stop_type: StopType) -> bytes:
    return bytes([CommandPrefix.STOP, int(stop_type)])


def build_set_speed(speed: int) -> bytes:
    return bytes([CommandPrefix.SET_SPEED]) + _pack_speed(speed)


def build_test_movement(movement_type: int) -> bytes:
    if not 0 <= movement_type <= 0xFF:
        raise ValueError("movement_type must fit in one byte")
    return bytes([CommandPrefix.TEST_MOVEMENT, movement_type])


def build_request_speed() -> bytes:
    """Ask the Arduino to reply with its current speed.
    3 bytes total: command + 2 clock bytes. The current Arduino firmware
    returns the queued speed packet on the next request transaction.
    """
    return bytes([CommandPrefix.REQUEST_SPEED, 0x00, 0x00])


def _normalize_spi_response(tx_data: bytes, raw: bytes) -> Optional[bytes]:
    """Convert a raw SPI transaction into a parseable response packet.

    Some Arduino SPI slave implementations return a reply that was queued by
    the previous transaction. Accept properly framed replies first, then the
    older shifted request-speed form used during bench bring-up. All-zero reads
    are treated as "no reply" so the GUI does not display a fake 0 speed.
    """
    if not raw:
        return None

    raw = bytes(raw)
    response_prefixes = (
        ResponsePrefix.CURRENT_SPEED,
        ResponsePrefix.ERROR,
        ResponsePrefix.SEQUENCE_STATUS,
    )

    if raw[0] in response_prefixes:
        return raw[:3]

    if len(raw) >= 4 and raw[1] in response_prefixes:
        return raw[1:4]

    if (
        tx_data
        and tx_data[0] == CommandPrefix.REQUEST_SPEED
        and len(raw) >= 3
        and raw[0] == CommandPrefix.REQUEST_SPEED
        and any(raw[1:3])
    ):
        return bytes([ResponsePrefix.CURRENT_SPEED, raw[1], raw[2]])

    return None


# ----- response types --------------------------------------------------------

@dataclass(frozen=True)
class CurrentSpeed:
    speed: int


@dataclass(frozen=True)
class ErrorResponse:
    error_code: int


@dataclass(frozen=True)
class SequenceStatus:
    status: int


ArduinoResponse = Union[CurrentSpeed, ErrorResponse, SequenceStatus]


def parse_arduino_response(data: bytes) -> Optional[ArduinoResponse]:
    """
    Parse one response packet. Returns None for malformed/unknown packets.
    Caller handles framing — pass exactly one packet's worth of bytes.
    """
    if not data:
        return None
    prefix = data[0]
    payload = data[1:]

    if prefix == ResponsePrefix.CURRENT_SPEED:
        if len(payload) < 2:
            return None
        speed = struct.unpack("<H", payload[:2])[0]
        return CurrentSpeed(speed=speed)

    if prefix == ResponsePrefix.ERROR:
        if len(payload) < 1:
            return None
        return ErrorResponse(error_code=payload[0])

    if prefix == ResponsePrefix.SEQUENCE_STATUS:
        if len(payload) < 1:
            return None
        return SequenceStatus(status=payload[0])

    return None


# ----- transport abstraction -------------------------------------------------

class SPITransport(ABC):
    """SPI-like transport. send() and read() are independent half-duplex
    operations from the caller's perspective."""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def send(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self) -> List[bytes]:
        """Return any response packets received since the last call.
        Each entry is one fully-framed packet."""


class MockSPITransport(SPITransport):
    """In-memory transport. Records sent packets in `sent`; tests inject
    response packets via inject_response()."""

    def __init__(self):
        self.sent: List[bytes] = []
        self._inbox: List[bytes] = []
        self._lock = threading.Lock()
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def send(self, data: bytes) -> None:
        with self._lock:
            self.sent.append(bytes(data))

    def inject_response(self, data: bytes) -> None:
        with self._lock:
            self._inbox.append(bytes(data))

    def read(self) -> List[bytes]:
        with self._lock:
            out = self._inbox
            self._inbox = []
        return out


class SPIMotorTransport(SPITransport):
    """
    Real SPI transport via spidev. Lazy-imported so non-Linux dev
    machines can still load this module.

    Arduino firmware (Main.ino) defaults SPCR to SPI Mode 0 (CPOL=0,
    CPHA=0). We set mode explicitly to match rather than relying on the
    spidev default.

    Response framing: the Arduino reply is normalized from the raw SPI
    transaction into a parseable packet. For current-speed polling, the
    returned frame may be shifted by one byte, so we reconstruct the
    CURRENT_SPEED prefix before it is queued.
    """

    def __init__(
        self,
        bus: int = 0,
        device: int = 0,
        max_speed_hz: int = 500_000,
        mode: int = 0,
        read_length: int = 3,
    ):
        self.bus = bus
        self.device = device
        self.max_speed_hz = max_speed_hz
        self.mode = mode
        self.read_length = read_length
        self._spi = None
        self._inbox: List[bytes] = []

    def open(self) -> None:
        import spidev  # lazy
        self._spi = spidev.SpiDev()
        self._spi.open(self.bus, self. device)
        self._spi.max_speed_hz = self.max_speed_hz
        self._spi.mode = self.mode

    def close(self) -> None:
        if self._spi is not None:
            self._spi.close()
            self._spi = None

    def send(self, data: bytes) -> None:
        if self._spi is None:
            raise RuntimeError("SPI transport not open")
        raw = bytes(self._spi.xfer2(list(data)))
        response = _normalize_spi_response(data, raw)
        if response is not None and any(response):
            self._inbox.append(response)

    def read(self) -> List[bytes]:
        if self._spi is None:
            return []
        out = self._inbox
        self._inbox = []
        return out


# ----- motor controller ------------------------------------------------------

class MotorController(QObject):
    """
    Typed wrapper around an SPITransport. Provides start/stop/set_speed/
    test_movement methods that build packets, and emits Qt signals for
    parsed Arduino responses via poll().
    """

    current_speed = pyqtSignal(int)
    error_received = pyqtSignal(int)
    sequence_status = pyqtSignal(int)
    raw_bytes_received = pyqtSignal(bytes)   # emitted for unrecognised packets

    def __init__(self, transport: SPITransport, parent=None):
        super().__init__(parent)
        self._transport = transport

    def open(self) -> None:
        self._transport.open()

    def close(self) -> None:
        self._transport.close()

    def start(self, speed: int) -> None:
        pkt = build_start(speed)
        print(f"[SPI TX] START  speed={speed}  raw={pkt.hex(' ')}")
        self._transport.send(pkt)

    def stop(self, stop_type: StopType = StopType.RAMP_DOWN) -> None:
        pkt = build_stop(stop_type)
        print(f"[SPI TX] STOP   type={stop_type.name}  raw={pkt.hex(' ')}")
        self._transport.send(pkt)

    def set_speed(self, speed: int) -> None:
        pkt = build_set_speed(speed)
        print(f"[SPI TX] SET_SPEED  speed={speed}  raw={pkt.hex(' ')}")
        self._transport.send(pkt)

    def test_movement(self, movement_type: int) -> None:
        pkt = build_test_movement(movement_type)
        print(f"[SPI TX] TEST_MOVEMENT  type={movement_type}  raw={pkt.hex(' ')}")
        self._transport.send(pkt)

    def request_speed(self) -> None:
        pkt = build_request_speed()
        print(f"[SPI TX] REQUEST_SPEED  raw={pkt.hex(' ')}")
        self._transport.send(pkt)

    def poll(self) -> None:
        """Request current speed, then drain pending response packets.

        Call this from a timer to keep the current-speed readout updated.
        """
        self.request_speed()
        for packet in self._transport.read():
            resp = parse_arduino_response(packet)
            if isinstance(resp, CurrentSpeed):
                print(f"[SPI RX] CURRENT_SPEED  speed={resp.speed}  raw={packet.hex(' ')}")
                self.current_speed.emit(resp.speed)
            elif isinstance(resp, ErrorResponse):
                print(f"[SPI RX] ERROR  code={resp.error_code}  raw={packet.hex(' ')}")
                self.error_received.emit(resp.error_code)
            elif isinstance(resp, SequenceStatus):
                print(f"[SPI RX] SEQ_STATUS  status={resp.status}  raw={packet.hex(' ')}")
                self.sequence_status.emit(resp.status)
            else:
                print(f"[SPI RX] UNKNOWN  raw={packet.hex(' ')}")
                self.raw_bytes_received.emit(packet)
