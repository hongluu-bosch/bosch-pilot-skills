"""Unit tests for :mod:`scripts.fscs.builder`.

The builder is the Phase 1 transform: raw ``inputs/*.json`` records ->
validated :class:`FSCSDocument`. These tests exercise the semantic
mapping rules the legacy ``FSCSGenerator`` used to embed in its
rendering code, now extracted into pure data-model territory.
"""

from __future__ import annotations

import pytest

from fscs import (
    FSCSProject,
    FSCSValueRangeComposite,
    FSCSValueRangeEnum,
    FSCSValueRangeNone,
    FSCSValueRangeNumeric,
    build_fscs_document,
)


def _make_record(**overrides):
    """Baseline raw record that passes validation out of the box.

    Matches the ``tiny_did.json`` fixture shape so tests exercise the
    same code paths the phase-1 pipeline does end-to-end.
    """
    base = {
        "did_hex": "0xF190",
        "did_name_en": "BaselineCounter",
        "did_name_zh": "\u57fa\u7ebf\u8ba1\u6570\u5668",
        "supported_by_ecu": "Y",
        "rw_state": "R",
        "size_bytes": "1",
        "data_type": "Unsigned",
        "storage_pos": "EEPROM",
        "access": {
            "service_22": {
                "application": {"default": "Y", "programming": "N", "extended": "Y"},
                "security": {"level0": "Y", "level1": "Y"},
            },
            "service_2e": {
                "application": {"default": "N", "programming": "N", "extended": "N"},
                "security": {"level0": "N", "level1": "N"},
            },
        },
        "sub_fields": [
            {
                "byte": "0",
                "bit": "All",
                "name_en": "counter value",
                "name_zh": "\u8ba1\u6570\u503c",
                "range_min_phy": "0",
                "range_max_phy": "255",
                "unit": "",
                "method_en": "",
                "method_zh": "",
                "default_value_phy": "0",
            }
        ],
    }
    base.update(overrides)
    return base


class TestFiltering:

    def test_drops_unsupported_records(self):
        doc = build_fscs_document(
            [
                _make_record(supported_by_ecu="N"),
                _make_record(did_hex="0xF1A0", did_name_en="LiveTemperature"),
            ],
            generated_at="2026-04-20T00:00:00+00:00",
        )
        assert [d.did_name for d in doc.dids] == ["LiveTemperature"]


class TestServiceSupportDerivedFromRwState:

    def test_r_only(self):
        doc = build_fscs_document(
            [_make_record(rw_state="R")],
            generated_at="t",
        )
        assert doc.dids[0].service_22.supported is True
        assert doc.dids[0].service_2e.supported is False

    def test_rw_promotes_both(self):
        doc = build_fscs_document(
            [_make_record(rw_state="RW")],
            generated_at="t",
        )
        assert doc.dids[0].service_22.supported is True
        assert doc.dids[0].service_2e.supported is True

    def test_w_only(self):
        doc = build_fscs_document(
            [_make_record(rw_state="W")],
            generated_at="t",
        )
        assert doc.dids[0].service_22.supported is False
        assert doc.dids[0].service_2e.supported is True


class TestSecurityLevelRules:

    def test_both_l0_l1_supported_emits_only_l0_with_note(self):
        record = _make_record()
        record["access"]["service_22"]["security"] = {"level0": "Y", "level1": "Y"}
        doc = build_fscs_document([record], generated_at="t")
        levels = doc.dids[0].service_22.security_levels
        assert len(levels) == 1
        assert levels[0].level == "L0"
        assert levels[0].note is not None and "security access" in levels[0].note

    def test_l1_only_emits_bare_l1(self):
        record = _make_record()
        record["access"]["service_22"]["security"] = {"level0": "N", "level1": "Y"}
        doc = build_fscs_document([record], generated_at="t")
        levels = doc.dids[0].service_22.security_levels
        assert len(levels) == 1
        assert levels[0].level == "L1"
        assert levels[0].note is None

    def test_neither_empty(self):
        record = _make_record()
        record["access"]["service_22"]["security"] = {"level0": "N", "level1": "N"}
        doc = build_fscs_document([record], generated_at="t")
        assert doc.dids[0].service_22.security_levels == []


