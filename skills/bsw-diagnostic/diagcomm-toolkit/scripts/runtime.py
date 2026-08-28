"""Shared runtime infrastructure for the diagcomm-toolkit pipeline.

This module is the low-level "plumbing" layer. Everything here is
command-agnostic: loading JSON, resolving paths (including fuzzy
``dcom_root`` glob resolution), counting fields, freshness compare,
planning which arxml node each mapping entry should rewrite, and a
handful of small helpers reused across commands. Nothing here depends
on argparse.

Split rationale:
  pipeline.py       -- argparse wiring + ``cmd_*`` dispatchers (thin)
  runtime.py  (this)-- paths, transforms, planning
  semantic.py       -- cross-field / range validation
  reports.py        -- FSCS / landing-report / catalog / schema-drift

``pipeline.py`` imports from all three; those three don't import
``pipeline``.

Rollback note: the skill does not keep local backups. Every target
project lives in source control (git / SVN / Jazz / ...); reverting a
bad apply is the project's own ``git checkout -- <arxml>`` or
equivalent. Keeping backup logic here would duplicate that safety net
and pollute ``outputs/`` with project bytes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import _log


class _RuntimeLog:
    """Tiny adapter that lets call sites keep the
    ``log.warning("fmt %s", arg)`` style while delegating to the
    framework-free ``_log.warn`` / ``_log.err`` / ``_log.info``
    helpers. ``_log`` doesn't expose a ``get(name)`` factory, so this
    one-instance shim takes its place without dragging in stdlib
    logging.
    """
    def info(self, msg: str, *args: Any) -> None:    _log.info(msg, *args)
    def warning(self, msg: str, *args: Any) -> None: _log.warn(msg, *args)
    def error(self, msg: str, *args: Any) -> None:   _log.err(msg, *args)


log = _RuntimeLog()

# ---------------------------------------------------------------------------
# Unicode-safe stdout setup (must run before any print calls)
#
# Force stdout/stderr to UTF-8 when possible so unicode characters in
# diffs / tables (e.g. ``\u2713`` ✓, ``\u2208`` ∈) don't crash on
# Windows consoles whose default codepage is cp1252. No-op on older
# pythons; harmless when the stream is already UTF-8.

for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if callable(_reconfigure):
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _safe_print(text: str) -> None:
    """Print ``text`` to stdout, replacing characters the current encoding
    cannot represent (instead of raising ``UnicodeEncodeError``).

    Covers the rare case where ``sys.stdout.reconfigure`` is unavailable
    (older pythons, non-standard stream wrappers) and the text contains
    non-cp1252 glyphs such as ``\u2713``.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", "ascii") or "ascii"
        sys.stdout.write(text.encode(enc, errors="replace").decode(enc))
        sys.stdout.write("\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Module search path + skill-tree constants

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Sibling modules (schema / mapping / arxml_patcher) are imported
# lazily where needed to keep this module's import cost cheap.
from mapping import (  # noqa: E402
    PARAM_MAP,
    TRANSFORMS,
    expand_path,
    get_nested,
)

# ---------------------------------------------------------------------------
# Two-root layout (v2.0.0)
#
# v1.x kept *everything* (skill code AND the user's project data) under
# a single SKILL_ROOT, which forced the user to clone the skill into
# every project. v2 splits the two roles:
#
#   SKILL_ROOT (immutable, bundled)
#     .../diagcomm-toolkit/        # this checkout, normally
#                                  # ~/.cursor/skills/diagcomm-toolkit/
#       scripts/                   # this file
#       assets/                    # template xlsx + doors skeleton + schema
#       reference/                 # docs
#       tests/                     # pytest suite
#
#   WORKSPACE_ROOT (per-project, mutable)
#     <project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/
#       inputs/DiagComm.xlsx       # the only thing the user hand-edits
#       .cache/                    # auto-derived from the xlsx (gitignored)
#       outputs/                   # generation reports / payload xlsx
#       state/doors_upload_state.json
#
# WORKSPACE_ROOT is derived from cwd at import time -- callers ``cd``
# into their project root and invoke
# ``python <skill>/scripts/pipeline.py ...``. This mirrors how
# ``did-toolkit`` works.
SKILL_ROOT = SCRIPTS_DIR.parent
ASSETS_DIR = SKILL_ROOT / "assets"

WORKSPACE_NAME = "DiagComm_Toolkit_PRJ"
DCOM_AI_DIRNAME = ".DCOM_AI"
WORKSPACE_ROOT = (Path.cwd() / DCOM_AI_DIRNAME / WORKSPACE_NAME).resolve()

INPUTS_DIR = WORKSPACE_ROOT / "inputs"
OUTPUTS_DIR = WORKSPACE_ROOT / "outputs"
STATE_DIR = WORKSPACE_ROOT / "state"
CACHE_DIR = WORKSPACE_ROOT / ".cache"

# DiagComm_schema.json lives under ``assets/`` because it is regenerated
# from ``assets/DiagComm.txt`` (via ``pipeline.py gen-schema``) and is
# never edited by the user. Skill-bundled, immutable.
SCHEMA_PATH = ASSETS_DIR / "DiagComm_schema.json"

# Skill-bundled templates copied / merged into the workspace at init.
TEMPLATE_PATH = ASSETS_DIR / "inputs_template.xlsx"
DOORS_SKELETON_PATH = ASSETS_DIR / "doors_mapping_skeleton.yaml"

# The single user-editable file -- lives in the project workspace.
XLSX_PATH = INPUTS_DIR / "DiagComm.xlsx"

# Cache files derived from the xlsx by ``scripts/excel_loader.py``. Same
# JSON shape as the <= 1.19.x ``inputs/`` files so no consumer parser
# had to change between v1.19 and v2.0.
VALUES_PATH = CACHE_DIR / "DiagComm_values.json"
CONFIG_PATH = CACHE_DIR / "DiagComm_config.json"
DOORS_MAPPING_PATH = CACHE_DIR / "doors_mapping.yaml"

# Filename component used by ``load_unified_pair`` and the doors_sync /
# build_doors_payload merge helpers when a caller passes a custom
# values path -- the sibling config file is expected to live next to
# it under this name.
CONFIG_FILENAME = "DiagComm_config.json"

# Legacy artefacts. Surfaced through ``_check_legacy_layout`` so users
# upgrading from a previous version see a concrete migration path
# instead of cryptic KeyErrors. v2 detects two flavours:
#
#  * 1.20.x layout: the xlsx + cache live INSIDE the skill checkout
#    (``<skill>/inputs/DiagComm.xlsx``). Surfaced because v2 expects
#    them under ``<workspace>/inputs/`` instead.
#  * 1.19.x layout: hand-edited JSON / YAML under ``<skill>/inputs/``.
#    Same files, older shape.
_LEGACY_SKILL_INPUTS_DIR  = SKILL_ROOT / "inputs"
_LEGACY_SKILL_XLSX        = _LEGACY_SKILL_INPUTS_DIR / "DiagComm.xlsx"
_LEGACY_SKILL_VALUES      = _LEGACY_SKILL_INPUTS_DIR / "DiagComm_values.json"
_LEGACY_SKILL_CONFIG      = _LEGACY_SKILL_INPUTS_DIR / "DiagComm_config.json"
_LEGACY_SKILL_DOORS       = _LEGACY_SKILL_INPUTS_DIR / "doors_mapping.yaml"

# Workspace-internal legacy: someone hand-dropped pre-1.20 JSON / YAML
# into the new workspace inputs/ folder (e.g. by following stale docs).
_LEGACY_INPUTS_VALUES = INPUTS_DIR / "DiagComm_values.json"
_LEGACY_INPUTS_CONFIG = INPUTS_DIR / "DiagComm_config.json"
_LEGACY_INPUTS_DOORS  = INPUTS_DIR / "doors_mapping.yaml"

# Pre-1.5.0 standalone config dir (still inside the skill).
_LEGACY_CONFIG_PATH = SKILL_ROOT / "config" / "project.json"

# Default `paths` and `options` populated into the blank Excel template
# by ``scripts/build_inputs_template.py``. v2 changed ``base_dir`` from
# ``"../../.."`` (relative to v1 SKILL_ROOT three levels deep in the
# project tree) to ``"../.."`` (relative to v2 WORKSPACE_ROOT, which is
# always exactly two levels deep at ``<project>/.DCOM_AI/<workspace>/``).
# These defaults are read at template-build time only -- once the user
# fills the Excel they own the values.
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

DEFAULT_OPTIONS: dict[str, Any] = {
    "dry_run_default": True,
    "validate_before_apply": True,
}


# ---------------------------------------------------------------------------
# JSON / path helpers


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pretty_path(p: Path) -> str:
    """Best-effort short path for user-facing messages: prefer relative
    to cwd, fall back to absolute. Used in legacy / init error text."""
    try:
        return p.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except (ValueError, OSError):
        return str(p).replace("\\", "/")


def _check_legacy_layout() -> None:
    """Fail loudly when an obsolete on-disk layout is detected so the
    user sees a concrete migration path instead of cryptic KeyErrors.

    Flavours, oldest first:

    * pre-1.5.0       : ``config/project.json`` still on disk.
    * 1.5.0 .. 1.19.x : hand-edited JSON / YAML under
      ``<skill>/inputs/``.
    * 1.20.0 .. 1.20.x: ``inputs/DiagComm.xlsx`` lives INSIDE the skill
      checkout (the workspace was the skill itself). v2 moved the
      workspace out to ``<project>/.DCOM_AI/DiagComm_Toolkit_PRJ/``.

    We never auto-migrate -- silent config rewrites are how data gets
    lost. The user runs ``python <skill>/scripts/migrate_v1_20_to_v2.py``
    for a one-shot conversion to v2 layout.
    """
    if _LEGACY_CONFIG_PATH.exists():
        raise SystemExit(
            "\n[diagcomm-toolkit] Pre-1.5.0 file detected: "
            f"{_pretty_path(_LEGACY_CONFIG_PATH)}\n"
            "Since v2.0.0, the only user-editable input file is an "
            "Excel workbook:\n"
            f"  {_pretty_path(XLSX_PATH)}\n"
            "Run `--init-project` then fill in your values:\n"
            f"  python {_pretty_path(SCRIPTS_DIR / 'pipeline.py')} --init-project\n"
        )

    skill_legacy = [p for p in (_LEGACY_SKILL_XLSX,
                                _LEGACY_SKILL_VALUES,
                                _LEGACY_SKILL_CONFIG,
                                _LEGACY_SKILL_DOORS) if p.exists()]
    if skill_legacy:
        names = "\n".join(f"  {_pretty_path(p)}" for p in skill_legacy)
        raise SystemExit(
            "\n[diagcomm-toolkit] Old in-skill workspace detected (<= 1.20.x):\n"
            f"{names}\n\n"
            "Since v2.0.0, the workspace lives in your project:\n"
            f"  {_pretty_path(WORKSPACE_ROOT)}\n\n"
            "One-shot migration (cd to your project root first):\n"
            f"  cd <project-root>\n"
            f"  python {_pretty_path(SCRIPTS_DIR / 'migrate_v1_20_to_v2.py')} "
            f"--from-skill {_pretty_path(SKILL_ROOT)}\n\n"
            "This moves inputs/, outputs/, state/, .cache/ from the skill "
            "checkout into the new workspace, then prints the cleanup steps.\n"
        )

    workspace_legacy = [p for p in (_LEGACY_INPUTS_VALUES,
                                    _LEGACY_INPUTS_CONFIG,
                                    _LEGACY_INPUTS_DOORS) if p.exists()]
    if workspace_legacy:
        names = "\n".join(f"  {_pretty_path(p)}" for p in workspace_legacy)
        raise SystemExit(
            "\n[diagcomm-toolkit] Pre-1.20 JSON / YAML inputs found in workspace:\n"
            f"{names}\n\n"
            "Since v1.20, all user input lives in a single Excel "
            "workbook with data-validation dropdowns:\n"
            f"  {_pretty_path(XLSX_PATH)}\n\n"
            "One-shot migration:\n"
            f"  python {_pretty_path(SCRIPTS_DIR / 'migrate_v1_19_to_xlsx.py')}\n\n"
            "This reads the legacy files, writes the equivalent values "
            "into the Excel workbook, and tells you which files to "
            "delete afterwards.\n"
        )


def _check_workspace_initialized() -> None:
    """Refuse to proceed if the workspace doesn't exist yet.

    This is the v2 equivalent of the old "missing inputs/ folder"
    check: callers either ``cd`` to a project where ``--init-project``
    has been run, or run ``--init-project`` themselves.
    """
    if WORKSPACE_ROOT.exists() and INPUTS_DIR.exists():
        return
    raise SystemExit(
        "\n[diagcomm-toolkit] No workspace found at:\n"
        f"  {WORKSPACE_ROOT}\n\n"
        "v2.0.0 keeps every user-editable file (inputs, outputs, state, "
        ".cache) under <project>/.DCOM_AI/DiagComm_Toolkit_PRJ/. Scaffold one:\n\n"
        f"  cd <project-root>\n"
        f"  python {_pretty_path(SCRIPTS_DIR / 'pipeline.py')} --init-project\n\n"
        "Then open `inputs/DiagComm.xlsx`, fill the required cells, and re-run.\n"
    )


def _migrate_v1_to_v2_in_memory(unified: dict[str, Any]) -> dict[str, Any]:
    """Convert a v1-shaped dict to v2 IN MEMORY ONLY. Used as a safety
    net so fixtures and external callers that bypass
    `_check_legacy_layout` don't crash; the loud error from
    `_check_legacy_layout` should still be the primary failure path
    for the on-disk default file.

    v1: {project_name, paths, options, values: {... product_type ...}}
    v2: {project: {name, product_type}, paths, options, parameters: {...}}

    Note: v2 keeps ``paths`` and ``options`` in the merged in-memory
    dict because that's the contract every downstream call site
    (split_unified, _inject_runtime_options, …) speaks. The on-disk
    *split* (paths/options in DiagComm_config.json) is a property of
    the file layout, not the merged dict.
    """
    if not isinstance(unified, dict):
        return unified
    if isinstance(unified.get("project"), dict) and isinstance(unified.get("parameters"), dict):
        return unified  # already v2

    values = dict(unified.get("values") or {})
    product_type = values.pop("product_type", None)
    return {
        "$schema": "diagcomm-toolkit/v2",
        "project": {
            "name": unified.get("project_name"),
            "product_type": product_type,
        },
        "paths": dict(unified.get("paths") or {}),
        "options": dict(unified.get("options") or {}),
        "parameters": values,
    }


def split_unified(unified: dict[str, Any]
                  ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a v2 unified dict into ``(config_view, parameters)``.

    Schema v2 (1.13.0+)::

        {
          "$schema":   "diagcomm-toolkit/v2",
          "project":   {"name": "...", "product_type": "..."},
          "paths":     {...},
          "options":   {...},
          "parameters": {... CAN_Channel + the 20 DiagComm fields ...}
        }

    ``config_view`` is the legacy-shaped dict that
    ``resolve_file_alias`` / ``resolve_dcom_root`` already know how to
    consume::

        {
          "project": {"name": "...", "product_type": "..."},
          "paths":   {...},
          "options": {...},
        }

    ``parameters`` is the unique per-upload parameter set: ``CAN_Channel``
    (a parameter, not a path-only selector despite reading like one),
    plus the 20 DiagComm fields (timing, addressing, frame, dcm).

    Centralising the split here means every command goes through one
    function -- no caller has to remember the new layout. v1 inputs
    (top-level ``project_name`` + ``values``) are auto-migrated in
    memory as a safety net, but `_check_legacy_layout` should normally
    fail first with a louder error.
    """
    unified = _migrate_v1_to_v2_in_memory(unified)
    project_block = unified.get("project") or {}
    config_view: dict[str, Any] = {
        "project": {
            "name":         project_block.get("name"),
            "product_type": project_block.get("product_type"),
        },
        "paths":   dict(unified.get("paths") or {}),
        "options": dict(unified.get("options") or {}),
    }
    parameters = dict(unified.get("parameters") or {})
    return config_view, parameters


def merge_values_with_config(values_dict: dict[str, Any],
                             config_dict: dict[str, Any] | None
                             ) -> dict[str, Any]:
    """Combine the ``project`` + ``parameters`` half (from
    ``DiagComm_values.json``) with the ``paths`` + ``options`` half
    (from ``DiagComm_config.json``) into the single in-memory shape
    that ``split_unified`` and every downstream call site already
    speak.

    The merge is **shallow and non-destructive**: keys in
    ``values_dict`` win when both files name the same top-level key
    (so a fixture / test that inlines a ``paths`` block can still
    override the sibling config file).

    ``config_dict`` may be ``None`` (sibling file missing); the merged
    result then has empty ``paths`` / ``options`` and the caller will
    fail loudly at first use, which is the correct behaviour for an
    incomplete inputs/ folder.
    """
    merged: dict[str, Any] = dict(values_dict or {})
    if config_dict:
        for key in ("paths", "options"):
            if key in config_dict and key not in merged:
                merged[key] = config_dict[key]
    return merged


def _read_config_for(values_path: Path) -> dict[str, Any] | None:
    """Read the sibling ``DiagComm_config.json`` next to ``values_path``.
    Returns ``None`` if the sibling does not exist; a parse error
    raises so the caller (and the user) sees the real problem.
    """
    sibling = values_path.parent / CONFIG_FILENAME
    if not sibling.exists():
        return None
    return strip_doc_keys(load_json(sibling))


def strip_doc_keys(payload: Any) -> Any:
    """Drop any top-level / nested key that starts with ``_``.

    Used to let the bundled ``inputs/`` templates carry inline ``_README``
    blocks (a poor-man's JSON comment) without contaminating the
    structured loader downstream. Non-dict / non-list inputs pass
    through unchanged.
    """
    if isinstance(payload, dict):
        return {k: strip_doc_keys(v) for k, v in payload.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(payload, list):
        return [strip_doc_keys(v) for v in payload]
    return payload


def _ensure_cache_fresh() -> None:
    """Refresh ``.cache/{DiagComm_values.json, DiagComm_config.json,
    doors_mapping.yaml}`` from ``inputs/DiagComm.xlsx`` +
    ``assets/doors_mapping_skeleton.yaml`` whenever the Excel or
    skeleton has been touched since the cache was last written.

    Cache writing is delegated to ``scripts/excel_loader``; this
    function is only the "ensure" side of the contract. Callers that
    need the parsed dict directly should use ``load_user_inputs()``
    instead, which wraps both this freshness check and the read.
    """
    try:
        import excel_loader  # noqa: PLC0415  -- lazy: heavy openpyxl import
    except ImportError as exc:
        raise SystemExit(
            f"\n[diagcomm-toolkit] cannot import scripts/excel_loader.py: {exc}.\n"
            "The skill clone is incomplete; restore via "
            "`git checkout -- scripts/excel_loader.py`.\n"
        ) from exc

    try:
        excel_loader.load_or_refresh(
            xlsx_path=XLSX_PATH,
            skeleton_path=DOORS_SKELETON_PATH,
            cache_dir=CACHE_DIR,
        )
    except excel_loader.LoaderError as exc:
        raise SystemExit(
            f"\n[diagcomm-toolkit] cannot read {_pretty_path(XLSX_PATH)}:\n"
            f"  {exc}\n"
        ) from exc


def load_user_inputs() -> dict[str, Any]:
    """Single entry point for "give me the user's project + parameters
    + paths + options dict, refreshing from Excel first if needed".

    Equivalent to ``load_unified`` (which now delegates here), kept as
    a separate name so call sites that want the explicit
    "Excel-aware" semantics read clearly.
    """
    _check_legacy_layout()
    _check_workspace_initialized()
    _ensure_cache_fresh()
    values = strip_doc_keys(load_json(VALUES_PATH))
    config = _read_config_for(VALUES_PATH)
    return merge_values_with_config(values, config)


def load_unified() -> dict[str, Any]:
    """Load the v2 user-input dict (project + paths + options +
    parameters). Backwards-compatible name for
    :func:`load_user_inputs`; consumers in <= 1.19.x called this.
    """
    return load_user_inputs()


def load_diagcomm() -> tuple[dict[str, Any], dict[str, Any]]:
    """Convenience: load + split in one call. Returns
    ``(config_view, parameters)`` as documented on ``split_unified``.
    """
    return split_unified(load_unified())


def resolve_base_dir(config: dict[str, Any]) -> Path:
    """Resolve ``paths.base_dir`` against the workspace root.

    v2.0.0 changed the relative-path anchor from SKILL_ROOT to
    WORKSPACE_ROOT (the per-project ``.DCOM_AI/DiagComm_Toolkit_PRJ/``
    directory). The new default ``"../.."`` therefore lands on the
    project root -- one level up from ``.DCOM_AI/`` and two from the
    workspace itself.

    Absolute paths are honoured verbatim.
    """
    base = config["paths"]["base_dir"]
    if Path(base).is_absolute():
        return Path(base)
    return (WORKSPACE_ROOT / base).resolve()


_DCOM_ROOT_CACHE: dict[tuple[str, str], Path] = {}
_GLOB_MAGIC = set("*?[")

# Sub-directories that, if present, strongly suggest a path is a real dcom
# root (and not some unrelated directory that happens to match the glob).
# Used as a health filter when multiple dirs match the wildcard pattern.
DCOM_HEALTH_MARKERS: tuple[str, ...] = ("RBAPLCust", "Cubas")


def _has_glob_magic(pattern: str) -> bool:
    return any(ch in _GLOB_MAGIC for ch in pattern)


def _is_healthy_dcom(path: Path) -> bool:
    return any((path / m).is_dir() for m in DCOM_HEALTH_MARKERS)


def resolve_dcom_root(config: dict[str, Any]) -> Path:
    """Resolve ``paths.dcom_root`` under ``base_dir``.

    Supports glob-style wildcards (``*`` / ``?`` / ``[...]``) so the same
    config template works across projects/platforms where one or more
    hierarchy segment names differ (e.g. ``<platformA>/rb/as/<bswA>/core/...``
    vs ``<platformB>/rb/as/<bswB>/core/...``). The *structural depth* still
    has to match; only segment names are fuzzy.

    Resolution rules:
      - No wildcard       -> literal join, no filesystem check.
      - Wildcard present  -> ``base_dir.glob(pattern)``; must resolve to
        an existing directory. Candidates are further filtered by a
        health check that requires at least one of DCOM_HEALTH_MARKERS
        (e.g. ``RBAPLCust`` / ``Cubas``) to exist as a sub-directory.
        When the filter removes every candidate it is treated as a soft
        signal and the raw glob matches are kept (with a warning) so
        non-standard layouts still work. When more than one healthy
        candidate survives, the first is used and a warning lists the
        others.
    """
    base = resolve_base_dir(config)
    pattern = config["paths"]["dcom_root"]
    cache_key = (str(base), pattern)
    cached = _DCOM_ROOT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if not _has_glob_magic(pattern):
        resolved = base / pattern
        _DCOM_ROOT_CACHE[cache_key] = resolved
        return resolved

    raw = sorted(p for p in base.glob(pattern) if p.is_dir())
    if not raw:
        raise FileNotFoundError(
            f"dcom_root pattern {pattern!r} matched no directory under {base}. "
            f"Check paths.base_dir in inputs/DiagComm.xlsx::Paths & Options, or "
            f"adjust the wildcards in paths.dcom_root."
        )

    healthy = [p for p in raw if _is_healthy_dcom(p)]
    if healthy:
        matches = healthy
    else:
        sample = ", ".join(str(p.relative_to(base)) for p in raw[:3])
        log.warning(
            "dcom_root pattern %r matched %d directory(ies) under %s but "
            "none contain any of %s; falling back to first raw match. "
            "Samples: %s",
            pattern, len(raw), base, DCOM_HEALTH_MARKERS, sample,
        )
        matches = raw

    if len(matches) > 1:
        others = ", ".join(str(m.relative_to(base)) for m in matches[1:])
        log.warning(
            "dcom_root pattern %r matched %d directories under %s; using "
            "%s (also matched: %s). To pin, make paths.dcom_root more "
            "specific in inputs/DiagComm.xlsx::Paths & Options.",
            pattern, len(matches), base, matches[0].relative_to(base), others,
        )
    _DCOM_ROOT_CACHE[cache_key] = matches[0]
    return matches[0]


def resolve_file_alias(config: dict[str, Any], alias: str) -> Path:
    paths = config["paths"]
    if alias not in paths:
        raise KeyError(
            f"Unknown path alias '{alias}' in inputs/DiagComm.xlsx::Paths & Options::paths.*")
    template = paths[alias]
    product_type = config["project"]["product_type"]
    can_channel = int(config["options"].get("can_channel", 0))
    relative = expand_path(template, product_type, can_channel)
    return resolve_dcom_root(config) / relative


# ---------------------------------------------------------------------------
# Status / freshness helpers
#
# ``cmd_status`` is the "is this skill ready to run?" dashboard: it
# aggregates the existence / freshness of every file the other commands
# depend on. The individual checks below are small pure helpers so they
# stay cheap and reusable (e.g. a future pre-flight gate in ``cmd_apply``).


def _referenced_file_aliases() -> list[str]:
    """Every distinct ``file`` alias referenced by the PARAM_MAP."""
    return sorted({entry["file"] for entry in PARAM_MAP})


def _count_leaf_values(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    total = 0
    for v in data.values():
        if isinstance(v, dict):
            total += _count_leaf_values(v)
        else:
            total += 1
    return total


def _count_schema_fields(schema: dict[str, Any]) -> tuple[int, int]:
    """Return (top-level field count, leaf field count)."""
    top = 0
    leaf = 0
    for spec in schema.get("fields", {}).values():
        top += 1
        if spec.get("type") == "object":
            leaf += len(spec.get("fields") or {})
        else:
            leaf += 1
    return top, leaf


def _newest_mtime(paths: list[Path]) -> float | None:
    stamps = [p.stat().st_mtime for p in paths if p.exists()]
    return max(stamps) if stamps else None


def _freshness(out_path: Path, newer_than: float | None) -> str:
    """Compare ``out_path``'s mtime to the newest input mtime.

    Returns ``MISSING``, ``STALE`` (older than some input) or ``FRESH``.
    ``newer_than=None`` short-circuits to ``FRESH`` when the file exists.
    """
    if not out_path.exists():
        return "MISSING"
    if newer_than is None:
        return "FRESH"
    return "FRESH" if out_path.stat().st_mtime + 1e-3 >= newer_than else "STALE"


def _rel_to_cwd(path: Path) -> str:
    """Pretty path: relative to the current working directory (which is
    normally the project root the user ``cd`` into before invoking the
    skill), with forward slashes so Windows and POSIX renders look
    identical.

    Workspace paths land as ``.DCOM_AI/DiagComm_Toolkit_PRJ/...``,
    project-tree paths as ``<platform>/rb/as/<bsw>/...``, skill paths as
    a leading ``../...`` chain. Falls back to the absolute path when a
    relative form cannot be constructed (cross-drive on Windows).
    """
    import os
    try:
        target = path.resolve()
    except OSError:
        target = path
    try:
        rel = os.path.relpath(target, Path.cwd().resolve())
    except ValueError:
        return str(path).replace("\\", "/")
    return rel.replace("\\", "/")


# Back-compat alias -- renamed to ``_rel_to_cwd`` in v2.0.0 because
# v2 anchors workspace / project-tree paths against the user's cwd
# (the project root) rather than the skill checkout. Removing the
# alias would break the published reports / context dump consumers.
_rel_to_skill = _rel_to_cwd


# ---------------------------------------------------------------------------
# Runtime option injection + derived-value synthesis


def _inject_runtime_options(config: dict[str, Any],
                            parameters: dict[str, Any]) -> None:
    """Copy the path-selector fields needed by path templates into
    ``config.options``.

    Schema v2 split:

    * ``project.product_type``  -> already in ``config.project.product_type``
      via ``split_unified``; nothing to do here.
    * ``parameters.CAN_Channel`` -> ``config.options.can_channel``.

    Path templates like
    ``RBAPLCust/cfg/{product_type}/Can{can_channel}_CusDiag_EcucValues_{product_type}.arxml``
    are resolved via those two config slots (see ``resolve_file_alias``);
    this function is the bridge between the user's
    ``inputs/DiagComm.xlsx::Project & Parameters`` answers and the
    path-resolution layer. Missing / ill-typed CAN_Channel silently falls through (no
    write) so callers with a partially-seeded parameters dict still
    run: the caller either sees a config default or a ``KeyError``
    from ``resolve_file_alias`` -- a natural loud failure.
    """
    if not isinstance(parameters, dict):
        return

    raw_ch = parameters.get("CAN_Channel")
    if raw_ch is not None:
        try:
            ch = int(raw_ch)
        except (TypeError, ValueError):
            pass
        else:
            config.setdefault("options", {})["can_channel"] = ch


def _is_canfd_label(v: Any) -> bool:
    """True when a frame_type literal denotes CAN-FD."""
    return str(v or "").strip().lower().replace(" ", "").replace("-", "") \
        in {"canfd", "fd"}


def _inject_derived_values(values: dict[str, Any]) -> None:
    """Populate synthetic fields that are computed from user inputs.

    Currently handles ``CAN_DLC.flexible_fd`` -- the global
    ``CanTpFlexibleDataRateSupport`` boolean. It is ``True`` iff either
    ``CAN_DLC.rx_frame_type`` or ``CAN_DLC.tx_frame_type`` is ``CANFD``.
    The derived PARAM_MAP entry (flagged ``derived=True``) then picks up
    this value through the regular ``bool_str`` transform and writes it
    to the CanTp feature file.

    No-op when ``CAN_DLC`` is missing or both frame_type fields are
    absent (legacy / partial values files just skip the FD write).
    """
    if not isinstance(values, dict):
        return
    can_dlc = values.get("CAN_DLC")
    if not isinstance(can_dlc, dict):
        return
    rx = can_dlc.get("rx_frame_type")
    tx = can_dlc.get("tx_frame_type")
    if rx is None and tx is None:
        return
    can_dlc["flexible_fd"] = (
        _is_canfd_label(rx) or _is_canfd_label(tx)
    )


# ---------------------------------------------------------------------------
# Mapping execution (transform + plan)


def _apply_transform(entry: dict[str, Any], raw_value: Any) -> str:
    transform_name = entry.get("transform", "identity")
    fn = TRANSFORMS.get(transform_name)
    if fn is None:
        raise ValueError(f"Unknown transform '{transform_name}' for {entry['param']}")
    return fn(raw_value)


def _plan_entries(config: dict[str, Any], values: dict[str, Any]) -> tuple[
        dict[Path, list[tuple[dict[str, Any], str]]], list[str]]:
    """Group mapping entries by resolved file path, return (plan, warnings)."""
    plan: dict[Path, list[tuple[dict[str, Any], str]]] = {}
    warnings: list[str] = []

    for entry in PARAM_MAP:
        raw_value = get_nested(values, entry["param"])
        if raw_value is None:
            # Derived entries (internal synthetic keys) are only missing
            # when their source inputs are absent -- silent skip, not a
            # user-visible warning, because the key is not part of the
            # values contract.
            if not entry.get("derived"):
                warnings.append(
                    f"{entry['param']}: not present in values file -> skipped")
            continue
        try:
            new_value = _apply_transform(entry, raw_value)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{entry['param']}: transform error {exc}")
            continue

        file_path = resolve_file_alias(config, entry["file"])
        plan.setdefault(file_path, []).append((entry, new_value))

    return plan, warnings
