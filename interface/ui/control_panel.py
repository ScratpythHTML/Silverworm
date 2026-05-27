"""Start/Stop/Snapshot/Recalibrate + Manual-mode toggle panel."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QVBoxLayout, QGridLayout, QLabel, QPushButton

from ui.theme import Theme
from ui.widgets import GlowingCard, AnimatedButton


class ControlPanel(GlowingCard):
    """Control buttons panel with Manual Mode toggle."""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    snapshot_clicked = pyqtSignal()
    recalibrate_clicked = pyqtSignal()
    manual_mode_toggled = pyqtSignal(bool)  # True = manual ON

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        header = QLabel("Controls")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        layout.addWidget(header)

        grid = QGridLayout()
        grid.setSpacing(12)

        self.start_btn = AnimatedButton("START", Theme.SUCCESS, Theme.SUCCESS_GLOW)
        self.start_btn.clicked.connect(self.start_clicked.emit)

        self.stop_btn = AnimatedButton("STOP", Theme.ERROR, Theme.ERROR_GLOW)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)

        self.snapshot_btn = AnimatedButton("SNAPSHOT", Theme.INFO, Theme.INFO_GLOW)
        self.snapshot_btn.clicked.connect(self.snapshot_clicked.emit)

        self.recalibrate_btn = AnimatedButton("RECALIBRATE", Theme.WARNING, Theme.WARNING_GLOW)
        self.recalibrate_btn.clicked.connect(self.recalibrate_clicked.emit)

        grid.addWidget(self.start_btn, 0, 0)
        grid.addWidget(self.stop_btn, 0, 1)
        grid.addWidget(self.snapshot_btn, 1, 0)
        grid.addWidget(self.recalibrate_btn, 1, 1)
        layout.addLayout(grid)

        self._manual_mode_on = False
        self.manual_btn = QPushButton("MANUAL MODE: OFF")
        self.manual_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.manual_btn.setMinimumHeight(44)
        self.manual_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manual_btn.setCheckable(True)
        self._apply_manual_btn_style(False)
        self.manual_btn.clicked.connect(self._on_manual_toggled)
        layout.addWidget(self.manual_btn)

    def _on_manual_toggled(self):
        checked = self.manual_btn.isChecked()
        self.set_manual_mode(checked)
        self.manual_mode_toggled.emit(checked)

    def set_manual_mode(self, on: bool):
        """Update button appearance to reflect manual mode state."""
        self._manual_mode_on = on
        self.manual_btn.setChecked(on)
        self.manual_btn.setText(f"MANUAL MODE: {'ON' if on else 'OFF'}")
        self._apply_manual_btn_style(on)

    def _apply_manual_btn_style(self, on: bool):
        if on:
            self.manual_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.WARNING};
                    color: #000000;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {Theme.WARNING_GLOW};
                }}
            """)
        else:
            self.manual_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {Theme.BG_ELEVATED};
                    color: {Theme.TEXT_SECONDARY};
                    border: 1px solid {Theme.BORDER};
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {Theme.BG_HOVER};
                    border-color: {Theme.BORDER_LIGHT};
                }}
            """)

    def set_running(self, running: bool):
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
