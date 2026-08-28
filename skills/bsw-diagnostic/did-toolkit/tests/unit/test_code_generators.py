"""Unit tests for the per-DID code generation helpers.

Covers:
* generate_pdm_entry                    (EEPROM-only, writecycles literal)
* generate_config_macro / ..._settings  (macro header + ON/OFF forms)
* generate_element_defs                 (ON=1, OFF=2 definitions)
* generate_range_macros                 (enum vs numeric vs no-range)
* generate_read_code                    (EEPROM vs RAM branches)
* generate_write_code                   (RW gate + enum / numeric / non-EEPROM branches)

Tests assert on stable substrings rather than full text so small
formatting tweaks in generators do not break unit tests - the full-text
contract is covered by the reviewer / generator unit tests that diff
the generated tree against `tests/golden/phase_all/`.
"""

from __future__ import annotations

import pytest

from generate_implementation import (
    DIDImplementationInfo,
    ImplementationGenerator,
)


@pytest.fixture
def gen() -> ImplementationGenerator:
    return ImplementationGenerator()


def _eeprom_numeric() -> DIDImplementationInfo:
    return DIDImplementationInfo(
        did_hex="0xF190",
        did_name="BaselineCounter",
        data_type="Unsigned",
        storage_pos="EEPROM",
        size_bytes="1",
        rw_state="R",
        nvm_item="NVM_ID_DCOM_BaselineCounter",
        value_range="0 ~ 255",
        is_enum=False,
        numeric_min="0",
        numeric_max="255",
    )


def _eeprom_enum_rw() -> DIDImplementationInfo:
    return DIDImplementationInfo(
        did_hex="0xF18C",
        did_name="ModeSelector",
        data_type="enum",
        storage_pos="EEPROM",
        size_bytes="1",
        rw_state="RW",
        nvm_item="NVM_ID_DCOM_ModeSelector",
        value_range="Enum: 0x00, 0x01, 0x02",
        is_enum=True,
        enum_values=["0x00", "0x01", "0x02"],
    )


def _eeprom_numeric_rw_edge() -> DIDImplementationInfo:
    """Edge: min==max. Exercise 'RW' path + numeric-range macros."""
    return DIDImplementationInfo(
        did_hex="0xF1A1",
        did_name="CalibrationConstant",
        data_type="Unsigned",
        storage_pos="EEPROM",
        size_bytes="1",
        rw_state="RW",
        nvm_item="NVM_ID_DCOM_CalibrationConstant",
        value_range="5 ~ 5",
        is_enum=False,
        numeric_min="5",
        numeric_max="5",
    )


def _ram_readonly() -> DIDImplementationInfo:
    return DIDImplementationInfo(
        did_hex="0xF1A0",
        did_name="LiveTemperature",
        data_type="Unsigned",
        storage_pos="RAM",
        size_bytes="1",
        rw_state="R",
        nvm_item="",
        value_range="",
    )


class TestGeneratePdmEntry:
    def test_eeprom_produces_block(self, gen):
        entry = gen.generate_pdm_entry(_eeprom_numeric())
        assert "use dataitem NVM_ID_DCOM_BaselineCounter" in entry
        assert "writecycles = 1000" in entry  # hard-coded 1000 per Bosch convention
        assert "RBFS_DCOM_BaselineCounter" in entry
        assert "#if (RBFS_DCOM_BaselineCounter == RBFS_DCOM_BaselineCounter_ON)" in entry

    def test_ram_returns_empty_string(self, gen):
        assert gen.generate_pdm_entry(_ram_readonly()) == ""


class TestConfigMacros:
    def test_config_macro_default_off(self, gen):
        out = gen.generate_config_macro(_eeprom_numeric())
        assert "#define RBFS_DCOM_BaselineCounter" in out
        assert "RBFS_DCOM_BaselineCounter_OFF" in out
        assert "#ifndef RBFS_DCOM_BaselineCounter" in out
        assert "/*DE|Feature Switch for DID $F190h" in out

    def test_config_settings_macro_on(self, gen):
        out = gen.generate_config_settings_macro(_eeprom_numeric())
        assert "#define RBFS_DCOM_BaselineCounter" in out
        assert "RBFS_DCOM_BaselineCounter_ON" in out
        assert "#ifndef" not in out  # settings form is an unconditional define


class TestElementDefs:
    def test_on_off_values(self, gen):
        out = gen.generate_element_defs(_eeprom_numeric())
        # ON=1, OFF=2 are the AUTOSAR enum values in RBAPLCUST_ConfigElements.h
        assert "#define RBFS_DCOM_BaselineCounter_ON" in out
        assert " 1" in out
        assert "#define RBFS_DCOM_BaselineCounter_OFF" in out
        assert " 2" in out


