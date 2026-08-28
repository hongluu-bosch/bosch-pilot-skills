from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Tuple

from io_encoding import save_json, save_text

from .analysis import collect_evidence
from .generator import build_snapshot_c_content, build_snapshot_c_filename, try_build_real_snapshot_c_content
from .models import SnapshotDIDInfo
from .paths import resolve_snapshot_c_output_dir
from .strategies import build_real_content


def run_snapshot_c_generation(workspace: Path, args: Any) -> int:
    json_path = workspace / "outputs" / "fscs" / "fscs.json"
    if not json_path.exists():
        print(f"[ERROR] {json_path} not found. Run --phase fscs first.")
        return 1

    doc = json.loads(json_path.read_text(encoding="utf-8"))
    config = json.loads((workspace / "config" / "project.json").read_text(encoding="utf-8"))
    record_numbers = doc.get("dtc_snapshot_record_numbers", ["0x01", "0xFF"])

    dids = [_to_model(d) for d in doc.get("dids", []) if d.get("used", True)]
    workspace_hooks = _load_workspace_hooks(workspace)
    reports_root = workspace / "outputs" / "c"
    reports_root.mkdir(parents=True, exist_ok=True)

    written_total = 0
    skipped_total = 0
    generated_paths: Dict[str, str] = {}

    for product_type in sorted({d.product_type or "Common" for d in dids}):
        product_dids = [d for d in dids if (d.product_type or "Common") == product_type]
        output_dir = resolve_snapshot_c_output_dir(config, product_type)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_dir = reports_root / product_type
        report_dir.mkdir(parents=True, exist_ok=True)

        written: List[str] = []
        skipped: List[str] = []
        fill_ready: List[str] = []
        fill_skipped: List[str] = []
        filled: List[str] = []
        for did in product_dids:
            filename = build_snapshot_c_filename(did)
            path = output_dir / filename
            project_notes_override = _apply_workspace_notes_hook(workspace_hooks, did)
            evidence = collect_evidence(did, project_notes_override=project_notes_override)
            ready = evidence.can_generate
            reason = evidence.reason
            if ready:
                fill_ready.append(f"{did.did_hex} {did.read_fnc} -> {path}")
            else:
                fill_skipped.append(f"{did.did_hex} {did.read_fnc} -> {reason}")

            real_content = build_real_content(did, record_numbers, evidence) if ready else None
            if path.exists():
                # Existing files always win; do not overwrite. Report potential fill targets only.
                skipped.append(str(path))
            else:
                content = real_content or build_snapshot_c_content(did, record_numbers)
                path.write_text(content, encoding="utf-8")
                written.append(str(path))
                if real_content is not None:
                    filled.append(f"{did.did_hex} {did.read_fnc} -> {path}")
            generated_paths[did.did_hex] = str(path)

        written_total += len(written)
        skipped_total += len(skipped)
        save_text(
            report_dir / "generation_report.txt",
            _build_report(product_type, written, skipped, fill_ready, fill_skipped, filled),
        )

    _write_generated_paths_back(json_path, doc, generated_paths)

    print(f"[OK] Phase 3 complete. {written_total} written / {skipped_total} skipped.")
    print("[AGENT REVIEW] Snapshot C stubs generated. Review TODO(agent) blocks before implementation.")
    return 0


def _to_model(did: Dict[str, Any]) -> SnapshotDIDInfo:
    return SnapshotDIDInfo(
        did_hex=did["did_hex"],
        did_name_en=did.get("did_name_en", ""),
        did_name_zh=did.get("did_name_zh", ""),
        size_bytes=did.get("size_bytes", 1),
        read_fnc=did.get("read_fnc", ""),
        product_type=did.get("product_type", "Common"),
        used=did.get("used", True),
        sub_fields=did.get("sub_fields", []),
        impl_signal_list=did.get("impl_signal_list", ""),
        impl_notes=did.get("impl_notes", ""),
    )


def _build_report(product_type: str, written: List[str], skipped: List[str],
                  fill_ready: List[str], fill_skipped: List[str], filled: List[str]) -> str:
    lines = [
        f"Generated snapshot read stubs for product {product_type}",
        f"Files written: {len(written)}",
        f"Files skipped (already exist): {len(skipped)}",
        f"Fill-ready DIDs: {len(fill_ready)}",
        f"Skipped fill due to insufficient input: {len(fill_skipped)}",
        f"Auto-filled real implementations: {len(filled)}",
        "",
    ]
    if written:
        lines.append("Written:")
        for path in written:
            lines.append(f"  + {path}")
    if skipped:
        lines.append("Skipped:")
        for path in skipped:
            lines.append(f"  = {path}")
    if fill_ready:
        lines.append("Fill-ready:")
        for item in fill_ready:
            lines.append(f"  > {item}")
    if fill_skipped:
        lines.append("Skipped fill:")
        for item in fill_skipped:
            lines.append(f"  ! {item}")
    if filled:
        lines.append("Filled:")
        for item in filled:
            lines.append(f"  # {item}")
    return "\n".join(lines) + "\n"




def _write_generated_paths_back(json_path: Path, doc: Dict[str, Any], generated_paths: Dict[str, str]) -> None:
    for did in doc.get("dids", []):
        if did.get("did_hex") in generated_paths:
            did["generated_c_file"] = generated_paths[did["did_hex"]]
    save_json(json_path, doc)


def _load_workspace_hooks(workspace: Path) -> Dict[str, Any]:
    hooks: Dict[str, Any] = {}
    scripts_dir = workspace / "scripts"
    hook_files = {
        "parse_impl_notes_project": scripts_dir / "parse_impl_notes_project.py",
        "derive_snapshot_rules": scripts_dir / "derive_snapshot_rules.py",
    }
    for key, path in hook_files.items():
        if not path.exists():
            continue
        spec = importlib.util.spec_from_file_location(key, str(path))
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hooks[key] = module
    return hooks


def _apply_workspace_notes_hook(hooks: Dict[str, Any], did: SnapshotDIDInfo):
    module = hooks.get("parse_impl_notes_project")
    if module is None or not hasattr(module, "parse_project_impl_notes"):
        return None
    return module.parse_project_impl_notes(did.__dict__)
