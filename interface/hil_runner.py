"""
HIL scenario runner and CSV telemetry exporter.

Defines five predefined test scenarios, runs them through the shared
pitch-control backend with mock SPI transports, injects simulated motor
feedback for response-time telemetry, and exports results to CSV.
Each scenario is a sequence of pitch measurements with associated confidence levels, designed to test specific aspects of the pitch-control logic. The
"manual_command" scenario simulates a direct feed-speed change from the GUI/PUI without any pitch measurement, to verify that manual commands are handled correctly and logged in telemetry.
"""

from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import AppConfig
from hil_test import make_hil_state
from pitch_control import PitchMeasurement, process_pitch_result
from telemetry import TelemetryLog, SpeedCommand


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

@dataclass
class HILScenario:
    key: str
    name: str
    description: str
    pitches_mm: list
    confidences: list


HIL_SCENARIOS: dict[str, HILScenario] = {
    "under_pitch": HILScenario(
        key="under_pitch",
        name="Under-pitch correction",
        description="Measured pitch below target — feed speed should increase then stabilise",
        pitches_mm=[5.0, 5.5, 5.8, 6.0],
        confidences=["HIGH", "HIGH", "HIGH", "HIGH"],
    ),
    "over_pitch": HILScenario(
        key="over_pitch",
        name="Over-pitch correction",
        description="Measured pitch above target — feed speed should decrease then stabilise",
        pitches_mm=[7.0, 6.6, 6.2, 6.0],
        confidences=["HIGH", "HIGH", "HIGH", "HIGH"],
    ),
    "mixed": HILScenario(
        key="mixed",
        name="Mixed correction",
        description="Alternating over/under — feed speed adjusts up/down appropriately",
        pitches_mm=[5.0, 6.5, 5.8, 6.0],
        confidences=["HIGH", "HIGH", "HIGH", "HIGH"],
    ),
    "low_confidence": HILScenario(
        key="low_confidence",
        name="Low-confidence trigger",
        description="Confidence LOW → Manual Mode activates immediately, no command sent",
        pitches_mm=[5.0],
        confidences=["LOW"],
    ),
    "manual_command": HILScenario(
        key="manual_command",
        name="Manual speed command",
        description="Direct feed-speed change (GUI/PUI) — telemetry logged, no pitch estimate",
        pitches_mm=[],
        confidences=[],
    ),
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def run_hil_scenario(
    scenario: HILScenario,
    config: AppConfig,
    initial_feed_speed_mm_s: float = 10.0,
    correction_gain: float = 1.0,
    mock_feedback_delay_ms: float = 150.0,
    manual_feed_speed_mm_s: Optional[float] = None,
) -> tuple[TelemetryLog, list[str], str]:
    """Run a single HIL scenario. Returns (telemetry_log, step_logs, run_id).

    Uses mock SPI transports — no hardware required. Simulated motor-feedback
    packets are injected ``mock_feedback_delay_ms`` after each sent command
    to populate ``motor_response_time_ms`` in the telemetry record.
    """
    run_id = uuid.uuid4().hex[:8]
    state, wrap_t, feed_t = make_hil_state(config)
    state.gui_set_machine_on(True)
    state.gui_set_feed_speed(initial_feed_speed_mm_s)
    wrap_t.sent.clear()
    feed_t.sent.clear()

    tlog = TelemetryLog()
    step_logs: list[str] = []

    if scenario.key == "manual_command":
        target_speed = (
            manual_feed_speed_mm_s
            if manual_feed_speed_mm_s is not None
            else initial_feed_speed_mm_s
        )
        prev = state.feed_speed_mms
        state.gui_set_feed_speed(target_speed)
        rec = tlog.record_command(
            mode="MANUAL",
            source="GUI/PUI",
            target_pitch_mm=config.target_pitch_um / 1000.0,
            previous_feed_speed_mm_s=prev,
            commanded_feed_speed_mm_s=target_speed,
            command_sent_successfully=True,
            reason="manual feed change",
        )
        rec.resulting_mode = state.mode.value.upper()
        _inject_mock_feedback(tlog, state.feed_speed_mms, mock_feedback_delay_ms)
        step_logs.append(f"[MANUAL] feed {prev:.3f}→{target_speed:.3f} mm/s")
        return tlog, step_logs, run_id

    for pitch_mm, conf in zip(scenario.pitches_mm, scenario.confidences):
        m = PitchMeasurement(
            measured_pitch_mm=pitch_mm,
            confidence=conf,
            num_wraps=10,
            source="HIL",
        )
        log = process_pitch_result(
            m, state, config,
            telemetry=tlog,
            correction_gain=correction_gain,
        )
        step_logs.append(log)
        _inject_mock_feedback(tlog, state.feed_speed_mms, mock_feedback_delay_ms)

    return tlog, step_logs, run_id


def _inject_mock_feedback(
    tlog: TelemetryLog, feed_speed_mm_s: float, delay_ms: float
) -> None:
    """If the latest record was a sent command, inject a simulated feedback
    packet so motor_response_time_ms is populated in the telemetry."""
    last = tlog.last
    if (
        last is not None
        and last.command_sent_successfully
        and last.timestamp_command_sent is not None
        and last.motor_response_time_ms is None
    ):
        mock_ts = last.timestamp_command_sent + delay_ms / 1000.0
        # Simulated actual speed: 99 % of commanded (mock hardware latency).
        tlog.record_motor_feedback(feed_speed_mm_s * 0.99, now=mock_ts)


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "run_id", "step", "timestamp", "mode", "source",
    "target_pitch_mm", "measured_pitch_mm", "confidence",
    "previous_feed_speed_mm_s", "commanded_feed_speed_mm_s", "speed_delta_mm_s",
    "correction_gain", "command_sent", "timestamp_command_sent",
    "mock_actual_feed_speed_mm_s", "timestamp_motor_feedback_received",
    "motor_response_time_ms", "next_pitch_mm", "pitch_change_mm",
    "pitch_sensitivity_per_feed_speed", "blocked_reason", "resulting_mode",
]