class TestGenerateRangeMacros:
    def test_numeric_produces_min_max(self, gen):
        out = gen.generate_range_macros(_eeprom_numeric())
        assert "#define DID_F190_MIN" in out
        assert "#define DID_F190_MAX" in out
        assert "0" in out and "255" in out

    def test_enum_produces_val_indices(self, gen):
        out = gen.generate_range_macros(_eeprom_enum_rw())
        assert "#define DID_F18C_VAL_0" in out
        assert "#define DID_F18C_VAL_1" in out
        assert "#define DID_F18C_VAL_2" in out

    def test_ram_returns_empty(self, gen):
        assert gen.generate_range_macros(_ram_readonly()) == ""

    def test_numeric_min_equals_max(self, gen):
        out = gen.generate_range_macros(_eeprom_numeric_rw_edge())
        assert "#define DID_F1A1_MIN" in out
        assert "#define DID_F1A1_MAX" in out


class TestGenerateReadCode:
    def test_eeprom_read_uses_nvm_api(self, gen):
        out = gen.generate_read_code(_eeprom_numeric())
        assert "RBAPLCUST_F190_BaselineCounter_ReadData" in out
        assert "DCOM_ReadDataByNVMId" in out
        assert "NvMConf_NvMBlockDescriptor_NVM_ID_DCOM_BaselineCounter" in out
        assert "#include \"RBAPLCUST_NVMGeneric.h\"" in out
        assert "RB_ASSERT_SWITCH_SETTINGS(RBFS_DCOM_BaselineCounter" in out

    def test_ram_read_uses_todo_placeholder(self, gen):
        out = gen.generate_read_code(_ram_readonly())
        assert "RBAPLCUST_F1A0_LiveTemperature_ReadData" in out
        assert "DCOM_ReadDataByNVMId" not in out
        # Skeleton body: kind-tagged comments let reviewers distinguish
        # RAM from ROM/Flash at a glance and flag the two separate
        # future-work items the engineering team needs to land.
        assert "Read data (RAM storage)" in out
        # v1.27.0: the per-DID brief file pointer was retired; the
        # inline TODO(agent) block now carries identity + storage
        # classification + FSCS behaviour context directly. Pin the
        # markers that downstream agent prompts grep for so a future
        # refactor that drops the inline TODO surfaces here.
        assert "TODO(agent)" in out
        assert "RAM read body" in out
        assert "class       : RAM" in out
        assert (
            "Playbook    : reference/implementation-storage-positions.md"
            in out
        )
        assert "RBAPLCUST_NVMGeneric.h" not in out

    def test_rom_read_uses_rom_flash_kind_tag(self, gen):
        """ROM-backed DIDs (e.g. baked-in software-version strings) are
        fully auto-generated in v2.4.0 when the FSCS behavior text contains
        a valid HardCode: block.  The generated .c uses macro assignments
        (Data[i] = C_DID_..._UB;) and auto-#includes the matching .h.
        No TODO(agent) stub is emitted for ROM/Flash DIDs.
        """
        rom_did = DIDImplementationInfo(
            did_hex="0xF195",
            did_name="SoftwareVersion",
            data_type="Identity",
            storage_pos="ROM",
            size_bytes="29",
            rw_state="R",
        )
        out = gen.generate_read_code(rom_did)
        assert "DCOM_ReadDataByNVMId" not in out
        assert "Read data (ROM/Flash storage)" in out
        # v2.4.0: ROM/Flash DIDs are auto-generated — no TODO(agent) stub.
        assert "TODO(agent)" not in out
        assert "C_DID_SoftwareVersion_Byte0_UB" in out
        assert "RBAPLCUST_RDBI_SoftwareVersion.h" in out
        assert "RBAPLCUST_NVMGeneric.h" not in out


class TestGenerateWriteCode:
    def test_read_only_returns_empty(self, gen):
        assert gen.generate_write_code(_eeprom_numeric()) == ""

    def test_rw_enum_uses_valid_values_check(self, gen):
        out = gen.generate_write_code(_eeprom_enum_rw())
        assert "RBAPLCUST_F18C_ModeSelector_WriteData" in out
        assert "DCOM_WriteDataByNVMId" in out
        # enum branch pulls in DID_<HEX>_VAL_n macro checks
        assert "DID_F18C_VAL_0" in out
        assert "DID_F18C_VAL_1" in out
        assert "DCM_E_REQUESTOUTOFRANGE" in out

    def test_rw_numeric_uses_min_max_macros(self, gen):
        out = gen.generate_write_code(_eeprom_numeric_rw_edge())
        assert "DID_F1A1_MIN" in out
        assert "DID_F1A1_MAX" in out
        assert "DCM_E_REQUESTOUTOFRANGE" in out

    def test_non_eeprom_rw_has_todo_placeholder(self, gen):
        ram_rw = DIDImplementationInfo(
            did_hex="0xF1B0",
            did_name="TransientVal",
            data_type="Unsigned",
            storage_pos="RAM",
            size_bytes="1",
            rw_state="RW",
        )
        out = gen.generate_write_code(ram_rw)
        assert "Write data (RAM storage)" in out
        # v1.27.0: inline TODO(agent) block on the write side, same
        # contract as the read side — class + playbook reference.
        assert "TODO(agent)" in out
        assert "RAM write body" in out
        assert "class       : RAM" in out
        assert (
            "Playbook    : reference/implementation-storage-positions.md"
            in out
        )
        assert "DCOM_WriteDataByNVMId" not in out