class TestNvmItemDerivation:

    def test_eeprom_derives_prefixed_name(self):
        doc = build_fscs_document([_make_record(storage_pos="EEPROM")], generated_at="t")
        assert doc.dids[0].nvm_item == "NVM_ID_DCOM_BaselineCounter"

    def test_ram_has_empty_nvm_item(self):
        doc = build_fscs_document([_make_record(storage_pos="RAM")], generated_at="t")
        assert doc.dids[0].nvm_item == ""

    def test_mixed_case_storage_still_detected(self):
        doc = build_fscs_document([_make_record(storage_pos="eeprom")], generated_at="t")
        assert doc.dids[0].nvm_item.startswith("NVM_ID_DCOM_")

    def test_nvm_alias_canonicalises_to_eeprom(self):
        """``storage_pos: "NVM"`` must land as canonical ``EEPROM``.

        This guards the Bosch DCOM synonym: customer inputs that spell
        the field ``"NVM"`` have historically exploded the schema;
        post-normalisation they route through the same NVM-item-derivation
        code path as real ``"EEPROM"`` entries.
        """
        doc = build_fscs_document([_make_record(storage_pos="NVM")], generated_at="t")
        entry = doc.dids[0]
        assert entry.storage_position == "EEPROM"
        assert entry.nvm_item == "NVM_ID_DCOM_BaselineCounter"

    def test_nvm_alias_mixed_case(self):
        doc = build_fscs_document([_make_record(storage_pos="nvm")], generated_at="t")
        assert doc.dids[0].storage_position == "EEPROM"

    def test_rom_preserved_with_no_nvm_item(self):
        """ROM-backed DIDs keep the ``ROM`` spelling and get no NVM item.

        Emitting a PDM block for a flash-constant DID would resolve to
        a non-existent NvM block descriptor at runtime. The empty
        ``nvm_item`` is the generator's contract that "this DID has
        no NvM side effects".
        """
        doc = build_fscs_document([_make_record(storage_pos="ROM")], generated_at="t")
        entry = doc.dids[0]
        assert entry.storage_position == "ROM"
        assert entry.nvm_item == ""

    def test_flash_alias_canonicalises_to_rom(self):
        """``Flash`` and ``ROM`` denote the same class; ``Flash`` canonicalises."""
        doc = build_fscs_document([_make_record(storage_pos="Flash")], generated_at="t")
        entry = doc.dids[0]
        assert entry.storage_position == "ROM"
        assert entry.nvm_item == ""


class TestBehaviorTemplates:

    def test_eeprom_rw_generates_nvm_behavior_per_service(self):
        doc = build_fscs_document([_make_record(rw_state="RW")], generated_at="t")
        entry = doc.dids[0]

        assert entry.service_22.behavior == (
            "Read from NVM item: NVM_ID_DCOM_BaselineCounter"
        )
        assert entry.service_2e.behavior == (
            "Write to NVM item: NVM_ID_DCOM_BaselineCounter"
        )

    def test_ram_generates_interface_behavior(self):
        doc = build_fscs_document(
            [_make_record(storage_pos="RAM", rw_state="RW")], generated_at="t",
        )
        entry = doc.dids[0]

        assert entry.service_22.behavior == "interface: "
        assert entry.service_2e.behavior == "interface: "

    def test_rom_read_generates_hardcode_placeholders(self):
        doc = build_fscs_document(
            [_make_record(storage_pos="ROM", rw_state="R", size_bytes="2")],
            generated_at="t",
        )
        entry = doc.dids[0]

        assert entry.service_22.behavior == (
            "HardCode:\n"
            "C_DID_BaselineCounter_Byte0_UB = 0x\n"
            "C_DID_BaselineCounter_Byte1_UB = 0x"
        )
        assert entry.service_2e.behavior == ""


