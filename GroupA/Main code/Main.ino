// Code for using PID control to reach a given target speed, using hall effect sensor feedback


#include <Arduino.h>
#include "interrupts.h"
#include "PID.h"
#include "motor.h"

#define INA 2 // drives motor clcokwise when high, pin 2
#define INB 4 // drives motor counter - clockwise when high, pin 3
#define PWM 3 // output the pwm to pin 4
#define HALL 5 // Hall effect sensor input pin 2


Motor motor(5, 6, 9); // pins: INA, INB, PWM
float omega_ref = 60.0; // original reference speed rad/s

// Speed variables
float currentSpeed = 0.0;     // will receive instantaneous omega
float targetPWM =  0;        // will receive PID output and is the PWM aiming for

// QuickPID controller
// Arguments: &Input, &Output, &Setpoint, Kp, Ki, Kd
QuickPID speedPID(&currentSpeed, &targetPWM, &omega_ref,
                  2.0, 0.5, 0.1, DIRECT);


void setup() {
    attachInterrupt(digitalPinToInterrupt(HALL), hallISR, RISING); // add interrupt for hall sensor

    speedPID.SetOutputLimits(-255, 255);    // PID output limits match PWM range
    speedPID.SetSampleTimeUs(50000);        // 50 ms sample time
    speedPID.SetMode(AUTOMATIC);            // enable PID

    Serial.begin(9600);
}

void loop() {
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

  //output time current speed and target speed
  Serial.print(millis());
  Serial.print(",");
  Serial.print(currentSpeed);
  Serial.print(",");
  Serial.println(targetPWM);
  Serial.print(",");
  Serial.println(omega_ref);
}
