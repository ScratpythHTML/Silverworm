#include <EEPROM.h>
#include "MotorSpiHandler.h"
#include "LinearStage.h"
#include "BldcMotor.h"
#include "SpiProtocol.h"

// EEPROM layout: [0..3] last known position (float), [4..7] current target (float)
#define EEPROM_POS_ADDR    0
#define EEPROM_TARGET_ADDR 4

// Fixed oscillation endpoints (mm)
#define POS_A 30.0f
#define POS_B 70.0f

// How often to snapshot position to EEPROM while moving.
// At 1 s the worst-case error on power loss is 1 s × speed mm.
#define EEPROM_SAVE_INTERVAL_MS 1000UL

LinearStage stage;
BldcMotor   bldc;

// ── State machine ─────────────────────────────────────────────────────────────
enum class MotorState : uint8_t {
  OSCILLATING,  // normal 30 ↔ 70 loop
  RAMP_DOWN,    // decelerating to 0, will save EEPROM on arrival
  STOPPED       // halted after any stop command
};
MotorState motorState = MotorState::OSCILLATING;

// ── EEPROM helpers ────────────────────────────────────────────────────────────
float loadFloat(int addr, float fallback) {
  float val;
  EEPROM.get(addr, val);
  if (isnan(val) || isinf(val)) return fallback;
  return val;
}

void saveFloat(int addr, float val) {
  float stored;
  EEPROM.get(addr, stored);
  if (stored != val) EEPROM.put(addr, val);  // only write on change — preserves ~100 k cycle life
}

// ── Globals ───────────────────────────────────────────────────────────────────
float targetPos;
bool  wasMoving        = false;
unsigned long lastPosSaveMs = 0;
unsigned long lastPrintMs   = 0;

void setup() {
  Serial.begin(115200);
  motorSpiBegin();

  stage.begin();
  stage.setStrokeMm(96.0f);
  stage.setMaxSpeedMmS(15.0f);
  stage.setMaxAccelMmS2(20.0f);
  stage.enable(true);

  bldc.begin();

  // Restore last known position
  float lastPos = loadFloat(EEPROM_POS_ADDR, POS_A);
  if (lastPos < 0.0f || lastPos > stage.strokeMm()) lastPos = POS_A;
  stage.setPositionMm(lastPos);

  // Restore which endpoint we were heading to; continue toward it on restart
  targetPos = loadFloat(EEPROM_TARGET_ADDR, POS_B);
  if (targetPos != POS_A && targetPos != POS_B) {
    // Fallback: head to whichever endpoint is further away
    targetPos = (lastPos <= (POS_A + POS_B) * 0.5f) ? POS_B : POS_A;
  }

  stage.moveToMm(targetPos);
  wasMoving = true;

  Serial.print("Restored pos: ");
  Serial.print(lastPos, 1);
  Serial.print(" mm -> continuing to: ");
  Serial.print(targetPos, 1);
  Serial.println(" mm  [oscillating 30 <-> 70]");
}

