"""
HIL Test Runner panel — Tools → HIL Test Runner.

Two modes:

  Live (real hardware)
      Uses the running app's AppState and telemetry. Inject buttons send
      real SPI SET_SPEED commands to the feed motor. Actual speed feedback
      arrives via the normal SPI poll → _on_feed_current path and is
      captured in the shared TelemetryLog automatically.

  Mock (standalone / no hardware)
      Creates its own AppState with mock SPI transports.  Safe to run
      on a Mac with no motors attached.  Runs predefined batch scenarios.

The two modes share the same log window and CSV export path.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QDoubleSpinBox, QComboBox, QCheckBox,
    QPushButton, QTextEdit, QFileDialog, QMessageBox,
)

from app_state import AppState
from config import AppConfig
from pitch_control import PitchMeasurement, process_pitch_result
from telemetry import TelemetryLog
from hil_runner import HIL_SCENARIOS, run_hil_scenario, export_csv, default_csv_path


class HILTestPanel(QDialog):
    """HIL Test Runner — live injection or offline batch."""

    # Emitted when the HIL target pitch changes — MainWindow updates the
    # TARGET cell in the pitch metrics card so recordings show the HIL target.
    target_pitch_changed = pyqtSignal(float)

    # Emitted when a correction is calculated (in either mode).
    # MainWindow connects this to update the feed-motor panel and telemetry labels.
    speed_commanded = pyqtSignal(float)

    def __init__(
        self,
        config: AppConfig,
        app_state: Optional[AppState] = None,
        telemetry: Optional[TelemetryLog] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("HIL Test Runner")
        self.setMinimumWidth(580)
        self.setMinimumHeight(600)

        self._config = config
        # Live references — only present when real hardware is connected.
        self._live_app_state = app_state
        self._live_telemetry = telemetry

        # The TelemetryLog used for the most recent run (live or mock).
        self._active_tlog: Optional[TelemetryLog] = None
        self._active_run_id: str = ""

        self._setup_ui()

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── hardware mode toggle ──────────────────────────────────────
        mode_row = QHBoxLayout()
        self._live_chk = QCheckBox("Live mode — use real hardware / SPI")
        self._live_chk.setEnabled(self._live_app_state is not None)
        self._live_chk.setChecked(self._live_app_state is not None)
        self._live_chk.toggled.connect(self._on_mode_toggled)
        live_hint = QLabel(
            "(inject pitch into running AppState → real SPI → Group B feed motor)"
            if self._live_app_state is not None
            else "(no live hardware available — mock mode only)"
        )
        live_hint.setStyleSheet("color: grey; font-size: 10px;")
        mode_row.addWidget(self._live_chk)
        mode_row.addWidget(live_hint, 1)
        root.addLayout(mode_row)

        # ── shared parameters ─────────────────────────────────────────
        params = QFormLayout()
        params.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        params.setSpacing(6)

        self._target_pitch = QDoubleSpinBox()
        self._target_pitch.setRange(0.1, 50.0)
        self._target_pitch.setDecimals(2)
        self._target_pitch.setSuffix(" mm")
        self._target_pitch.setValue(self._config.target_pitch_um / 1000.0)
        self._target_pitch.valueChanged.connect(
            lambda v: self.target_pitch_changed.emit(v)
        )
        params.addRow("Target pitch:", self._target_pitch)

        self._gain = QDoubleSpinBox()
        self._gain.setRange(0.01, 2.0)
        self._gain.setDecimals(2)
        self._gain.setSingleStep(0.1)
        self._gain.setValue(1.0)
        params.addRow("Correction gain:", self._gain)

        root.addLayout(params)

        # ── live inject section ───────────────────────────────────────
        self._inject_group = QGroupBox("Inject pitch reading (live or mock single-shot)")
        inj = QVBoxLayout(self._inject_group)

        # live: show current feed speed so the operator knows where they're starting
        self._live_feed_label = QLabel()
        self._live_feed_label.setStyleSheet("color: grey; font-size: 10px;")
        inj.addWidget(self._live_feed_label)
        self._update_live_feed_label()

        # mock single-shot: configurable initial feed speed (hidden in live mode)
        self._mock_feed_row = QHBoxLayout()
        self._mock_feed_row.addWidget(QLabel("Starting feed speed:"))
        self._mock_initial_feed = QDoubleSpinBox()
        self._mock_initial_feed.setRange(0.1, 20.0)
        self._mock_initial_feed.setDecimals(3)
        self._mock_initial_feed.setSuffix(" mm/s")
        self._mock_initial_feed.setValue(self._config.initial_feed_speed_mms or 10.0)
        self._mock_feed_row.addWidget(self._mock_initial_feed)
        self._mock_feed_widget = QWidget()
        self._mock_feed_widget.setLayout(self._mock_feed_row)
        inj.addWidget(self._mock_feed_widget)

        # confidence
        conf_row = QHBoxLayout()
        conf_row.addWidget(QLabel("Confidence:"))
        self._conf_box = QComboBox()
        for c in ("HIGH", "MEDIUM", "LOW", "FAILED"):
            self._conf_box.addItem(c)
        conf_row.addWidget(self._conf_box)
        conf_row.addStretch()
        inj.addLayout(conf_row)

        # quick-inject buttons (under / over / at target)
        quick = QHBoxLayout()
        quick.addWidget(QLabel("Quick inject:"))
        for label, pct in (("−20%", 0.80), ("−10%", 0.90),
                           ("At target", 1.00),
                           ("+10%", 1.10), ("+20%", 1.20)):
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _checked, p=pct: self._on_inject_quick(p))
            quick.addWidget(btn)
        inj.addLayout(quick)

        # custom pitch + inject
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom pitch:"))
        self._custom_pitch = QDoubleSpinBox()
        self._custom_pitch.setRange(0.01, 100.0)
        self._custom_pitch.setDecimals(3)
        self._custom_pitch.setSuffix(" mm")
        self._custom_pitch.setValue(self._config.target_pitch_um / 1000.0)
        custom_row.addWidget(self._custom_pitch)
        inject_btn = QPushButton("Inject →")
        inject_btn.setFixedHeight(28)
        inject_btn.clicked.connect(
            lambda: self._do_inject(self._custom_pitch.value(), self._conf_box.currentText())
        )
        custom_row.addWidget(inject_btn)
        inj.addLayout(custom_row)

        root.addWidget(self._inject_group)

        # ── mock-only: batch scenario ─────────────────────────────────
        self._batch_group = QGroupBox("Batch scenario (mock mode only)")
        batch = QVBoxLayout(self._batch_group)

        sc_row = QHBoxLayout()
        sc_row.addWidget(QLabel("Scenario:"))
        self._scenario_box = QComboBox()
        for key, sc in HIL_SCENARIOS.items():
            self._scenario_box.addItem(sc.name, userData=key)
        self._scenario_box.currentIndexChanged.connect(self._on_scenario_changed)
        sc_row.addWidget(self._scenario_box, 1)
        batch.addLayout(sc_row)

        self._desc_label = QLabel()
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color: grey; font-size: 10px;")
        batch.addWidget(self._desc_label)
        self._on_scenario_changed(0)

        batch_params = QFormLayout()
        batch_params.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        batch_params.setSpacing(6)

        self._initial_feed = QDoubleSpinBox()
        self._initial_feed.setRange(0.1, 20.0)
        self._initial_feed.setDecimals(3)
        self._initial_feed.setSuffix(" mm/s")
        self._initial_feed.setValue(10.0)
        batch_params.addRow("Initial feed speed:", self._initial_feed)

        self._delay_ms = QDoubleSpinBox()
        self._delay_ms.setRange(0.0, 5000.0)
        self._delay_ms.setDecimals(0)
        self._delay_ms.setSuffix(" ms")
        self._delay_ms.setValue(150.0)
        batch_params.addRow("Mock feedback delay:", self._delay_ms)

        self._manual_speed = QDoubleSpinBox()
        self._manual_speed.setRange(0.0, 20.0)
        self._manual_speed.setDecimals(3)
        self._manual_speed.setSuffix(" mm/s")
        self._manual_speed.setValue(8.0)
        batch_params.addRow("Manual speed (manual scenario):", self._manual_speed)
        batch.addLayout(batch_params)

        run_btn = QPushButton("Run Batch Scenario")
        run_btn.clicked.connect(self._on_run_batch)
        batch.addWidget(run_btn)

        root.addWidget(self._batch_group)

        # ── log + export ──────────────────────────────────────────────
        root.addWidget(QLabel("Log:"))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(150)
        root.addWidget(self._log, 1)

        bottom = QHBoxLayout()
        self._clear_btn = QPushButton("Clear log")
        self._clear_btn.clicked.connect(self._on_clear)
        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        bottom.addWidget(self._clear_btn)
        bottom.addStretch()
        bottom.addWidget(self._export_btn)
        root.addLayout(bottom)

        self._path_label = QLabel()
        self._path_label.setStyleSheet("font-size: 10px; color: grey;")
        self._path_label.setWordWrap(True)
        root.addWidget(self._path_label)

        # initial visibility
        self._on_mode_toggled(self._live_chk.isChecked())

    # ------------------------------------------------------------------
    # Mode toggle
    # ------------------------------------------------------------------

    def _on_mode_toggled(self, live: bool) -> None:
        self._batch_group.setVisible(not live)
        self._mock_feed_widget.setVisible(not live)
        self._live_feed_label.setVisible(live)
        self._inject_group.setTitle(
            "Inject pitch reading (→ real SPI → Group B feed motor)"
            if live else
            "Inject pitch reading (single-shot mock)"
        )
        self._update_live_feed_label()
        self.adjustSize()

    def _update_live_feed_label(self) -> None:
        """Refresh the 'Current feed speed' info line from the live AppState."""
        if self._live_app_state is not None and self._live_chk.isChecked():
            mms = self._live_app_state.feed_speed_mms
            self._live_feed_label.setText(
                f"Current feed speed in AppState: {mms:.3f} mm/s  "
                f"(machine {'ON' if self._live_app_state.machine_on else 'OFF'})"
            )
        else:
            self._live_feed_label.setText("")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _effective_config(self) -> AppConfig:
        """Config with the panel's target pitch override applied."""
        import copy
        cfg = copy.copy(self._config)
        cfg.target_pitch_um = self._target_pitch.value() * 1000.0
        return cfg

    def _is_live(self) -> bool:
        return self._live_chk.isChecked() and self._live_app_state is not None

    def _log_line(self, text: str) -> None:
        self._log.append(text)

    # ------------------------------------------------------------------
    # Inject (shared by live and single-shot mock)
    # ------------------------------------------------------------------

    def _on_inject_quick(self, fraction: float) -> None:
        pitch = self._target_pitch.value() * fraction
        self._custom_pitch.setValue(pitch)
        self._do_inject(pitch, self._conf_box.currentText())

    def _do_inject(self, pitch_mm: float, confidence: str) -> None:
        """Inject a single pitch measurement into either live or mock state."""
        cfg = self._effective_config()

        if self._is_live():
            # ── live: use the running AppState ────────────────────────
            state = self._live_app_state
            tlog = self._live_telemetry
            if not self._active_run_id:
                self._active_run_id = uuid.uuid4().hex[:8]
                self._log_line(f"── live run {self._active_run_id} ──")
            self._active_tlog = tlog
        else:
            # ── mock: create a temporary AppState for this one inject ─
            from hil_test import make_hil_state
            state, _wrap_t, _feed_t = make_hil_state(cfg)
            state.gui_set_machine_on(True)
            speed_before = self._mock_initial_feed.value()
            state.gui_set_feed_speed(speed_before)
            tlog = TelemetryLog()
            self._active_tlog = tlog
            if not self._active_run_id:
                self._active_run_id = uuid.uuid4().hex[:8]

        m = PitchMeasurement(
            measured_pitch_mm=pitch_mm,
            confidence=confidence,
            num_wraps=10,
            source="HIL",
        )
        log = process_pitch_result(
            m, state, cfg,
            telemetry=tlog,
            correction_gain=self._gain.value(),
        )
        self._log_line(log)

        # Show commanded speed in log and notify main window to update its
        # motor panel + telemetry labels (works in both mock and live mode).
        last = tlog.last
        if last is not None and last.command_sent_successfully:
            self._log_line(
                f"  → commanded {last.commanded_feed_speed_mm_s:.3f} mm/s"
                f"  (Δ {last.speed_delta_mm_s:+.3f} mm/s)"
            )
            self.speed_commanded.emit(last.commanded_feed_speed_mm_s)

        # Refresh live feed label so operator sees updated speed after inject.
        self._update_live_feed_label()
        self._export_btn.setEnabled(True)
        self._path_label.setText("")

    # ------------------------------------------------------------------
    # Batch scenario (mock only)
    # ------------------------------------------------------------------

    def _on_scenario_changed(self, _index: int) -> None:
        key = self._scenario_box.currentData()
        if key in HIL_SCENARIOS:
            self._desc_label.setText(HIL_SCENARIOS[key].description)

    def _on_run_batch(self) -> None:
        key = self._scenario_box.currentData()
        scenario = HIL_SCENARIOS[key]
        cfg = self._effective_config()

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

        self._active_tlog = tlog
        self._active_run_id = run_id
        self._export_btn.setEnabled(True)

        self._log_line(f"── batch run {run_id} ──")
        for line in logs:
            self._log_line(line)

        last = tlog.last
        if last is not None:
            self._log_line(f"Resulting mode : {last.resulting_mode}")
        self._log_line(f"Records logged : {len(tlog.records)}")

        motor_ms = tlog.last_motor_response_time_ms
        if motor_ms is not None:
            self._log_line(f"Motor resp.    : {motor_ms:.0f} ms")
        sens = tlog.last_pitch_sensitivity_per_feed_speed
        if sens is not None:
            self._log_line(f"Δpitch/Δfeed   : {sens:.4f} mm per mm/s")
        self._path_label.setText("")

    # ------------------------------------------------------------------
    # Export / clear
    # ------------------------------------------------------------------

    def _on_clear(self) -> None:
        self._log.clear()
        self._active_run_id = ""
        self._active_tlog = None
        self._export_btn.setEnabled(False)
        self._path_label.setText("")

    def _on_export(self) -> None:
        tlog = self._active_tlog
        if tlog is None or not tlog.records:
            QMessageBox.warning(self, "No data", "Inject at least one reading first.")
            return

        suggested = default_csv_path()
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save HIL Telemetry CSV", str(suggested),
            "CSV files (*.csv);;All Files (*)",
        )
        if not path_str:
            return

        try:
            out = export_csv(tlog.records, Path(path_str), self._active_run_id)
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))
            return

        self._path_label.setText(f"Exported: {out}")
