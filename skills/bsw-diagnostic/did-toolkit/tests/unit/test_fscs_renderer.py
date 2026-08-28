"""Unit tests for :mod:`scripts.fscs.renderer`.

These tests lock three rendering contracts:

1. **JSON determinism** -- the same :class:`FSCSDocument` always
   serialises to the same bytes (stable key order, indent, trailing
   newline).
2. **TXT layout parity** -- the output matches the legacy
   ``generate_fscs.py`` FSCS_22/FSCS_2E layout closely enough to be
   reviewable side-by-side (tab alignment, ``=`` separator, section
   ordering). Exact byte equality is not required because the user
   explicitly signed off on "格式和风格一致即可".
3. **Override slots** -- ``free_text.*`` values, when populated, win
   over the auto-rendered defaults.
"""

from __future__ import annotations

import json

import pytest

from fscs.renderer import (
    SEPARATOR,
    render_fscs_22_txt,
    render_fscs_2e_txt,
    render_fscs_json,
)
from fscs.schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSFreeText,
    FSCSSecurityLevel,
    FSCSServiceAccess,
    FSCSSubField,
    FSCSValueRangeEnum,
    FSCSValueRangeNone,
    FSCSValueRangeNumeric,
)


# ---------------------------------------------------------------------------
# Fixtures -- two tidy DIDs (one EEPROM+read, one RAM+read) + one RW
# ---------------------------------------------------------------------------


@pytest.fixture
def baseline_did():
    """EEPROM read-only DID with a numeric range, similar to F190."""
    return DIDFscsEntry(
        did_hex="F190",
        did_name="BaselineCounter",
        data_type="Unsigned",
        storage_position="EEPROM",
        size_bytes=1,
        rw_state="R",
        nvm_item="NVM_ID_DCOM_BaselineCounter",
        service_22=FSCSServiceAccess(
            supported=True,
            sessions=["defaultSession", "extendedDiagnosticSession"],
            security_levels=[
                FSCSSecurityLevel(
                    level="L0", note="(means no security access assurance)",
                ),
            ],
            behavior="Read from NVM item: NVM_ID_DCOM_BaselineCounter",
        ),
        service_2e=FSCSServiceAccess(supported=False),
        sub_fields=[
            FSCSSubField(
                byte_range="0",
                name_en="counter value",
                range_min="0",
                range_max="255",
            ),
        ],
        value_range=FSCSValueRangeNumeric(min="0", max="255"),
    )


@pytest.fixture
def live_did():
    """RAM DID with an empty NVM item -- the exact shape the old
    regex bug mis-handled."""
    return DIDFscsEntry(
        did_hex="F1A0",
        did_name="LiveTemperature",
        data_type="Unsigned",
        storage_position="RAM",
        size_bytes=1,
        rw_state="R",
        nvm_item="",
        service_22=FSCSServiceAccess(
            supported=True,
            sessions=["defaultSession"],
            security_levels=[FSCSSecurityLevel(level="L0")],
            behavior="interface: ",
        ),
        service_2e=FSCSServiceAccess(supported=False),
        sub_fields=[
            FSCSSubField(
                byte_range="0",
                name_en="temperature",
                range_min="0",
                range_max="100",
                unit="C",
            ),
        ],
        value_range=FSCSValueRangeNumeric(min="0", max="100", unit="C"),
    )


