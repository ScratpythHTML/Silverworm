# Silverworm

Yarn-pitch estimation and wrapping control system. PyQt6 GUI on a Raspberry
Pi that talks to a Physical UI panel (ESP32, I2C) and a motor controller
(Arduino, SPI), with a USB-microscope vision pipeline for live pitch
measurement.

The full design brief lives in [CLAUDE.md](CLAUDE.md). Recent changes are
in [CHANGELOG.md](CHANGELOG.md).

## Architecture

```
┌─────────────┐    I2C ASCII     ┌──────────────┐    SPI bytes    ┌────────────┐
│ ESP32 (PUI) │ ───────────────► │ Raspberry Pi │ ──────────────► │  Arduino   │
│ dials/switch│  D1±N, AS0/1, TP │  PyQt6 GUI   │  prefix+payload │ motor ctrl │
│   /lights   │                  │ vision (cv2) │ ◄────────────── │            │
└─────────────┘                  └──────────────┘   status/error  └────────────┘
```

**Physical UI (PUI) is always source of truth.** GUI controls are
suggestions — the next dial twist or mode-switch flip from the panel
overwrites whatever the GUI set.

## Project structure

```
Silverworm-app/
├── CLAUDE.md                       # Full design brief
├── CHANGELOG.md                    # Dated implementation history
├── README.md                       # This file
├── image-processing/
│   ├── pitch_estimate.py           # CV pipeline (OpenCV/SciPy)
│   └── sample-images/              # Test microscope frames
└── interface/
    ├── app.py                      # GUI entry point
    ├── app_state.py                # Central state machine + motor routing
    ├── config.py                   # AppConfig + JSON load/save
    ├── controller.py               # (legacy SetpointController, being phased out)
    ├── comms/
    │   ├── pui.py                  # PUI I2C protocol (parser + transport + listener)
    │   ├── motor_spi.py            # Motor SPI protocol (packet codec + transport)
    │   └── transport.py            # (legacy UART, kept for transitional code)
    ├── camera/                     # AmScope HHD 8300-P detection + capture
    ├── processing/                 # PitchDetectionPipeline (wraps pitch_estimate.py)
    ├── ui/
    │   ├── startup_dialog.py       # 3-field config dialog shown on launch
    │   ├── camera_widget.py        # Live camera view
    │   └── manual_mode_dialog.py   # Manual-mode acknowledgement banner
    ├── tests/                      # pytest suite (mocked hardware)
    └── venv/                       # Python 3.14 virtualenv
```

## Setup

### Prerequisites
- Python 3.10+ (Python 3.14 verified on macOS)
- Raspberry Pi OS (Bookworm or later) for hardware deployment

### Install (dev — macOS or Linux)

```bash
cd interface
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install PyQt6 opencv-python numpy scipy matplotlib pytest
```

### Install (Pi — adds hardware drivers)

```bash
pip install smbus2 spidev      # only needed on the Pi
```

The app loads on any OS; `smbus2`/`spidev` are lazy-imported only when
the real I2C/SPI transports open.

## Running the app

```bash
cd interface
source venv/bin/activate
python app.py
```

On launch you'll see the **Startup Configuration** dialog (Target Pitch,
Wire Thickness, Tube Diameter) — fill it in once and tick "Remember
settings" to skip it next time. Config persists to:
- macOS:   `~/Library/Preferences/Silverworm/config.json`
- Linux:   `~/.config/Silverworm/config.json`
- Windows: `%APPDATA%/Silverworm/config.json`

Use the **Debug** menu in the menu bar to inject simulated PUI messages
(`D1+1`, `D1-2`, `AS0`, `AS1`, `TP`, etc.) while developing on a machine
without a connected panel. Every transition mirrors to the alert log.

## Communication protocols

### PUI → RPi (I2C, ASCII messages)

| Message | Meaning |
|---|---|
| `D1±N` | Dial 1 (wrap speed) changed by N detents, N ∈ {1,2,3} = small/medium/large |
| `D2±N` | Dial 2 (feed speed) changed by N detents |
| `AS0`  | Mode switch → MANUAL |
| `AS1`  | Mode switch → AUTO |
| `TP`   | Toggle machine power state |

Dial events apply *increments* (configured in `DetentConfig`), not
absolute values. `D1+2` adds the medium dial-1 increment to the current
wrap speed.

### RPi → Arduino (SPI, byte packets)

| Prefix | Command       | Payload                                |
|--------|---------------|----------------------------------------|
| `0x01` | Start         | `speedL`, `speedH` (uint16, little-endian) |
| `0x02` | Stop          | `stop_type` (1=ramp, 2=emergency, 3=power-off) |
| `0x03` | Set speed     | `speedL`, `speedH`                     |
| `0x04` | Test movement | `movement_type` (1 byte)               |

