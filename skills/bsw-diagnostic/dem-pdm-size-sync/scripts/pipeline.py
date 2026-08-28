#!/usr/bin/env python3
"""Unified entrypoint for dem-pdm-size-sync."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from workspace import init_workspace, load_project_config, resolve_paths


SCRIPT_DIR = Path(__file__).resolve().parent
ANALYZER = SCRIPT_DIR / "analyze_variant.py"
SKILL_ROOT = SCRIPT_DIR.parent


def run_analyzer(args: argparse.Namespace, apply: bool = False, verify: bool = False) -> int:
    project_root = Path(args.project_root).resolve()
    paths = resolve_paths(project_root, SKILL_ROOT)
    cmd = [
        sys.executable,
        str(ANALYZER),
        "--project-root",
        str(project_root),
        "--buildconfig",
        args.buildconfig,
        "--target",
        args.target,
    ]
    if args.json:
        cmd.append("--json")
    if args.force_fallback:
        cmd.append("--force-fallback")
    if apply:
        cmd.append("--apply")
    if verify:
        cmd.append("--verify")
    completed = subprocess.run(cmd, check=False, capture_output=args.json, text=args.json, encoding="utf-8")
    if args.json:
        if completed.stdout:
            payload = json.loads(completed.stdout)
            text = format_summary(payload)
            init_workspace(paths)
            stem = "verify_report" if verify else ("apply_report" if apply else "latest_report")
            from workspace import save_report

            save_report(paths, stem, payload, text)
            print(completed.stdout)
        if completed.stderr:
            print(completed.stderr, file=sys.stderr)
    else:
        if completed.stdout:
            print(completed.stdout, end="")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
    return completed.returncode


def format_summary(payload: dict) -> str:
    lines = [
        "Buildconfig",
        f"- {payload.get('buildconfig', '')}",
        "",
        "Target",
        f"- {payload.get('target', '')}",
        f"- {payload.get('display_name', '')}",
        "",
        "Effective Context",
        f"- Active PDM file: {payload.get('effective_pdm_file', '')}",
        f"- ApbDistributed: {payload.get('rbfs_apbdistributed', '')}",
        "",
        "Size Analysis",
        f"- Real size: {payload.get('real_struct_size', '')} bytes",
        f"- Size source: {payload.get('size_source', '')}",
        "",
        "Current PDM Mapping",
        f"- Current family: {payload.get('current_dataitem_family', '')}",
        f"- Current PDM size: {payload.get('current_pdm_size', '')}",
        f"- Assertion size: {payload.get('assertion_size', '')}",
    ]
    verify = payload.get("verify_result")
    if verify:
        lines.extend(
            [
                "",
                "Verification",
                f"- Assertion header matches target: {verify.get('assertion_matches')}",
                f"- ARXML NvM block length matches target: {verify.get('arxml_matches')}",
                f"- NvM_Cfg.h matches target: {verify.get('nvm_cfg_matches')}",
            ]
        )
    return "\n".join(lines) + "\n"


def run_init_project(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    paths = resolve_paths(project_root, SKILL_ROOT)
    init_workspace(paths)
    print(f"Workspace initialized: {paths.workspace_root}")
    print(f"Project config: {paths.project_json}")
    return 0


def run_status(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    paths = resolve_paths(project_root, SKILL_ROOT)
    print(f"Project root: {paths.project_root}")
    print(f"Workspace root: {paths.workspace_root}")
    print(f"Workspace exists: {paths.workspace_root.exists()}")
    print(f"Project config exists: {paths.project_json.exists()}")
    if paths.project_json.exists():
        print(json.dumps(load_project_config(paths), indent=2, ensure_ascii=False))
    for stem in ("latest_report", "apply_report", "verify_report"):
        report = paths.outputs_dir / f"{stem}.json"
        print(f"{stem}: {'present' if report.exists() else 'missing'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dem-pdm-size-sync")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--project-root", required=True)
        sub.add_argument("--buildconfig", required=True)
        sub.add_argument("--target", choices=["evmem", "generic"], default="evmem")
        sub.add_argument("--json", action="store_true")
        sub.add_argument("--force-fallback", action="store_true")

    analyze = subparsers.add_parser("analyze", help="Analyze current DEM/PDM size mapping")
    add_common(analyze)

    apply = subparsers.add_parser("apply", help="Apply minimal current-project update")
    add_common(apply)

    verify = subparsers.add_parser("verify", help="Verify generated outputs against target size")
    add_common(verify)

    init_project = subparsers.add_parser("init-project", help="Initialize project-local .DCOM_AI workspace")
    init_project.add_argument("--project-root", required=True)

    status = subparsers.add_parser("status", help="Show project-local workspace status")
    status.add_argument("--project-root", required=True)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "analyze":
        return run_analyzer(args)
    if args.command == "apply":
        return run_analyzer(args, apply=True)
    if args.command == "verify":
        return run_analyzer(args, verify=True)
    if args.command == "init-project":
        return run_init_project(args)
    if args.command == "status":
        return run_status(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
