"""Excel-driven user-input loader for diagcomm-toolkit (1.20.0+).

Background
----------
Up to 1.19.x users hand-edited three files under ``inputs/``:

    inputs/DiagComm_values.json    -- project + 21 calibration parameters
    inputs/DiagComm_config.json    -- paths + runtime flags
    inputs/doors_mapping.yaml      -- DOORS column mapping (mostly read-only)

Hand-editing JSON / YAML is brittle: typos in enum values, missing
required fields, nested-key drift. From 1.20.0 the user instead edits a
single Excel file with data-validation dropdowns:

    inputs/DiagComm.xlsx
      Sheet "Project & Parameters"  -- project identity + 21 parameters
      Sheet "Paths & Options"       -- paths + runtime flags (rare-edit)
      Sheet "DOORS Upload"          -- 3 fields: document_uuid, mode, dry_run

This module is the bridge between the Excel sheet and the rest of the
pipeline. It:

  1. Reads ``inputs/DiagComm.xlsx`` and parses the three data sheets.
  2. Coerces cell values into the right Python types (bool from
     "TRUE"/"FALSE", numbers from numeric cells, hex strings preserved).
  3. Merges the three Excel "DOORS" overrides with the bundled skeleton
     ``assets/doors_mapping_skeleton.yaml`` to reconstruct the complete
     DOORS mapping that 1.19.x stored in ``inputs/doors_mapping.yaml``.
  4. Writes three cache files under ``.cache/`` (gitignored) whose
     filenames + shapes are byte-identical to the 1.19.x ``inputs/``
     files. Every other script in the pipeline still reads these
     filenames -- they just live under ``.cache/`` now instead of
     ``inputs/`` (one constant per consumer; see runtime.VALUES_PATH).

  5. Validates the parsed dict against ``assets/DiagComm_schema.json``
     for required-field presence and enum membership; returns a list of
     human-readable errors that the pipeline surfaces verbatim.

Cache freshness is checked by mtime: if every ``.cache/*`` is newer
than both ``inputs/DiagComm.xlsx`` and
``assets/doors_mapping_skeleton.yaml``, the cache is reused. Otherwise
the loader regenerates all three cache files atomically (write-tmp +
replace) so partial failures cannot leave a half-cache behind.

CLI
---
Run from the project root (``cd <project-root>`` first); ``<skill>`` is
your installed skill path (e.g. ``~/.cursor/skills/diagcomm-toolkit``).

``python <skill>/scripts/excel_loader.py --check``
    Load Excel, run validation, exit 0 if clean / 2 with the error
    list if not. Does NOT regenerate the cache.

``python <skill>/scripts/excel_loader.py --dump``
    Force-regenerate the three cache files even if mtimes look fresh.

``python <skill>/scripts/excel_loader.py --show <dotted.path>``
    Resolve a single field (e.g. ``parameters.CAN_DLC.rx_dl``) and
    print its post-coercion value to stdout. Handy for debugging.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent
ASSETS_DIR = SKILL_ROOT / "assets"

# v2.0.0: workspace lives under <project>/.DCOM_AI/DiagComm_Toolkit_PRJ/
# (cwd-anchored at import time). Keep this in sync with runtime.py.
WORKSPACE_NAME = "DiagComm_Toolkit_PRJ"
DCOM_AI_DIRNAME = ".DCOM_AI"
WORKSPACE_ROOT = (Path.cwd() / DCOM_AI_DIRNAME / WORKSPACE_NAME).resolve()

INPUTS_DIR = WORKSPACE_ROOT / "inputs"
CACHE_DIR = WORKSPACE_ROOT / ".cache"

XLSX_PATH = INPUTS_DIR / "DiagComm.xlsx"
SKELETON_PATH = ASSETS_DIR / "doors_mapping_skeleton.yaml"
SCHEMA_PATH = ASSETS_DIR / "DiagComm_schema.json"
TEMPLATE_PATH = ASSETS_DIR / "inputs_template.xlsx"

# Cache filenames mirror the 1.19.x inputs/ filenames so every consumer
# in the pipeline only changes its directory constant, not its parser.
CACHE_VALUES = CACHE_DIR / "DiagComm_values.json"
CACHE_CONFIG = CACHE_DIR / "DiagComm_config.json"
CACHE_DOORS_MAPPING = CACHE_DIR / "doors_mapping.yaml"

# Sheet names in inputs/DiagComm.xlsx -- must match build_inputs_template.py.
SHEET_PROJECT_PARAMS = "Project & Parameters"
SHEET_PATHS_OPTIONS = "Paths & Options"
SHEET_DOORS = "DOORS Upload"

DATA_SHEETS = (SHEET_PROJECT_PARAMS, SHEET_PATHS_OPTIONS, SHEET_DOORS)

# Column convention (1-based): A = Field, B = Value, C = Notes.
COL_FIELD = 1
COL_VALUE = 2

# Section divider rows in the xlsx start with this prefix and have no value.
SECTION_PREFIX = "## "

# Strings that mean "the user has not filled this in yet" -- treated as None.
PLACEHOLDER_STRINGS = frozenset({
    "<fill-me>",
    "<set-me>",
    "<set-me-on-first-launch>",
    "<bootstrap>",
})


class LoaderError(RuntimeError):
    """Raised on unrecoverable load problems (file missing / unparseable).

    Caller (typically pipeline.py / preflight.py) catches and turns into a
    SystemExit with a friendly message that names the action the user
    should take.
    """


def _pretty(p: Path) -> str:
    """Best-effort relative path for user-facing error messages.

    v2.0.0: anchor on the current working directory (the user's project
    root) first, then fall back to the absolute string form. The skill
    no longer owns workspace paths, so anchoring on SKILL_ROOT would
    print a useless leading ``../../../...`` chain.
    """
    try:
        rel = p.resolve().relative_to(Path.cwd().resolve())
    except (ValueError, OSError):
        return str(p).replace("\\", "/")
    return rel.as_posix()


# ---------------------------------------------------------------------------
# Lazy heavy imports (openpyxl, yaml). Kept lazy so a stdlib-only caller
# (e.g. preflight.py probing for the file's mere existence) doesn't pay the
# import cost.

def _import_openpyxl():
    try:
        import openpyxl
    except ImportError as exc:  # noqa: BLE001
        raise LoaderError(
            "openpyxl is required to read inputs/DiagComm.xlsx. "
            "Install with:  pip install openpyxl"
        ) from exc
    return openpyxl


def _import_yaml():
    try:
        import yaml
    except ImportError as exc:  # noqa: BLE001
        raise LoaderError(
            "PyYAML is required to merge assets/doors_mapping_skeleton.yaml. "
            "Install with:  pip install pyyaml"
        ) from exc
    return yaml


# ---------------------------------------------------------------------------
# Type coercion

def _coerce_bool(raw: Any) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "yes", "1", "on"):
        return True
    if s in ("false", "no", "0", "off"):
        return False
    return None


def _coerce_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if raw.is_integer():
            return int(raw)
        return int(raw)  # truncate; out-of-range checked elsewhere
    s = str(raw).strip()
    if not s:
        return None
    try:
        if s.lower().startswith("0x"):
            return int(s, 16)
        return int(float(s))
    except (TypeError, ValueError):
        return None


def _coerce_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return float(int(raw))
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _coerce_hex_string(raw: Any) -> str | None:
    """Hex fields (CAN IDs, PaddingByte) are stored as ``0xNN`` strings.

    Accepts an int (Excel may auto-convert), a string with or without
    ``0x`` prefix, or even a float (Excel quirk). Returns the canonical
    upper-case ``0x..`` form.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return None
        return f"0x{n:0{max(2, len(f'{n:X}'))}X}"
    s = str(raw).strip()
    if not s:
        return None
    if s.lower().startswith("0x"):
        try:
            n = int(s, 16)
        except (TypeError, ValueError):
            return None
        # Preserve the user-typed width (e.g. "0x00" -> "0x00", not "0x0").
        width = max(2, len(s) - 2)
        return f"0x{n:0{width}X}"
    try:
        n = int(s)
    except (TypeError, ValueError):
        return None
    return f"0x{n:0{max(2, len(f'{n:X}'))}X}"


