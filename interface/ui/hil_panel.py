"""
HIL Test Runner panel — Tools → HIL Test Runner.

A developer/test dialog; does not affect the live camera or motor path.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QDoubleSpinBox, QComboBox,
    QPushButton, QTextEdit, QFileDialog, QMessageBox,
)

from config import AppConfig
from hil_runner import HIL_SCENARIOS, run_hil_scenario, export_csv, default_csv_path


class HILTestPanel(QDialog):
    """Simple HIL test runner dialog. Fully standalone — creates its own
    mock AppState per run and does not touch the live motor/camera path."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HIL Test Runner")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self._config = config
        self._last_tlog = None
        self._last_run_id = ""
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # --- inputs ---
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self._target_pitch = QDoubleSpinBox()
        self._target_pitch.setRange(0.1, 50.0)
        self._target_pitch.setDecimals(2)
        self._target_pitch.setSuffix(" mm")
        self._target_pitch.setValue(self._config.target_pitch_um / 1000.0)
        form.addRow("Target pitch:", self._target_pitch)

        self._initial_feed = QDoubleSpinBox()
        self._initial_feed.setRange(0.1, 20.0)
        self._initial_feed.setDecimals(3)
        self._initial_feed.setSuffix(" mm/s")
        self._initial_feed.setValue(10.0)
        form.addRow("Initial feed speed:", self._initial_feed)

        self._gain = QDoubleSpinBox()
        self._gain.setRange(0.01, 2.0)
        self._gain.setDecimals(2)
        self._gain.setSingleStep(0.1)
        self._gain.setValue(1.0)
        form.addRow("Correction gain:", self._gain)

        self._delay_ms = QDoubleSpinBox()
        self._delay_ms.setRange(0.0, 5000.0)
        self._delay_ms.setDecimals(0)
        self._delay_ms.setSuffix(" ms")
        self._delay_ms.setValue(150.0)
        form.addRow("Mock feedback delay:", self._delay_ms)

        self._manual_speed = QDoubleSpinBox()
        self._manual_speed.setRange(0.0, 20.0)
        self._manual_speed.setDecimals(3)
        self._manual_speed.setSuffix(" mm/s")
        self._manual_speed.setValue(8.0)
        form.addRow("Manual speed (manual scenario):", self._manual_speed)

        root.addLayout(form)

        # --- scenario selector ---
        sc_row = QHBoxLayout()
        sc_row.addWidget(QLabel("Scenario:"))
        self._scenario_box = QComboBox()
        for key, sc in HIL_SCENARIOS.items():
            self._scenario_box.addItem(sc.name, userData=key)
        sc_row.addWidget(self._scenario_box, 1)
        root.addLayout(sc_row)

        # --- description label ---
        self._desc_label = QLabel()
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color: grey; font-size: 11px;")
        self._scenario_box.currentIndexChanged.connect(self._on_scenario_changed)
        root.addWidget(self._desc_label)
        self._on_scenario_changed(0)

        # --- buttons ---
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("Run HIL Test")
        self._run_btn.clicked.connect(self._on_run)
        self._export_btn = QPushButton("Export CSV")
        self._export_btn.clicked.connect(self._on_export)
        self._export_btn.setEnabled(False)
        btn_row.addWidget(self._run_btn)
        btn_row.addWidget(self._export_btn)
        root.addLayout(btn_row)

        # --- results log ---
        root.addWidget(QLabel("Results:"))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(180)
        root.addWidget(self._log, 1)

        # --- export path ---
        self._path_label = QLabel()
        self._path_label.setStyleSheet("font-size: 10px; color: grey;")
        self._path_label.setWordWrap(True)
        root.addWidget(self._path_label)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_scenario_changed(self, _index: int) -> None:
        key = self._scenario_box.currentData()
        if key in HIL_SCENARIOS:
            self._desc_label.setText(HIL_SCENARIOS[key].description)

    def _on_run(self) -> None:
        key = self._scenario_box.currentData()
        scenario = HIL_SCENARIOS[key]

        # Build a temporary config with panel's target pitch.
        cfg = AppConfig(
            target_pitch_um=self._target_pitch.value() * 1000.0,
            wire_thickness_um=self._config.wire_thickness_um,
            tube_diameter_mm=self._config.tube_diameter_mm,
        )

        try:
            tlog, logs, run_id = run_hil_scenario(
                scenario=scenario,
                config=cfg,
                initial_feed_speed_mm_s=self._initial_feed.value(),
                correction_gain=self._gain.value(),
                mock_feedback_delay_ms=self._delay_ms.value(),
                manual_feed_speed_mm_s=self._manual_speed.value(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "HIL Error", str(exc))
            return

        self._last_tlog = tlog
        self._last_run_id = run_id
        self._export_btn.setEnabled(True)

        # Display step logs + summary.
        text_lines = [f"Run ID: {run_id}", ""]
        text_lines.extend(logs)
        text_lines.append("")

        last = tlog.last
        if last is not None:
            text_lines.append(f"Resulting mode : {last.resulting_mode}")
        text_lines.append(f"Records logged : {len(tlog.records)}")

        motor_ms = tlog.last_motor_response_time_ms
        if motor_ms is not None:
            text_lines.append(f"Motor resp.    : {motor_ms:.0f} ms")

        sens = tlog.last_pitch_sensitivity_per_feed_speed
        if sens is not None:
            text_lines.append(f"Δpitch/Δfeed   : {sens:.4f} mm per mm/s")

        self._log.setPlainText("\n".join(text_lines))
        self._path_label.setText("")

    def _on_export(self) -> None:
        if self._last_tlog is None or not self._last_tlog.records:
            QMessageBox.warning(self, "No data", "Run a scenario first.")
            return

        suggested = default_csv_path()
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save HIL Telemetry CSV",
            str(suggested),
            "CSV files (*.csv);;All Files (*)",
        )
        if not path_str:
            return

        try:
            out = export_csv(self._last_tlog.records, Path(path_str), self._last_run_id)
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
            return

        self._path_label.setText(f"Exported: {out}")
