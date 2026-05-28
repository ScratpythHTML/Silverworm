"""
Camera capture worker thread.

Provides QThread-based background frame capture with thread-safe signal
communication to the main UI thread.
"""

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
import numpy as np
from typing import Optional
import time

from .backends import CameraBackend, BackendFactory
from .config import CameraConfig


class CameraWorker(QThread):
    """
    QThread worker for camera frame capture.

    Runs in a background thread and emits frames via signals for thread-safe
    communication with the UI. Supports pause/resume and clean shutdown.

    Signals:
        frame_ready: Emitted when a new frame is available (BGR numpy array)
        error_occurred: Emitted when an error occurs (error message string)
        status_changed: Emitted when worker status changes (status string)
        fps_updated: Emitted periodically with actual FPS (float)
    """

    # Signals for thread-safe communication
    frame_ready = pyqtSignal(np.ndarray)      # BGR frame
    error_occurred = pyqtSignal(str)          # Error message
    status_changed = pyqtSignal(str)          # Status update
    fps_updated = pyqtSignal(float)           # Actual FPS

    def __init__(self, device_index: int, config: CameraConfig, parent=None):
        """
        Initialize camera worker.

        Args:
            device_index: Camera device index (e.g., 0 for /dev/video0)
            config: Camera configuration
            parent: Parent QObject
        """
        super().__init__(parent)
        self.device_index = device_index
        self.config = config
        self.backend: Optional[CameraBackend] = None

        # Thread control
        self._running = False
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._paused = False

        # FPS tracking
        self._frame_count = 0
        self._last_fps_update = 0.0

    def run(self):
        """Main thread loop - runs in background thread"""

        # Initialize backend
        try:
            self.backend = BackendFactory.create_backend(self.config.backend)
            if not self.backend.open(self.device_index):
                self.error_occurred.emit(
                    f"Failed to open camera device {self.device_index} "
                    f"with {self.config.backend} backend"
                )
                return
        except Exception as e:
            self.error_occurred.emit(f"Backend initialization failed: {e}")
            return

        # Configure camera properties
        self._configure_camera()

        self._running = True
        self.status_changed.emit("Camera running")

        self._last_fps_update = time.time()

        # Main capture loop
        while self._running:
            # Check if paused
            self._mutex.lock()
            if self._paused:
                self._condition.wait(self._mutex)
            self._mutex.unlock()

            if not self._running:
                break

            # Read frame
            try:
                success, frame = self.backend.read_frame()
            except Exception as e:
                self.error_occurred.emit(f"Frame read exception: {e}")
                time.sleep(0.1)
                continue

            if not success or frame is None:
                # Frame read failed - retry after brief pause
                time.sleep(0.05)
                continue

            # Emit frame (thread-safe via signal)
            self.frame_ready.emit(frame)

            # Update FPS counter
            self._frame_count += 1
            current_time = time.time()
            elapsed = current_time - self._last_fps_update

            if elapsed >= 1.0:
                fps = self._frame_count / elapsed
                self.fps_updated.emit(fps)
                self._frame_count = 0
                self._last_fps_update = current_time

            # Sleep to achieve target FPS (avoid busy-waiting)
            if self.config.target_fps > 0:
                time.sleep(1.0 / self.config.target_fps)

        # Cleanup
        if self.backend:
            self.backend.release()
        self.status_changed.emit("Camera stopped")

    def _configure_camera(self):
        """Configure camera properties based on config"""
        if not self.backend or not self.backend.is_opened():
            return

        try:
            import cv2

            # Set resolution
            self.backend.set_property(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            self.backend.set_property(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)

            # Set FPS
            self.backend.set_property(cv2.CAP_PROP_FPS, self.config.target_fps)

            # Set format (MJPEG for high resolution)
            if self.config.use_mjpeg:
                fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                self.backend.set_property(cv2.CAP_PROP_FOURCC, fourcc)

        except Exception as e:
            self.error_occurred.emit(f"Camera configuration error: {e}")

    def pause(self):
        """Pause frame capture (thread-safe)"""
        self._mutex.lock()
        self._paused = True
        self._mutex.unlock()
        self.status_changed.emit("Camera paused")

    def resume(self):
        """Resume frame capture (thread-safe)"""
        self._mutex.lock()
        self._paused = False
        self._condition.wakeAll()
        self._mutex.unlock()
        self.status_changed.emit("Camera resumed")

    def stop(self):
        """Stop capture and exit thread (blocks until thread finishes)"""
        self._running = False
        self.resume()  # Ensure not stuck in pause
        self.wait()    # Wait for thread to finish
