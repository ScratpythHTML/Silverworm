"""
Application configuration: dataclass, JSON load/save, derived quantities.

Config file lives in the OS-appropriate user config directory, resolved via
QStandardPaths.AppConfigLocation:
  - macOS:   ~/Library/Preferences/Silverworm/config.json
  - Linux:   ~/.config/Silverworm/config.json
  - Windows: %APPDATA%/Silverworm/config.json
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QStandardPaths


APP_NAME = "Silverworm"
CONFIG_FILENAME = "config.json"


@dataclass
class DetentConfig:
    """
    Per-dial speed increment for each detent size (small/medium/large).

    The PUI sends "D1±N" where N ∈ {1,2,3} selects the detent size and the
    sign selects the direction. Each (dial, size) maps to an increment here.
    """
    dial1_small_rpm: float = 0.1
    dial1_medium_rpm: float = 0.5
    dial1_large_rpm: float = 1.0
    dial2_small_mms: float = 0.01
    dial2_medium_mms: float = 0.05
    dial2_large_mms: float = 0.1


@dataclass
class AppConfig:
    target_pitch_um: float = 250.0
    wire_thickness_um: float = 100.0
    tube_diameter_mm: float = 5.0
    detent_config: DetentConfig = field(default_factory=DetentConfig)
    manual_mode_gui_enabled: bool = False
    remember_settings: bool = True
    scale_um_per_px: float = 0.0  # µm per pixel; 0 = not yet calibrated
    # "mock" = software-only (dev/macOS), "rpi5" = RPi 5 test rig, "cm5" = CM5 production
    hw_platform: str = "mock"

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        detent_raw = data.get("detent_config", {}) or {}
        detent = DetentConfig(
            dial1_small_rpm=float(detent_raw.get("dial1_small_rpm", 0.1)),
            dial1_medium_rpm=float(detent_raw.get("dial1_medium_rpm", 0.5)),
            dial1_large_rpm=float(detent_raw.get("dial1_large_rpm", 1.0)),
            dial2_small_mms=float(detent_raw.get("dial2_small_mms", 0.01)),
            dial2_medium_mms=float(detent_raw.get("dial2_medium_mms", 0.05)),
            dial2_large_mms=float(detent_raw.get("dial2_large_mms", 0.1)),
        )
        return cls(
            target_pitch_um=float(data.get("target_pitch_um", 250.0)),
            wire_thickness_um=float(data.get("wire_thickness_um", 100.0)),
            tube_diameter_mm=float(data.get("tube_diameter_mm", 5.0)),
            detent_config=detent,
            manual_mode_gui_enabled=bool(data.get("manual_mode_gui_enabled", False)),
            remember_settings=bool(data.get("remember_settings", True)),
            scale_um_per_px=float(data.get("scale_um_per_px", 0.0)),
            hw_platform=str(data.get("hw_platform", "mock")),
        )


def calculate_wrap_angle_deg(
    target_pitch_um: float,
    tube_diameter_mm: float,
    wire_thickness_um: float,
) -> float:
    """
    Wrap angle θ = arctan(P / π(D + 2t)).

    All inputs are converted to a common unit (μm) before the ratio.
    Returns degrees. Returns 0 for non-positive effective diameter.
    """
    tube_diameter_um = tube_diameter_mm * 1000.0
    d_effective_um = tube_diameter_um + 2.0 * wire_thickness_um
    if d_effective_um <= 0:
        return 0.0
    circumference_um = math.pi * d_effective_um
    return math.degrees(math.atan(target_pitch_um / circumference_um))


def config_path() -> Path:
    """Resolve OS-appropriate config file path. Parent directory may not exist."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if not base:
        base = str(Path.home() / ".config" / APP_NAME)
    # AppConfigLocation already typically ends with the app name on Linux/Windows,
    # but on macOS we get ~/Library/Preferences without the app suffix. Normalize.
    base_path = Path(base)
    if base_path.name != APP_NAME:
        base_path = base_path / APP_NAME
    return base_path / CONFIG_FILENAME


def load_config() -> Optional[AppConfig]:
    """Return saved config if present and parseable, else None."""
    path = config_path()
    if not path.exists():
        return None
    try:
        with path.open("r") as f:
            data = json.load(f)
        return AppConfig.from_dict(data)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(config.to_dict(), f, indent=2)
