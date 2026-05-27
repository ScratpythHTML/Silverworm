"""
Tests for aspect ratio preservation and letterboxing/pillarboxing.

Validates that camera frames are displayed without stretching and that
geometry calculations are correct.
"""

import pytest
from PyQt6.QtCore import QRectF
from ui.camera_widget import EnhancedCameraView
import numpy as np


def test_letterbox_wide_frame(qapp, sample_frame_hd):
    """Test letterboxing for wide aspect ratio frame"""
    widget = EnhancedCameraView()
    widget.resize(800, 600)  # 4:3 widget

    # 16:9 frame (wider than widget)
    widget.update_frame(sample_frame_hd)

    # Should have black bars on top/bottom (full width, less height)
    assert abs(widget._display_rect.width() - widget.width()) < 1
    assert widget._display_rect.height() < widget.height()
    assert widget._display_rect.y() > 0  # Offset from top


def test_pillarbox_tall_frame(qapp):
    """Test pillarboxing for tall aspect ratio frame"""
    widget = EnhancedCameraView()
    widget.resize(800, 600)  # 4:3 widget

    # Vertical frame (taller than widget)
    tall_frame = np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8)
    widget.update_frame(tall_frame)

    # Should have black bars on sides (full height, less width)
    assert abs(widget._display_rect.height() - widget.height()) < 1
    assert widget._display_rect.width() < widget.width()
    assert widget._display_rect.x() > 0  # Offset from left


def test_aspect_ratio_preserved(qapp, sample_frame):
    """Test that aspect ratio is exactly preserved"""
    widget = EnhancedCameraView()
    widget.resize(800, 600)

    widget.update_frame(sample_frame)

    frame_aspect = 640 / 480
    display_aspect = widget._display_rect.width() / widget._display_rect.height()

    # Aspect ratios should match within tolerance
    assert abs(frame_aspect - display_aspect) < 0.01


def test_resize_recalculates_rect(qapp, sample_frame_hd):
    """Test that display rect is calculated correctly after resize"""
    widget = EnhancedCameraView()
    widget.update_frame(sample_frame_hd)

    # Initial size
    widget.resize(800, 600)
    assert widget._display_rect.width() > 0
    assert widget._display_rect.height() > 0

    # Resize to different aspect ratio
    widget.resize(1600, 900)

    # Display rect should still be valid and within bounds
    assert widget._display_rect.width() > 0
    assert widget._display_rect.width() <= 1600
    assert widget._display_rect.height() > 0
    assert widget._display_rect.height() <= 900


def test_demo_mode_to_live_mode(qapp, sample_frame):
    """Test transition from demo mode to live camera mode"""
    widget = EnhancedCameraView()

    # Initially in demo mode
    assert widget._demo_mode is True

    # Update with frame
    widget.update_frame(sample_frame)

    # Should exit demo mode
    assert widget._demo_mode is False
    assert widget._display_pixmap is not None


def test_none_frame_handling(qapp):
    """Test handling of None frames"""
    widget = EnhancedCameraView()

    # Should not crash
    widget.update_frame(None)
    assert widget._demo_mode is True


def test_empty_frame_handling(qapp):
    """Test handling of empty frames"""
    widget = EnhancedCameraView()

    empty_frame = np.array([])
    widget.update_frame(empty_frame)

    # Should remain in demo mode
    assert widget._demo_mode is True
