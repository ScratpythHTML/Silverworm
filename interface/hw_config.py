"""
Raspberry Pi hardware pin configuration for the Silverworm system.

This file documents which physical pins are used on each platform and
what Linux device files they map to. Python opens device files — the
actual GPIO → peripheral mux is set by the OS via
/boot/firmware/config.txt (device-tree overlays).

IMPORTANT: GPIO10 and GPIO11 differ between platforms.
  - RPi 5 (test rig): GPIO10 = SPI0_MOSI, GPIO11 = SPI0_CLK  ← SPI, not I2C
  - CM5 (production):  GPIO10/11 *may* be reassigned to I2C via overlay
                       (not active/confirmed yet — see CM5Config below)

Do not use CM5Config until the CM5 board is available and the overlay
is verified.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class I2CConfig:
    """I2C bus configuration."""
    bus_number: int        # Linux /dev/i2c-N
    sda_gpio: int          # BCM GPIO number (documentation only)
    sda_physical_pin: int  # Physical board pin number
    scl_gpio: int
    scl_physical_pin: int
    pui_address: int = 0x55  # ESP32 I2C slave address (Control_panel.ino)


@dataclass(frozen=True)
class SPIConfig:
    """SPI bus + chip-select configuration for one motor controller."""
    bus: int               # Linux spidev bus number (B in /dev/spidev-B.D)
    device: int            # Chip-select index (D in /dev/spidev-B.D)
    mosi_gpio: int
    miso_gpio: int
    sclk_gpio: int
    cs_gpio: int
    max_speed_hz: int = 500_000
    mode: int = 0          # SPI Mode 0 (CPOL=0 CPHA=0) — Arduino default


@dataclass(frozen=True)
class PlatformConfig:
    name: str
    i2c: I2CConfig
    wrap_spi: SPIConfig    # Wrap motor (Arduino)
    feed_spi: SPIConfig    # Feed motor (Arduino)


# ---------------------------------------------------------------------------
# Raspberry Pi 5 — test rig configuration (active)
# ---------------------------------------------------------------------------
#
# I2C1: standard pins, always available, no overlay needed.
# SPI0: standard pins, enabled via raspi-config → Interfacing Options → SPI.
#   Wrap motor (Arduino) on SPI0 with chip-select CE0.
# SPI1: secondary bus, requires dtoverlay=spi1-1cs in /boot/firmware/config.txt.
#   Feed motor (Arduino) on SPI1 with chip-select CE0.
#
# Physical wiring reference:
#   I2C SDA  GPIO2   pin 3
#   I2C SCL  GPIO3   pin 5
#   SPI0 MOSI GPIO10  pin 19 ← wrap motor
#   SPI0 MISO GPIO9   pin 21
#   SPI0 SCLK GPIO11  pin 23
#   SPI0 CE0  GPIO8   pin 24
#   SPI1 MOSI GPIO20  pin 38 ← feed motor
#   SPI1 MISO GPIO19  pin 35
#   SPI1 SCLK GPIO21  pin 40
#   SPI1 CE0  GPIO18  pin 12

RPI5 = PlatformConfig(
    name="rpi5",
    i2c=I2CConfig(
        bus_number=1,
        sda_gpio=2,          sda_physical_pin=3,
        scl_gpio=3,          scl_physical_pin=5,
    ),
    wrap_spi=SPIConfig(
        bus=0, device=0,
        mosi_gpio=10,        # pin 19
        miso_gpio=9,         # pin 21
        sclk_gpio=11,        # pin 23
        cs_gpio=8,           # pin 24 CE0
    ),
    feed_spi=SPIConfig(
        bus=1, device=0,
        mosi_gpio=20,        # pin 38
        miso_gpio=19,        # pin 35
        sclk_gpio=21,        # pin 40
        cs_gpio=18,          # pin 12 CE0
    ),
)

# ---------------------------------------------------------------------------
# CM5 — FUTURE / NOT ACTIVE
# ---------------------------------------------------------------------------
#
# The CM5 carrier board routes I2C to GPIO10/11 via a device-tree overlay.
# That GPIO assignment conflicts with SPI0 on a standard Pi — the overlay
# must be confirmed before these numbers are usable.
#
# TODO (CM5 bring-up): verify the overlay bus number by running
#   ls /dev/i2c-*   after booting the CM5 with the overlay applied.
#
# Leave CM5 = None so build_transports() raises clearly instead of
# silently using wrong bus numbers.

CM5 = None  # not ready — see above


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PLATFORMS: dict[str, PlatformConfig | None] = {
    "rpi5": RPI5,
    "cm5": CM5,
}


def get_platform(name: str) -> PlatformConfig:
    """Return the PlatformConfig for the given name, or raise."""
    name = name.lower()
    if name not in PLATFORMS:
        raise ValueError(
            f"Unknown hw_platform {name!r}. Known: {list(PLATFORMS)}"
        )
    config = PLATFORMS[name]
    if config is None:
        raise NotImplementedError(
            f"Platform {name!r} is defined but not yet configured. "
            "See hw_config.py for bring-up instructions."
        )
    return config
