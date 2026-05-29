#include "motor.h"

Motor::Motor(int a, int b, int pwm) {
    pinA = a;
    pinB = b;
    pinPWM = pwm;
    pinMode(pinA, OUTPUT);
    pinMode(pinB, OUTPUT);
    pinMode(pinPWM, OUTPUT);
}

void Motor::setSpeed(float speed) {
    speed = constrain(speed, -255, 255);

    if (speed == 0) {
        digitalWrite(pinA, LOW);
        digitalWrite(pinB, LOW);
        analogWrite(pinPWM, 0);
        return;
    }

    if (speed < 0) {
        digitalWrite(pinA, HIGH);
        digitalWrite(pinB, LOW);
        speed = -speed;
    } else {
        digitalWrite(pinA, LOW);
        digitalWrite(pinB, HIGH);
    }

    analogWrite(pinPWM, int(speed));
}