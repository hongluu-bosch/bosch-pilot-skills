"""Unit tests for the v1.13.0 differential B: reviewer-from-emitted-set.

The bug class fixed by differential B is the **per-axis false
positive on dropped DIDs**: in v1.12.x, when the generator's
classifier dropped a DID (DESELECTED, write-only ERROR, or
RW-compliance SKIPPED), the reviewer would still expect it in the
ARXML and report ``COVERAGE`` / ``IDENTIFIER`` / ``SIZE`` /
``INFOREF`` / ``FUNCTION`` issues against it -- noise the operator
had to grep through to find real issues.

These tests pin the new contract:

1. The same ``fscs.json`` that produces N SUCCESS DIDs in the
   generator must produce **zero coverage issues** in the reviewer
   when the ARXML faithfully contains those N DIDs (the legacy
   ``supported_by_ecu`` filter would have inflated the expected set
   to include DESELECTED / SKIPPED / ERROR DIDs and miscount).
2. The reviewer's ``self.emitted`` projection has the right shape
   for the per-axis checks to consume.
3. The fallback to ``supported_by_ecu`` is preserved for legacy
   callers that build :class:`ARXMLReviewer` and inject
   ``dids_json`` directly without ``load_from_fscs_json``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from review_arxml import ARXMLReviewer
from generate_arxml import ARXMLGenerator
from fscs.schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSServiceAccess,
    FSCSSecurityLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    *,
    supported: bool = True,
    used: bool = True,
    sessions=("defaultSession",),
    security_level: str = "L0",
) -> FSCSServiceAccess:
    """Build a service-side access record with the toolkit's defaults."""
    return FSCSServiceAccess(
        supported=supported,
        used=used,
        sessions=list(sessions),
        security_levels=[FSCSSecurityLevel(level=security_level)],
    )


def _make_did(
    *,
    did_hex: str,
    did_name: str,
    rw_state: str = "R",
    storage: str = "EEPROM",
    size: int = 4,
    nvm_item: str = "NVM_ID_DCOM_TEST",
    service_22: FSCSServiceAccess,
    service_2e: FSCSServiceAccess,
) -> DIDFscsEntry:
    return DIDFscsEntry(
        did_hex=did_hex,
        did_name=did_name,
        data_type="Unsigned",
        storage_position=storage,
        size_bytes=size,
        rw_state=rw_state,
        nvm_item=nvm_item,
        service_22=service_22,
        service_2e=service_2e,
    )


# ---------------------------------------------------------------------------
# Test 1 -- The "central" claim: deselected DIDs do not count as missing
# ---------------------------------------------------------------------------


def test_deselected_did_does_not_produce_coverage_issue(tmp_path):
    """A DID with both services ``used=False`` is DESELECTED by the
    generator, so the reviewer must not flag its absence as a
    COVERAGE issue."""
    document = FSCSDocument(
        dids=[
            _make_did(
                did_hex="F190",
                did_name="Vin",
                rw_state="R",
                service_22=_make_service(supported=True, used=True),
                service_2e=_make_service(supported=False, used=False),
            ),
            _make_did(
                did_hex="0102",
                did_name="DeselectedDid",
                rw_state="RW",
                service_22=_make_service(supported=True, used=False),
                service_2e=_make_service(supported=True, used=False),
            ),
        ]
    )

    fscs_json = tmp_path / "fscs.json"
    fscs_json.write_text(document.model_dump_json(), encoding="utf-8")

    output_arxml = tmp_path / "DID_Config.arxml"
    gen = ARXMLGenerator()
    gen.generate(
        output_path=output_arxml,
        fscs_json_path=fscs_json,
        product_type="DPB",
        report_dir=tmp_path,
    )

    reviewer = ARXMLReviewer()
    reviewer.parse_arxml(output_arxml)
    reviewer.load_from_fscs_json(fscs_json)
    reviewer.review_coverage()

    coverage_issues = [i for i in reviewer.issues if i.type == "COVERAGE"]
    deselected_coverage = [
        i for i in coverage_issues if "0x0102" in i.did or "DeselectedDid" in i.message
    ]
    assert deselected_coverage == [], (
        f"Reviewer reported COVERAGE issues against the deselected DID 0x0102: "
        f"{[i.message for i in deselected_coverage]}"
    )


