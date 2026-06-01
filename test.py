import spidev
import time

spi = spidev.SpiDev()
spi.open(1, 2)  # Open SPI bus 0, device (CE) 0
spi.max_speed_hz = 562000  # Set max speed (adjust)
spi.mode = 0

# response = spi.xfer2(0x01, 0x00, 0x64)  # Send dummy byte to read

while True:
    response = spi.xfer2([0x05])  # Send dummy byte to read
    print(response)
    time.sleep(1)  # Read every second
