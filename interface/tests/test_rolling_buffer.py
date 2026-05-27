"""
Unit tests for RollingBuffer.

The window is set to 10 seconds so the test suite finishes quickly.
Production uses 300 seconds (5 minutes) — the logic is identical.
"""

import time
from pathlib import Path

import numpy as np
import pytest

from camera.rolling_buffer import RollingBuffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(val: int = 128, h: int = 4, w: int = 4) -> np.ndarray:
    """Return a tiny solid-colour BGR frame."""
    return np.full((h, w, 3), val, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Basic add / eviction
# ---------------------------------------------------------------------------

class TestBasicAddEviction:

    def test_empty_initially(self):
        buf = RollingBuffer(window_seconds=10.0)
        assert buf.frame_count == 0

    def test_add_single_frame(self):
        buf = RollingBuffer(window_seconds=10.0)
        buf.add_frame(_make_frame())
        assert buf.frame_count == 1

    def test_add_multiple_frames_within_window(self):
        buf = RollingBuffer(window_seconds=10.0)
        for _ in range(5):
            buf.add_frame(_make_frame())
        assert buf.frame_count == 5

    def test_frames_older_than_window_are_evicted(self, monkeypatch):
        """Frames added before the window cutoff should be dropped."""
        buf = RollingBuffer(window_seconds=10.0)

        # Simulate: first frame at t=0
        fake_time = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

        buf.add_frame(_make_frame(10))

        # Advance 11 seconds and add a new frame — old one should be evicted
        fake_time[0] = 11.0
        buf.add_frame(_make_frame(20))

        assert buf.frame_count == 1

    def test_frames_within_window_are_kept(self, monkeypatch):
        buf = RollingBuffer(window_seconds=10.0)
        fake_time = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

        for i in range(5):
            fake_time[0] = float(i)       # t=0,1,2,3,4 — all within 10s of t=9
            buf.add_frame(_make_frame(i))

        fake_time[0] = 9.0
        buf.add_frame(_make_frame(99))    # t=9 — triggers eviction check
        # Frames at t=0..4 are within 9 - 10 = -1 cutoff, so all kept
        assert buf.frame_count == 6

    def test_clear_empties_buffer(self):
        buf = RollingBuffer(window_seconds=10.0)
        for _ in range(3):
            buf.add_frame(_make_frame())
        buf.clear()
        assert buf.frame_count == 0

    def test_frames_are_copied_not_referenced(self):
        """add_frame must copy the frame so mutations to the source don't corrupt the buffer."""
        buf = RollingBuffer(window_seconds=10.0)
        frame = _make_frame(0)
        buf.add_frame(frame)
        frame[:] = 255  # mutate original
        with buf._lock:
            stored = buf._frames[0].frame
        assert stored[0, 0, 0] == 0   # buffer still has the original value


# ---------------------------------------------------------------------------
# Duration / timestamp properties
# ---------------------------------------------------------------------------

class TestTimestampProperties:

    def test_duration_zero_with_one_frame(self):
        buf = RollingBuffer(window_seconds=10.0)
        buf.add_frame(_make_frame())
        assert buf.duration_seconds == 0.0

    def test_duration_reflects_actual_span(self, monkeypatch):
        buf = RollingBuffer(window_seconds=60.0)
        fake_time = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

        buf.add_frame(_make_frame())   # t=0
        fake_time[0] = 5.0
        buf.add_frame(_make_frame())   # t=5
        fake_time[0] = 9.0
        buf.add_frame(_make_frame())   # t=9

        assert buf.duration_seconds == pytest.approx(9.0)

    def test_oldest_and_newest_timestamps(self, monkeypatch):
        buf = RollingBuffer(window_seconds=60.0)
        fake_time = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

        buf.add_frame(_make_frame())   # t=0
        fake_time[0] = 3.0
        buf.add_frame(_make_frame())   # t=3

        assert buf.oldest_timestamp == pytest.approx(0.0)
        assert buf.newest_timestamp == pytest.approx(3.0)

    def test_none_timestamps_when_empty(self):
        buf = RollingBuffer(window_seconds=10.0)
        assert buf.oldest_timestamp is None
        assert buf.newest_timestamp is None


# ---------------------------------------------------------------------------
# Save to MP4
# ---------------------------------------------------------------------------

class TestSave:

    def test_save_returns_false_when_empty(self, tmp_path):
        buf = RollingBuffer(window_seconds=10.0)
        ok = buf.save(tmp_path / "empty.mp4")
        assert ok is False

    def test_save_creates_file(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(window_seconds=10.0, nominal_fps=5.0)
        for _ in range(10):
            buf.add_frame(_make_frame())
        out = tmp_path / "test_recording.mp4"
        ok = buf.save(out)
        assert ok is True
        assert out.exists()
        assert out.stat().st_size > 0

    def test_save_creates_parent_dirs(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(window_seconds=10.0, nominal_fps=5.0)
        buf.add_frame(_make_frame())
        out = tmp_path / "a" / "b" / "c" / "rec.mp4"
        ok = buf.save(out)
        assert ok is True
        assert out.exists()

    def test_save_does_not_leave_temp_file_on_success(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(window_seconds=10.0, nominal_fps=5.0)
        buf.add_frame(_make_frame())
        out = tmp_path / "rec.mp4"
        buf.save(out)
        tmp_files = list(tmp_path.glob("*.tmp.mp4"))
        assert tmp_files == []

    def test_save_10s_rolling_window(self, tmp_path, monkeypatch):
        """Integration: simulate 10 seconds of frames and save the buffer."""
        pytest.importorskip("cv2")
        buf = RollingBuffer(window_seconds=10.0, nominal_fps=10.0)
        fake_time = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

        # Add 100 frames spread over 10 seconds at 10 fps
        for i in range(100):
            fake_time[0] = i * 0.1   # 0.0 → 9.9
            buf.add_frame(_make_frame(i % 256))

        assert buf.frame_count == 100

        out = tmp_path / "window_10s.mp4"
        ok = buf.save(out)
        assert ok is True
        assert out.exists()

    def test_save_evicts_old_frames_before_saving(self, tmp_path, monkeypatch):
        """Frames outside the 10s window must NOT appear in the saved file."""
        pytest.importorskip("cv2")
        buf = RollingBuffer(window_seconds=10.0, nominal_fps=10.0)
        fake_time = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: fake_time[0])

        # 5 frames in the first second (will be evicted)
        for i in range(5):
            buf.add_frame(_make_frame(10))

        # Jump to t=15 and add 5 new frames
        fake_time[0] = 15.0
        for i in range(5):
            buf.add_frame(_make_frame(200))

        # Only the 5 recent frames should remain
        assert buf.frame_count == 5

        out = tmp_path / "evicted.mp4"
        ok = buf.save(out)
        assert ok is True
