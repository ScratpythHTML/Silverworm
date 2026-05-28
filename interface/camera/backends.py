"""
Camera backend abstraction for V4L2 and GStreamer.

Provides a unified interface for different camera backends with automatic
fallback support.
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple
import numpy as np


class CameraBackend(ABC):
    """Abstract camera backend interface"""

    @abstractmethod
    def open(self, device_index: int) -> bool:
        """
        Open camera device.

        Args:
            device_index: Device index (e.g., 0 for /dev/video0)

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """
        Read a frame from the camera.

        Returns:
            (success, frame) tuple where frame is BGR numpy array
        """
        pass

    @abstractmethod
    def release(self):
        """Release camera device"""
        pass

    @abstractmethod
    def get_property(self, prop: int) -> float:
        """
        Get camera property value.

        Args:
            prop: OpenCV property constant (e.g., cv2.CAP_PROP_FRAME_WIDTH)

        Returns:
            Property value
        """
        pass

    @abstractmethod
    def set_property(self, prop: int, value: float) -> bool:
        """
        Set camera property value.

        Args:
            prop: OpenCV property constant
            value: Value to set

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def is_opened(self) -> bool:
        """Check if camera is currently opened"""
        pass


class V4L2Backend(CameraBackend):
    """V4L2 backend for Linux (Video4Linux2)"""

    def __init__(self):
        self.cap: Optional['cv2.VideoCapture'] = None

    def open(self, device_index: int) -> bool:
        """Open camera with V4L2 backend"""
        try:
            import cv2
            self.cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
            return self.cap.isOpened()
        except Exception as e:
            print(f"V4L2Backend open error: {e}")
            return False

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read frame from V4L2 device"""
        if not self.cap:
            return False, None
        return self.cap.read()

    def release(self):
        """Release V4L2 device"""
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_property(self, prop: int) -> float:
        """Get V4L2 property"""
        if not self.cap:
            return 0.0
        return self.cap.get(prop)

    def set_property(self, prop: int, value: float) -> bool:
        """Set V4L2 property"""
        if not self.cap:
            return False
        return self.cap.set(prop, value)

    def is_opened(self) -> bool:
        """Check if V4L2 device is opened"""
        return self.cap is not None and self.cap.isOpened()


class GStreamerBackend(CameraBackend):
    """GStreamer backend (fallback for devices not working with V4L2)"""

    def __init__(self):
        self.cap: Optional['cv2.VideoCapture'] = None
        self.device_path: str = ""

    def open(self, device_index: int) -> bool:
        """Open camera with GStreamer backend"""
        try:
            import cv2
            self.device_path = f"/dev/video{device_index}"

            # GStreamer pipeline for V4L2 source
            pipeline = (
                f"v4l2src device={self.device_path} ! "
                "videoconvert ! "
                "video/x-raw,format=BGR ! "
                "appsink"
            )

            self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            return self.cap.isOpened()
        except Exception as e:
            print(f"GStreamerBackend open error: {e}")
            return False

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read frame from GStreamer pipeline"""
        if not self.cap:
            return False, None
        return self.cap.read()

    def release(self):
        """Release GStreamer pipeline"""
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_property(self, prop: int) -> float:
        """Get GStreamer property"""
        if not self.cap:
            return 0.0
        return self.cap.get(prop)

    def set_property(self, prop: int, value: float) -> bool:
        """Set GStreamer property"""
        if not self.cap:
            return False
        return self.cap.set(prop, value)

    def is_opened(self) -> bool:
        """Check if GStreamer pipeline is opened"""
        return self.cap is not None and self.cap.isOpened()


class AVFoundationBackend(CameraBackend):
    """AVFoundation backend for macOS cameras"""

    def __init__(self):
        self.cap: Optional['cv2.VideoCapture'] = None

    def open(self, device_index: int) -> bool:
        """Open camera with AVFoundation backend (macOS)"""
        try:
            import cv2
            import time

            self.cap = cv2.VideoCapture(device_index, cv2.CAP_AVFOUNDATION)

            # Give camera time to initialize on macOS
            time.sleep(0.3)

            return self.cap.isOpened()
        except Exception as e:
            print(f"AVFoundationBackend open error: {e}")
            return False

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read frame from AVFoundation device"""
        if not self.cap:
            return False, None
        return self.cap.read()

    def release(self):
        """Release AVFoundation device"""
        if self.cap:
            self.cap.release()
            self.cap = None

    def get_property(self, prop: int) -> float:
        """Get AVFoundation property"""
        if not self.cap:
            return 0.0
        return self.cap.get(prop)

    def set_property(self, prop: int, value: float) -> bool:
        """Set AVFoundation property"""
        if not self.cap:
            return False
        return self.cap.set(prop, value)

    def is_opened(self) -> bool:
        """Check if AVFoundation device is opened"""
        return self.cap is not None and self.cap.isOpened()


