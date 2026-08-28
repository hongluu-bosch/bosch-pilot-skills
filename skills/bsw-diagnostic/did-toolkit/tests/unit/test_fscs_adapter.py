"""Unit tests for :mod:`scripts.fscs.adapter`.

The adapter is Step 3's single loading policy and the projection layer
that funnels the JSON-first FSCSDocument onto the legacy consumer
dataclasses (Phase 3's ``DIDImplementationInfo``). These tests pin both
contracts:

* ``load_fscs`` picks the correct source (explicit JSON, sibling JSON,
  or legacy TXT fallback) and raises only when nothing is resolvable.
* ``to_did_implementation_infos`` mirrors ``parse_both_fscs``'s
  classification (``ERROR`` for write-only, ``SKIPPED`` for recoverable
  per-DID issues, ``SUCCESS`` otherwise) and hex-sorted order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fscs import (
    FSCSProject,
    build_fscs_document,
    load_fscs,
    load_fscs_json,
    save_fscs_json,
    to_did_implementation_infos,
    to_review_dicts,
)


_BASE_PROJECT = FSCSProject(
    customer_name="TestCustomer",
)


def _record(**overrides):
    """Baseline raw DID record (mirrors ``tiny_did.json``)."""
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
            },
            "service_2e": {
                "application": {"default": "N", "programming": "N", "extended": "N"},
            },
        },
        "sub_fields": [
            {
                "byte": "0",
                "bit": "All",
                "name_en": "value",
                "range_min_phy": "0",
                "range_max_phy": "255",
            }
        ],
    }
    base.update(overrides)
    return base


class TestLoadFscsResolution:
    """``load_fscs`` source-picking behaviour."""

    def test_explicit_json_wins(self, tmp_path):
        doc = build_fscs_document([_record()], project=_BASE_PROJECT)
        json_path = tmp_path / "custom.json"
        save_fscs_json(doc, json_path)

        loaded = load_fscs(fscs_json=json_path)
        assert [d.did_hex for d in loaded.dids] == ["F190"]

    def test_sibling_json_auto_discovered(self, tmp_path):
        doc = build_fscs_document([_record()], project=_BASE_PROJECT)
        fscs_dir = tmp_path / "outputs" / "fscs"
        fscs_dir.mkdir(parents=True)
        save_fscs_json(doc, fscs_dir / "fscs.json")

        # Point the loader at TXT paths that don't exist; it should
        # still prefer the sibling fscs.json.
        loaded = load_fscs(
            fscs_22=fscs_dir / "FSCS_22.txt",
            fscs_2e=fscs_dir / "FSCS_2E.txt",
        )
        assert [d.did_hex for d in loaded.dids] == ["F190"]

    def test_nothing_supplied_raises(self):
        with pytest.raises(FileNotFoundError):
            load_fscs()

    def test_txt_only_does_not_fall_back(self, tmp_path):
        """Part 6 removed the runtime TXT fallback.

        When ``fscs.json`` is missing, :func:`load_fscs` must raise
        ``FileNotFoundError`` with a Phase 1 hint rather than silently
        parse ``FSCS_*.txt`` -- the drift that would reintroduce is
        exactly what the governance migration closed. Migrating a
        legacy project is now the explicit job of
        ``scripts/fscs_import.py``.
        """
        fscs_dir = tmp_path / "outputs" / "fscs"
        fscs_dir.mkdir(parents=True)
        txt_22 = fscs_dir / "FSCS_22.txt"
        txt_22.write_text(
            "Identifier $F190h - BaselineCounter\n"
            "\n"
            "Data Type:\tUnsigned\n"
            "Storage Position:\tEEPROM\n"
            "Size:\t1\tbytes\n"
            "R/W State:\tR\n"
            "NVM Item:\tNVM_ID_DCOM_BaselineCounter\n"
            "Value Range:\t0 ~ 255\n"
            + ("=" * 80)
            + "\n",
            encoding="utf-8",
        )
        with pytest.raises(FileNotFoundError) as excinfo:
            load_fscs(fscs_22=txt_22)
        msg = str(excinfo.value)
        assert "fscs.json" in msg
        assert "Phase 1" in msg or "fscs_import.py" in msg


class TestProjectionContract:
    """``to_did_implementation_infos`` classification + ordering."""

    def test_hex_sorted_order(self):
        # Build a document with DIDs in non-hex order.
        doc = build_fscs_document(
            [
                _record(did_hex="0xF1A0", did_name_en="Bravo"),
                _record(did_hex="0xF190", did_name_en="Alpha"),
                _record(did_hex="0xF18C", did_name_en="Zulu"),
            ],
            project=_BASE_PROJECT,
        )
        valid, report = to_did_implementation_infos(doc)

        # Report must be hex-ascending regardless of input order.
        assert [e["did_hex"] for e in report] == ["0xF18C", "0xF190", "0xF1A0"]
        assert [d.did_hex for d in valid] == ["0xF18C", "0xF190", "0xF1A0"]

    def test_success_status_for_read_only(self):
        doc = build_fscs_document([_record()], project=_BASE_PROJECT)
        valid, report = to_did_implementation_infos(doc)

        assert report[0]["status"] == "SUCCESS"
        assert report[0]["errors"] == []
        assert len(valid) == 1
        assert valid[0].rw_state == "R"

    def test_rw_promotion_and_validation(self):
        """Dual-service DIDs promote to RW and pick up the write checks."""
        rec = _record(
            rw_state="RW",
            access={
                "service_22": {
                    "application": {"default": "Y", "programming": "N", "extended": "Y"},
                    "security": {"level0": "Y", "level1": "N"},
                },
                "service_2e": {
                    "application": {"default": "N", "programming": "N", "extended": "Y"},
                    "security": {"level0": "N", "level1": "Y"},
                },
            },
        )
        doc = build_fscs_document([rec], project=_BASE_PROJECT)
        valid, report = to_did_implementation_infos(doc)

        assert report[0]["status"] == "SUCCESS"
        assert len(valid) == 1
        assert valid[0].rw_state == "RW"

    def test_write_only_is_error_not_skipped(self):
        """Legacy parse_both_fscs hard-errors on write-only; mirror that."""
        rec = _record(
            rw_state="W",
            access={
                "service_22": {
                    "application": {"default": "N", "programming": "N", "extended": "N"},
                },
                "service_2e": {
                    "application": {"default": "N", "programming": "N", "extended": "Y"},
                },
            },
        )
        doc = build_fscs_document([rec], project=_BASE_PROJECT)
        valid, report = to_did_implementation_infos(doc)

        assert valid == []
        assert report[0]["status"] == "ERROR"
        assert any("write-only" in err for err in report[0]["errors"])

    def test_enum_and_numeric_projection(self):
        """``is_enum`` / ``enum_values`` / ``numeric_min`` / ``numeric_max``
        must be populated from the tagged-union value range."""
        enum_rec = _record(
            did_hex="0xF18C",
            did_name_en="ModeSelector",
            sub_fields=[
                {
                    "byte": "0",
                    "bit": "All",
                    "name_en": "mode",
                    # Builder recognises enums via ``method_en`` key=value
                    # syntax; values flow through to FSCSValueRangeEnum.
                    "method_en": "0x00=Off\n0x01=On\n0x02=Auto",
                }
            ],
        )
        numeric_rec = _record(
            did_hex="0xF1A0",
            did_name_en="LiveTemperature",
            sub_fields=[
                {
                    "byte": "0",
                    "bit": "All",
                    "name_en": "temp",
                    "range_min_phy": "-40",
                    "range_max_phy": "125",
                    "unit": "degC",
                }
            ],
        )
        doc = build_fscs_document([enum_rec, numeric_rec], project=_BASE_PROJECT)
        valid, _ = to_did_implementation_infos(doc)

        by_hex = {d.did_hex: d for d in valid}
        assert by_hex["0xF18C"].is_enum is True
        assert by_hex["0xF18C"].enum_values == ["0x00", "0x01", "0x02"]
        assert by_hex["0xF1A0"].is_enum is False
        assert by_hex["0xF1A0"].numeric_min == "-40"
        assert by_hex["0xF1A0"].numeric_max == "125"
        # Value range string keeps the unit suffix for downstream parsers.
        assert "degC" in by_hex["0xF1A0"].value_range


class TestReviewProjection:
    """``to_review_dicts`` reshape contract (review_arxml + review_impl)."""

    def test_fields_mirror_input_json_shape(self):
        """Reviewers still reach into ``did_name_en``, ``access.service_*``
        and ``sub_fields[].method_en``; the projection must supply them.
        """
        rec = _record(
            rw_state="RW",
            access={
                "service_22": {
                    "application": {"default": "Y", "programming": "N", "extended": "Y"},
                    "security": {"level0": "Y", "level1": "N"},
                },
                "service_2e": {
                    "application": {"default": "N", "programming": "N", "extended": "Y"},
                    "security": {"level0": "N", "level1": "Y"},
                },
            },
        )
        doc = build_fscs_document([rec], project=_BASE_PROJECT)
        reviews = to_review_dicts(doc)

        assert len(reviews) == 1
        r = reviews[0]
        assert r["did_hex"] == "F190"           # bare upper hex
        assert r["did_name_en"] == "BaselineCounter"
        assert r["size_bytes"] == 1
        assert r["rw_state"] == "RW"
        assert r["storage_pos"] == "EEPROM"
        assert r["supported_by_ecu"] == "Y"
        assert r["access"]["service_22"]["_"] == "Y"
        assert r["access"]["service_2e"]["_"] == "Y"

    def test_unsupported_service_projects_n(self):
        """service_2e with no ``Y`` leaves must appear as ``_: N``."""
        doc = build_fscs_document([_record()], project=_BASE_PROJECT)
        reviews = to_review_dicts(doc)
        assert reviews[0]["access"]["service_2e"]["_"] == "N"

    def test_sub_field_range_mapping(self):
        """``range_min`` / ``range_max`` / ``enum_mapping`` remap onto
        the legacy ``range_min_phy`` / ``range_max_phy`` / ``method_en``
        keys that ``ImplReviewer._has_range`` depends on."""
        enum_rec = _record(
            did_hex="0xF18C",
            did_name_en="ModeSelector",
            sub_fields=[{
                "byte": "0",
                "bit": "All",
                "name_en": "mode",
                "method_en": "0x00=Off\n0x01=On",
            }],
        )
        doc = build_fscs_document([enum_rec], project=_BASE_PROJECT)
        reviews = to_review_dicts(doc)
        sub = reviews[0]["sub_fields"][0]
        assert sub["method_en"] == "0x00=Off\n0x01=On"
        assert sub["name_en"] == "mode"


class TestUsedFlagPropagation:
    """Operator ``used`` selections must gate downstream projections.

    These tests pin the Phase 2 / Phase 3 / Review behaviour for
    deselected DIDs: dropped from ``to_review_dicts`` entirely, and
    bucketed as ``DESELECTED`` (not ``ERROR``) in
    ``to_did_implementation_infos``. The documents still round-trip
    through ``fscs.json`` unchanged -- ``used`` is a downstream gate,
    not a data deletion.
    """

    def test_to_review_dicts_skips_fully_deselected(self):
        rec_kept = _record()
        rec_drop = _record(did_hex="0xF1A0", did_name_en="Dropped")
        doc = build_fscs_document(
            [rec_kept, rec_drop], project=_BASE_PROJECT,
        )
        drop = next(d for d in doc.dids if d.did_hex == "F1A0")
        drop.service_22.used = False
        drop.service_2e.used = False

        reviews = to_review_dicts(doc)

        hexes = {r["did_hex"] for r in reviews}
        assert hexes == {"F190"}, (
            "Deselected DIDs must not appear in reviewer projections; "
            "they've been excluded from emitted artefacts by operator "
            "choice and cross-checks would false-positive."
        )

    def test_to_review_dicts_reflects_partial_deselection(self):
        """RW DID with ``used_2e=False`` projects as read-only."""
        rec = _record(
            rw_state="RW",
            access={
                "service_22": {
                    "application": {"default": "Y", "extended": "Y"},
                    "security": {"level0": "Y", "level1": "N"},
                },
                "service_2e": {
                    "application": {"default": "N", "extended": "Y"},
                    "security": {"level0": "N", "level1": "Y"},
                },
            },
        )
        doc = build_fscs_document([rec], project=_BASE_PROJECT)
        doc.dids[0].service_2e.used = False

        reviews = to_review_dicts(doc)
        assert reviews[0]["access"]["service_22"]["_"] == "Y"
        assert reviews[0]["access"]["service_2e"]["_"] == "N", (
            "Deselecting the write service must flip the projected "
            "service_2e cell to N so the reviewer sees the same scope "
            "the C generator actually emitted."
        )

    def test_to_impl_infos_marks_fully_deselected_as_deselected(self):
        rec_kept = _record()
        rec_drop = _record(did_hex="0xF1A0", did_name_en="Dropped")
        doc = build_fscs_document(
            [rec_kept, rec_drop], project=_BASE_PROJECT,
        )
        drop = next(d for d in doc.dids if d.did_hex == "F1A0")
        drop.service_22.used = False
        drop.service_2e.used = False

        valid, report = to_did_implementation_infos(doc)

        valid_hexes = [d.did_hex for d in valid]
        assert valid_hexes == ["0xF190"], (
            "Deselected DIDs must not contribute generated C code."
        )
        drop_report = next(r for r in report if r["did_hex"] == "0xF1A0")
        assert drop_report["status"] == "DESELECTED", (
            "Deselected status must be distinct from ERROR / SKIPPED "
            "so validation_report.txt tells a reviewer the exclusion "
            "was an operator decision, not a toolkit failure."
        )

    def test_rw_did_with_2e_deselected_becomes_read_only(self):
        """Demote rw_state to R when the operator unchecks 2E."""
        rec = _record(
            rw_state="RW",
            access={
                "service_22": {
                    "application": {"default": "Y", "extended": "Y"},
                    "security": {"level0": "Y"},
                },
                "service_2e": {
                    "application": {"default": "N", "extended": "Y"},
                    "security": {"level1": "Y"},
                },
            },
        )
        doc = build_fscs_document([rec], project=_BASE_PROJECT)
        doc.dids[0].service_2e.used = False

        valid, _report = to_did_implementation_infos(doc)
        assert len(valid) == 1
        assert valid[0].rw_state == "R", (
            "Deselecting only the 2E side must demote the DID to read-only "
            "in Phase 3 output -- otherwise the generator emits write "
            "functions the operator explicitly excluded."
        )
