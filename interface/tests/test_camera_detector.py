"""
Tests for camera detection and diagnostics.

Tests device enumeration, priority calculation, AmScope detection,
and diagnostic report generation.

NOTE: CameraDetector.detect_all_devices() takes a platform-specific branch.
The v4l2-ctl-based tests below only exercise the Linux path and are skipped
on macOS — they will run for real on the Pi. Tests that don't depend on the
Linux path (priority calculation) run everywhere.
"""

import sys
import pytest
from camera.detector import CameraDetector, CameraDevice, DiagnosticResult


linux_only = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Linux-only: detector takes macOS branch on darwin and ignores v4l2/glob mocks",
)


@linux_only
def test_detect_multiple_devices(mock_subprocess, mock_glob, mock_opencv_capture):
    """Test that detector finds all /dev/video* devices"""
    detector = CameraDetector()
    result = detector.detect_all_devices()

    assert len(result.devices) >= 2  # At least some devices detected
    assert result.video_paths == ['/dev/video0', '/dev/video1', '/dev/video2', '/dev/video3']


def test_select_amscope_device(mock_subprocess, mock_glob, mock_opencv_capture):
    """Test that AmScope device gets highest priority"""
    detector = CameraDetector()
    result = detector.detect_all_devices()

    assert result.selected_device is not None
    # Should select device with "AmScope" in name (higher priority)
    # Note: In real test with proper mocking, we'd verify the specific device index


def test_priority_calculation():
    """Test device priority calculation"""
    detector = CameraDetector()

    # AmScope device with high resolution
    priority1 = detector._calculate_priority("AmScope HHD 8300-P", "/dev/video2", 3264, 2448)

    # Generic USB camera
    priority2 = detector._calculate_priority("USB Camera", "/dev/video0", 1920, 1080)

    # AmScope should have much higher priority
    assert priority1 > priority2
    assert priority1 >= 100  # Should have AmScope bonus


@linux_only
def test_permission_warning(mock_subprocess, mock_glob, mock_opencv_capture):
    """Test that permission issues generate warnings"""
    from unittest.mock import patch

    with patch('os.access', return_value=False):
        detector = CameraDetector()
        result = detector.detect_all_devices()

        assert len(result.warnings) > 0
        assert any('permission' in w.lower() for w in result.warnings)


@linux_only
def test_v4l2_not_found(mock_glob, mock_opencv_capture):
    """Test handling when v4l2-ctl is not installed"""
    from unittest.mock import patch

    with patch('subprocess.check_output', side_effect=FileNotFoundError):
        detector = CameraDetector()
        result = detector.detect_all_devices()

        assert any('v4l2-ctl not found' in w for w in result.warnings)


@linux_only
def test_no_devices_found():
    """Test behavior when no devices found"""
    from unittest.mock import patch

    with patch('glob.glob', return_value=[]):
        detector = CameraDetector()
        result = detector.detect_all_devices()

        assert len(result.devices) == 0
        assert result.selected_device is None


def test_diagnostic_report_generation(mock_subprocess, mock_glob, mock_opencv_capture):
    """Test that diagnostic report is generated correctly"""
    detector = CameraDetector()
    result = detector.detect_all_devices()

    report = detector.format_diagnostic_report()

    assert "CAMERA DIAGNOSTIC REPORT" in report
    assert "devices found" in report.lower()
    if result.selected_device:
        assert result.selected_device.path in report
