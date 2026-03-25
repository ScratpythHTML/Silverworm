
import time
import spidev

# spidev guide is here: https://pypi.org/project/spidev/


## Setting up SPI bus 1: wrapper arm (copy and edit for subsequent SPI busses)

# Setting bus number and chip select pin (device) number
wrapBus = 0         # wrapper is on SPI bus 0
wrapDevice = 0      # wrapper is chip select pin 0 within bus 0

wrapSPI = spidev.SpiDev()           # Defines wrapSPI object
wrapSPI.open(wrapBus, wrapDevice)   # Opens connection to the specific bus and device
wrapSPI.max_speed_hz = 500000           # arbitrary or should be changed???
wrapSPI.mode = 0                        # actually not sure what goes here - ZAK check

