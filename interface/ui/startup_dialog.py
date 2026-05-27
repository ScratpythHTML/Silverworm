"""
Startup configuration dialog.

Modal dialog shown before the main window. Captures three target parameters
(pitch, wire thickness, tube diameter), shows a live-calculated wrap angle,
and offers a "remember for next session" option.

Reused for in-session edits via Settings menu (later).
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QFrame, QToolButton,
)

from config import AppConfig, calculate_wrap_angle_deg


# Theme colors duplicated here to keep dialog standalone (importing from app.py
# would create a circular import since app.py also imports this dialog).
class _Theme:
    BG_PRIMARY = "#0a0e14"
    BG_CARD = "#151b23"
    BG_ELEVATED = "#1a222d"
    ACCENT_PRIMARY = "#00d4aa"
    TEXT_PRIMARY = "#e6e6e6"
    TEXT_SECONDARY = "#8b949e"
    TEXT_MUTED = "#5c6470"
    BORDER = "#2d3748"
    BORDER_FOCUS = "#00d4aa"
    ERROR = "#ff6b6b"


_PITCH_INFO_TEXT = (
    "Target Pitch is the desired axial spacing between yarn wraps.\n\n"
    "You can change this later at any time via:\n"
    "Settings → Target Parameters"
)


class StartupConfigDialog(QDialog):
    """
    Modal startup dialog. After exec(), if result() == Accepted, use config()
    to retrieve the populated AppConfig. The detent_config and
    manual_mode_gui_enabled fields are carried through unchanged from
    `initial` so existing user preferences survive a startup re-prompt.
    """

    def __init__(self, initial: Optional[AppConfig] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Silverworm — Configuration")
        self.setModal(True)
        self.setMinimumWidth(480)

        # Seed with existing config if provided so the dialog is pre-populated
        # for returning users who previously checked "Remember settings".
        self._initial = initial or AppConfig()
        self._hw_platform: str = self._initial.hw_platform

        self._build_ui()
        self._wire_validation()
        self._update_angle_preview()

    # ----- public --------------------------------------------------------

    def config(self) -> AppConfig:
        """Return the AppConfig assembled from current field values."""
        return AppConfig(
            target_pitch_um=float(self.pitch_input.text()),
            wire_thickness_um=float(self.thickness_input.text()),
            tube_diameter_mm=float(self.diameter_input.text()),
            detent_config=self._initial.detent_config,
            manual_mode_gui_enabled=self._initial.manual_mode_gui_enabled,
            remember_settings=self.remember_checkbox.isChecked(),
            hw_platform=self._hw_platform,
            scale_um_per_px=self._initial.scale_um_per_px,
        )

    # ----- ui construction ----------------------------------------------

    def _build_ui(self):
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {_Theme.BG_PRIMARY};
            }}
            QLabel {{
                color: {_Theme.TEXT_PRIMARY};
                font-family: 'Segoe UI', 'SF Pro Display', sans-serif;
            }}
            QLineEdit {{
                background-color: {_Theme.BG_ELEVATED};
                color: {_Theme.TEXT_PRIMARY};
                border: 1px solid {_Theme.BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 13px;
                font-family: 'Consolas', 'Menlo', monospace;
            }}
            QLineEdit:focus {{
                border: 1px solid {_Theme.BORDER_FOCUS};
            }}
            QLineEdit[invalid="true"] {{
                border: 1px solid {_Theme.ERROR};
            }}
            QPushButton {{
                background-color: {_Theme.BG_ELEVATED};
                color: {_Theme.TEXT_PRIMARY};
                border: 1px solid {_Theme.BORDER};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                border: 1px solid {_Theme.BORDER_FOCUS};
            }}
            QPushButton:disabled {{
                color: {_Theme.TEXT_MUTED};
            }}
            QPushButton#primary {{
                background-color: {_Theme.ACCENT_PRIMARY};
                color: {_Theme.BG_PRIMARY};
                border: none;
            }}
            QPushButton#primary:disabled {{
                background-color: {_Theme.BORDER};
                color: {_Theme.TEXT_MUTED};
            }}
            QCheckBox {{
                color: {_Theme.TEXT_SECONDARY};
                spacing: 8px;
            }}
            QToolButton {{
                background: transparent;
                color: {_Theme.ACCENT_PRIMARY};
                border: none;
                font-weight: bold;
                font-size: 14px;
            }}
            QToolButton:hover {{
                color: {_Theme.TEXT_PRIMARY};
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 22)
        outer.setSpacing(16)

        # Title
        title = QLabel("Configure Wrapping Parameters")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {_Theme.ACCENT_PRIMARY};")
        outer.addWidget(title)

        subtitle = QLabel(
            "These values define the target geometry of the wrap. "
            "All fields are required."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {_Theme.TEXT_SECONDARY}; font-size: 12px;")
        outer.addWidget(subtitle)

        # Input grid
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        # Row 0: Target Pitch with info icon
        pitch_label = QLabel("Target Pitch")
        pitch_info = QToolButton()
        pitch_info.setText("ⓘ")
        pitch_info.setToolTip(_PITCH_INFO_TEXT)
        pitch_info.setCursor(Qt.CursorShape.WhatsThisCursor)
        pitch_label_row = QHBoxLayout()
        pitch_label_row.setContentsMargins(0, 0, 0, 0)
        pitch_label_row.setSpacing(4)
        pitch_label_row.addWidget(pitch_label)
        pitch_label_row.addWidget(pitch_info)
        pitch_label_row.addStretch()
        pitch_label_wrap = QWidgetContainer(pitch_label_row)

        self.pitch_input = QLineEdit(f"{self._initial.target_pitch_um:g}")
        self.pitch_input.setValidator(QDoubleValidator(0.0001, 1e9, 4))
        pitch_unit = QLabel("μm")
        pitch_unit.setStyleSheet(f"color: {_Theme.TEXT_MUTED};")

        grid.addWidget(pitch_label_wrap, 0, 0)
        grid.addWidget(self.pitch_input, 0, 1)
        grid.addWidget(pitch_unit, 0, 2)

        # Row 1: Wire Thickness
        grid.addWidget(QLabel("Wire Thickness"), 1, 0)
        self.thickness_input = QLineEdit(f"{self._initial.wire_thickness_um:g}")
        self.thickness_input.setValidator(QDoubleValidator(0.0001, 1e9, 4))
        thickness_unit = QLabel("μm")
        thickness_unit.setStyleSheet(f"color: {_Theme.TEXT_MUTED};")
        grid.addWidget(self.thickness_input, 1, 1)
        grid.addWidget(thickness_unit, 1, 2)

        # Row 2: Tube Diameter
        grid.addWidget(QLabel("Tube Diameter"), 2, 0)
        self.diameter_input = QLineEdit(f"{self._initial.tube_diameter_mm:g}")
        self.diameter_input.setValidator(QDoubleValidator(0.0001, 1e9, 4))
        diameter_unit = QLabel("mm")
        diameter_unit.setStyleSheet(f"color: {_Theme.TEXT_MUTED};")
        grid.addWidget(self.diameter_input, 2, 1)
        grid.addWidget(diameter_unit, 2, 2)

        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        # Hardware platform selector
        platform_card = QFrame()
        platform_card.setStyleSheet(
            f"background-color: {_Theme.BG_CARD};"
            f"border: 1px solid {_Theme.BORDER};"
            f"border-radius: 8px;"
        )
        platform_outer = QVBoxLayout(platform_card)
        platform_outer.setContentsMargins(14, 10, 14, 10)
        platform_outer.setSpacing(8)

        platform_title = QLabel("Hardware Platform")
        platform_title.setStyleSheet(f"color: {_Theme.TEXT_SECONDARY}; font-size: 11px;")
        platform_outer.addWidget(platform_title)

        platform_row = QHBoxLayout()
        platform_row.setSpacing(8)
        self._platform_btns: dict = {}
        for key, label, tip in [
            ("mock",  "Mock (Dev)",  "Software-only — no hardware required"),
            ("rpi5",  "RPi 5",       "Raspberry Pi 5 test rig (I2C bus 1)"),
            ("cm5",   "CM5",         "CM5 production board (I2C bus 1 — confirm overlay)"),
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setToolTip(tip)
            btn.setChecked(key == self._hw_platform)
            btn.setStyleSheet(self._platform_btn_style(key == self._hw_platform))
            btn.clicked.connect(lambda _, k=key: self._on_platform_selected(k))
            self._platform_btns[key] = btn
            platform_row.addWidget(btn)
        platform_outer.addLayout(platform_row)
        outer.addWidget(platform_card)

        # Wrap angle preview
        preview_card = QFrame()
        preview_card.setStyleSheet(
            f"background-color: {_Theme.BG_CARD};"
            f"border: 1px solid {_Theme.BORDER};"
            f"border-radius: 8px;"
        )
        preview_layout = QHBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 10, 14, 10)

        preview_label = QLabel("Calculated wrap angle")
        preview_label.setStyleSheet(f"color: {_Theme.TEXT_SECONDARY};")
        self.angle_value = QLabel("—")
        self.angle_value.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self.angle_value.setStyleSheet(f"color: {_Theme.ACCENT_PRIMARY};")
        formula = QLabel("θ = arctan(P / π(D + 2t))")
        formula.setStyleSheet(
            f"color: {_Theme.TEXT_MUTED}; font-family: Consolas, Menlo, monospace;"
        )

        preview_layout.addWidget(preview_label)
        preview_layout.addStretch()
        preview_layout.addWidget(formula)
        preview_layout.addSpacing(12)
        preview_layout.addWidget(self.angle_value)
        outer.addWidget(preview_card)

        # Remember checkbox
        self.remember_checkbox = QCheckBox("Remember these settings for next session")
        self.remember_checkbox.setChecked(self._initial.remember_settings)
        outer.addWidget(self.remember_checkbox)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton("Continue")
        self.ok_button.setObjectName("primary")
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self._on_accept)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.ok_button)
        outer.addLayout(button_row)

    @staticmethod
    def _platform_btn_style(active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background-color: {_Theme.ACCENT_PRIMARY}; "
                f"color: {_Theme.BG_PRIMARY}; border: none; border-radius: 6px; "
                f"padding: 6px 14px; font-weight: 600; font-size: 12px; }}"
            )
        return (
            f"QPushButton {{ background-color: {_Theme.BG_ELEVATED}; "
            f"color: {_Theme.TEXT_SECONDARY}; border: 1px solid {_Theme.BORDER}; "
            f"border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {_Theme.BORDER_FOCUS}; "
            f"color: {_Theme.TEXT_PRIMARY}; }}"
        )

    def _on_platform_selected(self, key: str) -> None:
        self._hw_platform = key
        for k, btn in self._platform_btns.items():
            btn.setChecked(k == key)
            btn.setStyleSheet(self._platform_btn_style(k == key))

    def _wire_validation(self):
        for w in (self.pitch_input, self.thickness_input, self.diameter_input):
            w.textChanged.connect(self._update_angle_preview)

    # ----- behaviour -----------------------------------------------------

    def _parse_inputs(self) -> Optional[tuple[float, float, float]]:
        """Return (pitch_um, thickness_um, diameter_mm) if all valid, else None."""
        try:
            pitch = float(self.pitch_input.text())
            thickness = float(self.thickness_input.text())
            diameter = float(self.diameter_input.text())
        except ValueError:
            return None
        if pitch <= 0 or thickness <= 0 or diameter <= 0:
            return None
        return pitch, thickness, diameter

    def _update_angle_preview(self):
        parsed = self._parse_inputs()
        if parsed is None:
            self.angle_value.setText("—")
            self.ok_button.setEnabled(False)
            for w in (self.pitch_input, self.thickness_input, self.diameter_input):
                txt = w.text().strip()
                invalid = bool(txt) and (not _is_positive_float(txt))
                w.setProperty("invalid", invalid)
                w.style().unpolish(w)
                w.style().polish(w)
            return

        # All inputs valid
        for w in (self.pitch_input, self.thickness_input, self.diameter_input):
            w.setProperty("invalid", False)
            w.style().unpolish(w)
            w.style().polish(w)

        pitch_um, thickness_um, diameter_mm = parsed
        angle = calculate_wrap_angle_deg(pitch_um, diameter_mm, thickness_um)
        self.angle_value.setText(f"{angle:.2f}°")
        self.ok_button.setEnabled(True)

    def _on_accept(self):
        if self._parse_inputs() is None:
            return
        self.accept()


def _is_positive_float(s: str) -> bool:
    try:
        return float(s) > 0
    except ValueError:
        return False


# Small helper to wrap a layout in a QWidget for QGridLayout.addWidget usage.
from PyQt6.QtWidgets import QWidget

class QWidgetContainer(QWidget):
    def __init__(self, layout):
        super().__init__()
        self.setLayout(layout)
