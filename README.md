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

## Group C
This is the integration & control software — a PyQt6 app on a Raspberry Pi that reads the physical control panel, drives both motors, and measures yarn pitch live from a microscope camera.

### Hardware
- Raspberry Pi (Compute Module 5 + IO board)
- ESP32 physical UI panel — dials + mode/power switches (I2C)
- Wrap & feed motor controllers (SPI)
- AmScope HHD 8300-P USB microscope

### Software
The app is the system's central controller. It holds the machine state (mode, power, wrap + feed speeds), and the **physical panel is always the source of truth** — GUI controls are overwritten by the next dial/switch input. In AUTO it measures wrap pitch from the live camera and adjusts feed speed to hit the target; in MANUAL it overlays the target pitch/angle on the camera view for hand setup.

### Quick start

**On the wrapping machine (Raspberry Pi):**
```bash
python3 -m pip install -r interface/requirements-rpi.txt --break-system-packages
cd interface && python3 app.py
```

**On another computer (development, no hardware):**
```bash
python3 -m pip install -r interface/requirements.txt
cd interface && python3 app.py
```

On first launch you'll set target pitch, wire thickness, and tube diameter (tick "Remember settings" to skip it next time). With no panel attached, use the **Debug** menu to simulate dial/switch input.

### Code files
```
interface/
  app.py             Launcher — startup dialog → main window
  ui/main_window.py  Wires UI + state + hardware together
  app_state.py       Central state (mode/power/speeds), routes motor commands
  config.py          Settings, JSON persistence, wrap-angle math
  pitch_control.py   Closed-loop pitch → feed-speed control
  telemetry.py       Per-command timing/telemetry for the test report
  storage.py         Atomic saves (snapshots, recordings, logs)
  hardware.py        Picks real vs mock I2C/SPI transports per platform
  comms/
    pui.py           ESP32 panel protocol (I2C parser + listener)
    motor_spi.py     Arduino motor protocol (SPI packet codec)
  camera/            AmScope detection, capture, rolling frame buffer
  processing/
    pipeline.py      Runs pitch estimation on live camera frames
  ui/                GUI widgets (camera view, controls, graphs, dialogs)
  hil_test.py        Hardware-in-the-loop harness (no camera needed)
  diagnose.py        Environment / setup checker
image-processing/
  pitch_estimate.py  CV pitch measurement (OpenCV + SciPy)
```

### Continuing development
Start at `app.py` → `ui/main_window.py` → `app_state.py` (the central state machine). The reference sections below cover the protocols, formulas, and extension recipes you need to add features or bring up new hardware.

## How it works (reference)

### Architecture
```
ESP32 (panel) ──I2C──► Raspberry Pi (this app) ──SPI──► Arduino (motors)
 dials/switches          PyQt6 GUI + vision            wrap + feed
                         AppState = source of truth
```
The **physical panel always wins**: any dial/switch event overwrites what the GUI set. The GUI is a display/backup.

### Communication protocols
**I2C — panel → Pi (ASCII):**

| Message | Meaning |
|---|---|
| `D1±N` | Dial 1 (wrap) ± N detents, N∈{1,2,3} = small/med/large |
| `D2±N` | Dial 2 (feed) ± N detents |
| `AS0` / `AS1` | Mode → MANUAL / AUTO |
| `TP` | Toggle machine power |

Dials send *increments*, not absolute values; the detent→units lookup is in `DetentConfig` (`config.py`).

**SPI — Pi → Arduino (byte packets):**

| Prefix | Command | Payload |
|--------|---------|---------|
| `0x01` | Start | speedL, speedH (uint16 LE) |
| `0x02` | Stop | stop_type (1=ramp, 2=emergency, 3=power-off) |
| `0x03` | Set speed | speedL, speedH |
| `0x04` | Test movement | movement_type |
| `0x05` | Request speed | — |

**SPI — Arduino → Pi:** `0x01` current speed · `0x02` error_code · `0x03` sequence status.

### Core formulas
```python
theta = arctan(pitch / (pi * (tube_diameter + 2 * wire_thickness)))  # wrap angle
pitches_um = np.diff(peak_positions_px) * um_per_px                   # pitch from peaks
cv = std_pitch / mean_pitch                                          # confidence:
#   HIGH if wraps>=10 and cv<0.20 ; MEDIUM if wraps>=5 and cv<0.35 ; else LOW
```

### Settings
Persisted to the OS config dir, loaded on startup (target pitch, wire thickness, tube diameter, detent→speed mappings, remember-settings): macOS `~/Library/Preferences/Silverworm/config.json`, Linux `~/.config/Silverworm/config.json`. The manual-mode GUI toggle is hidden by default (enable in Settings with the warning ack) to avoid PUI/GUI desync.

## Extending the app
- **New PUI message:** add a case in `parse_pui_message()` + a dataclass (`comms/pui.py`) → signal on `PUIListener` → `apply_*` handler on `AppState` → wire in `MainWindow._connect_app_state_signals()` → test in `tests/test_pui_protocol.py` + `tests/test_app_state.py`.
- **New motor command:** add to `CommandPrefix` + `build_<cmd>()` with bounds checks (`comms/motor_spi.py`) → method on `MotorController` → test in `tests/test_motor_spi.py`.
- **Tune pitch detection:** edit `image-processing/pitch_estimate.py` (`min_dist_px`, `sigma`, `prom_factor`).

## Testing
```bash
cd interface
pytest -q tests/test_pui_protocol.py tests/test_motor_spi.py tests/test_app_state.py
```
The protocol layer is fully tested without hardware via `MockPUITransport` / `MockSPITransport`. Camera/UI tests need Linux + `pytest-qt`.

## Repository map
Several subfolders have their own README with hardware-specific detail (pin maps, wiring, board files). Start here, then drill in:

| Folder | Contents |
|--------|----------|
| [interface/](interface/) | Group C control software (see above) |
| [image-processing/](image-processing/) | Pitch-measurement CV pipeline |
| [GroupA/](GroupA/) | Group A wrapper-motor firmware (Arduino Nano Every) |
| [GroupB/](GroupB/README.md) | Group B collecting firmware + Uno pin map |
| [IO Panel/](IO%20Panel/Silverworm_Control_Panel/README.md) | ESP32 panel pinout + I2C protocol |
| → [Web test tool](IO%20Panel/Silverworm_Control_Panel/IO%20Panel%20Software/Web_Test_Version/README.md) | Browser serial test UI for the panel |
| [Motherboard/Hardware/](Motherboard/Hardware/Silverworm%20-%20CM5%20Motherboard/) | CM5 carrier-board KiCAD files |
| [Motherboard/Software/](Motherboard/Software/README.md) | Enabling SPI/I2C on the CM5 |
| [Subsystem Interfacing/](Subsystem%20Interfacing/README.md) | Cross-board SPI wiring overview |
