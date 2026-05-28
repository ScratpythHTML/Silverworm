"""
Pytest configuration and fixtures for Silverworm tests.

Provides mocks for hardware components (camera, subprocess, file system)
to enable comprehensive testing without physical devices.
"""

import pytest
import sys
from unittest.mock import Mock, MagicMock, patch
import numpy as np

# Add project paths
sys.path.insert(0, '/Users/anhad/Silverworm-app/interface')
sys.path.insert(0, '/Users/anhad/Silverworm-app/image-processing')


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for v4l2-ctl calls"""
    with patch('subprocess.check_output') as mock:
        # Simulate v4l2-ctl output with AmScope camera
        mock.return_value = """
USB Camera (usb-0000:00:14.0-1):
\t/dev/video0
\t/dev/video1

AmScope HHD 8300-P (usb-0000:00:14.0-2):
\t/dev/video2
\t/dev/video3
"""
        yield mock


@pytest.fixture
def mock_glob():
    """Mock glob.glob for /dev/video* enumeration"""
    with patch('glob.glob') as mock:
        mock.return_value = ['/dev/video0', '/dev/video1', '/dev/video2', '/dev/video3']
        yield mock


@pytest.fixture
def mock_opencv_capture():
    """Mock cv2.VideoCapture for camera simulation"""
    with patch('cv2.VideoCapture') as mock:
        capture_instance = MagicMock()
        capture_instance.isOpened.return_value = True
        capture_instance.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
        capture_instance.get.side_effect = lambda prop: {
            5: 1920,    # CAP_PROP_FRAME_WIDTH
            4: 1080,    # CAP_PROP_FRAME_HEIGHT
            5: 30       # CAP_PROP_FPS
        }.get(prop, 0)
        capture_instance.set.return_value = True
        mock.return_value = capture_instance
        yield mock


@pytest.fixture
def sample_frame():
    """Generate sample BGR frame for testing"""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def sample_frame_hd():
    """Generate HD sample BGR frame"""
    return np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)


@pytest.fixture
def mock_os_access():
    """Mock os.access for permission checks"""
    with patch('os.access') as mock:
        mock.return_value = True  # Default: has permission
        yield mock


@pytest.fixture
def qapp(qapp):
    """Qt application fixture from pytest-qt"""
    return qapp
