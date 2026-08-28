"""Unit tests for FSCSGenerator (generate_fscs.py) and its builder helpers.

After the v1.1 refactor Phase 1 only writes ``fscs.json`` and
``fscs_generation_report.txt``; ``FSCS_22.txt`` / ``FSCS_2E.txt`` are
now produced by the UI on Save. Tests below reflect that split.

Covers:

* rw_state → service_22/service_2e.supported routing (builder).
* application session mapping → ``service_XX.sessions`` (builder).
* security level resolution (L0+L1, L0-only, L1-only, neither).
* ``_derive_value_range`` enum/numeric precedence.
* :meth:`FSCSGenerator.generate` end-to-end against the tiny fixture:
  writes only ``fscs.json`` + report, used flags are preserved across
  regeneration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generate_fscs import FSCSGenerator
from fscs.builder import (
    _derive_security_levels,
    _derive_value_range,
    build_fscs_document,
)
from fscs.schema import FSCSSubField


def _make_record(**overrides) -> dict:
    """Minimal ``inputs/*.json`` record accepted by :func:`build_fscs_document`."""
    base = {
        "did_hex": "0xF190",
        "did_name_en": "BaselineCounter",
        "size_bytes": "1",
        "data_type": "Unsigned",
        "storage_pos": "EEPROM",
        "rw_state": "R",
        "supported_by_ecu": "Y",
        "access": {
            "service_22": {
                "application": {"default": "N", "extended": "N"},
                "security": {"level0": "N", "level1": "N"},
            },
            "service_2e": {
                "application": {"default": "N", "extended": "N"},
                "security": {"level0": "N", "level1": "N"},
            },
        },
        "sub_fields": [],
    }
    base.update(overrides)
    return base


class TestServiceRouting:
    """rw_state drives which of service_22 / service_2e is ``supported``."""

    def test_r_supports_22_only(self):
        doc = build_fscs_document([_make_record(rw_state="R")])
        did = doc.dids[0]
        assert did.service_22.supported is True
        assert did.service_2e.supported is False

    def test_rw_supports_both(self):
        doc = build_fscs_document([_make_record(rw_state="RW")])
        did = doc.dids[0]
        assert did.service_22.supported is True
        assert did.service_2e.supported is True

    def test_w_supports_2e_only(self):
        doc = build_fscs_document([_make_record(rw_state="W")])
        did = doc.dids[0]
        assert did.service_22.supported is False
        assert did.service_2e.supported is True


class TestSessionMapping:
    """``access.service_22.application.*`` → ``service_22.sessions`` list."""

    def test_default_and_extended(self):
        rec = _make_record(
            access={
                "service_22": {
                    "application": {"default": "Y", "extended": "Y"},
                    "security": {"level0": "N", "level1": "N"},
                },
                "service_2e": {
                    "application": {"default": "N", "extended": "N"},
                    "security": {"level0": "N", "level1": "N"},
                },
            },
        )
        doc = build_fscs_document([rec])
        assert doc.dids[0].service_22.sessions == [
            "defaultSession",
            "extendedDiagnosticSession",
        ]

    def test_neither(self):
        rec = _make_record()  # default access has everything N
        doc = build_fscs_document([rec])
        assert doc.dids[0].service_22.sessions == []


class TestSecurityLevels:
    """Policy: L0+L1 emits only L0; L0-only keeps L0; L1-only keeps L1."""

    def test_both_levels_output_l0_only(self):
        levels = _derive_security_levels(l0=True, l1=True, did_hex="0xF190")
        assert [lvl.level for lvl in levels] == ["L0"]

    def test_l1_only_outputs_l1(self):
        levels = _derive_security_levels(l0=False, l1=True, did_hex="0xF190")
        assert [lvl.level for lvl in levels] == ["L1"]

    def test_l0_only_keeps_l0(self):
        levels = _derive_security_levels(l0=True, l1=False, did_hex="0xF190")
        assert [lvl.level for lvl in levels] == ["L0"]
        assert levels[0].note  # explanatory note attached

    def test_neither_level_empty(self):
        levels = _derive_security_levels(l0=False, l1=False, did_hex="0xF190")
        assert levels == []


class TestValueRange:
    """``_derive_value_range`` picks enum over numeric and handles emptiness."""

    def test_enum_precedence_over_numeric(self):
        sf = FSCSSubField(
            byte_range="0",
            bit="All",
            name_en="x",
            range_min="0x00",
            range_max="0xFF",
            unit="",
            enum_mapping="0x00=A\n0x01=B",
        )
        vr = _derive_value_range([sf])
        assert vr.kind == "enum"
        assert vr.values == ["0x00", "0x01"]

    def test_numeric_when_no_enum(self):
        sf = FSCSSubField(
            byte_range="0",
            bit="All",
            name_en="x",
            range_min="0",
            range_max="255",
            unit="C",
            enum_mapping=None,
        )
        vr = _derive_value_range([sf])
        assert vr.kind == "numeric"
        assert vr.min == "0" and vr.max == "255" and vr.unit == "C"

    def test_no_sub_fields_none(self):
        vr = _derive_value_range([])
        assert vr.kind == "none"


class TestEndToEndGenerate:
    """v1.1: Phase 1 only produces ``fscs.json`` + report.

    The two ``FSCS_*.txt`` artefacts used to land here too; they now
    come out of the UI on Save, so the tests verify their *absence*
    from a standalone Phase 1 run and that the report is created.
    """

    def test_writes_json_and_report_only(self, fixtures_dir, tmp_path):
        gen = FSCSGenerator()
        out_json = tmp_path / "fscs.json"
        out_report = tmp_path / "fscs_generation_report.txt"
        result = gen.generate(
            input_path=fixtures_dir / "tiny_did.json",
            output_path_json=out_json,
            report_path=out_report,
        )

        assert out_json.is_file(), "fscs.json must be produced"
        assert out_report.is_file(), "generation report must be produced"
        assert not (tmp_path / "FSCS_22.txt").exists(), (
            "v1.1 Phase 1 must not write FSCS_22.txt; that's the UI's job"
        )
        assert not (tmp_path / "FSCS_2E.txt").exists(), (
            "v1.1 Phase 1 must not write FSCS_2E.txt; that's the UI's job"
        )

        # Counts come from the new result shape (kept / filtered /
        # skipped) and effective counts per service.
        assert result["kept"] == 5
        assert result["effective_22"] == 5
        assert result["effective_2e"] == 2

        doc = json.loads(out_json.read_text(encoding="utf-8"))
        assert {d["did_hex"] for d in doc["dids"]} == {
            "F190", "F18C", "F1A0", "F1A1", "F1A2",
        }

        report_text = out_report.read_text(encoding="utf-8")
        assert "FSCS Generation Report" in report_text
        assert "Kept (written to fscs.json)   : 5" in report_text

    def test_used_flags_preserved_across_regeneration(
        self, fixtures_dir, tmp_path
    ):
        """Re-running Phase 1 after UI edits must keep operator selections."""
        gen = FSCSGenerator()
        out_json = tmp_path / "fscs.json"
        out_report = tmp_path / "fscs_generation_report.txt"
        inputs = fixtures_dir / "tiny_did.json"

        gen.generate(
            input_path=inputs,
            output_path_json=out_json,
            report_path=out_report,
        )
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        f190 = next(d for d in doc["dids"] if d["did_hex"] == "F190")
        assert f190["service_22"]["used"] is True

        # Simulate the operator deselecting F190 and editing Behavior in CSV.
        f190["service_22"]["used"] = False
        f190["service_22"]["behavior"] = "custom read behavior"
        out_json.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        gen.generate(
            input_path=inputs,
            output_path_json=out_json,
            report_path=out_report,
        )
        doc2 = json.loads(out_json.read_text(encoding="utf-8"))
        f190_after = next(d for d in doc2["dids"] if d["did_hex"] == "F190")
        assert f190_after["service_22"]["used"] is False, (
            "Operator selection was lost on Phase 1 regeneration -- "
            "check the preservation path in generate_fscs.FSCSGenerator.generate."
        )
        assert f190_after["service_22"]["behavior"] == "custom read behavior"

    def test_reset_used_discards_previous_selection(
        self, fixtures_dir, tmp_path
    ):
        """``--reset-used`` forces every DID back to used=True."""
        gen = FSCSGenerator()
        out_json = tmp_path / "fscs.json"
        out_report = tmp_path / "fscs_generation_report.txt"
        inputs = fixtures_dir / "tiny_did.json"

        gen.generate(
            input_path=inputs,
            output_path_json=out_json,
            report_path=out_report,
        )
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        f190 = next(d for d in doc["dids"] if d["did_hex"] == "F190")
        f190["service_22"]["used"] = False
        out_json.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        gen.generate(
            input_path=inputs,
            output_path_json=out_json,
            report_path=out_report,
            reset_used=True,
        )
        doc2 = json.loads(out_json.read_text(encoding="utf-8"))
        f190_after = next(d for d in doc2["dids"] if d["did_hex"] == "F190")
        assert f190_after["service_22"]["used"] is True, (
            "--reset-used should have restored used=True"
        )

        report = out_report.read_text(encoding="utf-8")
        assert "--reset-used" in report, (
            "report must disclose that reset-used mode was active"
        )
