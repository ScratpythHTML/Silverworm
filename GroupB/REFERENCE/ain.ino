#include <Arduino.h>
#include <SPI.h>
#include "Interrupts.h"
#include <QuickPID.h>
#include "motor.h"
#include <avr/interrupt.h>

#define INA 4
#define INB 2
#define PWM 3
#define HALL 5

// Nano Every hardware SPI ALT2 pins:
// CS/SS = D8
// MOSI  = D11
// MISO  = D12
// SCK   = D13
#define SPI_SS_PIN 8
#define SPI_MOSI_PIN 11
#define SPI_MISO_PIN 12
#define SPI_SCK_PIN 13



// === SPI slave configuration (Nano Every / ATmega4809) ===
// Raspberry Pi SPI modes:
// - Mode 0: CPOL=0, CPHA=0
// - Mode 1: CPOL=0, CPHA=1
// - Mode 2: CPOL=1, CPHA=0
// - Mode 3: CPOL=1, CPHA=1
//
// Change this if the Pi reads garbage / shifted bytes.
constexpr uint8_t SPI_DATA_MODE = 0; // 0..3

volatile byte receivedBuffer[3];
volatile byte completedCommand[3];
volatile byte bufferIndex = 0;
volatile byte expectedCommandLength = 0;
volatile bool newCommand = false;

volatile byte replyBuffer[3];
volatile byte replyLength = 0;
volatile byte replyIndex = 0;

Motor motor(INA, INB, PWM);

float omega_ref = 0;
float currentSpeed = 0.0;
float targetPWM = 30;

float omega_target = 0;
float rampRate = 0.2;

QuickPID speedPID(&currentSpeed, &targetPWM, &omega_ref,
                  1.0, 2.0, 0.0, QuickPID::Action::direct);


bool spiIdle() {
  return bufferIndex == 0 && replyLength == 0 && replyIndex == 0;
}

bool setReply(byte a, byte b = 0, byte c = 0, byte length = 1) {
  bool ok = false;

  noInterrupts();
  if (spiIdle()) {
    replyBuffer[0] = a;
    replyBuffer[1] = b;
    replyBuffer[2] = c;
    replyLength = length;
    replyIndex = 0;
    if (replyLength > 0) {
      SPI0.DATA = replyBuffer[replyIndex++];
    }
    ok = true;
  }
  interrupts();

  return ok;
}

static inline uint8_t spiModeToCtrlb(uint8_t mode) {
  switch (mode & 0x03) {
    case 0: return SPI_MODE_0_gc;
    case 1: return SPI_MODE_1_gc;
    case 2: return SPI_MODE_2_gc;
    default: return SPI_MODE_3_gc;
  }
}

ISR(SPI0_INT_vect) {
  byte c = SPI0.DATA;

  if (bufferIndex < sizeof(receivedBuffer)) {
    receivedBuffer[bufferIndex++] = c;
  }

  if (bufferIndex == 1) {
    if (c == 0x01 || c == 0x03) {
      expectedCommandLength = 3;
    } 
    else if (c == 0x02) {
      expectedCommandLength = 2;
    } 
    else if (c == 0x04) {
      expectedCommandLength = 2;
    }
    else if (c == 0x05) {
      expectedCommandLength = 3;
    } 
    else {
      bufferIndex = 0;
      expectedCommandLength = 0;
      SPI0.DATA = 0;
      SPI0.INTFLAGS = SPI_IF_bm;
      return;
    }
  }

  if (expectedCommandLength > 0 && bufferIndex >= expectedCommandLength) {
    for (byte i = 0; i < 3; i++) {
      completedCommand[i] = i < expectedCommandLength ? receivedBuffer[i] : 0;
    }

    bufferIndex = 0;
    expectedCommandLength = 0;
    newCommand = true;
  }

  if (replyIndex < replyLength) {
    SPI0.DATA = replyBuffer[replyIndex++];
  } else {
    SPI0.DATA = 0;
    replyLength = 0;
    replyIndex = 0;
  }

  SPI0.INTFLAGS = SPI_IF_bm;
}

