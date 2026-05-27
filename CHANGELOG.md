# Changelog

## 2026-05-18 (afternoon) — GUI/AppState unification + test cleanup

Pi bring-up tomorrow. Before-the-bench cleanup so the SPI mock path
exercises identically whether the trigger came from the panel or the
GUI, and so `pytest` is trustworthy on the Pi.

### GUI now routes through AppState

Previously the GUI buttons updated the UI directly while only PUI events
(via the Debug menu) reached `AppState` and the SPI mock. Today they
share the same path:

- **START / STOP** ([app.py:1394–1399](interface/app.py)) — `_on_start` /
  `_on_stop` now do nothing but call `app_state.gui_set_machine_on(True/False)`.
  All the UI work (status label, indicators, pitch-pipeline start/stop)
  moved into a new `_apply_running_ui_state(bool)` handler connected to
  `app_state.machine_power_changed`. PUI `TP` and the GUI buttons both
  emit the same SPI Start/Stop packets.
- **Manual mode toggle** — `_on_manual_mode_button` now calls
  `app_state.gui_set_mode(MANUAL/AUTO)`; the legacy `SetpointController`
  call is kept so the low-confidence auto-trigger path still works.
  UI manual-mode highlighting is driven by `app_state.mode_changed`.
- **Manual speed inputs** — `_on_feed_motor_set` and `_on_wrapper_motor_set`
  call `app_state.gui_set_feed_speed(value)` /
  `gui_set_wrap_speed(value)` before the legacy controller path. SET
  buttons now emit `SET_SPEED` SPI packets when the machine is running.

Verified end-to-end:
```
GUI START      → wrap_spi: 01 00 00  (Start, speed 0 LE)
                 feed_spi: 01 00 00
PUI 'TP'       → wrap_spi: 02 01     (Stop, RAMP_DOWN)
GUI 2.5 rpm    → wrap_spi: 03 19 00  (Set speed, 25 units = 2.5 × 10)
   (running)
```

### Test cleanup

- Installed `pytest-qt` and `pytest-mock` (already listed in
  [requirements.txt](interface/requirements.txt) but never installed in
  the venv). Resolves the recursive `qapp(qapp)` fixture in
  [conftest.py](interface/tests/conftest.py) — pytest-qt now supplies
  the upstream `qapp` it was waiting for.
- Marked the four Linux-only camera-detector tests with `@linux_only`
  (skip on darwin). They'll run for real on the Pi.
- Removed local `qapp` module-scope fixtures in the new test files; they
  shadowed pytest-qt's and risked QCoreApplication / QApplication
  conflicts.

**Result:** `pytest tests/` now reports **131 passed, 4 skipped, 0
failures** on macOS. On the Pi tomorrow, the 4 skipped tests will
execute against real `/dev/video*` enumeration and v4l2-ctl mocks.

### What's still pending for tomorrow

- Swap `MockPUITransport` → `I2CPUITransport(bus=1, address=...)` in
  [`app.py`](interface/app.py) `MainWindow.__init__` once the PUI
  firmware author confirms the I2C address and framing.
- Swap `MockSPITransport` → `SPIMotorTransport(bus=0, device=…)`
  similarly for both motors.
- Confirm Arduino speed units — current scaling assumes `rpm × 10`
  and `mm/s × 1000` (see `WRAP_RPM_UNITS_PER` / `FEED_MMS_UNITS_PER` in
  [`app_state.py`](interface/app_state.py)).
- Resolve the motor-panel unit mismatch: panel labels read "RPM" for
  both, but `AppState.feed_speed` is mm/s. Either rename the panel or
  rescale at the boundary.

---

## 2026-05-18 — Startup config + PUI/SPI protocol layer + state machine

First end-to-end protocol implementation per [CLAUDE.md](CLAUDE.md). All
hardware I/O is abstracted behind interfaces with Mock implementations,
so the system runs and is fully tested on macOS without a Pi.

### Added

**Startup configuration**
- [`interface/config.py`](interface/config.py) — `AppConfig` dataclass, JSON load/save
  to OS-standard location (`~/Library/Preferences/Silverworm/config.json` on macOS,
  `~/.config/Silverworm/config.json` on Linux), `calculate_wrap_angle_deg()`.
- [`interface/ui/startup_dialog.py`](interface/ui/startup_dialog.py) — modal startup
  dialog: Target Pitch / Wire Thickness / Tube Diameter, ⓘ tooltip on pitch,
  live wrap-angle preview (θ = arctan(P / π(D + 2t))), "Remember settings"
  checkbox.

**PUI protocol (I2C, ESP32 → RPi)**
- [`interface/comms/pui.py`](interface/comms/pui.py)
  - Parser for `D1±N`, `D2±N`, `AS0`, `AS1`, `TP` ASCII messages.
  - `DialChange`, `ModeSwitch`, `PowerToggle` typed dataclasses.
  - `PUITransport` ABC + `MockPUITransport` (tests) + `I2CPUITransport`
    (lazy-imports `smbus2`, runs on Pi only).
  - `PUIListener` — Qt timer-driven, emits typed signals.

