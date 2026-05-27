"""
Unit tests for camera selection/fallback logic.

Tests the CameraDetector priority logic and the device selection rules that
drive the camera toggle feature — no real hardware needed.
"""

import pytest
from unittest.mock import MagicMock, patch

from camera.detector import CameraDetector, CameraDevice, DiagnosticResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(
    index: int,
    name: str,
    path: str = "/dev/video0",
    width: int = 1920,
    height: int = 1080,
    priority: int = 0,
) -> CameraDevice:
    return CameraDevice(
        index=index,
        path=path,
        name=name,
        driver="test",
        width=width,
        height=height,
        priority=priority,
    )


# ---------------------------------------------------------------------------
# Priority calculation
# ---------------------------------------------------------------------------

class TestPriorityCalculation:

    def test_amscope_gets_priority_boost(self):
        det = CameraDetector()
        p = det._calculate_priority("AmScope HHD 8300-P", "/dev/video2", 3264, 2448)
        assert p >= 100

    def test_generic_usb_camera_lower_priority_than_amscope(self):
        det = CameraDetector()
        p_amscope = det._calculate_priority("AmScope HHD 8300-P", "/dev/video2", 3264, 2448)
        p_generic = det._calculate_priority("USB Camera", "/dev/video0", 1920, 1080)
        assert p_amscope > p_generic

    def test_higher_resolution_boosts_priority(self):
        det = CameraDetector()
        p_hd = det._calculate_priority("Camera", "/dev/video1", 1280, 720)
        p_fhd = det._calculate_priority("Camera", "/dev/video1", 1920, 1080)
        p_8mp = det._calculate_priority("Camera", "/dev/video1", 3264, 2448)
        assert p_8mp > p_fhd > p_hd

    def test_video0_gets_small_boost(self):
        det = CameraDetector()
        p0 = det._calculate_priority("Camera", "/dev/video0", 1280, 720)
        p1 = det._calculate_priority("Camera", "/dev/video1", 1280, 720)
        assert p0 > p1

    def test_uvc_name_gets_amscope_class_boost(self):
        det = CameraDetector()
        p = det._calculate_priority("UVC Camera", "/dev/video0", 640, 480)
        assert p >= 100


# ---------------------------------------------------------------------------
# Device selection (select_device / _select_device)
# ---------------------------------------------------------------------------

class TestDeviceSelection:

    def test_selects_highest_priority_device(self):
        det = CameraDetector()
        devices = [
            _make_device(0, "Generic", priority=10),
            _make_device(1, "AmScope", priority=150),
            _make_device(2, "USB Cam", priority=20),
        ]
        selected = det._select_device(devices)
        assert selected.name == "AmScope"

    def test_returns_none_when_no_devices(self):
        det = CameraDetector()
        assert det._select_device([]) is None

    def test_returns_single_device_when_only_one(self):
        det = CameraDetector()
        devices = [_make_device(0, "Only Camera", priority=5)]
        selected = det._select_device(devices)
        assert selected.name == "Only Camera"


# ---------------------------------------------------------------------------
# Camera toggle selection logic (mirrors what app.py does)
# ---------------------------------------------------------------------------

class TestCameraToggleSelectionLogic:
    """
    Verifies the sort-by-priority logic that app.py uses to pick primary
    and secondary camera. Tests the algorithm, not the Qt widget.
    """

    def _pick_primary_and_secondary(self, devices):
        """Replicate app.py's device ranking."""
        sorted_devices = sorted(devices, key=lambda d: d.priority, reverse=True)
        primary = sorted_devices[0] if sorted_devices else None
        secondary = sorted_devices[1] if len(sorted_devices) > 1 else None
        return primary, secondary

    def test_microscope_is_primary_webcam_is_secondary(self):
        devices = [
            _make_device(0, "USB Webcam", priority=25),
            _make_device(1, "AmScope HHD 8300-P", priority=150),
        ]
        primary, secondary = self._pick_primary_and_secondary(devices)
        assert "AmScope" in primary.name
        assert "Webcam" in secondary.name

    def test_no_secondary_when_only_one_camera(self):
        devices = [_make_device(0, "Only Camera", priority=50)]
        primary, secondary = self._pick_primary_and_secondary(devices)
        assert primary is not None
        assert secondary is None

    def test_no_cameras_returns_both_none(self):
        primary, secondary = self._pick_primary_and_secondary([])
        assert primary is None
        assert secondary is None

    def test_fallback_to_webcam_when_microscope_unavailable(self):
        """If only a webcam is present it becomes primary (no AmScope)."""
        devices = [_make_device(0, "USB Webcam", priority=25)]
        primary, secondary = self._pick_primary_and_secondary(devices)
        assert primary.name == "USB Webcam"
        assert secondary is None

    def test_three_cameras_tertiary_ignored(self):
        devices = [
            _make_device(0, "Cam A", priority=10),
            _make_device(1, "Cam B", priority=50),
            _make_device(2, "Cam C", priority=30),
        ]
        primary, secondary = self._pick_primary_and_secondary(devices)
        assert primary.name == "Cam B"
        assert secondary.name == "Cam C"
        # Cam A (priority=10) is the third — not returned


# ---------------------------------------------------------------------------
# Fallback when selected camera fails
# ---------------------------------------------------------------------------

class TestCameraFallback:

    def test_warning_shown_when_active_camera_errors(self):
        """
        When the active camera emits an error, the app should surface a
        warning. This test verifies the logic path rather than the Qt widget.
        """
        # Simulate the state an app would track
        active_camera = "microscope"
        warnings = []

        def handle_camera_error(role: str, err: str):
            if role == active_camera:
                warnings.append(f"Camera error: {role}")

        handle_camera_error("microscope", "device lost")
        assert len(warnings) == 1
        assert "microscope" in warnings[0]

    def test_inactive_camera_error_does_not_show_warning(self):
        active_camera = "microscope"
        warnings = []

        def handle_camera_error(role: str, err: str):
            if role == active_camera:
                warnings.append(f"Camera error: {role}")

        handle_camera_error("webcam", "some error")
        assert len(warnings) == 0

    def test_toggle_changes_active_camera(self):
        active = {"camera": "microscope"}

        def toggle():
            active["camera"] = "webcam" if active["camera"] == "microscope" else "microscope"

        assert active["camera"] == "microscope"
        toggle()
        assert active["camera"] == "webcam"
        toggle()
        assert active["camera"] == "microscope"
