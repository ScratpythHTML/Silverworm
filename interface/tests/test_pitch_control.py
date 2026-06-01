"""
Tests for the pitch-control backend (pitch_control.py).

Each test maps directly to an acceptance criterion. No camera code or
pitch_estimate.py is used here — all pitch values are injected directly.

Fixture: running_auto
    AppState with machine ON, mode AUTO, feed=10.0 mm/s, target=6.0 mm.
    Both wrap and feed motors wired to separate MockSPITransports so we
    can inspect each independently.
"""

import pytest
from types import SimpleNamespace

from comms.motor_spi import build_set_speed
from app_state import Mode, mms_to_units
from config import AppConfig
from processing import PITCH_DETECTION_INTERVAL_MS, PitchDetectionPipeline
from pitch_control import (
    PitchMeasurement,
    process_pitch_result,
    calculate_corrected_feed_speed,
    compute_initial_feed_speed_mm_s,
    compute_wrapper_rpm_from_feed_speed,
    measurement_from_pitch_result,
    MIN_WRAPS_FOR_CORRECTION,
)
from hil_test import make_hil_state, run_hil_pitch_sequence, set_speed_packets
from telemetry import TelemetryLog


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def running_auto(qapp):
    """Machine ON, mode AUTO, feed=10.0 mm/s, target=6.0 mm (6000 µm)."""
    config = AppConfig(target_pitch_um=6000.0)
    state, wrap_t, feed_t = make_hil_state(config)
    state.gui_set_machine_on(True)
    state.gui_set_feed_speed(10.0)
    wrap_t.sent.clear()
    feed_t.sent.clear()
    return state, config, wrap_t, feed_t


# ---------------------------------------------------------------------------
# 1. Speed correction direction
# ---------------------------------------------------------------------------

class TestSpeedDirection:

    def test_measured_below_target_increases_feed(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        # 5.0 mm < 6.0 mm → new = 10.0 * (6.0/5.0) = 12.0 mm/s
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10)
        process_pitch_result(m, state, config)
        assert state.feed_speed_mms == pytest.approx(12.0)

    def test_measured_above_target_decreases_feed(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        # 7.0 mm > 6.0 mm → new = 10.0 * (6.0/7.0) ≈ 8.571 mm/s
        m = PitchMeasurement(measured_pitch_mm=7.0, confidence="HIGH", num_wraps=10)
        process_pitch_result(m, state, config)
        assert state.feed_speed_mms == pytest.approx(10.0 * 6.0 / 7.0)

    def test_measured_equal_target_within_deadband(self, running_auto):
        # 6.0 mm == 6.0 mm target → 0% error, within 2% deadband → no correction
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=6.0, confidence="HIGH", num_wraps=10)
        log = process_pitch_result(m, state, config)
        assert "deadband" in log
        assert set_speed_packets(feed_t) == []

    def test_within_deadband_no_correction(self, running_auto):
        # 6.05 mm → error = 0.05/6.0 = 0.83 % < 2 % → no correction
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=6.05, confidence="HIGH", num_wraps=10)
        log = process_pitch_result(m, state, config)
        assert "deadband" in log
        assert set_speed_packets(feed_t) == []
        assert state.feed_speed_mms == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# 2 & 3. LOW / FAILED confidence
# ---------------------------------------------------------------------------

