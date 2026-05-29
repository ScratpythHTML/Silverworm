#include "SpiSlave.h"
#include <avr/interrupt.h>

// Internal receive state
static volatile byte receivedBuffer[3];
static volatile byte bufferIndex = 0;
static volatile byte expectedCommandLength = 0;

// Completed command — written by ISR, read by loop()
volatile byte completedCommand[3];
volatile bool newCommand = false;

// Reply state — written by setReply(), consumed by ISR
static volatile byte replyBuffer[3];
static volatile byte replyLength = 0;
static volatile byte replyIndex = 0;

bool spiIdle() {
  return bufferIndex == 0 && replyLength == 0 && replyIndex == 0;
}

bool setReply(byte a, byte b, byte c, byte length) {
  bool ok = false;
  noInterrupts();
  if (spiIdle()) {
    replyBuffer[0] = a;
    replyBuffer[1] = b;
    replyBuffer[2] = c;
    replyLength = length;
    replyIndex = 0;
    if (replyLength > 0) {
      SPDR = replyBuffer[replyIndex++];
    }
    ok = true;
  }
  interrupts();
  return ok;
}

// Fires once per SPI byte transferred (master clocks it).
ISR(SPI_STC_vect) {
  byte c = SPDR;  // byte received from master

  if (bufferIndex < 3) {
    receivedBuffer[bufferIndex++] = c;
  }

  // First byte determines expected command length
  if (bufferIndex == 1) {
    if (c == 0x01 || c == 0x03) {
      expectedCommandLength = 3;
    } else if (c == 0x02 || c == 0x04) {
      expectedCommandLength = 2;
    } else if (c == 0x05) {
      expectedCommandLength = 3;  // query frame includes two clock bytes
    } else {
      bufferIndex = 0;
      expectedCommandLength = 0;
      SPDR = 0;
      return;
    }
  }

  // Full command received — copy for loop() and reset receive state
  if (expectedCommandLength > 0 && bufferIndex >= expectedCommandLength) {
    for (byte i = 0; i < 3; i++) {
      completedCommand[i] = (i < expectedCommandLength) ? receivedBuffer[i] : 0;
    }
    bufferIndex = 0;
    expectedCommandLength = 0;
    newCommand = true;
  }

  // Load next reply byte for the master's next clock cycle
  if (replyIndex < replyLength) {
    SPDR = replyBuffer[replyIndex++];
  } else {
    SPDR = 0;
    replyLength = 0;
    replyIndex = 0;
  }
}

void spiSlaveBegin() {
  pinMode(MISO, OUTPUT);
  pinMode(MOSI, INPUT);
  pinMode(SCK, INPUT);
  pinMode(SS, INPUT_PULLUP);

  SPCR = 0;
  SPCR |= _BV(SPE);   // enable SPI as slave
  SPCR |= _BV(SPIE);  // enable SPI interrupt
  SPDR = 0;
}