def export_csv(
    records: list[SpeedCommand],
    output_path: Path | str,
    run_id: str,
) -> Path:
    """Write telemetry records to a CSV file. Returns the written path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for step, rec in enumerate(records, start=1):
            writer.writerow({
                "run_id": run_id,
                "step": step,
                "timestamp": rec.timestamp_command_requested,
                "mode": rec.mode,
                "source": rec.source,
                "target_pitch_mm": rec.target_pitch_mm,
                "measured_pitch_mm": rec.measured_pitch_before_mm,
                "confidence": rec.confidence,
                "previous_feed_speed_mm_s": rec.previous_feed_speed_mm_s,
                "commanded_feed_speed_mm_s": rec.commanded_feed_speed_mm_s,
                "speed_delta_mm_s": rec.speed_delta_mm_s,
                "correction_gain": rec.correction_gain,
                "command_sent": rec.command_sent_successfully,
                "timestamp_command_sent": rec.timestamp_command_sent,
                "mock_actual_feed_speed_mm_s": rec.actual_feed_speed_mm_s,
                "timestamp_motor_feedback_received": rec.timestamp_motor_feedback_received,
                "motor_response_time_ms": rec.motor_response_time_ms,
                "next_pitch_mm": rec.measured_pitch_after_mm,
                "pitch_change_mm": rec.pitch_change_mm,
                "pitch_sensitivity_per_feed_speed": rec.pitch_sensitivity_per_feed_speed,
                "blocked_reason": rec.reason if not rec.command_sent_successfully else "",
                "resulting_mode": rec.resulting_mode,
            })

    return output_path


def default_csv_path() -> Path:
    """Sensible default export path: ~/Silverworm/hil/hil_run_<timestamp>.csv"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.home() / "Silverworm" / "hil" / f"hil_run_{ts}.csv"
