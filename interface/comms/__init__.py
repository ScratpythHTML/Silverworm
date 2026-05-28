"""
Comms module: hardware transport layers.

Two protocols live here:
  - pui.py        I2C, ESP32 → RPi  (Physical UI events)
  - motor_spi.py  SPI, RPi ↔ Arduino (motor commands and responses)

The legacy transport.py (UART, MockTransport/SerialTransport) is kept
for now because parts of the existing app still import from it. It will
be removed once the GUI is fully migrated to the new SPI motor protocol.
"""

from .transport import Transport, MockTransport, SerialTransport, CommandID, build_command
from .pui import (
    DetentSize, PUIMode, DialChange, ModeSwitch, PowerToggle,
    parse_pui_message,
    PUITransport, MockPUITransport, I2CPUITransport,
    PUIListener,
)
from .motor_spi import (
    CommandPrefix, ResponsePrefix, StopType, SPEED_MAX,
    build_start, build_stop, build_set_speed, build_test_movement,
    CurrentSpeed, ErrorResponse, SequenceStatus,
    parse_arduino_response,
    SPITransport, MockSPITransport, SPIMotorTransport,
    MotorController,
)

__all__ = [
    # legacy
    "Transport", "MockTransport", "SerialTransport", "CommandID", "build_command",
    # PUI
    "DetentSize", "PUIMode", "DialChange", "ModeSwitch", "PowerToggle",
    "parse_pui_message",
    "PUITransport", "MockPUITransport", "I2CPUITransport", "PUIListener",
    # SPI motor
    "CommandPrefix", "ResponsePrefix", "StopType", "SPEED_MAX",
    "build_start", "build_stop", "build_set_speed", "build_test_movement",
    "CurrentSpeed", "ErrorResponse", "SequenceStatus", "parse_arduino_response",
    "SPITransport", "MockSPITransport", "SPIMotorTransport", "MotorController",
]
