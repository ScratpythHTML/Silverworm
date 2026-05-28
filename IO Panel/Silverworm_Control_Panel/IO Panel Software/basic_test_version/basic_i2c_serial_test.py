#!/usr/bin/env python3

import sys
import threading
import time

try:
    from smbus2 import SMBus, i2c_msg
except ImportError:
    print("Missing dependency: smbus2")
    print("Install it with: pip install smbus2")
    sys.exit(1)


BUS_NUMBER = 1
SLAVE_ADDRESS = 0x55
MAX_PAYLOAD = 31
RESPONSE_BYTES = 32
POLL_INTERVAL_SECONDS = 0.5


def read_response(bus: SMBus):
    request = i2c_msg.read(SLAVE_ADDRESS, RESPONSE_BYTES)
    bus.i2c_rdwr(request)

    data = bytes(request)
    if not data:
      return None

    payload_length = data[0]
    if payload_length == 0:
        return None

    payload = data[1:1 + payload_length].decode("utf-8", errors="replace")
    if payload:
        return payload

    return None


def write_message(bus: SMBus, message: str):
    payload = message.encode("utf-8")[:MAX_PAYLOAD]
    request = i2c_msg.write(SLAVE_ADDRESS, payload)
    bus.i2c_rdwr(request)


def poll_esp32(bus: SMBus, stop_event: threading.Event, bus_lock: threading.Lock):
    while not stop_event.is_set():
        with bus_lock:
            try:
                response = read_response(bus)
                if response:
                    print(f"I2C< {response}")
            except OSError:
                pass

        stop_event.wait(POLL_INTERVAL_SECONDS)


def main():
    print("Raspberry Pi basic I2C serial test")
    print(f"Bus: {BUS_NUMBER}, Slave address: 0x{SLAVE_ADDRESS:02X}")
    print("Type a line and press Enter to send it to the ESP32-H2.")
    print("Any pending line from the ESP32 serial monitor will be printed automatically.")
    print("Type /quit to exit.")

    stop_event = threading.Event()
    bus_lock = threading.Lock()

    with SMBus(BUS_NUMBER) as bus:
        poll_thread = threading.Thread(
            target=poll_esp32,
            args=(bus, stop_event, bus_lock),
            daemon=True,
        )
        poll_thread.start()

        try:
            while True:
                try:
                    message = input("Pi> ")
                except EOFError:
                    break

                if not message:
                    continue

                if message.strip().lower() == "/quit":
                    break

                with bus_lock:
                    try:
                        write_message(bus, message)
                        print(f"I2C> {message}")
                    except OSError as error:
                        print(f"I2C write error: {error}")
                        continue

                    try:
                        response = read_response(bus)
                        if response:
                            print(f"I2C< {response}")
                    except OSError as error:
                        print(f"I2C read error: {error}")

        finally:
            stop_event.set()
            poll_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()