# UI Panel Pinout

| Pin     | Use      | Mode         |
|---------|----------|--------------|
| GPIO 0  | LED1-R   | ANALOG OUT   |
| GPIO 1  | LED1-G   | ANALOG OUT   |
| GPIO 2  | LED1-B   | ANALOG OUT   |
| GPIO 3  | TOGGLE   | DIG INPUT    |
| GPIO 13 | BTN2_LED | NOT USED     |
| GPIO 14 | BTN_1LED | DIGITAL OUT  |
| GPIO 4  | BTN2     | NOT USED     |
| GPIO 5  | BTN1     | INPUT PULLUP |
| GPIO 24 | DIAL1A   | DIG INPUT    |
| GPIO 23 | DIAL1B   | DIG INPUT    |
| GPIO 10 | DIAL1NO  | INPUT PULLUP |
| GPIO 11 | DIAL2A   | DIG INPUT    |
| GPIO 25 | DIAL2B   | DIG INPUT    |
| GPIO 12 | DIAL2NO  | INPUT PULLUP |
| GPIO 8  | SDA      | SDA          |
| GPIO 22 | SCL      | SCL          |
| GPIO 9  | LED2-R   | ANALOG OUT   |
| GPIO 27 | LED2-G   | ANALOG OUT   |
| GPIO 26 | LED2-B   | ANALOG OUT   |


# UI Panel Communications Protocol:

Uses I2C for communications between the ESP32 and the RPi

On the RPi side, we are using pins:
GPIO10 for SDA
GPIO11 for SCL

## I2C Functions for Communication:

The ESP32 sends the change in speeds for the motors, which the Raspberry Pi then applies to the variables within the backend which store the target motor speeds

### For Dials:
The ESP32 sends the label `D1` or `D2` before every command to identify dials 1 and 2
Then the number that it increments by:
- Small detent gives a `+1` or `-1`
- Medium detent gives `+2` or `-2`
- Large detent gives `+3` or `-3`

_For example: `D1-2` or `D2+1`_

So the ESP32 tells the RPi _which_ detent option is being used, it is then up to the RPi to decide what this means with regards to motor speeds.
The user can decide what the increments are for each motor/dial combo.

### For the auto/manual switch:
The ESP32 sends the label `AS` before the argument
- It sends `0` if it is set to manual mode
- It sends `1` if it is set to automatic mode

So as soon as the RPi receives `AS0`, it sets the program to manual, regardless of what is already running on the machine. As soon as the RPi receives `AS1` it goes to automatic mode. The GUI still has the power to change the mode, but the signals received from the ESP32 always override the mode.

### For the ON/OFF switch:
The ESP sends a simple command `TP` which toggles the machine between the ON and OFF state.
The RPi sends `ON` or `OFF` to the ESP32 when it the machine starts and stops, so that the ESP can cotnrol the status light inside the power button.
