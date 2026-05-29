#pragma once

#include <Arduino.h>

void motorSpiBegin();
void motorSpiPoll();

// Returns the stop-type byte from the most recent kStop command; 0 = none.
uint8_t motorSpiTakeStopType();

// Returns true and fills rpm if a new kStart command arrived; false otherwise.
bool motorSpiTakeStartRpm(int16_t& rpm);

// Returns true and fills rpm if a new kSetSpeed command arrived; false otherwise.
bool motorSpiTakeSetSpeedRpm(int16_t& rpm);

// Call each loop() with the latest feedback RPM so kQuery replies are current.
void motorSpiSetFeedbackRpm(int16_t rpm);
