"""Print the runtime context an agent needs before using the skill.

This script is intentionally stdlib-only and read-only. It exists so an
LLM does not have to discover the skill root, project root, input files,
or CusDiag ARXML paths by browsing the repository.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_ROOT / "assets"

# v2.0.0: workspace lives under <project>/.DCOM_AI/DiagComm_Toolkit_PRJ/
# (cwd-anchored at import time -- callers cd into the project root
# before invoking the skill). Keep this in sync with runtime.py.
WORKSPACE_NAME = "DiagComm_Toolkit_PRJ"
DCOM_AI_DIRNAME = ".DCOM_AI"
WORKSPACE_ROOT = (Path.cwd() / DCOM_AI_DIRNAME / WORKSPACE_NAME).resolve()

INPUTS_DIR = WORKSPACE_ROOT / "inputs"
OUTPUTS_DIR = WORKSPACE_ROOT / "outputs"
STATE_DIR = WORKSPACE_ROOT / "state"
CACHE_DIR = WORKSPACE_ROOT / ".cache"

# Single user-editable input (workspace) + skill-bundled templates.
XLSX_PATH = INPUTS_DIR / "DiagComm.xlsx"
TEMPLATE_PATH = ASSETS_DIR / "inputs_template.xlsx"
DOORS_SKELETON_PATH = ASSETS_DIR / "doors_mapping_skeleton.yaml"
VALUES_PATH = CACHE_DIR / "DiagComm_values.json"
CONFIG_PATH = CACHE_DIR / "DiagComm_config.json"
DOORS_MAPPING_PATH = CACHE_DIR / "doors_mapping.yaml"

DEFAULT_PATHS: dict[str, str] = {
    "base_dir": "../..",
    "dcom_root": "*/rb/as/*/core/app/dcom",
    "cantp_common": "RBAPLCust/cfg/Common/CanTp_CusDiag_EcucValues.arxml",
    "cantp_feature_file": "Cubas/cfg/CanTp_Feature_EcucValues.arxml",
    "dcm_common": "RBAPLCust/cfg/Common/Dcm_CusDiag_Can_EcucValues.arxml",
    "dcm_feature_file": "Cubas/cfg/Dcm_Feature_EcucValues.arxml",
    "dcm_services_common": "RBAPLCust/cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml",
    "can_pt_file": "RBAPLCust/cfg/{product_type}/Can{can_channel}_CusDiag_EcucValues_{product_type}.arxml",
}

TARGET_ALIASES = (
    "cantp_common",
    "cantp_feature_file",
    "dcm_common",
    "dcm_feature_file",
    "dcm_services_common",
    "can_pt_file",
)

PLACEHOLDER_VALUES = frozenset({
    "<fill-me>",
    "<set-me>",
    "<set-me-on-first-launch>",
    "<bootstrap>",
})


def _strip_doc_keys(payload: Any) -> Any:
    """Drop top-level / nested keys that start with ``_`` (e.g. ``_README``)."""
    if isinstance(payload, dict):
        return {k: _strip_doc_keys(v) for k, v in payload.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(payload, list):
        return [_strip_doc_keys(v) for v in payload]
    return payload


def _is_unfilled(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        s = value.strip()
        if not s or s in PLACEHOLDER_VALUES:
            return True
    return False


def _fillness_check(values: dict[str, Any] | None,
                    schema: dict[str, Any] | None) -> list[str]:
    """Inline mirror of pipeline.py::_check_template_fillness, kept
    stdlib-only so context.py never has to import the heavier modules.
    Returns one human-readable line per unfilled prompt-required field.
    """
    if not isinstance(values, dict):
        return []
    project = _coerce_mapping(values, "project")
    parameters = _coerce_mapping(values, "parameters")
    fields = (schema or {}).get("fields") if isinstance(schema, dict) else None
    fields = fields if isinstance(fields, dict) else {}

    out: list[str] = []
    if _is_unfilled(project.get("name")):
        out.append("project.name")
    if _is_unfilled(project.get("product_type")):
        spec = fields.get("product_type") or {}
        allowed = spec.get("allowed")
        hint = ""
        if isinstance(allowed, list) and allowed:
            hint = f" ({'/'.join(map(str, allowed))})"
        out.append(f"project.product_type{hint}")

    def _walk(prefix: str, sub_schema: dict[str, Any], sub_values: Any) -> None:
        for key, spec in sub_schema.items():
            if not isinstance(spec, dict):
                continue
            if not prefix and key == "product_type":
                continue
            full = f"parameters.{key}" if not prefix else f"{prefix}.{key}"
            if spec.get("type") == "object":
                child = sub_values.get(key) if isinstance(sub_values, dict) else None
                _walk(full, spec.get("fields") or {}, child if isinstance(child, dict) else {})
                continue
            if not spec.get("prompt_required"):
                continue
            value = sub_values.get(key) if isinstance(sub_values, dict) else None
            if _is_unfilled(value):
                bits: list[str] = []
                if spec.get("type"):
                    bits.append(str(spec["type"]))
                allowed = spec.get("allowed")
                if isinstance(allowed, list) and allowed:
                    bits.append("in: " + "/".join(map(str, allowed)))
                if spec.get("unit"):
                    bits.append(str(spec["unit"]))
                hint = f" ({', '.join(bits)})" if bits else ""
                out.append(f"{full}{hint}")

    _walk("", fields, parameters)
    return out


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - diagnostics should not crash.
        return None, f"parse error: {exc}"
    if not isinstance(data, dict):
        return None, "not a JSON object"
    return data, None


def _status(path: Path) -> str:
    return "OK" if path.exists() else "MISSING"


def _rel(path: Path) -> str:
    """Pretty-print a path relative to cwd (the project root) when
    possible, falling back to the absolute form. v2 paths cross both
    the skill (~/.cursor/skills/...) and the workspace
    (<project>/.DCOM_AI/...) so cwd is the only useful anchor."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def _coerce_mapping(data: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _resolve_base_dir(paths: dict[str, Any]) -> Path:
    raw = str(paths.get("base_dir") or DEFAULT_PATHS["base_dir"])
    base = Path(raw)
    if not base.is_absolute():
        base = WORKSPACE_ROOT / base
    return base.resolve()


