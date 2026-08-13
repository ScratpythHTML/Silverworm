#include "ShaftEncoder.h"

#if defined(ARDUINO_ARCH_AVR)
#include <avr/interrupt.h>
#endif

static ShaftEncoder* gEncoder = nullptr;
static uint8_t gLastAbState = 0;

static const int8_t kQuadTable[16] = {
    0, 1, -1, 0, -1, 0, 0, 1, 1, 0, 0, -1, 0, -1, 1, 0,
};

static uint8_t readAbState() {
  const uint8_t a = digitalRead(ENC2_A_PIN) ? 1 : 0;
  const uint8_t b = digitalRead(ENC2_B_PIN) ? 1 : 0;
  return (a << 1) | b;
}

static void enc2Isr() {
  if (gEncoder == nullptr) return;

#if ENC2_Z_PIN >= 0
  static uint8_t lastZ = HIGH;
  const uint8_t z = digitalRead(ENC2_Z_PIN);
  if (lastZ == HIGH && z == LOW) {
    gEncoder->count_ = 0;
  }
  lastZ = z;
#endif

  const uint8_t state = readAbState();
  const uint8_t idx = (gLastAbState << 2) | state;
  gEncoder->count_ += kQuadTable[idx];
  gLastAbState = state;
}

// ISR(PCINT2_vect) commented out — SoftwareSerial (ODrive UART) owns all PCINT vectors.
// Re-enable and switch to AltSoftSerial if ShaftEncoder interrupt counting is needed again.
// #if defined(ARDUINO_ARCH_AVR)
// ISR(PCINT2_vect) {
//   enc2Isr();
// }
// #endif

void ShaftEncoder::begin() {
  gEncoder = this;
  count_ = 0;
  lastCount_ = 0;
  rpm_ = 0.0f;
  lastSampleMs_ = millis();

  pinMode(ENC2_A_PIN, INPUT_PULLUP);
  pinMode(ENC2_B_PIN, INPUT_PULLUP);
#if ENC2_Z_PIN >= 0
  pinMode(ENC2_Z_PIN, INPUT_PULLUP);
#endif

  gLastAbState = readAbState();

// PCINT2 setup commented out — SoftwareSerial (ODrive UART) owns PCINT vectors.
// #if defined(ARDUINO_ARCH_AVR)
//   PCICR |= _BV(PCIE2);
//   PCMSK2 |= _BV(PCINT21);  // D5 / PD5
//   PCMSK2 |= _BV(PCINT22);  // D6 / PD6
// #if ENC2_Z_PIN >= 0
//   PCMSK2 |= _BV(PCINT23);  // D7 / PD7
// #endif
#if !defined(ARDUINO_ARCH_AVR)  // non-AVR fallback only
  attachInterrupt(digitalPinToInterrupt(ENC2_A_PIN), enc2Isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC2_B_PIN), enc2Isr, CHANGE);
#if ENC2_Z_PIN >= 0
  attachInterrupt(digitalPinToInterrupt(ENC2_Z_PIN), enc2Isr, CHANGE);
#endif
#endif
}

void ShaftEncoder::resetCount() {
  noInterrupts();
  count_ = 0;
  lastCount_ = 0;
  interrupts();
}

long ShaftEncoder::count() const {
  noInterrupts();
  const long c = count_;
  interrupts();
  return c;
}

void ShaftEncoder::poll() {
  const unsigned long now = millis();
  if (now - lastSampleMs_ < ENC2_RPM_FILTER_MS) return;

  const long c = count();
  const unsigned long dt = now - lastSampleMs_;
  lastSampleMs_ = now;
  if (dt == 0) return;

  const long delta = c - lastCount_;
  lastCount_ = c;

  rpm_ = (delta * 60000.0f) / (ENC2_CPR * (float)dt);
}

float ShaftEncoder::rpm() const { return rpm_; }
