# Motherboard - RPi CM5 - Software Setup

## How to enable SPI communication

[Taken from Sparkfun tutorial here](https://learn.sparkfun.com/tutorials/raspberry-pi-spi-and-i2c-tutorial/all)

1. Run `sudo raspi-config`
2. Select `5 Interfacing Options`
3. Select `P4 SPI`
4. Select yes when it asks you to enable SPI
5. Also select yes if it asks about automatically loading the kernel module.
6. Use the right arrow to select the `<Finish>` button.
7. Select yes when it asks to reboot.

8. After reebooting, run
```
ls /dev/*spi*
```

9. Expect the Pi to respond with a list of the enabled SPI pins (should be 6 pins on the CM5)

## Found this SPI comms article:
https://roboticsbackend.com/raspberry-pi-master-arduino-uno-slave-spi-communication-with-wiringpi/
