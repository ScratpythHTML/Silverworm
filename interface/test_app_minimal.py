#!/usr/bin/env python3
"""Minimal test to isolate the crash"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

# Test imports
try:
    from camera import CameraDetector, CameraWorker, CameraConfig
    print("✓ Camera imports OK")
except Exception as e:
    print(f"✗ Camera import failed: {e}")
    sys.exit(1)

try:
    from processing import PitchDetectionPipeline
    print("✓ Processing imports OK")
except Exception as e:
    print(f"✗ Processing import failed: {e}")
    sys.exit(1)

try:
    from ui.camera_widget import EnhancedCameraView
    from ui.manual_mode_dialog import ManualModeBanner
    print("✓ UI imports OK")
except Exception as e:
    print(f"✗ UI import failed: {e}")
    sys.exit(1)

# Create QApplication
app = QApplication(sys.argv)
print("✓ QApplication created")

# Test camera detection
try:
    detector = CameraDetector()
    result = detector.detect_all_devices()
    print(f"✓ Camera detection completed: {len(result.devices)} devices found")
except Exception as e:
    print(f"✗ Camera detection failed: {e}")
    import traceback
    traceback.print_exc()

# Test pitch pipeline
try:
    pipeline = PitchDetectionPipeline(interval_ms=2000)
    print("✓ Pitch pipeline created")
    pipeline.start()
    print("✓ Pitch pipeline started")
    QTimer.singleShot(1000, lambda: pipeline.stop())
    print("✓ Pipeline stop scheduled")
except Exception as e:
    print(f"✗ Pitch pipeline failed: {e}")
    import traceback
    traceback.print_exc()

# Test camera widget
try:
    camera_widget = EnhancedCameraView()
    print("✓ Camera widget created")
except Exception as e:
    print(f"✗ Camera widget failed: {e}")
    import traceback
    traceback.print_exc()

print("\nAll basic tests passed! Now testing full MainWindow...")

# Import and test MainWindow
try:
    from app import MainWindow
    print("✓ MainWindow imported")

    window = MainWindow()
    print("✓ MainWindow created")

    window.show()
    print("✓ MainWindow shown")

    # Auto-exit after 2 seconds
    QTimer.singleShot(2000, app.quit)

    print("\nStarting event loop...")
    sys.exit(app.exec())
except Exception as e:
    print(f"✗ MainWindow failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
