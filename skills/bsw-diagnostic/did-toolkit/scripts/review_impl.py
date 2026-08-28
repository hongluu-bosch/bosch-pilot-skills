#!/usr/bin/env python3
"""Implementation Content Review.

Cross-checks the Phase 3 artifact tree under ``outputs/implementation/``
against Phase 1's ``outputs/fscs/fscs.json`` (authoritative DID catalog)
and surfaces structural drift that the in-tree ``validation_report.txt``
does not catch.

After the Part 6 cleanup this reviewer no longer reads
``inputs/*.json`` directly -- Phase 1's ``fscs.json`` is the single
source of truth so both Phase 2 and Phase 3 reviewers compare against
the same committed catalog.

Checks performed
----------------

* **Coverage** : every ``supported_by_ecu=Y`` DID with at least one
  ``Y`` in ``access.service_22`` has an ``RBAPLCUST_RDBI_*.c`` file;
  every RW DID with at least one ``Y`` in ``access.service_2e`` also has
  an ``RBAPLCUST_WDBI_*.c`` file.
* **PDM consistency** : one ``use dataitem NVM_ID_DCOM_<Name>`` block per
  EEPROM DID; RAM-only DIDs produce no PDM entry.
* **Feature-switch headers** : every DID has a matching
  ``#define RBFS_DCOM_<Name>`` entry in
  ``header_config_macros.txt`` and ``header_config_settings.txt``, and an
  ON/OFF definition in ``header_element_defs.txt``.
* **Range macros** : ``header_range_macros.txt`` only exists when at
  least one DID declares a numeric/enum range, and every DID range
  declared in the JSON shows up there.

Usage
-----

::

    python scripts/review_impl.py \\
        --impl-dir outputs/implementation \\
        --fscs-json outputs/fscs/fscs.json \\
        --output outputs/implementation/impl_review_report.txt

``pipeline.py`` invokes :func:`run_review` directly after Phase 3 so the
CLI and pipeline paths share a single orchestration entry point (same
pattern as ``review_fscs.run_review``).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_encoding import reconfigure_stdio_utf8  # noqa: E402
from fscs import load_fscs, to_review_dicts  # noqa: E402

reconfigure_stdio_utf8()


class ImplReviewIssue:
    """One structural finding against the implementation output tree."""

    def __init__(self, issue_type: str, did: str, message: str):
        self.type = issue_type  # COVERAGE / PDM / HEADER / RANGE
        self.did = did
        self.message = message


class ImplReviewer:
    """Review generated implementation artifacts.

    Parses ``outputs/implementation/`` and the input DID JSON into plain
    dicts/sets, then runs a handful of cross-checks. Call sites populate
    ``self.dids_json`` and ``self.impl_dir`` first (via ``parse_*``) and
    then invoke the individual ``review_*`` methods in any order.
    """

    _FS_MACRO_RE = re.compile(r"#define\s+RBFS_DCOM_(\w+)")
    _PDM_BLOCK_RE = re.compile(r"use\s+dataitem\s+NVM_ID_DCOM_(\w+)")
    _RANGE_MACRO_RE = re.compile(r"#define\s+DID_([0-9A-Fa-f]+)_")

    def __init__(self):
        self.issues: List[ImplReviewIssue] = []
        self.dids_json: List[Dict] = []
        self.impl_dir: Path = Path(".")

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def load_from_fscs_json(self, fscs_json_path: Path) -> None:
        """Load expected DIDs from Phase 1's ``fscs.json``.

        :func:`fscs.to_review_dicts` projects ``FSCSDocument`` back to
        the list-of-dicts shape every ``review_*`` method already
        operates on (``did_name_en``, ``access.service_22`` nested
        Y/N, ``sub_fields[].method_en``, etc.) so Part 6 could swap
        the data source without touching a single check.
        """
        document = load_fscs(fscs_json=Path(fscs_json_path))
        self.dids_json = to_review_dicts(document)

    def parse_impl_dir(self, impl_dir: Path) -> None:
        self.impl_dir = Path(impl_dir)
        if not self.impl_dir.is_dir():
            raise FileNotFoundError(
                f"Implementation output directory not found: {self.impl_dir}"
            )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_name(name: str) -> str:
        """Mirror ImplementationGenerator._capitalize_first(_clean_name(...)).

        Must match the generator exactly or coverage checks will produce
        false positives. Kept as a static helper here to avoid importing
        generate_implementation (and its 1100+ lines) just for naming.
        """
        if not name:
            return ""
        cleaned = re.sub(r"[\u4e00-\u9fff]", "", name)
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
        if not cleaned:
            return ""
        return cleaned[0].upper() + cleaned[1:]

    @staticmethod
    def _supports_any(access_leaf: Dict) -> bool:
        """True iff any leaf field under an access subtree is 'Y'."""
        if not isinstance(access_leaf, dict):
            return False
        for v in access_leaf.values():
            if isinstance(v, dict) and ImplReviewer._supports_any(v):
                return True
            if isinstance(v, str) and v.strip().upper() == "Y":
                return True
        return False

    def _effective_dids(self) -> List[Dict]:
        """DIDs with ``supported_by_ecu=Y`` (same gate FSCS generator applies)."""
        return [
            d for d in self.dids_json
            if str(d.get("supported_by_ecu", "Y")).strip().upper() != "N"
        ]

    def _supports_22(self, did: Dict) -> bool:
        return self._supports_any(did.get("access", {}).get("service_22", {}))

    def _supports_2e(self, did: Dict) -> bool:
        return self._supports_any(did.get("access", {}).get("service_2e", {}))

    def _is_eeprom(self, did: Dict) -> bool:
        return str(did.get("storage_pos", "")).strip().upper() == "EEPROM"

    def _has_range(self, did: Dict) -> bool:
        """True iff the generator would emit range macros for this DID.

        Mirrors ``ImplementationGenerator.generate_range_macros`` exactly:
        range macros are emitted only for EEPROM DIDs that also declare a
        value range (enum method_en OR numeric min/max). RAM DIDs never
        produce range macros even if their JSON carries ranges, because
        runtime range enforcement lives inside the .c body for RAM.
        """
        if not self._is_eeprom(did):
            return False
        for sub in did.get("sub_fields", []) or []:
            method = str(sub.get("method_en", "") or "").strip()
            if method and re.search(r"^\s*0x[0-9A-Fa-f]+\s*=", method, re.MULTILINE):
                return True
            rmin = str(sub.get("range_min_phy", "") or "").strip()
            rmax = str(sub.get("range_max_phy", "") or "").strip()
            if rmin and rmax and rmin.lower() not in ("null", "n/a") \
                    and rmax.lower() not in ("null", "n/a"):
                return True
        return False

    # ------------------------------------------------------------------
    # Review checks
    # ------------------------------------------------------------------

    def review_c_file_coverage(self) -> None:
        """Each supported DID has RDBI.c; each 2E-writable DID also has WDBI.c."""
        c_code_dir = self.impl_dir / "c_code"
        if not c_code_dir.is_dir():
            self.issues.append(ImplReviewIssue(
                "COVERAGE", "-", f"Missing c_code directory: {c_code_dir}"
            ))
            return

        present = {p.name for p in c_code_dir.iterdir() if p.is_file()}

        # Pre-compute cleaned-name collisions (same rule as the generator).
        name_counts: Dict[str, int] = {}
        for did in self._effective_dids():
            stem = self._clean_name(did.get("did_name_en", ""))
            name_counts[stem] = name_counts.get(stem, 0) + 1

        for did in self._effective_dids():
            did_hex = did.get("did_hex", "?")
            did_stem_name = self._clean_name(did.get("did_name_en", ""))
            hex_stripped = str(did_hex).replace("0x", "").replace("0X", "").upper()
            # The generator uses the hex-disambiguated form for colliders.
            if name_counts.get(did_stem_name, 0) > 1:
                stem = f"{hex_stripped}_{did_stem_name}"
            else:
                stem = did_stem_name

            if self._supports_22(did):
                expected = f"RBAPLCUST_RDBI_{stem}.c"
                if expected not in present:
                    self.issues.append(ImplReviewIssue(
                        "COVERAGE", did_hex,
                        f"Expected read file {expected} missing under c_code/",
                    ))

            if did.get("rw_state", "").upper() == "RW" and self._supports_2e(did):
                expected_w = f"RBAPLCUST_WDBI_{stem}.c"
                if expected_w not in present:
                    self.issues.append(ImplReviewIssue(
                        "COVERAGE", did_hex,
                        f"Expected write file {expected_w} missing under c_code/",
                    ))

    def review_pdm_consistency(self) -> None:
        """Exactly one PDM block per EEPROM DID; none for RAM-only DIDs."""
        pdm_path = self.impl_dir / "pdms" / "pdm_entries.txt"
        if not pdm_path.is_file():
            if any(self._is_eeprom(d) for d in self._effective_dids()):
                self.issues.append(ImplReviewIssue(
                    "PDM", "-", f"pdm_entries.txt missing but EEPROM DIDs exist: {pdm_path}"
                ))
            return

        found_names: Set[str] = set(self._PDM_BLOCK_RE.findall(pdm_path.read_text(encoding="utf-8")))

        expected_eeprom: Set[str] = set()
        for did in self._effective_dids():
            if self._is_eeprom(did):
                expected_eeprom.add(self._clean_name(did.get("did_name_en", "")))

        missing = expected_eeprom - found_names
        for stem in sorted(missing):
            self.issues.append(ImplReviewIssue(
                "PDM", "-",
                f"EEPROM DID {stem} has no corresponding NVM_ID_DCOM_{stem} block in pdm_entries.txt",
            ))

        ram_leaks = {
            self._clean_name(d.get("did_name_en", ""))
            for d in self._effective_dids()
            if not self._is_eeprom(d)
        } & found_names
        for stem in sorted(ram_leaks):
            self.issues.append(ImplReviewIssue(
                "PDM", "-",
                f"Non-EEPROM DID {stem} unexpectedly has a PDM entry "
                f"(storage_pos is not EEPROM)",
            ))

    def review_feature_switch_headers(self) -> None:
        """Every DID has RBFS_DCOM_<Name> in macros + settings + elements."""
        macros = self.impl_dir / "headers" / "header_config_macros.txt"
        settings = self.impl_dir / "headers" / "header_config_settings.txt"
        elements = self.impl_dir / "headers" / "header_element_defs.txt"

        expected_stems = {
            self._clean_name(d.get("did_name_en", ""))
            for d in self._effective_dids()
        }

        for path in (macros, settings, elements):
            if not path.is_file():
                self.issues.append(ImplReviewIssue(
                    "HEADER", "-", f"Missing header artifact: {path}",
                ))
                continue
            present = set(self._FS_MACRO_RE.findall(path.read_text(encoding="utf-8")))
            # Drop OFF/ON literal suffixes that appear as standalone macros.
            present = {p.split("_OFF")[0].split("_ON")[0] for p in present}
            missing = expected_stems - present
            for stem in sorted(missing):
                self.issues.append(ImplReviewIssue(
                    "HEADER", "-",
                    f"Feature-switch macro RBFS_DCOM_{stem} missing in {path.name}",
                ))

    def review_range_macros(self) -> None:
        """header_range_macros.txt exists iff any DID has a range."""
        range_path = self.impl_dir / "headers" / "header_range_macros.txt"
        effective = self._effective_dids()
        dids_with_range = [d for d in effective if self._has_range(d)]

        if not dids_with_range:
            if range_path.is_file() and range_path.read_text(encoding="utf-8").strip():
                self.issues.append(ImplReviewIssue(
                    "RANGE", "-",
                    f"header_range_macros.txt is non-empty but no DID declares a range",
                ))
            return

        if not range_path.is_file():
            self.issues.append(ImplReviewIssue(
                "RANGE", "-",
                f"header_range_macros.txt missing but {len(dids_with_range)} "
                f"DID(s) declare ranges: "
                f"{sorted(d.get('did_hex', '?') for d in dids_with_range)}",
            ))
            return

        content = range_path.read_text(encoding="utf-8")
        found_hex = {h.upper() for h in self._RANGE_MACRO_RE.findall(content)}
        for did in dids_with_range:
            hex_str = str(did.get("did_hex", "")).replace("0x", "").replace("0X", "").upper()
            if hex_str and hex_str not in found_hex:
                self.issues.append(ImplReviewIssue(
                    "RANGE", did.get("did_hex", "?"),
                    f"DID {did.get('did_hex')} declares a range but no "
                    f"DID_{hex_str}_* macro exists in header_range_macros.txt",
                ))

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def generate_report(self, output_path: Path) -> Dict:
        coverage = [i for i in self.issues if i.type == "COVERAGE"]
        pdm = [i for i in self.issues if i.type == "PDM"]
        header = [i for i in self.issues if i.type == "HEADER"]
        range_issues = [i for i in self.issues if i.type == "RANGE"]

        total = len(self.issues)
        effective = self._effective_dids()

        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("Implementation Content Review Report")
        lines.append("=" * 80)
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"输入 DID 数: {len(self.dids_json)}")
        lines.append(f"被 ECU 支持: {len(effective)}")
        lines.append("")

        for title, bucket in (
            ("一、C 文件覆盖检查 (Coverage)", coverage),
            ("二、PDM 条目一致性检查 (PDM Consistency)", pdm),
            ("三、Feature-Switch 头文件检查 (Header Completeness)", header),
            ("四、Range 宏检查 (Range Macros)", range_issues),
        ):
            lines.append("=" * 80)
            lines.append(title)
            lines.append("=" * 80)
            if not bucket:
                lines.append("  ✓ 全部通过")
            else:
                for issue in bucket:
                    tag = f"[{issue.did}] " if issue.did not in ("-", "", None) else ""
                    lines.append(f"  ✗ {tag}{issue.message}")
            lines.append("")

        lines.append("=" * 80)
        lines.append("汇总 (Summary)")
        lines.append("=" * 80)
        if total:
            lines.append(f"发现 {total} 个异常 (不阻断后续流程):")
            lines.append(f"  - 覆盖: {len(coverage)}个")
            lines.append(f"  - PDM: {len(pdm)}个")
            lines.append(f"  - Header: {len(header)}个")
            lines.append(f"  - Range: {len(range_issues)}个")
        else:
            lines.append("✅ 所有检查通过")
        lines.append("")
        lines.append("=" * 80)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")

        return {
            "has_issues": total > 0,
            "issues": self.issues,
            "summary": {
                "total": total,
                "coverage": len(coverage),
                "pdm": len(pdm),
                "header": len(header),
                "range": len(range_issues),
                "dids_json_count": len(self.dids_json),
                "dids_effective_count": len(effective),
            },
            "report_path": str(output_path),
        }


def run_review(impl_dir: Path, fscs_json: Path, output_path: Path) -> Dict:
    """Shared orchestration for CLI and pipeline; mirrors review_fscs.run_review.

    ``fscs_json`` is the authoritative Phase 1 catalog; the old
    ``input_json`` parameter was dropped in Part 6 so this reviewer
    compares against the same document Phase 3 emitted from.
    """
    reviewer = ImplReviewer()
    reviewer.parse_impl_dir(Path(impl_dir))
    reviewer.load_from_fscs_json(Path(fscs_json))
    reviewer.review_c_file_coverage()
    reviewer.review_pdm_consistency()
    reviewer.review_feature_switch_headers()
    reviewer.review_range_macros()
    return reviewer.generate_report(Path(output_path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Implementation Content Review - 检查生成的 C/PDM/header 内容合规性",
    )
    parser.add_argument("--impl-dir", default="outputs/implementation",
                        help="Implementation output directory (default: outputs/implementation)")
    parser.add_argument("--fscs-json", default="outputs/fscs/fscs.json",
                        help="权威 fscs.json 输入路径 (default: outputs/fscs/fscs.json)")
    parser.add_argument("--output", "-o",
                        default="outputs/implementation/impl_review_report.txt",
                        help="Review 报告输出路径")
    args = parser.parse_args()

    fscs_json_path = Path(args.fscs_json)
    if not fscs_json_path.is_file():
        print(f"❌ 错误: 找不到 fscs.json: {fscs_json_path}")
        print("   请先运行 Phase 1 生成 fscs.json, 例如:")
        print("       python scripts/pipeline.py --phase fscs --input <your-did>.json")
        return 2

    try:
        print("=" * 70)
        print("Implementation Content Review")
        print("=" * 70)
        print()
        result = run_review(
            impl_dir=Path(args.impl_dir),
            fscs_json=fscs_json_path,
            output_path=Path(args.output),
        )
        summary = result["summary"]
        print(f"  JSON DID 数: {summary['dids_json_count']}")
        print(f"  Effective DID 数 (supported_by_ecu=Y): {summary['dids_effective_count']}")
        print()
        if result["has_issues"]:
            print(f"⚠️  发现 {len(result['issues'])} 个问题:")
            for issue in result["issues"]:
                tag = f"[{issue.did}] " if issue.did not in ("-", "", None) else ""
                print(f"   [{issue.type}] {tag}{issue.message}")
            print(f"\n详细报告: {args.output}")
            return 1
        print("✅ 所有检查通过")
        return 0
    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        return 2
    except Exception as e:
        print(f"❌ Review 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
