"""Unit tests for FSCSReviewer (review_fscs.py).

The reviewer has four concrete checks:
  * review_only_2e_dids    - flags write-only DIDs missing from FSCS_22.
  * review_compliance_22   - default+extended + L0 required.
  * review_compliance_2e   - extended-only + L1 required, no defaultSession.
  * review_consistency     - FSCS vs JSON intersection + rw_state match.

Part 6 migrated the reviewer to source DIDs exclusively from
``fscs.json`` (via :meth:`FSCSReviewer.populate_from_document`). The
tests here seed a synthetic :class:`FSCSDocument` so each rule can be
exercised in isolation, then assert on ``reviewer.issues`` by type and
message keyword.
"""

from __future__ import annotations

import json

import pytest

from fscs.schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSSecurityLevel,
    FSCSServiceAccess,
)

# The dangerous sys.stdout/stderr re-wrapping in review_fscs.py is sandboxed
# by conftest.py::_preload_review_fscs before pytest starts. Here we just
# consume the cached module entry.
from review_fscs import FSCSReviewer


def _svc(supported: bool, sessions=None, levels=None) -> FSCSServiceAccess:
    return FSCSServiceAccess(
        supported=supported,
        sessions=sessions or [],
        security_levels=[FSCSSecurityLevel(level=lv) for lv in (levels or [])],
    )


def _entry(
    did_hex: str,
    name: str,
    *,
    rw: str,
    svc22: FSCSServiceAccess,
    svc2e: FSCSServiceAccess,
) -> DIDFscsEntry:
    """Minimal ``DIDFscsEntry`` covering all mandatory schema fields.

    ``data_type=Unsigned``, ``storage_position=RAM``, ``size_bytes=1``
    and ``nvm_item=""`` are fixed across these fixtures -- none of the
    compliance/consistency checks look at them, they only exist to
    satisfy pydantic validation.
    """
    return DIDFscsEntry(
        did_hex=did_hex,
        did_name=name,
        data_type="Unsigned",
        storage_position="RAM",
        size_bytes=1,
        rw_state=rw,
        nvm_item="",
        service_22=svc22,
        service_2e=svc2e,
    )


@pytest.fixture
def seeded(tmp_path):
    """Seed an ``FSCSDocument`` with three DIDs covering each rule + a JSON input.

    * F190 ("Clean"): 22 default+extended + L0, no 2E       -> no issue.
    * F18C ("RwDid"): 22 OK, 2E uses defaultSession (bad)  -> COMPLIANCE.
    * F1B0 ("WriteOnly"): 2E only                          -> BUSINESS +
                                                              CONSISTENCY
                                                              (missing
                                                              from JSON).
    """
    doc = FSCSDocument(dids=[
        _entry(
            "F190", "Clean",
            rw="R",
            svc22=_svc(True,
                       ["defaultSession", "extendedDiagnosticSession"],
                       ["L0"]),
            svc2e=_svc(False),
        ),
        _entry(
            "F18C", "RwDid",
            rw="RW",
            svc22=_svc(True,
                       ["defaultSession", "extendedDiagnosticSession"],
                       ["L0"]),
            svc2e=_svc(True,
                       ["defaultSession", "extendedDiagnosticSession"],
                       ["L1"]),
        ),
        _entry(
            "F1B0", "WriteOnly",
            rw="W",
            svc22=_svc(False),
            svc2e=_svc(True, ["extendedDiagnosticSession"], ["L1"]),
        ),
    ])

    input_json = tmp_path / "input.json"
    input_json.write_text(
        json.dumps(
            [
                {"did_hex": "0xF190", "supported_by_ecu": "Y", "rw_state": "R"},
                {"did_hex": "0xF18C", "supported_by_ecu": "Y", "rw_state": "RW"},
                # F1B0 intentionally absent -> CONSISTENCY extra_in_fscs.
            ]
        ),
        encoding="utf-8",
    )
    return doc, input_json


class TestFSCSReviewer:
    def test_write_only_flagged_as_business(self, seeded):
        doc, input_json = seeded
        r = FSCSReviewer()
        r.populate_from_document(doc)
        r.parse_json_input(input_json)
        r.review_only_2e_dids()

        business = [i for i in r.issues if i.type == "BUSINESS"]
        assert len(business) == 1
        assert business[0].did == "0xF1B0"

    def test_service_2e_default_session_is_compliance_issue(self, seeded):
        doc, input_json = seeded
        r = FSCSReviewer()
        r.populate_from_document(doc)
        r.parse_json_input(input_json)
        r.review_compliance_2e()

        msgs = [i.message for i in r.issues if i.type == "COMPLIANCE" and i.service == "2E"]
        assert any("defaultSession" in m for m in msgs)

    def test_consistency_flags_fscs_extras(self, seeded):
        doc, input_json = seeded
        r = FSCSReviewer()
        r.populate_from_document(doc)
        r.parse_json_input(input_json)
        r.review_consistency()

        consistency = [i for i in r.issues if i.type == "CONSISTENCY"]
        extras = [i for i in consistency if "JSON" in i.message]
        # F1B0 is in FSCS_2E but missing from input JSON -> extra_in_fscs.
        assert any(i.did == "0xF1B0" for i in extras)

    def test_generate_report_writes_file(self, seeded, tmp_path):
        doc, input_json = seeded
        r = FSCSReviewer()
        r.populate_from_document(doc)
        r.parse_json_input(input_json)
        r.review_only_2e_dids()
        r.review_compliance_22()
        r.review_compliance_2e()
        r.review_consistency()

        report_path = tmp_path / "review.txt"
        result = r.generate_report(report_path)
        assert report_path.is_file()
        assert result["has_issues"] is True
        assert result["summary"]["business"] >= 1
        assert result["summary"]["dids_22_count"] == 2
        assert result["summary"]["dids_2e_count"] == 2

    def test_deselected_did_is_skipped_by_all_review_checks(self, tmp_path):
        deselected = _entry(
            "F1C0", "Deselected",
            rw="RW",
            svc22=_svc(True, [], []),
            svc2e=_svc(True, ["defaultSession"], []),
        )
        deselected.service_22.used = False
        deselected.service_2e.used = False
        doc = FSCSDocument(dids=[deselected])
        input_json = tmp_path / "input.json"
        input_json.write_text(
            json.dumps([
                {"did_hex": "0xF1C0", "supported_by_ecu": "Y", "rw_state": "RW"},
            ]),
            encoding="utf-8",
        )

        r = FSCSReviewer()
        r.populate_from_document(doc)
        r.parse_json_input(input_json)
        r.review_only_2e_dids()
        r.review_compliance_22()
        r.review_compliance_2e()
        r.review_consistency()

        assert r.dids_22 == {}
        assert r.dids_2e == {}
        assert r.deselected_dids == {"0xF1C0"}
        assert r.issues == []
