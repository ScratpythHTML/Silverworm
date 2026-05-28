"""Unit tests for the PUI (Physical UI) protocol parser and mock transport."""

import pytest

from comms.pui import (
    parse_pui_message,
    DialChange, ModeSwitch, PowerToggle,
    DetentSize, PUIMode,
    MockPUITransport,
)


class TestParseDialMessages:
    def test_d1_plus_one_is_small_increase(self):
        assert parse_pui_message("D1+1") == DialChange(1, +1, DetentSize.SMALL)

    def test_d1_plus_two_is_medium_increase(self):
        assert parse_pui_message("D1+2") == DialChange(1, +1, DetentSize.MEDIUM)

    def test_d1_minus_two_is_medium_decrease(self):
        assert parse_pui_message("D1-2") == DialChange(1, -1, DetentSize.MEDIUM)

    def test_d2_plus_three_is_large_increase(self):
        assert parse_pui_message("D2+3") == DialChange(2, +1, DetentSize.LARGE)

    def test_d2_minus_one_is_small_decrease(self):
        assert parse_pui_message("D2-1") == DialChange(2, -1, DetentSize.SMALL)


class TestParseModeMessages:
    def test_as0_is_manual(self):
        assert parse_pui_message("AS0") == ModeSwitch(PUIMode.MANUAL)

    def test_as1_is_auto(self):
        assert parse_pui_message("AS1") == ModeSwitch(PUIMode.AUTO)


class TestParsePowerToggle:
    def test_tp(self):
        assert parse_pui_message("TP") == PowerToggle()


class TestParseEdgeCases:
    def test_whitespace_stripped(self):
        assert parse_pui_message("  D1+2  \n") == DialChange(1, +1, DetentSize.MEDIUM)
        assert parse_pui_message("\tTP\r\n") == PowerToggle()

    def test_invalid_strings_return_none(self):
        assert parse_pui_message("XYZ") is None
        assert parse_pui_message("D3+1") is None      # bad dial
        assert parse_pui_message("D1+4") is None      # bad detent
        assert parse_pui_message("D1+0") is None      # bad detent (regex rejects 0)
        assert parse_pui_message("D1") is None        # missing detent
        assert parse_pui_message("D1++2") is None     # bad sign
        assert parse_pui_message("AS2") is None       # unknown mode
        assert parse_pui_message("") is None
        assert parse_pui_message("   ") is None

    def test_case_sensitive(self):
        # Protocol is case-sensitive per the spec
        assert parse_pui_message("tp") is None
        assert parse_pui_message("d1+2") is None
        assert parse_pui_message("as0") is None


class TestMockPUITransport:
    def test_inject_and_read(self):
        t = MockPUITransport()
        t.open()
        t.inject("D1+1")
        t.inject("AS0")
        assert t.read_messages() == ["D1+1", "AS0"]
        assert t.read_messages() == []

    def test_read_on_unopened_returns_empty(self):
        t = MockPUITransport()
        assert t.read_messages() == []
