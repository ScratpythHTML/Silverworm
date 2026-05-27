#include "interrupts.h"
volatile unsigned long triggerCount = 0;   // ADD THIS
const int pulsePerRev = 1; //amount of pulses for each revolution
volatile unsigned long lastPulseTime = 0; // time in ms of last pulse since turning on 
volatile float omega = 0; // current speed

// If the hall input is noisy (floating, loose wire, or electrical interference),
// the ISR can fire rapidly even without a magnet.
// At your expected speed (~50 rev/s when omega ~315 rad/s), period is ~20 ms,
// so ignoring edges closer than a few ms is safe.
static const uint32_t HALL_DEBOUNCE_US = 2000; // 2 ms

void hallISR() {
    unsigned long now = micros();

    // Debounce: ignore edges arriving too soon after the last *accepted* edge.
    if (lastPulseTime > 0 && (now - lastPulseTime) < HALL_DEBOUNCE_US) {
        return;
    }

    triggerCount++;

    if(lastPulseTime > 0) {
        unsigned long period = now - lastPulseTime;
        omega = (2.0 * PI * 1000000.0) / (pulsePerRev * period);
    }

    lastPulseTime = now;
}