### Arduino → RPi

| Prefix | Response         | Payload                  |
|--------|------------------|--------------------------|
| `0x01` | Current speed    | `speedL`, `speedH`       |
| `0x02` | Error            | `error_code` (1 byte)    |
| `0x03` | Sequence status  | `status` (1 byte)        |

Code: [`interface/comms/pui.py`](interface/comms/pui.py),
[`interface/comms/motor_spi.py`](interface/comms/motor_spi.py).

## State model

[`AppState`](interface/app_state.py) is the single source of truth for
`mode`, `machine_on`, `wrap_speed_rpm`, and `feed_speed_mms`. Events from
both the GUI and the PUI listener call the same internal setters — the
"precedence" rule is simply that PUI events happen whenever the operator
touches the panel and overwrite whatever the GUI last set.

State transitions emit Qt signals (`mode_changed`, `wrap_speed_changed`,
etc.) which the GUI subscribes to.

## Testing

```bash
cd interface
source venv/bin/activate
python -m pytest tests/test_pui_protocol.py tests/test_motor_spi.py tests/test_app_state.py -v
```

The protocol layer is fully tested without hardware via `MockPUITransport`
and `MockSPITransport`. Coverage includes:

- PUI ASCII parser (every message form + edge cases)
- SPI packet encoding (`speedL`/`speedH` byte order, stop types, bounds)
- Arduino response parsing
- AppState behaviour: dial increments, PUI/GUI mode precedence, TP →
  start/stop motor packets, speed propagation only while running

Pre-existing camera/UI tests require Linux (`v4l-utils`) and `pytest-qt`;
they're not part of the protocol test target.

## Hardware bring-up on the Pi

1. Install `smbus2` and `spidev` (see "Install" above).
2. Enable I2C and SPI in `raspi-config` → Interfacing Options.
3. In [`interface/app.py`](interface/app.py) `MainWindow.__init__`, swap
   the mock transports for real ones:
   ```python
   from comms import I2CPUITransport, SPIMotorTransport
   self._pui_transport = I2CPUITransport(bus_number=1, address=0x42)
   self._wrap_spi = SPIMotorTransport(bus=0, device=0)
   self._feed_spi = SPIMotorTransport(bus=0, device=1)
   ```
4. Confirm I2C address with the PUI firmware author; the placeholder is
   `0x42`. See TODOs in [`comms/pui.py`](interface/comms/pui.py) and
   [`comms/motor_spi.py`](interface/comms/motor_spi.py).
5. Use a logic analyser on the I2C / SPI lines to verify packet
   structure matches the tables above.

## Camera setup (Linux, AmScope HHD 8300-P)

```bash
sudo apt-get install v4l-utils
sudo usermod -a -G video $USER     # log out + back in
ls -l /dev/video*
v4l2-ctl --list-devices            # should list "AmScope HHD 8300-P"
```

The app auto-detects the AmScope camera; if multiple cameras are present
it prioritises AmScope. See [`interface/camera/detector.py`](interface/camera/detector.py).

### Camera troubleshooting

| Symptom | Check |
|---|---|
| Camera not detected | `lsusb`, `dmesg \| grep video`, try a data-capable USB cable / different port |
| Permission denied | `groups` (need `video`), `ls -l /dev/video*`, reboot after group add |
| Low frame rate | Switch to `CameraConfig.amscope_8300p_lowres()`, set `use_mjpeg=False`, use USB 3.0 |
| Wrong camera selected | Adjust priority in `camera/detector.py` |

## Theme / customisation

Colours live in the `Theme` class at the top of
[`interface/app.py`](interface/app.py) (also duplicated in
[`interface/ui/startup_dialog.py`](interface/ui/startup_dialog.py) as
`_Theme` to keep the dialog free of circular imports).

```python
class Theme:
    ACCENT_PRIMARY = "#00d4aa"   # teal
    BG_PRIMARY     = "#0a0e14"
    SUCCESS        = "#00d68f"
    ERROR          = "#ff6b6b"
    # ...
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `QRadialGradient` type error on launch | Already fixed (line 254 uses `QPointF`). Pull latest. |
| App opens then crashes on camera probe | OpenCV will spam "out of bound" warnings for non-existent `/dev/video*` indices on macOS — these are harmless; the window still opens. |
| Tests fail with `pytest-qt`-related errors | The protocol tests (`test_pui_protocol/motor_spi/app_state`) don't need `pytest-qt`. Run only those. |
| `pip install PyQt6` fails on Python 3.14 | Upgrade pip first: `pip install -U pip`. |
