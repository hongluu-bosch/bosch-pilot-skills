"""Unit tests for :mod:`scripts.fscs.schema`.

The schema is the contract every downstream consumer (Phase 2 ARXML,
Phase 3 Implementation, Review, xlsx edit) relies on, so these
tests are deliberately strict: every enum boundary, every discriminator
branch, and every normalisation rule must fail loudly on bad input.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fscs.schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSSecurityLevel,
    FSCSServiceAccess,
    FSCSSubField,
    FSCSValueRangeComposite,
    FSCSValueRangeEnum,
    FSCSValueRangeNone,
    FSCSValueRangeNumeric,
    SCHEMA_VERSION,
    normalize_did_hex,
    normalize_storage_position,
)


# ---------------------------------------------------------------------------
# Minimal-DID helper so each test only spells out the fields it cares about.
# ---------------------------------------------------------------------------


def _minimal_did(**overrides) -> DIDFscsEntry:
    base = dict(
        did_hex="F190",
        did_name="BaselineCounter",
        data_type="Unsigned",
        storage_position="EEPROM",
        size_bytes=1,
        rw_state="R",
        nvm_item="NVM_ID_DCOM_BaselineCounter",
        service_22=FSCSServiceAccess(
            supported=True,
            sessions=["defaultSession"],
            security_levels=[FSCSSecurityLevel(level="L0", note="(demo)")],
        ),
        service_2e=FSCSServiceAccess(supported=False),
    )
    base.update(overrides)
    return DIDFscsEntry(**base)


# ---------------------------------------------------------------------------
# DID hex normalisation
# ---------------------------------------------------------------------------


class TestNormalizeDidHex:

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("F190", "F190"),
            ("f190", "F190"),
            ("0xF190", "F190"),
            ("0xf190", "F190"),
            ("$F190h", "F190"),
            ("$f190H", "F190"),
            ("  F190 ", "F190"),
            # Short hex pads out to 4.
            ("F19", "0F19"),
        ],
    )
    def test_accepts_canonical_and_legacy_forms(self, raw, expected):
        assert normalize_did_hex(raw) == expected

    def test_passes_through_non_string(self):
        # Non-strings are returned as-is so pydantic can surface the
        # real type error rather than a confusing str coercion one.
        assert normalize_did_hex(0xF190) == 0xF190
        assert normalize_did_hex(None) is None

    def test_returns_bad_input_unchanged_for_pydantic_to_reject(self):
        # "not-hex" stays as-is; model validation raises downstream.
        assert normalize_did_hex("not-hex") == "not-hex"


class TestDIDHexField:

    def test_normalises_on_construction(self):
        did = _minimal_did(did_hex="0xf190")
        assert did.did_hex == "F190"

    def test_rejects_non_hex(self):
        with pytest.raises(ValidationError):
            _minimal_did(did_hex="ZZZZ")


# ---------------------------------------------------------------------------
# nvm_item / RAM handling (the bug this migration closes)
# ---------------------------------------------------------------------------


class TestNvmItem:

    def test_empty_string_is_valid_for_ram(self):
        did = _minimal_did(storage_position="RAM", nvm_item="")
        assert did.nvm_item == ""

    def test_rejects_none_for_nvm_item(self):
        """Empty NVM is ``""``, never ``None``; this is the whole point
        of the migration -- no more ``in (None, "")`` ambiguity."""
        with pytest.raises(ValidationError):
            _minimal_did(nvm_item=None)


# ---------------------------------------------------------------------------
# Enums reject out-of-domain values
# ---------------------------------------------------------------------------


class TestEnumConstraints:

    def test_rejects_unknown_storage_position(self):
        # ``FLASH`` is an accepted synonym for ``ROM`` (see
        # ``TestNormalizeStoragePosition``); use a genuinely unknown
        # value so pydantic's Literal check fires as intended.
        with pytest.raises(ValidationError):
            _minimal_did(storage_position="OTP")

    def test_rejects_unknown_rw_state(self):
        with pytest.raises(ValidationError):
            _minimal_did(rw_state="X")

    def test_rejects_unknown_session(self):
        with pytest.raises(ValidationError):
            _minimal_did(
                service_22=FSCSServiceAccess(
                    supported=True,
                    sessions=["programmingSession"],  # not allowed
                    security_levels=[],
                ),
            )

    def test_rejects_unknown_security_level(self):
        with pytest.raises(ValidationError):
            FSCSSecurityLevel(level="L2")

    def test_size_bytes_positive(self):
        with pytest.raises(ValidationError):
            _minimal_did(size_bytes=0)


# ---------------------------------------------------------------------------
# extra='forbid' on every model
# ---------------------------------------------------------------------------


class TestStrictExtraForbid:

    def test_top_level_document_forbids_extra(self):
        with pytest.raises(ValidationError):
            FSCSDocument(dids=[], mystery_key="oops")

    def test_did_entry_forbids_extra(self):
        with pytest.raises(ValidationError):
            _minimal_did(legacy_variant_field="ignored-in-new-schema")

    def test_sub_field_forbids_extra(self):
        with pytest.raises(ValidationError):
            FSCSSubField(name_en="x", unknown="y")


# ---------------------------------------------------------------------------
# value_range discriminated union
# ---------------------------------------------------------------------------


class TestValueRangeDiscriminator:

    def test_numeric_branch_round_trip(self):
        did = _minimal_did(
            value_range=FSCSValueRangeNumeric(min="0", max="255", unit=""),
        )
        dumped = did.model_dump(mode="json")
        assert dumped["value_range"]["kind"] == "numeric"
        reloaded = DIDFscsEntry.model_validate(dumped)
        assert isinstance(reloaded.value_range, FSCSValueRangeNumeric)
        assert reloaded.value_range.min == "0"

    def test_enum_branch_round_trip(self):
        did = _minimal_did(
            value_range=FSCSValueRangeEnum(values=["0x00", "0x01", "0x02"]),
        )
        dumped = did.model_dump(mode="json")
        assert dumped["value_range"]["kind"] == "enum"
        reloaded = DIDFscsEntry.model_validate(dumped)
        assert isinstance(reloaded.value_range, FSCSValueRangeEnum)
        assert reloaded.value_range.values == ["0x00", "0x01", "0x02"]

    def test_composite_branch_preserves_rendered_string(self):
        did = _minimal_did(
            value_range=FSCSValueRangeComposite(
                rendered="0 ~ 10 C; 100 ~ 200 C",
            ),
        )
        dumped = did.model_dump(mode="json")
        assert dumped["value_range"] == {
            "kind": "composite",
            "rendered": "0 ~ 10 C; 100 ~ 200 C",
        }

    def test_none_is_default(self):
        did = _minimal_did()
        assert isinstance(did.value_range, FSCSValueRangeNone)

    def test_bad_discriminator_rejected(self):
        with pytest.raises(ValidationError):
            DIDFscsEntry.model_validate(
                {
                    **_minimal_did().model_dump(mode="json"),
                    "value_range": {"kind": "linear", "slope": 1, "offset": 0},
                }
            )


# ---------------------------------------------------------------------------
# Document round-trip
# ---------------------------------------------------------------------------


class TestDocumentRoundTrip:

    def test_empty_dids_is_valid(self):
        doc = FSCSDocument(dids=[])
        assert doc.schema_version == SCHEMA_VERSION
        assert doc.dids == []

    def test_legacy_json_without_used_key_still_loads(self):
        """Fscs.json written before the selection feature omits ``used``.

        The schema default (``True``) must kick in on load so that pre-
        feature documents continue to drive the same downstream output
        they always did (everything is effectively selected). This is
        the whole reason ``used`` is defaulted and not required.
        """
        legacy_did = {
            "did_hex": "F190",
            "did_name": "BaselineCounter",
            "data_type": "Unsigned",
            "storage_position": "EEPROM",
            "size_bytes": 1,
            "rw_state": "R",
            "nvm_item": "NVM_ID_DCOM_BaselineCounter",
            "service_22": {
                "supported": True,
                "sessions": ["defaultSession"],
                "security_levels": [{"level": "L0", "note": "(demo)"}],
            },
            "service_2e": {
                "supported": False,
                "sessions": [],
                "security_levels": [],
            },
            "sub_fields": [],
            "value_range": {"kind": "none"},
            "free_text": {
                "description_read": None,
                "description_write": None,
                "request_block_22": None,
                "response_block_22": None,
                "request_block_2e": None,
                "response_block_2e": None,
                "custom_paragraphs": [],
            },
        }
        reloaded = DIDFscsEntry.model_validate(legacy_did)
        assert reloaded.service_22.used is True
        assert reloaded.service_2e.used is True
        assert reloaded.service_22.behavior == ""
        assert reloaded.service_2e.behavior == ""

    def test_legacy_document_schema_version_upgrades_to_current(self):
        doc = FSCSDocument.model_validate({
            "schema_version": "1.0",
            "generated_at": "2026-04-20T10:15:30Z",
            "generator": {
                "tool": "did-toolkit/generate_fscs.py",
                "source_inputs": None,
            },
            "project": {"customer_name": None, "product_type": None},
            "dids": [_minimal_did().model_dump(mode="json")],
        })
        assert doc.schema_version == SCHEMA_VERSION

    def test_full_round_trip(self):
        doc = FSCSDocument(
            generated_at="2026-04-20T10:15:30Z",
            dids=[
                _minimal_did(),
                _minimal_did(
                    did_hex="F1A0",
                    did_name="LiveTemperature",
                    storage_position="RAM",
                    nvm_item="",
                    value_range=FSCSValueRangeNumeric(
                        min="0", max="100", unit="C",
                    ),
                    service_22=FSCSServiceAccess(
                        supported=True,
                        sessions=["defaultSession", "extendedDiagnosticSession"],
                        security_levels=[
                            FSCSSecurityLevel(
                                level="L0",
                                note="(means no security access assurance)",
                            ),
                        ],
                    ),
                ),
            ],
        )
        dumped = doc.model_dump(mode="json")
        rehydrated = FSCSDocument.model_validate(dumped)
        assert rehydrated == doc

    def test_service_behavior_round_trips(self):
        did = _minimal_did(
            service_22=FSCSServiceAccess(
                supported=True,
                behavior="Read from NVM item: NVM_ID_DCOM_BaselineCounter",
            ),
            service_2e=FSCSServiceAccess(
                supported=True,
                behavior="Write to NVM item: NVM_ID_DCOM_BaselineCounter",
            ),
        )
        dumped = did.model_dump(mode="json")
        assert dumped["service_22"]["behavior"].startswith("Read from NVM")
        assert dumped["service_2e"]["behavior"].startswith("Write to NVM")
        reloaded = DIDFscsEntry.model_validate(dumped)
        assert reloaded.service_22.behavior == did.service_22.behavior
        assert reloaded.service_2e.behavior == did.service_2e.behavior


# ---------------------------------------------------------------------------
# Selection flag (`used`) + effective gate
# ---------------------------------------------------------------------------


class TestSelectionFlag:
    """Contract tests for the ``used`` flag introduced by the selection UI.

    ``used`` is the operator-owned gate that lets a reviewer exclude a
    DID from FSCS_*.txt / ARXML / C without removing it from
    ``fscs.json``. The effective rule consumers read is ``supported
    AND used`` (exposed as :attr:`FSCSServiceAccess.effective`).
    """

    def test_used_defaults_to_true(self):
        """Freshly-built documents include every DID by default.

        Without this, the first-run UX would be "everything unchecked"
        and the operator would have to click every DID back on.
        """
        svc = FSCSServiceAccess(supported=True)
        assert svc.used is True

    def test_effective_requires_both_supported_and_used(self):
        cases = [
            (True, True, True),    # happy path
            (True, False, False),  # deselected by operator
            (False, True, False),  # not structurally supported
            (False, False, False), # neither
        ]
        for supported, used, expected in cases:
            svc = FSCSServiceAccess(supported=supported, used=used)
            assert svc.effective is expected, (
                f"supported={supported}, used={used} -> "
                f"expected effective={expected}, got {svc.effective}"
            )

    def test_used_survives_round_trip(self):
        """Toggling ``used=False`` must round-trip through JSON intact.

        The whole point of storing ``used`` in fscs.json is so that
        re-running Phase 1 (which rebuilds from inputs/*.json) can
        preserve the selection. If JSON serialisation dropped it, the
        preservation logic in generate_fscs.py would silently fail.
        """
        did = _minimal_did()
        did.service_22.used = False
        did.service_2e.used = False
        dumped = did.model_dump(mode="json")
        assert dumped["service_22"]["used"] is False
        assert dumped["service_2e"]["used"] is False
        reloaded = DIDFscsEntry.model_validate(dumped)
        assert reloaded.service_22.used is False
        assert reloaded.service_2e.used is False


# ---------------------------------------------------------------------------
# Storage-position alias: ``NVM`` is a synonym for ``EEPROM``
# ---------------------------------------------------------------------------


class TestNormalizeStoragePosition:
    """``NVM`` must collapse into canonical ``EEPROM`` at the schema boundary.

    Bosch DCOM inputs use ``storage_pos: "NVM"`` interchangeably with
    ``"EEPROM"``. The schema pins one canonical form so downstream code
    (PDM emission, write-validation macros, reviewers) only has to
    branch on ``== "EEPROM"``.
    """

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # EEPROM + NVM alias
            ("EEPROM", "EEPROM"),
            ("eeprom", "EEPROM"),
            ("NVM", "EEPROM"),
            ("nvm", "EEPROM"),
            ("Nvm", "EEPROM"),
            ("  NVM ", "EEPROM"),
            # RAM
            ("RAM", "RAM"),
            ("ram", "RAM"),
            # ROM + FLASH alias
            ("ROM", "ROM"),
            ("rom", "ROM"),
            ("FLASH", "ROM"),
            ("flash", "ROM"),
            ("Flash", "ROM"),
            ("  FLASH ", "ROM"),
        ],
    )
    def test_aliases_and_canonical_values_fold_to_canonical(self, raw, expected):
        assert normalize_storage_position(raw) == expected

    def test_unknown_values_are_uppercased_but_not_rewritten(self):
        """Only genuine synonyms alias; typos stay (to surface as errors).

        We deliberately don't swallow ``OTP`` / ``HSM`` into RAM or
        EEPROM/ROM -- that would hide customer-input bugs. The value is
        returned upper-cased so pydantic's ``Literal`` check produces a
        clear error message pointing at the real input.
        """
        assert normalize_storage_position("otp") == "OTP"
        assert normalize_storage_position("hsm") == "HSM"

    def test_non_string_passes_through(self):
        assert normalize_storage_position(None) is None
        assert normalize_storage_position(42) == 42

    def test_did_entry_accepts_nvm_as_synonym_for_eeprom(self):
        """End-to-end: ``storage_pos: NVM`` parses and normalises.

        Customer inputs that spell the field ``"NVM"`` must not fail
        validation -- the whole point of the alias. After construction
        the stored value is canonical ``"EEPROM"`` so downstream reads
        of ``did.storage_position`` see what they expect.
        """
        did = _minimal_did(storage_position="NVM")
        assert did.storage_position == "EEPROM"

    def test_did_entry_accepts_flash_as_synonym_for_rom(self):
        """``storage_pos: "Flash"`` round-trips as canonical ``ROM``.

        "ROM" and "Flash" denote the same compile-time-constant storage
        class in customer inputs (on-chip flash holding const data).
        Aliasing to a single canonical spelling means downstream
        skeleton-generation code doesn't have to branch on two labels.
        """
        did = _minimal_did(storage_position="Flash")
        assert did.storage_position == "ROM"

    def test_did_entry_rejects_unknown_storage_values(self):
        with pytest.raises(ValidationError):
            _minimal_did(storage_position="OTP")

    def test_nvm_survives_json_round_trip_as_eeprom(self):
        """Loaded-then-dumped values never regress to the alias.

        ``fscs.json`` always carries the canonical spelling; re-loading
        an older ``fscs.json`` that happened to contain ``"NVM"`` (e.g.
        hand-edited or produced before this normalisation existed)
        canonicalises on load.
        """
        did = DIDFscsEntry.model_validate(
            {
                "did_hex": "F190",
                "did_name": "BaselineCounter",
                "data_type": "Unsigned",
                "storage_position": "NVM",
                "size_bytes": 1,
                "rw_state": "R",
                "nvm_item": "NVM_ID_DCOM_BaselineCounter",
                "service_22": {
                    "supported": True,
                    "sessions": ["defaultSession"],
                    "security_levels": [
                        {"level": "L0", "note": "(demo)"}
                    ],
                },
                "service_2e": {"supported": False},
            }
        )
        assert did.storage_position == "EEPROM"
        dumped = did.model_dump(mode="json")
        assert dumped["storage_position"] == "EEPROM"
