#include "interrupts.h"
const int pulsePerRev = 1; //amount of pulses for each revolution
volatile unsigned long lastPulseTime = 0; // time in ms of last pulse since turning on 
volatile float omega = 0; // current speed


void hallISR() {
    unsigned long now = micros(); // microsecond timestamp
    if(lastPulseTime > 0) {
        unsigned long period = now - lastPulseTime; // microseconds
        omega = (2.0 * PI * 1000000.0) / (pulsePerRev*period); // current speed rad/s
    }
    lastPulseTime = now;
}