void setup() {
  Serial.begin(9600);

  pinMode(HALL, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(HALL), hallISR, FALLING);

  speedPID.SetOutputLimits(-255, 255);
  speedPID.SetSampleTimeUs(50000);
  speedPID.SetMode(QuickPID::Control::automatic);

  PORTMUX.TWISPIROUTEA = PORTMUX_SPI0_ALT2_gc;

  pinMode(SPI_SS_PIN, INPUT_PULLUP);
  pinMode(SPI_MOSI_PIN, INPUT);
  pinMode(SPI_MISO_PIN, OUTPUT);
  pinMode(SPI_SCK_PIN, INPUT);

  SPI0.CTRLA = 0;
  SPI0.CTRLB = spiModeToCtrlb(SPI_DATA_MODE);
  SPI0.INTFLAGS = SPI_IF_bm;
  SPI0.INTCTRL = SPI_IE_bm;
  SPI0.DATA = 0;

  SPI0.CTRLA = SPI_ENABLE_bm;

  interrupts();

  Serial.println("Nano Every SPI slave ready");




}

// Called when SS goes HIGH (end of SPI transaction). Resets framing state
// so the next transaction is treated as a fresh command.
void onSSDeassert() {
    bufferIndex = 0;
    expectedCommandLength = 0;
}

void loop() {
  byte command[3] = {0, 0, 0};

  if (newCommand) {
    noInterrupts();
    for (byte i = 0; i < 3; i++) {
      command[i] = completedCommand[i];
    }
    newCommand = false;
    interrupts();

    byte prefix = command[0];
    byte second = command[1];

    Serial.print("received: ");
    Serial.println(prefix);

    switch (prefix) {
      case 0x01: {
        int speed_rpm = command[1] | (command[2] << 8);
        Serial.print(speed_rpm);
        float speed_rad = speed_rpm * (2.0 * 3.14156 / 60.0);
        omega_target = speed_rad;
        rampRate = 0.2;
        setReply(0x03, 0x01, 0, 2);
        break;
      }

      case 0x02: {
            motor.setSpeed(0);
            omega_target = 0;
            omega_ref = 0;
            targetPWM = 0;
            speedPID.Reset();
            setReply(0x03, 0x02, 0, 2);
            break;
      }
      //   switch (second) {
      //     case '1': {
      //       omega_target = 0;
      //       rampRate = 0.2;
      //       setReply('3', '2', 0, 2);
      //       break;
      //     }

      //     case '2': {
      //       motor.setSpeed(0);
      //       omega_target = 0;
      //       omega_ref = 0;
      //       targetPWM = 0;
      //       speedPID.Reset();
      //       setReply('3', '2', 0, 2);
      //       break;
      //     }

      //     case '3': {
      //       motor.setSpeed(0);
      //       omega_target = 0;
      //       omega_ref = 0;
      //       targetPWM = 0;
      //       speedPID.Reset();
      //       setReply('3', '2', 0, 2);
      //       break;
      //     }

      //     default: {
      //       setReply('2', '1', 0, 2);
      //       break;
      //     }
      //   }
      //   break;
      // }

      case 0x03: {
        int speed_rpm = command[1] | (command[2] << 8);
        float speed_rad = speed_rpm * (2.0 * 3.14156 / 60.0);
        omega_target = speed_rad;
        rampRate = 20;
        setReply(0x03, 0x03, 0, 2);
        break;
      }

      case 0x04: {
        Serial.println("test command received");
        setReply(0x03, 0x04, 0x00, 2);
        break;
      }

      case 0x05: {
        unsigned long lastPulseUs;
        float measuredRadS;
        noInterrupts();
        lastPulseUs = lastPulseTime;
        measuredRadS = currentSpeed;
        interrupts();

        int speedRpm = 0;
        if (lastPulseUs > 0 && (micros() - lastPulseUs) <= 2000000UL) {
          speedRpm = (int)(measuredRadS * 60.0 / (2.0 * PI));
        }
        speedRpm = constrain(speedRpm, 0, 65535);

        setReply(0x01, speedRpm & 0xFF, (speedRpm >> 8) & 0xFF, 3);
        break;
      }

      default: {
        setReply(0x02, 0x01, 0x00, 2);
        break;
      }
    }
  }

  noInterrupts();
  currentSpeed = omega;
  interrupts();

  if (omega_ref < omega_target) {
    omega_ref += rampRate;
    if (omega_ref > omega_target) omega_ref = omega_target;
  }

  if (omega_ref > omega_target) {
    omega_ref -= rampRate;
    if (omega_ref < omega_target) omega_ref = omega_target;
  }

  speedPID.Compute();
  targetPWM = constrain(targetPWM, -255, 255);
  motor.setSpeed((int)targetPWM);
}

