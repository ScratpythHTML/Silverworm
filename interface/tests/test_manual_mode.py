"""
Tests for manual mode triggering and acknowledgement.

Validates that manual mode triggers on LOW confidence and requires
user acknowledgement.
"""

import pytest
from PyQt6.QtCore import QTimer
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
