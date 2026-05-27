#!/usr/bin/env python3
"""
I2C Test Script for Raspberry Pi (Master mode).
Reads messages from ESP32 controller (I2C slave) and displays them.
When TP (toggle power) is received, tracks state and prints status.

Run with: python3 test_i2c_comms.py
"""

import re
import time
import sys

try:
    import smbus2
except ImportError:
    print("ERROR: smbus2 not installed. Install with: pip install smbus2")
    sys.exit(1)


class I2CTestListener:
    I2C_BUS = 1  # RPi I2C bus (use 0 on older Pi)
    ESP32_ADDR = 0x55  # ESP32 controller I2C address (adjust if needed)

    def __init__(self):
        self.bus = None
        self.power_state = False  # Track on/off state
        self.message_count = 0
        self.last_read = None

    def connect(self):
        """Connect to I2C bus as master."""
        try:
            self.bus = smbus2.SMBus(self.I2C_BUS)
            print(f"✓ Connected to I2C bus {self.I2C_BUS} (RPi as master)")
        except Exception as e:
            print(f"✗ Failed to connect to I2C bus: {e}")
            print("  Enable I2C: sudo raspi-config → Interfacing Options → I2C")
            print("  Then reboot: sudo reboot")
            sys.exit(1)

    def read_from_esp32(self):
        """Read message from ESP32 slave."""
        try:
            # Read up to 16 bytes from ESP32
            data = self.bus.read_i2c_block_data(self.ESP32_ADDR, 0, 16)
            raw_hex = ' '.join(f'{b:02x}' for b in data)
            # Print raw bytes so we can see what's actually arriving
            print(f"    [raw] {raw_hex}", end='\r')
            # Filter out null bytes and parse
            msg_bytes = bytes(b for b in data if b != 0)
            if msg_bytes and msg_bytes != self.last_read:
                self.last_read = msg_bytes
                return msg_bytes.decode('ascii', errors='replace').strip()
        except OSError as e:
            print(f"\n✗ I2C read error: {e}")
            print("  → ESP32 not found at this address, or I2C wiring issue")
        except Exception as e:
            print(f"\n✗ Unexpected error: {e}")
        return None

    def handle_message(self, msg):
        """Process received message."""
        self.message_count += 1
        print(f"\n[{self.message_count}] Received: {repr(msg)}")

        # Dial 1 change: D1±N
        if match := re.match(r'D1([+-])(\d)', msg):
            direction = "+" if match.group(1) == "+" else "-"
            size = match.group(2)
            size_name = {
                "1": "small",
                "2": "medium",
                "3": "large"
            }.get(size, "unknown")
            print(f"    → Dial 1: {direction}{size_name}")

        # Dial 2 change: D2±N
        elif match := re.match(r'D2([+-])(\d)', msg):
            direction = "+" if match.group(1) == "+" else "-"
            size = match.group(2)
            size_name = {
                "1": "small",
                "2": "medium",
                "3": "large"
            }.get(size, "unknown")
            print(f"    → Dial 2: {direction}{size_name}")

        # Mode switch: AS0 (manual) / AS1 (auto)
        elif msg == "AS0":
            print(f"    → Mode: MANUAL")

        elif msg == "AS1":
            print(f"    → Mode: AUTO")

        # Power toggle: TP
        elif msg == "TP":
            self.power_state = not self.power_state
            status_str = "ON" if self.power_state else "OFF"
            print(f"    → Power toggle: now {status_str}")

        else:
            print(f"    → [Unrecognized message]")

    def run(self):
        """Main loop - poll ESP32 for messages."""
        self.connect()
        print("\n" + "="*60)
        print("I2C Test Listener - Monitoring ESP32 Controller")
        print("="*60)
        print(f"RPi (Master) ←I2C← ESP32 (Slave @ 0x{self.ESP32_ADDR:02X})")
        print(f"Bus: {self.I2C_BUS}")
        print("\nPolling for messages (Ctrl+C to exit)...\n")

        try:
            while True:
                msg = self.read_from_esp32()
                if msg:
                    self.handle_message(msg)

                time.sleep(0.1)  # Poll every 100ms

        except KeyboardInterrupt:
            print("\n\n✓ Exiting...")
        finally:
            if self.bus:
                self.bus.close()
                print("✓ I2C bus closed")


if __name__ == "__main__":
    listener = I2CTestListener()
    listener.run()