class FallbackBackend(CameraBackend):
    """
    Fallback backend that tries platform-specific backends automatically.
    Linux: V4L2 → GStreamer → Auto
    macOS: AVFoundation → Auto
    """

    def __init__(self):
        self.cap: Optional['cv2.VideoCapture'] = None
        self.active_backend: str = ""

    def open(self, device_index: int) -> bool:
        """Try opening with platform-appropriate backends"""
        try:
            import cv2
            import sys
        except ImportError:
            return False

        # macOS: Try AVFoundation first
        if sys.platform == 'darwin':
            try:
                import time
                self.cap = cv2.VideoCapture(device_index, cv2.CAP_AVFOUNDATION)
                time.sleep(0.3)  # Let camera initialize
                if self.cap.isOpened():
                    self.active_backend = "AVFoundation"
                    return True
            except:
                pass

        # Linux: Try V4L2 first
        if sys.platform == 'linux':
            try:
                self.cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)
                if self.cap.isOpened():
                    self.active_backend = "V4L2"
                    return True
            except:
                pass

            # Try GStreamer on Linux
            try:
                pipeline = (
                    f"v4l2src device=/dev/video{device_index} ! "
                    "videoconvert ! "
                    "video/x-raw,format=BGR ! "
                    "appsink"
                )
                self.cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
                if self.cap.isOpened():
                    self.active_backend = "GStreamer"
                    return True
            except:
                pass

        # Try plain OpenCV (auto backend) as last resort
        try:
            self.cap = cv2.VideoCapture(device_index)
            if self.cap.isOpened():
                self.active_backend = "Auto"
                return True
        except:
            pass

        return False

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read frame from active backend"""
        if not self.cap:
            return False, None
        return self.cap.read()

    def release(self):
        """Release active backend"""
        if self.cap:
            self.cap.release()
            self.cap = None
        self.active_backend = ""

    def get_property(self, prop: int) -> float:
        """Get property from active backend"""
        if not self.cap:
            return 0.0
        return self.cap.get(prop)

    def set_property(self, prop: int, value: float) -> bool:
        """Set property on active backend"""
        if not self.cap:
            return False
        return self.cap.set(prop, value)

    def is_opened(self) -> bool:
        """Check if backend is opened"""
        return self.cap is not None and self.cap.isOpened()


class BackendFactory:
    """Factory for creating camera backends with fallback support"""

    @staticmethod
    def create_backend(preferred: str = 'v4l2') -> CameraBackend:
        """
        Create backend with automatic fallback.

        Args:
            preferred: Preferred backend ('v4l2', 'gstreamer', or 'fallback')

        Returns:
            CameraBackend instance
        """
        preferred_lower = preferred.lower()

        if preferred_lower == 'v4l2':
            return V4L2Backend()
        elif preferred_lower == 'gstreamer':
            return GStreamerBackend()
        elif preferred_lower == 'fallback':
            return FallbackBackend()
        else:
            # Default to fallback for maximum compatibility
            return FallbackBackend()
