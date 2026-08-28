"""Unit tests for per-DID product-type filtering.

Three concerns:

1. **Phase 1 default-fill** (``apply_product_type_defaults``):
   every DID has a non-empty ``product_type`` post-load (schema
   migrator + field validator collapse missing / None / blank to
   the wildcard ``"Common"``). When the caller passes a non-empty
   non-Common ``default_product_type``, entries still showing the
   default ``Common`` are stamped with the override. Operator-set
   specific products (e.g. ``ESP``) are preserved verbatim.
2. **Phase 2 filter + OUT_OF_SCOPE** (``ARXMLGenerator._document_to_dids``
   with ``product_type=...``): mismatched per-DID product_type
   flow into the validation report as ``OUT_OF_SCOPE`` and are
   excluded from the emitted ARXML; the special ``"Common"`` token
   (case-insensitive) is the wildcard exemption that mirrors the
   DOORS-export convention.
3. **Cross-product SCOPE auditor**: when a DID's
   SHORT-NAME shows up in a *sibling* product's ARXML, the reviewer
   emits a ``SCOPE`` issue -- unless the entry is tagged
   ``product_type='Common'``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fscs import apply_product_type_defaults
from fscs.schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSProject,
    FSCSServiceAccess,
    FSCSSecurityLevel,
)
from generate_arxml import ARXMLGenerator
from review_arxml import ARXMLReviewer
from config import ProjectConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(*, supported=True, used=True, sessions=("defaultSession",), level="L0"):
    return FSCSServiceAccess(
        supported=supported,
        used=used,
        sessions=list(sessions),
        security_levels=[FSCSSecurityLevel(level=level)],
    )


def _make_did(*, did_hex, did_name, rw_state="R", product_type=None,
              service_22=None, service_2e=None):
    return DIDFscsEntry(
        did_hex=did_hex,
        did_name=did_name,
        data_type="Unsigned",
        storage_position="EEPROM",
        size_bytes=4,
        rw_state=rw_state,
        nvm_item="NVM_ID_DCOM_TEST",
        service_22=service_22 or _make_service(),
        service_2e=service_2e or _make_service(supported=False, used=False),
        product_type=product_type,
    )


# ---------------------------------------------------------------------------
# 1. Phase 1 default-fill (apply_product_type_defaults)
# ---------------------------------------------------------------------------


class TestApplyProductTypeDefaults:
    """``apply_product_type_defaults(document, default_product_type=...)``.

    Stamps the override over the default wildcard ``Common``. After
    schema migration every DID carries a non-empty ``product_type``;
    entries still showing ``Common`` are treated as "no operator
    customisation yet" and replaced when an explicit override is
    supplied. Operator-tagged specific products are preserved.
    """

    def test_fills_common_when_default_set(self):
        """Fresh DIDs default to 'Common'; override stamps them all."""
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="A"),
                _make_did(did_hex="F191", did_name="B"),
            ],
        )
        filled = apply_product_type_defaults(document, default_product_type="DPB")
        assert filled == 2
        assert document.dids[0].product_type == "DPB"
        assert document.dids[1].product_type == "DPB"

    def test_no_op_when_default_empty(self):
        """No override: every entry keeps the default wildcard 'Common'."""
        document = FSCSDocument(
            dids=[_make_did(did_hex="F190", did_name="A")],
        )
        filled = apply_product_type_defaults(document, default_product_type="")
        assert filled == 0
        assert document.dids[0].product_type == "Common"

    def test_no_op_when_default_none(self):
        document = FSCSDocument(
            dids=[_make_did(did_hex="F190", did_name="A")],
        )
        filled = apply_product_type_defaults(document, default_product_type=None)
        assert filled == 0
        assert document.dids[0].product_type == "Common"

    def test_no_op_when_default_is_common(self):
        """Passing 'Common' as the override is the same as no override."""
        document = FSCSDocument(
            dids=[_make_did(did_hex="F190", did_name="A")],
        )
        filled = apply_product_type_defaults(document, default_product_type="Common")
        assert filled == 0
        assert document.dids[0].product_type == "Common"

    def test_preserves_operator_tagged_values(self):
        """A specific product tag is never overwritten -- operator intent wins."""
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="A", product_type="ESP"),
                _make_did(did_hex="F191", did_name="B"),
            ],
        )
        filled = apply_product_type_defaults(document, default_product_type="DPB")
        assert filled == 1
        assert document.dids[0].product_type == "ESP"
        assert document.dids[1].product_type == "DPB"

    def test_replaces_common_wildcard_with_override(self):
        """A non-Common override replaces every entry still tagged Common.

        Note: with 'Common' as the schema default, the helper cannot
        distinguish operator-set 'Common' from the default — both
        get stamped. Operators who want a DID to genuinely apply
        everywhere should either skip the ``--product-type`` CLI
        flag entirely, or re-set the cell to ``Common`` in the CSV
        after the Phase 1 export.
        """
        document = FSCSDocument(
            dids=[_make_did(did_hex="F190", did_name="A", product_type="Common")],
        )
        filled = apply_product_type_defaults(document, default_product_type="DPB")
        assert filled == 1
        assert document.dids[0].product_type == "DPB"


# ---------------------------------------------------------------------------
# 2. Phase 2 filter + OUT_OF_SCOPE
# ---------------------------------------------------------------------------


class TestPhase2ProductTypeFilter:
    """``ARXMLGenerator._document_to_dids(product_type=...)`` filtering."""

    def test_no_product_type_no_filter(self):
        """When ``product_type`` is None, scope is ignored (v1.3 posture)."""
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="A", product_type="DPB"),
                _make_did(did_hex="F191", did_name="B", product_type="ESP"),
            ],
        )
        valid, report = ARXMLGenerator()._document_to_dids(document, verbose=False)
        statuses = {r["did_hex"]: r["status"] for r in report}
        assert statuses == {"0xF190": "SUCCESS", "0xF191": "SUCCESS"}
        assert len(valid) == 2

    def test_mismatched_value_becomes_out_of_scope(self):
        """``product_type=ESP`` against build-target ``DPB`` -> OUT_OF_SCOPE."""
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="A", product_type="DPB"),
                _make_did(did_hex="F191", did_name="B", product_type="ESP"),
            ],
        )
        valid, report = ARXMLGenerator()._document_to_dids(
            document, verbose=False, product_type="DPB",
        )
        statuses = {r["did_hex"]: r["status"] for r in report}
        assert statuses == {"0xF190": "SUCCESS", "0xF191": "OUT_OF_SCOPE"}
        assert [d.did_hex for d in valid] == ["0xF190"]
        oos = next(r for r in report if r["status"] == "OUT_OF_SCOPE")
        assert "ESP" in oos["errors"][0] and "DPB" in oos["errors"][0]

    def test_common_value_passes_for_any_product(self):
        """``product_type='Common'`` is the wildcard."""
        document = FSCSDocument(
            dids=[_make_did(did_hex="F190", did_name="A", product_type="Common")],
        )
        for target in ("DPB", "ESP", "RBU"):
            _, report = ARXMLGenerator()._document_to_dids(
                document, verbose=False, product_type=target,
            )
            assert report[0]["status"] == "SUCCESS"

    def test_common_value_match_is_case_insensitive(self):
        document = FSCSDocument(
            dids=[_make_did(did_hex="F190", did_name="A", product_type="common")],
        )
        _, report = ARXMLGenerator()._document_to_dids(
            document, verbose=False, product_type="DPB",
        )
        assert report[0]["status"] == "SUCCESS"

    def test_default_common_passes_for_any_product(self):
        """The default 'Common' tag is the wildcard for every build target.

        The schema field validator turns missing / None / blank
        ``product_type`` values into ``"Common"`` at model-build
        time, so a freshly-constructed entry without an explicit
        tag is always in-scope downstream.
        """
        document = FSCSDocument(
            dids=[_make_did(did_hex="F190", did_name="A", product_type=None)],
        )
        assert document.dids[0].product_type == "Common"
        _, report = ARXMLGenerator()._document_to_dids(
            document, verbose=False, product_type="DPB",
        )
        assert report[0]["status"] == "SUCCESS"

    def test_out_of_scope_excluded_from_arxml(self, tmp_path):
        """OUT_OF_SCOPE DIDs must not appear in the rendered ARXML."""
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="Vin", product_type="DPB"),
                _make_did(did_hex="F195", did_name="EspOnly", product_type="ESP"),
            ],
        )
        fscs_json = tmp_path / "fscs.json"
        fscs_json.write_text(document.model_dump_json(), encoding="utf-8")
        out_arxml = tmp_path / "DID_Config.arxml"
        ARXMLGenerator().generate(
            output_path=out_arxml,
            fscs_json_path=fscs_json,
            product_type="DPB",
            report_dir=tmp_path,
        )
        text = out_arxml.read_text(encoding="utf-8")
        assert "F190" in text
        assert "F195" not in text

    def test_validation_report_records_out_of_scope_count(self, tmp_path):
        """``validation_report.txt`` exposes the OUT_OF_SCOPE bucket."""
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="Vin", product_type="DPB"),
                _make_did(did_hex="F195", did_name="EspOnly", product_type="ESP"),
            ],
        )
        fscs_json = tmp_path / "fscs.json"
        fscs_json.write_text(document.model_dump_json(), encoding="utf-8")
        out_arxml = tmp_path / "DID_Config.arxml"
        ARXMLGenerator().generate(
            output_path=out_arxml,
            fscs_json_path=fscs_json,
            product_type="DPB",
            report_dir=tmp_path,
        )
        report = (tmp_path / "validation_report.txt").read_text(encoding="utf-8")
        assert "OUT_OF_SCOPE: 1" in report
        assert "[SCOPE]" in report
        assert "F195" in report


# ---------------------------------------------------------------------------
# 2b. v1.24.0: ESP and ESPCL iterate independently (no DID fold-in)
# ---------------------------------------------------------------------------


class TestEspEspclIndependentIterations:
    """v1.24.0 reverted the v1.23.0 ``accepted_scopes`` DID fold-in.

    The Phase-2 ESPCL → ESP alias is now a *path* alias (the two
    products share an output folder via the
    ``{product_type_arxml_folder}`` placeholder) rather than a DID
    fold-in (where ESP's iteration would absorb ESPCL DIDs). These
    tests pin the single-target filter behaviour so a future
    accidental re-introduction of fold-in semantics flips a test.
    """

    def test_esp_iteration_excludes_espcl_dids(self):
        # ESP iteration sees ESP- and Common-tagged DIDs only;
        # ESPCL-tagged is OUT_OF_SCOPE (it lands in ESPCL's own
        # iteration, which writes a separate ARXML to the same
        # ``cfg/ESP/`` folder via the path alias).
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="EspDid", product_type="ESP"),
                _make_did(did_hex="F195", did_name="EspclDid", product_type="ESPCL"),
                _make_did(did_hex="F198", did_name="ComDid", product_type="Common"),
            ],
        )
        valid, report = ARXMLGenerator()._document_to_dids(
            document, verbose=False, product_type="ESP",
        )
        emitted_hexes = {d.did_hex for d in valid}
        assert "0xF190" in emitted_hexes
        assert "0xF198" in emitted_hexes  # Common always in scope
        assert "0xF195" not in emitted_hexes
        statuses = {entry["did_hex"]: entry["status"] for entry in report}
        assert statuses["0xF195"] == "OUT_OF_SCOPE"

    def test_espcl_iteration_excludes_esp_dids(self):
        # Symmetric: ESPCL iteration sees ESPCL- and Common-tagged
        # DIDs only; ESP-tagged is OUT_OF_SCOPE.
        document = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="EspDid", product_type="ESP"),
                _make_did(did_hex="F195", did_name="EspclDid", product_type="ESPCL"),
            ],
        )
        valid, report = ARXMLGenerator()._document_to_dids(
            document, verbose=False, product_type="ESPCL",
        )
        emitted_hexes = {d.did_hex for d in valid}
        assert emitted_hexes == {"0xF195"}
        statuses = {entry["did_hex"]: entry["status"] for entry in report}
        assert statuses["0xF190"] == "OUT_OF_SCOPE"


# ---------------------------------------------------------------------------
# 3. Differential C: cross-product SCOPE auditor
# ---------------------------------------------------------------------------


class TestCrossProductScopeAudit:
    """``ARXMLReviewer.review_cross_product_scope(config, current_product_type)``."""

    @staticmethod
    def _build_two_product_workspace(tmp_path: Path):
        """Create a Bosch-tree-like layout with DPB and ESP ARXML siblings.

        Returns ``(config, dpb_arxml, esp_arxml, dpb_fscs)`` where the
        DPB tree's fscs.json + ARXML contain DID 0xF190 (the overlapping
        DID under test) and 0xD001 (DPB-only). The ESP ARXML also
        contains 0xF190 -- this is the cross-product overlap the
        auditor is supposed to flag.
        """
        base = tmp_path / "Fe_Super"
        dpb_dir = base / "rb" / "as" / "rbcn" / "core" / "app" / "dcom" / "RBAPLCust" / "cfg" / "DPB"
        esp_dir = base / "rb" / "as" / "rbcn" / "core" / "app" / "dcom" / "RBAPLCust" / "cfg" / "ESP"
        dpb_dir.mkdir(parents=True)
        esp_dir.mkdir(parents=True)

        # v1.19.0: schema 2.0 dropped both ``project`` and
        # ``paths.project_root``; ``project_root`` only survives as
        # a literal segment in the path templates. The arxml_file
        # template still uses {product_type_upper} so the
        # auditor's path resolver finds both DPB and ESP siblings.
        config = ProjectConfig(
            paths={  # type: ignore[arg-type]
                "base_dir": str(tmp_path),
                "arxml_file": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/{product_type_upper}/DID_Config.arxml",
            },
        )

        dpb_doc = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="VinShared", product_type="DPB"),
                _make_did(did_hex="D001", did_name="DpbOnly", product_type="DPB"),
            ],
        )
        dpb_fscs = tmp_path / "dpb_fscs.json"
        dpb_fscs.write_text(dpb_doc.model_dump_json(), encoding="utf-8")
        dpb_arxml = dpb_dir / "DID_Config.arxml"
        ARXMLGenerator().generate(
            output_path=dpb_arxml,
            fscs_json_path=dpb_fscs,
            product_type="DPB",
            report_dir=dpb_dir,
        )

        esp_doc = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="VinShared", product_type="ESP"),
                _make_did(did_hex="E001", did_name="EspOnly", product_type="ESP"),
            ],
        )
        esp_fscs = tmp_path / "esp_fscs.json"
        esp_fscs.write_text(esp_doc.model_dump_json(), encoding="utf-8")
        esp_arxml = esp_dir / "DID_Config.arxml"
        ARXMLGenerator().generate(
            output_path=esp_arxml,
            fscs_json_path=esp_fscs,
            product_type="ESP",
            report_dir=esp_dir,
        )

        return config, dpb_arxml, esp_arxml, dpb_fscs

    def test_overlap_flagged_when_value_is_not_common(self, tmp_path):
        """F190 in both DPB and ESP ARXMLs but tagged DPB only -> SCOPE."""
        config, dpb_arxml, _esp_arxml, dpb_fscs = self._build_two_product_workspace(tmp_path)

        reviewer = ARXMLReviewer()
        reviewer.parse_arxml(dpb_arxml)
        reviewer.load_from_fscs_json(dpb_fscs, product_type="DPB")
        reviewer.review_cross_product_scope(config, "DPB")

        scope_issues = [i for i in reviewer.issues if i.type == "SCOPE"]
        assert len(scope_issues) == 1, (
            f"Expected exactly one SCOPE issue for the F190 overlap; got "
            f"{[(i.type, i.did, i.message) for i in scope_issues]}"
        )
        assert "0xF190" in scope_issues[0].did
        assert "ESP" in scope_issues[0].message

    def test_common_value_silences_overlap(self, tmp_path):
        """Tag F190 ``product_type='Common'`` -> overlap is OK, no SCOPE issue."""
        config, dpb_arxml, _esp_arxml, _dpb_fscs = self._build_two_product_workspace(tmp_path)

        common_doc = FSCSDocument(
            dids=[
                _make_did(did_hex="F190", did_name="VinShared", product_type="Common"),
                _make_did(did_hex="D001", did_name="DpbOnly", product_type="DPB"),
            ],
        )
        common_fscs = dpb_arxml.parent.parent / "common_fscs.json"
        common_fscs.write_text(common_doc.model_dump_json(), encoding="utf-8")

        reviewer = ARXMLReviewer()
        reviewer.parse_arxml(dpb_arxml)
        reviewer.load_from_fscs_json(common_fscs, product_type="DPB")
        reviewer.review_cross_product_scope(config, "DPB")

        scope_issues = [i for i in reviewer.issues if i.type == "SCOPE"]
        assert scope_issues == [], (
            f"DIDs tagged Common must not produce SCOPE noise; got "
            f"{[i.message for i in scope_issues]}"
        )

    def test_skipped_when_template_has_no_placeholder(self, tmp_path):
        """Single-product layouts (no ``{product_type}`` in template) skip."""
        config = ProjectConfig(
            paths={  # type: ignore[arg-type]
                "base_dir": str(tmp_path),
                "arxml_file": "DID_Config.arxml",
            },
        )
        reviewer = ARXMLReviewer()
        reviewer.review_cross_product_scope(config, "DPB")
        assert [i for i in reviewer.issues if i.type == "SCOPE"] == []

    def test_skipped_when_config_is_none(self):
        """``config=None`` is the v1.12.x posture: no audit, no error."""
        reviewer = ARXMLReviewer()
        reviewer.review_cross_product_scope(None, "DPB")
        assert reviewer.issues == []
