"""Unit tests for scripts/semantic.py.

Pure functions, no filesystem or XML access; these tests are the
canary that tells us when cross-field / range rules regress.
"""
from __future__ import annotations

import pytest

from semantic import _coerce_int, _semantic_checks

# ---------------------------------------------------------------------------
# _coerce_int: hex / decimal / edge cases


@pytest.mark.parametrize("value,expected", [
    (None, None),
    ("", None),
    (0, 0),
    (42, 42),
    (True, 1),
    (False, 0),
    ("10", 10),
    (" 10 ", 10),
    ("0x7DF", 0x7DF),
    ("0X7df", 0x7DF),
    ("7DF", 0x7DF),         # bare hex -- auto-detected because of A..F
    ("ABC", 0xABC),
    ("not a number", None),
    ("0xZZ", None),
])
def test_coerce_int(value, expected):
    assert _coerce_int(value) == expected


# ---------------------------------------------------------------------------
# CAN ID range vs format


def test_11bit_ok_29bit_ok_baseline():
    errors, warns = _semantic_checks({
        "CAN_ID_Format": "11bit",
        "CAN_Functional_Request_ID": "0x7DF",
        "CAN_Physical_Request_ID": "0x722",
        "CAN_Response_ID": "0x7A2",
    })
    assert errors == []


def test_11bit_rejects_29bit_id():
    errors, _ = _semantic_checks({
        "CAN_ID_Format": "11bit",
        "CAN_Functional_Request_ID": "0x18DAF100",  # 29-bit value
    })
    assert any("11-bit" in e for e in errors), errors


def test_29bit_accepts_high_id():
    errors, _ = _semantic_checks({
        "CAN_ID_Format": "29bit",
        "CAN_Functional_Request_ID": "0x1FFFFFFF",
    })
    assert errors == []


def test_29bit_rejects_too_high_id():
    errors, _ = _semantic_checks({
        "CAN_ID_Format": "29bit",
        "CAN_Functional_Request_ID": "0x20000000",
    })
    assert any("29-bit" in e for e in errors), errors


def test_unknown_id_format_is_warning_not_error():
    errors, warns = _semantic_checks({
        "CAN_ID_Format": "17bit",
        "CAN_Functional_Request_ID": "0x100",
    })
    assert errors == []
    assert any("unknown value" in w for w in warns), warns


# ---------------------------------------------------------------------------
# STmin hard cap


def test_stmin_accepts_127ms():
    errors, _ = _semantic_checks({"STmin": 127})
    assert errors == []


def test_stmin_rejects_above_cap():
    errors, _ = _semantic_checks({"STmin": 128})
    assert any("127" in e for e in errors), errors


def test_stmin_rejects_negative():
    errors, _ = _semantic_checks({"STmin": -1})
    assert any("negative" in e for e in errors), errors


def test_stmin_parse_error():
    errors, _ = _semantic_checks({"STmin": "not a number"})
    assert any("cannot parse" in e for e in errors), errors


# ---------------------------------------------------------------------------
# PaddingByte / NRC78_Times 0..255 range


def test_paddingbyte_hex_ok():
    errors, _ = _semantic_checks({"PaddingByte": "0xAA"})
    assert errors == []


def test_paddingbyte_upper_limit_ok():
    errors, _ = _semantic_checks({"PaddingByte": 255})
    assert errors == []


def test_paddingbyte_too_large():
    errors, _ = _semantic_checks({"PaddingByte": 256})
    assert any("0..255" in e for e in errors), errors


def test_nrc78_range_ok():
    errors, _ = _semantic_checks({"NRC78_Times": 10})
    assert errors == []


def test_nrc78_too_large():
    errors, _ = _semantic_checks({"NRC78_Times": 300})
    assert any("0..255" in e for e in errors), errors


# ---------------------------------------------------------------------------
# CAN_DLC cross-check: ClassicCAN forces DL=8


def test_classiccan_with_dl_8_ok():
    errors, _ = _semantic_checks({
        "CAN_DLC": {
            "rx_frame_type": "ClassicCAN",
            "rx_dl": 8,
            "tx_frame_type": "ClassicCAN",
            "tx_dl": 8,
        },
    })
    assert errors == []


def test_classiccan_rejects_dl_64():
    errors, _ = _semantic_checks({
        "CAN_DLC": {"rx_frame_type": "ClassicCAN", "rx_dl": 64},
    })
    assert any("rx_dl must be 8" in e for e in errors), errors


def test_canfd_allows_dl_64():
    errors, _ = _semantic_checks({
        "CAN_DLC": {
            "rx_frame_type": "CANFD", "rx_dl": 64,
            "tx_frame_type": "CANFD", "tx_dl": 64,
        },
    })
    assert errors == []


def test_asymmetric_rx_fd_tx_classic_ok():
    """RX CANFD(64) + TX ClassicCAN(8) is a supported asymmetric layout."""
    errors, _ = _semantic_checks({
        "CAN_DLC": {
            "rx_frame_type": "CANFD", "rx_dl": 64,
            "tx_frame_type": "ClassicCAN", "tx_dl": 8,
        },
    })
    assert errors == []


# ---------------------------------------------------------------------------
# No false positives on empty/partial inputs


def test_empty_values_no_errors():
    errors, warns = _semantic_checks({})
    assert errors == []
    assert warns == []


def test_partial_values_only_checks_present_keys():
    errors, _ = _semantic_checks({"CAN_ID_Format": "11bit"})
    assert errors == []
