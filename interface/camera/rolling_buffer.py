"""
Disk-backed rolling recorder for incident capture.

Continuously records the camera feed to short MP4 *segments* on flash
storage (NOT RAM). Frames are encoded on the fly, so RAM holds at most the
single frame currently being written — never the whole window. Only the
last ``window_seconds`` of footage is retained; older segments are deleted,
and a hard byte cap bounds total disk use.

Lifecycle:
  - ``add_frame()``  — called continuously from the camera thread.
  - ``save(path)``   — on a *sudden error*, flush the recent footage to one
                       permanent MP4. (Rare; re-encodes the segments.)
  - ``discard()``    — on a normal shutdown, delete the temp segments. We do
                       not keep routine footage.

Thread-safe: ``add_frame()`` runs on the camera thread; ``save()`` /
``discard()`` on the main thread. A lock serialises access to the cv2 writer
and the segment list.

The class name is kept as ``RollingBuffer`` for import compatibility, but it
is a disk recorder — nothing of size is held in memory.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Optional
import os
import time

import numpy as np

try:
    import cv2
except ImportError:  # headless / CI without OpenCV
    cv2 = None


@dataclass
class _Segment:
    path: Path
    start_ts: float   # time.monotonic() of first frame
    end_ts: float     # time.monotonic() of last frame
    frames: int
    nbytes: int


class RollingBuffer:
    """
    A disk-backed, time- and size-bounded rolling video recorder.

    Parameters
    ----------
    temp_dir:
        Directory on flash for temporary segment files. Cleared of stale
        ``seg_*.mp4`` files on construction.
    window_seconds:
        How many seconds of footage to retain (default 180 = 3 min).
    segment_seconds:
        Length of each MP4 segment before rotating to a new file.
    sample_fps:
        Maximum frames written per second (0 = write every frame). Bounds
        encode load and file size.
    max_bytes:
        Hard cap on total retained segment bytes. Default 4 GiB — well under
        the CM5's 32 GB flash and never reached by 3 min of compressed video.
    nominal_fps:
        Playback FPS recorded into the MP4 headers.
    fourcc:
        VideoWriter codec (default ``mp4v``).
    """

    def __init__(
        self,
        temp_dir: Path | str,
        window_seconds: float = 180.0,
        segment_seconds: float = 15.0,
        sample_fps: float = 15.0,
        max_bytes: int = 4 * 1024 ** 3,
        nominal_fps: float = 15.0,
        fourcc: str = "mp4v",
    ):
        self.temp_dir = Path(temp_dir)
        self.window_seconds = window_seconds
        self.segment_seconds = segment_seconds
        self.sample_fps = sample_fps
        self.max_bytes = max_bytes
        self.nominal_fps = nominal_fps
        self.fourcc = fourcc

        self._segments: deque[_Segment] = deque()
        self._finalized_bytes = 0
        self._seg_counter = 0
        self._lock = Lock()

        # Current open segment (None when not recording).
        self._writer = None
        self._writer_path: Optional[Path] = None
        self._writer_start_ts = 0.0
        self._writer_last_ts = 0.0
        self._writer_frames = 0
        self._writer_size: Optional[tuple[int, int]] = None  # (w, h)
        self._last_store_ts = 0.0

        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._purge_temp_dir()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_frame(self, frame: np.ndarray) -> None:
        """Encode a frame into the current segment, rotating/pruning as needed."""
        if cv2 is None or frame is None or frame.size == 0:
            return

        now = time.monotonic()
        h, w = frame.shape[:2]
        size = (w, h)

        with self._lock:
            # Sampling: skip frames arriving faster than sample_fps.
            if (
                self.sample_fps > 0
                and self._writer is not None
                and now - self._last_store_ts < 1.0 / self.sample_fps
            ):
                return

            rotate = (
                self._writer is None
                or self._writer_size != size
                or (now - self._writer_start_ts) >= self.segment_seconds
            )
            if rotate:
                self._finalize_locked()
                self._open_locked(size, now)

            if self._writer is None:
                return  # writer failed to open (e.g. bad codec)

            self._writer.write(frame)
            self._writer_frames += 1
            self._writer_last_ts = now
            self._last_store_ts = now
            self._prune_locked(now)

    def save(self, output_path: Path | str, fps: Optional[float] = None) -> bool:
        """
        Concatenate the retained segments into one permanent MP4.

        Returns True if at least one frame was written. The in-progress
        segment is finalised first so the most recent footage is included.
        """
        if cv2 is None:
            return False

        with self._lock:
            self._finalize_locked()
            segments = list(self._segments)

        if not segments:
            return False

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_fps = fps or self.nominal_fps
        tmp_path = output_path.with_suffix(".tmp.mp4")
        fourcc = cv2.VideoWriter_fourcc(*self.fourcc)

        writer = None
        out_size: Optional[tuple[int, int]] = None
        try:
            for seg in segments:
                cap = cv2.VideoCapture(str(seg.path))
                try:
                    while True:
                        ok, frame = cap.read()
                        if not ok:
                            break
                        if writer is None:
                            out_size = (frame.shape[1], frame.shape[0])
                            writer = cv2.VideoWriter(
                                str(tmp_path), fourcc, write_fps, out_size
                            )
                            if not writer.isOpened():
                                return False
                        if (frame.shape[1], frame.shape[0]) != out_size:
                            frame = cv2.resize(frame, out_size)
                        writer.write(frame)
                finally:
                    cap.release()
        finally:
            if writer is not None:
                writer.release()

        if writer is None:  # nothing decoded
            if tmp_path.exists():
                tmp_path.unlink()
            return False

        os.replace(tmp_path, output_path)
        return True

    def discard(self) -> None:
        """Stop recording and delete all temporary segments."""
        with self._lock:
            self._finalize_locked()
            while self._segments:
                self._remove_oldest_locked()
            self._finalized_bytes = 0

    def clear(self) -> None:
        """Alias for discard() — drop everything currently buffered."""
        self.discard()

    # ------------------------------------------------------------------
    # Internal helpers (caller holds the lock)
    # ------------------------------------------------------------------

    def _open_locked(self, size: tuple[int, int], now: float) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._seg_counter += 1
        path = self.temp_dir / f"seg_{int(now * 1000)}_{self._seg_counter}.mp4"
        fourcc = cv2.VideoWriter_fourcc(*self.fourcc)
        writer = cv2.VideoWriter(str(path), fourcc, self.nominal_fps, size)
        if not writer.isOpened():
            writer.release()
            self._writer = None
            return
        self._writer = writer
        self._writer_path = path
        self._writer_start_ts = now
        self._writer_last_ts = now
        self._writer_frames = 0
        self._writer_size = size

    def _finalize_locked(self) -> None:
        """Close the current segment, recording it (or deleting it if empty)."""
        if self._writer is None:
            return
        self._writer.release()
        path = self._writer_path
        if self._writer_frames > 0 and path is not None and path.exists():
            try:
                nbytes = path.stat().st_size
            except OSError:
                nbytes = 0
            self._segments.append(
                _Segment(path, self._writer_start_ts, self._writer_last_ts,
                         self._writer_frames, nbytes)
            )
            self._finalized_bytes += nbytes
        elif path is not None and path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        self._writer = None
        self._writer_path = None
        self._writer_frames = 0
        self._writer_size = None

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._segments and self._segments[0].end_ts < cutoff:
            self._remove_oldest_locked()
        while len(self._segments) > 1 and self._finalized_bytes > self.max_bytes:
            self._remove_oldest_locked()

    def _remove_oldest_locked(self) -> None:
        seg = self._segments.popleft()
        self._finalized_bytes -= seg.nbytes
        try:
            seg.path.unlink()
        except OSError:
            pass

    def _purge_temp_dir(self) -> None:
        """Delete stale segment files left by a previous run or crash."""
        for p in self.temp_dir.glob("seg_*.mp4"):
            try:
                p.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Introspection (read-only)
    # ------------------------------------------------------------------

    @property
    def frame_count(self) -> int:
        with self._lock:
            return sum(s.frames for s in self._segments) + self._writer_frames

    @property
    def segment_count(self) -> int:
        with self._lock:
            return len(self._segments) + (1 if self._writer is not None else 0)

    @property
    def estimated_bytes(self) -> int:
        """Total retained segment bytes on disk (finalised + in-progress)."""
        with self._lock:
            current = 0
            if self._writer_path is not None:
                try:
                    current = self._writer_path.stat().st_size
                except OSError:
                    current = 0
            return self._finalized_bytes + current

    @property
    def duration_seconds(self) -> float:
        with self._lock:
            starts = [s.start_ts for s in self._segments]
            ends = [s.end_ts for s in self._segments]
            if self._writer is not None:
                starts.append(self._writer_start_ts)
                ends.append(self._writer_last_ts)
            if not starts:
                return 0.0
            return max(ends) - min(starts)

    @property
    def oldest_timestamp(self) -> Optional[float]:
        with self._lock:
            if self._segments:
                return self._segments[0].start_ts
            if self._writer is not None:
                return self._writer_start_ts
            return None

    @property
    def newest_timestamp(self) -> Optional[float]:
        with self._lock:
            if self._writer is not None:
                return self._writer_last_ts
            if self._segments:
                return self._segments[-1].end_ts
            return None