@pytest.fixture
def mode_rw_did():
    """Enum-typed RW DID -- exercises the 2E rendering path too."""
    return DIDFscsEntry(
        did_hex="F18C",
        did_name="ModeSelector",
        data_type="enum",
        storage_position="EEPROM",
        size_bytes=1,
        rw_state="RW",
        nvm_item="NVM_ID_DCOM_ModeSelector",
        service_22=FSCSServiceAccess(
            supported=True,
            sessions=["defaultSession", "extendedDiagnosticSession"],
            security_levels=[FSCSSecurityLevel(level="L0")],
            behavior="Read from NVM item: NVM_ID_DCOM_ModeSelector",
        ),
        service_2e=FSCSServiceAccess(
            supported=True,
            sessions=["extendedDiagnosticSession"],
            security_levels=[FSCSSecurityLevel(level="L1")],
            behavior="Write to NVM item: NVM_ID_DCOM_ModeSelector",
        ),
        sub_fields=[
            FSCSSubField(
                byte_range="0",
                name_en="mode code",
                range_min="0x00",
                range_max="0x02",
                enum_mapping="0x00=Normal\n0x01=Sport\n0x02=Eco",
            ),
        ],
        value_range=FSCSValueRangeEnum(values=["0x00", "0x01", "0x02"]),
    )


@pytest.fixture
def document(baseline_did, live_did, mode_rw_did):
    return FSCSDocument(
        generated_at="2026-04-20T10:15:30Z",
        dids=[baseline_did, mode_rw_did, live_did],
    )


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


class TestRenderJson:

    def test_deterministic_across_calls(self, document):
        a = render_fscs_json(document)
        b = render_fscs_json(document)
        assert a == b

    def test_ends_with_trailing_newline(self, document):
        out = render_fscs_json(document)
        assert out.endswith("\n")

    def test_pretty_indented_with_two_spaces(self, document):
        out = render_fscs_json(document)
        # First nested key lands on a 2-space indent, proving indent=2.
        assert '\n  "schema_version"' in out

    def test_preserves_field_declaration_order(self, document):
        out = render_fscs_json(document)
        # schema_version must precede generated_at must precede dids.
        sv = out.index('"schema_version"')
        ga = out.index('"generated_at"')
        di = out.index('"dids"')
        assert sv < ga < di

    def test_ram_did_keeps_empty_nvm_item_as_string(self, document):
        data = json.loads(render_fscs_json(document))
        live = next(d for d in data["dids"] if d["did_hex"] == "F1A0")
        assert live["nvm_item"] == ""

    def test_value_range_discriminator_serialised(self, document):
        data = json.loads(render_fscs_json(document))
        kinds = {d["did_hex"]: d["value_range"]["kind"] for d in data["dids"]}
        assert kinds == {
            "F190": "numeric",
            "F1A0": "numeric",
            "F18C": "enum",
        }


# ---------------------------------------------------------------------------
# FSCS_22 TXT rendering
# ---------------------------------------------------------------------------


