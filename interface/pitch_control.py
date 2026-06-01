"""
Pitch-control backend.

Shared control path used by both the live camera pipeline (later) and the
HIL runner (now). No camera code or pitch_estimate.py is imported here.

Architecture:
    PitchMeasurement  →  process_pitch_result()  →  app_state.gui_set_feed_speed()
                                                  →  app_state.gui_set_mode(MANUAL)

The wrapper motor speed is fixed. Only the feed motor speed is adjusted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from app_state import AppState, Mode, FEED_SPEED_MIN_MMS, FEED_SPEED_MAX_MMS
from config import AppConfig

# Fractional deadband: skip correction if |measured - target| / target < DEADBAND.
# Avoids repeated tiny commands from sensor noise.
DEADBAND = 0.02   # 2 %

# Minimum wrap count before a correction reading is trusted.
MIN_WRAPS_FOR_CORRECTION = 3


@dataclass
class PitchMeasurement:
    """Minimal pitch result consumed by the control backend.

    Both the camera pipeline and the HIL runner produce this object so
    process_pitch_result() never depends on pitch_estimate.py internals.
    """
    measured_pitch_mm: float
    confidence: str       # "HIGH" | "MEDIUM" | "LOW" | "FAILED"  (normalised internally)
    num_wraps: int
    source: str = "camera"


def measurement_from_pitch_result(result, source: str = "camera") -> PitchMeasurement:
    """Convert a camera ``PitchResult`` into the shared ``PitchMeasurement``.

    This is the single seam between the camera pipeline and the control
    backend; the HIL runner builds ``PitchMeasurement`` directly. ``result``
    only needs ``mean_pitch_um``, ``confidence`` and ``num_wraps``.
    """
    return PitchMeasurement(
        measured_pitch_mm=result.mean_pitch_um / 1000.0,
        confidence=result.confidence,
        num_wraps=result.num_wraps,
        source=source,
    )


def calculate_corrected_feed_speed(
    current_feed_speed_mm_s: float,
    target_pitch_mm: float,
    measured_pitch_mm: float,
    min_feed_speed_mm_s: float,
    max_feed_speed_mm_s: float,
    correction_gain: float = 1.0,
) -> float:
    """Return the clamped corrected feed speed for one measurement.

    Direct ratio correction (shared by AUTO and HIL):
        direct = current * (target / measured)

    Applied through a proportional gain:
        new = current + correction_gain * (direct - current)

    Default behaviour is full ratio correction. Set correction_gain < 1.0
    only if testing shows corrections are too aggressive.

    The caller must ensure target and measured pitch are > 0.
    """
    direct_feed_speed = current_feed_speed_mm_s * (target_pitch_mm / measured_pitch_mm)
    new_feed_speed = (
        current_feed_speed_mm_s
        + correction_gain * (direct_feed_speed - current_feed_speed_mm_s)
    )
    return max(min_feed_speed_mm_s, min(max_feed_speed_mm_s, new_feed_speed))


def compute_initial_feed_speed_mm_s(
    wrapper_rpm: float,
    target_pitch_mm: float,
    tube_diameter_mm: float,
    wire_diameter_mm: float,
) -> Optional[float]:
    """Theoretical initial feed speed (mm/s) for AUTO startup only.

    Research-paper geometry — do NOT use measured pitch here; that belongs
    to live correction (calculate_corrected_feed_speed).

        v = wrapper_rps / sqrt(1/D2^2 - 1/(4*pi^2*(r + D1/2)^2))

    with D2 = target_pitch_mm, r = tube_diameter_mm/2, D1 = wire_diameter_mm,
    wrapper_rps = wrapper_rpm / 60.

    Returns None for invalid inputs (non-positive geometry/speed or a
    non-positive square-root argument) so the caller can skip applying it.
    """
    if target_pitch_mm <= 0:
        return None
    if tube_diameter_mm <= 0:
        return None
    if wire_diameter_mm < 0:
        return None
    if wrapper_rpm <= 0:
        return None

    wrapper_rps = wrapper_rpm / 60.0
    effective_radius_mm = tube_diameter_mm / 2.0 + wire_diameter_mm / 2.0

    sqrt_arg = (
        1.0 / (target_pitch_mm ** 2)
        - 1.0 / (4.0 * math.pi ** 2 * effective_radius_mm ** 2)
    )
    if sqrt_arg <= 0:
        return None

    return wrapper_rps / math.sqrt(sqrt_arg)


def process_pitch_result(
    measurement: PitchMeasurement,
    app_state: AppState,
    config: AppConfig,
    telemetry=None,
    correction_gain: float = 1.0,
) -> str:
    """Apply one pitch measurement to the feed-speed control loop.

    Returns a short log string describing what happened and why.
    This is the single shared control path for both HIL and live camera input.

    Wrapper motor speed is intentionally left unchanged — only the feed
    motor speed is adjusted.

    If a ``telemetry`` (TelemetryLog) is given, each call records one command
    (sent or blocked); a valid reading first closes out the previous sent
    command as its "after" pitch (for response time / pitch sensitivity).
    """
    conf = measurement.confidence.upper()
    src = measurement.source
    prev = app_state.feed_speed_mms
    target_mm = config.target_pitch_um / 1000.0
    mode = "HIL" if src == "HIL" else app_state.mode.value.upper()

    valid_reading = conf in ("HIGH", "MEDIUM") and measurement.measured_pitch_mm > 0
    measured_before = measurement.measured_pitch_mm if valid_reading else None

    # A valid reading is the "after" pitch for the previous sent command.
    if telemetry is not None and valid_reading:
        telemetry.record_pitch_after(measurement.measured_pitch_mm)

    def _finish(reason: str, sent: bool, commanded: float) -> str:
        if telemetry is not None:
            rec = telemetry.record_command(
                mode=mode,
                source=src,
                target_pitch_mm=target_mm,
                previous_feed_speed_mm_s=prev,
                commanded_feed_speed_mm_s=commanded,
                command_sent_successfully=sent,
                reason=reason,
                measured_pitch_before_mm=measured_before,
            )
            rec.confidence = conf
            rec.correction_gain = correction_gain
            rec.resulting_mode = app_state.mode.value.upper()
        return reason

    # --- LOW / FAILED: switch to manual mode immediately, no correction ----
    if conf in ("LOW", "FAILED"):
        app_state.gui_set_mode(Mode.MANUAL)
        if app_state.mode != Mode.MANUAL:
            # gui_set_mode(MANUAL) is normally always allowed; log if somehow blocked.
            return _finish(
                f"[{src}] confidence={conf} → tried MANUAL mode but mode change was"
                f" blocked (current mode: {app_state.mode.value}); no correction",
                False, prev,
            )
        return _finish(
            f"[{src}] confidence={conf} → switched to MANUAL mode, no correction",
            False, prev,
        )

    # --- Precondition guards -------------------------------------------------
    if not app_state.machine_on:
        return _finish(f"[{src}] machine off → no correction", False, prev)
    if app_state.mode != Mode.AUTO:
        return _finish(f"[{src}] mode={app_state.mode.value} → no correction", False, prev)
    if measurement.num_wraps < MIN_WRAPS_FOR_CORRECTION:
        return _finish(
            f"[{src}] only {measurement.num_wraps} wraps"
            f" (need >= {MIN_WRAPS_FOR_CORRECTION}) → no correction",
            False, prev,
        )

    if target_mm <= 0:
        return _finish(
            f"[{src}] target pitch <= 0 ({config.target_pitch_um} um) → no correction",
            False, prev,
        )
    if measurement.measured_pitch_mm <= 0:
        return _finish(
            f"[{src}] measured pitch <= 0"
            f" ({measurement.measured_pitch_mm} mm) → no correction",
            False, prev,
        )

    # --- Deadband check ------------------------------------------------------
    error_fraction = abs(measurement.measured_pitch_mm - target_mm) / target_mm
    if error_fraction < DEADBAND:
        return _finish(
            f"[{src}] error {error_fraction * 100:.2f}% within"
            f" {DEADBAND * 100:.0f}% deadband → no correction",
            False, prev,
        )

    # --- Proportional feed-speed correction ----------------------------------
    new_speed = calculate_corrected_feed_speed(
        current_feed_speed_mm_s=prev,
        target_pitch_mm=target_mm,
        measured_pitch_mm=measurement.measured_pitch_mm,
        min_feed_speed_mm_s=FEED_SPEED_MIN_MMS,
        max_feed_speed_mm_s=FEED_SPEED_MAX_MMS,
        correction_gain=correction_gain,
    )

    # MVP: reuse gui_set_feed_speed because it already sends the SET_SPEED SPI
    # packet to the feed motor when the machine is on. A future refactor could
    # separate auto-control writes from operator GUI writes if needed.
    app_state.gui_set_feed_speed(new_speed)

    return _finish(
        f"[{src}] measured={measurement.measured_pitch_mm:.3f}mm"
        f" target={target_mm:.3f}mm"
        f" error={error_fraction * 100:.1f}%"
        f" → feed {prev:.3f}→{new_speed:.3f} mm/s",
        True, new_speed,
    )