class TestConfidenceHandling:

    def test_low_confidence_switches_to_manual(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="LOW", num_wraps=10)
        process_pitch_result(m, state, config)
        assert state.mode == Mode.MANUAL

    def test_low_confidence_no_speed_packet(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="LOW", num_wraps=10)
        process_pitch_result(m, state, config)
        assert set_speed_packets(feed_t) == []

    def test_failed_confidence_switches_to_manual(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="FAILED", num_wraps=10)
        process_pitch_result(m, state, config)
        assert state.mode == Mode.MANUAL

    def test_failed_confidence_no_speed_packet(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="FAILED", num_wraps=10)
        process_pitch_result(m, state, config)
        assert set_speed_packets(feed_t) == []

    def test_confidence_string_normalised(self, running_auto):
        """'high', 'High', 'HIGH' must all allow correction."""
        state, config, wrap_t, feed_t = running_auto
        for conf in ("high", "High", "HIGH"):
            state.gui_set_feed_speed(10.0)
            feed_t.sent.clear()
            m = PitchMeasurement(measured_pitch_mm=5.0, confidence=conf, num_wraps=10)
            process_pitch_result(m, state, config)
            assert set_speed_packets(feed_t), f"Expected correction for confidence={conf!r}"
            state.gui_set_feed_speed(10.0)  # reset for next iteration

    def test_low_confidence_normalised(self, running_auto):
        """'low', 'Low', 'LOW' must all trigger MANUAL and block correction."""
        state, config, wrap_t, feed_t = running_auto
        for conf in ("low", "Low", "LOW"):
            state.gui_set_mode(Mode.AUTO)
            feed_t.sent.clear()
            m = PitchMeasurement(measured_pitch_mm=5.0, confidence=conf, num_wraps=10)
            process_pitch_result(m, state, config)
            assert state.mode == Mode.MANUAL
            assert set_speed_packets(feed_t) == [], f"Unexpected packet for confidence={conf!r}"

    def test_medium_confidence_allows_correction(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="MEDIUM", num_wraps=10)
        process_pitch_result(m, state, config)
        assert state.feed_speed_mms == pytest.approx(12.0)

    # 4. LOW on first result must trigger MANUAL immediately
    def test_low_confidence_first_result_triggers_manual(self, qapp):
        config = AppConfig(target_pitch_um=6000.0)
        state, wrap_t, feed_t = make_hil_state(config)
        state.gui_set_machine_on(True)
        state.gui_set_feed_speed(10.0)
        feed_t.sent.clear()

        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="LOW", num_wraps=10)
        process_pitch_result(m, state, config)

        assert state.mode == Mode.MANUAL
        assert set_speed_packets(feed_t) == []


# ---------------------------------------------------------------------------
# 5, 6, 7. Blocking conditions
# ---------------------------------------------------------------------------

