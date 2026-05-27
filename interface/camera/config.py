"""
Camera configuration dataclasses.

Provides configuration presets for different cameras and platforms.
"""

from dataclasses import dataclass
import sys


@dataclass
class CameraConfig:
    """Camera configuration"""
    width: int = 1920           # Target width
    height: int = 1080          # Target height
    target_fps: int = 30        # Target FPS
    backend: str = 'fallback'   # Backend to use
    use_mjpeg: bool = False     # Use MJPEG for high resolution

    @classmethod
    def auto_detect_backend(cls):
        """Auto-detect the best backend for current platform"""
        if sys.platform == 'darwin':
            return 'fallback'  # Uses AVFoundation on macOS
        elif sys.platform == 'linux':
            return 'v4l2'
        else:
            return 'fallback'

    @classmethod
    def default(cls):
        """Default camera configuration"""
        return cls(
            width=1920,
            height=1080,
            target_fps=30,
            backend=cls.auto_detect_backend(),
            use_mjpeg=False
        )

    @classmethod
    def amscope_8300p(cls):
        """AmScope HHD 8300-P optimal settings (full resolution)"""
        return cls(
            width=3264,
            height=2448,
            target_fps=15,  # 8MP at 15fps
            backend=cls.auto_detect_backend(),
            use_mjpeg=True if sys.platform == 'linux' else False
        )

    @classmethod
    def amscope_8300p_lowres(cls):
        """AmScope HHD 8300-P lower resolution for better performance"""
        return cls(
            width=1920,
            height=1080,
            target_fps=30,
            backend=cls.auto_detect_backend(),
            use_mjpeg=False
        )

    @classmethod
    def macbook_camera(cls):
        """MacBook built-in camera settings"""
        return cls(
            width=1280,
            height=720,
            target_fps=30,
            backend='fallback',  # Uses AVFoundation
            use_mjpeg=False
        )
