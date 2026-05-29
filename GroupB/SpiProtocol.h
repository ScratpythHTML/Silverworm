#pragma once

#include <Arduino.h>

// =============================================================================
// SPI message protocol — binary byte values (not ASCII)
// =============================================================================

// --- Raspberry Pi (master) → Arduino (slave) ---
namespace SpiCmd {
constexpr uint8_t kStart    = 0x01;  // 3 bytes: prefix + speedL + speedH (RPM, int16 LE)
constexpr uint8_t kStop     = 0x02;  // 2 bytes: prefix + stop type
constexpr uint8_t kSetSpeed = 0x03;  // 3 bytes: prefix + speedL + speedH (RPM, int16 LE)
constexpr uint8_t kTest     = 0x04;  // 1 byte:  prefix only
constexpr uint8_t kQuery    = 0x05;  // 1 byte:  prefix only — request feedback RPM
}  // namespace SpiCmd

namespace SpiStopType {
constexpr uint8_t kRampDown  = 0x01;  // decelerate to 0, save EEPROM on arrival
constexpr uint8_t kEmergency = 0x02;  // halt immediately, save EEPROM now
constexpr uint8_t kCutPower  = 0x03;  // cut power immediately, save EEPROM now
}  // namespace SpiStopType

namespace SpiTestType {
constexpr uint8_t kLinearWiggle = 0x01;  // ±10 mm jog
constexpr uint8_t kBldcPulse    = 0x02;  // brief spin then stop
constexpr uint8_t kLedBlink     = 0x03;  // comms check
}  // namespace SpiTestType

// --- Arduino (slave) → Raspberry Pi (master) ---
namespace SpiReply {
constexpr uint8_t kAck   = 0x03;  // 2 bytes: 0x03 + echoed command byte
constexpr uint8_t kSpeed = 0x01;  // 3 bytes: 0x01 + speedL + speedH (feedback RPM)
constexpr uint8_t kError = 0x02;  // 2 bytes: 0x02 + error code
}  // namespace SpiReply

namespace SpiErrorCode {
constexpr uint8_t kUnknownCommand         = 0x01;
constexpr uint8_t kMotorStoppedUnexpected = 0x02;
}  // namespace SpiErrorCode

// =============================================================================
// Helpers
// =============================================================================

// Returns the byte-length of a master→slave command frame.
constexpr uint8_t spiMessageLength(uint8_t prefix) {
  return (prefix == SpiCmd::kStart || prefix == SpiCmd::kSetSpeed) ? 3
       : (prefix == SpiCmd::kStop)                                  ? 2
       : (prefix == SpiCmd::kTest  || prefix == SpiCmd::kQuery)     ? 1
       : 0;
}

inline int16_t spiDecodeSpeed(uint8_t low, uint8_t high) {
  return static_cast<int16_t>(static_cast<uint16_t>(low) |
                              (static_cast<uint16_t>(high) << 8));
}

inline void spiEncodeSpeed(int16_t rpm, uint8_t& low, uint8_t& high) {
  const uint16_t raw = static_cast<uint16_t>(rpm);
  low  = static_cast<uint8_t>(raw & 0xFF);
  high = static_cast<uint8_t>((raw >> 8) & 0xFF);
}
