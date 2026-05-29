#include <Arduino.h>
#include "pid-autotune.h"

// ===== PINS =====
#define HALL 5
#define PWM 3

// ===== HALL SETTINGS =====
constexpr float PULSES_PER_REV = 2.0;     // change to 1.0 if only 1 pulse/rev
constexpr uint32_t HALL_DEBOUNCE_US = 2000;
constexpr uint32_t SPEED_TIMEOUT_US = 2000000UL;

// ===== SPEED VARIABLES =====
volatile unsigned long triggerCount = 0;
volatile unsigned long lastPulseTime = 0;
volatile float omega = 0.0;               // rad/s

float currentSpeed = 0.0;                 // rad/s

// ===== PID AUTOTUNE =====
PID pid = PID();
pid_tuner tuner = pid_tuner(pid);

double currentSetpoint = 0;
unsigned long testStartTime = 0;
bool tuningFinished = false;
bool changedSetpoint = false;

// ===== HALL ISR =====
void hallISR() {
  unsigned long now = micros();

  if (lastPulseTime > 0 && (now - lastPulseTime) < HALL_DEBOUNCE_US) {
    return;
  }

  triggerCount++;

  if (lastPulseTime > 0) {
    unsigned long period = now - lastPulseTime;
    omega = (2.0 * PI * 1000000.0) / (PULSES_PER_REV * period);
  }

  lastPulseTime = now;
}

// ===== OUTPUT MOTOR PWM =====
void outputFunc(double x) {
  int pwm = constrain((int)x, 0, 255);
  analogWrite(PWM, pwm);
}

// ===== READ SPEED SAFELY =====
double readSpeed() {
  noInterrupts();
  float speed = omega;
  unsigned long last = lastPulseTime;
  interrupts();

  if (last == 0 || micros() - last > SPEED_TIMEOUT_US) {
    speed = 0;

    noInterrupts();
    omega = 0;
    interrupts();
  }

  currentSpeed = speed;
  return (double)currentSpeed;
}

void setup() {
  Serial.begin(115200);

  pinMode(PWM, OUTPUT);
  analogWrite(PWM, 0);

  pinMode(HALL, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(HALL), hallISR, FALLING);

  // Target is in rad/s.
  // 100 rad/s = about 955 RPM.
  tuner.setTargetValue(10);

  // Full PWM range for autotune.
  // Reduce max if your motor is too aggressive.
  tuner.setOutputRange(0, 255);

  tuner.setCycles(10);

  // Library uses this spelling in the example.
  pid.setConstrains(0, 255);

  Serial.println(">>> PHASE 1: STARTING AUTOTUNE <<<");
  Serial.println("Setpoint,Input,Output");

  tuner.start();
}

void loop() {
  double input = readSpeed();

  if (!tuningFinished) {
    double output = tuner.update(input);
    outputFunc(output);

    Serial.print("100,");
    Serial.print(input);
    Serial.print(",");
    Serial.println(output);

    if (tuner.isDone()) {
      tuningFinished = true;

      double* constants = tuner.getConstants();

      analogWrite(PWM, 0);
      delay(1000);

      Serial.println(">>> TUNING COMPLETE <<<");
      Serial.print("Kp: "); Serial.println(constants[0], 6);
      Serial.print("Ki: "); Serial.println(constants[1], 6);
      Serial.print("Kd: "); Serial.println(constants[2], 6);

      pid.enable();

      currentSetpoint = 150; // rad/s
      pid.setSetPoint(currentSetpoint);

      testStartTime = millis();

      Serial.println(">>> PHASE 2: STEP RESPONSE TEST <<<");
      Serial.println("Setpoint,Input,Output");
    }
  } else {
    double output = pid.compute(input);
    outputFunc(output);

    unsigned long elapsed = millis() - testStartTime;

    if (!changedSetpoint && elapsed > 10000) {
      currentSetpoint = 200; // rad/s
      pid.setSetPoint(currentSetpoint);
      changedSetpoint = true;
      Serial.println(">>> SETPOINT CHANGE: 200 <<<");
    }

    Serial.print(currentSetpoint);
    Serial.print(",");
    Serial.print(input);
    Serial.print(",");
    Serial.println(output);
  }

  delay(10);
}