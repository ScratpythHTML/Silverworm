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

// kQuery feedback — written by spiSetQueryRpm(), read directly inside ISR
static volatile int16_t isrFeedbackRpm = 0;

void spiSetQueryRpm(int16_t rpm) {
  noInterrupts();
  isrFeedbackRpm = rpm;
  interrupts();
}

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
    ok = true;
  }
  interrupts();
  return ok;
}

// Fires once per SPI byte transferred (master clocks it).
ISR(SPI_STC_vect) {
  byte c = SPDR;  // byte received from master

  if (bufferIndex < sizeof(receivedBuffer)) {
    receivedBuffer[bufferIndex++] = c;
  }

  // First byte determines expected command length
  if (bufferIndex == 1) {
    if (c == 0x01 || c == 0x03) {
      expectedCommandLength = 3;
    } else if (c == 0x02) {
      expectedCommandLength = 2;
    } else if (c == 0x04 || c == 0x05) {
      expectedCommandLength = 1;  // single-byte commands: kTest, kQuery
    } else {
      bufferIndex = 0;
      expectedCommandLength = 0;
      SPDR = 0;
      return;
    }
  }

  // Full command received — copy for loop() and pre-load reply into SPDR immediately.
  // The Pi clocks its first dummy byte on the very next cycle, so the reply must be
  // in SPDR before this ISR returns.
  if (expectedCommandLength > 0 && bufferIndex >= expectedCommandLength) {
    for (byte i = 0; i < 3; i++) {
      completedCommand[i] = (i < expectedCommandLength) ? receivedBuffer[i] : 0;
    }
    bufferIndex = 0;
    expectedCommandLength = 0;

    switch (completedCommand[0]) {

      case 0x05:  // kQuery — reply: [kSpeed=0x01, lo, hi]  (no newCommand; loop not needed)
      {
        const int16_t rpm = isrFeedbackRpm;
        replyBuffer[0] = 0x01;
        replyBuffer[1] = static_cast<byte>(rpm & 0xFF);
        replyBuffer[2] = static_cast<byte>((rpm >> 8) & 0xFF);
        replyLength = 3;
        break;
      }

      case 0x01:  // kStart    — reply: [kAck=0x03, 0x01]
      case 0x02:  // kStop     — reply: [kAck=0x03, 0x02]
      case 0x03:  // kSetSpeed — reply: [kAck=0x03, 0x03]
      case 0x04:  // kTest     — reply: [kAck=0x03, 0x04]
        replyBuffer[0] = 0x03;             // kAck
        replyBuffer[1] = completedCommand[0];
        replyBuffer[2] = 0;
        replyLength = 1;
        newCommand = true;
        break;

      default:
        replyBuffer[0] = 0x02;             // kError
        replyBuffer[1] = 0x01;             // kUnknownCommand
        replyBuffer[2] = 0;
        replyLength = 2;
        newCommand = true;
        break;
    }

    // Pre-load first reply byte so Pi reads it on its very next clock cycle
    replyIndex = 1;
    SPDR = replyBuffer[0];
    return;
  }

  // Continuation: load subsequent reply bytes on each clock cycle
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
  sei();
  Serial.println("SPI slave ready");
}