def test_write_only_did_does_not_produce_coverage_issue(tmp_path):
    """A DID effective only on $2E (write-only) is dropped as ERROR
    by the generator; reviewer must not COVERAGE-flag it."""
    document = FSCSDocument(
        dids=[
            _make_did(
                did_hex="F190",
                did_name="Vin",
                rw_state="R",
                service_22=_make_service(supported=True, used=True),
                service_2e=_make_service(supported=False, used=False),
            ),
            _make_did(
                did_hex="0103",
                did_name="WriteOnlyDid",
                rw_state="W",
                service_22=_make_service(supported=False, used=False),
                service_2e=_make_service(
                    supported=True,
                    used=True,
                    sessions=("extendedDiagnosticSession",),
                    security_level="L1",
                ),
            ),
        ]
    )

    fscs_json = tmp_path / "fscs.json"
    fscs_json.write_text(document.model_dump_json(), encoding="utf-8")

    output_arxml = tmp_path / "DID_Config.arxml"
    gen = ARXMLGenerator()
    gen.generate(
        output_path=output_arxml,
        fscs_json_path=fscs_json,
        product_type="DPB",
        report_dir=tmp_path,
    )

    reviewer = ARXMLReviewer()
    reviewer.parse_arxml(output_arxml)
    reviewer.load_from_fscs_json(fscs_json)
    reviewer.review_coverage()

    coverage_issues = [i for i in reviewer.issues if i.type == "COVERAGE"]
    write_only_noise = [
        i for i in coverage_issues
        if "0x0103" in i.did or "WriteOnlyDid" in i.message
    ]
    assert write_only_noise == [], (
        f"Reviewer reported COVERAGE noise against the write-only ERROR DID "
        f"0x0103: {[i.message for i in write_only_noise]}"
    )


def test_rw_compliance_skipped_did_does_not_produce_coverage_issue(tmp_path):
    """An RW DID with non-compliant write-side session/security gets
    SKIPPED by the generator (e.g. write side missing
    ``extendedDiagnosticSession``); the reviewer must not flag its
    absence."""
    document = FSCSDocument(
        dids=[
            _make_did(
                did_hex="F190",
                did_name="Vin",
                rw_state="R",
                service_22=_make_service(supported=True, used=True),
                service_2e=_make_service(supported=False, used=False),
            ),
            _make_did(
                did_hex="0104",
                did_name="NonCompliantRw",
                rw_state="RW",
                service_22=_make_service(supported=True, used=True),
                service_2e=_make_service(
                    supported=True,
                    used=True,
                    # Compliance violation: write needs extendedDiagnosticSession
                    sessions=("defaultSession",),
                    security_level="L1",
                ),
            ),
        ]
    )

    fscs_json = tmp_path / "fscs.json"
    fscs_json.write_text(document.model_dump_json(), encoding="utf-8")

    output_arxml = tmp_path / "DID_Config.arxml"
    gen = ARXMLGenerator()
    gen.generate(
        output_path=output_arxml,
        fscs_json_path=fscs_json,
        product_type="DPB",
        report_dir=tmp_path,
    )

    reviewer = ARXMLReviewer()
    reviewer.parse_arxml(output_arxml)
    reviewer.load_from_fscs_json(fscs_json)
    reviewer.review_coverage()
    reviewer.review_identifiers()
    reviewer.review_data_size()
    reviewer.review_info_refs()

    noise = [
        i for i in reviewer.issues
        if "0x0104" in i.did or "NonCompliantRw" in i.message
    ]
    assert noise == [], (
        f"Reviewer reported issues against the SKIPPED DID 0x0104 across "
        f"axes: {[(i.type, i.message) for i in noise]}"
    )


# ---------------------------------------------------------------------------
# Test 2 -- emitted projection shape
# ---------------------------------------------------------------------------


def test_set_emitted_projects_dids_into_reviewer_dict_shape(tmp_path):
    """``set_emitted`` must produce the four-key dict shape the
    per-axis checks consume: did_hex / did_name_en / size_bytes /
    rw_state."""
    document = FSCSDocument(
        dids=[
            _make_did(
                did_hex="F190",
                did_name="Vin",
                rw_state="R",
                service_22=_make_service(supported=True, used=True),
                service_2e=_make_service(supported=False, used=False),
            ),
        ]
    )
    fscs_json = tmp_path / "fscs.json"
    fscs_json.write_text(document.model_dump_json(), encoding="utf-8")

    reviewer = ARXMLReviewer()
    reviewer.load_from_fscs_json(fscs_json)
    assert len(reviewer.emitted) == 1
    row = reviewer.emitted[0]
    assert set(row.keys()) >= {"did_hex", "did_name_en", "size_bytes", "rw_state"}
    assert row["did_hex"] == "0xF190"
    assert row["did_name_en"] == "Vin"
    assert row["rw_state"] == "R"


# ---------------------------------------------------------------------------
# Test 3 -- legacy fallback path is preserved
# ---------------------------------------------------------------------------


def test_legacy_supported_by_ecu_fallback_when_emitted_unset():
    """Tests that construct ARXMLReviewer directly (no
    load_from_fscs_json call) and inject ``dids_json`` must still see
    the v1.12.x ``supported_by_ecu`` filter applied. Backward
    compatibility for the existing test_review_arxml.py fixtures."""
    reviewer = ARXMLReviewer()
    reviewer.dids_json = [
        {"did_hex": "0x1111", "did_name_en": "A", "supported_by_ecu": "Y"},
        {"did_hex": "0x2222", "did_name_en": "B", "supported_by_ecu": "N"},
        {"did_hex": "0x3333", "did_name_en": "C"},  # no field -> defaults to Y
    ]
    # emitted is empty -> falls back to legacy filter
    effective = reviewer._effective_dids()
    hex_set = {d["did_hex"] for d in effective}
    assert hex_set == {"0x1111", "0x3333"}
