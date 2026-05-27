"""
MainWindow — composes the GUI and routes hardware events to AppState.

Responsibilities (intentionally narrow):
  - build the window layout from the widgets in `ui/`
  - wire ControlPanel / motor panels / camera signals to AppState
  - listen to AppState signals and update widgets accordingly
  - own the camera workers, pitch pipeline, and storage objects
  - subscribe to PUI / motor errors and surface them in the alert log

Anything visual lives in `ui/*.py`. Hardware transport construction
lives in `hardware.py`. Protocol parsing lives in `comms/*.py`.
"""

from __future__ import annotations

import math
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from PyQt6.QtCore import Qt, QTimer, QStandardPaths
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFileDialog,
)

# Hardware + state
from app_state import (
    AppState, Mode, WRAP_RPM_UNITS_PER, FEED_MMS_UNITS_PER,
)
from config import AppConfig, save_config, calculate_wrap_angle_deg
from hardware import build_transports
from comms import PUIListener, MotorController
from comms import MockTransport, Transport
from controller import (
    SetpointController, OperatingMode, Setpoints,
    SPEED_A_MIN, SPEED_A_MAX, SPEED_B_MIN, SPEED_B_MAX,
)
from storage import StorageManager

# Camera + vision
from camera import CameraDetector, CameraWorker, CameraConfig
from camera.rolling_buffer import RollingBuffer
from processing import PitchDetectionPipeline

# Widgets
from ui.theme import Theme
from ui.widgets import PulsingIndicator
from ui.motor_panel import MotorMetricPanel
from ui.pitch_graph import PitchGraph
from ui.alert_log import AlertLog
from ui.control_panel import ControlPanel
from ui.camera_widget import EnhancedCameraView
from ui.manual_mode_dialog import ManualModeBanner
from ui.manual_overlay_panel import ManualOverlayPanel


