"""
Rolling frame buffer for incident recording.

Keeps the last N seconds of camera frames in memory. When triggered (user
presses Save or software detects an error), the buffer is flushed to an MP4
file. Old frames are evicted automatically so memory stays bounded.

Thread-safe: add_frame() may be called from any thread; save() should only
be called from the main thread, but the lock makes concurrent access safe.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional
import time

import numpy as np


@dataclass
class _BufferedFrame:
    timestamp: float   # time.monotonic()
    frame: np.ndarray  # BGR, HxWx3 uint8


class RollingBuffer:
    """
    A time-bounded circular buffer of camera frames.

    Parameters
    ----------
    window_seconds:
        How many seconds of frames to retain (default 300 = 5 min).
    nominal_fps:
        Used as the output video FPS when save() writes an MP4. Does not
        control how fast frames are ingested.
    """

    def __init__(self, window_seconds: float = 300.0, nominal_fps: float = 30.0):
        self.window_seconds = window_seconds
        self.nominal_fps = nominal_fps
        self._frames: deque[_BufferedFrame] = deque()
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_frame(self, frame: np.ndarray) -> None:
        """Add a frame to the buffer, evicting frames outside the window."""
        now = time.monotonic()
        with self._lock:
            self._frames.append(_BufferedFrame(timestamp=now, frame=frame.copy()))
            cutoff = now - self.window_seconds
            while self._frames and self._frames[0].timestamp < cutoff:
                self._frames.popleft()

    def save(self, output_path: Path | str, fps: Optional[float] = None) -> bool:
        """
        Write the buffered frames to an MP4 file.

        Returns True if at least one frame was written, False otherwise.
        The file is written in one shot; no partial writes are visible.
        """
        try:
            import cv2
        except ImportError:
            return False

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            frames = list(self._frames)

        if not frames:
            return False

        write_fps = fps or self.nominal_fps
        h, w = frames[0].frame.shape[:2]

        # Write to a temp file first so a crash mid-write doesn't leave a
        # corrupt file at the final path.
        tmp_path = output_path.with_suffix(".tmp.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(tmp_path), fourcc, write_fps, (w, h))

        if not writer.isOpened():
            return False

        try:
            for bf in frames:
                writer.write(bf.frame)
        finally:
            writer.release()

        # Atomic rename
        import os
        os.replace(tmp_path, output_path)
        return True

    def clear(self) -> None:
        """Discard all buffered frames."""
        with self._lock:
            self._frames.clear()

    # ------------------------------------------------------------------
    # Introspection (read-only)
    # ------------------------------------------------------------------

    @property
    def frame_count(self) -> int:
        with self._lock:
            return len(self._frames)

    @property
    def duration_seconds(self) -> float:
        """Actual span of timestamps currently buffered."""
        with self._lock:
            if len(self._frames) < 2:
                return 0.0
            return self._frames[-1].timestamp - self._frames[0].timestamp

    @property
    def oldest_timestamp(self) -> Optional[float]:
        with self._lock:
            return self._frames[0].timestamp if self._frames else None

    @property
    def newest_timestamp(self) -> Optional[float]:
        with self._lock:
            return self._frames[-1].timestamp if self._frames else None
