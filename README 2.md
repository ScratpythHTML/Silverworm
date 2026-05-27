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

## Group B
This is the feeding. We have a feeding system that is passively tensioned which goes into team A's system; after the warpped yarn comes out, we collect it on a rotating collecting spool, which is on a linear rail to ensure orthodirectionality. 

### Hardware
- STM32
- DM423T Stepper Driver
- Linear Guide Rail with Nema 23 Stepper Motor
- oDrive S1 Motor Driver
- 24V 3000RPM 0.16Nm 50W 3.30A 42x42x62mm Brushless DC Motor ( with included hall effect sensor ) 
- 2 x Incremental Rotary Encoder IHC3808-001G-2000BZ1 ABZ 3-Channel 8mm Hollow Shaft

### Software
The code would take a inputted speed of the linear core yarn and then calculate the corresponding speeds that the linear rail and the BLDC motor would need to run at to ensure linear speed is accurate. The 2 encoders would give us both the radial velocity of the wrapper and the core yarn, allowing us to create a closed-loop control.
