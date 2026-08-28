"""Unit tests for _parse_enum_values and _parse_numeric_range."""

from __future__ import annotations

import pytest

from generate_implementation import ImplementationGenerator


@pytest.fixture
def gen() -> ImplementationGenerator:
    return ImplementationGenerator()


class TestParseEnumValues:
    def test_happy_path(self, gen):
        result = gen._parse_enum_values("Enum: 0x00, 0x01, 0x02")
        assert result == ["0x00", "0x01", "0x02"]

    def test_tolerates_extra_whitespace(self, gen):
        result = gen._parse_enum_values("Enum: 0x00 ,  0x01 , 0x02 ")
        assert result == ["0x00", "0x01", "0x02"]

    def test_single_value(self, gen):
        assert gen._parse_enum_values("Enum: 0x05") == ["0x05"]

    def test_missing_enum_marker_returns_empty(self, gen):
        assert gen._parse_enum_values("0 ~ 255") == []
        assert gen._parse_enum_values("") == []


class TestParseNumericRange:
    def test_happy_path(self, gen):
        assert gen._parse_numeric_range("0 ~ 255") == ("0", "255")

    def test_hex_range(self, gen):
        assert gen._parse_numeric_range("0x00 ~ 0xFF") == ("0x00", "0xFF")

    def test_negative_min(self, gen):
        assert gen._parse_numeric_range("-128 ~ 127") == ("-128", "127")

    def test_strips_unit_from_max(self, gen):
        # "0 ~ 255 units" -> max should lose the trailing unit
        assert gen._parse_numeric_range("0 ~ 255 C") == ("0", "255")

    def test_ignores_enum_string(self, gen):
        assert gen._parse_numeric_range("Enum: 0x00, 0x01") == ("", "")

    def test_handles_missing_tilde(self, gen):
        assert gen._parse_numeric_range("just text") == ("", "")

    def test_min_equals_max_edge(self, gen):
        assert gen._parse_numeric_range("5 ~ 5") == ("5", "5")
