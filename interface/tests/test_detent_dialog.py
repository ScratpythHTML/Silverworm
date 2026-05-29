"""
Tests for the Detent Configurator dialog and the guarantee that saving new
detent values changes the increment future PUI dial events apply.
"""

import pytest

from ui.detent_dialog import DetentConfigDialog, _WRAPPER, _FEED
from config import AppConfig, DetentConfig
from app_state import AppState, Mode
from comms.pui import DialChange, DetentSize


# qapp fixture provided by pytest-qt via conftest.py.


@pytest.fixture
def detent():
    return DetentConfig(
        dial1_small_rpm=0.1, dial1_medium_rpm=0.5, dial1_large_rpm=1.0,
        dial2_small_mms=0.01, dial2_medium_mms=0.05, dial2_large_mms=0.1,
    )


def test_loads_wrapper_values_and_rpm_units_first(qapp, detent):
    dlg = DetentConfigDialog(detent)
    assert dlg.motor_combo.currentText() == _WRAPPER
    assert [f.text() for f in dlg._inputs] == ["0.1", "0.5", "1"]
    assert [u.text() for u in dlg._unit_labels] == ["RPM", "RPM", "RPM"]


def test_switching_motor_swaps_values_and_units(qapp, detent):
    dlg = DetentConfigDialog(detent)
    dlg.motor_combo.setCurrentText(_FEED)
    assert [f.text() for f in dlg._inputs] == ["0.01", "0.05", "0.1"]
    assert [u.text() for u in dlg._unit_labels] == ["mm/s", "mm/s", "mm/s"]


def test_edits_to_both_motors_are_preserved_on_accept(qapp, detent):
    dlg = DetentConfigDialog(detent)
    # Edit wrapper (dial 1) values, then switch and edit feed (dial 2).
    dlg._inputs[0].setText("2.5")          # wrapper small
    dlg.motor_combo.setCurrentText(_FEED)  # flushes wrapper edits
    dlg._inputs[2].setText("0.9")          # feed large

    result = dlg.detent_config()
    assert result.dial1_small_rpm == 2.5
    assert result.dial1_medium_rpm == 0.5   # untouched
    assert result.dial2_large_mms == 0.9
    assert result.dial2_small_mms == 0.01   # untouched


def test_saved_detents_change_future_dial_increments(qapp, detent):
    """End-to-end: replacing config.detent_config makes AppState use the new
    increment for subsequent dial events (PUI reads config live)."""
    config = AppConfig(detent_config=detent)
    state = AppState(config)
    state.gui_set_mode(Mode.MANUAL)

    # Old increment: wrapper large = 1.0 rpm.
    state.apply_dial_change(DialChange(1, +1, DetentSize.LARGE))
    assert state.wrap_speed_rpm == 1.0

    # Simulate the dialog saving a new value (what _on_edit_detents does).
    dlg = DetentConfigDialog(config.detent_config)
    dlg._inputs[2].setText("5.0")  # wrapper large → 5.0
    config.detent_config = dlg.detent_config()

    # Next event uses the new increment.
    state.apply_dial_change(DialChange(1, +1, DetentSize.LARGE))
    assert state.wrap_speed_rpm == 6.0  # 1.0 + 5.0
