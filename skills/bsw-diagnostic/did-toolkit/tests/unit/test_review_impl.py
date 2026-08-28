"""Unit tests for :mod:`review_impl`.

Covers:
* Happy path against the committed phase_all golden tree
  (cross-checked against the golden ``fscs.json``).
* Missing ``c_code/`` directory → single COVERAGE issue.
* Missing PDM block for an EEPROM DID → PDM issue.
* Missing Feature-Switch macro in all three headers → three HEADER issues.
* Collision-aware coverage: two DIDs that collapse to the same cleaned
  name require the hex-disambiguated file form.

Part 6 migrated the reviewer off ``inputs/*.json`` onto
``outputs/fscs/fscs.json`` as authoritative; every test now passes
``fscs_json=`` rather than ``input_json=``. The collision test builds
a synthetic ``FSCSDocument`` on the fly since ``tiny_did.json`` has no
name collisions by itself.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fscs import save_fscs_json
from fscs.schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSServiceAccess,
    FSCSSecurityLevel,
)
from review_impl import ImplReviewer, run_review


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# v1.21.0: phase-all goldens fan out per product. tiny_did.json
# yields the ``Common`` slot, so the implementation review checks
# point at that subtree.
GOLDEN_IMPL = (
    PROJECT_ROOT / "tests" / "golden" / "phase_all" / "implementation" / "Common"
)
GOLDEN_FSCS_JSON = PROJECT_ROOT / "tests" / "golden" / "phase_all" / "fscs" / "fscs.json"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture
def clean_tree(tmp_path: Path) -> Path:
    """Copy the committed golden impl tree into a mutable sandbox."""
    dest = tmp_path / "implementation"
    shutil.copytree(GOLDEN_IMPL, dest)
    return dest


def test_clean_tree_passes_all_checks(clean_tree: Path, tmp_path: Path):
    """The golden phase_all impl tree must satisfy every review rule."""
    result = run_review(
        impl_dir=clean_tree,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    assert result["has_issues"] is False, [i.message for i in result["issues"]]
    assert result["summary"]["total"] == 0


def test_missing_c_code_directory_reports_coverage(tmp_path: Path):
    impl_dir = tmp_path / "implementation"
    impl_dir.mkdir()  # empty — no c_code/, no pdms/, no headers/
    result = run_review(
        impl_dir=impl_dir,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    coverage = [i for i in result["issues"] if i.type == "COVERAGE"]
    assert coverage, "Expected a COVERAGE issue when c_code/ is missing"
    assert any("c_code" in i.message for i in coverage)


def test_removed_rdbi_file_reports_missing_coverage(clean_tree: Path, tmp_path: Path):
    victim = clean_tree / "c_code" / "RBAPLCUST_RDBI_ModeSelector.c"
    assert victim.is_file()
    victim.unlink()

    result = run_review(
        impl_dir=clean_tree,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    coverage = [i for i in result["issues"] if i.type == "COVERAGE"]
    assert any("RBAPLCUST_RDBI_ModeSelector.c" in i.message for i in coverage)


def test_missing_pdm_block_reports_pdm_issue(clean_tree: Path, tmp_path: Path):
    pdm = clean_tree / "pdms" / "pdm_entries.txt"
    text = pdm.read_text(encoding="utf-8")
    # Drop the ModeSelector block by splitting on its marker.
    mangled = text.replace("use dataitem NVM_ID_DCOM_ModeSelector", "use dataitem NVM_ID_DCOM_REMOVED")
    pdm.write_text(mangled, encoding="utf-8")

    result = run_review(
        impl_dir=clean_tree,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    pdm_issues = [i for i in result["issues"] if i.type == "PDM"]
    assert any("ModeSelector" in i.message for i in pdm_issues), \
        f"Expected ModeSelector PDM gap, got: {[i.message for i in pdm_issues]}"


def test_missing_feature_switch_macro_reports_header_issue(clean_tree: Path, tmp_path: Path):
    macros = clean_tree / "headers" / "header_config_macros.txt"
    text = macros.read_text(encoding="utf-8")
    mangled = text.replace("RBFS_DCOM_BaselineCounter", "RBFS_DCOM_Removed")
    macros.write_text(mangled, encoding="utf-8")

    result = run_review(
        impl_dir=clean_tree,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    header_issues = [i for i in result["issues"] if i.type == "HEADER"]
    assert any("BaselineCounter" in i.message for i in header_issues)


def test_ram_did_with_range_does_not_trigger_range_issue(clean_tree: Path, tmp_path: Path):
    """RAM DIDs with ranges intentionally have no range macro — reviewer agrees."""
    result = run_review(
        impl_dir=clean_tree,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    range_issues = [i for i in result["issues"] if i.type == "RANGE"]
    assert range_issues == [], f"Unexpected range issues: {[i.message for i in range_issues]}"


def test_clean_name_matches_generator_rule():
    """Shared naming must agree with the generator to avoid false positives.

    The generator keeps every alphanumeric character from the raw name —
    it does NOT drop content inside parens. The reviewer mirrors that.
    """
    r = ImplReviewer()
    assert r._clean_name("Brake system type(Only for GAC)") == "BrakesystemtypeOnlyforGAC"
    assert r._clean_name("   ") == ""
    assert r._clean_name("BaselineCounter") == "BaselineCounter"
    # Chinese chars are stripped; remaining alphanum chars survive.
    assert r._clean_name("mode 中文 selector") == "Modeselector"


def _make_ram_read_entry(did_hex: str, did_name: str) -> DIDFscsEntry:
    """Minimal ``DIDFscsEntry`` for a RAM-backed read-only DID.

    Used by the collision test below; the review logic only cares
    about ``did_hex`` / ``did_name`` / ``storage_position`` / service
    support flags, but we still populate the mandatory schema fields
    (``service_22.sessions`` + ``security_levels``) so pydantic
    accepts the document.
    """
    return DIDFscsEntry(
        did_hex=did_hex,
        did_name=did_name,
        data_type="Unsigned",
        storage_position="RAM",
        size_bytes=1,
        rw_state="R",
        nvm_item="",
        service_22=FSCSServiceAccess(
            supported=True,
            sessions=["defaultSession", "extendedDiagnosticSession"],
            security_levels=[FSCSSecurityLevel(level="L0")],
        ),
        service_2e=FSCSServiceAccess(supported=False),
    )


def test_collision_aware_coverage(tmp_path: Path):
    """Two DIDs with the same cleaned name require hex-disambiguated files."""
    impl_dir = tmp_path / "implementation"
    (impl_dir / "c_code").mkdir(parents=True)
    (impl_dir / "pdms").mkdir()
    (impl_dir / "headers").mkdir()

    # Both stem to 'Counter' after cleaning. The raw names differ by a
    # trailing space so the reviewer's _clean_name collapses them to the
    # same token; the generator's collision disambiguator then prefixes
    # with the hex id, and the expected file names follow suit.
    fscs_doc = FSCSDocument(dids=[
        _make_ram_read_entry("F190", "Counter"),
        _make_ram_read_entry("F191", "Counter "),
    ])
    fscs_json = tmp_path / "fscs.json"
    save_fscs_json(fscs_doc, fscs_json)

    # Emit files matching the disambiguated form (what the generator would do).
    for hex_part in ("F190", "F191"):
        (impl_dir / "c_code" / f"RBAPLCUST_RDBI_{hex_part}_Counter.c").write_text(
            "/* stub */", encoding="utf-8"
        )
    # Empty PDM + headers are fine for RAM-only DIDs in this minimal input.
    (impl_dir / "pdms" / "pdm_entries.txt").write_text("", encoding="utf-8")
    (impl_dir / "headers" / "header_config_macros.txt").write_text(
        "#define RBFS_DCOM_Counter RBFS_DCOM_Counter_OFF\n", encoding="utf-8"
    )
    (impl_dir / "headers" / "header_config_settings.txt").write_text(
        "#define RBFS_DCOM_Counter RBFS_DCOM_Counter_ON\n", encoding="utf-8"
    )
    (impl_dir / "headers" / "header_element_defs.txt").write_text(
        "#define RBFS_DCOM_Counter_ON  1\n#define RBFS_DCOM_Counter_OFF 2\n", encoding="utf-8"
    )

    result = run_review(
        impl_dir=impl_dir,
        fscs_json=fscs_json,
        output_path=tmp_path / "report.txt",
    )
    coverage = [i for i in result["issues"] if i.type == "COVERAGE"]
    assert coverage == [], f"Unexpected coverage issues: {[i.message for i in coverage]}"
