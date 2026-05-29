#include "LinearStage.h"

void LinearStage::begin() {
  pinMode(LINEAR_STEP_PIN, OUTPUT);
  pinMode(LINEAR_DIR_PIN, OUTPUT);
  pinMode(LINEAR_ENABLE_PIN, OUTPUT);
  digitalWrite(LINEAR_STEP_PIN, LOW);

#if LINEAR_LIMIT_MIN_PIN >= 0
  pinMode(LINEAR_LIMIT_MIN_PIN, INPUT_PULLUP);
#endif
#if LINEAR_LIMIT_MAX_PIN >= 0
  pinMode(LINEAR_LIMIT_MAX_PIN, INPUT_PULLUP);
#endif

  setMaxSpeedMmS(LINEAR_MAX_SPEED_MM_S);
  setMaxAccelMmS2(LINEAR_MAX_ACCEL_MM_S2);
  enable(false);
}

float LinearStage::stepsPerMm() const {
  const float stepsPerRev =
      static_cast<float>(LINEAR_FULL_STEPS_PER_REV * LINEAR_MICROSTEPS);
  return stepsPerRev / LINEAR_SCREW_LEAD_MM;
}

void LinearStage::setStrokeMm(float strokeMm) {
  strokeMm_ = (strokeMm < 0.0f) ? 0.0f : strokeMm;
}

void LinearStage::setMaxSpeedMmS(float mmPerS) {
  maxSpeedStepsPerS_ = mmPerS * stepsPerMm();
}

void LinearStage::setMaxAccelMmS2(float mmPerS2) {
  maxAccelStepsPerS2_ = mmPerS2 * stepsPerMm();
}

float LinearStage::positionMm() const {
  return static_cast<float>(currentSteps_) / stepsPerMm();
}

void LinearStage::setPositionMm(float mm) {
  currentSteps_ = lroundf(mm * stepsPerMm());
  targetSteps_ = currentSteps_;
  moving_ = false;
}

void LinearStage::enable(bool on) {
  enabled_ = on;
#if LINEAR_ENABLE_ACTIVE_LOW
  digitalWrite(LINEAR_ENABLE_PIN, on ? LOW : HIGH);
#else
  digitalWrite(LINEAR_ENABLE_PIN, on ? HIGH : LOW);
#endif
}

bool LinearStage::isMoving() const { return moving_; }

void LinearStage::stop() {
  targetSteps_ = currentSteps_;
  moving_ = false;
  homing_ = false;
  speedStepsPerS_ = 0;
}

void LinearStage::stepOnce(int dir) {
  digitalWrite(LINEAR_DIR_PIN, dir > 0 ? HIGH : LOW);
  digitalWrite(LINEAR_STEP_PIN, HIGH);
  delayMicroseconds(2);
  digitalWrite(LINEAR_STEP_PIN, LOW);
  currentSteps_ += dir;
}

void LinearStage::planMove(long targetSteps) {
  const long minSteps = 0;
  const long maxSteps = lroundf(strokeMm_ * stepsPerMm());
  targetSteps = constrain(targetSteps, minSteps, maxSteps);

  const long delta = targetSteps - currentSteps_;
  if (delta == 0) {
    moving_ = false;
    return;
  }

  targetSteps_ = targetSteps;
  startSteps_ = currentSteps_;
  moving_ = true;

  const float dist = fabsf(static_cast<float>(delta));
  const float tReachMax =
      maxSpeedStepsPerS_ / maxAccelStepsPerS2_;
  const float dReachMax =
      0.5f * maxAccelStepsPerS2_ * tReachMax * tReachMax;

  if (dist <= 2.0f * dReachMax) {
  // Triangular profile
    segmentDurationS_ =
        2.0f * sqrtf(dist / maxAccelStepsPerS2_);
    speedStepsPerS_ = maxAccelStepsPerS2_ * (segmentDurationS_ * 0.5f);
  } else {
  // Trapezoidal profile
    const float tCruise =
        (dist - 2.0f * dReachMax) / maxSpeedStepsPerS_;
    segmentDurationS_ = 2.0f * tReachMax + tCruise;
    speedStepsPerS_ = maxSpeedStepsPerS_;
  }

  segmentStartUs_ = micros();
}

void LinearStage::moveMm(float deltaMm) {
  if (!enabled_) enable(true);
  planMove(currentSteps_ + lroundf(deltaMm * stepsPerMm()));
}

void LinearStage::moveToMm(float positionMm) {
  if (!enabled_) enable(true);
  planMove(lroundf(positionMm * stepsPerMm()));
}

void LinearStage::jogMm(float deltaMm) {
  if (!enabled_) enable(true);
  targetSteps_ = currentSteps_ + lroundf(deltaMm * stepsPerMm());
  startSteps_ = currentSteps_;
  moving_ = true;
  speedStepsPerS_ = maxSpeedStepsPerS_;
  segmentDurationS_ =
      fabsf(static_cast<float>(targetSteps_ - currentSteps_)) / speedStepsPerS_;
  segmentStartUs_ = micros();
}

bool LinearStage::updateMotion() {
  if (!moving_) return false;

  const int dir = (targetSteps_ > currentSteps_) ? 1 : -1;
  const long remaining = labs(targetSteps_ - currentSteps_);

  if (remaining == 0) {
    moving_ = false;
    homing_ = false;
    return false;
  }

  const float elapsedS =
      static_cast<float>(micros() - segmentStartUs_) * 1e-6f;
  (void)elapsedS;

  // Trapezoid: ramp up first half of accel region, cruise, ramp down
  const long totalDelta = labs(targetSteps_ - startSteps_);
  const long traveled = labs(currentSteps_ - startSteps_);
  const float fracDone =
      totalDelta > 0 ? static_cast<float>(traveled) / totalDelta : 1.0f;

  float instSpeed = speedStepsPerS_;
  if (fracDone < 0.01f) {
    instSpeed = maxAccelStepsPerS2_ * elapsedS;
  } else if (fracDone > 0.99f) {
    // Distance-based decel: v = sqrt(2 * a * remaining) — immune to time drift
    const float remainingSteps = static_cast<float>(labs(targetSteps_ - currentSteps_));
    instSpeed = sqrtf(2.0f * maxAccelStepsPerS2_ * remainingSteps);
  }
  instSpeed = constrain(instSpeed, maxSpeedStepsPerS_ * 0.05f, maxSpeedStepsPerS_);

  const unsigned long intervalUs =
      static_cast<unsigned long>(1e6f / instSpeed);
  static unsigned long lastStepUs = 0;
  const unsigned long now = micros();
  if (now - lastStepUs >= intervalUs) {
    lastStepUs = now;
    stepOnce(dir);
  }

  if (currentSteps_ == targetSteps_) {
    moving_ = false;
    homing_ = false;
  }
  return moving_;
}

void LinearStage::poll() {
#if LINEAR_LIMIT_MIN_PIN >= 0
  if (digitalRead(LINEAR_LIMIT_MIN_PIN) == LOW && homing_) {
    setPositionMm(0);
    stop();
  }
#endif
  updateMotion();
}

void LinearStage::homeToMin() {
#if LINEAR_LIMIT_MIN_PIN < 0
  return;
#endif
  enable(true);
  homing_ = true;
  moving_ = true;
  targetSteps_ = -1000000L;
  startSteps_ = currentSteps_;
  speedStepsPerS_ = maxSpeedStepsPerS_ * 0.25f;
  segmentDurationS_ = 60.0f;
  segmentStartUs_ = micros();
}
