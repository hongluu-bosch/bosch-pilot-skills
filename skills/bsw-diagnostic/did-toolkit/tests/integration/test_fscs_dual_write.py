"""End-to-end integration test for Phase 1 + xlsx-import persistence.

The three FSCS artefacts are produced by two different steps:

* ``fscs.json`` -- Phase 1 (``generate_fscs.py``).
* ``FSCS_22.txt`` / ``FSCS_2E.txt`` -- CSV import persistence
  (:func:`fscs.save.save_all`), which rehydrates the document from
  ``fscs.json`` and emits the two text views.

This module drives both steps in sequence to check the two channels
still agree on the semantic view: every DID in the ``.txt`` files is
also in ``fscs.json`` with matching footer fields (Data Type / Storage
Position / NVM Item / R/W State / Size).
"""

from __future__ import annotations

import json
import re

import pytest

from generate_fscs import FSCSGenerator
from fscs import load_fscs_json
from fscs.save import fscs_paths, save_all


@pytest.fixture
def phase1_outputs(fixtures_dir, tmp_path):
    """Run Phase 1 (fscs.json) and then save txt views, return the triplet."""
    outputs_dir = tmp_path
    paths = fscs_paths(outputs_dir)
    out_json = paths["json"]
    out_report = out_json.parent / "fscs_generation_report.txt"

    # Phase 1: fscs.json + report only.
    gen = FSCSGenerator()
    gen.generate(
        input_path=fixtures_dir / "tiny_did.json",
        output_path_json=out_json,
        report_path=out_report,
    )
    assert out_json.is_file()
    assert not paths["txt_22"].exists(), (
        "Phase 1 must not write FSCS_22.txt"
    )
    assert not paths["txt_2e"].exists(), (
        "Phase 1 must not write FSCS_2E.txt"
    )

    # CSV import persistence: fscs.json -> txt pair. save_all rewrites
    # all three atomically, so after this call both txt files exist.
    document = load_fscs_json(out_json)
    save_all(document, paths)
    return paths["txt_22"], paths["txt_2e"], paths["json"]


class TestDualWriteSmoke:

    def test_all_three_artifacts_produced(self, phase1_outputs):
        out_22, out_2e, out_json = phase1_outputs
        assert out_22.is_file()
        assert out_2e.is_file()
        assert out_json.is_file()


class TestDualWriteEquivalence:

    def test_did_set_matches_between_json_and_txt_22(self, phase1_outputs):
        out_22, _, out_json = phase1_outputs
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        # v1.1: the txt reflects the ``effective`` subset (supported AND
        # used); on a fresh generation ``used=True`` for everyone so
        # the two sets happen to coincide with ``supported``.
        json_22 = {
            d["did_hex"] for d in doc["dids"]
            if d["service_22"]["supported"] and d["service_22"]["used"]
        }
        txt_22 = set(
            re.findall(r"Identifier\s+\$([0-9A-F]+)h", out_22.read_text(encoding="utf-8"))
        )
        assert json_22 == txt_22

    def test_did_set_matches_between_json_and_txt_2e(self, phase1_outputs):
        _, out_2e, out_json = phase1_outputs
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        json_2e = {
            d["did_hex"] for d in doc["dids"]
            if d["service_2e"]["supported"] and d["service_2e"]["used"]
        }
        txt_2e = set(
            re.findall(r"Identifier\s+\$([0-9A-F]+)h", out_2e.read_text(encoding="utf-8"))
        )
        assert json_2e == txt_2e

    def test_footer_fields_match_per_did(self, phase1_outputs):
        out_22, _, out_json = phase1_outputs
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        txt = out_22.read_text(encoding="utf-8")

        for block in txt.split("=" * 80):
            ident = re.search(r"Identifier\s+\$([0-9A-F]+)h", block)
            if not ident:
                continue
            did_hex = ident.group(1)
            entry = next((d for d in doc["dids"] if d["did_hex"] == did_hex), None)
            assert entry is not None, f"DID {did_hex} present in .txt but missing in JSON"

            m = re.search(r"Data Type:\s+(\S+)", block)
            if m:
                assert entry["data_type"] == m.group(1), f"{did_hex} data_type mismatch"

            m = re.search(r"Storage Position:\s+(\S+)", block)
            if m:
                assert entry["storage_position"] == m.group(1), f"{did_hex} storage mismatch"

            m = re.search(r"Size:\s+(\S+)\s+bytes", block)
            if m:
                assert str(entry["size_bytes"]) == m.group(1), f"{did_hex} size mismatch"

            m = re.search(r"NVM Item:[^\S\n]*([^\n]*)", block)
            if m:
                assert entry["nvm_item"] == m.group(1).rstrip(), (
                    f"{did_hex} nvm_item mismatch: .txt={m.group(1)!r} json={entry['nvm_item']!r}"
                )


class TestDualWriteRamEmptyNvm:
    """Dedicated coverage for the RAM-empty-NVM bug the migration fixed."""

    def test_ram_did_renders_empty_nvm_in_both_channels(self, phase1_outputs):
        out_22, _, out_json = phase1_outputs
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        live = next(d for d in doc["dids"] if d["did_hex"] == "F1A0")
        assert live["nvm_item"] == ""
        txt = out_22.read_text(encoding="utf-8")
        live_block = next(
            b for b in txt.split("=" * 80)
            if re.search(r"Identifier\s+\$F1A0h", b)
        )
        assert re.search(r"NVM Item:[ \t]*\n", live_block) is not None


class TestJsonShape:

    def test_schema_version_present(self, phase1_outputs):
        _, _, out_json = phase1_outputs
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        assert doc["schema_version"] == "1.5"

    def test_generator_metadata_embedded(self, phase1_outputs):
        _, _, out_json = phase1_outputs
        doc = json.loads(out_json.read_text(encoding="utf-8"))
        assert doc["generator"]["tool"].endswith("generate_fscs.py")
        assert doc["generator"]["source_inputs"].endswith("tiny_did.json")