def _find_dcom_roots(base_dir: Path, paths: dict[str, Any]) -> list[Path]:
    pattern = str(paths.get("dcom_root") or DEFAULT_PATHS["dcom_root"])
    try:
        return sorted(p.resolve() for p in base_dir.glob(pattern) if p.is_dir())
    except (OSError, RuntimeError):
        return []


def _format_target(template: str, product_type: str, can_channel: Any) -> str:
    try:
        return template.format(product_type=product_type, can_channel=can_channel)
    except Exception:
        return template


def _refresh_cache_quietly() -> str | None:
    """Auto-regenerate ``<workspace>/.cache/`` from
    ``<workspace>/inputs/DiagComm.xlsx``.

    Best-effort: failures are returned as a short error string so the
    dashboard can show the user what happened (instead of crashing
    context.py, which is supposed to be diagnosis-friendly).
    """
    if not WORKSPACE_ROOT.exists():
        return (f"workspace missing at {_rel(WORKSPACE_ROOT)} "
                "-- run --init-project")
    if not XLSX_PATH.exists():
        return f"{_rel(XLSX_PATH)} missing -- run --init-project --force"
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import excel_loader  # noqa: PLC0415  -- lazy: heavy openpyxl import
        excel_loader.load_or_refresh(
            xlsx_path=XLSX_PATH,
            skeleton_path=DOORS_SKELETON_PATH,
            cache_dir=CACHE_DIR,
        )
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


