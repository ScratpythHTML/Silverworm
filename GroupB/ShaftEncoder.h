#pragma once

#include <Arduino.h>
#include "config.h"

class ShaftEncoder {
public:
  void begin();
  void poll();

  long count() const;
  int rpm() const;
  void resetCount();

private:
  friend void enc2Isr();
  volatile long count_ = 0;

  long lastCount_ = 0;
  unsigned long lastSampleMs_ = 0;
  int rpm_ = 0;
};
