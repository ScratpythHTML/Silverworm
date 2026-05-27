"""
Tests for pitch overlay geometry and angle conventions.

Geometry:
  The spool is always horizontal in the camera frame.
  Wrap lines are nearly vertical, tilted by the helix advance angle θ.
  θ = arctan(P / π(D+2t)) from config.calculate_wrap_angle_deg().

  θ = 0°  → perfectly circumferential wind → perfectly vertical overlay lines
  θ > 0°  → helix advances along tube  → lines tilt θ degrees from vertical

  The helix advance angle is small (~1–5°) for typical fine-wire windings.
  It is measured from VERTICAL (not horizontal) when the spool is horizontal.
"""
import math
import pytest

from config import calculate_wrap_angle_deg
from ui.overlay_geometry import pitch_overlay_lines


# ---------------------------------------------------------------------------
# calculate_wrap_angle_deg — unit conversion and angle semantics
# ---------------------------------------------------------------------------

class TestCalculateWrapAngle:

    def test_converts_diameter_mm_to_um(self):
        # D=1 mm must be converted to 1000 µm before adding 2t.
        angle = calculate_wrap_angle_deg(target_pitch_um=1.0, tube_diameter_mm=1.0, wire_thickness_um=0.0)
        expected = math.degrees(math.atan(1.0 / (math.pi * 1000.0)))
        assert abs(angle - expected) < 1e-6

    def test_wire_thickness_applied_per_side(self):
        # d_effective = D + 2*t (wire adds a radius on each side of the tube centre).
        # D=0 mm, t=500 µm → d_effective = 1000 µm
        angle = calculate_wrap_angle_deg(target_pitch_um=1.0, tube_diameter_mm=0.0, wire_thickness_um=500.0)
        expected = math.degrees(math.atan(1.0 / (math.pi * 1000.0)))
        assert abs(angle - expected) < 1e-6

    def test_known_values_fine_wire(self):
        # P=500 µm, D=2 mm, t=100 µm → circumference = π*2200 µm
        angle = calculate_wrap_angle_deg(500.0, 2.0, 100.0)
        expected = math.degrees(math.atan(500.0 / (math.pi * 2200.0)))
        assert abs(angle - expected) < 1e-6
        assert 3.0 < angle < 6.0, f"Expected ~4.1°, got {angle:.2f}°"

    def test_angle_is_small_for_typical_winding(self):
        # The helix advance angle is always small (< ~15°) for normal windings.
        # It is the tilt from VERTICAL in the camera image, not from horizontal.
        angle = calculate_wrap_angle_deg(500.0, 2.0, 100.0)
        assert angle < 15.0

    def test_zero_effective_diameter_returns_zero(self):
        assert calculate_wrap_angle_deg(100.0, 0.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# pitch_overlay_lines — geometry
# ---------------------------------------------------------------------------

W, H = 640, 480


class TestPitchOverlayLines:

    def test_empty_for_zero_spacing(self):
        assert pitch_overlay_lines(0.0, 0.0, W, H) == []

    def test_empty_for_negative_spacing(self):
        assert pitch_overlay_lines(-10.0, 0.0, W, H) == []

    def test_empty_for_zero_width_or_height(self):
        assert pitch_overlay_lines(50.0, 0.0, 0, H) == []
        assert pitch_overlay_lines(50.0, 0.0, W, 0) == []

    def test_zero_tilt_gives_vertical_lines(self):
        # tilt=0° → perfectly circumferential wind → perfectly vertical lines.
        lines = pitch_overlay_lines(50.0, tilt_from_vertical_deg=0.0, width=W, height=H)
        assert lines
        for x1, y1, x2, y2 in lines:
            assert abs(x1 - x2) < 2, f"Expected vertical line, got ({x1},{y1})→({x2},{y2})"

    def test_zero_tilt_lines_span_full_height(self):
        lines = pitch_overlay_lines(50.0, 0.0, W, H)
        for x1, y1, x2, y2 in lines:
            assert abs(y2 - y1) > H

    def test_small_tilt_lines_are_nearly_vertical(self):
        # Typical helix angle ~1–5°: lines should remain nearly vertical.
        for tilt in (1.0, 2.5, 5.0):
            lines = pitch_overlay_lines(50.0, tilt, W, H)
            assert lines
            for x1, y1, x2, y2 in lines:
                dx = abs(x2 - x1)
                dy = abs(y2 - y1)
                assert dy > dx * 5, f"tilt={tilt}°: line not nearly vertical"

    def test_horizontal_spacing_matches_spacing_px(self):
        # With tilt=0°, lines are vertical; horizontal positions should be
        # spaced exactly spacing_px apart.
        spacing = 80.0
        lines = pitch_overlay_lines(spacing, 0.0, W, H)
        xs = sorted(set((x1 + x2) // 2 for x1, y1, x2, y2 in lines))
        gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        for gap in gaps:
            assert abs(gap - spacing) < 2.0, f"Horizontal gap {gap:.1f} ≠ {spacing}"

    def test_lines_extend_beyond_widget(self):
        # Every line must be long enough to cross the full widget diagonal.
        diag = math.hypot(W, H)
        lines = pitch_overlay_lines(50.0, 2.0, W, H)
        for x1, y1, x2, y2 in lines:
            length = math.hypot(x2 - x1, y2 - y1)
            assert length >= diag - 2

    def test_tilt_direction(self):
        # Positive tilt: the line should lean to the right as y increases
        # (lower end of line is to the right of the upper end).
        lines = pitch_overlay_lines(50.0, 5.0, W, H)
        cx_line = lines[len(lines) // 2]
        x1, y1, x2, y2 = cx_line
        # ensure y1 < y2 (top endpoint to bottom)
        if y1 > y2:
            x1, y1, x2, y2 = x2, y2, x1, y1
        assert x2 > x1, "Positive tilt should lean right going downward"


# ---------------------------------------------------------------------------
# End-to-end: helix angle from config drives overlay tilt
# ---------------------------------------------------------------------------

class TestHelixAngleDrivesOverlay:

    def test_helix_angle_produces_nearly_vertical_lines(self):
        # The full pipeline: compute tilt from config, check lines are nearly vertical.
        tilt = calculate_wrap_angle_deg(500.0, 2.0, 100.0)   # ~4.1°
        scale = 2.0  # µm/px (typical microscope)
        spacing_px = 500.0 / scale  # 250 px
        lines = pitch_overlay_lines(spacing_px, tilt, W, H)
        assert lines
        for x1, y1, x2, y2 in lines:
            dy = abs(y2 - y1)
            dx = abs(x2 - x1)
            assert dy > dx * 10, f"Line not nearly vertical: dy={dy}, dx={dx}"

    def test_larger_pitch_gives_wider_spacing(self):
        scale = 2.0
        tilt = calculate_wrap_angle_deg(500.0, 2.0, 100.0)
        lines_narrow = pitch_overlay_lines(100.0 / scale, tilt, W, H)
        lines_wide   = pitch_overlay_lines(500.0 / scale, tilt, W, H)
        # More lines needed for narrower spacing
        assert len(lines_narrow) > len(lines_wide)
