"""
Reusable visual primitives used by the Silverworm GUI.

These are generic — no hardware or app-state knowledge. Larger composite
panels (motor metrics, alert log, pitch graph) build on top of them.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtProperty, QPointF,
)
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QPen, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QPushButton, QFrame, QLabel, QWidget, QGraphicsDropShadowEffect,
)

from ui.theme import Theme


class AnimatedButton(QPushButton):
    """Button with hover animations and glow effects."""

    def __init__(self, text: str, color: str, glow_color: str, parent=None):
        super().__init__(text, parent)
        self.base_color = color
        self.glow_color = glow_color
        self._glow_intensity = 0

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        self.setMinimumHeight(44)

        self._update_style()

        self._glow_anim = QPropertyAnimation(self, b"glowIntensity")
        self._glow_anim.setDuration(200)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    @pyqtProperty(int)
    def glowIntensity(self):
        return self._glow_intensity

    @glowIntensity.setter
    def glowIntensity(self, value):
        self._glow_intensity = value
        self._update_shadow()

    def _update_style(self):
        text_color = "#000000" if self.base_color in (Theme.SUCCESS, Theme.WARNING) else "#ffffff"
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.base_color};
                color: {text_color};
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {self._lighten_color(self.base_color, 15)};
            }}
            QPushButton:pressed {{
                background-color: {self._darken_color(self.base_color, 10)};
            }}
            QPushButton:disabled {{
                background-color: {Theme.BG_SECONDARY};
                color: {Theme.TEXT_DISABLED};
            }}
        """)

    def _update_shadow(self):
        if self._glow_intensity > 0:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(self._glow_intensity)
            shadow.setColor(QColor(self.glow_color))
            shadow.setOffset(0, 0)
            self.setGraphicsEffect(shadow)
        else:
            self.setGraphicsEffect(None)

    def enterEvent(self, event):
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow_intensity)
        self._glow_anim.setEndValue(25)
        self._glow_anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow_intensity)
        self._glow_anim.setEndValue(0)
        self._glow_anim.start()
        super().leaveEvent(event)

    @staticmethod
    def _lighten_color(hex_color: str, percent: int) -> str:
        color = QColor(hex_color)
        h, s, l, a = color.getHsl()
        l = min(255, l + int(255 * percent / 100))
        color.setHsl(h, s, l, a)
        return color.name()

    @staticmethod
    def _darken_color(hex_color: str, percent: int) -> str:
        color = QColor(hex_color)
        h, s, l, a = color.getHsl()
        l = max(0, l - int(255 * percent / 100))
        color.setHsl(h, s, l, a)
        return color.name()


class GlowingCard(QFrame):
    """Card widget with subtle glow on hover."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            GlowingCard {{
                background-color: {Theme.BG_CARD};
                border: 1px solid {Theme.BORDER};
                border-radius: 12px;
            }}
            GlowingCard:hover {{
                border-color: {Theme.BORDER_LIGHT};
            }}
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)


class PulsingIndicator(QWidget):
    """Animated pulsing status indicator (dot with halo)."""

    def __init__(self, color: str = Theme.SUCCESS, parent=None):
        super().__init__(parent)
        self.color = color
        self._pulse = 0
        self.setFixedSize(12, 12)

        self._anim = QPropertyAnimation(self, b"pulse")
        self._anim.setDuration(1500)
        self._anim.setStartValue(0)
        self._anim.setEndValue(100)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)

    def start(self):
        self._anim.start()

    def stop(self):
        self._anim.stop()
        self._pulse = 0
        self.update()

    @pyqtProperty(int)
    def pulse(self):
        return self._pulse

    @pulse.setter
    def pulse(self, value):
        self._pulse = value
        self.update()

    def set_color(self, color: str):
        self.color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.rect().center())

        if self._pulse > 0:
            glow_alpha = int(50 * (1 - self._pulse / 100))
            glow_size = 6 + int(6 * self._pulse / 100)

            gradient = QRadialGradient(center, glow_size)
            glow_color = QColor(self.color)
            glow_color.setAlpha(glow_alpha)
            gradient.setColorAt(0, glow_color)
            glow_color.setAlpha(0)
            gradient.setColorAt(1, glow_color)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(center, glow_size, glow_size)

        painter.setBrush(QColor(self.color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, 5, 5)

        painter.end()


class AnimatedMetricValue(QLabel):
    """QLabel that animates value changes towards a target."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_value = 0.0
        self._target_value = 0.0
        self._unit = ""
        self._decimals = 1

        self.setFont(QFont("Consolas", 18, QFont.Weight.Bold))

        self._anim_timer = QTimer()
        self._anim_timer.setInterval(16)  # ~60fps
        self._anim_timer.timeout.connect(self._animate_step)

    def set_value(self, value: float, unit: str = "", decimals: int = 1, animate: bool = True):
        self._target_value = value
        self._unit = unit
        self._decimals = decimals

        if animate and abs(self._target_value - self._current_value) > 0.01:
            self._anim_timer.start()
        else:
            self._current_value = value
            self._update_display()

    def _animate_step(self):
        diff = self._target_value - self._current_value
        step = diff * 0.15

        if abs(diff) < 0.01:
            self._current_value = self._target_value
            self._anim_timer.stop()
        else:
            self._current_value += step

        self._update_display()

    def _update_display(self):
        self.setText(f"{self._current_value:.{self._decimals}f} {self._unit}")
