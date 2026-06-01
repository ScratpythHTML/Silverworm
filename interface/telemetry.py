"""
Minimal speed-command telemetry for the testing report.

One record per feed-speed command (AUTO / HIL / MANUAL), progressively filled
as motor feedback and the next pitch estimate arrive. Used to measure motor
response time and pitch sensitivity (Δpitch per Δfeed) for PUI detent
calibration.

No database, no plotting — just a list of dataclass records held in memory.
The same TelemetryLog is shared by the camera (AUTO), HIL and manual paths so
the report data is uniform.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional


# Feed actual-vs-commanded difference (mm/s) above which a non-blocking
# mismatch warning is raised. Configurable via TelemetryLog(...).
DEFAULT_MISMATCH_TOLERANCE_MM_S = 0.5


@dataclass
class SpeedCommand:
    """One feed-speed command and everything we learn about it afterwards."""
    # --- known when the command is issued ---
    timestamp_command_requested: float
    mode: str                                   # "AUTO" | "MANUAL" | "HIL"
    source: str                                 # "camera" | "HIL" | "GUI" | "PUI" | ...
    target_pitch_mm: float
    previous_feed_speed_mm_s: float
    commanded_feed_speed_mm_s: float
    speed_delta_mm_s: float
    command_sent_successfully: bool
    reason: str = ""                            # correction reason or blocked reason
    confidence: str = ""                        # HIGH | MEDIUM | LOW | FAILED | ""
    correction_gain: float = 1.0
    resulting_mode: str = ""                    # mode after command (may differ for LOW/FAILED)
    measured_pitch_before_mm: Optional[float] = None
    timestamp_command_sent: Optional[float] = None
    # --- filled when motor feedback arrives ---
    timestamp_motor_feedback_received: Optional[float] = None
    actual_feed_speed_mm_s: Optional[float] = None
    motor_response_time_ms: Optional[float] = None
    # --- filled when the next valid pitch estimate arrives ---
    measured_pitch_after_mm: Optional[float] = None
    timestamp_next_pitch: Optional[float] = None
    pitch_response_time_ms: Optional[float] = None
    pitch_change_mm: Optional[float] = None
    pitch_sensitivity_per_feed_speed: Optional[float] = None


class TelemetryLog:
    """Records speed commands and fills in feedback / pitch fields later.

    A single "pending" command (the last one that actually changed the feed
    speed) awaits its motor feedback and the next valid pitch estimate.
    """

    def __init__(self, mismatch_tolerance_mm_s: float = DEFAULT_MISMATCH_TOLERANCE_MM_S):
        self.mismatch_tolerance_mm_s = mismatch_tolerance_mm_s
        self.records: List[SpeedCommand] = []
        self.last_actual_feed_speed_mm_s: Optional[float] = None
        self._pending: Optional[SpeedCommand] = None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_command(
        self,
        *,
        mode: str,
        source: str,
        target_pitch_mm: float,
        previous_feed_speed_mm_s: float,
        commanded_feed_speed_mm_s: float,
        command_sent_successfully: bool,
        reason: str,
        measured_pitch_before_mm: Optional[float] = None,
        now: Optional[float] = None,
    ) -> SpeedCommand:
        """Log a command attempt (sent or blocked). Returns the new record."""
        now = time.monotonic() if now is None else now
        rec = SpeedCommand(
            timestamp_command_requested=now,
            mode=mode,
            source=source,
            target_pitch_mm=target_pitch_mm,
            previous_feed_speed_mm_s=previous_feed_speed_mm_s,
            commanded_feed_speed_mm_s=commanded_feed_speed_mm_s,
            speed_delta_mm_s=commanded_feed_speed_mm_s - previous_feed_speed_mm_s,
            command_sent_successfully=command_sent_successfully,
            reason=reason,
            measured_pitch_before_mm=measured_pitch_before_mm,
        )
        if command_sent_successfully:
            rec.timestamp_command_sent = now
        self.records.append(rec)
        # Only a real, sent speed change awaits motor feedback + the next pitch.
        if command_sent_successfully and rec.speed_delta_mm_s != 0:
            self._pending = rec
        return rec

    def record_motor_feedback(
        self, actual_feed_speed_mm_s: float, now: Optional[float] = None
    ) -> Optional[SpeedCommand]:
        """Store the latest actual feed speed; fill motor-response timing on the
        pending command using the FIRST feedback packet after it was sent."""
        now = time.monotonic() if now is None else now
        self.last_actual_feed_speed_mm_s = actual_feed_speed_mm_s
        rec = self._pending
        if (
            rec is not None
            and rec.timestamp_command_sent is not None
            and rec.motor_response_time_ms is None
        ):
            rec.timestamp_motor_feedback_received = now
            rec.actual_feed_speed_mm_s = actual_feed_speed_mm_s
            rec.motor_response_time_ms = (now - rec.timestamp_command_sent) * 1000.0
            return rec
        return None

    def record_pitch_after(
        self, measured_pitch_after_mm: float, now: Optional[float] = None
    ) -> Optional[SpeedCommand]:
        """Close out the pending command with the next valid pitch estimate:
        compute pitch response time, pitch change and sensitivity."""
        now = time.monotonic() if now is None else now
        rec = self._pending
        if rec is None or rec.timestamp_command_sent is None:
            return None
        rec.measured_pitch_after_mm = measured_pitch_after_mm
        rec.timestamp_next_pitch = now
        rec.pitch_response_time_ms = (now - rec.timestamp_command_sent) * 1000.0
        if rec.measured_pitch_before_mm is not None:
            rec.pitch_change_mm = measured_pitch_after_mm - rec.measured_pitch_before_mm
            if rec.speed_delta_mm_s != 0:
                rec.pitch_sensitivity_per_feed_speed = (
                    rec.pitch_change_mm / rec.speed_delta_mm_s
                )
            # speed_delta == 0 → sensitivity left as None (skipped safely)
        self._pending = None
        return rec

    # ------------------------------------------------------------------
    # Read helpers (for the GUI / report)
    # ------------------------------------------------------------------

    @property
    def last(self) -> Optional[SpeedCommand]:
        return self.records[-1] if self.records else None

    def _last_with(self, attr: str):
        for rec in reversed(self.records):
            value = getattr(rec, attr)
            if value is not None:
                return value
        return None

    @property
    def last_motor_response_time_ms(self) -> Optional[float]:
        return self._last_with("motor_response_time_ms")

    @property
    def last_pitch_response_time_ms(self) -> Optional[float]:
        return self._last_with("pitch_response_time_ms")

    @property
    def last_pitch_change_mm(self) -> Optional[float]:
        return self._last_with("pitch_change_mm")

    @property
    def last_pitch_sensitivity_per_feed_speed(self) -> Optional[float]:
        return self._last_with("pitch_sensitivity_per_feed_speed")

    def actual_feed_speed_display(self) -> str:
        """GUI string: the actual feed speed, or a waiting placeholder."""
        if self.last_actual_feed_speed_mm_s is None:
            return "Waiting for feedback"
        return f"{self.last_actual_feed_speed_mm_s:.3f} mm/s"

    def mismatch_warning(self, commanded_feed_speed_mm_s: float) -> Optional[str]:
        """Non-blocking warning if the latest actual feed speed differs from the
        commanded speed beyond the tolerance. Returns None otherwise.

        A single mismatch must NOT switch the machine to Manual Mode — callers
        only surface this as a warning.
        """
        actual = self.last_actual_feed_speed_mm_s
        if actual is None:
            return None
        if abs(actual - commanded_feed_speed_mm_s) > self.mismatch_tolerance_mm_s:
            return (
                f"Feed speed mismatch: commanded {commanded_feed_speed_mm_s:.3f} mm/s, "
                f"actual {actual:.3f} mm/s"
            )
        return None
