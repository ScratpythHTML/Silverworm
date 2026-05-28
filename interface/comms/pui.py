"""
Physical UI (PUI) communication layer — I2C from ESP32 to Raspberry Pi.

The PUI panel is an ESP32 (slave, address 0x55) that talks to the Pi over
I2C and sends short ASCII messages:

    D1±N   — dial 1 changed by N detents (N ∈ {1,2,3} = small/medium/large)
    D2±N   — dial 2 changed by N detents
    AS0    — mode switch to MANUAL
    AS1    — mode switch to AUTO
    TP     — toggle machine power state

The ESP32 also receives status from the Pi:
    ON     — machine started (lights power-button LED)
    OFF    — machine stopped (dims power-button LED)

This module provides:
    - PUIMessage dataclasses (DialChange, ModeSwitch, PowerToggle)
    - parse_pui_message(text) — pure parser, no I/O
    - PUITransport ABC + MockPUITransport (tests) + I2CPUITransport (Pi)
    - PUIListener (Qt) — polls a transport, emits typed signals, proxies send_status
"""

from __future__ import annotations

import re
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Union

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


# ----- enums + message types -------------------------------------------------

class DetentSize(Enum):
    SMALL = 1
    MEDIUM = 2
    LARGE = 3


class PUIMode(Enum):
    MANUAL = 0
    AUTO = 1


@dataclass(frozen=True)
class DialChange:
    dial: int           # 1 (wrap) or 2 (feed)
    direction: int      # +1 or -1
    size: DetentSize


@dataclass(frozen=True)
class ModeSwitch:
    mode: PUIMode


@dataclass(frozen=True)
class PowerToggle:
    pass


PUIMessage = Union[DialChange, ModeSwitch, PowerToggle]


# ----- parser ----------------------------------------------------------------

_DIAL_RE = re.compile(r"^D([12])([+-])([123])$")


def parse_pui_message(text: str) -> Optional[PUIMessage]:
    """
    Parse one PUI ASCII message. Returns the typed message or None for
    malformed input. Whitespace is stripped; everything else must match
    exactly.
    """
    s = text.strip()
    if not s:
        return None

    if s == "TP":
        return PowerToggle()
    if s == "AS0":
        return ModeSwitch(PUIMode.MANUAL)
    if s == "AS1":
        return ModeSwitch(PUIMode.AUTO)

    m = _DIAL_RE.match(s)
    if m:
        dial = int(m.group(1))
        sign = +1 if m.group(2) == "+" else -1
        size = DetentSize(int(m.group(3)))
        return DialChange(dial=dial, direction=sign, size=size)

    return None


# ----- transport abstraction -------------------------------------------------

class PUITransport(ABC):
    """Abstract I2C-like transport. Returns raw ASCII messages."""

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def read_messages(self) -> List[str]:
        """Return any ASCII messages received since the previous call.
        Non-blocking; returns an empty list if nothing is pending."""

    @abstractmethod
    def send_status(self, text: str) -> None:
        """Send a short status string to the PUI (e.g. 'ON' or 'OFF').
        Non-blocking; silently drops if transport is not open."""


class MockPUITransport(PUITransport):
    """In-memory transport. Tests call inject() to enqueue messages."""

    def __init__(self):
        self._queue: List[str] = []
        self._lock = threading.Lock()
        self._open = False
        self.status_sent: List[str] = []  # records send_status calls for tests

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def inject(self, message: str) -> None:
        with self._lock:
            self._queue.append(message)

    def read_messages(self) -> List[str]:
        with self._lock:
            out = self._queue
            self._queue = []
        return out

    def send_status(self, text: str) -> None:
        with self._lock:
            self.status_sent.append(text)


class I2CPUITransport(PUITransport):
    """
    Real I2C transport via smbus2. Lazy-imported so dev machines without
    smbus2 can still load this module.

    ESP32 acts as I2C slave (address 0x55). The RPi polls by doing a
    read request; the ESP32 responds via Wire.onRequest() with a
    null-terminated ASCII command string (e.g. "TP\0").

    The RPi sends status back via a plain write (no register prefix) so
    the ESP32's Wire.onReceive() fires with the exact string bytes.
    """

    def __init__(
        self,
        bus_number: int = 1,
        address: int = 0x55,
        read_length: int = 32,
    ):
        self.bus_number = bus_number
        self.address = address
        self.read_length = read_length
        self._bus = None
        self._buffer = ""

    def open(self) -> None:
        import smbus2  # lazy
        self._bus = smbus2.SMBus(self.bus_number)

    def close(self) -> None:
        if self._bus is not None:
            self._bus.close()
            self._bus = None

    def read_messages(self) -> List[str]:
        if self._bus is None:
            return []
        try:
            chunk = self._bus.read_i2c_block_data(self.address, 0, self.read_length)
        except OSError:
            return []
        # Keep null bytes (0x00) — they are the ESP32's message terminator.
        # Strip only non-ASCII bytes (>127).
        raw = bytes(b for b in chunk if b < 128)
        text = raw.decode("ascii", errors="ignore")
        self._buffer += text
        parts = re.split(r"[\r\n\x00,;]+", self._buffer)
        # Last fragment may be incomplete; keep in buffer until next read.
        self._buffer = parts[-1]
        return [p for p in parts[:-1] if p]

    def send_status(self, text: str) -> None:
        """Write a status string to the ESP32 (plain I2C write, no register)."""
        if self._bus is None:
            return
        try:
            from smbus2 import i2c_msg  # lazy — same package as smbus2
            msg = i2c_msg.write(self.address, list(text.encode("ascii")))
            self._bus.i2c_rdwr(msg)
        except OSError:
            pass


# ----- Qt listener -----------------------------------------------------------

class PUIListener(QObject):
    """
    Polls a PUITransport on a Qt timer and emits typed signals for each
    parsed message. Lives on the GUI thread; AppState connects to its
    signals directly.
    """

    dial_changed = pyqtSignal(object)    # DialChange
    mode_switched = pyqtSignal(object)   # ModeSwitch
    power_toggled = pyqtSignal()
    raw_message = pyqtSignal(str)        # for logging/debug panel
    parse_error = pyqtSignal(str)
    hardware_unavailable = pyqtSignal(str)  # emitted when open() fails

    def __init__(
        self,
        transport: PUITransport,
        poll_interval_ms: int = 50,
        parent=None,
    ):
        super().__init__(parent)
        self._transport = transport
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        try:
            self._transport.open()
        except Exception as e:
            self.hardware_unavailable.emit(str(e))
            # Still start the poll timer — read_messages() returns [] safely
            # when the transport is not open, so we can reconnect later.
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        try:
            self._transport.close()
        except Exception:
            pass

    def send_status(self, text: str) -> None:
        """Forward a status string to the ESP32 (e.g. 'ON' or 'OFF')."""
        self._transport.send_status(text)

    def _poll(self) -> None:
        for raw in self._transport.read_messages():
            self.raw_message.emit(raw)
            msg = parse_pui_message(raw)
            if msg is None:
                self.parse_error.emit(raw)
                continue
            if isinstance(msg, DialChange):
                self.dial_changed.emit(msg)
            elif isinstance(msg, ModeSwitch):
                self.mode_switched.emit(msg)
            elif isinstance(msg, PowerToggle):
                self.power_toggled.emit()
