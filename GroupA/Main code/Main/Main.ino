// Code for using PID control to reach a given target speed, using hall effect sensor feedback


#include <Arduino.h>
#include <SPI.h>
#include "interrupts.h"
#include "PID.h"
#include "motor.h"


#define INA 2 // drives motor clcokwise when high, pin 2
#define INB 4 // drives motor counter - clockwise when high, pin 4
#define PWM 3 // output the pwm to pin 3
#define HALL 5 // Hall effect sensor input pin 5

constexpr unsigned long SPEED_REPORT_INTERVAL_MS = 100;

volatile byte receivedBuffer[3];
volatile byte completedCommand[3];
volatile byte bufferIndex = 0;
volatile byte expectedCommandLength = 0;
volatile bool newCommand = false;
volatile byte replyBuffer[3];
volatile byte replyLength = 0;
volatile byte replyIndex = 0;

void setReply(byte a, byte b = 0, byte c = 0, byte length = 1) {
    noInterrupts();
    replyBuffer[0] = a;
    replyBuffer[1] = b;
    replyBuffer[2] = c;
    replyLength = length;
    replyIndex = 0;
    SPDR = replyBuffer[replyIndex++];
    interrupts();
}

// Interrupt for SPI transfers while the Arduino acts as slave.
ISR(SPI_STC_vect) {
    byte c = SPDR;

    receivedBuffer[bufferIndex++] = c;

    if (bufferIndex == 1) {
        if (c == '1' || c == '3') expectedCommandLength = 3;
        else if (c == '2' || c == '4') expectedCommandLength = 2;
        else expectedCommandLength = 1;
    }

    if (bufferIndex >= expectedCommandLength) {
        for (byte i = 0; i < 3; i++) {
            completedCommand[i] = receivedBuffer[i];
        }
        bufferIndex = 0;
        expectedCommandLength = 0;
        newCommand = true;
    }

    if (replyIndex < replyLength) {
        SPDR = replyBuffer[replyIndex++];
    } else {
        SPDR = 0;
        replyLength = 0;
        replyIndex = 0;
    }
}


Motor motor(INA, INB, PWM); // pins: INA, INB, PWM
float omega_ref = 60.0; // original reference speed rad/s

// Speed variables
float currentSpeed = 0.0;     // will receive instantaneous omega
float targetPWM =  0;        // will receive PID output and is the PWM aiming for

// QuickPID controller
// Arguments: &Input, &Output, &Setpoint, Kp, Ki, Kd
QuickPID speedPID(&currentSpeed, &targetPWM, &omega_ref,
                  2.0, 0.5, 0.1, DIRECT);


void setup() {
    // Interrupt for Hall sensor
    attachInterrupt(digitalPinToInterrupt(HALL), hallISR, RISING); // add interrupt for hall sensor

    // Set up for PID
    speedPID.SetOutputLimits(-255, 255);    // PID output limits match PWM range
    speedPID.SetSampleTimeUs(50000);        // 50 ms sample time
    speedPID.SetMode(AUTOMATIC);            // enable PID

    // Pin setup for SPI
    pinMode(MISO, OUTPUT);  // required for slave
    pinMode(SS, INPUT_PULLUP);

    SPDR = 0;
    SPCR |= _BV(SPE);       // enable SPI
    SPCR |= _BV(SPIE);      // enable interrupt
    Serial.begin(9600);
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

    switch (prefix) {

        case '1': {  // START
            int speed = command[1] | (command[2] << 8);
            omega_ref = speed;
            setReply('3', '1', 0, 2);
            break;
        }

        case '2': {  // STOP
            motor.setSpeed(0);
            omega_ref = 0;
            setReply('3', '2', 0, 2);
            break;
        }

        case '3': {  // SET SPEED
            int speed = command[1] | (command[2] << 8);
            omega_ref = speed;
            break;
        }

        case '4': {  // TEST
            motor.setSpeed(100);
            delay(200);
            motor.setSpeed(0);
            break;
        }

        default:
            setReply('2', '1', 0, 2);
            break;
    }
  }
  // read latest instantaneous omega safely
  noInterrupts();
  currentSpeed = omega;
  interrupts();

  // run PID to set new pwm value
  speedPID.Compute();

  // clamp to valid PWM range
  targetPWM = constrain(targetPWM, -255, 255);

  // apply to motor
  motor.setSpeed((int)targetPWM);

  // send speed via spi
  unsigned long now = millis();
  if (now - lastSpeedReportMs >= SPEED_REPORT_INTERVAL_MS) {
    lastSpeedReportMs = now;
    int speed = (int)currentSpeed;
    setReply('1', speed & 0xFF, (speed >> 8) & 0xFF, 3);
  }

  //output time current speed and target speed
  Serial.print(millis());
  Serial.print(",");
  Serial.print(currentSpeed);
  Serial.print(",");
  Serial.print(targetPWM);
  Serial.print(",");
  Serial.println(omega_ref);
}
