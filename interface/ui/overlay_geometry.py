"""
Pitch overlay geometry — pure functions, no Qt dependency.

Geometry assumption:
  The spool is always oriented HORIZONTALLY in the camera frame.
  Wire wraps appear as nearly-vertical lines with a slight tilt from vertical.
  The tilt is the helix advance angle θ = arctan(P / π(D + 2t)), calculated
  by config.calculate_wrap_angle_deg().

  θ = 0°  → perfectly circumferential wind → perfectly vertical lines
  θ > 0°  → helix advances along tube → lines tilt θ degrees from vertical

  This is NOT the same as the texture/thread angle detected by pitch_estimate.py,
  which measures an arbitrary tube orientation in the image.
"""
from __future__ import annotations

import math
from typing import List, Tuple


def pitch_overlay_lines(
    spacing_px: float,
    tilt_from_vertical_deg: float,
    width: int,
    height: int,
) -> List[Tuple[int, int, int, int]]:
    """Return (x1, y1, x2, y2) tuples for pitch reference lines.

    Lines are drawn at *tilt_from_vertical_deg* from vertical (nearly vertical
    for typical fine-wire windings).  Adjacent lines are spaced *spacing_px*
    apart measured horizontally (= along the horizontal tube axis).

    tilt_from_vertical_deg  comes from config.calculate_wrap_angle_deg().
    spacing_px              = target_pitch_um / scale_um_per_px.

    Returns an empty list when spacing_px <= 0 or the widget has no area.
    """
    if spacing_px <= 0 or width <= 0 or height <= 0:
        return []

    tilt = math.radians(tilt_from_vertical_deg)

    # Line direction unit vector — tilt_from_vertical_deg from vertical.
    # (0, 1) is straight down; positive tilt rotates clockwise.
    lx = math.sin(tilt)
    ly = math.cos(tilt)

    # Spacing direction — perpendicular to line direction = along tube axis.
    # For small tilt this is nearly horizontal (1, 0).
    sx = math.cos(tilt)
    sy = -math.sin(tilt)

    cx = width / 2.0
    cy = height / 2.0
    diag = math.hypot(width, height)
    n = int(diag / spacing_px) + 2

    lines: List[Tuple[int, int, int, int]] = []
    for k in range(-n, n + 1):
        ox = cx + k * spacing_px * sx
        oy = cy + k * spacing_px * sy
        lines.append((
            int(ox - diag * lx),
            int(oy - diag * ly),
            int(ox + diag * lx),
            int(oy + diag * ly),
        ))
    return lines
