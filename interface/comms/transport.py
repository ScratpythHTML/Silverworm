"""
Transport abstraction and command protocol for motor controller comms.

Packet format (minimal for MVP):
    [START_BYTE] [CMD_ID] [PAYLOAD_LEN] [PAYLOAD...] [CHECKSUM]

    START_BYTE  = 0xAA
    CMD_ID      = 1 byte (see CommandID)
    PAYLOAD_LEN = 1 byte (0-255)
    PAYLOAD     = PAYLOAD_LEN bytes
    CHECKSUM    = XOR of all bytes from CMD_ID through last PAYLOAD byte

Speed payload encoding:
    speed_a (float32 LE, 4 bytes) + speed_b (float32 LE, 4 bytes) = 8 bytes
"""

import struct
from abc import ABC, abstractmethod
from enum import IntEnum
from typing import List, Optional
from dataclasses import dataclass, field


START_BYTE = 0xAA


class CommandID(IntEnum):
    SET_SPEEDS = 0x01
    START = 0x02
    STOP = 0x03
    PAUSE = 0x04


def _xor_checksum(data: bytes) -> int:
    """XOR checksum over data bytes."""
    cs = 0
    for b in data:
        cs ^= b
    return cs


def build_command(cmd_id: CommandID, payload: bytes = b"") -> bytes:
    """
    Build a framed command packet.

    Returns bytes: [0xAA] [cmd_id] [payload_len] [payload...] [checksum]
    """
    payload_len = len(payload)
    if payload_len > 255:
        raise ValueError(f"Payload too long: {payload_len} bytes (max 255)")

    inner = bytes([cmd_id, payload_len]) + payload
    checksum = _xor_checksum(inner)
    return bytes([START_BYTE]) + inner + bytes([checksum])


def build_set_speeds_command(speed_a: float, speed_b: float) -> bytes:
    """Build a SET_SPEEDS command with two float32 values."""
    payload = struct.pack("<ff", speed_a, speed_b)
    return build_command(CommandID.SET_SPEEDS, payload)


# ---------------------------------------------------------------------------
# Transport interface
# ---------------------------------------------------------------------------

class Transport(ABC):
    """Abstract transport layer for sending commands to motor controller."""

    @abstractmethod
    def open(self):
        """Open the transport connection."""

    @abstractmethod
    def close(self):
        """Close the transport connection."""

    @abstractmethod
    def send(self, data: bytes):
        """Send raw bytes over the transport."""

    @abstractmethod
    def is_open(self) -> bool:
        """Return True if transport is currently open."""

    def send_command(self, cmd_id: CommandID, payload: bytes = b""):
        """Build and send a framed command."""
        packet = build_command(cmd_id, payload)
        self.send(packet)

    def send_speeds(self, speed_a: float, speed_b: float):
        """Convenience: build and send a SET_SPEEDS command."""
        packet = build_set_speeds_command(speed_a, speed_b)
        self.send(packet)


# ---------------------------------------------------------------------------
# MockTransport — for unit testing
# ---------------------------------------------------------------------------

class MockTransport(Transport):
    """
    Records all sent data for assertions in tests.
    No actual hardware communication.
    """

    def __init__(self):
        self._open = False
        self.sent_packets: List[bytes] = []

    def open(self):
        self._open = True

    def close(self):
        self._open = False

    def send(self, data: bytes):
        if not self._open:
            raise IOError("MockTransport is not open")
        self.sent_packets.append(data)

    def is_open(self) -> bool:
        return self._open

    def clear(self):
        """Clear recorded packets."""
        self.sent_packets.clear()

    def last_packet(self) -> Optional[bytes]:
        """Return the most recently sent packet, or None."""
        return self.sent_packets[-1] if self.sent_packets else None

    def decode_last_speeds(self) -> Optional[tuple]:
        """
        Decode the last SET_SPEEDS packet into (speed_a, speed_b).
        Returns None if no packets or last packet isn't SET_SPEEDS.
        """
        pkt = self.last_packet()
        if pkt is None or len(pkt) < 4:
            return None
        # pkt: [0xAA] [cmd] [len] [payload...] [checksum]
        cmd = pkt[1]
        if cmd != CommandID.SET_SPEEDS:
            return None
        payload_len = pkt[2]
        payload = pkt[3 : 3 + payload_len]
        if len(payload) != 8:
            return None
        return struct.unpack("<ff", payload)


# ---------------------------------------------------------------------------
# SerialTransport — UART via pyserial (MVP hardware transport)
# ---------------------------------------------------------------------------

class SerialTransport(Transport):
    """
    UART transport using pyserial.

    Usage:
        transport = SerialTransport(port="/dev/ttyUSB0", baudrate=115200)
        transport.open()
        transport.send_speeds(1.0, 1000.0)
        transport.close()
    """

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self._serial = None

    def open(self):
        try:
            import serial
        except ImportError:
            raise ImportError(
                "pyserial is required for SerialTransport. "
                "Install with: pip install pyserial"
            )
        self._serial = serial.Serial(self.port, self.baudrate, timeout=1)

    def close(self):
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def send(self, data: bytes):
        if self._serial is None or not self._serial.is_open:
            raise IOError("Serial port is not open")
        self._serial.write(data)

    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open
