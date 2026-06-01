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

# This creates the fake AppState + mock wrap/feed SPI transports.
# Longer term, make_hil_state could be moved into a neutral helper file.
from hil_test import make_hil_state

from pitch_control import PitchMeasurement, process_pitch_result

from telemetry import TelemetryLog, SpeedCommand


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

@dataclass
class HILScenario:
    """
    Defines one predefined test scenario.

    key:
        Machine-readable scenario name.

    name:
        Human-readable display name for the GUI.

    description:
        Explains what the scenario is testing.

    pitches_mm:
        Dummy measured pitch values that pretend to come from the camera.

    confidences:
        Confidence labels attached to each pitch value.
    """
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
        # Target is usually 6 mm.
        # These values are below target, so backend should increase feed speed.
        pitches_mm=[5.0, 5.5, 5.8, 6.0],
        confidences=["HIGH", "HIGH", "HIGH", "HIGH"],
    ),

    "over_pitch": HILScenario(
        key="over_pitch",
        name="Over-pitch correction",
        description="Measured pitch above target — feed speed should decrease then stabilise",
        # These values are above target, so backend should decrease feed speed.
        pitches_mm=[7.0, 6.6, 6.2, 6.0],
        confidences=["HIGH", "HIGH", "HIGH", "HIGH"],
    ),

    "mixed": HILScenario(
        key="mixed",
        name="Mixed correction",
        description="Alternating over/under — feed speed adjusts up/down appropriately",
        # Alternates below/above target to show the backend can correct both ways.
        pitches_mm=[5.0, 6.5, 5.8, 6.0],
        confidences=["HIGH", "HIGH", "HIGH", "HIGH"],
    ),

    "low_confidence": HILScenario(
        key="low_confidence",
        name="Low-confidence trigger",
        description="Confidence LOW → Manual Mode activates immediately, no command sent",
        # This is testing safety behaviour, not pitch correction.
        # Expected result: switch to Manual Mode and block auto correction.
        pitches_mm=[5.0],
        confidences=["LOW"],
    ),

    "manual_command": HILScenario(
        key="manual_command",
        name="Manual speed command",
        description="Direct feed-speed change (GUI/PUI) — telemetry logged, no pitch estimate",
        # No dummy pitch values because this is meant to simulate a manual user command.
        pitches_mm=[],
        confidences=[],
    ),
}


# ---------------------------------------------------------------------------
# HIL scenario runner
# ---------------------------------------------------------------------------

