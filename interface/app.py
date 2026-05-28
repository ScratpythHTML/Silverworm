#!/usr/bin/env python3
"""
Silverworm Control System — launcher.

Shows the startup configuration dialog, then opens the main window.
All UI/state/hardware wiring lives in ui/main_window.py and the modules
it composes; this file stays small on purpose.
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from config import load_config, save_config
from ui.startup_dialog import StartupConfigDialog
from ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Silverworm")
    app.setOrganizationName("Silverworm")

    # Pre-populate startup dialog from saved config (if the user opted in).
    saved = load_config()
    initial = saved if (saved and saved.remember_settings) else None

    dialog = StartupConfigDialog(initial=initial)
    if dialog.exec() != StartupConfigDialog.DialogCode.Accepted:
        sys.exit(0)

    config = dialog.config()
    if config.remember_settings:
        save_config(config)

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
