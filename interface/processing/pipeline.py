"""
Pitch detection pipeline for live camera integration.

Integrates the pitch_estimate.py module with real-time camera frames,
providing periodic pitch detection and manual mode triggering.
"""

from PyQt6.QtCore import QObject, pyqtSignal, QTimer
import numpy as np
import cv2
from typing import Optional
import sys
import os
import tempfile

# Add image-processing to path
sys.path.insert(0, '/Users/anhad/Silverworm-app/image-processing')

try:
    from pitch_estimate import PitchResult, estimate_pitch
except ImportError:
    print("Warning: Could not import pitch_estimate module")
    # Create dummy PitchResult for testing without pitch_estimate
    from dataclasses import dataclass

    @dataclass
    class PitchResult:
        pitches_um: np.ndarray
        mean_pitch_um: float
        std_pitch_um: float
        num_wraps: int
        confidence: str
        scale_um_per_px: float
        texture_angle_deg: float
        thread_angle_deg: float


class PitchDetectionPipeline(QObject):
    """
    Integrates pitch_estimate.py with live camera feed.

    Runs pitch detection periodically (e.g., every 2 seconds) on the latest
    frame from the camera. Emits results and triggers manual mode on low
    confidence.

    Signals:
        pitch_result_ready: Emitted when pitch detection completes (PitchResult)
        manual_mode_triggered: Emitted when confidence is LOW (str: confidence level)
        detection_error: Emitted when pitch detection fails (str: error message)
    """

    pitch_result_ready = pyqtSignal(object)  # PitchResult
    manual_mode_triggered = pyqtSignal(str)  # Confidence level
    detection_error = pyqtSignal(str)         # Error message

    def __init__(self, interval_ms: int = 2000, parent=None):
        """
        Initialize pitch detection pipeline.

        Args:
            interval_ms: Detection interval in milliseconds (default: 2000 = 2 seconds)
            parent: Parent QObject
        """
        super().__init__(parent)
        self.interval_ms = interval_ms
        self._latest_frame: Optional[np.ndarray] = None  # BGR format
        self._enabled = False

        # Timer for periodic detection
        self._timer = QTimer()
        self._timer.timeout.connect(self._run_detection)

        # Consecutive low confidence counter
        self._consecutive_low_count = 0
        self._low_threshold = 1  # Trigger manual mode after this many consecutive LOW results

    def start(self):
        """Start periodic pitch detection"""
        self._enabled = True
        self._timer.start(self.interval_ms)

    def stop(self):
        """Stop pitch detection"""
        self._enabled = False
        self._timer.stop()
        self._consecutive_low_count = 0

    def set_interval(self, interval_ms: int):
        """
        Change detection interval.

        Args:
            interval_ms: New interval in milliseconds
        """
        self.interval_ms = interval_ms
        if self._timer.isActive():
            self._timer.setInterval(interval_ms)

    def update_frame(self, frame: np.ndarray):
        """
        Update latest frame for detection.

        Args:
            frame: BGR numpy array from camera
        """
        if frame is not None and frame.size > 0:
            self._latest_frame = frame.copy()

    def trigger_manual_detection(self):
        """Manually trigger detection immediately (e.g., from SNAPSHOT button)"""
        if self._latest_frame is not None:
            self._run_detection()

    def _run_detection(self):
        """Run pitch detection on latest frame"""
        if not self._enabled or self._latest_frame is None:
            return

        # Create temp file (pitch_estimate expects file path)
        temp_file = None
        tmp_path = None

        try:
            temp_file = tempfile.NamedTemporaryFile(
                suffix='.jpg',
                delete=False
            )
            tmp_path = temp_file.name
            temp_file.close()

            # Save frame to temp file
            success = cv2.imwrite(tmp_path, self._latest_frame)
            if not success:
                raise IOError(f"Failed to write frame to {tmp_path}")

            # Run pitch detection (disable plots for live mode)
            try:
                result = estimate_pitch(tmp_path, show_plots=False)
            except NameError:
                # pitch_estimate not available - create dummy result for testing
                result = PitchResult(
                    pitches_um=np.array([100.0, 102.0, 98.0]),
                    mean_pitch_um=100.0,
                    std_pitch_um=2.0,
                    num_wraps=3,
                    confidence="MEDIUM",
                    scale_um_per_px=2.0,
                    texture_angle_deg=45.0,
                    thread_angle_deg=0.0
                )

            # Emit result
            self.pitch_result_ready.emit(result)

            # Check for manual mode trigger
            if result.confidence == "LOW" or result.confidence == "FAILED":
                self._consecutive_low_count += 1
                if self._consecutive_low_count >= self._low_threshold:
                    self.manual_mode_triggered.emit(result.confidence)
            else:
                # Reset counter on good result
                self._consecutive_low_count = 0

        except Exception as e:
            error_msg = f"Pitch detection error: {e}"
            print(error_msg)
            self.detection_error.emit(error_msg)

        finally:
            # Cleanup temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception as e:
                    print(f"Failed to delete temp file {tmp_path}: {e}")
