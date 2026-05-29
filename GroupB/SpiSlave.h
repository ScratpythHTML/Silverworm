#pragma once

#include <Arduino.h>

// Completed command buffer — safe to read from loop() after checking newCommand.
extern volatile byte completedCommand[3];
extern volatile bool newCommand;

// Returns true when SPI is not mid-command and no reply is pending.
bool spiIdle();

// Queue up to 3 bytes to be sent to the master on its next SPI clock cycles.
// Does nothing and returns false if a reply is already in flight.
bool setReply(byte a, byte b = 0, byte c = 0, byte length = 1);

// Call once from setup() to configure the ATmega328P SPI peripheral as a slave.
void spiSlaveBegin();
