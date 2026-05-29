#!/usr/bin/env python3
"""
Silverworm root launcher.

Checks that dependencies are installed (installs them system-wide if not),
then starts the app.  Works identically on a dev machine and the CM5 —
no virtual environment needed.

Usage:  python app.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQS = ROOT / "interface" / "requirements.txt"


def _deps_ok() -> bool:
    try:
        import PyQt6   # noqa: F401
        import cv2     # noqa: F401
        import numpy   # noqa: F401
        return True
    except ImportError:
        return False


def _install_deps() -> None:
    print("Silverworm: installing dependencies (first run)…")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQS), "--quiet"],
        capture_output=True,
    )
    if result.returncode != 0:
        # Modern Debian/Ubuntu needs this flag for system-wide installs.
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(REQS),
             "--break-system-packages", "--quiet"]
        )
    print("Silverworm: dependencies ready.")


if __name__ == "__main__":
    if not _deps_ok():
        _install_deps()
        # Re-exec so newly installed packages are visible on sys.path.
        os.execv(sys.executable, [sys.executable] + sys.argv)

    sys.path.insert(0, str(ROOT / "interface"))
    from app import main  # interface/app.py
    main()
