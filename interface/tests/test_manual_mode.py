"""
Tests for manual mode triggering and acknowledgement.

Validates that manual mode triggers on LOW confidence and requires
user acknowledgement.
"""

import pytest
from types import SimpleNamespace
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from processing.pipeline import PitchDetectionPipeline
from ui.manual_mode_dialog import ManualModeBanner, ManualModeDialog
import numpy as np


def test_manual_mode_triggers_on_low_confidence(qapp):
    """Test that manual mode triggers when confidence is LOW"""
    from unittest.mock import patch, MagicMock

    pipeline = PitchDetectionPipeline(interval_ms=100)

    triggered = []
    pipeline.manual_mode_triggered.connect(lambda c: triggered.append(c))

    # Mock pitch_estimate to return LOW confidence
    mock_result = MagicMock()
    mock_result.confidence = "LOW"
    mock_result.mean_pitch_um = 101.0
    mock_result.std_pitch_um = 3.5
    mock_result.num_wraps = 3

    with patch('processing.pipeline.estimate_pitch', return_value=mock_result):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        pipeline.update_frame(frame)
        pipeline.start()

        # Wait for detection to run
        QTimer.singleShot(500, qapp.quit)
        qapp.exec()

        pipeline.stop()

    # Should have triggered manual mode
    assert len(triggered) > 0
    assert "LOW" in triggered


def test_manual_mode_not_triggered_on_high_confidence(qapp):
    """Test that manual mode does NOT trigger when confidence is HIGH"""
    from unittest.mock import patch, MagicMock

    pipeline = PitchDetectionPipeline(interval_ms=100)

    triggered = []
    pipeline.manual_mode_triggered.connect(lambda c: triggered.append(c))

    # Mock pitch_estimate to return HIGH confidence
    mock_result = MagicMock()
    mock_result.confidence = "HIGH"
    mock_result.mean_pitch_um = 100.4
    mock_result.std_pitch_um = 1.2
    mock_result.num_wraps = 10

    with patch('processing.pipeline.estimate_pitch', return_value=mock_result):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        pipeline.update_frame(frame)
        pipeline.start()

        QTimer.singleShot(500, qapp.quit)
        qapp.exec()

        pipeline.stop()

    # Should NOT have triggered manual mode
    assert len(triggered) == 0


def test_manual_mode_banner_acknowledgement(qapp):
    """Test that banner emits signal on acknowledgement"""
    banner = ManualModeBanner()

    acknowledged = []
    banner.acknowledged.connect(lambda: acknowledged.append(True))

    banner.show_banner()

    # Simulate OK button click
    QTimer.singleShot(100, banner._on_acknowledged)
    QTimer.singleShot(200, qapp.quit)
    qapp.exec()

    assert len(acknowledged) == 1
    assert not banner.isVisible()  # Should be hidden after acknowledge


def test_manual_mode_dialog_modal(qapp):
    """Test that dialog is modal"""
    dialog = ManualModeDialog("LOW")

    assert dialog.isModal() is True


def test_pipeline_clears_latest_frame_on_stop(qapp):
    """stop() must release the retained frame so it isn't pinned in memory."""
    pipeline = PitchDetectionPipeline(interval_ms=1000)
    pipeline.update_frame(np.zeros((480, 640, 3), dtype=np.uint8))
    assert pipeline._latest_frame is not None

    pipeline.start()
    assert pipeline.is_active()

    pipeline.stop()
    assert not pipeline.is_active()
    assert pipeline._latest_frame is None


# ---------------------------------------------------------------------------
# MainWindow pitch-detection lifecycle (manual mode stops detection)
# ---------------------------------------------------------------------------

class _FakeWorker(QObject):
    """Stand-in camera worker exposing only the frame_ready signal."""
    frame_ready = pyqtSignal(np.ndarray)


