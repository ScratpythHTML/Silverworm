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
    START = 0x31          # Arduino switch uses case '1' (ASCII)
    STOP = 0x32           # case '2'
    SET_SPEED = 0x33      # case '3'
    TEST_MOVEMENT = 0x34  # case '4'


class ResponsePrefix(IntEnum):
    CURRENT_SPEED = 0x31   # Arduino setReply('1', ...)
    ERROR = 0x32           # setReply('2', ...)
    SEQUENCE_STATUS = 0x33 # setReply('3', ...)


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

    Response framing: the Arduino pushes a reply into SPDR during the
    same ISR that receives a command. The RPi reads the reply by clocking
    three zero bytes immediately after sending. No data-ready GPIO is
    used; the assumption is that the reply is always ready for the next
    transaction after a command is sent.
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
        response = bytes(self._spi.xfer2(list(data)))
        if parse_arduino_response(response) is not None:
            self._inbox.append(response)

    def read(self) -> List[bytes]:
        if self._spi is None:
            return []

        response = bytes(self._spi.xfer2([0] * self.read_length))
        if parse_arduino_response(response) is not None:
            self._inbox.append(response)

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

    def __init__(self, transport: SPITransport, parent=None):
        super().__init__(parent)
        self._transport = transport

    def open(self) -> None:
        self._transport.open()

    def close(self) -> None:
        self._transport.close()

    def start(self, speed: int) -> None:
        self._transport.send(build_start(speed))

    def stop(self, stop_type: StopType = StopType.RAMP_DOWN) -> None:
        self._transport.send(build_stop(stop_type))

    def set_speed(self, speed: int) -> None:
        self._transport.send(build_set_speed(speed))

    def test_movement(self, movement_type: int) -> None:
        self._transport.send(build_test_movement(movement_type))

    def poll(self) -> None:
        """Drain pending response packets and emit signals. Call from a timer."""
        for packet in self._transport.read():
            resp = parse_arduino_response(packet)
            if isinstance(resp, CurrentSpeed):
                self.current_speed.emit(resp.speed)
            elif isinstance(resp, ErrorResponse):
                self.error_received.emit(resp.error_code)
            elif isinstance(resp, SequenceStatus):
                self.sequence_status.emit(resp.status)
