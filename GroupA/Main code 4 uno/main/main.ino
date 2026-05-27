// Arduino Uno version of Nano Every SPI + PID motor controller
// Uses your existing Interrupts.h / interrupts.cpp and motor.h / motor.cpp

#include <Arduino.h>
#include <SPI.h>
#include "Interrupts.h"
#include <QuickPID.h>
#include "motor.h"
#include <avr/interrupt.h>

// -------------------- Pin definitions for Arduino Uno --------------------
// Uno external interrupts only work normally on D2 and D3.
// PWM is already on D3, so Hall should be on D2.
#define INA 4
#define INB 7      // changed from D2 so HALL can use D2 interrupt
#define PWM 3
#define HALL 2

// Uno hardware SPI pins are fixed:
// MOSI = D11
// MISO = D12
// SCK  = D13
// SS   = D10
#define SPI_SS_PIN 10

constexpr unsigned long SPEED_REPORT_INTERVAL_MS = 100;


// -------------------- SPI receive/reply buffers --------------------
volatile byte receivedBuffer[3];
volatile byte completedCommand[3];
volatile byte bufferIndex = 0;
volatile byte expectedCommandLength = 0;
volatile bool newCommand = false;

volatile byte replyBuffer[3];
volatile byte replyLength = 0;
volatile byte replyIndex = 0;

unsigned long lastSpeedReportMs = 0;
unsigned long testEndMs = 0;

// True when SPI is not mid-command and no reply is waiting
bool spiIdle() {
  return bufferIndex == 0 && replyLength == 0 && replyIndex == 0;
}

// Queue a reply to be sent later by the SPI ISR.
// This does not send immediately. The Pi/master must clock SPI to read it.
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

// -------------------- Uno SPI slave interrupt --------------------
// This fires once per SPI byte transfer.
ISR(SPI_STC_vect) {
  byte c = SPDR;  // byte received from Raspberry Pi/master

  // Store received byte into command buffer
  if (bufferIndex < sizeof(receivedBuffer)) {
    receivedBuffer[bufferIndex++] = c;
  }

  // First byte tells us how long the command should be
  if (bufferIndex == 1) {
    if (c == '1' || c == '3') {
      expectedCommandLength = 3;  // START or SET SPEED
    } else if (c == '2' || c == '4') {
      expectedCommandLength = 2;  // STOP or TEST
    } else {
      expectedCommandLength = 1;  // invalid/unknown command
    }
  }

  // If full command received, copy it for loop() to process
  if (expectedCommandLength > 0 && bufferIndex >= expectedCommandLength) {
    for (byte i = 0; i < 3; i++) {
      completedCommand[i] = (i < expectedCommandLength) ? receivedBuffer[i] : 0;
    }

    bufferIndex = 0;
    expectedCommandLength = 0;
    newCommand = true;
  }

  // Load next reply byte for the NEXT SPI transfer
  if (replyIndex < replyLength) {
    SPDR = replyBuffer[replyIndex++];
  } else {
    SPDR = 0;
    replyLength = 0;
    replyIndex = 0;
  }
}

// -------------------- Motor and PID --------------------
Motor motor(INA, INB, PWM);

float omega_ref = 20.0;       // target speed in rad/s
float currentSpeed = 0.0;    // measured speed from hall sensor
float targetPWM = 10.0;      // PID output

QuickPID speedPID(&currentSpeed, &targetPWM, &omega_ref,
                  1.0, 2.0, 0.0, QuickPID::Action::direct);

void setup() {
  Serial.begin(115200);

  // Your Motor constructor already sets pinMode for motor pins.

  // Hall sensor input with pullup. Your hallISR is in interrupts.cpp.
  pinMode(HALL, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(HALL), hallISR, FALLING);

  // PID setup
  speedPID.SetOutputLimits(-255, 255);
  speedPID.SetSampleTimeUs(50000);  // 50 ms
  speedPID.SetMode(QuickPID::Control::automatic);

  // SPI slave setup for Arduino Uno / ATmega328P
  pinMode(MISO, OUTPUT);
  pinMode(MOSI, INPUT);
  pinMode(SCK, INPUT);
  pinMode(SPI_SS_PIN, INPUT_PULLUP);

  SPCR = 0;
  SPCR |= _BV(SPE);   // enable SPI as slave
  SPCR |= _BV(SPIE);  // enable SPI interrupt

  SPDR = 0;           // default outgoing byte
  sei();              // enable global interrupts
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
    Serial.println("command received");
    Serial.println((char)command[0]);
    Serial.print("command received HEX: ");
    Serial.println(command[0], HEX);
    byte prefix = command[0];

    switch (prefix) {
      case '1': {  // START
        int speed = command[1] | (command[2] << 8);
        omega_ref = speed;
        Serial.print("starting up");
        setReply('3', '1', 0, 2);  // ACK start
        Serial.print("reply sent");
        break;
      }

      case '2': {  // STOP
        motor.setSpeed(0);
        omega_ref = 0;
        targetPWM = 0;
        setReply('3', '2', 0, 2);  // ACK stop
        break;
      }

      case '3': {  // SET SPEED
        int speed = command[1] | (command[2] << 8);
        omega_ref = speed;
        break;
      }

      case '4': {  // TEST — 200 ms pulse

        break;
      }

      default: {
        setReply('2', '1', 0, 2);  // error: invalid command
        break;
      }
    }
  }



  // Read latest omega safely from interrupts.cpp
  noInterrupts();
  currentSpeed = omega;
  interrupts();


  // Run PID and apply motor PWM
  speedPID.Compute();
  targetPWM = constrain(targetPWM, -255, 255);
  motor.setSpeed(targetPWM);

  // Queue speed report every 100 ms, only if SPI is idle
  unsigned long now = millis();
  if (now - lastSpeedReportMs >= SPEED_REPORT_INTERVAL_MS) {
    lastSpeedReportMs = now;

    noInterrupts();
    bool idle = spiIdle();
    interrupts();

    if (idle) {
      int speed = (int)currentSpeed;
      setReply('1', speed & 0xFF, (speed >> 8) & 0xFF, 3);
    }
  }


  // Serial Plotter output
  // Serial.print(omega_ref);
  // // Serial.print(",");
  // // Serial.println(targetPWM);
  // Serial.print(",");
  // Serial.println(currentSpeed);
}
