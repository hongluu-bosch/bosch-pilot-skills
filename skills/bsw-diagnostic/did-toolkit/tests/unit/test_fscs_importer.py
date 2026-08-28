"""Unit tests for :mod:`scripts.fscs.importer`.

The importer is a migration bridge: legacy ``FSCS_*.txt`` plaintext ->
validated :class:`FSCSDocument`. The shipped ``expected_fscs_22.txt``
and ``expected_fscs_2e.txt`` fixtures are byte-for-byte samples from
the legacy generator, so they're the authoritative ground truth for
what the importer has to accept.
"""

from __future__ import annotations

import pytest

from fscs import (
    FSCSValueRangeEnum,
    FSCSValueRangeNone,
    FSCSValueRangeNumeric,
    import_fscs_txt,
)


@pytest.fixture
def both_paths(fixtures_dir):
    return (
        fixtures_dir / "expected_fscs_22.txt",
        fixtures_dir / "expected_fscs_2e.txt",
    )


class TestLegacyPairRoundTrip:

    def test_merges_22_and_2e(self, both_paths):
        p22, p2e = both_paths
        doc = import_fscs_txt(fscs_22_path=p22, fscs_2e_path=p2e)
        assert len(doc.dids) == 5
        hexes = [d.did_hex for d in doc.dids]
        assert set(hexes) == {"F190", "F18C", "F1A0", "F1A1", "F1A2"}

    def test_rw_state_promotion(self, both_paths):
        p22, p2e = both_paths
        doc = import_fscs_txt(fscs_22_path=p22, fscs_2e_path=p2e)
        by_hex = {d.did_hex: d for d in doc.dids}
        # ModeSelector and CalibrationConstant appear in both files.
        assert by_hex["F18C"].rw_state == "RW"
        assert by_hex["F1A1"].rw_state == "RW"
        # Read-only DIDs stay R.
        assert by_hex["F190"].rw_state == "R"

    def test_ram_did_has_empty_nvm_item(self, both_paths):
        p22, p2e = both_paths
        doc = import_fscs_txt(fscs_22_path=p22, fscs_2e_path=p2e)
        live = next(d for d in doc.dids if d.did_hex == "F1A0")
        # The same RAM+empty-NVM case that used to be xfailed in the
        # legacy parser must parse cleanly here too.
        assert live.storage_position == "RAM"
        assert live.nvm_item == ""


class TestValueRangeRoundTrip:

    def test_numeric_range_round_trips(self, both_paths):
        p22, _ = both_paths
        doc = import_fscs_txt(fscs_22_path=p22)
        f190 = next(d for d in doc.dids if d.did_hex == "F190")
        assert isinstance(f190.value_range, FSCSValueRangeNumeric)
        assert f190.value_range.min == "0"
        assert f190.value_range.max == "255"

    def test_enum_round_trips(self, both_paths):
        p22, _ = both_paths
        doc = import_fscs_txt(fscs_22_path=p22)
        f18c = next(d for d in doc.dids if d.did_hex == "F18C")
        assert isinstance(f18c.value_range, FSCSValueRangeEnum)
        assert f18c.value_range.values == ["0x00", "0x01", "0x02"]

    def test_numeric_range_with_unit(self, both_paths):
        p22, _ = both_paths
        doc = import_fscs_txt(fscs_22_path=p22)
        f1a0 = next(d for d in doc.dids if d.did_hex == "F1A0")
        assert isinstance(f1a0.value_range, FSCSValueRangeNumeric)
        assert f1a0.value_range.unit == "C"


class TestSecurityLevels:

    def test_l0_note_captured(self, both_paths):
        p22, _ = both_paths
        doc = import_fscs_txt(fscs_22_path=p22)
        f190 = next(d for d in doc.dids if d.did_hex == "F190")
        assert len(f190.service_22.security_levels) == 1
        sl = f190.service_22.security_levels[0]
        assert sl.level == "L0"
        assert "security access" in (sl.note or "")


class TestSessions:

    def test_read_sessions_extracted(self, both_paths):
        p22, _ = both_paths
        doc = import_fscs_txt(fscs_22_path=p22)
        f190 = next(d for d in doc.dids if d.did_hex == "F190")
        assert f190.service_22.sessions == [
            "defaultSession",
            "extendedDiagnosticSession",
        ]


class TestOneSidedImport:

    def test_only_22_file(self, fixtures_dir):
        doc = import_fscs_txt(
            fscs_22_path=fixtures_dir / "expected_fscs_22.txt",
            fscs_2e_path=None,
        )
        # Every DID is read-only; service_2e is unsupported everywhere.
        assert all(d.rw_state == "R" for d in doc.dids)
        assert all(d.service_2e.supported is False for d in doc.dids)

    def test_only_2e_file(self, fixtures_dir):
        doc = import_fscs_txt(
            fscs_22_path=None,
            fscs_2e_path=fixtures_dir / "expected_fscs_2e.txt",
        )
        assert all(d.rw_state == "W" for d in doc.dids)
        assert all(d.service_22.supported is False for d in doc.dids)


class TestProvenance:

    def test_generator_tool_identifies_importer(self, both_paths):
        p22, p2e = both_paths
        doc = import_fscs_txt(fscs_22_path=p22, fscs_2e_path=p2e)
        assert "import" in doc.generator.tool
        assert doc.generator.source_inputs and str(p22) in doc.generator.source_inputs


class TestRoundTripEquivalence:
    """Build-via-import then serialise; make sure the .txt footer fields
    downstream parsers care about survive intact."""

    def test_footer_fields_survive_round_trip(self, both_paths, tmp_path):
        from fscs import render_fscs_22_txt
        p22, p2e = both_paths
        doc = import_fscs_txt(fscs_22_path=p22, fscs_2e_path=p2e)

        rendered_22 = render_fscs_22_txt(doc)

        # Every read-supporting DID's footer ought to appear with the
        # same numeric/enum classification. We spot-check the tricky
        # cases: RAM+empty-NVM and numeric-with-unit.
        assert "NVM Item:\t\t\n" in rendered_22.replace("NVM Item:\t\t\t", "x")
        # M8: footer Value Range uses two-line layout (label + indented
        # content). The TXT importer does not reconstruct sub_fields, so
        # the renderer falls back to the summary ``did.value_range`` --
        # numeric values keep their ``min ~ max [unit]`` shape and enum
        # values render as a merged-interval list, both anchored under
        # ``Byte[0]:``.
        assert (
            "Value Range:\n\t\t\tByte[0]:\n\t\t\t    0 ~ 100 C"
        ) in rendered_22
        assert (
            "Value Range:\n\t\t\tByte[0]:\n\t\t\t    0x00~0x02"
        ) in rendered_22
