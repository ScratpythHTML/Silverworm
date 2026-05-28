"""Scrollable timestamped alert log widget."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QScrollArea, QWidget

from ui.theme import Theme
from ui.widgets import GlowingCard


_LEVEL_COLOR = {
    "info": Theme.TEXT_SECONDARY,
    "success": Theme.SUCCESS,
    "warning": Theme.WARNING,
    "error": Theme.ERROR,
}

_LEVEL_ICON = {
    "info": "ℹ",
    "success": "✓",
    "warning": "⚠",
    "error": "✕",
}


class AlertLog(GlowingCard):
    """System alert log with styled, timestamped entries."""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        header = QLabel("System Log")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Theme.BG_SECONDARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 6px;
            }}
            QScrollBar:vertical {{
                background-color: {Theme.BG_SECONDARY};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {Theme.BORDER_LIGHT};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {Theme.ACCENT_PRIMARY};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        self.container = QWidget()
        self.log_layout = QVBoxLayout(self.container)
        self.log_layout.setContentsMargins(8, 8, 8, 8)
        self.log_layout.setSpacing(2)
        self.log_layout.addStretch()

        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)

    def log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = _LEVEL_COLOR.get(level, Theme.TEXT_SECONDARY)
        icon = _LEVEL_ICON.get(level, "•")

        entry = QLabel(f"{icon} [{timestamp}] {message}")
        entry.setFont(QFont("Consolas", 10))
        entry.setWordWrap(True)
        entry.setStyleSheet(f"color: {color}; padding: 3px;")
        self.log_layout.insertWidget(self.log_layout.count() - 1, entry)

        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()
        ))
