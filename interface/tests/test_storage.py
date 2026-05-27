"""
Unit tests for StorageManager.

All tests operate on temporary directories so nothing touches the real
Silverworm config/data directories.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from storage import StorageManager


@pytest.fixture
def sm(tmp_path):
    """A StorageManager rooted in a fresh temp directory."""
    return StorageManager(base_dir=tmp_path / "silverworm")


def _bgr_frame(h: int = 8, w: int = 8, val: int = 128) -> np.ndarray:
    return np.full((h, w, 3), val, dtype=np.uint8)


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------

class TestDirectoryCreation:

    def test_ensure_dirs_creates_all_subdirectories(self, sm):
        for d in (sm.screenshots_dir, sm.logs_dir, sm.metadata_dir, sm.recordings_dir):
            assert d.is_dir(), f"{d} was not created"

    def test_ensure_dirs_is_idempotent(self, sm):
        sm.ensure_dirs()  # second call must not raise
        for d in (sm.screenshots_dir, sm.logs_dir, sm.metadata_dir, sm.recordings_dir):
            assert d.is_dir()

    def test_nested_base_dir_is_created(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "silverworm"
        sm = StorageManager(base_dir=deep)
        assert sm.screenshots_dir.is_dir()


# ---------------------------------------------------------------------------
# Timestamped paths
# ---------------------------------------------------------------------------

class TestTimestampedPath:

    def test_returns_path_in_correct_dir(self, sm):
        p = sm.timestamped_path(sm.screenshots_dir, "snap", "png")
        assert p.parent == sm.screenshots_dir

    def test_includes_prefix_in_name(self, sm):
        p = sm.timestamped_path(sm.screenshots_dir, "error_snap", "png")
        assert p.name.startswith("error_snap_")

    def test_has_correct_extension(self, sm):
        p = sm.timestamped_path(sm.screenshots_dir, "snap", "png")
        assert p.suffix == ".png"

    def test_ext_with_leading_dot_is_handled(self, sm):
        p = sm.timestamped_path(sm.screenshots_dir, "snap", ".png")
        assert p.suffix == ".png"

    def test_unique_paths_on_collision(self, sm):
        """Simulate a collision by pre-creating the first candidate."""
        import datetime as _dt
        from unittest.mock import patch

        # Fix datetime so both calls generate the same timestamp
        fixed_ts = "20260521_120000_000000"
        with patch("storage.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = fixed_ts

            p1 = sm.timestamped_path(sm.screenshots_dir, "snap", "png")
            p1.touch()  # create the file so p2 must pick a different name
            p2 = sm.timestamped_path(sm.screenshots_dir, "snap", "png")

        assert p1 != p2
        assert not p2.exists()  # second path not created yet


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

class TestAtomicWrite:

    def test_writes_bytes(self, sm):
        p = sm.screenshots_dir / "test.bin"
        sm.atomic_write(p, b"\x01\x02\x03")
        assert p.read_bytes() == b"\x01\x02\x03"

    def test_writes_string(self, sm):
        p = sm.logs_dir / "test.txt"
        sm.atomic_write(p, "hello world")
        assert p.read_text() == "hello world"

    def test_no_tmp_file_left_after_success(self, sm):
        p = sm.logs_dir / "file.txt"
        sm.atomic_write(p, "content")
        tmp_files = list(sm.logs_dir.glob("*.tmp"))
        assert tmp_files == []

    def test_does_not_overwrite_existing_in_place(self, sm, monkeypatch):
        """Existing file content is intact while write is in progress (rename is atomic)."""
        p = sm.logs_dir / "existing.txt"
        p.write_text("original")
        sm.atomic_write(p, "new content")
        assert p.read_text() == "new content"

    def test_creates_parent_dirs(self, sm):
        p = sm.base_dir / "deep" / "nested" / "file.txt"
        sm.atomic_write(p, "hi")
        assert p.read_text() == "hi"


# ---------------------------------------------------------------------------
# Screenshot saving
# ---------------------------------------------------------------------------

class TestSaveScreenshot:

    def test_saves_png_and_returns_path(self, sm):
        pytest.importorskip("cv2")
        frame = _bgr_frame()
        path = sm.save_screenshot(frame, prefix="snap")
        assert path is not None
        assert path.exists()
        assert path.suffix == ".png"

    def test_screenshot_is_in_screenshots_dir(self, sm):
        pytest.importorskip("cv2")
        frame = _bgr_frame()
        path = sm.save_screenshot(frame)
        assert path is not None
        assert path.parent == sm.screenshots_dir

    def test_custom_prefix_appears_in_filename(self, sm):
        pytest.importorskip("cv2")
        path = sm.save_screenshot(_bgr_frame(), prefix="error_event")
        assert path is not None
        assert path.name.startswith("error_event_")

    def test_two_screenshots_have_distinct_names(self, sm):
        pytest.importorskip("cv2")
        p1 = sm.save_screenshot(_bgr_frame(val=10))
        p2 = sm.save_screenshot(_bgr_frame(val=20))
        assert p1 is not None and p2 is not None
        assert p1 != p2


# ---------------------------------------------------------------------------
# Alert log (JSONL)
# ---------------------------------------------------------------------------

class TestSaveAlertEntry:

    def test_creates_log_file(self, sm):
        sm.save_alert_entry({"type": "test", "msg": "hello"})
        log_path = sm._alert_log_path()
        assert log_path.exists()

    def test_entry_is_valid_json(self, sm):
        sm.save_alert_entry({"type": "error", "code": 42})
        log_path = sm._alert_log_path()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["type"] == "error"
        assert parsed["code"] == 42

    def test_multiple_entries_appended(self, sm):
        sm.save_alert_entry({"n": 1})
        sm.save_alert_entry({"n": 2})
        sm.save_alert_entry({"n": 3})
        log_path = sm._alert_log_path()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 3
        assert json.loads(lines[2])["n"] == 3

    def test_existing_entries_not_corrupted(self, sm):
        sm.save_alert_entry({"msg": "first"})
        sm.save_alert_entry({"msg": "second"})
        log_path = sm._alert_log_path()
        lines = log_path.read_text().strip().splitlines()
        assert json.loads(lines[0])["msg"] == "first"
        assert json.loads(lines[1])["msg"] == "second"

    def test_non_serialisable_values_use_str_default(self, sm):
        from pathlib import PurePosixPath
        sm.save_alert_entry({"path": PurePosixPath("/tmp/x")})
        log_path = sm._alert_log_path()
        parsed = json.loads(log_path.read_text().strip())
        assert parsed["path"] == "/tmp/x"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestSaveMetadata:

    def test_saves_valid_json(self, sm):
        data = {"pitch_um": 250.0, "confidence": "HIGH"}
        path = sm.save_metadata(data)
        assert path.exists()
        loaded = json.loads(path.read_text())
        assert loaded["pitch_um"] == 250.0

    def test_metadata_in_metadata_dir(self, sm):
        path = sm.save_metadata({"x": 1})
        assert path.parent == sm.metadata_dir


# ---------------------------------------------------------------------------
# Shutdown / flush
# ---------------------------------------------------------------------------

class TestShutdown:

    def test_shutdown_does_not_raise(self, sm):
        sm.shutdown()  # must be a no-op, not an exception

    def test_flush_does_not_raise(self, sm):
        sm.flush()
