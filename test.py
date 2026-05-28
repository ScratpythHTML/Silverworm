import spidev
import time

spi =spidev.SpiDev()
spi.open(0, 1)  # Open SPI bus 0, device (CE) 0
spi.max_speed_hz = 1000  # Set max speed (adjust
spi.mode = 0

while True:
    response = spi.xfer2(0x03)  # Send dummy byte to read
    print(response)
    time.sleep(1)  # Read every secondc