"""Tests for the v1.1 ``fscs_generation_report.txt`` artefact.

Phase 1 now produces a generation report summarising which DIDs were
kept, filtered out, or skipped with errors. Downstream operators lean
on this report to triage upstream JSON problems without opening the
raw input file, so the content must be stable and informative.

Covered behaviours:

* Report exists after every Phase 1 run (even a fully-clean input).
* Summary counts match the actual build outcome (kept / filtered /
  skipped).
* Each skipped record carries its DID hex (when recoverable) and a
  human-readable reason.
* Records filtered by ``supported_by_ecu != Y`` are counted separately
  from records rejected by Pydantic (skipped).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generate_fscs import FSCSGenerator


def _write(path: Path, records: list) -> Path:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _baseline_record(**over) -> dict:
    rec = {
        "did_hex": "0xF190",
        "did_name_en": "BaselineCounter",
        "size_bytes": "1",
        "data_type": "Unsigned",
        "storage_pos": "EEPROM",
        "rw_state": "R",
        "supported_by_ecu": "Y",
        "access": {
            "service_22": {
                "application": {"default": "Y", "extended": "Y"},
                "security": {"level0": "N", "level1": "N"},
            },
            "service_2e": {
                "application": {"default": "N", "extended": "N"},
                "security": {"level0": "N", "level1": "N"},
            },
        },
        "sub_fields": [],
    }
    rec.update(over)
    return rec


class TestReportAlwaysWritten:

    def test_clean_input_still_produces_report(self, tmp_path):
        inp = _write(tmp_path / "did.json", [_baseline_record()])
        gen = FSCSGenerator()
        report = tmp_path / "fscs_generation_report.txt"
        gen.generate(
            input_path=inp,
            output_path_json=tmp_path / "fscs.json",
            report_path=report,
        )
        assert report.is_file()
        text = report.read_text(encoding="utf-8")
        assert "FSCS Generation Report" in text
        assert "Kept" in text and "Skipped" in text and "Filtered" in text


class TestSummaryCountsMatch:

    def test_kept_filtered_skipped_counts(self, tmp_path):
        records = [
            _baseline_record(did_hex="0xF190"),
            # Filter: supported_by_ecu = N
            _baseline_record(did_hex="0xF191", supported_by_ecu="N"),
            # Skip: did_hex has non-hex chars, which the pydantic
            # validator in ``DIDFscsEntry`` flags (rw_state is coerced
            # to "R" by the builder's normaliser, so don't use that
            # field for validation-failure tests).
            _baseline_record(did_hex="0xZZZZ"),
        ]
        inp = _write(tmp_path / "did.json", records)

        gen = FSCSGenerator()
        report = tmp_path / "fscs_generation_report.txt"
        result = gen.generate(
            input_path=inp,
            output_path_json=tmp_path / "fscs.json",
            report_path=report,
        )
        # Return value should mirror the report.
        assert result["kept"] == 1
        assert result["filtered"] == 1
        assert result["skipped"] == 1

        text = report.read_text(encoding="utf-8")
        assert "Kept (written to fscs.json)   : 1" in text
        assert "Filtered (supported_by_ecu=N) : 1" in text
        assert "Skipped (schema errors)       : 1" in text


class TestSkippedRecordDiagnostics:

    def test_skipped_record_lists_did_hex_and_reason(self, tmp_path):
        records = [
            _baseline_record(did_hex="0xZZZZ"),
        ]
        inp = _write(tmp_path / "did.json", records)
        gen = FSCSGenerator()
        report = tmp_path / "fscs_generation_report.txt"
        gen.generate(
            input_path=inp,
            output_path_json=tmp_path / "fscs.json",
            report_path=report,
        )
        text = report.read_text(encoding="utf-8")
        # The report must name the DID (as supplied in the input) and
        # describe the failure. We don't pin the exact Pydantic wording
        # (it varies across versions) but ``did_hex`` is the field that
        # failed and ``ZZZZ`` is the offending value.
        assert "ZZZZ" in text
        assert "did_hex" in text


class TestJsonExcludesSkipped:

    def test_skipped_records_do_not_land_in_fscs_json(self, tmp_path):
        records = [
            _baseline_record(did_hex="0xF190"),
            _baseline_record(did_hex="0xZZZZ"),
        ]
        inp = _write(tmp_path / "did.json", records)
        gen = FSCSGenerator()
        out_json = tmp_path / "fscs.json"
        gen.generate(
            input_path=inp,
            output_path_json=out_json,
            report_path=tmp_path / "report.txt",
        )
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        kept = {d["did_hex"] for d in doc["dids"]}
        assert kept == {"F190"}, (
            "Skipped DIDs must stay out of fscs.json; keeping them would "
            "defeat the whole point of per-record validation"
        )
