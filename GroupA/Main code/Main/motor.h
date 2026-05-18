#ifndef MOTOR_H
#define MOTOR_H

#include <Arduino.h>

class Motor {
private:
    int pinA, pinB, pinPWM;
public:
    Motor(int a, int b, int pwm);
    void setSpeed(float speed); // speed: -255 to 255, pwm output
};

#endif
