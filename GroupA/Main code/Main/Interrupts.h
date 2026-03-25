#ifndef INTERRUPTS_H
#define INTERRUPTS_H

#include <Arduino.h>

extern volatile unsigned long lastPulseTime; // holds value of the last time hall effect sensor was there
extern volatile float omega; // current speed rad/s

void hallISR();

#endif
