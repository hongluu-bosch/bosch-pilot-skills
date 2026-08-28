"""Unit tests for :mod:`review_arxml`.

Covers:
* Happy path against the committed phase_all golden ARXML
  (cross-checked against the golden ``fscs.json``).
* Malformed XML → STRUCTURE issue.
* Wrong DcmDspDidIdentifier decimal value → IDENTIFIER issue.
* Wrong DcmDspDataSize (bits) → SIZE issue.
* Wrong DcmDspDidInfoRef target → INFOREF issue.

Part 6 migrated the reviewer off ``inputs/*.json`` onto
``outputs/fscs/fscs.json`` as authoritative, so every test now
passes ``fscs_json=`` rather than ``input_json=``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from review_arxml import run_review


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# v1.21.0: phase-all goldens fan out per product. tiny_did.json
# yields the ``Common`` slot. v1.24.0 renamed the per-iteration
# ARXML to carry the ``_<suffix>`` tag (Common → ``SingleCANID``)
# so multiple PTs sharing a folder don't clobber each other.
GOLDEN_ARXML = (
    PROJECT_ROOT / "tests" / "golden" / "phase_all" / "arxml" / "Common"
    / "DID_Config_SingleCANID.arxml"
)
GOLDEN_FSCS_JSON = PROJECT_ROOT / "tests" / "golden" / "phase_all" / "fscs" / "fscs.json"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


@pytest.fixture
def sandboxed_arxml(tmp_path: Path) -> Path:
    """Copy the golden ARXML so mutations stay in the sandbox."""
    dest = tmp_path / "DID_Config.arxml"
    shutil.copyfile(GOLDEN_ARXML, dest)
    return dest


def test_golden_arxml_passes_all_checks(sandboxed_arxml: Path, tmp_path: Path):
    """The committed golden ARXML must satisfy every review rule."""
    result = run_review(
        arxml_path=sandboxed_arxml,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    assert result["has_issues"] is False, [i.message for i in result["issues"]]


def test_malformed_xml_produces_structure_issue(tmp_path: Path):
    bad = tmp_path / "bad.arxml"
    bad.write_text("<AUTOSAR><broken", encoding="utf-8")
    result = run_review(
        arxml_path=bad,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    structure = [i for i in result["issues"] if i.type == "STRUCTURE"]
    assert structure, "Expected STRUCTURE issue on malformed XML"


def test_wrong_identifier_value_is_flagged(sandboxed_arxml: Path, tmp_path: Path):
    text = sandboxed_arxml.read_text(encoding="utf-8")
    # F18C is decimal 61836; ModeSelector is the only DID whose DID
    # container carries DcmDspDidIdentifier value 61836. Replace it with
    # an obviously wrong value to trigger the identifier check.
    mangled = text.replace("<VALUE>61836</VALUE>", "<VALUE>42</VALUE>", 1)
    assert mangled != text, "Fixture drift: 61836 no longer in ARXML"
    sandboxed_arxml.write_text(mangled, encoding="utf-8")

    result = run_review(
        arxml_path=sandboxed_arxml,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    ident_issues = [i for i in result["issues"] if i.type == "IDENTIFIER"]
    assert any("61836" in i.message or "42" in i.message for i in ident_issues), \
        [i.message for i in ident_issues]


def test_wrong_data_size_is_flagged(sandboxed_arxml: Path, tmp_path: Path):
    text = sandboxed_arxml.read_text(encoding="utf-8")
    # Every DID in tiny_did.json is 1 byte → 8 bits. Replace the first 8
    # under DcmDspDataSize with 128 so exactly one SIZE issue fires for
    # the ModeSelector data container.
    lines = text.splitlines()
    mangled_lines = list(lines)
    for idx, line in enumerate(lines):
        if "/DcmDspDataSize</DEFINITION-REF>" in line:
            # the next few lines include <VALUE>N</VALUE>
            for j in range(idx + 1, min(idx + 4, len(lines))):
                if "<VALUE>8</VALUE>" in lines[j]:
                    mangled_lines[j] = lines[j].replace("<VALUE>8</VALUE>", "<VALUE>128</VALUE>")
                    break
            break
    sandboxed_arxml.write_text("\n".join(mangled_lines), encoding="utf-8")

    result = run_review(
        arxml_path=sandboxed_arxml,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    size_issues = [i for i in result["issues"] if i.type == "SIZE"]
    assert size_issues, f"Expected SIZE issue when bits flipped 8→128, got: {result['issues']}"
    assert any("128" in i.message for i in size_issues)


def test_wrong_info_ref_target_is_flagged(sandboxed_arxml: Path, tmp_path: Path):
    text = sandboxed_arxml.read_text(encoding="utf-8")
    # Point a _ReadAndWrite ref to _Read instead; this must fail for the
    # first RW DID (ModeSelector, F18C).
    # The generator emits VALUE-REFs that END with DcmDspDidInfo_ReadAndWrite.
    # Replace the first one to end with DcmDspDidInfo_Read_WRONG.
    needle = "/DcmDspDidInfo_ReadAndWrite</VALUE-REF>"
    replacement = "/DcmDspDidInfo_Read</VALUE-REF>"
    assert needle in text, "Fixture drift: ReadAndWrite ref no longer present"
    mangled = text.replace(needle, replacement, 1)
    sandboxed_arxml.write_text(mangled, encoding="utf-8")

    result = run_review(
        arxml_path=sandboxed_arxml,
        fscs_json=GOLDEN_FSCS_JSON,
        output_path=tmp_path / "report.txt",
    )
    info_issues = [i for i in result["issues"] if i.type == "INFOREF"]
    assert info_issues, "Expected INFOREF issue when a RW DID points at DcmDspDidInfo_Read"
