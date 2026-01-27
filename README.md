# Silverworm
Hardware and software design for the Silverworm spiral yarn wrapping machine.

## Group A
This is the wrapping team. We have designed a rotating arm that enscapulates a core yarn with a conductive outer fibre. The code in this repository is used to set the speed of the motor.

### Hardware
- Arduino Nano Every
- VNH5019 Motor Driver
- Honeywell Digital Hall Effect Sensor
- CHANCS 30W Permanent Magnet DC Motor 

### Software
The arduino code takes an inputted reference speed and accelerates the motor to this. It uses a Hall effect sensor and magnets on the arm to calculate the current speed. A PID controller is used for this system to eliminate error and ensure the motor willl get to the correct speed with in a set time. 