class MainWindow(QMainWindow):
    """Main application window — coordinates UI ↔ AppState ↔ hardware."""

    def __init__(self, config: AppConfig):
        super().__init__()
        self.setWindowTitle("Silverworm Control System")
        self.setMinimumSize(1400, 900)
        self.resize(1600, 1000)

        self.config = config
        self._is_running = False
        self._distance = 0
        self._calibrated_scale_um_per_px: float = config.scale_um_per_px
        self._calibration_manually_applied: bool = config.scale_um_per_px > 0

        # Camera + processing state
        self.camera_worker: Optional[CameraWorker] = None
        self._primary_worker: Optional[CameraWorker] = None
        self._secondary_worker: Optional[CameraWorker] = None
        self._active_camera: str = "microscope"
        self._current_raw_frame: Optional[np.ndarray] = None
        self.pitch_pipeline = PitchDetectionPipeline(interval_ms=2000, parent=self)
        self.manual_banner: Optional[ManualModeBanner] = None

        # Storage and rolling buffer
        self.rolling_buffer = RollingBuffer(window_seconds=300.0)
        self.storage = StorageManager()
        self._snapshot_dir = self._get_default_pictures_dir()

        # Legacy setpoint controller + UART transport (still used by the
        # low-confidence auto-manual flow; the new AppState path is the
        # authoritative one for normal operation).
        self.controller = SetpointController()
        self.transport: Transport = MockTransport()
        self.transport.open()
        self._last_comms_ok = True

        # Hardware transports + AppState wiring
        self._setup_hardware()

        # UI
        self._setup_ui()
        self._setup_menu_bar()
        self._setup_timers()
        self._connect_signals()
        self._connect_app_state_signals()
        self._connect_motor_feedback()
        self._setup_controller_callbacks()
        self._apply_styles()

        self.alert_log.log("System initialized", "success")
        if self._transports.is_mock:
            self.alert_log.log("Hardware mode: MOCK (no I2C/SPI)", "info")
        else:
            self.alert_log.log(
                f"Hardware mode: {self.config.hw_platform.upper()}", "info"
            )
        self.alert_log.log("Awaiting camera connection...", "info")

        # Camera last — depends on alert_log being available
        self._setup_camera()
        self._connect_camera_signals()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _setup_hardware(self) -> None:
        """Build I2C/SPI transports and the central AppState."""
        self._transports = build_transports(self.config)

        self.pui_listener = PUIListener(self._transports.pui, parent=self)
        self.wrap_motor_controller = MotorController(self._transports.wrap_spi, parent=self)
        self.feed_motor_controller = MotorController(self._transports.feed_spi, parent=self)

        # Motor SPI transports must be opened before AppState can drive them.
        # A real hardware failure raises here; we catch and continue with mocks-ish
        # behaviour (the controller still emits signals; sends just go nowhere).
        for name, controller in (
            ("wrap", self.wrap_motor_controller),
            ("feed", self.feed_motor_controller),
        ):
            try:
                controller.open()
            except Exception as e:
                # alert_log doesn't exist yet — defer the message.
                print(f"[hardware] {name} motor open failed: {e}")

        self.app_state = AppState(
            self.config,
            wrap_motor=self.wrap_motor_controller,
            feed_motor=self.feed_motor_controller,
            parent=self,
        )
        self.pui_listener.start()

    def _setup_timers(self) -> None:
        self.metrics_timer = QTimer()
        self.metrics_timer.timeout.connect(self._update_metrics)

        self.graph_timer = QTimer()
        self.graph_timer.timeout.connect(self._update_graph)

        # Poll motor controllers for response packets at 10 Hz.
        # No-op on MockSPITransport unless tests inject responses; on real
        # hardware this is what drives the actual-speed readout.
        self.motor_poll_timer = QTimer()
        self.motor_poll_timer.setInterval(100)
        self.motor_poll_timer.timeout.connect(self._poll_motors)
        self.motor_poll_timer.start()

    def _setup_controller_callbacks(self) -> None:
        """Wire the legacy SetpointController callbacks."""
        self.controller.on_setpoints_changed = self._on_setpoints_changed
        self.controller.on_mode_changed = self._on_controller_mode_changed

    @staticmethod
    def _get_default_pictures_dir() -> str:
        pictures = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.PicturesLocation
        )
        if pictures and os.path.isdir(pictures):
            return pictures
        return str(Path.home())

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        main = QHBoxLayout(central)
        main.setContentsMargins(24, 24, 24, 24)
        main.setSpacing(24)

        # ----- left column -----
        left = QVBoxLayout()
        left.setSpacing(20)

        # Header
        header_widget = QWidget()
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 12)

        title = QLabel("Silverworm Control System")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Theme.TEXT_PRIMARY};")

        self.status_indicator = PulsingIndicator(Theme.WARNING)
        self.status_label = QLabel("STANDBY")
        self.status_label.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self.status_label.setStyleSheet(f"color: {Theme.WARNING};")

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status_indicator)
        header.addWidget(self.status_label)
        left.addWidget(header_widget)

        # Camera card
        from ui.widgets import GlowingCard
        camera_card = GlowingCard()
        camera_layout = QVBoxLayout(camera_card)
        camera_layout.setContentsMargins(16, 12, 16, 12)

        cam_header = QHBoxLayout()
        cam_title = QLabel("Live Camera View")
        cam_title.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        cam_title.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")

        cam_hint = QLabel("Click to focus • Arrow keys move crosshair • Shift for faster")
        cam_hint.setFont(QFont("Segoe UI", 9))
        cam_hint.setStyleSheet(f"color: {Theme.TEXT_MUTED};")

        self._cam_toggle_btn = QPushButton("Switch to Webcam")
        self._cam_toggle_btn.setFixedHeight(26)
        self._cam_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {Theme.BG_ELEVATED};
                color: {Theme.TEXT_SECONDARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 4px;
                padding: 0 10px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                background-color: {Theme.BG_HOVER};
                color: {Theme.ACCENT_PRIMARY};
                border-color: {Theme.ACCENT_PRIMARY};
            }}
            QPushButton:disabled {{
                color: {Theme.TEXT_DISABLED};
            }}
        """)
        self._cam_toggle_btn.setEnabled(False)
        self._cam_toggle_btn.clicked.connect(self._on_camera_toggle)

        self._cam_warning_label = QLabel()
        self._cam_warning_label.setStyleSheet(f"color: {Theme.WARNING}; font-size: 11px;")
        self._cam_warning_label.hide()

        cam_header.addWidget(cam_title)
        cam_header.addStretch()
        cam_header.addWidget(self._cam_warning_label)
        cam_header.addWidget(cam_hint)
        cam_header.addWidget(self._cam_toggle_btn)
        camera_layout.addLayout(cam_header)

        self.camera = EnhancedCameraView()
        camera_layout.addWidget(self.camera)
        left.addWidget(camera_card, 2)

        # Manual-overlay calibration (hidden until manual mode)
        self._manual_overlay_panel = ManualOverlayPanel()
        self._manual_overlay_panel.scale_applied.connect(self._on_overlay_scale_applied)
        self._manual_overlay_panel.set_scale(self._calibrated_scale_um_per_px)
        self._manual_overlay_panel.hide()
        left.addWidget(self._manual_overlay_panel)

        # Pitch graph
        self.graph = PitchGraph()
        left.addWidget(self.graph, 1)

        main.addLayout(left, 3)

        # ----- right column -----
        right = QVBoxLayout()
        right.setSpacing(20)

        self.feed_motor_panel = MotorMetricPanel(
            "Feed Motor", 1.0,
            speed_min=SPEED_A_MIN, speed_max=SPEED_A_MAX,
        )
        self.wrap_motor_panel = MotorMetricPanel(
            "Wrapper Motor", 1000.0,
            speed_min=SPEED_B_MIN, speed_max=SPEED_B_MAX,
        )
        right.addWidget(self.feed_motor_panel)
        right.addWidget(self.wrap_motor_panel)

        # Pitch metrics card
        pitch_card = GlowingCard()
        pitch_layout = QVBoxLayout(pitch_card)
        pitch_layout.setContentsMargins(20, 16, 20, 16)

        pitch_header = QLabel("Pitch Metrics")
        pitch_header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        pitch_header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        pitch_layout.addWidget(pitch_header)

        pitch_grid = QGridLayout()
        pitch_grid.setSpacing(16)
        for col, (label, default) in enumerate(
            [("TARGET", "1.00 mm"), ("ACTUAL", "-- mm"), ("ERROR", "--")]
        ):
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 9))
            lbl.setStyleSheet(f"color: {Theme.TEXT_MUTED};")
            pitch_grid.addWidget(lbl, 0, col)

            val = QLabel(default)
            val.setFont(QFont("Consolas", 18, QFont.Weight.Bold))
            pitch_grid.addWidget(val, 1, col)

            if label == "ACTUAL":
                self.pitch_actual = val
            elif label == "ERROR":
                self.pitch_error = val

        pitch_layout.addLayout(pitch_grid)
        right.addWidget(pitch_card)

        # Controls + log
        self.controls = ControlPanel()
        right.addWidget(self.controls)
        self.alert_log = AlertLog()
        right.addWidget(self.alert_log, 1)

        main.addLayout(right, 1)

    def _setup_menu_bar(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")

        snapshot_folder_action = file_menu.addAction("Set Default Snapshot Folder...")
        snapshot_folder_action.triggered.connect(self._on_set_snapshot_folder)
        file_menu.addSeparator()

        snapshot_action = file_menu.addAction("Save Snapshot")
        snapshot_action.setShortcut("Ctrl+S")
        snapshot_action.triggered.connect(self._on_snapshot)

        recording_action = file_menu.addAction("Save Last 5-Minute Recording")
        recording_action.setShortcut("Ctrl+R")
        recording_action.triggered.connect(self._on_save_recording)

        # Debug menu — inject simulated PUI messages on macOS / dev rigs.
        # Only meaningful when the underlying transport is a MockPUITransport.
        debug_menu = menu_bar.addMenu("Debug")
        debug_menu.addSection("PUI injection")
        for raw in ("D1+1", "D1+2", "D1+3", "D1-1", "D1-2", "D1-3"):
            debug_menu.addAction(
                f"Inject {raw}",
                lambda r=raw: self._inject_pui_message(r),
            )
        debug_menu.addSeparator()
        for raw in ("D2+1", "D2+2", "D2+3", "D2-1", "D2-2", "D2-3"):
            debug_menu.addAction(
                f"Inject {raw}",
                lambda r=raw: self._inject_pui_message(r),
            )
        debug_menu.addSeparator()
        for label, raw in (
            ("AS0 (manual)", "AS0"),
            ("AS1 (auto)", "AS1"),
            ("TP (toggle power)", "TP"),
        ):
            debug_menu.addAction(
                f"Inject {label}",
                lambda r=raw: self._inject_pui_message(r),
            )

    def _inject_pui_message(self, raw: str) -> None:
        """Inject a PUI message — only works when transport is the Mock variant."""
        transport = self._transports.pui
        inject = getattr(transport, "inject", None)
        if inject is None:
            self.alert_log.log(
                "PUI injection only available in mock mode", "warning"
            )
            return
        inject(raw)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.controls.start_clicked.connect(self._on_start)
        self.controls.stop_clicked.connect(self._on_stop)
        self.controls.snapshot_clicked.connect(self._on_snapshot)
        self.controls.recalibrate_clicked.connect(self._on_recalibrate)
        self.camera.position_changed.connect(self._on_position_changed)

        self.controls.manual_mode_toggled.connect(self._on_manual_mode_button)

        self.feed_motor_panel.manual_speed_changed.connect(self._on_feed_motor_set)
        self.wrap_motor_panel.manual_speed_changed.connect(self._on_wrap_motor_set)

    def _connect_app_state_signals(self) -> None:
        """AppState is the single source of truth. GUI buttons → AppState;
        PUI events → AppState; UI updates ← AppState signals."""

        def on_mode(mode: Mode):
            self.alert_log.log(f"Mode → {mode.value.upper()}", "info")
            is_manual = mode == Mode.MANUAL
            self.controls.set_manual_mode(is_manual)
            self.feed_motor_panel.set_manual_mode(is_manual)
            self.wrap_motor_panel.set_manual_mode(is_manual)
            if is_manual:
                self._manual_overlay_panel.show()
                self._recompute_pitch_overlay()
            else:
                self._manual_overlay_panel.hide()
                self.camera.clear_pitch_overlay()

        def on_power(on: bool):
            self.alert_log.log(
                f"Machine power → {'ON' if on else 'OFF'}",
                "success" if on else "warning",
            )
            # ESP32 lights the power-button LED based on this.
            self.pui_listener.send_status("ON" if on else "OFF")
            self._apply_running_ui_state(on)

        def on_wrap(rpm: float):
            self.alert_log.log(f"Wrap speed: {rpm:.2f} rpm", "info")

        def on_feed(mms: float):
            self.alert_log.log(f"Feed speed: {mms:.3f} mm/s", "info")

        self.app_state.mode_changed.connect(on_mode)
        self.app_state.machine_power_changed.connect(on_power)
        self.app_state.wrap_speed_changed.connect(on_wrap)
        self.app_state.feed_speed_changed.connect(on_feed)

        # PUI listener → AppState (PUI precedence is enforced inside AppState).
        self.pui_listener.dial_changed.connect(self.app_state.apply_dial_change)
        self.pui_listener.mode_switched.connect(self.app_state.apply_mode_switch)
        self.pui_listener.power_toggled.connect(self.app_state.apply_power_toggle)

        # Diagnostics — raw PUI + hardware errors all hit the alert log.
        self.pui_listener.raw_message.connect(
            lambda raw: self.alert_log.log(f"PUI: {raw}", "info")
        )
        self.pui_listener.parse_error.connect(
            lambda raw: self.alert_log.log(f"PUI parse error: {raw}", "warning")
        )
        self.pui_listener.hardware_unavailable.connect(
            lambda err: self.alert_log.log(f"PUI hardware unavailable: {err}", "warning")
        )
        self.app_state.motor_error.connect(
            lambda err: self.alert_log.log(f"Motor error: {err}", "error")
        )
        self.app_state.mode_change_blocked.connect(
            lambda reason: self.alert_log.log(reason, "warning")
        )

    def _connect_motor_feedback(self) -> None:
        """Arduino → MotorController → panel: real motor readback."""
        self.wrap_motor_controller.current_speed.connect(
            lambda units: self.wrap_motor_panel.update_metrics(units / WRAP_RPM_UNITS_PER)
        )
        self.feed_motor_controller.current_speed.connect(
            lambda units: self.feed_motor_panel.update_metrics(units / FEED_MMS_UNITS_PER)
        )
        self.wrap_motor_controller.error_received.connect(
            lambda code: self.alert_log.log(f"Wrap motor error code {code}", "error")
        )
        self.feed_motor_controller.error_received.connect(
            lambda code: self.alert_log.log(f"Feed motor error code {code}", "error")
        )

    def _poll_motors(self) -> None:
        try:
            self.wrap_motor_controller.poll()
        except Exception as e:
            # Swallow per-tick errors so a transient SPI glitch doesn't kill the timer.
            self.alert_log.log(f"Wrap poll error: {e}", "warning")
        try:
            self.feed_motor_controller.poll()
        except Exception as e:
            self.alert_log.log(f"Feed poll error: {e}", "warning")

    # ------------------------------------------------------------------
    # Manual-speed SET buttons
    # ------------------------------------------------------------------

    def _on_feed_motor_set(self, value: float) -> None:
        """User clicked SET on feed-motor panel. Forwarded to AppState (truth)
        and to the legacy SetpointController (keeps the low-confidence banner
        flow working)."""
        self.app_state.gui_set_feed_speed(value)
        self.feed_motor_panel.set_target(value)
        if self.controller.set_manual_speed_a(value):
            if self._last_comms_ok:
                self.camera.show_overlay_message(f"Feed motor speed set to {value:.1f}")
                self.alert_log.log(f"Feed motor speed manually set: {value:.1f}", "success")

    def _on_wrap_motor_set(self, value: float) -> None:
        self.app_state.gui_set_wrap_speed(value)
        self.wrap_motor_panel.set_target(value)
        if self.controller.set_manual_speed_b(value):
            if self._last_comms_ok:
                self.camera.show_overlay_message(f"Wrapper motor speed set to {value:.1f} RPM")
                self.alert_log.log(f"Wrapper motor speed manually set: {value:.1f} RPM", "success")

    def _on_manual_mode_button(self, checked: bool) -> None:
        """User flipped the GUI Manual Mode toggle.

        AppState may reject the change (e.g. PUI is in MANUAL and the user
        clicked AUTO). After calling AppState, re-sync the button visual
        AND the legacy controller to the actual mode so they don't drift.
        """
        self.app_state.gui_set_mode(Mode.MANUAL if checked else Mode.AUTO)
        is_manual = self.app_state.mode == Mode.MANUAL
        self.controls.set_manual_mode(is_manual)
        self.controller.set_mode(OperatingMode.MANUAL if is_manual else OperatingMode.AUTO)

    # ------------------------------------------------------------------
    # Legacy controller callbacks
    # ------------------------------------------------------------------

    def _on_setpoints_changed(self, setpoints: Setpoints) -> None:
        """Legacy UART path. Kept until the low-confidence banner flow is migrated."""
        self._last_comms_ok = True
        try:
            self.transport.send_speeds(setpoints.speed_a, setpoints.speed_b)
        except IOError as e:
            self._last_comms_ok = False
            self.alert_log.log(f"Comms error: {e}", "error")

    def _on_controller_mode_changed(self, mode: OperatingMode) -> None:
        is_manual = mode == OperatingMode.MANUAL
        self.controls.set_manual_mode(is_manual)
        self.feed_motor_panel.set_manual_mode(is_manual)
        self.wrap_motor_panel.set_manual_mode(is_manual)
        if is_manual:
            self.alert_log.log("Manual mode ON — enter motor speeds manually", "warning")
        else:
            self.alert_log.log("Auto mode ON — using vision-computed setpoints", "info")

    # ------------------------------------------------------------------
    # Overlay calibration
    # ------------------------------------------------------------------

    def _on_overlay_scale_applied(self, um_per_px: float) -> None:
        self._calibrated_scale_um_per_px = um_per_px
        self._calibration_manually_applied = True
        self.config.scale_um_per_px = um_per_px
        save_config(self.config)
        self._recompute_pitch_overlay()
        self.alert_log.log(f"Overlay scale set: {um_per_px:.4g} µm/px", "info")

    def _recompute_pitch_overlay(self) -> None:
        scale = self._calibrated_scale_um_per_px
        if scale <= 0:
            scale = 2.0  # fallback until user enters a calibrated value
        spacing_px = self.config.target_pitch_um / scale
        tilt_deg = calculate_wrap_angle_deg(
            self.config.target_pitch_um,
            self.config.tube_diameter_mm,
            self.config.wire_thickness_um,
        )
        self.camera.set_pitch_overlay(spacing_px, tilt_deg)

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        self.app_state.gui_set_machine_on(True)

    def _on_stop(self) -> None:
        self.app_state.gui_set_machine_on(False)

    def _apply_running_ui_state(self, running: bool) -> None:
        """Reflects AppState.machine_on into the UI. SPI start/stop packets
        are emitted by AppState before this handler runs."""
        if running:
            try:
                self._is_running = True
                self.controls.set_running(True)
                self.feed_motor_panel.set_running(True)
                self.wrap_motor_panel.set_running(True)

                self.status_indicator.set_color(Theme.SUCCESS)
                self.status_indicator.start()
                self.status_label.setText("RUNNING")
                self.status_label.setStyleSheet(f"color: {Theme.SUCCESS};")

                self.metrics_timer.start(150)
                self.graph_timer.start(500)

                if self.camera_worker and not hasattr(self, "_pitch_connected"):
                    try:
                        self.camera_worker.frame_ready.connect(self.pitch_pipeline.update_frame)
                        self._pitch_connected = True
                        self.alert_log.log("Pitch detection connected to camera", "info")
                    except Exception as e:
                        self.alert_log.log(f"Failed to connect pitch detection: {e}", "warning")

                try:
                    self.pitch_pipeline.start()
                    self.alert_log.log("Pitch detection started", "info")
                except Exception as e:
                    self.alert_log.log(f"Failed to start pitch detection: {e}", "warning")

                self.alert_log.log("System started — wrapping process initiated", "success")

            except Exception as e:
                self.alert_log.log(f"Error starting system: {e}", "error")
                # Roll back via AppState so SPI also gets a stop packet
                try:
                    self.app_state.gui_set_machine_on(False)
                except Exception:
                    pass
        else:
            self._is_running = False
            self.controls.set_running(False)
            self.feed_motor_panel.set_running(False)
            self.wrap_motor_panel.set_running(False)

            self.status_indicator.set_color(Theme.ERROR)
            self.status_indicator.stop()
            self.status_label.setText("STOPPED")
            self.status_label.setStyleSheet(f"color: {Theme.ERROR};")

            self.metrics_timer.stop()
            self.graph_timer.stop()

            try:
                self.pitch_pipeline.stop()
                self.alert_log.log("Pitch detection stopped", "info")
            except Exception:
                pass
            self.alert_log.log("System stopped", "warning")

    # ------------------------------------------------------------------
    # Metric / graph ticks
    # ------------------------------------------------------------------

    def _update_metrics(self) -> None:
        """Periodic UI metric refresh.

        - Manual mode: show the current setpoint as the actual value (no
          real feedback path until the Arduino reports `current_speed`).
        - Auto + mock platform: synthesise a plausible value so the panel
          isn't dead during dev. NOT used on real hardware — those values
          come from `_connect_motor_feedback`.
        """
        if not self._is_running:
            return

        if self.app_state.mode == Mode.MANUAL:
            self.feed_motor_panel.update_metrics(self.app_state.feed_speed_mms)
            self.wrap_motor_panel.update_metrics(self.app_state.wrap_speed_rpm)
            return

        if self.config.hw_platform != "mock":
            return  # real hardware drives the panels via current_speed signals

        feed = max(0.5, min(3.0, 1.0 + random.gauss(0.5, 0.3)))
        self.feed_motor_panel.update_metrics(feed)

        t = datetime.now().timestamp()
        osc = math.sin(t * 0.5) * 50 + math.sin(t * 1.3) * 25
        wrapper = max(850, min(1000, 925 + osc + random.gauss(0, 10)))
        self.wrap_motor_panel.update_metrics(wrapper)

        if abs(feed - 1.0) > 1.0:
            self.alert_log.log(f"Feed motor deviation: {feed:.1f} RPM", "warning")

    def _update_graph(self) -> None:
        if not self._is_running:
            return
        self._distance += random.uniform(2, 5)
        if self._distance > 500:
            self._distance = 0
            self.graph.clear()
        # Real points are added by _on_pitch_result.

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def _setup_camera(self) -> None:
        detector = CameraDetector()
        diag = detector.detect_all_devices()

        print(detector.format_diagnostic_report())
        self.alert_log.log("Running camera diagnostics...", "info")

        if not diag.devices:
            self.alert_log.log("No camera detected — running in demo mode", "warning")
            for err in diag.errors:
                self.alert_log.log(err, "error")
            for warn in diag.warnings[:2]:
                self.alert_log.log(warn, "warning")
            return

        sorted_devices = sorted(diag.devices, key=lambda d: d.priority, reverse=True)
        primary_device = sorted_devices[0]
        secondary_device = sorted_devices[1] if len(sorted_devices) > 1 else None

        cam_cfg = CameraConfig.amscope_8300p_lowres()
        webcam_cfg = CameraConfig.default()

        self._primary_worker = CameraWorker(
            device_index=primary_device.index, config=cam_cfg, parent=self,
        )
        self._primary_worker.start()
        self.alert_log.log(
            f"Primary camera: {primary_device.name} ({primary_device.path})", "success"
        )

        if secondary_device:
            self._secondary_worker = CameraWorker(
                device_index=secondary_device.index, config=webcam_cfg, parent=self,
            )
            self._secondary_worker.start()
            self.alert_log.log(
                f"Secondary camera: {secondary_device.name} ({secondary_device.path})", "info"
            )
            self._cam_toggle_btn.setEnabled(True)
        else:
            self._cam_toggle_btn.setEnabled(False)

        self._active_camera = "microscope"
        self.camera_worker = self._primary_worker

    def _connect_camera_signals(self) -> None:
        self._first_frame_logged = False

        if self._primary_worker:
            self._primary_worker.frame_ready.connect(self.camera.update_frame)
            self._primary_worker.frame_ready.connect(self.rolling_buffer.add_frame)
            self._primary_worker.frame_ready.connect(self._on_raw_frame)

            def log_first_frame(frame):
                if not self._first_frame_logged:
                    self._first_frame_logged = True
                    self.alert_log.log(
                        f"Camera feed active — {frame.shape[1]}x{frame.shape[0]}", "success"
                    )
            self._primary_worker.frame_ready.connect(log_first_frame)
            self._primary_worker.status_changed.connect(
                lambda msg: self.alert_log.log(msg, "info")
            )
            self._primary_worker.error_occurred.connect(
                lambda err: self._handle_camera_error("microscope", err)
            )
            self._primary_worker.fps_updated.connect(lambda _: None)

        if self._secondary_worker:
            self._secondary_worker.error_occurred.connect(
                lambda err: self._handle_camera_error("webcam", err)
            )

        self.pitch_pipeline.pitch_result_ready.connect(self._on_pitch_result)
        self.pitch_pipeline.manual_mode_triggered.connect(self._on_manual_mode)
        self.pitch_pipeline.detection_error.connect(
            lambda err: self.alert_log.log(err, "error")
        )

    def _on_raw_frame(self, frame: np.ndarray) -> None:
        self._current_raw_frame = frame

    def _on_camera_toggle(self) -> None:
        """Switch the displayed feed between microscope and external webcam."""
        if self._active_camera == "microscope":
            if self._secondary_worker is None:
                self.alert_log.log("No secondary camera available", "warning")
                return
            self._primary_worker.frame_ready.disconnect(self.camera.update_frame)
            self._primary_worker.frame_ready.disconnect(self.rolling_buffer.add_frame)
            self._primary_worker.frame_ready.disconnect(self._on_raw_frame)
            self._secondary_worker.frame_ready.connect(self.camera.update_frame)
            self._secondary_worker.frame_ready.connect(self.rolling_buffer.add_frame)
            self._secondary_worker.frame_ready.connect(self._on_raw_frame)
            self._active_camera = "webcam"
            self.camera_worker = self._secondary_worker
            self._cam_toggle_btn.setText("Switch to Microscope")
            self.alert_log.log("Camera feed → webcam", "info")
            self._cam_warning_label.hide()
        else:
            if self._primary_worker is None:
                self.alert_log.log("No microscope camera available", "warning")
                return
            self._secondary_worker.frame_ready.disconnect(self.camera.update_frame)
            self._secondary_worker.frame_ready.disconnect(self.rolling_buffer.add_frame)
            self._secondary_worker.frame_ready.disconnect(self._on_raw_frame)
            self._primary_worker.frame_ready.connect(self.camera.update_frame)
            self._primary_worker.frame_ready.connect(self.rolling_buffer.add_frame)
            self._primary_worker.frame_ready.connect(self._on_raw_frame)
            self._active_camera = "microscope"
            self.camera_worker = self._primary_worker
            self._cam_toggle_btn.setText("Switch to Webcam")
            self.alert_log.log("Camera feed → microscope", "info")
            self._cam_warning_label.hide()

    def _handle_camera_error(self, role: str, err: str) -> None:
        self.alert_log.log(f"Camera error ({role}): {err}", "error")
        if role == self._active_camera:
            self._cam_warning_label.setText(f"Camera error: {role}")
            self._cam_warning_label.show()

    # ------------------------------------------------------------------
    # Pitch results
    # ------------------------------------------------------------------

    def _on_pitch_result(self, result) -> None:
        try:
            detected_scale = getattr(result, "scale_um_per_px", 0.0)
            if not self._calibration_manually_applied:
                if detected_scale > 0 and detected_scale != self._calibrated_scale_um_per_px:
                    self._calibrated_scale_um_per_px = detected_scale
                    self._manual_overlay_panel.set_scale(detected_scale)
                    if self.app_state.mode == Mode.MANUAL:
                        self._recompute_pitch_overlay()

            self.pitch_actual.setText(f"{result.mean_pitch_um:.2f} μm")

            target_um = 1000.0
            error_pct = abs((result.mean_pitch_um - target_um) / target_um * 100)
            self.pitch_error.setText(f"{error_pct:.1f}%")

            if self._is_running:
                self.graph.add_point(self._distance, result.mean_pitch_um / 1000.0)

            confidence_colors = {
                "HIGH": "success",
                "MEDIUM": "info",
                "LOW": "warning",
                "FAILED": "error",
            }
            self.alert_log.log(
                f"Pitch: {result.mean_pitch_um:.1f}μm ({result.num_wraps} wraps), "
                f"Confidence: {result.confidence}",
                confidence_colors.get(result.confidence, "info"),
            )

            if result.confidence in ("LOW", "FAILED"):
                self._auto_capture(
                    alert_type=f"low_confidence_{result.confidence.lower()}",
                    confidence=result.confidence,
                    pitch_um=result.mean_pitch_um,
                )
        except Exception as e:
            self.alert_log.log(f"Error processing pitch result: {e}", "error")

    def _on_manual_mode(self, confidence: str) -> None:
        """Manual mode auto-triggered by low confidence from vision pipeline.

        Both AppState (canonical) and the legacy SetpointController need
        updating: AppState so `mode_changed` fires and the overlay /
        calibration panel show; the legacy controller because it owns the
        ack-required flag that gates the banner."""
        self.app_state.gui_set_mode(Mode.MANUAL)
        self.controller.trigger_manual_from_low_confidence()

        if self.manual_banner is None:
            self.manual_banner = ManualModeBanner(self)
            self.manual_banner.setParent(self.centralWidget())
            self.manual_banner.setGeometry(24, 24, self.width() - 48, 60)
            self.manual_banner.acknowledged.connect(self._on_manual_mode_acknowledged)

        self.manual_banner.show_banner()
        self.alert_log.log(
            f"Manual mode auto-triggered — confidence: {confidence}. "
            "Adjust alignment/focus and set speeds manually.",
            "warning",
        )
        self._auto_capture(alert_type="manual_mode_trigger", confidence=confidence)

    def _on_manual_mode_acknowledged(self) -> None:
        self.controller.acknowledge_manual_mode()
        self.alert_log.log("Manual mode acknowledged — continuing operation", "info")

    # ------------------------------------------------------------------
    # Snapshot / recording / calibration reset
    # ------------------------------------------------------------------

    def _on_set_snapshot_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Default Snapshot Folder",
            self._snapshot_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._snapshot_dir = folder
            self.alert_log.log(f"Default snapshot folder set to: {folder}", "info")

    def _on_snapshot(self) -> None:
        pixmap = self.camera._display_pixmap
        if pixmap is None or pixmap.isNull():
            self.alert_log.log("No camera frame to capture", "warning")
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"snapshot_{ts}.png"
        default_path = os.path.join(self._snapshot_dir, default_name)

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Snapshot",
            default_path,
            "PNG Images (*.png);;JPEG Images (*.jpg *.jpeg);;All Files (*)",
        )
        if not file_path:
            return

        if pixmap.save(file_path):
            self.alert_log.log(
                f"{os.path.basename(file_path)} saved! — location: {os.path.dirname(file_path)}",
                "success",
            )
            self._snapshot_dir = os.path.dirname(file_path)
        else:
            self.alert_log.log(f"Failed to save snapshot to {file_path}", "error")

    def _on_recalibrate(self) -> None:
        self.camera.h_offset = 0
        self.camera.v_offset = 0
        self.camera.update()
        self._distance = 0
        self.graph.clear()
        self.alert_log.log("Calibration reset - crosshair centered", "info")

    def _on_position_changed(self, x: int, y: int) -> None:
        if abs(x) > 50 or abs(y) > 50:
            self.alert_log.log(f"Large offset detected: ({x}, {y})", "warning")

    def _on_save_recording(self) -> None:
        if self.rolling_buffer.frame_count == 0:
            self.alert_log.log("No frames in buffer yet — nothing to save", "warning")
            return

        path = self.storage.timestamped_path(
            self.storage.recordings_dir, "recording", "mp4"
        )
        dur = self.rolling_buffer.duration_seconds
        self.alert_log.log(
            f"Saving recording ({dur:.0f}s, {self.rolling_buffer.frame_count} frames)...",
            "info",
        )

        if self.rolling_buffer.save(path):
            self.alert_log.log(f"Recording saved: {path.name}", "success")
        else:
            self.alert_log.log("Recording save failed (cv2 or no frames)", "error")

    def _auto_capture(
        self,
        alert_type: str,
        confidence: Optional[str] = None,
        pitch_um: Optional[float] = None,
    ) -> None:
        """Save a screenshot + alert-log entry for a significant event."""
        frame = self._current_raw_frame
        if frame is None:
            return

        prefix = f"auto_{alert_type.lower().replace(' ', '_')}"
        screenshot_path = self.storage.save_screenshot(frame, prefix=prefix)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "alert_type": alert_type,
            "confidence": confidence,
            "pitch_um": pitch_um,
            "active_camera": self._active_camera,
            "screenshot": str(screenshot_path) if screenshot_path else None,
        }
        self.storage.save_alert_entry(entry)

    # ------------------------------------------------------------------
    # Styles + lifecycle
    # ------------------------------------------------------------------

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {Theme.BG_PRIMARY};
            }}
            QWidget {{
                color: {Theme.TEXT_PRIMARY};
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }}
            QLabel {{
                background: transparent;
            }}
            QMenuBar {{
                background-color: {Theme.BG_SECONDARY};
                color: {Theme.TEXT_PRIMARY};
                border-bottom: 1px solid {Theme.BORDER};
                padding: 2px 0px;
                font-size: 13px;
            }}
            QMenuBar::item {{
                padding: 6px 14px;
                border-radius: 4px;
            }}
            QMenuBar::item:selected {{
                background-color: {Theme.BG_HOVER};
            }}
            QMenu {{
                background-color: {Theme.BG_CARD};
                color: {Theme.TEXT_PRIMARY};
                border: 1px solid {Theme.BORDER};
                border-radius: 8px;
                padding: 6px 0px;
            }}
            QMenu::item {{
                padding: 8px 30px 8px 20px;
            }}
            QMenu::item:selected {{
                background-color: {Theme.BG_HOVER};
                color: {Theme.ACCENT_PRIMARY};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {Theme.BORDER};
                margin: 4px 12px;
            }}
        """)

    def closeEvent(self, event):
        if self._primary_worker:
            self._primary_worker.stop()
        if self._secondary_worker:
            self._secondary_worker.stop()
        self.pitch_pipeline.stop()
        self.storage.shutdown()
        try:
            self.pui_listener.stop()
        except Exception:
            pass
        try:
            self.wrap_motor_controller.close()
            self.feed_motor_controller.close()
        except Exception:
            pass
        try:
            self.transport.close()
        except Exception:
            pass
        event.accept()
