"""
Unit tests for the speed-command telemetry log.

Pure logic — no Qt or hardware. Timestamps are passed explicitly (now=...)
so response-time maths is deterministic.
"""

import pytest

from telemetry import TelemetryLog


def _record_sent(log, *, prev=10.0, commanded=12.0, measured_before=5.0, now=100.0):
    return log.record_command(
        mode="AUTO",
        source="camera",
        target_pitch_mm=6.0,
        previous_feed_speed_mm_s=prev,
        commanded_feed_speed_mm_s=commanded,
        command_sent_successfully=True,
        reason="correction",
        measured_pitch_before_mm=measured_before,
        now=now,
    )


# ---------------------------------------------------------------------------
# record_command
# ---------------------------------------------------------------------------

class TestRecordCommand:

    def test_fields_and_delta(self):
        log = TelemetryLog()
        rec = _record_sent(log)
        assert rec.previous_feed_speed_mm_s == 10.0
        assert rec.commanded_feed_speed_mm_s == 12.0
        assert rec.speed_delta_mm_s == pytest.approx(2.0)
        assert rec.command_sent_successfully is True
        assert rec.timestamp_command_sent == 100.0
        assert log.last is rec

    def test_blocked_command_is_not_pending(self):
        log = TelemetryLog()
        log.record_command(
            mode="AUTO", source="camera", target_pitch_mm=6.0,
            previous_feed_speed_mm_s=10.0, commanded_feed_speed_mm_s=10.0,
            command_sent_successfully=False, reason="deadband", now=1.0,
        )
        assert log.last.command_sent_successfully is False
        # No pending → motor feedback can't attach to it.
        assert log.record_motor_feedback(10.0, now=2.0) is None


# ---------------------------------------------------------------------------
# Motor feedback → response time + actual speed
# ---------------------------------------------------------------------------

class TestMotorFeedback:

    def test_motor_response_time_ms(self):
        log = TelemetryLog()
        _record_sent(log, now=100.0)
        rec = log.record_motor_feedback(11.9, now=100.25)   # 250 ms later
        assert rec is not None
        assert rec.actual_feed_speed_mm_s == pytest.approx(11.9)
        assert rec.motor_response_time_ms == pytest.approx(250.0)
        assert log.last_actual_feed_speed_mm_s == pytest.approx(11.9)

    def test_only_first_feedback_sets_response_time(self):
        log = TelemetryLog()
        _record_sent(log, now=100.0)
        log.record_motor_feedback(11.9, now=100.25)
        second = log.record_motor_feedback(12.0, now=100.5)
        assert second is None                                # already filled
        assert log.last.motor_response_time_ms == pytest.approx(250.0)
        assert log.last_actual_feed_speed_mm_s == pytest.approx(12.0)  # latest still tracked

    def test_no_feedback_shows_waiting(self):
        log = TelemetryLog()
        assert log.last_actual_feed_speed_mm_s is None
        assert log.actual_feed_speed_display() == "Waiting for feedback"


# ---------------------------------------------------------------------------
# Pitch after → pitch change + sensitivity
# ---------------------------------------------------------------------------

class TestPitchAfter:

    def test_pitch_change_and_sensitivity(self):
        log = TelemetryLog()
        _record_sent(log, prev=10.0, commanded=12.0, measured_before=5.0, now=100.0)
        rec = log.record_pitch_after(5.5, now=102.0)        # 2000 ms later
        assert rec.measured_pitch_after_mm == pytest.approx(5.5)
        assert rec.pitch_response_time_ms == pytest.approx(2000.0)
        assert rec.pitch_change_mm == pytest.approx(0.5)
        assert rec.pitch_sensitivity_per_feed_speed == pytest.approx(0.25)  # 0.5 / 2.0

    def test_zero_speed_delta_skips_sensitivity_safely(self):
        log = TelemetryLog()
        # Sent but commanded == prev → delta 0 → never becomes pending.
        log.record_command(
            mode="AUTO", source="camera", target_pitch_mm=6.0,
            previous_feed_speed_mm_s=10.0, commanded_feed_speed_mm_s=10.0,
            command_sent_successfully=True, reason="no change",
            measured_pitch_before_mm=5.0, now=100.0,
        )
        # No crash, nothing to close, no sensitivity computed.
        assert log.record_pitch_after(5.5, now=101.0) is None
        assert log.last.pitch_sensitivity_per_feed_speed is None

    def test_pitch_after_without_pending_is_noop(self):
        log = TelemetryLog()
        assert log.record_pitch_after(5.5, now=100.0) is None


# ---------------------------------------------------------------------------
# Mismatch warning (non-blocking)
# ---------------------------------------------------------------------------

class TestMismatchWarning:

    def test_warning_beyond_tolerance(self):
        log = TelemetryLog(mismatch_tolerance_mm_s=0.5)
        log.record_motor_feedback(8.0)
        warn = log.mismatch_warning(10.0)                   # diff 2.0 > 0.5
        assert warn is not None
        assert "commanded 10" in warn
        assert "actual 8" in warn

    def test_no_warning_within_tolerance(self):
        log = TelemetryLog(mismatch_tolerance_mm_s=0.5)
        log.record_motor_feedback(9.8)
        assert log.mismatch_warning(10.0) is None           # diff 0.2 < 0.5

    def test_no_warning_without_feedback(self):
        log = TelemetryLog()
        assert log.mismatch_warning(10.0) is None


# ---------------------------------------------------------------------------
# "last_*" convenience props search back past later blocked records
# ---------------------------------------------------------------------------

class TestLastProps:

    def test_last_props_search_backwards(self):
        log = TelemetryLog()
        _record_sent(log, now=100.0)
        log.record_motor_feedback(11.9, now=100.2)          # +200 ms
        log.record_pitch_after(5.5, now=102.0)
        # A later blocked record has no motor/pitch fields of its own.
        log.record_command(
            mode="AUTO", source="camera", target_pitch_mm=6.0,
            previous_feed_speed_mm_s=12.0, commanded_feed_speed_mm_s=12.0,
            command_sent_successfully=False, reason="deadband", now=103.0,
        )
        assert log.last_motor_response_time_ms == pytest.approx(200.0)
        assert log.last_pitch_change_mm == pytest.approx(0.5)
        assert log.last_pitch_sensitivity_per_feed_speed == pytest.approx(0.25)
