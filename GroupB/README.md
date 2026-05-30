# Collecting-system firmware (Arduino Uno R2)

For **STM32CubeIDE** (bare metal), see `[stm32/motors/README.md](../../stm32/motors/README.md)`.

Target board: **Arduino Uno R2** (ATmega328P).


| Subsystem           | Hardware                      | Interface                                   |
| ------------------- | ----------------------------- | ------------------------------------------- |
| Linear rail         | FSK40J + NEMA 23 + **DM423T** | STEP / DIR / ENA → D2–D4                    |
| Collecting spool    | 42BSA62 + **oDrive S1**       | UART → D8–D9; encoder **#1** on oDrive ENC0 |
| Line / roller shaft | IHC3808 encoder **#2**        | Quadrature A/B/(Z) → D5–D7                  |
| Supervisor          | Raspberry Pi                  | SPI slave → D10–D13                         |


No USB serial commands in production — control is **SPI only** (`SpiProtocol.h`).

## Uno pin map (ATmega328P)


| Arduino pin | ATmega328P port | Function                       |
| ----------- | --------------- | ------------------------------ |
| D2          | PD2             | Linear STEP → DM423T PUL+      |
| D3          | PD3             | Linear DIR → DM423T DIR+       |
| D4          | PD4             | Linear ENA → DM423T ENA+       |
| D5          | PD5             | Encoder #2 A                   |
| D6          | PD6             | Encoder #2 B                   |
| D7          | PD7             | Encoder #2 Z (index, optional) |
| D8          | PB0             | oDrive UART RX ← oDrive TX     |
| D9          | PB1             | oDrive UART TX → oDrive RX     |
| D10         | PB2             | SPI SS (CS) ← Pi               |
| D11         | PB3             | SPI MOSI ← Pi                  |
| D12         | PB4             | SPI MISO → Pi                  |
| D13         | PB5             | SPI SCK ← Pi                   |
| A0          | PC0             | Limit switch min (optional)    |
| A1          | PC1             | Limit switch max (optional)    |


DM423T **PUL−, DIR−, ENA−** → Arduino **GND**.

`config.h` uses Arduino pin numbers (`2`–`13`, `A0`/`A1`) as on the Uno.

## Power and grounds

- **24 V** → DM423T and oDrive motor supply (common GND).
- **5 V** → DM423T logic (if required), oDrive `ISO_VDD` (set logic level per [oDrive UART docs](https://docs.odriverobotics.com/v/latest/manual/uart.html)).
- Uno I/O is **5 V**. Level-shift SPI and UART to the Pi and oDrive if those interfaces expect 3.3 V.
- **Pi GND** ↔ Arduino GND.

## oDrive setup (ODrive Tool / Web GUI)

Before relying on firmware:

1. Motor phases → oDrive; **incremental encoder #1** on **ENC0** (A, B, Z).
2. Set `inc_encoder0.config.cpr` (typically **8000** for 2000 PPR quadrature).
3. Run encoder calibration and closed-loop test.
4. Enable UART A at `**ODRIVE_BAUD` (19200)**. Firmware uses **SoftwareSerial** on D8/D9 — the Uno has only one hardware UART (D0/D1, used by USB serial). To use hardware Serial instead, rewire to D0/D1 and switch `BldcMotor` to `HardwareSerial` (Serial).
5. Match GPIO UART pins on the S1 to your harness.
6. Optional: save `vel_ramp_rate` in the GUI if you tune ramping there — firmware also sets **velocity ramp** (`INPUT_MODE_VEL_RAMP`) at boot to match `SPI_SPEED_RAMP_RPM_S` in `config.h`.

Firmware uses the **[ODriveArduino](https://docs.odriverobotics.com/v/latest/guides/arduino-uart-guide.html)** library (`ODriveUART`: `setVelocity`, `getFeedback`, `clearErrors`, closed-loop state).

## Encoder #2

Counted in firmware via GPIO interrupts on D5 and D6 (PD5, PD6). `lineEncoder.rpm()` is updated in `poll()` for local use (ratio / monitoring). SPI telemetry prefix `'1'` still reports **spool** RPM from oDrive feedback.

Set `ENC2_CPR` in `config.h` to match the IHC3808 datasheet.

## SPI protocol

See `SpiProtocol.h` and the transaction rules in the previous sections of this README.

Outbound priority: **error** > **sequence ack** > **live spool speed**.

## Build

1. Install the **Arduino IDE** (2.x recommended) with the standard **Arduino AVR Boards** package.
2. Install **ODriveArduino**: *Sketch → Include Library → Manage Libraries* → "ODriveArduino".
3. Open `motors.ino`.
4. Board: **Arduino Uno** (Tools → Board → Arduino AVR Boards → Arduino Uno).
5. Edit `config.h` (stroke, CPR, limits).
6. Upload via USB.

## Calibration

1. Set `LINEAR_STROKE_MM_DEFAULT` to your FSK40J stroke.
2. Home linear axis (limits on A0/A1 when wired).
3. Confirm oDrive enters closed loop and spool feedback RPM matches direction before coupling yarn.

