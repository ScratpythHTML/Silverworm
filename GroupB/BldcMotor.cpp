#include <ODriveUART.h>
#include <ODriveCAN.h>

#include "BldcMotor.h"

#if !MOTORS_ENABLED

BldcMotor::BldcMotor() {}
void BldcMotor::begin() {}
void BldcMotor::poll() {}
void BldcMotor::enable(bool) {}
void BldcMotor::setSpeedRpm(int) {}
void BldcMotor::startRampTo(int) {}
void BldcMotor::rampTo(int) {}
void BldcMotor::stopImmediate() {}
void BldcMotor::cutPower() {}
void BldcMotor::stop() {}

#else  // MOTORS_ENABLED

static float rpmToTurnsPerSec(int rpm) {
  return static_cast<float>(rpm) / 60.0f;
}

static int turnsPerSecToRpm(float turnsPerSec) {
  return static_cast<int>(turnsPerSec * 60.0f);
}

BldcMotor::BldcMotor()
    : odriveSerial_(8, 9), odrive_(odriveSerial_) {}  // D8 RX, D9 TX

void BldcMotor::configureVelocityRamp() {
  const float rampTurnsPerSec2 =
      static_cast<float>(SPI_SPEED_RAMP_RPM_S) / 60.0f;

  odrive_.setParameter(F("axis0.controller.config.control_mode"),
                       String(CONTROL_MODE_VELOCITY_CONTROL));
  odrive_.setParameter(F("axis0.controller.config.input_mode"),
                       String(INPUT_MODE_VEL_RAMP));
  odrive_.setParameter(F("axis0.controller.config.vel_ramp_rate"),
                       String(rampTurnsPerSec2, 4));
}

void BldcMotor::ensureClosedLoop() {
  odrive_.clearErrors();
  for (uint8_t attempt = 0; attempt < 50; ++attempt) {
    if (odrive_.getState() == AXIS_STATE_CLOSED_LOOP_CONTROL) {
      return;
    }
    odrive_.setState(AXIS_STATE_CLOSED_LOOP_CONTROL);
    delay(10);
  }
}

void BldcMotor::applyTargetVelocity() {
  if (!armed_) {
    fault_ = true;
    return;
  }

  // odrive_.setVelocity(rpmToTurnsPerSec(targetRpm_));  
  odrive_.setVelocity(targetRpm_);  
  Serial.print("odrive.setVelocity "); // debug.. remove later.
  Serial.println(targetRpm_);
  fault_ = false;
}

void BldcMotor::begin() {
  odriveSerial_.begin(ODRIVE_BAUD);
  delay(50);

  armed_ = false;
  fault_ = false;
  targetRpm_ = 0;
  currentRpm_ = 0;
  feedbackRpm_ = 0;
  lastFeedbackMs_ = 0;

  configureVelocityRamp();
  ensureClosedLoop();
  odrive_.setVelocity(0.0f);

  armed_ = true;
  fault_ = false;
}

void BldcMotor::setSpeedRpm(int rpm) {
  targetRpm_ = constrain(rpm, -BLDC_RATED_RPM, BLDC_RATED_RPM);
  applyTargetVelocity();
}

void BldcMotor::startRampTo(int rpm) {
  if (!armed_) {
    enable(true);
  }
  Serial.print("BLDC: startRampTo ");
  Serial.println(rpm);
  targetRpm_ = constrain(rpm, -BLDC_RATED_RPM, BLDC_RATED_RPM);
  applyTargetVelocity();
}

void BldcMotor::stopImmediate() {
  targetRpm_ = 0;
  if (armed_) {
    odrive_.setVelocity(0.0f);
  }
}

void BldcMotor::cutPower() {
  stopImmediate();
  armed_ = false;
}

void BldcMotor::stop() { startRampTo(0); }

void BldcMotor::enable(bool on) {
  if (on) {
    configureVelocityRamp();
    ensureClosedLoop();
    armed_ = true;
    fault_ = false;
    applyTargetVelocity();
  } else {
    cutPower();
  }
}

void BldcMotor::poll() {
  const unsigned long now = millis();
  if (now - lastFeedbackMs_ < ODRIVE_FEEDBACK_INTERVAL_MS) {
    return;
  }
  lastFeedbackMs_ = now;

  const ODriveFeedback feedback = odrive_.getFeedback();
  feedbackRpm_ = feedback.vel;
  currentRpm_ = feedbackRpm_;

  // 1-second moving average (kAvgLen slots, updated every ODRIVE_FEEDBACK_INTERVAL_MS)
  velBufSum_ -= velBuf_[velBufIdx_];
  velBuf_[velBufIdx_] = feedbackRpm_;
  velBufSum_ += feedbackRpm_;
  velBufIdx_ = (velBufIdx_ + 1) % kAvgLen;
  smoothedRpm_ = static_cast<int>(velBufSum_ / kAvgLen);

  Serial.print(F("cmd=")); Serial.print(targetRpm_);
  Serial.print(F(" rpm  pos=")); Serial.print(feedback.pos, 3);
  Serial.print(F("  vel=")); Serial.print(feedback.vel, 3);
  Serial.println(F(" turns/s"));

  if (armed_ && targetRpm_ != 0) {
    const ODriveAxisState state = odrive_.getState();
    fault_ = (state == AXIS_STATE_UNDEFINED ||
              state != AXIS_STATE_CLOSED_LOOP_CONTROL);
  } else {
    fault_ = false;
  }
}

#endif  // MOTORS_ENABLED