class TestRender22Txt:

    def test_only_includes_read_supported_dids(self, document, baseline_did):
        """Set service_22 off for one DID -> it must disappear."""
        # Swap in a read-off copy.
        baseline_did.service_22.supported = False
        rendered = render_fscs_22_txt(document)
        assert "BaselineCounter" not in rendered
        # The other two (F18C RW, F1A0 R) are still there.
        assert "ModeSelector" in rendered
        assert "LiveTemperature" in rendered

    def test_starts_with_generated_banner(self, document):
        out = render_fscs_22_txt(document)
        # Step-5 header: every .txt starts with the "Generated from
        # fscs.json" banner so hand-editors are warned off, then a
        # blank line, then the first Identifier block.
        assert out.startswith("# ")
        assert "Generated from outputs/fscs/fscs.json" in out.splitlines()[1]
        # The first Identifier line appears after the banner.
        assert "\nIdentifier $F190h - BaselineCounter\n" in out

    def test_uses_80_equal_separator_between_dids(self, document):
        out = render_fscs_22_txt(document)
        assert SEPARATOR in out
        # The separator appears after each DID block (3 read DIDs).
        assert out.count(SEPARATOR) == 3

    def test_renders_tab_aligned_footer(self, document):
        out = render_fscs_22_txt(document)
        # Exact tab shape matches the legacy generator: one tab after
        # "Storage Position:" and "R/W State:", two tabs after
        # "Data Type:" / "NVM Item:", three tabs after "Size:" to
        # line up the value column. Value Range itself is now a bare
        # header line; byte labels and content live underneath at the
        # 3-tab indent so all byte rows align in the same column.
        assert "Data Type:\t\tUnsigned" in out
        assert "Storage Position:\tEEPROM" in out
        assert "Size:\t\t\t1 bytes" in out
        assert "R/W State:\t\tR" in out
        assert "NVM Item:\t\tNVM_ID_DCOM_BaselineCounter" in out
        assert "Value Range:\n\t\t\tByte[0]:\n" in out
        assert (
            "\t\t\t    Physical range: 0 ~ 255 "
            "(Resolution: 1, Offset: 0, Encoded: Unsigned)"
        ) in out

    def test_renders_behavior_after_value_range(self, document):
        out = render_fscs_22_txt(document)
        assert (
            "Value Range:\n"
            "\t\t\tByte[0]:\n"
            "\t\t\t    Physical range: 0 ~ 255 "
            "(Resolution: 1, Offset: 0, Encoded: Unsigned)\n"
            "Behavior:\n"
            "Read from NVM item: NVM_ID_DCOM_BaselineCounter"
        ) in out

    def test_ram_did_has_empty_nvm_line(self, document):
        out = render_fscs_22_txt(document)
        # ``NVM Item:\t\t`` followed directly by newline -> empty value.
        assert "NVM Item:\t\t\n" in out.replace(
            "NVM Item:\t\t\t", "NVM Item:\t\t",  # guard against typos
        )

    def test_security_level_line_uses_two_tab_indent_and_note(self, document):
        out = render_fscs_22_txt(document)
        assert "Security Level:" in out
        assert "\t\tL0 (means no security access assurance)" in out

    def test_request_and_response_blocks_present(self, document):
        out = render_fscs_22_txt(document)
        # Header rows now share the data-record column width (dynamic
        # padding, not tabs) so byte labels line up with sub-field labels.
        assert 'Byte 1          $22 = Request Service Id "ReadDataByIdentifier"' in out
        assert 'Byte 1          $62 = Response Service Id "ReadDataByIdentifier"' in out
        assert "Byte 4          counter value" in out
        assert "                Range: 0x00 ~ 0xFF" in out

    def test_enum_did_renders_enum_mapping_detail_lines(self, document):
        out = render_fscs_22_txt(document)
        # Each enum entry should appear as an indented detail line, aligned
        # under the byte label column (16 spaces by default).
        assert "                0x00: Normal" in out
        assert "                0x01: Sport" in out
        assert "                0x02: Eco" in out
        # Footer Value Range now lays out byte/value on two lines and
        # collapses consecutive enum keys into a single ``0x00~0x02``
        # interval -- enum singletons should never appear when a
        # contiguous range describes the same set.
        assert "Value Range:\n\t\t\tByte[0]:\n\t\t\t    0x00~0x02" in out


# ---------------------------------------------------------------------------
# FSCS_2E TXT rendering
# ---------------------------------------------------------------------------


class TestRender2eTxt:

    def test_only_includes_write_supported_dids(self, document):
        out = render_fscs_2e_txt(document)
        # Only the RW ModeSelector (F18C) supports 2E.
        assert "ModeSelector" in out
        assert "BaselineCounter" not in out
        assert "LiveTemperature" not in out

    def test_rw_state_reads_as_W_from_2E_perspective(self, document):
        out = render_fscs_2e_txt(document)
        assert "R/W State:\t\tW" in out

    def test_uses_2e_request_and_response_service_ids(self, document):
        out = render_fscs_2e_txt(document)
        assert 'Byte 1          $2E = Request Service Id "WriteDataByIdentifier"' in out
        assert 'Byte 1          $6E = Response Service Id "WriteDataByIdentifier"' in out

    def test_2e_emits_request_data_record_table_only(self, document):
        out = render_fscs_2e_txt(document)
        assert "Data Record" not in out
        assert "Byte 4          mode code" in out
        response = out.split("Positive Response Message:", 1)[1]
        assert "mode code" not in response

    def test_renders_write_behavior_after_value_range(self, document):
        out = render_fscs_2e_txt(document)
        # Even on the write side the enum interval list appears under
        # Value Range -- enums are no longer skipped from the footer.
        assert "Value Range:\n\t\t\tByte[0]:\n\t\t\t    0x00~0x02" in out
        assert (
            "Behavior:\n"
            "Write to NVM item: NVM_ID_DCOM_ModeSelector"
        ) in out


