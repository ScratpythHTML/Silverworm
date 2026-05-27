"""
Panel shown in manual mode to configure the pitch overlay scale calibration.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)


class ManualOverlayPanel(QFrame):
    """
    Compact card shown while manual mode is active.

    The overlay draws nearly-vertical pitch reference lines.  Their spacing
    comes from target_pitch_um / scale_um_per_px.  The slight tilt is
    calculated automatically from the configured pitch, tube diameter, and
    wire thickness.

    Only the camera scale (µm/px) needs to be entered here.
    """

    scale_applied = pyqtSignal(float)  # µm per pixel

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------

    def set_scale(self, um_per_px: Optional[float]) -> None:
        """Pre-fill the scale field (from a pipeline result or saved config)."""
        if um_per_px is not None and um_per_px > 0:
            self._scale_input.setText(f"{um_per_px:.4g}")

    # kept for compatibility with callers that pass both values
    def set_calibration(
        self,
        um_per_px: Optional[float],
        thread_angle_deg=None,   # ignored — angle is auto-computed from config
    ) -> None:
        self.set_scale(um_per_px)

    # ------------------------------------------------------------------

    def _build_ui(self):
        self.setStyleSheet("""
            ManualOverlayPanel {
                background-color: #151b23;
                border: 1px solid #2d3748;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title = QLabel("OVERLAY CALIBRATION")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #00d4aa;")
        layout.addWidget(title)

        msg = QLabel(
            "Enter the microscope's pixel size (µm/px) to set the spacing of "
            "the pitch reference lines. The wrap angle is calculated automatically "
            "from your configured pitch, tube diameter, and wire thickness. "
            "Find the scale value in your microscope spec sheet, or run Auto "
            "mode once to detect it from the scale bar in the image."
        )
        msg.setWordWrap(True)
        msg.setFont(QFont("Segoe UI", 10))
        msg.setStyleSheet("color: #8b949e;")
        layout.addWidget(msg)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._scale_input = QLineEdit()
        self._scale_input.setPlaceholderText("e.g. 2.50")
        self._scale_input.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self._scale_input.setFixedWidth(120)
        self._scale_input.setValidator(QDoubleValidator(0.0001, 10000.0, 4))
        self._scale_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a222d;
                color: #e6e6e6;
                border: 1px solid #2d3748;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QLineEdit:focus { border-color: #00d4aa; }
        """)
        self._scale_input.returnPressed.connect(self._on_apply)

        unit = QLabel("µm / px")
        unit.setFont(QFont("Segoe UI", 10))
        unit.setStyleSheet("color: #5c6470;")

        apply_btn = QPushButton("Apply")
        apply_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        apply_btn.setFixedSize(70, 32)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #00d4aa;
                color: #0a0e14;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover { background-color: #00f5c4; }
        """)
        apply_btn.clicked.connect(self._on_apply)

        row.addWidget(self._scale_input)
        row.addWidget(unit)
        row.addStretch()
        row.addWidget(apply_btn)
        layout.addLayout(row)

    def _on_apply(self):
        try:
            value = float(self._scale_input.text().strip())
            if value > 0:
                self.scale_applied.emit(value)
        except ValueError:
            pass
