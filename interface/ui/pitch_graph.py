"""Pitch history graph widget — rolling distance/pitch plot."""

from __future__ import annotations

from typing import List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPainter, QColor, QPen, QPainterPath
from PyQt6.QtWidgets import QVBoxLayout, QLabel, QWidget

from ui.theme import Theme
from ui.widgets import GlowingCard


class PitchGraph(GlowingCard):
    """Enhanced pitch history graph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)

        self.data: List[Tuple[float, float]] = []
        self.max_points = 100
        self.max_distance = 500

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QLabel("Pitch History")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {Theme.ACCENT_PRIMARY};")
        layout.addWidget(header)

        self.canvas = QWidget()
        self.canvas.setMinimumHeight(160)
        layout.addWidget(self.canvas, 1)

    def add_point(self, distance: float, pitch: float):
        self.data.append((distance, pitch))
        if len(self.data) > self.max_points:
            self.data.pop(0)
        self.update()

    def clear(self):
        self.data.clear()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = 24
        header_h = 50
        graph = self.rect().adjusted(margin + 30, header_h, -margin, -margin - 20)

        if graph.width() < 50 or graph.height() < 50:
            painter.end()
            return

        painter.fillRect(graph, QColor(Theme.BG_SECONDARY))

        pen = QPen(QColor(Theme.BORDER))
        pen.setWidth(1)
        painter.setPen(pen)
        for i in range(6):
            x = graph.left() + graph.width() * i // 5
            painter.drawLine(x, graph.top(), x, graph.bottom())
        for i in range(5):
            y = graph.top() + graph.height() * i // 4
            painter.drawLine(graph.left(), y, graph.right(), y)

        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QColor(Theme.TEXT_MUTED))
        for i in range(6):
            x = graph.left() + graph.width() * i // 5
            painter.drawText(x - 12, graph.bottom() + 15, f"{int(self.max_distance * i / 5)}")
        for i in range(5):
            y = graph.bottom() - graph.height() * i // 4
            painter.drawText(graph.left() - 28, y + 4, f"{i * 0.5:.1f}")

        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(graph.center().x() - 35, graph.bottom() + 32, "Distance (mm)")
        painter.save()
        painter.translate(graph.left() - 50, graph.center().y() + 35)
        painter.rotate(-90)
        painter.drawText(0, 0, "Pitch (mm)")
        painter.restore()

        if len(self.data) > 1:
            path = QPainterPath()
            first = True
            for dist, pitch in self.data:
                x = graph.left() + (dist / self.max_distance) * graph.width()
                y = graph.bottom() - (pitch / 2.0) * graph.height()
                x = max(graph.left(), min(graph.right(), x))
                y = max(graph.top(), min(graph.bottom(), y))
                if first:
                    path.moveTo(x, y)
                    first = False
                else:
                    path.lineTo(x, y)

            glow_pen = QPen(QColor(Theme.ACCENT_PRIMARY))
            glow_pen.setWidth(6)
            painter.setPen(glow_pen)
            painter.setOpacity(0.3)
            painter.drawPath(path)

            painter.setOpacity(1.0)
            pen = QPen(QColor(Theme.ACCENT_PRIMARY))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawPath(path)

        if not self.data:
            painter.setFont(QFont("Segoe UI", 11))
            painter.setPen(QColor(Theme.TEXT_MUTED))
            text = "Awaiting pitch data..."
            tr = painter.fontMetrics().boundingRect(text)
            painter.drawText(graph.center().x() - tr.width() // 2, graph.center().y(), text)

        painter.setPen(QPen(QColor(Theme.BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(graph)
        painter.end()
