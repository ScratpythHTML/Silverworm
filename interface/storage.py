"""
Safe file storage for screenshots, alert logs, metadata, and recordings.

All writes are atomic (write to temp → rename) so a crash mid-write cannot
corrupt an existing file. Directories are created on first access. File names
are timestamped and unique — no existing file is ever overwritten.

Usage
-----
    storage = StorageManager()           # or StorageManager(base_dir=Path(...))
    path = storage.save_screenshot(bgr_frame, prefix="error")
    storage.save_alert_entry({...})
    storage.shutdown()                   # call before process exit
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import numpy as np


class StorageManager:
    """
    Manages persistent storage for all Silverworm output files.

    Directory layout under ``base_dir``:
        screenshots/   – PNG frames captured on errors/manual/user request
        logs/          – JSONL alert logs (one file per day)
        metadata/      – JSON metadata blobs (pitch results, config snapshots)
        recordings/    – MP4 rolling-buffer saves
    """

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            if sys.platform == "darwin":
                base_dir = Path.home() / "Library" / "Application Support" / "Silverworm"
            else:
                # Linux (Pi) and everything else
                base_dir = Path.home() / ".local" / "share" / "Silverworm"
        self.base_dir = Path(base_dir)
        self.screenshots_dir = self.base_dir / "screenshots"
        self.logs_dir = self.base_dir / "logs"
        self.metadata_dir = self.base_dir / "metadata"
        self.recordings_dir = self.base_dir / "recordings"
        self.ensure_dirs()

    # ------------------------------------------------------------------
    # Directory management
    # ------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """Create all subdirectories if they don't exist."""
        for d in (
            self.screenshots_dir,
            self.logs_dir,
            self.metadata_dir,
            self.recordings_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path generation
    # ------------------------------------------------------------------

    def timestamped_path(self, directory: Path, prefix: str, ext: str) -> Path:
        """
        Return a unique path ``directory/prefix_YYYYMMDD_HHMMSS_mmm.ext``.

        If that path already exists (same millisecond), appends ``_1``,
        ``_2``, … until a free slot is found.
        """
        # Include microseconds, truncated to ms precision
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        ext = ext.lstrip(".")
        candidate = directory / f"{prefix}_{ts}.{ext}"
        if not candidate.exists():
            return candidate
        n = 1
        while True:
            candidate = directory / f"{prefix}_{ts}_{n}.{ext}"
            if not candidate.exists():
                return candidate
            n += 1

    # ------------------------------------------------------------------
    # Atomic write
    # ------------------------------------------------------------------

    def atomic_write(self, path: Path, content: Union[bytes, str]) -> None:
        """
        Write ``content`` to ``path`` atomically.

        Writes to a sibling temp file first, then os.replace() so a crash
        mid-write leaves the original file (if any) intact.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, mode) as fh:
                fh.write(content)
        except Exception:
            os.unlink(tmp_name)
            raise
        os.replace(tmp_name, path)

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------

    def save_screenshot(
        self,
        frame: np.ndarray,
        prefix: str = "screenshot",
    ) -> Optional[Path]:
        """
        Save a BGR numpy frame as PNG.

        Returns the saved path, or None if cv2 is unavailable or write fails.
        """
        try:
            import cv2
        except ImportError:
            return None

        try:
            path = self.timestamped_path(self.screenshots_dir, prefix, "png")
            cv2.imwrite(str(path), frame)
            return path if path.exists() else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Alert log (JSONL, one file per day)
    # ------------------------------------------------------------------

    def _alert_log_path(self) -> Path:
        today = datetime.now().strftime("%Y%m%d")
        return self.logs_dir / f"alerts_{today}.jsonl"

    def save_alert_entry(self, entry: dict) -> None:
        """
        Append a JSON-lines record to today's alert log atomically.

        Existing records are preserved: the entire file is re-written as
        old_content + new_line via atomic_write.
        """
        log_path = self._alert_log_path()
        line = json.dumps(entry, default=str) + "\n"
        existing = b""
        if log_path.exists():
            existing = log_path.read_bytes()
        self.atomic_write(log_path, existing + line.encode())

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def save_metadata(self, data: dict, prefix: str = "metadata") -> Path:
        """Save a JSON metadata blob with a timestamped name."""
        path = self.timestamped_path(self.metadata_dir, prefix, "json")
        self.atomic_write(path, json.dumps(data, indent=2, default=str))
        return path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """No-op — writes are already atomic. Reserved for future buffering."""

    def shutdown(self) -> None:
        """Call before process exit to flush any pending state."""
        self.flush()