class TestValueRangeDerivation:

    def test_single_sub_field_numeric(self):
        doc = build_fscs_document([_make_record()], generated_at="t")
        vr = doc.dids[0].value_range
        assert isinstance(vr, FSCSValueRangeNumeric)
        assert vr.min == "0"
        assert vr.max == "255"

    def test_single_sub_field_enum_from_equals_mapping(self):
        record = _make_record(
            data_type="enum",
            sub_fields=[{
                "byte": "0", "bit": "All", "name_en": "mode",
                "method_en": "0x00=Normal\n0x01=Sport\n0x02=Eco",
                "range_min_phy": "0x00", "range_max_phy": "0x02",
            }],
        )
        doc = build_fscs_document([record], generated_at="t")
        vr = doc.dids[0].value_range
        assert isinstance(vr, FSCSValueRangeEnum)
        assert vr.values == ["0x00", "0x01", "0x02"]

    def test_no_sub_fields_yields_none(self):
        record = _make_record(sub_fields=[])
        doc = build_fscs_document([record], generated_at="t")
        assert isinstance(doc.dids[0].value_range, FSCSValueRangeNone)

    def test_multiple_sub_fields_yield_composite(self):
        record = _make_record(
            size_bytes="2",
            sub_fields=[
                {
                    "byte": "0", "bit": "All", "name_en": "lo",
                    "range_min_phy": "0", "range_max_phy": "9", "unit": "C",
                },
                {
                    "byte": "1", "bit": "All", "name_en": "hi",
                    "range_min_phy": "10", "range_max_phy": "99",
                },
            ],
        )
        doc = build_fscs_document([record], generated_at="t")
        vr = doc.dids[0].value_range
        assert isinstance(vr, FSCSValueRangeComposite)
        assert "0 ~ 9 C" in vr.rendered
        assert "10 ~ 99" in vr.rendered


class TestCjkNameStripping:

    def test_did_name_strips_cjk(self):
        # CJK leaks sometimes via did_name_en; the .txt stays English-only.
        doc = build_fscs_document(
            [_make_record(did_name_en="BaselineCounter\u57fa\u7ebf")],
            generated_at="t",
        )
        assert doc.dids[0].did_name == "BaselineCounter"

    def test_did_name_zh_preserved_verbatim(self):
        doc = build_fscs_document([_make_record()], generated_at="t")
        assert doc.dids[0].did_name_zh == "\u57fa\u7ebf\u8ba1\u6570\u5668"


class TestProjectAndProvenance:

    def test_project_metadata_round_trip(self):
        # v1.16.0 (FSCS schema 1.5): FSCSProject no longer carries
        # ``product_type`` -- the build target lives on the CLI and
        # the per-DID tag lives on each DIDFscsEntry. The metadata
        # round-trip now pins the remaining customer_name + the
        # provenance fields.
        doc = build_fscs_document(
            [_make_record()],
            project=FSCSProject(customer_name="Acme"),
            generated_at="2026-04-20T00:00:00+00:00",
            source_inputs="tiny_did.json",
        )
        assert doc.project.customer_name == "Acme"
        assert doc.generator.source_inputs == "tiny_did.json"
        assert doc.generated_at == "2026-04-20T00:00:00+00:00"


class TestSizeCoercion:

    @pytest.mark.parametrize("raw,expected", [
        ("1", 1), ("4", 4), ("TBD", 1), ("", 1), (None, 1), (2, 2),
    ])
    def test_size_bytes_robust_coercion(self, raw, expected):
        doc = build_fscs_document(
            [_make_record(size_bytes=raw)], generated_at="t",
        )
        assert doc.dids[0].size_bytes == expected
