"""
Enhanced camera view widget with real camera feed support.

Displays camera frames with construction lines overlay, ROI markers, and
aspect ratio preservation (letterbox/pillarbox).
"""

from PyQt6.QtWidgets import QFrame, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRectF, QPoint
from PyQt6.QtGui import (
    QPainter, QImage, QPixmap, QColor, QPen, QBrush,
    QLinearGradient, QRadialGradient, QFont, QKeyEvent
)
import math
import numpy as np
from typing import Optional
import random
import cv2

from .overlay_geometry import pitch_overlay_lines


class EnhancedCameraView(QFrame):
    """
    Enhanced camera view widget.

    Features:
    - Real camera feed OR demo mode (animated placeholder)
    - Construction lines overlay with keyboard control
    - ROI box with corner brackets
    - Aspect ratio preservation (letterbox/pillarbox, no stretching)
    - Thread-safe frame updates via signal/slot
    - Temporary overlay messages (e.g. "Motor speed set!")
    """

    position_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Camera frame display
        self._current_frame: Optional[np.ndarray] = None  # BGR format
        self._display_pixmap: Optional[QPixmap] = None
        self._display_rect = QRectF()  # Where to draw frame (letterboxed)

        # Construction lines (crosshair) - user adjustable
        self.h_offset = 0  # Horizontal line offset
        self.v_offset = 0  # Vertical line offset

        # ROI parameters
        self.roi_width = 400
        self.roi_height = 250

        # Pitch overlay (manual mode reference lines)
        self._pitch_overlay_enabled: bool = False
        self._pitch_spacing_px: float = 0.0
        self._pitch_tilt_from_vertical_deg: float = 0.0

        # Overlay message (temporary toast shown over camera feed)
        self._overlay_text: Optional[str] = None
        self._overlay_timer = QTimer()
        self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._clear_overlay)

        # Demo mode (when no camera)
        self._demo_mode = True
        self._noise_phase = 0
        self._scanline_y = 0

        self._demo_timer = QTimer()
        self._demo_timer.timeout.connect(self._update_demo_animation)
        self._demo_timer.start(50)

        self._setup_style()

    # ------------------------------------------------------------------
    # Pitch overlay (manual mode)
    # ------------------------------------------------------------------

    def set_pitch_overlay(self, spacing_px: float, tilt_from_vertical_deg: float) -> None:
        """Draw pitch reference lines for manual mode.

        spacing_px             — target pitch in pixels (target_pitch_um / scale_um_per_px).
        tilt_from_vertical_deg — helix advance angle from config.calculate_wrap_angle_deg().
                                 Lines are nearly vertical; this is the slight tilt from
                                 vertical caused by the helix winding on a horizontal spool.
        """
        self._pitch_spacing_px = max(1.0, spacing_px)
        self._pitch_tilt_from_vertical_deg = tilt_from_vertical_deg
        self._pitch_overlay_enabled = True
        self.update()

    def clear_pitch_overlay(self) -> None:
        """Remove pitch reference lines (called when leaving manual mode)."""
        self._pitch_overlay_enabled = False
        self.update()

    # ------------------------------------------------------------------

    def _setup_style(self):
        """Apply widget styling"""
        self.setStyleSheet("""
            EnhancedCameraView {
                background-color: #000000;
                border: 2px solid #2d3748;
                border-radius: 8px;
            }
            EnhancedCameraView:focus {
                border-color: #00d4aa;
            }
        """)

    def update_frame(self, frame: np.ndarray):
        """
        Thread-safe frame update (called from main thread via signal/slot).

        Args:
            frame: BGR numpy array from camera worker
        """
        if frame is None or frame.size == 0:
            return

        # Convert BGR to RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Create QImage
        h, w, ch = rgb_frame.shape
        bytes_per_line = ch * w
        q_image = QImage(
            rgb_frame.data,
            w, h,
            bytes_per_line,
            QImage.Format.Format_RGB888
        )

        # Convert to pixmap
        self._display_pixmap = QPixmap.fromImage(q_image.copy())

        # Disable demo mode
        if self._demo_mode:
            self._demo_mode = False
            self._demo_timer.stop()

        # Calculate display rect (letterbox/pillarbox)
        self._calculate_display_rect()

        # Trigger repaint
        self.update()

    def _calculate_display_rect(self):
        """
        Calculate letterbox/pillarbox rectangle to preserve aspect ratio.

        Updates self._display_rect with the rectangle where the frame should
        be drawn, adding black bars (letterbox/pillarbox) as needed.
        """
        if not self._display_pixmap:
            return

        widget_rect = self.rect()
        pixmap_size = self._display_pixmap.size()

        # Calculate aspect ratios
        widget_aspect = widget_rect.width() / widget_rect.height()
        pixmap_aspect = pixmap_size.width() / pixmap_size.height()

        if pixmap_aspect > widget_aspect:
            # Pillarbox (black bars on top/bottom)
            display_width = widget_rect.width()
            display_height = display_width / pixmap_aspect
            x = 0
            y = (widget_rect.height() - display_height) / 2
        else:
            # Letterbox (black bars on sides)
            display_height = widget_rect.height()
            display_width = display_height * pixmap_aspect
            x = (widget_rect.width() - display_width) / 2
            y = 0

        self._display_rect = QRectF(x, y, display_width, display_height)

    def _update_demo_animation(self):
        """Update demo mode animation (when no camera)"""
        self._noise_phase = (self._noise_phase + 1) % 1000
        self._scanline_y = (self._scanline_y + 2) % (self.height() + 20)
        self.update()

    def show_overlay_message(self, text: str, duration_ms: int = 3000):
        """
        Show a temporary message overlaid on the camera feed.

        The message appears as a banner near the top of the camera view and
        auto-hides after duration_ms milliseconds.
        """
        self._overlay_text = text
        self._overlay_timer.start(duration_ms)
        self.update()

    def _clear_overlay(self):
        self._overlay_text = None
        self.update()

    def resizeEvent(self, event):
        """Recalculate display rect on resize"""
        super().resizeEvent(event)
        if self._display_pixmap:
            self._calculate_display_rect()

    def keyPressEvent(self, event: QKeyEvent):
        """Move construction lines with arrow keys"""
        step = 5 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1

        moved = True
        if event.key() == Qt.Key.Key_Up:
            self.h_offset -= step
        elif event.key() == Qt.Key.Key_Down:
            self.h_offset += step
        elif event.key() == Qt.Key.Key_Left:
            self.v_offset -= step
        elif event.key() == Qt.Key.Key_Right:
            self.v_offset += step
        else:
            moved = False
            super().keyPressEvent(event)

        if moved:
            self.position_changed.emit(self.v_offset, self.h_offset)
            self.update()

    def paintEvent(self, event):
        """Paint camera frame + overlays"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()

        # Draw camera frame or demo mode
        if self._demo_mode:
            self._paint_demo_mode(painter, rect)
        else:
            self._paint_camera_frame(painter)

        # Draw overlays on top (construction lines, ROI)
        self._paint_overlays(painter, rect)

        # Draw temporary overlay message (e.g. "Motor speed set!")
        if self._overlay_text:
            self._paint_overlay_message(painter, rect)

        painter.end()

    def _paint_camera_frame(self, painter: QPainter):
        """Paint actual camera frame"""
        if self._display_pixmap and not self._display_pixmap.isNull():
            painter.drawPixmap(self._display_rect.toRect(), self._display_pixmap)

    def _paint_demo_mode(self, painter: QPainter, rect):
        """Paint demo mode animation (shown when no camera available)"""
        # Background gradient
        gradient = QLinearGradient(0, 0, 0, rect.height())
        gradient.setColorAt(0, QColor("#0a0a0a"))
        gradient.setColorAt(0.5, QColor("#050505"))
        gradient.setColorAt(1, QColor("#0a0a0a"))
        painter.fillRect(rect, gradient)

        # Animated noise
        random.seed(self._noise_phase)
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(150):
            x = random.randint(0, rect.width())
            y = random.randint(0, rect.height())
            intensity = random.randint(8, 25)
            size = random.randint(1, 3)
            painter.setBrush(QColor(intensity, intensity, intensity))
            painter.drawRect(x, y, size, size)

        # Scanline effect
        scanline_gradient = QLinearGradient(
            0, self._scanline_y - 10,
            0, self._scanline_y + 10
        )
        scanline_gradient.setColorAt(0, QColor(0, 212, 170, 0))
        scanline_gradient.setColorAt(0.5, QColor(0, 212, 170, 30))
        scanline_gradient.setColorAt(1, QColor(0, 212, 170, 0))
        painter.fillRect(0, self._scanline_y - 10, rect.width(), 20, scanline_gradient)

        # "No Signal" text
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.setPen(QColor("#5c6470"))
        text = "⬤ AWAITING CAMERA SIGNAL"
        tr = painter.fontMetrics().boundingRect(text)
        painter.drawText(rect.width()//2 - tr.width()//2, 35, text)

    def _paint_overlays(self, painter: QPainter, rect):
        """
        Paint overlays (construction lines, ROI, position display).

        Coordinates are mapped to widget space, accounting for letterboxing.
        """
        cx, cy = rect.width() // 2, rect.height() // 2

        # Pitch overlay — lines perpendicular to thread axis, spaced by target pitch
        if self._pitch_overlay_enabled and self._pitch_spacing_px > 0:
            pen = QPen(QColor(0, 212, 170, 160))
            pen.setWidth(1)
            painter.setPen(pen)
            for x1, y1, x2, y2 in pitch_overlay_lines(
                self._pitch_spacing_px,
                self._pitch_tilt_from_vertical_deg,
                int(rect.width()),
                int(rect.height()),
            ):
                painter.drawLine(x1, y1, x2, y2)

        # ROI box
        roi_x = cx - self.roi_width // 2
        roi_y = cy - self.roi_height // 2

        # ROI fill
        roi_fill = QColor(0, 212, 170, 12)
        painter.fillRect(roi_x, roi_y, self.roi_width, self.roi_height, roi_fill)

        # ROI border
        pen = QPen(QColor("#00d4aa"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(roi_x, roi_y, self.roi_width, self.roi_height)

        # Corner brackets
        corner_len = 20
        pen.setWidth(3)
        painter.setPen(pen)

        corners = [
            (roi_x, roi_y, 1, 1),
            (roi_x + self.roi_width, roi_y, -1, 1),
            (roi_x, roi_y + self.roi_height, 1, -1),
            (roi_x + self.roi_width, roi_y + self.roi_height, -1, -1)
        ]

        for x, y, dx, dy in corners:
            painter.drawLine(x, y, x + corner_len * dx, y)
            painter.drawLine(x, y, x, y + corner_len * dy)

        # Construction lines (crosshair)
        h_y = cy + self.h_offset
        v_x = cx + self.v_offset

        pen = QPen(QColor("#00cec9"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(0, h_y, rect.width(), h_y)
        painter.drawLine(v_x, 0, v_x, rect.height())

        # Center indicator
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(v_x, h_y), 10, 10)
        painter.drawEllipse(QPoint(v_x, h_y), 3, 3)

        # Position display
        font = QFont("Consolas", 10)
        painter.setFont(font)

        offset_text = f"X: {self.v_offset:+d}  Y: {self.h_offset:+d}"
        text_rect = painter.fontMetrics().boundingRect(offset_text)

        text_x = v_x + 18
        text_y = h_y - 18

        # Ensure text stays in bounds
        if text_x + text_rect.width() + 10 > rect.width():
            text_x = v_x - text_rect.width() - 25
        if text_y < 20:
            text_y = h_y + 30

        # Text background
        bg_rect = QRectF(
            text_x - 8, text_y - text_rect.height() - 4,
            text_rect.width() + 16, text_rect.height() + 8
        )
        painter.fillRect(bg_rect, QColor(0, 0, 0, 200))
        painter.setPen(QColor("#00cec9"))
        painter.drawText(text_x, text_y, offset_text)

        # Focus glow
        if self.hasFocus():
            glow_pen = QPen(QColor("#00d4aa"))
            glow_pen.setWidth(3)
            painter.setPen(glow_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)

    def _paint_overlay_message(self, painter: QPainter, rect):
        """Paint a temporary toast-style message banner near the top of the view."""
        painter.save()

        text = self._overlay_text
        font = QFont("Segoe UI", 13, QFont.Weight.DemiBold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(text)
        text_height = fm.height()

        # Banner dimensions
        padding_h = 24
        padding_v = 12
        banner_w = text_width + padding_h * 2
        banner_h = text_height + padding_v * 2
        banner_x = (rect.width() - banner_w) // 2
        banner_y = 50  # Near top, below the "no signal" area

        # Background with rounded corners and semi-transparency
        banner_rect = QRectF(banner_x, banner_y, banner_w, banner_h)
        painter.setPen(QPen(QColor("#00d4aa"), 2))
        painter.setBrush(QColor(10, 14, 20, 220))
        painter.drawRoundedRect(banner_rect, 10, 10)

        # Green accent bar on left edge
        accent_rect = QRectF(banner_x, banner_y, 4, banner_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#00d4aa"))
        painter.drawRoundedRect(accent_rect, 2, 2)

        # Text
        painter.setPen(QColor("#00d4aa"))
        painter.drawText(
            int(banner_x + padding_h),
            int(banner_y + padding_v + fm.ascent()),
            text,
        )

        painter.restore()
