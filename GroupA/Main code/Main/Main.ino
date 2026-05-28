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

#define SPI_SS_PIN 9

constexpr uint8_t SPI_DATA_MODE = 0;

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

QuickPID speedPID(&currentSpeed, &targetPWM, &omega_ref,
                  30.0, 2.0, 0.0, QuickPID::Action::direct);

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
    if (c == '1' || c == '3') {
      expectedCommandLength = 3;
    } 
    else if (c == '2' || c == '4') {
      expectedCommandLength = 2;
    } 
    else if (c == '5') {
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

  pinMode(MISO, OUTPUT);
  pinMode(MOSI, INPUT);
  pinMode(SCK, INPUT);
  pinMode(SPI_SS_PIN, INPUT_PULLUP);

  PORTMUX.TWISPIROUTEA = PORTMUX_SPI0_ALT2_gc;

  SPI0.CTRLA = SPI_ENABLE_bm;
  SPI0.CTRLA &= ~SPI_MASTER_bm;
  SPI0.CTRLB = spiModeToCtrlb(SPI_DATA_MODE);
  SPI0.INTCTRL = SPI_IE_bm;
  SPI0.INTFLAGS = SPI_IF_bm;
  SPI0.DATA = 0;

  interrupts();

  Serial.println("Nano Every SPI slave ready");
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

    Serial.print("received: ");
    Serial.println((char)prefix);

    switch (prefix) {
      case '1': {
        int speed_rpm = command[1] | (command[2] << 8);
        float speed_rad = speed_rpm * (2.0 * 3.14156 / 60.0);
        omega_ref =speed_rad;
        setReply('3', '1', 0, 2);
        break;
      }

      case '2': {
        motor.setSpeed(0);
        omega_ref = 0;
        targetPWM = 0;
        speedPID.Reset();
        setReply('3', '2', 0, 2);
        break;
      }

      case '3': {
        int speed_rpm = command[1] | (command[2] << 8);
        float speed_rad = speed_rpm * (2.0 * 3.14156 / 60.0);
        omega_ref = speed_rad;
        break;
      }

      case '4': {
        Serial.println("test command received");

        break;
      }

      case '5': {
        int speed = (int)currentSpeed;
        setReply(speed & 0xFF, (speed >> 8) & 0xFF, 0, 2);
        Serial.println("speed reply queued");
        break;
      }

      default: {
        setReply('2', '1', 0, 2);
        break;
      }
    }
  }

  noInterrupts();
  currentSpeed = omega;
  interrupts();

  speedPID.Compute();
  targetPWM = constrain(targetPWM, -255, 255);
  motor.setSpeed((int)targetPWM);
}