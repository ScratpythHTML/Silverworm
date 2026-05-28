"""
Camera device detection and diagnostics for Linux.

Provides robust detection of AmScope HHD 8300-P microscope camera with
support for V4L2, GStreamer, and USB imaging devices.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import subprocess
import os
import glob
import re


@dataclass
class CameraDevice:
    """Represents a detected camera device"""
    index: int                    # OpenCV device index
    path: str                     # /dev/video* path (Linux only)
    name: str                     # Device name from v4l2-ctl
    driver: str                   # Driver name
    capabilities: List[str] = field(default_factory=list)  # Device capabilities
    is_v4l2: bool = True         # V4L2 compatible
    is_usb_imaging: bool = False # USB imaging device (non-V4L2)
    priority: int = 0            # Selection priority (higher = better)
    width: int = 0               # Resolution width
    height: int = 0              # Resolution height


@dataclass
class DiagnosticResult:
    """Complete diagnostic information"""
    devices: List[CameraDevice] = field(default_factory=list)
    selected_device: Optional[CameraDevice] = None
    video_paths: List[str] = field(default_factory=list)        # All /dev/video* found
    v4l2_output: str = ""              # v4l2-ctl --list-devices output
    opencv_backends: List[str] = field(default_factory=list)     # Available OpenCV backends
    errors: List[str] = field(default_factory=list)             # Any errors encountered
    warnings: List[str] = field(default_factory=list)           # Warnings (permissions, etc.)


class CameraDetector:
    """Detects and diagnoses camera devices on Linux"""

    AMSCOPE_IDENTIFIERS = [
        "amscope",
        "hhd",
        "8300",
        "usb camera",
        "uvc",  # USB Video Class (generic but common)
    ]

    def __init__(self):
        self.diagnostic_result: Optional[DiagnosticResult] = None

    def detect_all_devices(self) -> DiagnosticResult:
        """
        Comprehensive camera detection:
        Linux: Enumerate /dev/video*, run v4l2-ctl, probe with OpenCV
        macOS: Probe camera indices 0-10 with AVFoundation
        """
        import sys

        # Platform-specific detection
        if sys.platform == 'darwin':
            return self._detect_macos_devices()
        else:
            return self._detect_linux_devices()

    def _detect_macos_devices(self) -> DiagnosticResult:
        """Detect cameras on macOS using AVFoundation"""
        devices = []
        errors = []
        warnings = []

        print("Detecting cameras on macOS...")

        # Try camera indices 0-10
        for idx in range(11):
            device = self._probe_device_macos(idx)
            if device:
                devices.append(device)
                print(f"  Found camera at index {idx}: {device.name}")

        # Detect available OpenCV backends
        opencv_backends = self._detect_opencv_backends()

        # Select best device
        selected = self._select_device(devices)

        diagnostic = DiagnosticResult(
            devices=devices,
            selected_device=selected,
            video_paths=[],  # No /dev/video* on macOS
            v4l2_output="",
            opencv_backends=opencv_backends,
            errors=errors,
            warnings=warnings
        )

        self.diagnostic_result = diagnostic
        return diagnostic

    def _detect_linux_devices(self) -> DiagnosticResult:
        """Detect cameras on Linux using V4L2"""
        devices = []
        errors = []
        warnings = []

        # Step 1: Find /dev/video* paths
        try:
            video_paths = sorted(glob.glob('/dev/video*'))
        except Exception as e:
            errors.append(f"Failed to enumerate /dev/video* devices: {e}")
            video_paths = []

        # Step 2: Parse v4l2-ctl output
        v4l2_output = ""
        v4l2_devices = {}
        try:
            v4l2_output = subprocess.check_output(
                ['v4l2-ctl', '--list-devices'],
                stderr=subprocess.STDOUT,
                timeout=5,
                text=True
            )
            v4l2_devices = self._parse_v4l2_output(v4l2_output)
        except FileNotFoundError:
            warnings.append("v4l2-ctl not found - install v4l-utils: sudo apt-get install v4l-utils")
        except subprocess.CalledProcessError as e:
            errors.append(f"v4l2-ctl failed: {e.output}")
        except subprocess.TimeoutExpired:
            errors.append("v4l2-ctl timeout")
        except Exception as e:
            errors.append(f"v4l2-ctl error: {e}")

        # Step 3: Check permissions
        for path in video_paths:
            if not os.access(path, os.R_OK | os.W_OK):
                warnings.append(
                    f"Insufficient permissions for {path}. "
                    f"Add user to 'video' group: sudo usermod -a -G video $USER (then logout/login)"
                )

        # Step 4: Probe with OpenCV
        for idx, path in enumerate(video_paths):
            device = self._probe_device(idx, path, v4l2_devices)
            if device:
                devices.append(device)

        # Step 5: Detect available OpenCV backends
        opencv_backends = self._detect_opencv_backends()

        # Step 6: Select best device
        selected = self._select_device(devices)

        diagnostic = DiagnosticResult(
            devices=devices,
            selected_device=selected,
            video_paths=video_paths,
            v4l2_output=v4l2_output,
            opencv_backends=opencv_backends,
            errors=errors,
            warnings=warnings
        )

        self.diagnostic_result = diagnostic
        return diagnostic

    def _parse_v4l2_output(self, output: str) -> Dict[str, Dict[str, str]]:
        """
        Parse v4l2-ctl output into device info.

        Format:
        Device name (usb-xxx):
            /dev/video0
            /dev/video1
        """
        devices = {}
        current_name = None
        current_driver = ""

        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue

            # Device name line (ends with colon)
            if line.endswith(':'):
                # Extract name and driver
                match = re.match(r'(.+?)\s*\((.+?)\):', line)
                if match:
                    current_name = match.group(1).strip()
                    current_driver = match.group(2).strip()
                else:
                    current_name = line[:-1].strip()
                    current_driver = "unknown"

            # Device path line (starts with /dev/)
            elif line.startswith('/dev/video') and current_name:
                devices[line] = {
                    'name': current_name,
                    'driver': current_driver,
                    'capabilities': []
                }

        return devices

    def _probe_device_macos(self, idx: int) -> Optional[CameraDevice]:
        """Probe a single camera on macOS using AVFoundation"""
        try:
            import cv2
            import time
        except ImportError:
            return None

        # Try to open device with AVFoundation
        cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)

        # Give camera time to initialize
        time.sleep(0.3)

        if not cap.isOpened():
            return None

        # Get device info
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = int(cap.get(cv2.CAP_PROP_FPS))
        except:
            width, height, fps = 0, 0, 0
        finally:
            cap.release()

        # Use camera name from system if available
        name = f"Camera {idx}"

        # Try to get actual camera name from system_profiler
        try:
            result = subprocess.check_output(
                ['system_profiler', 'SPCameraDataType'],
                timeout=2,
                text=True
            )
            # Parse camera names from output
            lines = result.split('\n')
            camera_names = [line.strip().replace(':', '') for line in lines
                          if ':' in line and 'camera' in line.lower()]
            if idx < len(camera_names):
                name = camera_names[idx]
        except:
            pass

        # Calculate priority
        priority = self._calculate_priority(name, f"index{idx}", width, height)

        return CameraDevice(
            index=idx,
            path=f"index{idx}",
            name=name,
            driver="AVFoundation",
            capabilities=["video_capture"],
            is_v4l2=False,
            is_usb_imaging=False,
            priority=priority,
            width=width,
            height=height
        )

    def _probe_device(self, idx: int, path: str, v4l2_info: Dict) -> Optional[CameraDevice]:
        """Probe a single device with OpenCV"""
        try:
            import cv2
        except ImportError:
            return None

        # Try to open device with V4L2
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not cap.isOpened():
            # Try without V4L2
            cap = cv2.VideoCapture(idx)

        if not cap.isOpened():
            return None

        # Get device info
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = int(cap.get(cv2.CAP_PROP_FPS))
        except:
            width, height, fps = 0, 0, 0
        finally:
            cap.release()

        # Get V4L2 info
        device_info = v4l2_info.get(path, {})
        name = device_info.get('name', 'Unknown Camera')
        driver = device_info.get('driver', 'unknown')

        # Calculate priority
        priority = self._calculate_priority(name, path, width, height)

        return CameraDevice(
            index=idx,
            path=path,
            name=name,
            driver=driver,
            capabilities=device_info.get('capabilities', []),
            is_v4l2=True,
            is_usb_imaging=False,
            priority=priority,
            width=width,
            height=height
        )

    def _calculate_priority(self, name: str, path: str, width: int, height: int) -> int:
        """Calculate device selection priority"""
        priority = 0

        # AmScope identifiers get highest priority
        name_lower = name.lower()
        for identifier in self.AMSCOPE_IDENTIFIERS:
            if identifier in name_lower:
                priority += 100
                break

        # Higher resolution = higher priority
        if width >= 3264:  # 8MP (AmScope HHD 8300-P)
            priority += 50
        elif width >= 1920:  # Full HD
            priority += 20
        elif width >= 1280:  # HD
            priority += 10

        # /dev/video0 gets slight boost (often the primary camera)
        if path == '/dev/video0':
            priority += 5

        return priority

    def _select_device(self, devices: List[CameraDevice]) -> Optional[CameraDevice]:
        """Select the best device based on priority"""
        if not devices:
            return None
        return max(devices, key=lambda d: d.priority)

    def _detect_opencv_backends(self) -> List[str]:
        """Detect available OpenCV backends"""
        try:
            import cv2
        except ImportError:
            return []

        backends = []

        # Try V4L2
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
            if cap.isOpened():
                backends.append('V4L2')
            cap.release()
        except:
            pass

        # Try GStreamer
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_GSTREAMER)
            if cap.isOpened():
                backends.append('GStreamer')
            cap.release()
        except:
            pass

        return backends

    def format_diagnostic_report(self) -> str:
        """Generate human-readable diagnostic report"""
        if not self.diagnostic_result:
            return "No diagnostics run yet. Call detect_all_devices() first."

        report = ["=" * 80]
        report.append("CAMERA DIAGNOSTIC REPORT")
        report.append("=" * 80)

        diag = self.diagnostic_result

        # Video devices found
        report.append(f"\n/dev/video* devices found: {len(diag.video_paths)}")
        for path in diag.video_paths:
            report.append(f"  {path}")

        # Detected cameras
        report.append(f"\nCamera devices detected: {len(diag.devices)}")
        for dev in diag.devices:
            report.append(
                f"  [{dev.index}] {dev.path} - {dev.name} "
                f"({dev.width}x{dev.height}, priority: {dev.priority})"
            )

        # Selected device
        if diag.selected_device:
            dev = diag.selected_device
            report.append(f"\nSelected Camera:")
            report.append(f"  Device: {dev.path} (index {dev.index})")
            report.append(f"  Name: {dev.name}")
            report.append(f"  Driver: {dev.driver}")
            report.append(f"  Resolution: {dev.width}x{dev.height}")
            report.append(f"  Priority: {dev.priority}")
        else:
            report.append("\nNo suitable camera selected")

        # OpenCV backends
        if diag.opencv_backends:
            report.append(f"\nOpenCV backends available: {', '.join(diag.opencv_backends)}")
        else:
            report.append("\nNo OpenCV backends detected")

        # Errors
        if diag.errors:
            report.append("\nERRORS:")
            for err in diag.errors:
                report.append(f"  ✗ {err}")

        # Warnings
        if diag.warnings:
            report.append("\nWARNINGS:")
            for warn in diag.warnings:
                report.append(f"  ⚠ {warn}")

        report.append("=" * 80)
        return "\n".join(report)
