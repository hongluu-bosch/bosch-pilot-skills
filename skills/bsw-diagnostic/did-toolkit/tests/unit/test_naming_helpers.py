"""Unit tests for the naming helpers on ImplementationGenerator.

Targets the Bosch-convention producers
(_clean_name, _capitalize_first, _get_fs_macro, _get_nvm_id,
_get_range_macro_name, _get_func_name) that every downstream artifact
(PDM / .h / .c) hangs off of. Drift here propagates everywhere.
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


class TestCleanName:
    def test_strips_special_chars_and_spaces(self, gen):
        assert gen._clean_name("hello world!") == "helloworld"
        assert gen._clean_name("A-B-C_1") == "ABC_1"

    def test_keeps_alphanumeric_and_underscore(self, gen):
        assert gen._clean_name("ABC_123") == "ABC_123"

    def test_empty_or_all_special_returns_unknown(self, gen):
        assert gen._clean_name("") == "Unknown"
        assert gen._clean_name("!!! ???") == "Unknown"


class TestCapitalizeFirst:
    def test_lowercase_input(self, gen):
        assert gen._capitalize_first("hello") == "Hello"

    def test_single_char_input(self, gen):
        assert gen._capitalize_first("h") == "H"

    def test_already_capitalized(self, gen):
        assert gen._capitalize_first("Hello") == "Hello"

    def test_empty(self, gen):
        assert gen._capitalize_first("") == ""


class TestGetFsMacro:
    def test_uses_rbfs_dcom_prefix(self, gen):
        assert gen._get_fs_macro("BaselineCounter") == "RBFS_DCOM_BaselineCounter"

    def test_strips_nvm_id_dcom_prefix(self, gen):
        # If the did_name already starts with NVM_ID_DCOM_ the generator
        # strips it so we never end up with RBFS_DCOM_NVM_ID_DCOM_Foo.
        assert gen._get_fs_macro("NVM_ID_DCOM_Foo") == "RBFS_DCOM_Foo"
        assert gen._get_fs_macro("nvm_id_dcom_foo") == "RBFS_DCOM_Foo"

    def test_cleans_special_chars_first(self, gen):
        assert gen._get_fs_macro("Mode-Selector!") == "RBFS_DCOM_ModeSelector"


class TestGetNvmId:
    def test_passthrough_with_strip(self, gen):
        assert gen._get_nvm_id("  NVM_ID_DCOM_Foo  ") == "NVM_ID_DCOM_Foo"

    def test_empty_nvm_item_returns_empty(self, gen):
        assert gen._get_nvm_id("") == ""


class TestGetRangeMacroName:
    def test_uses_did_hex_prefix(self, gen):
        assert gen._get_range_macro_name("0xF18C", "MIN") == "DID_F18C_MIN"
        assert gen._get_range_macro_name("0xF18C", "MAX") == "DID_F18C_MAX"
        assert gen._get_range_macro_name("0xF18C", "VAL_0") == "DID_F18C_VAL_0"

    def test_strips_dollar_sign_and_uppercases(self, gen):
        assert gen._get_range_macro_name("$f18c", "MIN") == "DID_F18C_MIN"

    def test_handles_no_prefix(self, gen):
        assert gen._get_range_macro_name("abc", "VAL_1") == "DID_ABC_VAL_1"


class TestGetFuncName:
    def test_format(self, gen):
        did = DIDImplementationInfo(
            did_hex="0xF190",
            did_name="Baseline Counter",
            data_type="Unsigned",
            storage_pos="EEPROM",
            size_bytes="1",
            rw_state="R",
        )
        assert gen._get_func_name(did) == "RBAPLCUST_F190_BaselineCounter"