void loop() {
  motorSpiPoll();
  stage.poll();
  bldc.poll();
  motorSpiSetFeedbackRpm(bldc.feedbackRpm());

  // ── SPI commands (normal path) ────────────────────────────────────────────
  uint8_t stopType = motorSpiTakeStopType();

  int16_t spiRpm = 0;
  if (motorSpiTakeStartRpm(spiRpm)) {
    bldc.enable(true);
    bldc.startRampTo(spiRpm);
    if (motorState == MotorState::STOPPED) {
      motorState = MotorState::OSCILLATING;
      wasMoving  = true;
      stage.moveToMm(targetPos);
    }
    Serial.print("SPI Start: BLDC -> ");
    Serial.print(spiRpm);
    Serial.println(" RPM");
  }
  if (motorSpiTakeSetSpeedRpm(spiRpm)) {
    bldc.startRampTo(spiRpm);
    Serial.print("SPI SetSpeed: BLDC -> ");
    Serial.print(spiRpm);
    Serial.println(" RPM");
  }

  // ── Serial test interface ─────────────────────────────────────────────────
  // Simulate any SpiCmd over Serial Monitor:
  //   s          → kStart (0x01)   resume oscillation; also re-arms BLDC
  //   v <mm/s>   → linear max speed  e.g. "v 25"
  //   t <1|2|3>  → kTest (0x04)   1=LinearWiggle  2=BldcPulse  3=LedBlink
  //   1          → kStop kRampDown  (0x02/0x01) go to 0, save EEPROM on arrival
  //   2          → kStop kEmergency (0x02/0x02) halt now, save EEPROM
  //   3          → kStop kCutPower  (0x02/0x03) halt now, save EEPROM
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      char cmd = static_cast<char>(line[0]);

      if (cmd == 's' || cmd == 'S') {                         // kStart
        if (motorState == MotorState::STOPPED) {
          motorState = MotorState::OSCILLATING;
          wasMoving  = true;
          stage.moveToMm(targetPos);
          Serial.print("Start -> resuming to ");
          Serial.print(targetPos, 1);
          Serial.println(" mm");
        } else {
          Serial.println("Already running");
        }

      } else if (cmd == 'v' || cmd == 'V') {                  // kSetSpeed
        float spd = line.substring(1).toFloat();
        if (spd > 0.0f) {
          stage.setMaxSpeedMmS(spd);
          Serial.print("Speed -> ");
          Serial.print(spd, 1);
          Serial.println(" mm/s");
        } else {
          Serial.println("Usage: v <mm/s>  e.g. v 25");
        }

      } else if (cmd == 't' || cmd == 'T') {                  // kTest
        String sub = line.substring(1);
        sub.trim();
        uint8_t testType = static_cast<uint8_t>(sub.toInt());
        switch (testType) {
          case SpiTestType::kLinearWiggle:
            Serial.println("Test: LinearWiggle");
            stage.jogMm(10.0f);
            break;
          case SpiTestType::kBldcPulse:
            bldc.startRampTo(200);
            Serial.println("Test: BldcPulse -> 200 RPM (send 2 to stop)");
            break;
          case SpiTestType::kLedBlink:
            Serial.println("Test: LedBlink (stub)");
            break;
          default:
            Serial.println("Usage: t <1|2|3>  1=LinearWiggle 2=BldcPulse 3=LedBlink");
            break;
        }

      } else if (cmd >= '1' && cmd <= '3') {                  // kStop subtypes
        // Map ASCII digit to binary stop type: '1'→0x01, '2'→0x02, '3'→0x03
        stopType = static_cast<uint8_t>(cmd - '0');
      }
    }
  }

  // ── Stop command handler (SPI or Serial) ──────────────────────────────────
  if (stopType != 0) {
    switch (stopType) {

      case SpiStopType::kRampDown:
        motorState = MotorState::RAMP_DOWN;
        wasMoving  = true;
        stage.moveToMm(0.0f);
        Serial.println("Ramp down -> moving to 0 mm");
        break;

      case SpiStopType::kEmergency:
      case SpiStopType::kCutPower:
        stage.stop();
        motorState = MotorState::STOPPED;
        saveFloat(EEPROM_POS_ADDR,    stage.positionMm());
        saveFloat(EEPROM_TARGET_ADDR, targetPos);
        Serial.print("Stopped at ");
        Serial.print(stage.positionMm(), 1);
        Serial.println(" mm - EEPROM saved");
        break;
    }
  }

  // ── State machine ──────────────────────────────────────────────────────────
  bool moving = stage.isMoving();

  switch (motorState) {

    case MotorState::OSCILLATING:
      // Periodic position snapshot for mid-move power-loss recovery
      if (millis() - lastPosSaveMs >= EEPROM_SAVE_INTERVAL_MS) {
        lastPosSaveMs = millis();
        saveFloat(EEPROM_POS_ADDR, stage.positionMm());
      }
      // Arrived at endpoint → flip to the other side
      if (!moving && wasMoving) {
        targetPos = (targetPos == POS_B) ? POS_A : POS_B;
        saveFloat(EEPROM_POS_ADDR,    stage.positionMm());  // exact turnaround position
        saveFloat(EEPROM_TARGET_ADDR, targetPos);
        stage.moveToMm(targetPos);
        wasMoving = false;
        Serial.print("Reached end -> moving to ");
        Serial.print(targetPos, 1);
        Serial.println(" mm");
      } else {
        wasMoving = moving;
      }
      break;

    case MotorState::RAMP_DOWN:
      // Wait until position 0 is reached, then save and halt
      if (!moving && wasMoving) {
        saveFloat(EEPROM_POS_ADDR,    stage.positionMm());  // ≈ 0 mm
        saveFloat(EEPROM_TARGET_ADDR, targetPos);           // resume direction on next start
        motorState = MotorState::STOPPED;
        wasMoving  = false;
        Serial.println("Reached 0 mm - EEPROM saved, motor stopped");
      } else {
        wasMoving = moving;
      }
      break;

    case MotorState::STOPPED:
      break;  // waiting for power cycle / restart
  }

  // ── Progress print ─────────────────────────────────────────────────────────
  if (moving && millis() - lastPrintMs >= 500UL) {
    lastPrintMs = millis();
    Serial.print("pos: ");
    Serial.print(stage.positionMm(), 1);
    Serial.print(" mm  target: ");
    Serial.println(targetPos, 1);
  }
}