class TestBlockingConditions:

    def test_machine_off_no_correction(self, qapp):
        # machine_on defaults to False
        config = AppConfig(target_pitch_um=6000.0)
        state, wrap_t, feed_t = make_hil_state(config)
        state.gui_set_feed_speed(10.0)
        feed_t.sent.clear()
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10)
        log = process_pitch_result(m, state, config)
        assert "machine off" in log
        assert set_speed_packets(feed_t) == []

    def test_manual_mode_no_correction(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        state.gui_set_mode(Mode.MANUAL)
        feed_t.sent.clear()
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10)
        log = process_pitch_result(m, state, config)
        assert "mode=manual" in log.lower()
        assert set_speed_packets(feed_t) == []

    def test_not_enough_wraps_no_correction(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(
            measured_pitch_mm=5.0, confidence="HIGH", num_wraps=MIN_WRAPS_FOR_CORRECTION - 1
        )
        log = process_pitch_result(m, state, config)
        assert "wraps" in log
        assert set_speed_packets(feed_t) == []

    def test_invalid_measured_pitch_no_correction(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=0.0, confidence="HIGH", num_wraps=10)
        log = process_pitch_result(m, state, config)
        assert "<= 0" in log
        assert set_speed_packets(feed_t) == []

    def test_negative_measured_pitch_no_correction(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=-1.0, confidence="HIGH", num_wraps=10)
        log = process_pitch_result(m, state, config)
        assert "<= 0" in log
        assert set_speed_packets(feed_t) == []

    def test_invalid_target_pitch_no_correction(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        config.target_pitch_um = 0.0
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10)
        log = process_pitch_result(m, state, config)
        assert "<= 0" in log
        assert set_speed_packets(feed_t) == []


# ---------------------------------------------------------------------------
# 8. Feed speed clamping
# ---------------------------------------------------------------------------

class TestClamping:

    def test_clamped_at_max(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        # 0.01 mm measured → new = 10.0 * (6.0/0.01) = 6000 → clamped at 20.0
        m = PitchMeasurement(measured_pitch_mm=0.01, confidence="HIGH", num_wraps=10)
        process_pitch_result(m, state, config)
        assert state.feed_speed_mms == pytest.approx(20.0)

    def test_clamped_does_not_exceed_max(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=0.01, confidence="HIGH", num_wraps=10)
        process_pitch_result(m, state, config)
        from app_state import FEED_SPEED_MAX_MMS
        assert state.feed_speed_mms <= FEED_SPEED_MAX_MMS

    def test_clamped_not_below_zero(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        # Very large measured pitch → correction approaches 0 but stays >= 0
        m = PitchMeasurement(measured_pitch_mm=10000.0, confidence="HIGH", num_wraps=10)
        process_pitch_result(m, state, config)
        from app_state import FEED_SPEED_MIN_MMS
        assert state.feed_speed_mms >= FEED_SPEED_MIN_MMS


# ---------------------------------------------------------------------------
# 9. Packet correctness + feed motor only
# ---------------------------------------------------------------------------

class TestPacketCorrectness:

    def test_set_speed_packet_value(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        # 5.0 mm → new = 10.0 * (6.0/5.0) = 12.0 mm/s
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10)
        process_pitch_result(m, state, config)
        expected_speed_units = mms_to_units(10.0 * 6.0 / 5.0)  # mms_to_units(12.0)
        pkts = set_speed_packets(feed_t)
        assert len(pkts) == 1
        assert pkts[0] == build_set_speed(expected_speed_units)

    def test_correction_only_sent_to_feed_motor(self, running_auto):
        """Wrapper motor must NOT receive any SET_SPEED packet during correction."""
        state, config, wrap_t, feed_t = running_auto
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10)
        process_pitch_result(m, state, config)
        wrap_set_speed = set_speed_packets(wrap_t)
        assert wrap_set_speed == []
        # And feed motor did receive one
        assert len(set_speed_packets(feed_t)) == 1


# ---------------------------------------------------------------------------
# 10 & 11. HIL harness
# ---------------------------------------------------------------------------

class TestHIL:

    def test_hil_sequence_speed_directions(self, qapp):
        """[5.0, 6.0, 7.0] mm with HIGH confidence → increase, deadband, decrease."""
        config = AppConfig(target_pitch_um=6000.0)
        state, wrap_t, feed_t = make_hil_state(config)
        state.gui_set_machine_on(True)
        state.gui_set_feed_speed(10.0)
        feed_t.sent.clear()

        logs = run_hil_pitch_sequence([5.0, 6.0, 7.0], ["HIGH", "HIGH", "HIGH"], state, config)

        assert len(logs) == 3
        # Step 1: 5.0 mm → new = 10.0 * (6/5) = 12.0
        # Step 2: 6.0 mm → within deadband → stays 12.0
        # Step 3: 7.0 mm → new = 12.0 * (6/7) ≈ 10.286
        assert "deadband" in logs[1]
        assert state.feed_speed_mms == pytest.approx(12.0 * 6.0 / 7.0)
        pkts = set_speed_packets(feed_t)
        assert len(pkts) == 2   # step 2 is within deadband, no packet

    def test_hil_low_confidence_first_triggers_manual(self, qapp):
        config = AppConfig(target_pitch_um=6000.0)
        state, wrap_t, feed_t = make_hil_state(config)
        state.gui_set_machine_on(True)
        state.gui_set_feed_speed(10.0)
        feed_t.sent.clear()

        logs = run_hil_pitch_sequence([5.0], ["LOW"], state, config)

        assert state.mode == Mode.MANUAL
        assert set_speed_packets(feed_t) == []
        assert "MANUAL" in logs[0]

    def test_hil_configurable_num_wraps_blocks_correction(self, qapp):
        """num_wraps below threshold must block correction even with HIGH confidence."""
        config = AppConfig(target_pitch_um=6000.0)
        state, wrap_t, feed_t = make_hil_state(config)
        state.gui_set_machine_on(True)
        state.gui_set_feed_speed(10.0)
        feed_t.sent.clear()

        logs = run_hil_pitch_sequence(
            [5.0], ["HIGH"], state, config, num_wraps=MIN_WRAPS_FOR_CORRECTION - 1
        )

        assert "wraps" in logs[0]
        assert set_speed_packets(feed_t) == []

    def test_hil_uses_same_path_as_direct_call(self, qapp):
        """HIL produces identical state and packets to a direct process_pitch_result call."""
        config = AppConfig(target_pitch_um=6000.0)

        state_a, wrap_a, feed_a = make_hil_state(config)
        state_a.gui_set_machine_on(True)
        state_a.gui_set_feed_speed(10.0)
        feed_a.sent.clear()

        state_b, wrap_b, feed_b = make_hil_state(config)
        state_b.gui_set_machine_on(True)
        state_b.gui_set_feed_speed(10.0)
        feed_b.sent.clear()

        # Direct call with source="HIL" to match what run_hil_pitch_sequence produces
        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10, source="HIL")
        direct_log = process_pitch_result(m, state_a, config)

        # HIL harness call
        hil_logs = run_hil_pitch_sequence([5.0], ["HIGH"], state_b, config)

        assert state_a.feed_speed_mms == pytest.approx(state_b.feed_speed_mms)
        assert feed_a.sent == feed_b.sent
        assert direct_log == hil_logs[0]

    def test_hil_does_not_import_camera_or_pitch_estimate(self):
        """pitch_control.py must not import camera or pitch_estimate modules."""
        from pathlib import Path
        import_lines = [
            line.strip()
            for line in (Path(__file__).parent.parent / "pitch_control.py").read_text().splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        for line in import_lines:
            assert "pitch_estimate" not in line, f"Unexpected import: {line}"
            assert "camera" not in line, f"Unexpected import: {line}"


# ---------------------------------------------------------------------------
# Camera PitchResult → shared backend (Task 1)
# ---------------------------------------------------------------------------

class TestCameraResultConversion:

    def test_interval_is_2000ms(self):
        """Pitch estimation period is ~2000 ms and not per-frame."""
        assert PITCH_DETECTION_INTERVAL_MS == 2000
        assert PitchDetectionPipeline().interval_ms == 2000

    def test_pitch_result_converts_to_measurement(self):
        """mean_pitch_um → mm, confidence + num_wraps preserved, source=camera."""
        result = SimpleNamespace(
            mean_pitch_um=5500.0, confidence="HIGH", num_wraps=8
        )
        m = measurement_from_pitch_result(result)
        assert m.measured_pitch_mm == pytest.approx(5.5)
        assert m.confidence == "HIGH"
        assert m.num_wraps == 8
        assert m.source == "camera"

    def test_camera_result_drives_same_backend_path(self, running_auto):
        """A camera-style PitchResult, converted, corrects feed via the shared path."""
        state, config, wrap_t, feed_t = running_auto
        # 5.0 mm measured (5000 µm) vs 6.0 mm target → feed 10.0 → 12.0
        result = SimpleNamespace(
            mean_pitch_um=5000.0, confidence="HIGH", num_wraps=10
        )
        m = measurement_from_pitch_result(result)
        process_pitch_result(m, state, config)
        assert state.feed_speed_mms == pytest.approx(12.0)
        assert len(set_speed_packets(feed_t)) == 1

    def test_camera_low_confidence_triggers_manual(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        result = SimpleNamespace(
            mean_pitch_um=5000.0, confidence="LOW", num_wraps=10
        )
        m = measurement_from_pitch_result(result)
        process_pitch_result(m, state, config)
        assert state.mode == Mode.MANUAL
        assert set_speed_packets(feed_t) == []


# ---------------------------------------------------------------------------
# calculate_corrected_feed_speed helper (Task 2)
# ---------------------------------------------------------------------------

class TestCorrectionHelper:

    def test_gain_1_matches_direct_ratio(self):
        # 10.0 * (6.0/5.0) = 12.0
        result = calculate_corrected_feed_speed(
            current_feed_speed_mm_s=10.0,
            target_pitch_mm=6.0,
            measured_pitch_mm=5.0,
            min_feed_speed_mm_s=0.0,
            max_feed_speed_mm_s=20.0,
        )
        assert result == pytest.approx(12.0)

    def test_gain_half_moves_halfway(self):
        # direct = 12.0; halfway from 10.0 → 11.0
        result = calculate_corrected_feed_speed(
            current_feed_speed_mm_s=10.0,
            target_pitch_mm=6.0,
            measured_pitch_mm=5.0,
            min_feed_speed_mm_s=0.0,
            max_feed_speed_mm_s=20.0,
            correction_gain=0.5,
        )
        assert result == pytest.approx(11.0)

    def test_helper_clamps_to_max(self):
        result = calculate_corrected_feed_speed(
            current_feed_speed_mm_s=10.0,
            target_pitch_mm=6.0,
            measured_pitch_mm=0.01,
            min_feed_speed_mm_s=0.0,
            max_feed_speed_mm_s=20.0,
        )
        assert result == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# compute_initial_feed_speed_mm_s — theoretical AUTO startup (Task 2)
# ---------------------------------------------------------------------------

class TestTheoreticalStartup:

    def test_returns_positive_for_valid_inputs(self):
        v = compute_initial_feed_speed_mm_s(
            wrapper_rpm=600.0,        # 10 rev/s
            target_pitch_mm=2.0,
            tube_diameter_mm=5.0,
            wire_diameter_mm=0.1,
        )
        assert v is not None
        assert v > 0

    def test_matches_manual_formula(self):
        import math
        wrapper_rpm, target, tube, wire = 600.0, 2.0, 5.0, 0.1
        v = compute_initial_feed_speed_mm_s(wrapper_rpm, target, tube, wire)
        eff_r = tube / 2.0 + wire / 2.0
        expected = (wrapper_rpm / 60.0) / math.sqrt(
            1.0 / target ** 2 - 1.0 / (4.0 * math.pi ** 2 * eff_r ** 2)
        )
        assert v == pytest.approx(expected)

    def test_invalid_target_pitch_returns_none(self):
        assert compute_initial_feed_speed_mm_s(600.0, 0.0, 5.0, 0.1) is None
        assert compute_initial_feed_speed_mm_s(600.0, -1.0, 5.0, 0.1) is None

    def test_invalid_tube_diameter_returns_none(self):
        assert compute_initial_feed_speed_mm_s(600.0, 2.0, 0.0, 0.1) is None

    def test_negative_wire_diameter_returns_none(self):
        assert compute_initial_feed_speed_mm_s(600.0, 2.0, 5.0, -0.1) is None

    def test_invalid_wrapper_speed_returns_none(self):
        assert compute_initial_feed_speed_mm_s(0.0, 2.0, 5.0, 0.1) is None

    def test_negative_sqrt_argument_returns_none(self):
        # Large target pitch makes 1/D2^2 small → sqrt arg negative → None
        assert compute_initial_feed_speed_mm_s(600.0, 1000.0, 5.0, 0.1) is None


class TestWrapperFromFeed:
    """Inverse formula: wrapper RPM from feed speed."""

    def test_round_trips_with_feed_formula(self):
        # wrapper → feed → wrapper must recover the original wrapper RPM
        wrapper_rpm, target, tube, wire = 2000.0, 6.0, 5.0, 0.1
        v = compute_initial_feed_speed_mm_s(wrapper_rpm, target, tube, wire)
        back = compute_wrapper_rpm_from_feed_speed(v, target, tube, wire)
        assert back == pytest.approx(wrapper_rpm)

    def test_returns_positive_for_valid_inputs(self):
        rpm = compute_wrapper_rpm_from_feed_speed(10.0, 6.0, 5.0, 0.1)
        assert rpm is not None and rpm > 0

    def test_invalid_inputs_return_none(self):
        assert compute_wrapper_rpm_from_feed_speed(0.0, 6.0, 5.0, 0.1) is None   # feed 0
        assert compute_wrapper_rpm_from_feed_speed(10.0, 0.0, 5.0, 0.1) is None  # target 0
        assert compute_wrapper_rpm_from_feed_speed(10.0, 6.0, 0.0, 0.1) is None  # tube 0
        assert compute_wrapper_rpm_from_feed_speed(10.0, 6.0, 5.0, -0.1) is None  # wire < 0
        # Large target pitch → negative sqrt arg
        assert compute_wrapper_rpm_from_feed_speed(10.0, 1000.0, 5.0, 0.1) is None


# ---------------------------------------------------------------------------
# Telemetry threaded through the shared backend (Part 1 + Part 2)
# ---------------------------------------------------------------------------

class TestTelemetryIntegration:

    def test_auto_correction_logs_speeds_target_and_pitch(self, running_auto):
        state, config, wrap_t, feed_t = running_auto
        tlog = TelemetryLog()
        m = PitchMeasurement(
            measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10, source="camera"
        )
        process_pitch_result(m, state, config, telemetry=tlog)
        rec = tlog.last
        assert rec.mode == "AUTO"
        assert rec.source == "camera"
        assert rec.previous_feed_speed_mm_s == pytest.approx(10.0)
        assert rec.commanded_feed_speed_mm_s == pytest.approx(12.0)
        assert rec.target_pitch_mm == pytest.approx(6.0)
        assert rec.measured_pitch_before_mm == pytest.approx(5.0)
        assert rec.command_sent_successfully is True

    def test_hil_sequence_computes_pitch_change_and_sensitivity(self, qapp):
        config = AppConfig(target_pitch_um=6000.0)
        state, wrap_t, feed_t = make_hil_state(config)
        state.gui_set_machine_on(True)
        state.gui_set_feed_speed(10.0)
        feed_t.sent.clear()
        tlog = TelemetryLog()

        # Step 1: 5.0 mm sends 10→12 (delta 2). Step 2: 5.5 mm is the "after"
        # pitch that closes step 1's record.
        run_hil_pitch_sequence([5.0, 5.5], ["HIGH", "HIGH"], state, config, telemetry=tlog)

        first = tlog.records[0]
        assert first.measured_pitch_before_mm == pytest.approx(5.0)
        assert first.measured_pitch_after_mm == pytest.approx(5.5)
        assert first.pitch_change_mm == pytest.approx(0.5)
        assert first.speed_delta_mm_s == pytest.approx(2.0)
        assert first.pitch_sensitivity_per_feed_speed == pytest.approx(0.25)

    def test_hil_mock_feedback_computes_motor_response_time(self, qapp):
        config = AppConfig(target_pitch_um=6000.0)
        state, wrap_t, feed_t = make_hil_state(config)
        state.gui_set_machine_on(True)
        state.gui_set_feed_speed(10.0)
        feed_t.sent.clear()
        tlog = TelemetryLog()

        run_hil_pitch_sequence([5.0], ["HIGH"], state, config, telemetry=tlog)
        rec = tlog.last
        # Mock a feedback packet 0.3 s after the command was sent.
        tlog.record_motor_feedback(11.9, now=rec.timestamp_command_sent + 0.3)
        assert rec.motor_response_time_ms == pytest.approx(300.0)
        assert rec.actual_feed_speed_mm_s == pytest.approx(11.9)
        assert tlog.last_actual_feed_speed_mm_s == pytest.approx(11.9)

    def test_telemetry_optional_does_not_change_return_string(self, running_auto):
        """Passing telemetry must not alter the control return string."""
        state_a, config, wrap_a, feed_a = running_auto
        state_b, wrap_b, feed_b = make_hil_state(config)
        state_b.gui_set_machine_on(True)
        state_b.gui_set_feed_speed(10.0)

        m = PitchMeasurement(measured_pitch_mm=5.0, confidence="HIGH", num_wraps=10)
        without = process_pitch_result(m, state_b, config)
        with_tlog = process_pitch_result(m, state_a, config, telemetry=TelemetryLog())
        assert without == with_tlog
