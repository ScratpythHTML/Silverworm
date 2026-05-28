"""
Manual mode UI components.

Provides banner and modal dialog for manual mode alerts when pitch detection
confidence is low.
"""

from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QFont


class ManualModeBanner(QFrame):
    """
    Non-blocking banner that appears when manual mode is triggered.

    Slides down from top of parent widget. User must click "OK" to acknowledge.
    Does not block the UI - user can continue working.
    """

    acknowledged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setStyleSheet("""
            ManualModeBanner {
                background-color: #ff6b6b;
                border: 2px solid #ff8888;
                border-radius: 8px;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)

        # Warning icon
        icon = QLabel("⚠")
        icon.setFont(QFont("Segoe UI", 20))
        icon.setStyleSheet("color: white;")
        layout.addWidget(icon)

        # Message
        message = QLabel("MANUAL MODE ENABLED – Please adjust alignment/focus")
        message.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        message.setStyleSheet("color: white;")
        layout.addWidget(message, 1)

        # OK button
        ok_btn = QPushButton("OK")
        ok_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        ok_btn.setFixedSize(80, 40)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: white;
                color: #ff6b6b;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #f0f0f0;
            }
            QPushButton:pressed {
                background-color: #e0e0e0;
            }
        """)
        ok_btn.clicked.connect(self._on_acknowledged)
        layout.addWidget(ok_btn)

        # Start hidden
        self.hide()

    def show_banner(self):
        """Show banner with slide-down animation"""
        self.show()
        self.raise_()  # Bring to front

        # Note: Animation would need proper positioning setup in parent
        # For simplicity, just show without animation for now
        # A full implementation would use QPropertyAnimation on geometry

    def _on_acknowledged(self):
        """User clicked OK"""
        self.hide()
        self.acknowledged.emit()


class ManualModeDialog(QDialog):
    """
    Modal dialog for manual mode (blocks UI until acknowledged).

    Alternative to ManualModeBanner if blocking behavior is desired.
    Shows detailed message and requires user acknowledgement before continuing.
    """

    def __init__(self, confidence: str = "LOW", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Mode Required")
        self.setModal(True)
        self.setFixedSize(400, 220)

        # Remove window frame decorations for modern look
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint
        )

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Apply styling
        self.setStyleSheet("""
            QDialog {
                background-color: #151b23;
                border: 2px solid #ff6b6b;
                border-radius: 12px;
            }
        """)

        # Icon
        icon = QLabel("⚠")
        icon.setFont(QFont("Segoe UI", 48))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("color: #ff6b6b; background: transparent;")
        layout.addWidget(icon)

        # Title
        title = QLabel("Manual Mode Enabled")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #e6e6e6; background: transparent;")
        layout.addWidget(title)

        # Message
        msg = QLabel(
            f"Pitch detection confidence is {confidence}.\n"
            "Please adjust camera alignment and focus."
        )
        msg.setFont(QFont("Segoe UI", 11))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet("color: #8b949e; background: transparent;")
        layout.addWidget(msg)

        # OK button
        ok_btn = QPushButton("OK, I'll Adjust")
        ok_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        ok_btn.setFixedHeight(44)
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff6b6b;
                color: white;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #ff8888;
            }
            QPushButton:pressed {
                background-color: #ff5555;
            }
        """)
        ok_btn.clicked.connect(self.accept)
        layout.addWidget(ok_btn)

    def showEvent(self, event):
        """Center dialog on parent when shown"""
        super().showEvent(event)
        if self.parent():
            parent_rect = self.parent().geometry()
            dialog_rect = self.geometry()
            x = parent_rect.x() + (parent_rect.width() - dialog_rect.width()) // 2
            y = parent_rect.y() + (parent_rect.height() - dialog_rect.height()) // 2
            self.move(x, y)
