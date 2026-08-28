"""Unit tests for scripts/mapping.py and the transform round-trip.

Covers:
  * mapping.yaml parses into a well-formed PARAM_MAP
  * every entry has a known transform and reverse transform
  * forward/reverse transforms round-trip where applicable
  * locator shapes are one of the four supported types
"""
from __future__ import annotations

import pytest

import mapping
from mapping import PARAM_MAP, REVERSE_TRANSFORMS, TRANSFORMS

ALLOWED_LOCATOR_TYPES = {
    "def_suffix",
    "def_suffix_any",
    "def_suffix_under_short_name",
}


# ---------------------------------------------------------------------------
# PARAM_MAP structural invariants


def test_param_map_non_empty():
    assert len(PARAM_MAP) > 0


def test_every_entry_has_required_keys():
    for i, entry in enumerate(PARAM_MAP):
        for key in ("param", "file", "locator", "transform"):
            assert key in entry, f"PARAM_MAP[{i}]={entry} missing {key!r}"


def test_every_locator_type_is_supported():
    for entry in PARAM_MAP:
        loc = entry["locator"]
        # type defaults to def_suffix when absent (legacy); that's fine.
        ltype = loc.get("type", "def_suffix")
        assert ltype in ALLOWED_LOCATOR_TYPES, (
            f"{entry['param']}: unsupported locator type {ltype!r}")


def test_every_transform_is_callable():
    for entry in PARAM_MAP:
        name = entry["transform"]
        assert name in TRANSFORMS, (
            f"{entry['param']}: unknown transform {name!r}")
        assert callable(TRANSFORMS[name])


# Transforms intentionally shipped without a reverse. Empty today:
# the lazy-seed / reseed reverse walk pre-fills every mapped field from
# ARXML, so every forward transform must have a matching reverse.
# Adding names here must be deliberate -- anything in this set will be
# skipped when seeding inputs/DiagComm_values.json from live arxml.
_NO_REVERSE_OK: set[str] = set()


def test_every_transform_has_a_reverse_or_is_whitelisted():
    for entry in PARAM_MAP:
        name = entry["transform"]
        if name in _NO_REVERSE_OK:
            continue
        assert name in REVERSE_TRANSFORMS, (
            f"{entry['param']}: transform {name!r} has no reverse "
            f"(breaks the lazy-seed reverse walk). Add it to "
            f"REVERSE_TRANSFORMS or whitelist it in _NO_REVERSE_OK "
            f"with a comment.")
        assert callable(REVERSE_TRANSFORMS[name])


def test_derived_entries_have_the_derived_flag():
    derived_params = [e["param"] for e in PARAM_MAP if e.get("derived")]
    # At present only the synthetic FD flag is derived. If more are added,
    # this asserts that the flag still means what we think it means.
    assert "CAN_DLC.flexible_fd" in derived_params


# ---------------------------------------------------------------------------
# Forward / reverse round-trip for the common transforms


@pytest.mark.parametrize("ms,arxml_literal", [
    # Integral-second values must keep their float literal (".0" suffix)
    # so ECUC-FLOAT nodes aren't silently rewritten to an int-looking
    # VALUE. See scripts/mapping.py::_format_autosar_float.
    (70, "0.07"),
    (20, "0.02"),
    (150, "0.15"),
    (5000, "5.0"),
    # Zero is the sole carve-out: existing arxml conventionally stores
    # the zero literal as bare "0" (BS, default timers, etc.), so we
    # match that to avoid churn.
    (0, "0"),
])
def test_ms_to_seconds_round_trip(ms, arxml_literal):
    fwd = TRANSFORMS["ms_to_seconds"](ms)
    assert fwd == arxml_literal
    # Reverse: arxml literal back to ms. Tolerate floats returned as int
    # where the value is integral (that's the reverse transform's
    # documented behaviour).
    assert REVERSE_TRANSFORMS["ms_to_seconds"](fwd) == ms


@pytest.mark.parametrize("user,arxml_literal", [
    ("0x7DF", "2015"),
    ("0x722", "1826"),
    ("0x1FFFFFFF", str(0x1FFFFFFF)),
    (0, "0"),
    (255, "255"),
])
def test_hex_to_decimal_round_trip(user, arxml_literal):
    fwd = TRANSFORMS["hex_to_decimal"](user)
    assert fwd == arxml_literal
    # Reverse: decimal back to upper-case hex literal (0xNNN form).
    rev = REVERSE_TRANSFORMS["hex_to_decimal"](fwd)
    # Reverse normalizes to 0x-prefixed upper-case string.
    assert int(rev, 16) == int(arxml_literal)


@pytest.mark.parametrize("user,literal,expected_bool", [
    (True, "true", True),
    (False, "false", False),
    ("true", "true", True),
    ("false", "false", False),
    ("YES", "true", True),
    (1, "true", True),
    (0, "false", False),
])
def test_bool_str_round_trip(user, literal, expected_bool):
    fwd = TRANSFORMS["bool_str"](user)
    assert fwd == literal
    assert REVERSE_TRANSFORMS["bool_str"](literal) is expected_bool


def test_canfd_pdu_id_type_forward():
    # Classic CAN -> STANDARD_CAN, CANFD -> STANDARD_FD_CAN (11-bit ID).
    assert TRANSFORMS["canfd_pdu_id_type"]("ClassicCAN") == "STANDARD_CAN"
    assert TRANSFORMS["canfd_pdu_id_type"]("CANFD") == "STANDARD_FD_CAN"


def test_can_id_type_forward():
    assert TRANSFORMS["can_id_type"]("11bit") == "STANDARD"
    assert TRANSFORMS["can_id_type"]("29bit") == "EXTENDED"


# ---------------------------------------------------------------------------
# expand_path: template substitution


def test_expand_path_substitutes_product_and_channel():
    template = "RBAPLCust/cfg/{product_type}/Can{can_channel}_CusDiag_EcucValues_{product_type}.arxml"
    out = mapping.expand_path(template, "DPB", 0)
    assert "DPB" in out
    assert "Can0_" in out
    assert "{product_type}" not in out
    assert "{can_channel}" not in out


def test_expand_path_passthrough_when_no_placeholders():
    template = "RBAPLCust/cfg/Common/CanTp_CusDiag_EcucValues.arxml"
    assert mapping.expand_path(template, "DPB", 0) == template


# ---------------------------------------------------------------------------
# get_nested


def test_get_nested_flat():
    assert mapping.get_nested({"a": 1}, "a") == 1


def test_get_nested_dotted():
    data = {"CAN_DLC": {"rx_dl": 64}}
    assert mapping.get_nested(data, "CAN_DLC.rx_dl") == 64


def test_get_nested_missing_returns_none():
    assert mapping.get_nested({}, "X.Y") is None
    assert mapping.get_nested({"X": {}}, "X.Y") is None
