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

<img width="1767" height="1136" alt="image" src="https://github.com/user-attachments/assets/a8638710-c120-4e9f-a581-9d027e585755" />
