#include "MotorSpiHandler.h"
#include "SpiSlave.h"
#include "SpiProtocol.h"

static uint8_t  pendingStopType   = 0;
static bool     pendingStart      = false;
static int16_t  pendingStartRpm   = 0;
static bool     pendingSetSpeed   = false;
static int16_t  pendingSetSpeedRpm = 0;
static int16_t  feedbackRpm       = 0;

// ── Public API ──────────────────────────────────────────────────────────────

uint8_t motorSpiTakeStopType() {
  uint8_t t = pendingStopType;
  pendingStopType = 0;
  return t;
}

bool motorSpiTakeStartRpm(int16_t& rpm) {
  if (!pendingStart) return false;
  rpm = pendingStartRpm;
  pendingStart = false;
  return true;
}

bool motorSpiTakeSetSpeedRpm(int16_t& rpm) {
  if (!pendingSetSpeed) return false;
  rpm = pendingSetSpeedRpm;
  pendingSetSpeed = false;
  return true;
}

void motorSpiSetFeedbackRpm(int16_t rpm) {
  feedbackRpm = rpm;
}

// ── Init ────────────────────────────────────────────────────────────────────

void motorSpiBegin() {
  spiSlaveBegin();
}

// ── Command dispatch ────────────────────────────────────────────────────────

void motorSpiPoll() {
  if (!newCommand) return;

  byte command[3];
  noInterrupts();
  for (byte i = 0; i < 3; i++) command[i] = completedCommand[i];
  newCommand = false;
  interrupts();

  if (command[0] != SpiCmd::kQuery) {
    Serial.print("SPI cmd: 0x");
    Serial.println(command[0], HEX);
  }

  switch (command[0]) {

    case SpiCmd::kStart: {              
                            // 0x01 — ramp up
      pendingStartRpm = spiDecodeSpeed(command[1], command[2]);
      Serial.print(command[1]);
      Serial.print(command[2]);
      pendingStart    = true;
      setReply(SpiReply::kAck, SpiCmd::kStart, 0, 2);
      break;
    }

    case SpiCmd::kStop: {                                     // 0x02 — stop
      pendingStopType = command[1];
      setReply(SpiReply::kAck, SpiCmd::kStop, 0, 2);
      break;
    }

    case SpiCmd::kSetSpeed: {                                 // 0x03 — set speed
      pendingSetSpeedRpm = spiDecodeSpeed(command[1], command[2]);
      pendingSetSpeed    = true;
      Serial.print("SPI set speed: ");
      Serial.print(pendingSetSpeedRpm);
      Serial.println(" RPM");
      setReply(SpiReply::kAck, SpiCmd::kSetSpeed, 0, 2);
      break;
    }

    case SpiCmd::kTest: {                                     // 0x04 — test
      Serial.println("SPI test");
      setReply(SpiReply::kAck, SpiCmd::kTest, 0, 2);
      break;
    }

    case SpiCmd::kQuery: {                                    // 0x05 — query RPM
      uint8_t lo, hi;
      spiEncodeSpeed(feedbackRpm, lo, hi);
      setReply(SpiReply::kSpeed, lo, hi, 3);
      break;
    }

    default: {
      setReply(SpiReply::kError, SpiErrorCode::kUnknownCommand, 0, 2);
      break;
    }
  }
}
