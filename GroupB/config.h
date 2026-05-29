#pragma once

// =============================================================================
// Pin assignments — Arduino Uno R2 (ATmega328P)
// =============================================================================

// --- FSK40J linear stage (NEMA 23 via DM423T) ---
#define LINEAR_STEP_PIN         2   // D2
#define LINEAR_DIR_PIN          3   // D3
#define LINEAR_ENABLE_PIN       4   // D4
// DM423T PUL-/DIR-/ENA- → Nucleo GND

// --- Second-shaft encoder #2 (IHC3808 on roller / line) ---
#define ENC2_A_PIN              5   // D5
#define ENC2_B_PIN              6   // D6
#define ENC2_Z_PIN              7   // D7 — index; set -1 if not wired
#define ENC2_CPR                8000 // 2000 PPR × 4 (quadrature); verify datasheet

// --- oDrive S1 UART (42BSA62; encoder #1 on oDrive ENC0) ---
#define ODRIVE_UART_RX_PIN      8   // D8  ← oDrive TX
#define ODRIVE_UART_TX_PIN      9   // D9  → oDrive RX
#define ODRIVE_BAUD             19200
#define ODRIVE_AXIS             0

// --- SPI slave to Raspberry Pi (hardware SPI pins on Uno) ---
// D10 SS (NSS/CS), D11 MOSI, D12 MISO, D13 SCK

// Limit switches (optional)
#define LINEAR_LIMIT_MIN_PIN      A0
#define LINEAR_LIMIT_MAX_PIN      A1

// =============================================================================
// Linear stage (FSK40J + NEMA 23)
// =============================================================================

#define LINEAR_FULL_STEPS_PER_REV  200
#define LINEAR_SCREW_LEAD_MM       10.0f
#define LINEAR_MICROSTEPS          16
#define LINEAR_ENABLE_ACTIVE_LOW   true

#define LINEAR_STROKE_MM_DEFAULT   250.0f
#define LINEAR_MAX_SPEED_MM_S      150.0f
#define LINEAR_MAX_ACCEL_MM_S2     800.0f

// =============================================================================
// Collecting spool BLDC (42BSA62 via oDrive S1)
// =============================================================================

#define BLDC_RATED_RPM             3000
#define ODRIVE_FEEDBACK_INTERVAL_MS  50
#define SPI_SPEED_RAMP_RPM_S       500

// =============================================================================
// Second-shaft encoder telemetry
// =============================================================================

#define ENC2_RPM_FILTER_MS         100

// =============================================================================
// SPI / bench
// =============================================================================

#define SPI_TEST_LED_PIN           LED_BUILTIN
#define SPI_TEST_PULSE_MS          500

// =============================================================================
// Feature flags
// =============================================================================

// Set to 1 to compile BldcMotor (ODriveUART + SoftwareSerial) and LinearStage.
// Keep 0 when doing SPI-only development — avoids the PCINT2_vect conflict
// between SoftwareSerial and ShaftEncoder.
#define MOTORS_ENABLED             0
