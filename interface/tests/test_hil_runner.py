"""
Minimal tests for the HIL scenario runner and CSV export.

All tests use mock SPI transports — no hardware required.
"""

import csv
import pytest

from config import AppConfig
from hil_runner import HIL_SCENARIOS, run_hil_scenario, export_csv


@pytest.fixture
def config_6mm():
    return AppConfig(target_pitch_um=6000.0)


# ---------------------------------------------------------------------------
# Scenario behaviour
# ---------------------------------------------------------------------------

class TestScenarios:

    def test_under_pitch_increases_feed_speed(self, config_6mm):
        """Measured pitch below target → feed speed must end higher than initial."""
        tlog, logs, run_id = run_hil_scenario(
            HIL_SCENARIOS["under_pitch"],
            config_6mm,
            initial_feed_speed_mm_s=10.0,
        )
        sent = [r for r in tlog.records if r.command_sent_successfully]
        assert sent, "Expected at least one sent command"
        assert sent[0].commanded_feed_speed_mm_s > 10.0

    def test_over_pitch_decreases_feed_speed(self, config_6mm):
        """Measured pitch above target → feed speed must end lower than initial."""
        tlog, logs, run_id = run_hil_scenario(
            HIL_SCENARIOS["over_pitch"],
            config_6mm,
            initial_feed_speed_mm_s=10.0,
        )
        sent = [r for r in tlog.records if r.command_sent_successfully]
        assert sent, "Expected at least one sent command"
        assert sent[0].commanded_feed_speed_mm_s < 10.0

    def test_low_confidence_enters_manual_no_command(self, config_6mm):
        """LOW confidence → Manual Mode activates, no SET_SPEED sent."""
        tlog, logs, run_id = run_hil_scenario(
            HIL_SCENARIOS["low_confidence"],
            config_6mm,
            initial_feed_speed_mm_s=10.0,
        )
        assert len(tlog.records) == 1
        rec = tlog.records[0]
        assert rec.command_sent_successfully is False
        assert rec.resulting_mode == "MANUAL"
        assert "MANUAL" in logs[0]

    def test_mock_feedback_delay_populates_motor_response_time(self, config_6mm):
        """mock_feedback_delay_ms should appear as motor_response_time_ms."""
        tlog, _, _ = run_hil_scenario(
            HIL_SCENARIOS["under_pitch"],
            config_6mm,
            initial_feed_speed_mm_s=10.0,
            mock_feedback_delay_ms=200.0,
        )
        sent = [r for r in tlog.records if r.command_sent_successfully]
        assert sent[0].motor_response_time_ms == pytest.approx(200.0, abs=1.0)

    def test_run_id_is_unique_per_run(self, config_6mm):
        _, _, id1 = run_hil_scenario(HIL_SCENARIOS["under_pitch"], config_6mm)
        _, _, id2 = run_hil_scenario(HIL_SCENARIOS["under_pitch"], config_6mm)
        assert id1 != id2


# ---------------------------------------------------------------------------
# Pitch sensitivity
# ---------------------------------------------------------------------------

class TestPitchSensitivity:

    def test_pitch_sensitivity_calculated_when_speed_delta_nonzero(self, config_6mm):
        """Sequential HIL pitches → pitch_change_mm and sensitivity filled."""
        tlog, _, _ = run_hil_scenario(
            HIL_SCENARIOS["under_pitch"],
            config_6mm,
            initial_feed_speed_mm_s=10.0,
        )
        # The first sent command should have pitch_after set by the second step.
        sent = [r for r in tlog.records if r.command_sent_successfully]
        first = sent[0]
        assert first.measured_pitch_after_mm is not None
        assert first.pitch_change_mm is not None
        assert first.pitch_sensitivity_per_feed_speed is not None

    def test_speed_delta_zero_skips_sensitivity_safely(self, config_6mm):
        """Deadband step: speed_delta == 0, sensitivity must remain None."""
        tlog, _, _ = run_hil_scenario(
            HIL_SCENARIOS["under_pitch"],
            config_6mm,
            initial_feed_speed_mm_s=10.0,
        )
        # Last step is 6.0 mm (on target) → within deadband → not sent → delta 0.
        blocked = [r for r in tlog.records if not r.command_sent_successfully]
        for rec in blocked:
            assert rec.speed_delta_mm_s == pytest.approx(0.0)
            assert rec.pitch_sensitivity_per_feed_speed is None


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

class TestCSVExport:

    def test_csv_writes_expected_columns(self, config_6mm, tmp_path):
        tlog, _, run_id = run_hil_scenario(
            HIL_SCENARIOS["under_pitch"], config_6mm
        )
        out = tmp_path / "test.csv"
        export_csv(tlog.records, out, run_id)

        with open(out) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        expected_cols = {
            "run_id", "step", "timestamp", "mode", "source",
            "target_pitch_mm", "measured_pitch_mm", "confidence",
            "previous_feed_speed_mm_s", "commanded_feed_speed_mm_s",
            "speed_delta_mm_s", "correction_gain", "command_sent",
            "mock_actual_feed_speed_mm_s", "motor_response_time_ms",
            "next_pitch_mm", "pitch_change_mm",
            "pitch_sensitivity_per_feed_speed", "blocked_reason",
            "resulting_mode",
        }
        assert expected_cols.issubset(set(rows[0].keys()))

    def test_csv_run_id_matches(self, config_6mm, tmp_path):
        tlog, _, run_id = run_hil_scenario(
            HIL_SCENARIOS["over_pitch"], config_6mm
        )
        out = export_csv(tlog.records, tmp_path / "out.csv", run_id)
        with open(out) as f:
            rows = list(csv.DictReader(f))
        assert all(r["run_id"] == run_id for r in rows)

    def test_csv_step_numbers_are_sequential(self, config_6mm, tmp_path):
        tlog, _, run_id = run_hil_scenario(
            HIL_SCENARIOS["mixed"], config_6mm
        )
        out = export_csv(tlog.records, tmp_path / "out.csv", run_id)
        with open(out) as f:
            rows = list(csv.DictReader(f))
        steps = [int(r["step"]) for r in rows]
        assert steps == list(range(1, len(rows) + 1))

    def test_low_confidence_blocked_reason_in_csv(self, config_6mm, tmp_path):
        tlog, _, run_id = run_hil_scenario(
            HIL_SCENARIOS["low_confidence"], config_6mm
        )
        out = export_csv(tlog.records, tmp_path / "out.csv", run_id)
        with open(out) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["command_sent"] == "False"
        assert rows[0]["blocked_reason"] != ""
        assert rows[0]["resulting_mode"] == "MANUAL"
