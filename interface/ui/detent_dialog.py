"""
Detent configurator dialog.

Lets the operator edit the per-detent speed increments for one motor at a
time. The PUI sends "D1±N"/"D2±N" where N ∈ {1,2,3} selects the detent size
(small/medium/large) and the sign selects direction. Only the *magnitude* is
configured here — the sign comes from the physical dial direction.

  - Wrapper motor → Dial 1 → increments in RPM
  - Feed motor    → Dial 2 → increments in mm/s

On accept, call detent_config() to retrieve a fresh DetentConfig carrying all
six values (both motors), with the currently-shown motor's edits applied.
"""

from __future__ import annotations

from PyQt6.QtGui import QDoubleValidator, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox,
)

from config import DetentConfig
from ui.theme import Theme


# Detent sizes shown in the dialog, in PUI "N" order: small=1, medium=2, large=3.
_SIZES = (
    ("Small", "D±1"),
    ("Medium", "D±2"),
    ("Large", "D±3"),
)

_WRAPPER = "Wrapper Motor"
_FEED = "Feed Motor"


class DetentConfigDialog(QDialog):
    """Edit the six dial-increment values, one motor at a time."""

    def __init__(self, initial: DetentConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Silverworm — Detent Configurator")
        self.setModal(True)
        self.setMinimumWidth(420)

        # Working copy of all six magnitudes, keyed by (motor, size_index).
        # Edits to the visible motor are flushed here on every switch/accept.
        self._values: dict[tuple[str, int], float] = {
            (_WRAPPER, 0): initial.dial1_small_rpm,
            (_WRAPPER, 1): initial.dial1_medium_rpm,
            (_WRAPPER, 2): initial.dial1_large_rpm,
            (_FEED, 0): initial.dial2_small_mms,
            (_FEED, 1): initial.dial2_medium_mms,
            (_FEED, 2): initial.dial2_large_mms,
        }
        self._current_motor = _WRAPPER

        self._build_ui()
        self._load_motor(self._current_motor)

    # ----- public --------------------------------------------------------

    def detent_config(self) -> DetentConfig:
        """Assemble a DetentConfig from the working values (flushing edits first)."""
        self._flush_fields()
        return DetentConfig(
            dial1_small_rpm=self._values[(_WRAPPER, 0)],
            dial1_medium_rpm=self._values[(_WRAPPER, 1)],
            dial1_large_rpm=self._values[(_WRAPPER, 2)],
            dial2_small_mms=self._values[(_FEED, 0)],
            dial2_medium_mms=self._values[(_FEED, 1)],
            dial2_large_mms=self._values[(_FEED, 2)],
        )

    # ----- ui construction ----------------------------------------------

    def _build_ui(self) -> None:
        self.setStyleSheet(f"""
            QDialog {{ background-color: {Theme.BG_PRIMARY}; }}
            QLabel {{ color: {Theme.TEXT_PRIMARY};
                      font-family: 'Segoe UI', sans-serif; }}
            QComboBox, QLineEdit {{
                background-color: {Theme.BG_ELEVATED};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 13px;
            }}
            QLineEdit {{ font-family: 'Consolas', 'Menlo', monospace; }}
            QLineEdit:focus, QComboBox:focus {{ border: 1px solid {Theme.BORDER_FOCUS}; }}
            QPushButton {{
                background-color: {Theme.BG_ELEVATED};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 6px;
                padding: 8px 18px;
                font-size: 13px;
                font-weight: 600;
            }}
            QPushButton:hover {{ border: 1px solid {Theme.BORDER_FOCUS}; }}
            QPushButton#primary {{
                background-color: {Theme.ACCENT_PRIMARY};
                color: {Theme.BG_PRIMARY};
                border: none;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 22)
        outer.setSpacing(16)

        title = QLabel("Detent Configurator")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        outer.addWidget(title)

        subtitle = QLabel(
            "Set the speed change applied per dial detent. The magnitude is "
            "used for both directions; the sign comes from the dial."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: 12px;")
        outer.addWidget(subtitle)

        # Motor selector
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Motor"))
        self.motor_combo = QComboBox()
        self.motor_combo.addItems([_WRAPPER, _FEED])
        self.motor_combo.currentTextChanged.connect(self._on_motor_changed)
        selector_row.addWidget(self.motor_combo, 1)
        outer.addLayout(selector_row)

        # Increment grid — one editable magnitude per detent size.
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self._inputs: list[QLineEdit] = []
        self._unit_labels: list[QLabel] = []
        for row, (name, code) in enumerate(_SIZES):
            label = QLabel(f"{name} ({code})")
            field = QLineEdit()
            field.setValidator(QDoubleValidator(0.0, 1e9, 4))
            unit = QLabel()
            unit.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
            grid.addWidget(label, row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(unit, row, 2)
            self._inputs.append(field)
            self._unit_labels.append(unit)
        grid.setColumnStretch(1, 1)
        outer.addLayout(grid)

        # Buttons
        button_row = QHBoxLayout()
        button_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        button_row.addWidget(cancel)
        button_row.addWidget(save)
        outer.addLayout(button_row)

    # ----- behaviour -----------------------------------------------------

    def _unit_for(self, motor: str) -> str:
        return "RPM" if motor == _WRAPPER else "mm/s"

    def _flush_fields(self) -> None:
        """Save the visible fields back into the working store for the
        currently-selected motor. Blank/invalid entries keep their old value."""
        for i, field in enumerate(self._inputs):
            try:
                self._values[(self._current_motor, i)] = float(field.text())
            except ValueError:
                pass  # leave the previous value untouched

    def _load_motor(self, motor: str) -> None:
        """Populate the fields and units from the working store for `motor`."""
        unit = self._unit_for(motor)
        for i, field in enumerate(self._inputs):
            field.setText(f"{self._values[(motor, i)]:g}")
            self._unit_labels[i].setText(unit)

    def _on_motor_changed(self, motor: str) -> None:
        # Flush edits for the outgoing motor before swapping the view.
        self._flush_fields()
        self._current_motor = motor
        self._load_motor(motor)