# ---------------------------------------------------------------------------
# Selection filter (`used` flag gates the TXT output)
# ---------------------------------------------------------------------------


class TestRendererRespectsUsedFlag:
    """The operator-facing ``used`` flag filters .txt rendering.

    These tests lock the "fscs.json is the full input, .txt is the
    selected subset" contract down: flipping ``used=False`` on a
    structurally-supported service must remove that service's .txt
    block without side-effects on the JSON dump.
    """

    def test_used_false_excludes_did_from_22_txt(self, document, baseline_did):
        baseline_did.service_22.used = False
        out = render_fscs_22_txt(document)
        assert "BaselineCounter" not in out
        # Other DIDs still render -- the filter is per-DID, not global.
        assert "ModeSelector" in out
        assert "LiveTemperature" in out

    def test_used_false_excludes_did_from_2e_txt_only(
        self, document, mode_rw_did,
    ):
        """Deselect write on an RW DID -> 2E drops, 22 keeps it."""
        mode_rw_did.service_2e.used = False
        out_22 = render_fscs_22_txt(document)
        out_2e = render_fscs_2e_txt(document)
        assert "ModeSelector" in out_22, (
            "Deselecting 2E must not remove the DID from the read-side .txt"
        )
        assert "ModeSelector" not in out_2e, (
            "Deselecting 2E must remove the DID from the write-side .txt"
        )

    def test_used_false_leaves_json_intact(self, document, baseline_did):
        """JSON remains authoritative; ``used`` is just a render-time mask."""
        baseline_did.service_22.used = False
        data = json.loads(render_fscs_json(document))
        hexes = [d["did_hex"] for d in data["dids"]]
        assert "F190" in hexes, (
            "fscs.json must keep every DID from the input regardless of "
            "the operator's selection -- the UI mutates `used`, never the "
            "set of DIDs."
        )
        entry = next(d for d in data["dids"] if d["did_hex"] == "F190")
        assert entry["service_22"]["used"] is False

    def test_bulk_deselection_yields_empty_txt_body(
        self, document, baseline_did, mode_rw_did, live_did,
    ):
        """All DIDs deselected for 22 -> .txt has only the banner."""
        for did in (baseline_did, mode_rw_did, live_did):
            did.service_22.used = False
        out = render_fscs_22_txt(document)
        assert "Identifier $" not in out
        assert SEPARATOR not in out


# ---------------------------------------------------------------------------
# Override slots (free_text.*)
# ---------------------------------------------------------------------------


