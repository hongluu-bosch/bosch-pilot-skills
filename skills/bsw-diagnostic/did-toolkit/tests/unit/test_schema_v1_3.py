"""Tests for the v1.3 schema additions (``data_type`` / ``encoding``).

Originally introduced as the v1.3 (sub-field metadata) regression
suite; v1.13.0 (schema 1.4) and v1.16.0 (schema 1.5) keep the file
in place and update the schema-version assertions so the historical
1.0/1.1/1.2/1.3/1.4 upgrade-path tests still document the multi-step
migration chain.

The two new-in-1.3 optional fields land on :class:`FSCSSubField`.
They are backed by case-insensitive aliasing helpers
(:func:`normalize_sub_field_data_type` /
:func:`normalize_sub_field_encoding`) so questionnaires can use the
spellings the operators are familiar with (``int8``, ``Bytefield``,
``string``) without violating the strict ``Literal`` validator.

Coverage:

* The two normalisers map every documented synonym to the canonical
  form and pass through unknown values verbatim (so pydantic can
  reject typos with a clear error).
* :class:`FSCSSubField` accepts the canonical values, accepts ``None``
  / missing keys, normalises common synonyms on construction, and
  rejects free-form strings.
* :class:`FSCSDocument` reports ``schema_version="1.4"`` and silently
  upgrades v1.0 / v1.1 / v1.2 / v1.3 documents on load.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from fscs import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSServiceAccess,
    FSCSSubField,
    SCHEMA_VERSION,
    normalize_sub_field_data_type,
    normalize_sub_field_encoding,
)


# ---------------------------------------------------------------------------
# Schema-level metadata
# ---------------------------------------------------------------------------


def test_schema_version_is_1_5():
    assert SCHEMA_VERSION == "1.5"
    doc = FSCSDocument(dids=[])
    assert doc.schema_version == "1.5"


@pytest.mark.parametrize("legacy_version", ["1.0", "1.1", "1.2", "1.3", "1.4"])
def test_legacy_documents_upgrade_to_current(legacy_version):
    """Each historical version silently upgrades to the current SCHEMA_VERSION.

    1.3 -> 1.4 was a metadata-only bump (the optional ``product_scope``
    field).  1.4 -> 1.5 renamed ``product_scope`` to ``product_type``
    on each DID and dropped the global ``project.product_type`` knob;
    a legacy document carrying neither key still loads cleanly.
    """
    payload = {
        "schema_version": legacy_version,
        "generated_at": "2026-04-20T12:00:00+00:00",
        "dids": [],
    }
    doc = FSCSDocument.model_validate(payload)
    assert doc.schema_version == "1.5"


def test_unknown_schema_version_rejected():
    payload = {"schema_version": "9.9", "dids": []}
    with pytest.raises(ValidationError):
        FSCSDocument.model_validate(payload)


def test_round_trip_preserves_schema_version_in_json():
    doc = FSCSDocument(dids=[])
    text = doc.model_dump_json()
    loaded = json.loads(text)
    assert loaded["schema_version"] == "1.5"


# ---------------------------------------------------------------------------
# normalize_sub_field_data_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Numeric", "Numeric"),
        ("numeric", "Numeric"),
        ("NUM", "Numeric"),
        ("integer", "Numeric"),
        ("Enum", "Enum"),
        ("ENUMERATION", "Enum"),
        ("texttable", "Enum"),
        ("BitField", "BitField"),
        ("BIT FIELD", "BitField"),
        ("bits", "BitField"),
        ("hex", "Hex"),
        ("Bytefield", "Hex"),
        ("raw", "Hex"),
        ("ASCII", "ASCII"),
        ("string", "ASCII"),
        ("BCD", "BCD"),
        ("composite", "Composite"),
        ("STRUCT", "Composite"),
    ],
)
def test_normalize_data_type_aliases(raw, expected):
    assert normalize_sub_field_data_type(raw) == expected


def test_normalize_data_type_blank_returns_none():
    assert normalize_sub_field_data_type(None) is None
    assert normalize_sub_field_data_type("") is None
    assert normalize_sub_field_data_type("   ") is None


def test_normalize_data_type_unknown_passes_through():
    """Unknown text is returned unchanged so pydantic can complain."""
    assert normalize_sub_field_data_type("MysteryType") == "MysteryType"


def test_normalize_data_type_non_string_passthrough():
    """Non-strings (e.g. ints) bypass normalisation; pydantic raises later."""
    assert normalize_sub_field_data_type(42) == 42


# ---------------------------------------------------------------------------
# normalize_sub_field_encoding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Unsigned", "Unsigned"),
        ("uint", "Unsigned"),
        ("UInt8", "Unsigned"),
        ("u16", "Unsigned"),
        ("Signed", "Signed"),
        ("int", "Signed"),
        ("sint16", "Signed"),
        ("s32", "Signed"),
        ("float", "Float32"),
        ("Float32", "Float32"),
        ("real", "Float32"),
        ("double", "Float64"),
        ("FLOAT64", "Float64"),
        ("ascii", "ASCIIString"),
        ("string", "ASCIIString"),
        ("rawbytes", "RawBytes"),
        ("Bytes", "RawBytes"),
        ("hex", "RawBytes"),
    ],
)
def test_normalize_encoding_aliases(raw, expected):
    assert normalize_sub_field_encoding(raw) == expected


def test_normalize_encoding_blank_returns_none():
    assert normalize_sub_field_encoding(None) is None
    assert normalize_sub_field_encoding("") is None


def test_normalize_encoding_unknown_passes_through():
    assert normalize_sub_field_encoding("Unobtainium") == "Unobtainium"


# ---------------------------------------------------------------------------
# FSCSSubField acceptance
# ---------------------------------------------------------------------------


def _baseline_subfield(**overrides):
    base = dict(name_en="counter")
    base.update(overrides)
    return FSCSSubField(**base)


def test_subfield_omits_data_type_and_encoding_by_default():
    sf = _baseline_subfield()
    assert sf.data_type is None
    assert sf.encoding is None


def test_subfield_accepts_canonical_values():
    sf = _baseline_subfield(data_type="Numeric", encoding="Signed")
    assert sf.data_type == "Numeric"
    assert sf.encoding == "Signed"


def test_subfield_normalises_synonyms_on_construction():
    sf = _baseline_subfield(data_type="bytefield", encoding="uint16")
    assert sf.data_type == "Hex"
    assert sf.encoding == "Unsigned"


def test_subfield_rejects_unknown_data_type():
    with pytest.raises(ValidationError):
        _baseline_subfield(data_type="MysteryType")


def test_subfield_rejects_unknown_encoding():
    with pytest.raises(ValidationError):
        _baseline_subfield(encoding="Unobtainium")


def test_subfield_round_trip_preserves_v1_3_fields():
    sf = _baseline_subfield(data_type="Enum", encoding="Unsigned")
    payload = sf.model_dump_json()
    restored = FSCSSubField.model_validate(json.loads(payload))
    assert restored.data_type == "Enum"
    assert restored.encoding == "Unsigned"


def test_full_did_entry_with_v1_3_fields():
    """A whole DIDFscsEntry round-trips with sub-field metadata intact."""
    entry = DIDFscsEntry(
        did_hex="F190",
        did_name="VIN",
        data_type="ASCII",
        storage_position="EEPROM",
        size_bytes=17,
        rw_state="R",
        nvm_item="NVM_ID_DCOM_VIN",
        service_22=FSCSServiceAccess(supported=True, used=True),
        service_2e=FSCSServiceAccess(supported=False, used=True),
        sub_fields=[
            FSCSSubField(
                name_en="vin",
                byte_idx=0,
                byte_span=17,
                data_type="ASCII",
                encoding="ASCIIString",
            )
        ],
    )
    doc = FSCSDocument(dids=[entry])
    payload = doc.model_dump_json()
    restored = FSCSDocument.model_validate(json.loads(payload))
    assert restored.dids[0].sub_fields[0].data_type == "ASCII"
    assert restored.dids[0].sub_fields[0].encoding == "ASCIIString"