**Motor protocol (SPI, RPi ↔ Arduino)**
- [`interface/comms/motor_spi.py`](interface/comms/motor_spi.py)
  - Packet builders: `build_start(speed)`, `build_stop(stop_type)`,
    `build_set_speed(speed)`, `build_test_movement(type)`.
  - Speed is 16-bit unsigned, little-endian (`speedL` then `speedH`).
  - Response parser: `CurrentSpeed`, `ErrorResponse`, `SequenceStatus`.
  - `SPITransport` ABC + `MockSPITransport` + `SPIMotorTransport` (lazy `spidev`).
  - `MotorController` — typed wrapper that builds packets and emits signals
    for Arduino responses.

**Central state machine**
- [`interface/app_state.py`](interface/app_state.py) — `AppState` holds `mode`,
  `machine_on`, `wrap_speed_rpm`, `feed_speed_mms`. Receives events from PUI
  (`apply_*`) and GUI (`gui_set_*`). Forwards to two `MotorController`s
  (wrap + feed): toggling power sends `start(speed)` or `stop(RAMP_DOWN)`;
  speed changes while running send `set_speed(units)`.

**Tests** (65 new, all passing in ~0.07s)
- [`tests/test_pui_protocol.py`](interface/tests/test_pui_protocol.py) — message
  parser + mock transport.
- [`tests/test_motor_spi.py`](interface/tests/test_motor_spi.py) — packet
  encoding, response parsing, `MotorController` end-to-end.
- [`tests/test_app_state.py`](interface/tests/test_app_state.py) — dial increments,
  PUI/GUI mode precedence, power toggle → start/stop, speed propagation.

**GUI hooks (minimal)**
- `MainWindow` instantiates `AppState` + `PUIListener` + two `MotorController`s
  with mock transports.
- New **Debug** menu: inject any PUI message (`D1+1`...`TP`) from the GUI.
- All state transitions mirror to the alert log (mode, power, speeds, raw PUI).

### Changed
- [`interface/config.py`](interface/config.py) `DetentConfig` — old single
  field replaced with `dial{1,2}_{small,medium,large}_{rpm,mms}` (six values).
- [`interface/app.py`](interface/app.py) `MainWindow.__init__` — now accepts
  an `AppConfig`. Fixed a PyQt6 strict-typing bug at line 254
  (`QPointF` instead of `QPoint` for `QRadialGradient`).
- [`interface/comms/__init__.py`](interface/comms/__init__.py) — re-exports
  all new PUI/SPI symbols; legacy `transport.py` kept for now since some
  existing GUI code still imports from it.

### How it works

#### Boot path
1. `main()` shows `StartupConfigDialog` (pre-populated from saved config if
   "Remember" was previously checked).
2. On accept, `AppConfig` is constructed, persisted (if remembered), and
   passed into `MainWindow`.
3. `MainWindow` constructs the protocol stack with Mock transports.

#### Event flow (PUI → motor)
```
ESP32 panel
   ↓ I2C ASCII "D1+2"
MockPUITransport.read_messages()
   ↓ polled every 50 ms
PUIListener._poll()
   ↓ parse → DialChange(dial=1, +1, MEDIUM)
PUIListener.dial_changed signal
   ↓
AppState.apply_dial_change()
   ↓ (only mutates in MANUAL mode)
AppState._set_wrap_speed(rpm + 0.5)
   ↓ if machine_on
MotorController.set_speed(rpm_units)
   ↓
MockSPITransport.send(b'\x03\x05\x00')   # prefix=SET_SPEED, speed=0x0005 LE
```

#### Precedence rule
PUI and GUI both call the same internal setters. There is no gate — the
GUI is allowed to write but a later PUI event simply overwrites whatever
it set. That *is* the precedence.

#### Mock vs real
| Symbol | Mock (macOS) | Real (Pi) |
|---|---|---|
| `PUITransport` | `MockPUITransport` (in-memory queue) | `I2CPUITransport` (`smbus2`) |
| `SPITransport` | `MockSPITransport` (records sent, accepts injected responses) | `SPIMotorTransport` (`spidev`) |

Real implementations lazy-import their drivers, so the codebase loads on
any OS. On the Pi, swap two lines in `MainWindow.__init__`.

### Known TODOs (need hardware/firmware specs before they can land)
- `I2CPUITransport` — I2C address (placeholder `0x42`) and framing rule
  awaiting PUI firmware author.
- `SPIMotorTransport.read()` — returns empty until Arduino response framing
  (interrupt vs. polling) is pinned down.
- Speed scaling (`rpm × 10`, `mm/s × 1000`) — verify against motor
  controller's expected units.
- Dial events in AUTO mode currently dropped — confirm desired behaviour.

### Running it

```bash
cd interface
source venv/bin/activate         # macOS — Python 3.14 venv with PyQt6
python app.py                    # launches with mock transports
python -m pytest tests/test_pui_protocol.py tests/test_motor_spi.py tests/test_app_state.py -v
```

Use **Debug → Inject AS0 / TP / D1+2** in the running app to simulate a PUI
session. All transitions appear in the alert log; sent SPI packets are
visible via `MainWindow._wrap_spi.sent` / `_feed_spi.sent`.
