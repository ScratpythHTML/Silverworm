#pragma once

#include <Arduino.h>
#include "config.h"

class ShaftEncoder {
public:
  void begin();
  void poll();

  long count() const;
  float rpm() const;
  void resetCount();

private:
  friend void enc2Isr();
  volatile long count_ = 0;

  long lastCount_ = 0;
  unsigned long lastSampleMs_ = 0;
  float rpm_ = 0.0f;
};
