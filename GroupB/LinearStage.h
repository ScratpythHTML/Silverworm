#pragma once

#include <Arduino.h>
#include "config.h"

class LinearStage {
public:
  void begin();
  void poll();  // Call every loop(); runs non-blocking motion

  void setStrokeMm(float strokeMm);
  float strokeMm() const { return strokeMm_; }

  void moveMm(float deltaMm);
  void moveToMm(float positionMm);
  void jogMm(float deltaMm);  // Ignores soft limits (use with care)

  void setMaxSpeedMmS(float mmPerS);
  void setMaxAccelMmS2(float mmPerS2);

  void stop();
  void enable(bool on);
  bool isEnabled() const { return enabled_; }
  bool isMoving() const;

  float positionMm() const;
  long positionSteps() const { return currentSteps_; }

  void setPositionMm(float mm);  // Zero / calibrate without motion
  void homeToMin();              // Requires LINEAR_LIMIT_MIN_PIN wired; blocks until done or timeout

  float stepsPerMm() const;

private:
  void stepOnce(int dir);
  void planMove(long targetSteps);
  bool updateMotion();

  float strokeMm_ = LINEAR_STROKE_MM_DEFAULT;
  float maxSpeedStepsPerS_ = 0;
  float maxAccelStepsPerS2_ = 0;

  long currentSteps_ = 0;
  long targetSteps_ = 0;
  long startSteps_ = 0;

  float speedStepsPerS_ = 0;
  float accelStepsPerS2_ = 0;
  uint32_t segmentStartUs_ = 0;
  float segmentDurationS_ = 0;

  bool enabled_ = false;
  bool moving_ = false;
  bool homing_ = false;
};
