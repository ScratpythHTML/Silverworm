#!/usr/bin/env python3
"""
Diagnostic script for Silverworm application.

Run this to check if everything is set up correctly.
"""

import sys
import os

print("="*80)
print("SILVERWORM DIAGNOSTIC TOOL")
print("="*80)
print()

# Check Python version
print(f"Python version: {sys.version}")
if sys.version_info < (3, 9):
    print("✗ ERROR: Python 3.9+ required")
    sys.exit(1)
print("✓ Python version OK")
print()

# Check imports
print("Checking imports...")
errors = []

try:
    from PyQt6.QtCore import PYQT_VERSION_STR
    print(f"✓ PyQt6 {PYQT_VERSION_STR}")
except ImportError as e:
    errors.append(f"PyQt6 not installed: {e}")
    print(f"✗ PyQt6 missing")

try:
    import cv2
    print(f"✓ OpenCV {cv2.__version__}")
except ImportError as e:
    errors.append(f"OpenCV not installed: {e}")
    print(f"✗ OpenCV missing (install with: pip install opencv-python)")

try:
    import numpy as np
    print(f"✓ NumPy {np.__version__}")
except ImportError as e:
    errors.append(f"NumPy not installed: {e}")
    print(f"✗ NumPy missing")

try:
    import scipy
    print(f"✓ SciPy {scipy.__version__}")
except ImportError as e:
    print(f"⚠ SciPy missing (needed for pitch detection)")

print()

# Check module imports
print("Checking custom modules...")
sys.path.insert(0, os.path.dirname(__file__))

try:
    from camera import CameraDetector, CameraWorker, CameraConfig
    print("✓ Camera module")
except Exception as e:
    errors.append(f"Camera module import failed: {e}")
    print(f"✗ Camera module: {e}")

try:
    from processing import PitchDetectionPipeline
    print("✓ Processing module")
except Exception as e:
    errors.append(f"Processing module import failed: {e}")
    print(f"✗ Processing module: {e}")

try:
    from ui.camera_widget import EnhancedCameraView
    from ui.manual_mode_dialog import ManualModeBanner
    print("✓ UI modules")
except Exception as e:
    errors.append(f"UI module import failed: {e}")
    print(f"✗ UI modules: {e}")

print()

# Test camera detection
print("Testing camera detection...")
try:
    from camera import CameraDetector
    detector = CameraDetector()
    result = detector.detect_all_devices()
    print(f"  Found {len(result.devices)} camera device(s)")
    if result.selected_device:
        print(f"  Selected: {result.selected_device.name}")
    else:
        print(f"  ⚠ No camera detected (demo mode will be used)")
    if result.warnings:
        for warn in result.warnings[:2]:
            print(f"  ⚠ {warn}")
except Exception as e:
    errors.append(f"Camera detection failed: {e}")
    print(f"✗ Camera detection error: {e}")

print()

# Summary
print("="*80)
if errors:
    print(f"ERRORS FOUND: {len(errors)}")
    for err in errors:
        print(f"  • {err}")
    print()
    print("Please fix the errors above before running the application.")
    print()
    print("Common fixes:")
    print("  pip install PyQt6 opencv-python numpy scipy")
else:
    print("✓ ALL CHECKS PASSED")
    print()
    print("The application should work correctly.")
    print("Run with: python3 app.py")
    print()
    print("Note: If no camera is detected, the app will show a demo mode")
    print("      animation. This is normal if you don't have a camera connected.")

print("="*80)