def run_hil_scenario(
    scenario: HILScenario,
    config: AppConfig,
    initial_feed_speed_mm_s: float = 10.0,
    correction_gain: float = 1.0,
    mock_feedback_delay_ms: float = 150.0,
    manual_feed_speed_mm_s: Optional[float] = None,
) -> tuple[TelemetryLog, list[str], str]:
    """
    Run one predefined HIL scenario.

    Returns:
        telemetry_log:
            Structured telemetry records for CSV export.

        step_logs:
            Human-readable backend log strings.

        run_id:
            Unique ID for this test run, used in CSV export.

    This function is the main report-data generator.

    It uses mock SPI transports, so no hardware is needed.
    """

    # Unique ID for this scenario run.
    # This lets exported CSV rows be grouped by run.
    run_id = uuid.uuid4().hex[:8]

    # Build fake app state:
    # - real AppState
    # - real MotorController objects
    # - mock SPI transports underneath
    state, wrap_t, feed_t = make_hil_state(config)

    # Turn the virtual machine on.
    # This means gui_set_feed_speed(...) will actually send SET_SPEED packets
    # to the mock feed motor transport.
    state.gui_set_machine_on(True)

    # Set initial feed speed before the scenario starts.
    # This is setup, not the correction being tested.
    state.gui_set_feed_speed(initial_feed_speed_mm_s)

    # Clear setup packets so telemetry/results focus only on the scenario.
    wrap_t.sent.clear()
    feed_t.sent.clear()

    # TelemetryLog will store command attempts, motor feedback timings,
    # pitch changes and pitch sensitivity values.
    tlog = TelemetryLog()

    # Human-readable log strings for the GUI/text display.
    step_logs: list[str] = []

    # -----------------------------------------------------------------------
    # Manual command scenario
    # -----------------------------------------------------------------------
    if scenario.key == "manual_command":
        # This simulates the user manually entering a feed speed through GUI/PUI

        target_speed = (
            manual_feed_speed_mm_s
            if manual_feed_speed_mm_s is not None
            else initial_feed_speed_mm_s
        )

        # NOTE:
        # If manual_feed_speed_mm_s is None, this currently defaults to the same
        # speed as the initial feed speed, so it may not actually test a change
        # better default would be initial_feed_speed_mm_s + 2.0
        # but the current code still tests telemetry logging for a manual command

        prev = state.feed_speed_mms

        # This uses the same AppState path as real manual speed input
        # If machine is on, this should send SET_SPEED to the feed motor controller
        state.gui_set_feed_speed(target_speed)

        # Manually record telemetry because this path does not use
        # process_pitch_result(), since there is no pitch measurement
        rec = tlog.record_command(
            mode="MANUAL",
            source="GUI/PUI",
            target_pitch_mm=config.target_pitch_um / 1000.0,
            previous_feed_speed_mm_s=prev,
            commanded_feed_speed_mm_s=target_speed,
            command_sent_successfully=True,
            reason="manual feed change",
        )

        # Store resulting app mode after the command.
        rec.resulting_mode = state.mode.value.upper()

        # Inject fake motor feedback so motor_response_time_ms is populated.
        _inject_mock_feedback(tlog, state.feed_speed_mms, mock_feedback_delay_ms)

        step_logs.append(f"[MANUAL] feed {prev:.3f}→{target_speed:.3f} mm/s")
        return tlog, step_logs, run_id

    # -----------------------------------------------------------------------
    # Pitch-based HIL scenarios
    # -----------------------------------------------------------------------
    for pitch_mm, conf in zip(scenario.pitches_mm, scenario.confidences):

        # Create a fake pitch measurement
        # This is pretending that the camera/computer vision measured pitch_mm
        m = PitchMeasurement(
            measured_pitch_mm=pitch_mm,
            confidence=conf,
            num_wraps=10,
            source="HIL",
        )

        # This is the backend call.
        # It uses the SAME process_pitch_result() function as real auto mode.
        #
        # Inside process_pitch_result:
        # - LOW confidence triggers Manual Mode
        # - HIGH/MEDIUM confidence allows correction
        # - new feed speed is calculated
        # - AppState.gui_set_feed_speed(new_speed) is called
        # - SET_SPEED is sent to the feed motor mock transport
        # - telemetry record is created
        log = process_pitch_result(
            m,
            state,
            config,
            telemetry=tlog,
            correction_gain=correction_gain,
        )

        step_logs.append(log)

        # After each command attempt, inject fake motor feedback
        # This lets the telemetry system calculate motor_response_time_ms
        _inject_mock_feedback(tlog, state.feed_speed_mms, mock_feedback_delay_ms)

    return tlog, step_logs, run_id