def build_context() -> dict[str, Any]:
    cache_error = _refresh_cache_quietly()
    values_raw, values_error = _load_json(VALUES_PATH)
    config_raw, config_error = _load_json(CONFIG_PATH)
    values = _strip_doc_keys(values_raw) if isinstance(values_raw, dict) else None
    config = _strip_doc_keys(config_raw) if isinstance(config_raw, dict) else None
    schema_raw, _ = _load_json(ASSETS_DIR / "DiagComm_schema.json")
    schema = schema_raw if isinstance(schema_raw, dict) else None

    paths = dict(DEFAULT_PATHS)
    paths.update(_coerce_mapping(config, "paths"))

    project = _coerce_mapping(values, "project")
    parameters = _coerce_mapping(values, "parameters")
    product_type = str(project.get("product_type") or "<unknown>")
    project_name = str(project.get("name") or "<unknown>")
    can_channel = parameters.get("CAN_Channel", "<unknown>")

    base_dir = _resolve_base_dir(paths)
    dcom_roots = _find_dcom_roots(base_dir, paths)
    primary_dcom = dcom_roots[0] if dcom_roots else None

    target_files: list[dict[str, str]] = []
    for alias in TARGET_ALIASES:
        template = str(paths.get(alias) or DEFAULT_PATHS[alias])
        rel_path = _format_target(template, product_type, can_channel)
        abs_path = (primary_dcom / rel_path).resolve() if primary_dcom else None
        target_files.append({
            "alias": alias,
            "relative_path": rel_path,
            "status": _status(abs_path) if abs_path else "UNKNOWN",
            "absolute_path": abs_path.as_posix() if abs_path else "",
        })

    inputs = {
        "DiagComm.xlsx (user)": _status(XLSX_PATH),
    }
    cache = {
        "DiagComm_values.json": values_error or "OK",
        "DiagComm_config.json": config_error or "OK",
        "doors_mapping.yaml":   _status(DOORS_MAPPING_PATH),
    }
    if cache_error:
        cache["__refresh_error"] = cache_error
    assets = {
        "DiagComm.txt": _status(ASSETS_DIR / "DiagComm.txt"),
        "DiagComm_schema.json": _status(ASSETS_DIR / "DiagComm_schema.json"),
        "doors_template.xlsx": _status(ASSETS_DIR / "doors_template.xlsx"),
        "inputs_template.xlsx": _status(ASSETS_DIR / "inputs_template.xlsx"),
        "doors_mapping_skeleton.yaml": _status(ASSETS_DIR / "doors_mapping_skeleton.yaml"),
    }
    outputs = {
        "FSCS.txt": _status(OUTPUTS_DIR / "FSCS.txt"),
        "diff_report.txt": _status(OUTPUTS_DIR / "diff_report.txt"),
        "validation_report.txt": _status(OUTPUTS_DIR / "validation_report.txt"),
    }

    unfilled = _fillness_check(values, schema)

    broken_assets = [name for name, status in assets.items() if status != "OK"]
    if broken_assets:
        next_step = (
            "Skill install incomplete -- assets missing: "
            + ", ".join(broken_assets)
            + ". Restore from git (`git checkout -- assets/`)."
        )
    elif not WORKSPACE_ROOT.exists():
        next_step = (
            f"No workspace at {_rel(WORKSPACE_ROOT)}. cd to your project root and run:\n"
            f"  python {SKILL_ROOT.as_posix()}/scripts/pipeline.py --init-project"
        )
    elif not XLSX_PATH.exists():
        next_step = (
            f"Recover the user template:\n"
            f"  python {SKILL_ROOT.as_posix()}/scripts/pipeline.py --init-project --force"
        )
    elif cache_error:
        next_step = (
            f"Cache regen failed: {cache_error}. "
            f"Run `python {SKILL_ROOT.as_posix()}/scripts/excel_loader.py dump` for diagnostics."
        )
    elif values_error == "missing" or config_error == "missing":
        next_step = (
            f"Run: python {SKILL_ROOT.as_posix()}/scripts/excel_loader.py dump "
            "(force-regenerate the cache from inputs/DiagComm.xlsx)"
        )
    elif unfilled:
        next_step = (
            f"Fill {len(unfilled)} required cell(s) on Sheet 'Project & Parameters' "
            "of inputs/DiagComm.xlsx (see 'unfilled' section above), then run: "
            f"python {SKILL_ROOT.as_posix()}/scripts/pipeline.py validate"
        )
    elif not dcom_roots:
        next_step = ("Fix paths.base_dir or paths.dcom_root on Sheet "
                     "'Paths & Options' of inputs/DiagComm.xlsx, then run status")
    else:
        next_step = f"Run: python {SKILL_ROOT.as_posix()}/scripts/pipeline.py status"

    return {
        "skill_root": SKILL_ROOT.as_posix(),
        "workspace_root": WORKSPACE_ROOT.as_posix(),
        "workspace_exists": WORKSPACE_ROOT.exists(),
        "base_dir": base_dir.as_posix(),
        "dcom_root_pattern": str(paths.get("dcom_root") or DEFAULT_PATHS["dcom_root"]),
        "dcom_roots": [p.as_posix() for p in dcom_roots],
        "project": {
            "name": project_name,
            "product_type": product_type,
            "CAN_Channel": can_channel,
        },
        "inputs": inputs,
        "cache": cache,
        "assets": assets,
        "outputs": outputs,
        "target_files": target_files,
        "unfilled": unfilled,
        "next_step": next_step,
    }


