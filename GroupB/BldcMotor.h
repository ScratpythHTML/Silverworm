#pragma once

#include <Arduino.h>
#include "config.h"

#if MOTORS_ENABLED
#include <SoftwareSerial.h>
#include <ODriveUART.h>
#endif

// Collecting-spool BLDC (42BSA62) via oDrive S1 UART (ODriveArduino library).
// Encoder #1 is wired to oDrive ENC0 (configured in ODrive Tool).
class BldcMotor {
public:
  BldcMotor();

  void begin();
  void poll();

  void enable(bool on);
  bool isEnabled() const { return armed_; }
  bool hasFault()  const { return fault_; }

  void setSpeedRpm(int rpm);
  void startRampTo(int rpm);
  void rampTo(int rpm);
  void stopImmediate();
  void cutPower();
  void stop();

  int targetRpm()   const { return targetRpm_; }
  int currentRpm()  const { return currentRpm_; }
  int feedbackRpm() const { return feedbackRpm_; }
  int smoothedRpm() const { return smoothedRpm_; }

private:
#if MOTORS_ENABLED
  void configureVelocityRamp();
  void ensureClosedLoop();
  void applyTargetVelocity();

  SoftwareSerial odriveSerial_;  // D8 RX, D9 TX
  ODriveUART odrive_;
#endif

  int targetRpm_   = 0;
  int currentRpm_  = 0;
  int feedbackRpm_ = 0;
  int smoothedRpm_ = 0;
  bool armed_ = false;
  bool fault_ = false;

  // 1-second moving average: 20 slots at 50 ms/sample
  static constexpr uint8_t kAvgLen = 20;
  int     velBuf_[kAvgLen] = {};
  uint8_t velBufIdx_       = 0;
  long    velBufSum_       = 0;

  unsigned long lastFeedbackMs_ = 0;
};
