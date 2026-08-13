"""
Unit tests for the disk-backed RollingBuffer.

RollingBuffer spools the camera feed to short MP4 segments on flash (not
RAM). These tests use tiny frames, short windows, and a monkeypatched clock
so they run quickly and deterministically. They require cv2 for the encode
path; tests that don't touch encoding run without it.
"""

import time

import numpy as np
import pytest

from camera.rolling_buffer import RollingBuffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(val: int = 128, h: int = 64, w: int = 64) -> np.ndarray:
    """Return a small solid-colour BGR frame (16-divisible dims for the codec)."""
    return np.full((h, w, 3), val, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Empty / no-cv2 behaviour
# ---------------------------------------------------------------------------

class TestEmpty:

    def test_empty_initially(self, tmp_path):
        buf = RollingBuffer(temp_dir=tmp_path)
        assert buf.frame_count == 0
        assert buf.segment_count == 0
        assert buf.estimated_bytes == 0
        assert buf.duration_seconds == 0.0

    def test_timestamps_none_when_empty(self, tmp_path):
        buf = RollingBuffer(temp_dir=tmp_path)
        assert buf.oldest_timestamp is None
        assert buf.newest_timestamp is None

    def test_save_returns_false_when_empty(self, tmp_path):
        buf = RollingBuffer(temp_dir=tmp_path)
        assert buf.save(tmp_path / "empty.mp4") is False

    def test_purges_stale_temp_on_init(self, tmp_path):
        """Segments left behind by a previous run/crash are deleted on init."""
        stale = tmp_path / "seg_123_1.mp4"
        stale.write_bytes(b"junk")
        RollingBuffer(temp_dir=tmp_path)
        assert not stale.exists()


# ---------------------------------------------------------------------------
# Recording to disk
# ---------------------------------------------------------------------------

class TestRecording:

    def test_add_frame_writes_segment(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(temp_dir=tmp_path, sample_fps=0, segment_seconds=100)
        buf.add_frame(_make_frame())
        assert buf.frame_count == 1
        assert buf.segment_count == 1

    def test_multiple_frames_one_segment(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(temp_dir=tmp_path, sample_fps=0, segment_seconds=100)
        for _ in range(5):
            buf.add_frame(_make_frame())
        assert buf.frame_count == 5
        assert buf.segment_count == 1

    def test_rotation_creates_segments(self, tmp_path, monkeypatch):
        pytest.importorskip("cv2")
        t = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: t[0])
        buf = RollingBuffer(
            temp_dir=tmp_path, sample_fps=0, segment_seconds=10, window_seconds=1000
        )
        buf.add_frame(_make_frame())   # t=0  → seg1
        t[0] = 5
        buf.add_frame(_make_frame())   # t=5  → still seg1
        t[0] = 12
        buf.add_frame(_make_frame())   # t=12 → rotate, seg2 opens
        assert buf.segment_count == 2  # 1 finalised + 1 open
        assert buf.frame_count == 3

    def test_estimated_bytes_tracks_disk(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(temp_dir=tmp_path, sample_fps=0, segment_seconds=100)
        for _ in range(10):
            buf.add_frame(_make_frame())
        assert buf.estimated_bytes > 0


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

class TestSampling:

    def test_sampling_drops_frames_faster_than_sample_fps(self, tmp_path, monkeypatch):
        pytest.importorskip("cv2")
        t = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: t[0])
        buf = RollingBuffer(temp_dir=tmp_path, sample_fps=5.0, segment_seconds=100)

        buf.add_frame(_make_frame())   # t=0.00 → stored
        t[0] = 0.05
        buf.add_frame(_make_frame())   # +0.05s → dropped
        t[0] = 0.10
        buf.add_frame(_make_frame())   # +0.10s → dropped
        t[0] = 0.30
        buf.add_frame(_make_frame())   # +0.30s → stored

        assert buf.frame_count == 2

    def test_sampling_disabled_stores_every_frame(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(temp_dir=tmp_path, sample_fps=0, segment_seconds=100)
        for _ in range(8):
            buf.add_frame(_make_frame())
        assert buf.frame_count == 8


# ---------------------------------------------------------------------------
# Bounded eviction (time + bytes)
# ---------------------------------------------------------------------------

class TestEviction:

    def test_evicts_segments_older_than_window(self, tmp_path, monkeypatch):
        pytest.importorskip("cv2")
        t = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: t[0])
        buf = RollingBuffer(
            temp_dir=tmp_path, sample_fps=0, segment_seconds=5, window_seconds=10
        )
        buf.add_frame(_make_frame())   # t=0  seg1
        t[0] = 6
        buf.add_frame(_make_frame())   # t=6  rotate → seg2
        t[0] = 20
        buf.add_frame(_make_frame())   # t=20 rotate → seg3; seg1+seg2 now > 10s old
        assert buf.segment_count == 1  # only the open seg3 remains
        assert len(list(tmp_path.glob("seg_*.mp4"))) == 1  # old files deleted

    def test_evicts_by_byte_cap(self, tmp_path, monkeypatch):
        """With a tiny max_bytes, only the newest finalised segment is kept."""
        pytest.importorskip("cv2")
        t = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: t[0])
        buf = RollingBuffer(
            temp_dir=tmp_path, sample_fps=0, segment_seconds=5,
            window_seconds=100000, max_bytes=1,
        )
        for i in range(4):
            t[0] = i * 10           # force a rotation on each add
            buf.add_frame(_make_frame())
        # max_bytes=1 keeps at most one finalised segment (+ the open one).
        assert buf.segment_count == 2
        assert len(list(tmp_path.glob("seg_*.mp4"))) == 2


# ---------------------------------------------------------------------------
# Save (persist on error) + discard (routine cleanup)
# ---------------------------------------------------------------------------

class TestSaveDiscard:

    def test_save_creates_file(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(temp_dir=tmp_path / "tmp", sample_fps=0, segment_seconds=100)
        for _ in range(10):
            buf.add_frame(_make_frame())
        out = tmp_path / "out" / "rec.mp4"
        assert buf.save(out) is True
        assert out.exists()
        assert out.stat().st_size > 0

    def test_save_leaves_no_temp_artifact(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(temp_dir=tmp_path / "tmp", sample_fps=0, segment_seconds=100)
        for _ in range(5):
            buf.add_frame(_make_frame())
        out = tmp_path / "rec.mp4"
        buf.save(out)
        assert list(tmp_path.glob("*.tmp.mp4")) == []

    def test_discard_deletes_temp_files(self, tmp_path):
        pytest.importorskip("cv2")
        tmp = tmp_path / "tmp"
        buf = RollingBuffer(temp_dir=tmp, sample_fps=0, segment_seconds=100)
        for _ in range(3):
            buf.add_frame(_make_frame())
        assert len(list(tmp.glob("seg_*.mp4"))) >= 1

        buf.discard()
        assert buf.frame_count == 0
        assert buf.segment_count == 0
        assert list(tmp.glob("seg_*.mp4")) == []

    def test_clear_is_discard(self, tmp_path):
        pytest.importorskip("cv2")
        buf = RollingBuffer(temp_dir=tmp_path, sample_fps=0, segment_seconds=100)
        for _ in range(3):
            buf.add_frame(_make_frame())
        buf.clear()
        assert buf.frame_count == 0


# ---------------------------------------------------------------------------
# Timestamp / duration introspection
# ---------------------------------------------------------------------------

class TestTimestamps:

    def test_duration_reflects_span(self, tmp_path, monkeypatch):
        pytest.importorskip("cv2")
        t = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: t[0])
        buf = RollingBuffer(
            temp_dir=tmp_path, sample_fps=0, segment_seconds=2, window_seconds=1000
        )
        buf.add_frame(_make_frame())   # t=0
        t[0] = 3
        buf.add_frame(_make_frame())   # rotate → seg2
        t[0] = 5
        buf.add_frame(_make_frame())   # rotate → seg3
        assert buf.duration_seconds == pytest.approx(5.0)
        assert buf.oldest_timestamp == pytest.approx(0.0)
        assert buf.newest_timestamp == pytest.approx(5.0)
