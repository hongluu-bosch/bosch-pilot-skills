"""One-shot migration: 1.19.x JSON+YAML inputs -> 1.20.0 Excel workbook.

This is a *user-facing* helper that runs once when an existing
diagcomm-toolkit user upgrades from <= 1.19.x. It reads any of the
three legacy input files that are still on disk:

    inputs/DiagComm_values.json   -> {project, parameters} (REQUIRED)
    inputs/DiagComm_config.json   -> {paths, options}      (optional)
    inputs/doors_mapping.yaml     -> {doors.document_uuid, mode, upload.dry_run}
                                       (optional; only the user-input
                                       fields are migrated, the static
                                       skeleton stays in assets/)

…and writes the equivalent values into ``inputs/DiagComm.xlsx`` --
the single editable input from 1.20.0 onward. The Excel workbook is
constructed by:

  1. opening the bundled blank template (``assets/inputs_template.xlsx``)
  2. walking every (Field, Value) row on Sheets 1 / 2 / 3
  3. setting the Value cell from the legacy data when a match exists
  4. writing the workbook back to ``inputs/DiagComm.xlsx``

After a successful migration the legacy JSON / YAML files are
**not** deleted automatically -- the script prints the exact ``rm``
commands and lets the user decide. This keeps the migration tool
side-effect-free outside the one .xlsx file it writes.

Usage (run from the project root, ``cd <project-root>`` first;
``<skill>`` = e.g. ``~/.cursor/skills/diagcomm-toolkit``)::

    python <skill>/scripts/migrate_v1_19_to_xlsx.py
    python <skill>/scripts/migrate_v1_19_to_xlsx.py --dry-run
    python <skill>/scripts/migrate_v1_19_to_xlsx.py --output inputs/DiagComm.xlsx

Exit codes:
    0 = migration written (or dry-run completed)
    1 = nothing to migrate (no legacy files on disk)
    2 = legacy files exist but cannot be read
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent
ASSETS_DIR = SKILL_ROOT / "assets"

# v2.0.0: workspace-aware. Legacy JSON / YAML inputs are searched in
# the workspace inputs/ folder by default (where someone may have
# hand-dropped them after a botched migration); --legacy-from overrides.
WORKSPACE_NAME = "DiagComm_Toolkit_PRJ"
DCOM_AI_DIRNAME = ".DCOM_AI"
WORKSPACE_ROOT = (Path.cwd() / DCOM_AI_DIRNAME / WORKSPACE_NAME).resolve()
INPUTS_DIR = WORKSPACE_ROOT / "inputs"

DEFAULT_LEGACY_DIR = INPUTS_DIR
DEFAULT_TEMPLATE = ASSETS_DIR / "inputs_template.xlsx"
DEFAULT_OUTPUT   = INPUTS_DIR / "DiagComm.xlsx"


# ---------------------------------------------------------------------------
# Legacy loaders

def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            "PyYAML missing. Install with: pip install pyyaml"
        ) from exc
    raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    return raw if isinstance(raw, dict) else None


def _strip_doc_keys(payload: Any) -> Any:
    """Drop ``_README`` / ``_HOW_TO_FILL`` etc. inline-doc keys."""
    if isinstance(payload, dict):
        return {k: _strip_doc_keys(v) for k, v in payload.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(payload, list):
        return [_strip_doc_keys(v) for v in payload]
    return payload


# ---------------------------------------------------------------------------
# Translate legacy dicts -> {dotted_field_path: value} mapping

def _flatten(prefix: str, data: dict[str, Any], out: dict[str, Any]) -> None:
    for key, val in data.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            _flatten(full, val, out)
        else:
            out[full] = val


def _build_field_map(values: dict[str, Any] | None,
                     config: dict[str, Any] | None,
                     doors:  dict[str, Any] | None) -> dict[str, Any]:
    """Return ``{field_path -> value}`` for every leaf the migration
    knows how to land in the Excel template.

    Only the fields that the build_inputs_template script emits are
    listed; legacy keys outside that surface (e.g. test-only
    ``$schema`` markers) are silently dropped.
    """
    out: dict[str, Any] = {}

    # Sheet 1 -- project + parameters
    if isinstance(values, dict):
        project = values.get("project") or {}
        if isinstance(project, dict):
            for k in ("name", "product_type"):
                if k in project and project[k] not in (None, ""):
                    out[f"project.{k}"] = project[k]
        parameters = values.get("parameters") or {}
        if isinstance(parameters, dict):
            tmp: dict[str, Any] = {}
            _flatten("parameters", parameters, tmp)
            out.update({k: v for k, v in tmp.items() if v is not None})

    # Sheet 2 -- paths + options
    if isinstance(config, dict):
        for top in ("paths", "options"):
            block = config.get(top) or {}
            if isinstance(block, dict):
                tmp = {}
                _flatten(top, block, tmp)
                out.update({k: v for k, v in tmp.items() if v is not None})

    # Sheet 3 -- DOORS Upload (only 3 user-input fields)
    if isinstance(doors, dict):
        d_doors = doors.get("doors") or {}
        if isinstance(d_doors, dict):
            uuid = d_doors.get("document_uuid")
            if isinstance(uuid, str) and uuid.strip():
                out["doors.document_uuid"] = uuid.strip()
        mode = doors.get("mode")
        if isinstance(mode, str) and mode.strip():
            out["mode"] = mode.strip()
        upload = doors.get("upload") or {}
        if isinstance(upload, dict) and "dry_run" in upload:
            out["upload.dry_run"] = "TRUE" if bool(upload["dry_run"]) else "FALSE"

    return out


# ---------------------------------------------------------------------------
# Excel writer

def _write_xlsx(template_path: Path, output_path: Path,
                field_map: dict[str, Any]) -> tuple[int, int]:
    """Open ``template_path``, set the Value cells named in ``field_map``,
    save to ``output_path``. Returns (matched, missing) counts.

    A "matched" entry means the dotted-path field was found in the
    template. "missing" entries are field names from the legacy file
    that have no corresponding row in the template -- usually fields
    introduced before 1.20.0 schema regen + dropped in the meantime,
    or test-only synthetic keys. We list them in the user-facing
    summary so the user knows what was discarded.
    """
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            "openpyxl missing. Install with: pip install openpyxl"
        ) from exc

    wb = openpyxl.load_workbook(template_path)

    matched: set[str] = set()
    for sheet_name in wb.sheetnames:
        if sheet_name == "README":
            continue
        ws = wb[sheet_name]
        for row in range(2, ws.max_row + 1):
            field = ws.cell(row=row, column=1).value
            if not isinstance(field, str):
                continue
            field = field.strip()
            if field in field_map:
                ws.cell(row=row, column=2).value = field_map[field]
                matched.add(field)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    wb.close()

    missing = sorted(set(field_map) - matched)
    return len(matched), len(missing)


# ---------------------------------------------------------------------------
# CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate 1.19.x JSON+YAML inputs into the v2 inputs/DiagComm.xlsx.",
    )
    parser.add_argument(
        "--legacy-from", type=Path, default=DEFAULT_LEGACY_DIR,
        help="Directory containing DiagComm_values.json + DiagComm_config.json + "
             f"doors_mapping.yaml (default: {DEFAULT_LEGACY_DIR}).",
    )
    parser.add_argument(
        "--values", type=Path, default=None,
        help="Override the legacy values JSON path (else <legacy-from>/DiagComm_values.json).",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="Override the legacy config JSON path (else <legacy-from>/DiagComm_config.json).",
    )
    parser.add_argument(
        "--doors-mapping", type=Path, default=None,
        help="Override the legacy DOORS YAML path (else <legacy-from>/doors_mapping.yaml).",
    )
    parser.add_argument(
        "--template", type=Path, default=DEFAULT_TEMPLATE,
        help=f"Blank xlsx baseline (default: {DEFAULT_TEMPLATE}).",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=DEFAULT_OUTPUT,
        help=f"Where to write the populated xlsx (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite --output even if it already exists.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse legacy files + print the field map; do not write the xlsx.",
    )
    args = parser.parse_args(argv)

    legacy_dir = args.legacy_from
    if args.values is None:
        args.values = legacy_dir / "DiagComm_values.json"
    if args.config is None:
        args.config = legacy_dir / "DiagComm_config.json"
    if args.doors_mapping is None:
        args.doors_mapping = legacy_dir / "doors_mapping.yaml"

    try:
        values = _strip_doc_keys(_load_json(args.values))
    except Exception as exc:  # noqa: BLE001
        print(f"[migrate] cannot read {args.values}: {exc}", file=sys.stderr)
        return 2
    try:
        config = _strip_doc_keys(_load_json(args.config))
    except Exception as exc:  # noqa: BLE001
        print(f"[migrate] cannot read {args.config}: {exc}", file=sys.stderr)
        return 2
    try:
        doors = _strip_doc_keys(_load_yaml(args.doors_mapping))
    except Exception as exc:  # noqa: BLE001
        print(f"[migrate] cannot read {args.doors_mapping}: {exc}", file=sys.stderr)
        return 2

    if not any([values, config, doors]):
        print("[migrate] nothing to do -- no legacy files found at:")
        print(f"  {args.values}")
        print(f"  {args.config}")
        print(f"  {args.doors_mapping}")
        return 1

    field_map = _build_field_map(values, config, doors)

    if not args.template.exists():
        print(f"[migrate] template not found: {args.template}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"[migrate] dry-run -- would write the following fields to {args.output}:")
        for k in sorted(field_map):
            print(f"  {k:<48} = {field_map[k]!r}")
        print(f"[migrate] {len(field_map)} field(s) total")
        return 0

    if args.output.exists() and not args.force:
        print(
            f"[migrate] refusing to overwrite existing {args.output}.\n"
            "          Pass --force to overwrite, OR back the file up first:\n"
            f"            mv {args.output} {args.output}.bak\n"
            f"          then re-run this command."
        )
        return 1

    matched, missing = _write_xlsx(args.template, args.output, field_map)

    print(f"[migrate] wrote {args.output}")
    print(f"          {matched} field(s) populated from the legacy files")
    if missing:
        print(f"          {missing} field(s) had no matching row in the "
              "Excel template (silently dropped).")

    print("\n[migrate] next steps:")
    print(f"  1. Open {args.output} and verify every Value cell.")
    print( "  2. Re-run `python <skill>/scripts/pipeline.py status` to confirm "
           "the toolkit picks up the new file.")
    print( "  3. Once happy, delete the legacy files:")
    for p in (args.values, args.config, args.doors_mapping):
        if p.exists():
            print(f"       rm {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