def print_text(ctx: dict[str, Any]) -> None:
    print("diagcomm-toolkit context")
    print("-" * 60)
    print(f"skill root        : {ctx['skill_root']}")
    workspace_tag = "" if ctx.get("workspace_exists") else "  (NOT INITIALIZED)"
    print(f"workspace root    : {ctx['workspace_root']}{workspace_tag}")
    print(f"base_dir          : {ctx['base_dir']}")
    print(f"dcom_root pattern : {ctx['dcom_root_pattern']}")
    roots = ctx["dcom_roots"]
    if roots:
        print(f"dcom roots        : {len(roots)}")
        for root in roots[:5]:
            print(f"  - {root}")
        if len(roots) > 5:
            print(f"  - ... {len(roots) - 5} more")
    else:
        print("dcom roots        : MISSING")

    project = ctx["project"]
    print(f"project           : {project['name']} / {project['product_type']} / CAN_Channel={project['CAN_Channel']}")

    print("\ninputs (user-edited; in inputs/)")
    for name, status in ctx["inputs"].items():
        print(f"  {name:<32} {status}")

    cache_block = ctx.get("cache") or {}
    if cache_block:
        print("\ncache (auto-generated from inputs/DiagComm.xlsx; in .cache/)")
        for name, status in cache_block.items():
            print(f"  {name:<32} {status}")

    print("\nassets (skill-bundled; in assets/)")
    for name, status in ctx["assets"].items():
        print(f"  {name:<32} {status}")

    print("\noutputs (regenerable)")
    for name, status in ctx["outputs"].items():
        print(f"  {name:<24} {status}")

    print("\ntarget ARXML files")
    for item in ctx["target_files"]:
        path = item["absolute_path"] or item["relative_path"]
        print(f"  {item['alias']:<22} {item['status']:<8} {path}")

    unfilled = ctx.get("unfilled") or []
    if unfilled:
        print(f"\nunfilled (inputs/DiagComm.xlsx, Sheet 'Project & Parameters' -- "
              f"{len(unfilled)} required cell(s))")
        for line in unfilled:
            print(f"  - {line}")

    print("\nagent next step")
    print(f"  {ctx['next_step']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print read-only DiagComm skill context.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    ctx = build_context()
    if args.json:
        print(json.dumps(ctx, indent=2, ensure_ascii=False))
    else:
        print_text(ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