def _coerce_value(field_path: str, raw: Any, schema_spec: dict[str, Any] | None) -> Any:
    """Coerce ``raw`` (whatever openpyxl returned) into the schema-correct
    Python type for ``field_path``.

    Falls back to returning ``raw`` unchanged when no schema entry covers
    the field -- this is the case for ``project.name``,
    ``paths.*``, ``options.*``, ``doors.document_uuid``, ``mode``, and
    ``upload.dry_run`` which are not in DiagComm_schema.json.

    Special-case rules outside the schema:
      - ``options.*`` and ``upload.dry_run`` are coerced to bool.
      - ``paths.*`` are stripped strings.
      - ``mode`` is a stripped string.
      - ``project.name`` and ``doors.document_uuid`` are stripped strings,
        with placeholder strings normalised to ``None`` so the
        downstream "is unfilled" check trips.
    """
    if raw is None:
        return None

    # ---- schema-driven coercion (parameters.* and project.product_type) ----
    if schema_spec:
        kind = schema_spec.get("type")
        if kind == "bool":
            return _coerce_bool(raw)
        if kind == "int":
            return _coerce_int(raw)
        if kind == "float":
            return _coerce_float(raw)
        if kind == "hex":
            return _coerce_hex_string(raw)
        if kind == "enum":
            s = str(raw).strip() if not isinstance(raw, str) else raw.strip()
            if not s:
                return None
            # Normalise numeric enum values back to their schema type
            allowed = schema_spec.get("allowed") or []
            for opt in allowed:
                if str(opt) == s:
                    return opt  # preserves int 8 / 64 vs. string "11bit"
            return s  # validation will catch
        # type == "object" handled by the recursive walker, never lands here.
        # type == "string" or unset: fall through to generic stripping.

    # ---- non-schema generic rules ----
    if field_path.startswith("options.") or field_path == "upload.dry_run":
        return _coerce_bool(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s in PLACEHOLDER_STRINGS:
            return None
        return s
    return raw


# ---------------------------------------------------------------------------
# Schema lookup helpers

def _schema_spec_for(field_path: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Return the schema entry for a dotted ``field_path`` like
    ``parameters.CAN_DLC.rx_dl``, or ``None`` if outside the schema.
    """
    fields = (schema or {}).get("fields") or {}
    if field_path == "project.product_type":
        return fields.get("product_type")
    if field_path.startswith("parameters."):
        rest = field_path[len("parameters.") :].split(".")
        cur = fields
        spec: dict[str, Any] | None = None
        for part in rest:
            if not isinstance(cur, dict):
                return None
            spec = cur.get(part) if part in cur else None
            if spec is None:
                return None
            if isinstance(spec, dict) and spec.get("type") == "object":
                cur = spec.get("fields") or {}
            else:
                cur = {}
        return spec
    return None


# ---------------------------------------------------------------------------
# Nested dict helpers

def _set_nested(target: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = target
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _get_nested(source: Any, dotted: str) -> Any:
    cur = source
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


# ---------------------------------------------------------------------------
# Main load path

def _iter_data_rows(ws) -> list[tuple[int, str, Any]]:
    """Yield ``(row_index, field, raw_value)`` for every non-section,
    non-empty Field row in ``ws``. Stops at the first all-empty row to
    keep parsing forgiving of trailing blanks.
    """
    out: list[tuple[int, str, Any]] = []
    blank_streak = 0
    for row_idx in range(2, ws.max_row + 1):  # row 1 is the header
        field_cell = ws.cell(row=row_idx, column=COL_FIELD).value
        value_cell = ws.cell(row=row_idx, column=COL_VALUE).value
        if field_cell is None and value_cell is None:
            blank_streak += 1
            if blank_streak >= 5:
                break  # no more data
            continue
        blank_streak = 0
        if field_cell is None:
            continue
        s = str(field_cell).strip()
        if not s or s.startswith(SECTION_PREFIX):
            continue
        out.append((row_idx, s, value_cell))
    return out


def load_xlsx(xlsx_path: Path = XLSX_PATH,
              schema_path: Path = SCHEMA_PATH) -> dict[str, Any]:
    """Read ``xlsx_path``, return the merged in-memory dict that mirrors
    the 1.19.x v2 unified shape::

        {
          "$schema":   "diagcomm-toolkit/v2",
          "project":   {"name": ..., "product_type": ...},
          "paths":     {...},
          "options":   {...},
          "parameters": {... 21 parameters incl. nested CAN_DLC ...},
          "_doors_overrides": {     # excel-only; merged into yaml later
            "doors":  {"document_uuid": ...},
            "mode":   "...",
            "upload": {"dry_run": ...},
          }
        }

    Raises ``LoaderError`` if the file is missing, the workbook lacks a
    required sheet, or openpyxl cannot open it.
    """
    if not xlsx_path.exists():
        raise LoaderError(
            f"inputs Excel not found: {_pretty(xlsx_path)}.\n"
            "Recover the blank template with:\n"
            f"    cp {_pretty(TEMPLATE_PATH)} {_pretty(xlsx_path)}"
        )

    openpyxl = _import_openpyxl()
    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(
            f"Cannot open {_pretty(xlsx_path)}: {exc}\n"
            "If the file is corrupt, recover the blank template:\n"
            f"    cp {_pretty(TEMPLATE_PATH)} {_pretty(xlsx_path)}"
        ) from exc

    missing = [name for name in DATA_SHEETS if name not in wb.sheetnames]
    if missing:
        raise LoaderError(
            f"{_pretty(xlsx_path)} is missing required sheet(s): "
            f"{missing}. Got sheets: {wb.sheetnames}. "
            f"Re-copy the blank template from {_pretty(TEMPLATE_PATH)}."
        )

    schema: dict[str, Any] = {}
    if schema_path.exists():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            schema = {}

    merged: dict[str, Any] = {"$schema": "diagcomm-toolkit/v2"}

    # Sheet 1 -- project + parameters
    for _row, field, raw in _iter_data_rows(wb[SHEET_PROJECT_PARAMS]):
        spec = _schema_spec_for(field, schema)
        value = _coerce_value(field, raw, spec)
        _set_nested(merged, field, value)

    # Sheet 2 -- paths + options
    for _row, field, raw in _iter_data_rows(wb[SHEET_PATHS_OPTIONS]):
        value = _coerce_value(field, raw, None)
        _set_nested(merged, field, value)

    # Sheet 3 -- DOORS upload (lifted to a side block; merged with skeleton later)
    doors_overrides: dict[str, Any] = {}
    for _row, field, raw in _iter_data_rows(wb[SHEET_DOORS]):
        value = _coerce_value(field, raw, None)
        _set_nested(doors_overrides, field, value)
    merged["_doors_overrides"] = doors_overrides

    wb.close()
    return merged


# ---------------------------------------------------------------------------
# Validation

def validate(merged: dict[str, Any], schema_path: Path = SCHEMA_PATH) -> list[str]:
    """Return a list of human-readable validation errors.

    Empty list = ready to use. Each line is structured so the pipeline's
    fillness report can prefix it with sheet/row context.

    Checks:
      - project.name non-empty
      - project.product_type in schema.fields.product_type.allowed
      - every prompt_required parameters.* leaf is non-None
      - enum-typed parameters.* values are in the schema's allowed set
      - numeric-typed values within min/max when both present
    """
    errors: list[str] = []
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        schema = {"fields": {}}
    fields = schema.get("fields") or {}

    project = (merged.get("project") or {})
    if not project.get("name"):
        errors.append(
            "project.name is empty -- fill the 'Value' cell on Sheet "
            "'Project & Parameters'."
        )

    pt_spec = fields.get("product_type") or {}
    pt = project.get("product_type")
    if not pt:
        allowed = pt_spec.get("allowed") or []
        errors.append(
            "project.product_type is empty -- pick from "
            f"{allowed} on Sheet 'Project & Parameters'."
        )
    elif pt_spec.get("allowed") and pt not in pt_spec["allowed"]:
        errors.append(
            f"project.product_type = {pt!r} is not one of "
            f"{pt_spec['allowed']}."
        )

    parameters = merged.get("parameters") or {}

    def _walk(parent_path: str, sub_schema: dict[str, Any], sub_values: Any) -> None:
        for key, spec in sub_schema.items():
            if not isinstance(spec, dict):
                continue
            if not parent_path and key == "product_type":
                continue
            full = f"parameters.{key}" if not parent_path else f"{parent_path}.{key}"
            if spec.get("type") == "object":
                child = sub_values.get(key) if isinstance(sub_values, dict) else None
                _walk(full, spec.get("fields") or {}, child or {})
                continue
            value = sub_values.get(key) if isinstance(sub_values, dict) else None

            if spec.get("prompt_required") and value is None:
                allowed = spec.get("allowed")
                hint = ""
                if isinstance(allowed, list) and allowed:
                    hint = f" (allowed: {' / '.join(map(str, allowed))})"
                errors.append(
                    f"{full} is empty -- REQUIRED field"
                    f"{hint}. Fill the 'Value' cell on Sheet "
                    f"'Project & Parameters'."
                )
                continue

            if value is None:
                continue  # optional field left blank -- pipeline uses default

            allowed = spec.get("allowed")
            if isinstance(allowed, list) and allowed and value not in allowed:
                errors.append(
                    f"{full} = {value!r} is not one of {allowed}."
                )
            mn = spec.get("min")
            mx = spec.get("max")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if mn is not None and value < mn:
                    errors.append(f"{full} = {value} below min ({mn}).")
                if mx is not None and value > mx:
                    errors.append(f"{full} = {value} above max ({mx}).")

    _walk("", fields, parameters)
    return errors


# ---------------------------------------------------------------------------
# Skeleton merge

def merge_doors_skeleton(merged: dict[str, Any],
                         skeleton_path: Path = SKELETON_PATH) -> dict[str, Any]:
    """Merge ``merged["_doors_overrides"]`` into the bundled mapping
    skeleton and return the full DOORS mapping dict that
    build_doors_payload.py / doors_sync.py expect.
    """
    if not skeleton_path.exists():
        raise LoaderError(
            f"DOORS mapping skeleton missing: {_pretty(skeleton_path)}. "
            "Re-pull the skill from git."
        )
    yaml_mod = _import_yaml()
    skeleton = yaml_mod.safe_load(skeleton_path.read_text(encoding="utf-8")) or {}
    if not isinstance(skeleton, dict):
        raise LoaderError(
            f"{_pretty(skeleton_path)} did not parse to a "
            f"mapping (got {type(skeleton).__name__})."
        )

    out = deepcopy(skeleton)
    overrides = merged.get("_doors_overrides") or {}

    # doors.document_uuid -> out["doors"]["document_uuid"]
    doors_block = out.setdefault("doors", {})
    overrides_doors = overrides.get("doors") or {}
    if overrides_doors.get("document_uuid"):
        doors_block["document_uuid"] = overrides_doors["document_uuid"]

    # mode (top-level)
    mode = overrides.get("mode")
    if mode:
        out["mode"] = mode
    else:
        out.setdefault("mode", "insert")

    # upload.dry_run
    upload_block = out.get("upload")
    if not isinstance(upload_block, dict):
        upload_block = {}
    out["upload"] = upload_block
    upload_overrides = overrides.get("upload") or {}
    if "dry_run" in upload_overrides:
        upload_block["dry_run"] = bool(upload_overrides["dry_run"])
    else:
        upload_block.setdefault("dry_run", False)

    return out


# ---------------------------------------------------------------------------
# Cache writer

def _atomic_write(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _split_for_cache(merged: dict[str, Any]
                     ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split the unified dict into the two on-disk halves that the
    1.19.x ``inputs/`` shape used::

        DiagComm_values.json -> {$schema, project, parameters}
        DiagComm_config.json -> {$schema, paths, options}

    Mirroring the legacy split keeps every downstream consumer (which
    already knows how to read these two files) working with no parser
    change -- only the directory constant flips from ``inputs/`` to
    ``.cache/``.
    """
    schema_tag = merged.get("$schema") or "diagcomm-toolkit/v2"
    values_part: dict[str, Any] = {
        "$schema": schema_tag,
        "project": deepcopy(merged.get("project") or {}),
        "parameters": deepcopy(merged.get("parameters") or {}),
    }
    config_part: dict[str, Any] = {
        "$schema": schema_tag,
        "paths": deepcopy(merged.get("paths") or {}),
        "options": deepcopy(merged.get("options") or {}),
    }
    return values_part, config_part


def dump_cache(merged: dict[str, Any],
               *,
               cache_dir: Path = CACHE_DIR,
               skeleton_path: Path = SKELETON_PATH) -> dict[str, Path]:
    """Write the three legacy-shaped cache files atomically and return
    their paths keyed by short name.
    """
    values_part, config_part = _split_for_cache(merged)
    full_doors = merge_doors_skeleton(merged, skeleton_path=skeleton_path)

    cache_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        cache_dir / "DiagComm_values.json",
        json.dumps(values_part, indent=2, ensure_ascii=False) + "\n",
    )
    _atomic_write(
        cache_dir / "DiagComm_config.json",
        json.dumps(config_part, indent=2, ensure_ascii=False) + "\n",
    )

    yaml_mod = _import_yaml()
    yaml_text = yaml_mod.safe_dump(
        full_doors, sort_keys=False, allow_unicode=True
    )
    _atomic_write(
        cache_dir / "doors_mapping.yaml",
        "# Auto-generated by scripts/excel_loader.py from\n"
        "#   inputs/DiagComm.xlsx (DOORS Upload sheet)\n"
        "#   assets/doors_mapping_skeleton.yaml\n"
        "# Do NOT edit by hand. Regenerated on every pipeline run that\n"
        "# needs DOORS metadata.\n"
        + yaml_text,
    )

    return {
        "values": cache_dir / "DiagComm_values.json",
        "config": cache_dir / "DiagComm_config.json",
        "doors_mapping": cache_dir / "doors_mapping.yaml",
    }


# ---------------------------------------------------------------------------
# Cache freshness

def is_cache_fresh(*,
                   xlsx_path: Path = XLSX_PATH,
                   skeleton_path: Path = SKELETON_PATH,
                   cache_dir: Path = CACHE_DIR) -> bool:
    """Return True iff every cache file exists and is at least as new as
    BOTH ``xlsx_path`` and ``skeleton_path``. mtime comparison only --
    we do not hash file contents.
    """
    cache_files = (
        cache_dir / "DiagComm_values.json",
        cache_dir / "DiagComm_config.json",
        cache_dir / "doors_mapping.yaml",
    )
    if not all(p.exists() for p in cache_files):
        return False
    if not xlsx_path.exists():
        return True  # cache is the only available source; trust it
    sources_mtime = xlsx_path.stat().st_mtime
    if skeleton_path.exists():
        sources_mtime = max(sources_mtime, skeleton_path.stat().st_mtime)
    cache_mtime = min(p.stat().st_mtime for p in cache_files)
    return cache_mtime + 1e-3 >= sources_mtime


def load_or_refresh(*,
                    xlsx_path: Path = XLSX_PATH,
                    skeleton_path: Path = SKELETON_PATH,
                    cache_dir: Path = CACHE_DIR,
                    force: bool = False) -> dict[str, Any]:
    """Single-call entry used by runtime.load_user_inputs():

    1. If ``force`` or the cache is stale, load the Excel, dump the
       three cache files atomically.
    2. Return the parsed unified dict (always re-loaded from Excel when
       refreshed; otherwise reconstructed from the cache so callers
       always get the same shape).
    """
    if force or not is_cache_fresh(
        xlsx_path=xlsx_path,
        skeleton_path=skeleton_path,
        cache_dir=cache_dir,
    ):
        merged = load_xlsx(xlsx_path)
        dump_cache(merged, cache_dir=cache_dir, skeleton_path=skeleton_path)
        return merged

    # Cache is fresh: reconstruct the unified dict from the cache files
    # so callers see the same shape with or without a refresh.
    values = json.loads(
        (cache_dir / "DiagComm_values.json").read_text(encoding="utf-8")
    )
    config = json.loads(
        (cache_dir / "DiagComm_config.json").read_text(encoding="utf-8")
    )
    yaml_mod = _import_yaml()
    full_doors = yaml_mod.safe_load(
        (cache_dir / "doors_mapping.yaml").read_text(encoding="utf-8")
    ) or {}
    merged = {
        "$schema": values.get("$schema", "diagcomm-toolkit/v2"),
        "project": values.get("project") or {},
        "paths":   config.get("paths") or {},
        "options": config.get("options") or {},
        "parameters": values.get("parameters") or {},
        "_doors_overrides": {
            "doors":  {"document_uuid": (full_doors.get("doors") or {}).get("document_uuid")},
            "mode":   full_doors.get("mode"),
            "upload": {"dry_run": (full_doors.get("upload") or {}).get("dry_run", False)},
        },
    }
    return merged


# ---------------------------------------------------------------------------
# CLI

def _cmd_check(args: argparse.Namespace) -> int:
    try:
        merged = load_xlsx(Path(args.xlsx))
    except LoaderError as e:
        print(f"[excel_loader] ERROR: {e}", file=sys.stderr)
        return 2
    errors = validate(merged)
    if errors:
        print(f"[excel_loader] {len(errors)} validation error(s):")
        for line in errors:
            print(f"  - {line}")
        return 2
    print(f"[excel_loader] OK -- inputs/DiagComm.xlsx parses cleanly.")
    return 0


def _cmd_dump(args: argparse.Namespace) -> int:
    try:
        merged = load_or_refresh(xlsx_path=Path(args.xlsx), force=True)
    except LoaderError as e:
        print(f"[excel_loader] ERROR: {e}", file=sys.stderr)
        return 2
    print(f"[excel_loader] cache regenerated under {_pretty(CACHE_DIR)}/")
    for name, path in (("values", CACHE_VALUES),
                       ("config", CACHE_CONFIG),
                       ("doors",  CACHE_DOORS_MAPPING)):
        print(f"  - {name:<7}{_pretty(path)}")
    errors = validate(merged)
    if errors:
        print(f"[excel_loader] but validation flagged {len(errors)} issue(s):")
        for line in errors:
            print(f"  - {line}")
        return 2
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        merged = load_or_refresh(xlsx_path=Path(args.xlsx))
    except LoaderError as e:
        print(f"[excel_loader] ERROR: {e}", file=sys.stderr)
        return 2
    if not args.field:
        print(json.dumps(
            {k: v for k, v in merged.items() if not k.startswith("_")},
            indent=2, ensure_ascii=False,
        ))
        return 0
    value = _get_nested(merged, args.field)
    if value is None:
        # Try the doors overrides namespace as a fallback
        value = _get_nested(merged.get("_doors_overrides") or {}, args.field)
    print(repr(value))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Excel-driven user-input loader for diagcomm-toolkit.",
    )
    parser.add_argument(
        "--xlsx", default=str(XLSX_PATH),
        help=f"Path to the user Excel. Default: {_pretty(XLSX_PATH)}",
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_check = sub.add_parser("check", help="parse + validate; do not write cache")
    p_check.set_defaults(func=_cmd_check)

    p_dump = sub.add_parser("dump", help="force-regenerate the .cache/ files")
    p_dump.set_defaults(func=_cmd_dump)

    p_show = sub.add_parser("show", help="print one resolved field (debug)")
    p_show.add_argument("field", nargs="?", default=None,
                        help="dotted path, e.g. parameters.CAN_DLC.rx_dl")
    p_show.set_defaults(func=_cmd_show)

    # Backward-compat shorthand: `--check`, `--dump`, `--show <field>`.
    parser.add_argument("--check", dest="legacy_check", action="store_true")
    parser.add_argument("--dump",  dest="legacy_dump",  action="store_true")
    parser.add_argument("--show",  dest="legacy_show",  default=None,
                        help="dotted field path to print")

    args = parser.parse_args(argv)

    if getattr(args, "legacy_check", False):
        return _cmd_check(args)
    if getattr(args, "legacy_dump", False):
        return _cmd_dump(args)
    if getattr(args, "legacy_show", None) is not None:
        args.field = args.legacy_show
        return _cmd_show(args)

    if not getattr(args, "func", None):
        # No subcommand -- default to "dump" (refresh cache, validate, print summary)
        return _cmd_dump(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
