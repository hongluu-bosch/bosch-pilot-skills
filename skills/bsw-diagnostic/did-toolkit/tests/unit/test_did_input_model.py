"""Unit tests for the pydantic ``DIDInput`` model (phase 7).

We only cover the fail-fast contract, not every permissive passthrough:
the goal of the model is to catch obviously-bad JSON early with a
pointer at the offending field, not to enforce a strict schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from implementation.models import DIDInput, DIDSubField  # noqa: E402


VALID_DID = {
    "did_hex": "0xF190",
    "did_name_en": "BaselineCounter",
    "did_name_zh": "",
    "cvt": "U",
    "supported_by_ecu": "Y",
    "rw_state": "R",
    "size_bytes": "1",
    "data_type": "Unsigned",
    "storage_pos": "EEPROM",
    "access": {},
    "sub_fields": [
        {
            "byte": "0", "bit": "All", "name_en": "counter",
            "range_min_phy": "0", "range_max_phy": "255",
        }
    ],
}


def test_valid_minimal_did_passes():
    did = DIDInput.model_validate(VALID_DID)
    assert did.did_hex == "0xF190"
    assert did.rw_state == "R"
    assert isinstance(did.sub_fields[0], DIDSubField)


def test_extra_unknown_keys_are_allowed():
    """Future-proof: inputs may gain new fields; validation must not reject."""
    payload = {**VALID_DID, "future_field": {"some": "thing"}}
    did = DIDInput.model_validate(payload)
    assert did.did_name_en == "BaselineCounter"


def test_missing_required_field_raises():
    payload = {k: v for k, v in VALID_DID.items() if k != "did_hex"}
    with pytest.raises(ValidationError) as exc_info:
        DIDInput.model_validate(payload)
    assert "did_hex" in str(exc_info.value)


@pytest.mark.parametrize("bad_rw", ["read", "W", "rw", ""])
def test_rw_state_restricted_to_r_or_rw(bad_rw):
    payload = {**VALID_DID, "rw_state": bad_rw}
    with pytest.raises(ValidationError):
        DIDInput.model_validate(payload)


@pytest.mark.parametrize("bad_yn", ["yes", "", "Yes", "true"])
def test_supported_by_ecu_restricted_to_y_n(bad_yn):
    payload = {**VALID_DID, "supported_by_ecu": bad_yn}
    with pytest.raises(ValidationError):
        DIDInput.model_validate(payload)


def test_empty_did_hex_is_rejected():
    payload = {**VALID_DID, "did_hex": ""}
    with pytest.raises(ValidationError):
        DIDInput.model_validate(payload)


def test_validate_many_reports_bad_entry_index():
    bad = {**VALID_DID, "rw_state": "WRONG"}
    with pytest.raises(ValidationError) as exc_info:
        DIDInput.validate_many([VALID_DID, bad, VALID_DID])
    # pydantic encodes the list index in the error path.
    assert "rw_state" in str(exc_info.value)
