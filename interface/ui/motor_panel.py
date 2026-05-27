"""
Motor metrics display panel with optional manual speed input.

Owned by MainWindow. Updated externally via `update_metrics(actual_rpm)`
and `set_target(target_rpm)`. Emits `manual_speed_changed(float)` when
the operator commits a value via the SET button.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QFont
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QWidget,
    QLineEdit,
)

from ui.theme import Theme
from ui.widgets import GlowingCard, PulsingIndicator, AnimatedMetricValue


class MotorMetricPanel(GlowingCard):
    """Motor metrics display panel with optional manual speed input."""

    # Emitted when the user clicks SET after entering a manual speed.
    manual_speed_changed = pyqtSignal(float)

    def __init__(
        self,
        motor_name: str,
        target_rpm: float,
        speed_min: float = 0.0,
        speed_max: float = 3000.0,
        parent=None,
    ):
        super().__init__(parent)
        self.target_rpm = target_rpm

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        self.status_indicator = PulsingIndicator(Theme.TEXT_MUTED)
        header_layout.addWidget(self.status_indicator)

        header = QLabel(motor_name)
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        header_layout.addWidget(header)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Metrics
        metrics = QGridLayout()
        metrics.setSpacing(16)
        self._target_label = self._add_metric(
            metrics, 0, "TARGET", f"{target_rpm:.0f} RPM", Theme.TEXT_SECONDARY
        )

        actual_label = QLabel("ACTUAL")
        actual_label.setFont(QFont("Segoe UI", 9))
        actual_label.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        metrics.addWidget(actual_label, 0, 1)

        self.actual_value = AnimatedMetricValue()
        self.actual_value.setText("-- RPM")
        metrics.addWidget(self.actual_value, 1, 1)

        error_label = QLabel("ERROR")
        error_label.setFont(QFont("Segoe UI", 9))
        error_label.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        metrics.addWidget(error_label, 0, 2)

        self.error_value = QLabel("--")
        self.error_value.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        metrics.addWidget(self.error_value, 1, 2)
        layout.addLayout(metrics)

        # Manual speed input (hidden until manual mode)
        self.manual_row = QWidget()
        manual_layout = QHBoxLayout(self.manual_row)
        manual_layout.setContentsMargins(0, 4, 0, 0)
        manual_layout.setSpacing(8)

        manual_label = QLabel("MANUAL SPEED")
        manual_label.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        manual_label.setStyleSheet(f"color: {Theme.WARNING};")
        manual_layout.addWidget(manual_label)

        self.manual_input = QLineEdit()
        self.manual_input.setPlaceholderText(f"{speed_min:.0f} – {speed_max:.0f} RPM")
        self.manual_input.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
        self.manual_input.setFixedWidth(160)
        self.manual_input.setValidator(QDoubleValidator(speed_min, speed_max, 2))
        self.manual_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {Theme.BG_SECONDARY};
                color: {Theme.WARNING};
                border: 2px solid {Theme.WARNING};
                border-radius: 6px;
                padding: 6px 10px;
            }}
            QLineEdit:focus {{
                border-color: {Theme.ACCENT_PRIMARY};
                color: {Theme.ACCENT_PRIMARY};
            }}
        """)
        self.manual_input.returnPressed.connect(self._on_set_clicked)
        manual_layout.addWidget(self.manual_input)

        rpm_suffix = QLabel("RPM")
        rpm_suffix.setFont(QFont("Segoe UI", 10))
        rpm_suffix.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        manual_layout.addWidget(rpm_suffix)

        self.set_btn = QPushButton("SET")
        self.set_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.set_btn.setFixedSize(70, 38)
        self.set_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.ACCENT_PRIMARY};
                color: #000000;
                border: none;
                border-radius: 6px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {Theme.ACCENT_GLOW};
            }}
            QPushButton:pressed {{
                background-color: {Theme.ACCENT_SECONDARY};
            }}
        """)
        self.set_btn.clicked.connect(self._on_set_clicked)
        manual_layout.addWidget(self.set_btn)
        manual_layout.addStretch()

        layout.addWidget(self.manual_row)
        self.manual_row.hide()

    @staticmethod
    def _add_metric(layout, col, label_text, value_text, color):
        label = QLabel(label_text)
        label.setFont(QFont("Segoe UI", 9))
        label.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
        layout.addWidget(label, 0, col)

        value = QLabel(value_text)
        value.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
        value.setStyleSheet(f"color: {color};")
        layout.addWidget(value, 1, col)
        return value

    def set_target(self, rpm: float) -> None:
        self.target_rpm = rpm
        self._target_label.setText(f"{rpm:.0f} RPM")

    def update_metrics(self, actual: float):
        if self.target_rpm == 0.0:
            self.actual_value.set_value(actual, "RPM", 1)
            self.error_value.setText("--")
            return
        error = abs((actual - self.target_rpm) / self.target_rpm * 100)
        self.actual_value.set_value(actual, "RPM", 1)
        self.error_value.setText(f"{error:.1f}%")

        if error > 10:
            color = Theme.ERROR
            self.status_indicator.set_color(Theme.ERROR)
        elif error > 5:
            color = Theme.WARNING
            self.status_indicator.set_color(Theme.WARNING)
        else:
            color = Theme.SUCCESS
            self.status_indicator.set_color(Theme.SUCCESS)

        self.actual_value.setStyleSheet(f"color: {color};")
        self.error_value.setStyleSheet(f"color: {color};")

    def set_running(self, running: bool):
        if running:
            self.status_indicator.start()
        else:
            self.status_indicator.stop()

    def set_manual_mode(self, enabled: bool):
        if enabled:
            self.manual_row.show()
        else:
            self.manual_row.hide()

    def _on_set_clicked(self):
        text = self.manual_input.text().strip()
        if not text:
            return
        try:
            self.manual_speed_changed.emit(float(text))
        except ValueError:
            pass