class TestFreeTextOverrides:

    def test_description_read_override_wins(self, document, baseline_did):
        baseline_did.free_text = FSCSFreeText(
            description_read="Custom reviewer prose for the baseline counter.",
        )
        out = render_fscs_22_txt(document)
        assert "Custom reviewer prose for the baseline counter." in out
        assert "This identifier returns the BaselineCounter" not in out

    def test_request_block_22_override_replaces_default_lines(
        self, document, baseline_did,
    ):
        baseline_did.free_text = FSCSFreeText(
            request_block_22=(
                'Byte 1\t\t$22 = RDBI\n'
                'Byte 2-3\t$F190 = BaselineCounter (reviewer-tuned)'
            ),
        )
        out = render_fscs_22_txt(document)
        block = out.split(SEPARATOR)[0]
        # The override shows up.
        assert "BaselineCounter (reviewer-tuned)" in block
        assert "$22 = RDBI" in block
        # The auto-generated *request* line (with the long "Request
        # Service Id" quoted form) must be gone; the response block
        # keeps its own default and is unaffected.
        assert 'Request Service Id "ReadDataByIdentifier"' not in block
        assert 'Response Service Id "ReadDataByIdentifier"' in block

    def test_response_block_2e_override_wins(self, document, mode_rw_did):
        mode_rw_did.free_text = FSCSFreeText(
            response_block_2e=(
                'Byte 1\t\t$6E = Custom WDBI response'
            ),
        )
        out = render_fscs_2e_txt(document)
        assert "Custom WDBI response" in out


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_value_range_renders_from_current_sub_fields(self, document, baseline_did):
        baseline_did.value_range = FSCSValueRangeNone()
        out = render_fscs_22_txt(document)
        assert (
            "Value Range:\n\t\t\tByte[0]:\n\t\t\t    Physical range: 0 ~ 255"
        ) in out

    def test_no_sessions_renders_fallback_sentence(self, document, baseline_did):
        baseline_did.service_22.sessions = []
        out = render_fscs_22_txt(document)
        assert "No diagnostic sessions supported." in out

    def test_no_security_levels_renders_none(self, document, baseline_did):
        baseline_did.service_22.security_levels = []
        out = render_fscs_22_txt(document)
        assert "\t\tNone\n" in out

    def test_multi_byte_single_subfield_uses_byte_range_header(self, document):
        # Surgically enlarge baseline to size=4 with a single sub_field.
        doc = document.model_copy(deep=True)
        did = doc.dids[0]
        did.size_bytes = 4
        did.sub_fields = [
            FSCSSubField(byte_range="0-3", name_en="wide counter", range_min="0", range_max="9999"),
        ]
        out = render_fscs_22_txt(doc)
        # The redundant Data Record summary is gone; the sub-field header
        # carries the byte span.
        assert "Data Record" not in out
        assert "Byte 4-7        wide counter" in out

    def test_numeric_conversion_value_range_shows_logical_and_physical(self, document):
        doc = document.model_copy(deep=True)
        did = doc.dids[0]
        did.size_bytes = 2
        did.sub_fields = [
            FSCSSubField(
                byte_idx=0,
                byte_span=2,
                name_en="wheel speed",
                range_min="-10",
                range_max="6543.5",
                resolution="0.1",
                offset="-10",
                unit="km/h",
            ),
        ]
        out = render_fscs_22_txt(doc)
        # Logical/HEX range lives under each request/response sub-field as
        # the Range: aux line. The footer Value Range carries the byte
        # label on one line and the physical range on the indented line
        # below so byte/value columns stay independently scannable.
        # M9 adds an inferred ``Encoded:`` annotation -- here the raw
        # min derived from physical -10 with offset -10 is 0, so
        # the field is classified as Unsigned (offset-biased).
        assert "                Range: 0x0000 ~ 0xFFFF" in out
        assert (
            "Value Range:\n"
            "\t\t\tByte[0-1]:\n"
            "\t\t\t    Physical range: -10 ~ 6543.5 km/h "
            "(Resolution: 0.1, Offset: -10, Encoded: Unsigned)"
        ) in out

    def test_signed_field_renders_negative_hex_and_signed_tag(self, document):
        """Signed fields show ``-0xXX`` raw range and ``Encoded: Signed``."""
        doc = document.model_copy(deep=True)
        did = doc.dids[0]
        did.size_bytes = 2
        did.sub_fields = [
            FSCSSubField(
                byte_idx=0,
                byte_span=2,
                name_en="brake disk temperature",
                range_min="-63",
                range_max="1300",
                resolution="1",
                offset="0",
                unit="degC",
            ),
        ]
        out = render_fscs_22_txt(doc)
        # Negative raw values are rendered with a signed-magnitude
        # ``-0xXXXX`` prefix at the same column width as positives.
        assert "                Range: -0x003F ~ 0x0514" in out
        # Footer Physical range line carries the encoding inference.
        assert (
            "\t\t\t    Physical range: -63 ~ 1300 degC "
            "(Resolution: 1, Offset: 0, Encoded: Signed)"
        ) in out