def _make_window_stub(*, running: bool, mode):
    """Build a bare MainWindow with just the attributes the pitch-detection
    helpers touch — avoids constructing the full window (camera/hardware)."""
    from ui.main_window import MainWindow

    mw = MainWindow.__new__(MainWindow)
    mw._is_running = running
    mw.app_state = SimpleNamespace(mode=mode)
    mw.camera_worker = _FakeWorker()
    mw._pitch_source = None
    mw.pitch_pipeline = PitchDetectionPipeline(interval_ms=1000)
    mw.alert_log = SimpleNamespace(log=lambda *a, **k: None)
    return mw


def test_mainwindow_starts_pitch_when_running_and_auto(qapp):
    from app_state import Mode
    mw = _make_window_stub(running=True, mode=Mode.AUTO)

    mw._start_pitch_detection_if_allowed()

    assert mw.pitch_pipeline.is_active()
    assert mw._pitch_source is mw.camera_worker


def test_mainwindow_does_not_start_pitch_in_manual(qapp):
    from app_state import Mode
    mw = _make_window_stub(running=True, mode=Mode.MANUAL)

    mw._start_pitch_detection_if_allowed()

    assert not mw.pitch_pipeline.is_active()
    assert mw._pitch_source is None


def test_mainwindow_does_not_start_pitch_when_stopped(qapp):
    from app_state import Mode
    mw = _make_window_stub(running=False, mode=Mode.AUTO)

    mw._start_pitch_detection_if_allowed()

    assert not mw.pitch_pipeline.is_active()
    assert mw._pitch_source is None


def test_mainwindow_manual_mode_stops_pitch_detection(qapp):
    """Entering manual mode while running must stop detection, drop the
    retained frame, and disconnect the camera feed."""
    from app_state import Mode
    mw = _make_window_stub(running=True, mode=Mode.AUTO)

    mw._start_pitch_detection_if_allowed()
    mw.pitch_pipeline.update_frame(np.zeros((480, 640, 3), dtype=np.uint8))
    assert mw.pitch_pipeline.is_active()

    mw._stop_pitch_detection()

    assert not mw.pitch_pipeline.is_active()
    assert mw._pitch_source is None
    assert mw.pitch_pipeline._latest_frame is None


def test_mainwindow_no_duplicate_pitch_connection(qapp):
    """Repeated start calls must not stack camera→pipeline connections."""
    from app_state import Mode
    mw = _make_window_stub(running=True, mode=Mode.AUTO)

    # Spy in place of update_frame *before* the connection is made, so the
    # signal binds to the spy. One emit must deliver exactly once.
    calls = []
    mw.pitch_pipeline.update_frame = lambda frame: calls.append(frame)

    mw._start_pitch_detection_if_allowed()
    mw._start_pitch_detection_if_allowed()
    mw._start_pitch_detection_if_allowed()

    mw.camera_worker.frame_ready.emit(np.zeros((4, 4, 3), dtype=np.uint8))

    assert len(calls) == 1
    assert mw._pitch_source is mw.camera_worker


def test_consecutive_low_threshold(qapp):
    """Test that manual mode only triggers after consecutive LOW results"""
    from unittest.mock import patch, MagicMock

    pipeline = PitchDetectionPipeline(interval_ms=100)
    pipeline._low_threshold = 2  # Require 2 consecutive LOW

    triggered = []
    pipeline.manual_mode_triggered.connect(lambda c: triggered.append(c))

    mock_result_low = MagicMock()
    mock_result_low.confidence = "LOW"
    mock_result_low.mean_pitch_um = 101.0
    mock_result_low.num_wraps = 3

    with patch('processing.pipeline.estimate_pitch', return_value=mock_result_low):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        pipeline.update_frame(frame)
        pipeline.start()

        # First detection - should not trigger yet
        QTimer.singleShot(150, lambda: None)
        QTimer.singleShot(400, qapp.quit)
        qapp.exec()

        pipeline.stop()

    # Should have triggered after 2nd LOW
    assert len(triggered) > 0
