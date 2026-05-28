"""
Camera module for AmScope HHD 8300-P microscope integration.

Provides device detection, capture worker thread, and backend abstraction
for V4L2 and GStreamer on Linux.
"""

from .config import CameraConfig
from .detector import CameraDetector, CameraDevice, DiagnosticResult
from .capture import CameraWorker
from .rolling_buffer import RollingBuffer

__all__ = [
    'CameraConfig',
    'CameraDetector',
    'CameraDevice',
    'DiagnosticResult',
    'CameraWorker',
    'RollingBuffer',
]
