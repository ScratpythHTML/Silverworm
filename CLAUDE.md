# CLAUDE.md

## Project Overview

This is a **Yarn Pitch Estimation Application** that runs on a Raspberry Pi. It combines:
- Live microscope camera feed for yarn wrapping visualization
- Computer vision for automated pitch measurement
- Physical UI (dials/switches) on an ESP32, communicating with the Pi over I2C
- Motor control on an Arduino, driven by the Pi over SPI

## Architecture

```
ESP32 (PUI) ──I2C──► Raspberry Pi (this app) ──SPI──► Arduino (motor controller)
   │                       │                              ▲
   │                       ├── GUI (PyQt6)                │
   │                       ├── Camera Feed (OpenCV)       │
   │                       ├── Image Processing           │
   │                       └── AppState (central)         │
   │                                                       │
   └─ Dials, mode switch, power switch          status / error / current speed
```

## Key Conventions

### Physical UI Precedence
**PUI ALWAYS takes precedence over Digital UI.** When a PUI signal is received, the GUI state must update to match. The GUI is effectively a display/backup interface — PUI is the source of truth.

### Communication Protocols

**I2C (ESP32 PUI → RPi), ASCII messages:**
- `D1±N` = Dial 1 changed by N detents (N ∈ {1,2,3} = small/medium/large; sign = direction)
- `D2±N` = Dial 2 changed by N detents
- `AS0` = Mode switch → MANUAL
- `AS1` = Mode switch → AUTO
- `TP` = Toggle machine power state (each press flips it)

**SPI (RPi → Arduino), byte packets:**

| Prefix | Command       | Payload                                 |
|--------|---------------|-----------------------------------------|
| `0x01` | Start         | `speedL`, `speedH` (uint16, little-endian) |
| `0x02` | Stop          | `stop_type` (1=ramp, 2=emergency, 3=power-off) |
| `0x03` | Set speed     | `speedL`, `speedH`                      |
| `0x04` | Test movement | `movement_type` (1 byte)                |

**SPI (Arduino → RPi) responses:**

| Prefix | Response        | Payload                |
|--------|-----------------|------------------------|
| `0x01` | Current speed   | `speedL`, `speedH`     |
| `0x02` | Error           | `error_code` (1 byte)  |
| `0x03` | Sequence status | `status` (1 byte)      |

Implementations: [`interface/comms/pui.py`](interface/comms/pui.py),
[`interface/comms/motor_spi.py`](interface/comms/motor_spi.py).
Both expose a `Mock*Transport` for tests and a real I2C/SPI transport
that lazy-imports `smbus2`/`spidev` only on the Pi.

### Detent Mapping
Dial events carry an *increment direction and size* — not an absolute
value. `D1+2` means "apply the medium dial-1 increment in the positive
direction". The (dial × size) → physical-units lookup lives in
[`DetentConfig`](interface/config.py) and is editable via Settings →
Detent Configuration.

### Manual Mode Warning
Manual Mode toggle is **hidden from GUI by default**. It must be explicitly enabled in Settings with a warning acknowledgment. This prevents sync issues between PUI and GUI.

## File Structure

See [README.md](README.md) for the full repo layout. Key files relevant
to the architecture:

```
interface/
├── app.py                   # GUI entry point + MainWindow
├── app_state.py             # Central state (mode/power/speeds) + motor routing
├── config.py                # AppConfig + JSON load/save + wrap-angle math
├── comms/
│   ├── pui.py               # I2C PUI: parser + transport ABC + Mock/I2C impls
│   └── motor_spi.py         # SPI motors: packet codec + transport ABC + Mock/SPI impls
└── ui/
    └── startup_dialog.py    # 3-field startup config dialog
```

Settings persist to the OS-standard config dir
(`~/Library/Preferences/Silverworm/config.json` on macOS,
`~/.config/Silverworm/config.json` on Linux).

## Core Formulas

### Wrap Angle Calculation (Manual Mode)
```python
theta = arctan(pitch / (pi * (tube_diameter + 2 * wire_thickness)))
```

### Pitch from Peaks
```python
pitches_um = np.diff(peak_positions_px) * um_per_px
```

### Confidence Scoring
```python
cv = std_pitch / mean_pitch  # Coefficient of variation
if wraps >= 10 and cv < 0.20: confidence = "HIGH"
elif wraps >= 5 and cv < 0.35: confidence = "MEDIUM"
else: confidence = "LOW"
```

## Important Patterns

### State Management
- Internal state should always reflect PUI state
- When PUI signal received → update state → update GUI
- GUI changes are temporary until confirmed by PUI

### Camera Frame Processing
```python
# Main loop pattern
while running:
    frame = camera.read()
    if manual_mode:
        frame = draw_overlay_lines(frame, pitch_px, angle_deg)
    result = estimate_pitch(frame)  # Only in auto mode
    update_gui(frame, result)
```

### Settings Persistence
All configuration saved to OS-standard config dir (see "File Structure")
and loaded on startup. Includes:
- Target pitch, wire thickness, tube diameter
- Detent-to-speed mappings (six values: dial × {small,medium,large})
- Manual mode GUI enable flag
- "Remember settings" preference

## Common Tasks

### Adding a new PUI message type
1. Add a regex/match case in `parse_pui_message()` in [`comms/pui.py`](interface/comms/pui.py)
2. Add a new dataclass for the message type alongside `DialChange`/`ModeSwitch`/`PowerToggle`
3. Add a signal on `PUIListener` and emit it from `_poll()`
4. Add an `apply_*` handler on [`AppState`](interface/app_state.py)
5. Wire the listener signal → AppState handler in `MainWindow._connect_app_state_signals()`
6. Add a unit test in [`tests/test_pui_protocol.py`](interface/tests/test_pui_protocol.py)
   and [`tests/test_app_state.py`](interface/tests/test_app_state.py)

### Adding a new motor SPI command
1. Add prefix to `CommandPrefix` enum in [`comms/motor_spi.py`](interface/comms/motor_spi.py)
2. Write a `build_<cmd>()` builder + bounds checks
3. Add a method on `MotorController`
4. Add a unit test in [`tests/test_motor_spi.py`](interface/tests/test_motor_spi.py)

### Changing pitch estimation parameters
Edit [`image-processing/pitch_estimate.py`](image-processing/pitch_estimate.py) —
key params: `min_dist_px`, `sigma`, `prom_factor`.

## Testing Notes

- **Protocol tests** (no hardware): `pytest tests/test_pui_protocol.py tests/test_motor_spi.py tests/test_app_state.py`
- **PUI precedence**: Set GUI mode to MANUAL, then `apply_mode_switch(AUTO)` — state must be AUTO (covered by `test_gui_change_then_pui_overrides`)
- **Manual Mode warning**: Manual mode toggle hidden unless `AppConfig.manual_mode_gui_enabled = True`
- **TP → motor packets**: Toggling power must emit a START packet to both motors with current speeds, and STOP (RAMP_DOWN) on the next toggle (covered by `TestPowerToggle`)
- Test scale calibration: Without calibration, overlay spacing will be wrong