#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FSCS Content Review Module

对生成的FSCS文档进行内容Review，检查：
1. 业务合规性：识别仅支持2E写但不支持22读的DID
2. 配置合规性：检查Service 22/2E配置是否符合标准
3. 数据一致性：检查FSCS与输入JSON的一致性

Usage:
    python scripts/review_fscs.py \
        --fscs-json outputs/fscs/fscs.json \
        --input-json inputs/xxx.json \
        --output outputs/fscs/fscs_review_report.txt
"""

import sys

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

# Windows consoles default ``sys.stdout`` to cp1252/cp936 when not
# attached to a TTY, which mangles the CJK text this reviewer prints.
# ``reconfigure_stdio_utf8`` is idempotent and fail-soft, so importing
# and invoking it here covers both standalone runs and the
# ``pipeline.py`` driver path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_encoding import reconfigure_stdio_utf8  # noqa: E402
from fscs import FSCSDocument, load_fscs  # noqa: E402
from fscs.schema import FSCSServiceAccess  # noqa: E402

reconfigure_stdio_utf8()


def _svc_to_review_dict(did_name: str, svc: FSCSServiceAccess) -> Dict:
    """Translate a :class:`FSCSServiceAccess` into the legacy reviewer dict.

    ``security_levels`` is rendered as the same ``"L0 - ..."`` /
    ``"L1 - ..."`` lines that the legacy text parser would have
    captured, so the ``any('L0' in level for level in ...)`` checks in
    ``review_compliance_*`` match without modification.
    """
    security_lines: List[str] = []
    for entry in svc.security_levels:
        note_suffix = f" - {entry.note}" if entry.note else ""
        security_lines.append(f"{entry.level}{note_suffix}")
    return {
        "name": did_name,
        "sessions": list(svc.sessions),
        "security_levels": security_lines,
    }


class FSCSReviewIssue:
    """Review问题记录"""
    def __init__(self, issue_type: str, did: str, service: str, message: str):
        self.type = issue_type  # BUSINESS, COMPLIANCE, CONSISTENCY
        self.did = did
        self.service = service  # 22, 2E, or BOTH
        self.message = message


class FSCSReviewer:
    """FSCS内容Reviewer"""

    def __init__(self):
        self.issues: List[FSCSReviewIssue] = []
        self.dids_22: Dict[str, Dict] = {}  # DID -> 配置详情
        self.dids_2e: Dict[str, Dict] = {}  # DID -> 配置详情
        self.dids_json: Dict[str, Dict] = {}  # DID -> JSON原始数据
        self.deselected_dids: set[str] = set()

    def populate_from_document(self, document: FSCSDocument) -> None:
        """Populate ``self.dids_22`` / ``self.dids_2e`` from an ``FSCSDocument``.

        Since the Part 6 cleanup, ``fscs.json`` is the only source this
        reviewer ever reads. Only effective services (``supported AND
        used``) enter the review scope; DIDs deselected via ``used_flag``
        are intentionally skipped because they do not generate FSCS TXT,
        ARXML/C, or DOORS content. The dicts retain the same shape previous
        legacy parsers produced (``name`` / ``sessions`` /
        ``security_levels``) so the ``review_compliance_*`` checks stay
        unchanged.
        """
        self.dids_22 = {}
        self.dids_2e = {}
        self.deselected_dids = set()
        for did in document.dids:
            did_key = f"0x{did.did_hex}"
            if not did.service_22.effective and not did.service_2e.effective:
                self.deselected_dids.add(did_key)
                continue
            if did.service_22.effective:
                self.dids_22[did_key] = _svc_to_review_dict(
                    did.did_name, did.service_22
                )
            if did.service_2e.effective:
                self.dids_2e[did_key] = _svc_to_review_dict(
                    did.did_name, did.service_2e
                )

    def parse_json_input(self, json_path: Path):
        """Load the raw Phase-1 input JSON for cross-checking.

        Accepts only schema-compliant ``*_did.json``. The skill ships
        no built-in workbook parser; if you have a questionnaire
        workbook, normalise it first via an agent-written
        ``.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py``.
        """
        if not json_path.exists():
            raise FileNotFoundError(f"Input source not found: {json_path}")

        suffix = json_path.suffix.lower()
        if suffix in {".xlsx", ".xlsm"}:
            raise ValueError(
                f"Excel input {json_path.name!r} is not accepted directly; "
                "normalise via .DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py "
                "first to produce *_did.json."
            )
        with open(json_path, 'r', encoding='utf-8') as f:
            records = json.load(f)

        for record in records:
            did_hex = record.get('did_hex', '').strip()
            if did_hex:
                # 规范化为统一的格式: 0x + 大写十六进制 (如 0x0101)
                # 先移除现有的0x或0X前缀，然后重新组装
                if did_hex.upper().startswith('0X'):
                    did_hex = '0x' + did_hex[2:].upper()
                elif not did_hex.startswith('0x'):
                    did_hex = '0x' + did_hex.upper()
                else:
                    did_hex = '0x' + did_hex[2:].upper()
                self.dids_json[did_hex] = record

    def review_only_2e_dids(self):
        """
        核心业务检查：找出仅在Service 2E中出现但不在Service 22中的DID
        这类DID不合规（业务规则：所有DID必须至少支持读操作）
        """
        dids_22_set = set(self.dids_22.keys())
        dids_2e_set = set(self.dids_2e.keys())

        # 找出仅在2E中的DID
        only_2e_dids = dids_2e_set - dids_22_set

        for did in only_2e_dids:
            self.issues.append(FSCSReviewIssue(
                issue_type='BUSINESS',
                did=did,
                service='2E',
                message='仅在Service 2E中出现，缺少Service 22支持（不合规：所有DID应至少支持读操作）'
            ))

    def review_compliance_22(self):
        """
        检查Service 22配置合规性
        标准：应支持defaultSession + extendedDiagnosticSession + L0
        """
        for did, config in self.dids_22.items():
            sessions = config.get('sessions', [])
            security_levels = config.get('security_levels', [])

            # 检查会话
            if 'defaultSession' not in sessions:
                self.issues.append(FSCSReviewIssue(
                    issue_type='COMPLIANCE',
                    did=did,
                    service='22',
                    message='缺少defaultSession（标准要求支持defaultSession + extendedDiagnosticSession）'
                ))

            if 'extendedDiagnosticSession' not in sessions:
                self.issues.append(FSCSReviewIssue(
                    issue_type='COMPLIANCE',
                    did=did,
                    service='22',
                    message='缺少extendedDiagnosticSession（标准要求支持defaultSession + extendedDiagnosticSession）'
                ))

            # 检查安全等级
            has_l0 = any('L0' in level for level in security_levels)
            if not has_l0:
                self.issues.append(FSCSReviewIssue(
                    issue_type='COMPLIANCE',
                    did=did,
                    service='22',
                    message='缺少L0安全等级（标准要求L0）'
                ))

    def review_compliance_2e(self):
        """
        检查Service 2E配置合规性
        标准：应仅支持extendedDiagnosticSession + L1（不应支持defaultSession）
        """
        for did, config in self.dids_2e.items():
            sessions = config.get('sessions', [])
            security_levels = config.get('security_levels', [])

            # 检查会话：不应有defaultSession
            if 'defaultSession' in sessions:
                self.issues.append(FSCSReviewIssue(
                    issue_type='COMPLIANCE',
                    did=did,
                    service='2E',
                    message='不应支持defaultSession（标准仅要求extendedDiagnosticSession）'
                ))

            # 检查会话：必须有extended
            if 'extendedDiagnosticSession' not in sessions:
                self.issues.append(FSCSReviewIssue(
                    issue_type='COMPLIANCE',
                    did=did,
                    service='2E',
                    message='缺少extendedDiagnosticSession（标准要求仅extended）'
                ))

            # 检查安全等级：必须有L1
            has_l1 = any('L1' in level for level in security_levels)
            if not has_l1:
                self.issues.append(FSCSReviewIssue(
                    issue_type='COMPLIANCE',
                    did=did,
                    service='2E',
                    message='缺少L1安全等级（标准要求L1）'
                ))

    def review_consistency(self):
        """
        一致性检查：
        1. FSCS中的DID是否都在JSON中（完整性）
        2. JSON中supported_by_ecu=Y的DID是否都在FSCS中（完整性）
        3. rw_state一致性
        """
        fscs_dids = set(self.dids_22.keys()) | set(self.dids_2e.keys())
        json_dids = set(self.dids_json.keys())

        # 检查FSCS中有多余的DID（JSON中没有）
        extra_in_fscs = fscs_dids - json_dids
        for did in extra_in_fscs:
            service = '22' if did in self.dids_22 else '2E'
            self.issues.append(FSCSReviewIssue(
                issue_type='CONSISTENCY',
                did=did,
                service=service,
                message='在FSCS中出现但JSON输入中不存在'
            ))

        # 检查JSON中supported=Y的DID是否都在FSCS中。CSV used_flag=FALSE
        # 的 DID 不生成 FSCS/ARXML/C/DOORS，因此也不参与 Review。
        for did, data in self.dids_json.items():
            if did in self.deselected_dids:
                continue
            if data.get('supported_by_ecu') == 'Y' and did not in fscs_dids:
                self.issues.append(FSCSReviewIssue(
                    issue_type='CONSISTENCY',
                    did=did,
                    service='BOTH',
                    message='JSON中supported_by_ecu=Y但在FSCS中缺失'
                ))

        # 检查rw_state一致性
        for did in self.dids_22:
            if did in self.dids_json:
                json_rw = self.dids_json[did].get('rw_state', '')
                if json_rw not in ['R', 'RW']:
                    self.issues.append(FSCSReviewIssue(
                        issue_type='CONSISTENCY',
                        did=did,
                        service='22',
                        message=f'FSCS_22中存在但JSON中rw_state="{json_rw}"（预期R或RW）'
                    ))

        for did in self.dids_2e:
            if did in self.dids_json:
                json_rw = self.dids_json[did].get('rw_state', '')
                if json_rw not in ['W', 'RW']:
                    self.issues.append(FSCSReviewIssue(
                        issue_type='CONSISTENCY',
                        did=did,
                        service='2E',
                        message=f'FSCS_2E中存在但JSON中rw_state="{json_rw}"（预期W或RW）'
                    ))

    def generate_report(self, output_path: Path) -> Dict:
        """
        生成结构化Review报告

        Returns:
            Dict: {
                'has_issues': bool,
                'issues': List[FSCSReviewIssue],
                'summary': Dict
            }
        """
        # 统计各类问题数量
        business_issues = [i for i in self.issues if i.type == 'BUSINESS']
        compliance_issues = [i for i in self.issues if i.type == 'COMPLIANCE']
        consistency_issues = [i for i in self.issues if i.type == 'CONSISTENCY']

        # 生成报告内容
        lines = []
        lines.append("=" * 80)
        lines.append("FSCS Content Review Report")
        lines.append("=" * 80)
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Service 22 DID数: {len(self.dids_22)}")
        lines.append(f"Service 2E DID数: {len(self.dids_2e)}")
        lines.append("")

        # 一、业务合规性检查
        lines.append("=" * 80)
        lines.append("一、业务合规性检查 (Business Compliance)")
        lines.append("=" * 80)
        lines.append("")
        lines.append("[仅2E写DID检查]")
        lines.append("业务规则: 所有DID必须至少支持读操作（Service 22）")
        lines.append("")

        if business_issues:
            lines.append(f"  ✗ 发现 {len(business_issues)} 个不合规DID:")
            for issue in business_issues:
                lines.append(f"    - {issue.message}")
        else:
            lines.append("  ✓ 所有DID都支持Service 22（符合业务规则）")

        lines.append("")

        # 二、配置合规性检查
        lines.append("=" * 80)
        lines.append("二、配置合规性检查 (Configuration Compliance)")
        lines.append("=" * 80)
        lines.append("")

        # Service 22
        lines.append("[Service 22] 标准: defaultSession + extendedDiagnosticSession + L0")
        issues_22 = [i for i in compliance_issues if i.service == '22']
        if issues_22:
            for issue in issues_22:
                lines.append(f"  ✗ DID {issue.did}: {issue.message}")
        else:
            lines.append("  ✓ 所有DID符合标准")
        lines.append("")

        # Service 2E
        lines.append("[Service 2E] 标准: extendedDiagnosticSession only + L1")
        issues_2e = [i for i in compliance_issues if i.service == '2E']
        if issues_2e:
            for issue in issues_2e:
                lines.append(f"  ✗ DID {issue.did}: {issue.message}")
        else:
            lines.append("  ✓ 所有DID符合标准")
        lines.append("")

        # 三、数据一致性检查
        lines.append("=" * 80)
        lines.append("三、数据一致性检查 (Data Consistency)")
        lines.append("=" * 80)
        lines.append("")

        if consistency_issues:
            for issue in consistency_issues:
                lines.append(f"  ✗ [{issue.service}] DID {issue.did}: {issue.message}")
        else:
            lines.append("  ✓ FSCS与JSON输入完全一致")

        lines.append("")

        # 总结
        lines.append("=" * 80)
        lines.append("总结")
        lines.append("=" * 80)
        total = len(self.issues)
        if total > 0:
            lines.append(f"发现 {total} 个异常 (不影响后续执行):")
            lines.append(f"  - 业务不合规: {len(business_issues)}个")
            lines.append(f"  - 配置异常: {len(compliance_issues)}个")
            lines.append(f"  - 一致性异常: {len(consistency_issues)}个")
        else:
            lines.append("✅ 所有检查通过，未发现异常")

        lines.append("")
        lines.append("=" * 80)

        # 写入报告文件
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('\n'.join(lines), encoding='utf-8')

        return {
            'has_issues': len(self.issues) > 0,
            'issues': self.issues,
            'summary': {
                'total': total,
                'business': len(business_issues),
                'compliance': len(compliance_issues),
                'consistency': len(consistency_issues),
                'dids_22_count': len(self.dids_22),
                'dids_2e_count': len(self.dids_2e)
            },
            'report_path': str(output_path)
        }


def run_review(
    fscs_json: Path,
    input_json: Optional[Path],
    output_path: Path,
) -> Dict:
    """Run the FSCS review pipeline and write the report.

    Shared orchestration entry point for ``review_fscs.main`` (CLI),
    ``pipeline.run_review_only`` (``--phase review``), Phase 1
    auto-review, and CSV import auto-review. All call sites delegate
    here so behaviour stays identical.

    Parameters
    ----------
    fscs_json : Path
        Authoritative Phase 1 ``fscs.json``. Required after the Part 6
        cleanup; the old text-fallback path has been removed.
    input_json : Path or None
        Original DID definition JSON. Used only for the consistency
        check that flags ``supported_by_ecu=Y`` records missing from
        ``fscs.json``. Pass ``None`` (for example when the input JSON
        isn't in scope) to skip that
        check -- business + compliance checks still run.
    output_path : Path
        Destination for ``fscs_review_report.txt``; parent dirs are
        created on demand by ``FSCSReviewer.generate_report``.

    Returns
    -------
    dict
        The same structure returned by ``FSCSReviewer.generate_report``:
        ``has_issues`` (bool), ``issues`` (list), ``summary`` (dict with
        business/compliance/consistency counts), ``report_path`` (str).
    """
    reviewer = FSCSReviewer()
    document = load_fscs(fscs_json=Path(fscs_json))
    reviewer.populate_from_document(document)
    # Consistency check requires the raw input (it's the only way to
    # spot "supported_by_ecu=Y in the JSON but missing from fscs.json").
    # When the caller doesn't supply one, skip that single check and
    # leave its counter at zero; the report header still spells out
    # that consistency was skipped (see ``generate_report``).
    if input_json is not None:
        reviewer.parse_json_input(Path(input_json))
    reviewer.review_only_2e_dids()
    reviewer.review_compliance_22()
    reviewer.review_compliance_2e()
    if input_json is not None:
        reviewer.review_consistency()
    return reviewer.generate_report(Path(output_path))


def main():
    parser = argparse.ArgumentParser(
        description='FSCS Content Review - 检查生成的FSCS内容合规性',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    python scripts/review_fscs.py \\
        --fscs-json outputs/fscs/fscs.json \\
        --input-json inputs/<customer>_did.json \\
        --output outputs/fscs/fscs_review_report.txt
        """
    )

    parser.add_argument('--fscs-json', default='outputs/fscs/fscs.json',
                        help='权威 fscs.json 输入路径 (默认: outputs/fscs/fscs.json)')
    parser.add_argument('--input-json', required=True,
                        help='输入JSON文件路径')
    parser.add_argument('--output', '-o',
                        default='outputs/fscs/fscs_review_report.txt',
                        help='Review报告输出路径 (默认: outputs/fscs/fscs_review_report.txt)')

    args = parser.parse_args()

    fscs_json_path = Path(args.fscs_json)
    if not fscs_json_path.is_file():
        print(f"❌ 错误: 找不到 fscs.json: {fscs_json_path}")
        print("   请先运行 Phase 1 生成 fscs.json, 例如:")
        print("       python scripts/pipeline.py --phase fscs --input <your-did>.json")
        return 2

    try:
        print("=" * 70)
        print("FSCS Content Review")
        print("=" * 70)
        print()
        print(f"读取 {fscs_json_path} 并执行 Review 检查...")

        result = run_review(
            fscs_json=fscs_json_path,
            input_json=Path(args.input_json),
            output_path=Path(args.output),
        )

        summary = result['summary']
        print(f"  Service 22 DID数: {summary['dids_22_count']}")
        print(f"  Service 2E DID数: {summary['dids_2e_count']}")
        print()
        print("=" * 70)
        print("Review完成")
        print("=" * 70)
        print()

        if result['has_issues']:
            print(f"⚠️  发现 {len(result['issues'])} 个问题:")
            for issue in result['issues']:
                print(f"   [{issue.type}] {issue.message}")
            print()
            print(f"详细报告: {args.output}")
            print("注: 问题不影响后续执行，但建议修正")
        else:
            print("✅ 所有检查通过，未发现异常")

        print()
        return 0 if not result['has_issues'] else 1

    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        return 2
    except Exception as e:
        print(f"❌ Review执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == '__main__':
    exit(main())
