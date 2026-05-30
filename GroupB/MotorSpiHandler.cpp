#include "MotorSpiHandler.h"
#include "SpiSlave.h"
#include "SpiProtocol.h"


static uint8_t  pendingStopType    = 0;
static bool     pendingStart       = false;
static int16_t  pendingStartRpm    = 0;
static bool     pendingSetSpeed    = false;
static int16_t  pendingSetSpeedRpm = 0;

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
  spiSetQueryRpm(rpm);  // written into ISR-accessible isrFeedbackRpm
}

// ── Init ────────────────────────────────────────────────────────────────────

void motorSpiBegin() {
  spiSlaveBegin();
  Serial.println("SPI handler ready");
}

// ── Command dispatch ────────────────────────────────────────────────────────

void motorSpiPoll() {
  byte command[3];
  if (newCommand == false) return;
  noInterrupts();
  for (byte i = 0; i < 3; i++) command[i] = completedCommand[i];
  newCommand = false;
  interrupts();

  if (command[0] != SpiCmd::kQuery) {
    Serial.print("SPI cmd: 0x");
    Serial.println(command[0], HEX);
  }

  // Replies are pre-loaded into SPDR by the ISR in SpiSlave.cpp before loop() runs.
  // This function only needs to act on the command (motor control side-effects).
  switch (command[0]) {

    case SpiCmd::kStart: {
      pendingStartRpm = command[1] | (command[2] << 8);
      pendingStart    = true;
      Serial.print("SPI start: "); Serial.print(pendingStartRpm); Serial.println(" RPM");
      break;
    }

    case SpiCmd::kStop: {
      pendingStopType = command[1];
      Serial.print("SPI stop: "); Serial.println(pendingStopType);
      break;
    }

    case SpiCmd::kSetSpeed: {
      pendingSetSpeedRpm = command[1] | (command[2] << 8);
      pendingSetSpeed    = true;
      Serial.print("SPI set speed: "); Serial.print(pendingSetSpeedRpm); Serial.println(" RPM");
      break;
    }

    case SpiCmd::kTest: {
      Serial.println("SPI test");
      break;
    }

    default:
      break;
  }
  
}