def _inject_mock_feedback(
    tlog: TelemetryLog, feed_speed_mm_s: float, delay_ms: float
) -> None:
    """
    Inject simulated motor feedback into the telemetry log.

    In the real system:
        Group B controller would send back actual feed speed.

    In this mock HIL system:
        We fake that feedback after delay_ms.

    This is useful because it lets us test:
        motor_response_time_ms =
            timestamp_motor_feedback_received - timestamp_command_sent

    Important:
        This is NOT real motor response time.
        It only proves that the telemetry pipeline can calculate response time.
    """

    last = tlog.last

    # Only inject feedback if:
    # - there is a telemetry record,
    # - a command was actually sent,
    # - the command has a send timestamp,
    # - response time has not already been filled
    if (
        last is not None
        and last.command_sent_successfully
        and last.timestamp_command_sent is not None
        and last.motor_response_time_ms is None
    ):
        # Fake feedback timestamp = command timestamp + chosen delay
        mock_ts = last.timestamp_command_sent + delay_ms / 1000.0

        # Simulated actual speed.
        # Current code uses 99% of commanded speed, pretending the motor is slightly off
        # This is okay for testing mismatch/feedback plumbing, but be careful:
        # do NOT present this 1% difference as real motor error in the report
        #
        # For cleaner mocked report data, this could be changed to:
        # tlog.record_motor_feedback(feed_speed_mm_s, now=mock_ts)
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
    """
    Export telemetry records to CSV.

    Each SpeedCommand becomes one CSV row.

    This is the file you will use for the testing report.
    Useful columns include:
    - target_pitch_mm
    - measured_pitch_mm
    - previous_feed_speed_mm_s
    - commanded_feed_speed_mm_s
    - speed_delta_mm_s
    - command_sent
    - motor_response_time_ms
    - pitch_change_mm
    - pitch_sensitivity_per_feed_speed
    - blocked_reason
    - resulting_mode
    """

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()

        for step, rec in enumerate(records, start=1):

            # Convert one SpeedCommand dataclass into one CSV row
            writer.writerow({
                "run_id": run_id,
                "step": step,

                # Timestamp when command was requested
                "timestamp": rec.timestamp_command_requested,

                # AUTO / MANUAL / HIL
                "mode": rec.mode,

                # HIL / camera / GUI / PUI
                "source": rec.source,

                "target_pitch_mm": rec.target_pitch_mm,

                # The pitch before correction
                # For HIL this is the dummy pitch value
                "measured_pitch_mm": rec.measured_pitch_before_mm,

                "confidence": rec.confidence,

                # Speed before command
                "previous_feed_speed_mm_s": rec.previous_feed_speed_mm_s,

                # Speed requested by backend/manual command
                "commanded_feed_speed_mm_s": rec.commanded_feed_speed_mm_s,

                # Difference between commanded and previous speed
                "speed_delta_mm_s": rec.speed_delta_mm_s,

                # 1.0 = full direct correction
                # Less than 1.0 = softened correction
                "correction_gain": rec.correction_gain,

                # Whether a command was actually sent
                # False for deadband, low confidence, machine off, etc
                "command_sent": rec.command_sent_successfully,

                "timestamp_command_sent": rec.timestamp_command_sent,

                # Currently named mock_actual... because HIL uses fake feedback
                # Longer term, rename to actual_feed_speed_mm_s if real hardware
                # uses the same CSV format.
                "mock_actual_feed_speed_mm_s": rec.actual_feed_speed_mm_s,

                "timestamp_motor_feedback_received": rec.timestamp_motor_feedback_received,

                # Mock response time for now
                # Real motor response time only when actual Group B feedback is connected
                "motor_response_time_ms": rec.motor_response_time_ms,

                # Next valid pitch after the speed command
                "next_pitch_mm": rec.measured_pitch_after_mm,

                # next_pitch_mm - measured_pitch_mm
                "pitch_change_mm": rec.pitch_change_mm,

                # pitch_change_mm / speed_delta_mm_s
                # Useful for PUI detent calibration
                "pitch_sensitivity_per_feed_speed": rec.pitch_sensitivity_per_feed_speed,

                # Only filled if command was blocked.
                # Examples: deadband, LOW confidence, machine off etc
                "blocked_reason": rec.reason if not rec.command_sent_successfully else "",

                # AUTO or MANUAL after the step
                "resulting_mode": rec.resulting_mode,
            })

    return output_path


def default_csv_path() -> Path:
    """
    Default export path for HIL CSV results.

    Example:
        ~/Silverworm/hil/hil_run_20260601_142233.csv
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path.home() / "Silverworm" / "hil" / f"hil_run_{ts}.csv"