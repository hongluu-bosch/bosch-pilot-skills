"""diagcomm-toolkit main pipeline (CLI dispatch layer).

"DiagComm" = diagnostic communication (CAN + CAN-TP + Dcm layers) for
the CusDiag stack. "CANTP" is only the transport-layer subset and is
not used as a top-level name anymore.

Sub-commands:
  status           readiness dashboard (exit 0/1/2 = READY/DEGRADED/BROKEN)
  gen-schema       assets/DiagComm.txt -> assets/DiagComm_schema.json (+ --check)
  export-catalog   scripts/mapping.yaml -> reference/landing_spots.md (+ --check)
  landing-report   live per-project locator inventory -> outputs/landing_report.txt
  reseed           write outputs/reseed_suggestion.json from live arxml (--from-arxml)
  validate         sanity-check inputs/DiagComm.xlsx against schema + files
  apply            rewrite the CusDiag arxml files (surgical, byte-level)
  fscs             regenerate outputs/FSCS.txt (one-page final snapshot)

Rollback is delegated to the project's source control (git / SVN /
Jazz). The skill never copies ARXML into ``outputs/``.

Input pipeline (since 1.20.0): the user edits a single Excel
workbook ``inputs/DiagComm.xlsx``; ``scripts/excel_loader.py``
materialises it into the legacy JSON / YAML cache files under
``.cache/`` whose shape every consumer (status / validate / apply /
fscs / doors_sync / build_doors_payload) already knows how to read.
Cache regeneration is automatic on every command run -- the user
never invokes the loader manually.

Ownership contract: ``inputs/DiagComm.xlsx`` is the USER'S canvas;
no command ever overwrites it. ``.cache/`` is derived state and
gets regenerated from Excel any time Excel's mtime is newer.
``reseed --from-arxml`` writes a *suggestion* file under
``outputs/`` for review; the user transcribes interesting values
back into Excel by hand.

This module is the **only agent-facing entry point** for the skill.
Agents orchestrate the end-to-end flow (status â†’ validate â†’ dry-run
â†’ apply) by calling these sub-commands and branching on exit codes;
see ``SKILL.md`` for the prescribed playbook.

See ``runtime.py`` / ``semantic.py`` / ``reports.py`` for the split
infrastructure / validation / reporting layers; this module stays
focused on argparse wiring and ``cmd_*`` dispatch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import schema as schema_mod
from mapping import (
    CAN_PT_FILE,
    CANTP_COMMON,
    CANTP_FEATURE_FILE,
    DCM_COMMON,
    DCM_FEATURE_FILE,
    DCM_SERVICES_COMMON,
    PARAM_MAP,
    REVERSE_TRANSFORMS,
)
from reports import (
    CATALOG_TARGET,
    _ancestor_short_name_chain,
    _build_schema_drift,
    _inject_catalog,
    _read_current_value,
    _render_catalog_table,
    _write_fscs,
)

# Importing runtime first pulls in the UTF-8 stdout reconfigure + adds
# scripts/ to sys.path so sibling modules resolve regardless of how this
# script is invoked.
from runtime import (
    ASSETS_DIR,
    CACHE_DIR,
    CONFIG_FILENAME,
    CONFIG_PATH,
    DCOM_AI_DIRNAME,
    DEFAULT_OPTIONS,
    DEFAULT_PATHS,
    INPUTS_DIR,
    OUTPUTS_DIR,
    SCHEMA_PATH,
    SKILL_ROOT,
    STATE_DIR,
    TEMPLATE_PATH,
    VALUES_PATH,
    WORKSPACE_NAME,
    WORKSPACE_ROOT,
    XLSX_PATH,
    _check_legacy_layout,
    _count_leaf_values,
    _count_schema_fields,
    _freshness,
    _inject_derived_values,
    _inject_runtime_options,
    _migrate_v1_to_v2_in_memory,
    _newest_mtime,
    _plan_entries,
    _pretty_path,
    _read_config_for,
    _referenced_file_aliases,
    _rel_to_skill,
    _safe_print,
    load_json,
    load_unified,
    merge_values_with_config,
    resolve_dcom_root,
    resolve_file_alias,
    split_unified,
    strip_doc_keys,
)
from semantic import _semantic_checks

# ---------------------------------------------------------------------------
# status


def cmd_status(args: argparse.Namespace) -> int:
    """Readiness dashboard. Exit codes:
        0 = READY (everything green)
        1 = DEGRADED (non-fatal: stale snapshot, missing optional output)
        2 = BROKEN  (fatal: can't run apply -- missing config/schema/arxml)
    """
    lines: list[str] = ["[status]"]
    broken = False
    degraded = False

    lines.append(f"  skill root       : {str(SKILL_ROOT).replace(chr(92), '/')}")
    ws_tag = "" if WORKSPACE_ROOT.exists() else "  (NOT INITIALIZED)"
    lines.append(
        f"  workspace root   : {str(WORKSPACE_ROOT).replace(chr(92), '/')}{ws_tag}")

    # --- deps ---
    #
    # lxml is only imported lazily (inside validate / apply / fscs /
    # landing-report / reseed paths), so a cold environment without lxml
    # would otherwise look "READY" here and then explode at the first
    # real command. Probe with ``find_spec`` (no import side effects)
    # so this check itself cannot raise SystemExit from arxml_patcher.
    # PyYAML is covered by mapping.py's import-time guard -- if missing,
    # ``pipeline.py`` never reaches this function -- but we still list
    # it here for symmetry on the happy path.
    import importlib.util
    missing_deps: list[str] = []
    for pip_name, import_name in (("lxml", "lxml"), ("PyYAML", "yaml")):
        if importlib.util.find_spec(import_name) is None:
            missing_deps.append(pip_name)
    if missing_deps:
        joined = ", ".join(missing_deps)
        req = (SKILL_ROOT / "scripts" / "requirements.txt").as_posix()
        lines.append(
            f"  deps             : BROKEN   missing: {joined}. "
            f"Run: python -m pip install -r {req}")
        broken = True
    else:
        import lxml  # noqa: F401
        import yaml  # noqa: F401
        lxml_ver = getattr(lxml, "__version__", "?")
        yaml_ver = getattr(yaml, "__version__", "?")
        lines.append(
            f"  deps             : OK       lxml {lxml_ver} / PyYAML {yaml_ver}")

    # --- legacy layout guard ---
    #
    # Pre-1.5.0 shipped a separate ``config/project.json``. From 1.5.0
    # onwards every user knob lives in inputs/DiagComm_values.json. If
    # the legacy file is still on disk surface a clear migration error
    # before we touch anything else, so the user can't accidentally
    # run ``apply`` against half-migrated state.
    try:
        _check_legacy_layout()
    except SystemExit as exc:
        lines.append("  layout           : BROKEN   pre-1.5.0 config detected")
        for raw in str(exc).strip().splitlines():
            lines.append(f"                         {raw}")
        lines.append(f"OVERALL: BROKEN")
        print("\n".join(lines))
        return 2

    # --- schema ---
    schema: dict[str, Any] | None = None
    if SCHEMA_PATH.exists():
        try:
            schema = load_json(SCHEMA_PATH)
            top, leaf = _count_schema_fields(schema)
            # Drift check: is the committed schema still in sync with
            # DiagComm.txt? A silent mismatch would confuse the agent
            # (schema default says X, DiagComm.txt says Y) so flag it.
            try:
                in_sync, _ = _build_schema_drift(schema_mod.DEFAULT_TXT, SCHEMA_PATH)
            except Exception:
                in_sync = True  # don't fail status on drift-check errors
            if in_sync:
                lines.append(
                    f"  schema           : OK       assets/DiagComm_schema.json "
                    f"({top} top / {leaf} leaf fields)")
            else:
                lines.append(
                    "  schema           : DRIFT    assets/DiagComm_schema.json "
                    "differs from assets/DiagComm.txt; run `pipeline.py gen-schema`")
                degraded = True
        except Exception as exc:
            lines.append(f"  schema           : BROKEN   parse error: {exc}")
            broken = True
    else:
        lines.append("  schema           : MISSING  run `pipeline.py gen-schema`")
        degraded = True

    # --- unified values file ---
    #
    # Since 1.5.0 the unified ``inputs/DiagComm_values.json`` is the
    # ONLY user-editable file: project_name + paths + options + values
    # all live under one root. Lazy-seed: when missing, build a full
    # skeleton (DEFAULT_PATHS + DEFAULT_OPTIONS + reverse-walked values)
    # and write it. The user reviews and edits before the next run.
    unified: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    values: dict[str, Any] | None = None
    values_just_seeded = False

    if not XLSX_PATH.exists():
        lines.append(
            f"  inputs           : MISSING  {_pretty_path(XLSX_PATH)}\n"
            f"                         restore via --init-project (or copy "
            f"the template manually):\n"
            f"                         python {SKILL_ROOT.as_posix()}/scripts/pipeline.py --init-project --force"
        )
        broken = True

    if XLSX_PATH.exists():
        try:
            unified = load_unified()  # also refreshes .cache/ from Excel
            config, values = split_unified(unified)
            n = _count_leaf_values(values)
            unfilled = _check_template_fillness(config, values, schema)
            if unfilled:
                lines.append(
                    f"  inputs           : NEEDS-FILL inputs/DiagComm.xlsx "
                    f"({len(unfilled)} required field(s) not filled; "
                    f"{n} leaf entries total)")
                for line in unfilled:
                    lines.append(f"                         - {line}")
                degraded = True
            else:
                lines.append(f"  inputs           : OK       inputs/DiagComm.xlsx "
                             f"({n} leaf entries; cache at .cache/)")
            project_name = config["project"].get("name") or "<unset>"
            lines.append(f"  project          : {project_name}")
            _inject_runtime_options(config, values)
        except SystemExit as exc:
            lines.append(f"  inputs           : BROKEN   {exc}")
            broken = True
        except Exception as exc:
            lines.append(f"  inputs           : BROKEN   parse error: {exc}")
            broken = True

    # --- dcom_root ---
    dcom: Path | None = None
    if config is not None:
        try:
            dcom = resolve_dcom_root(config)
            lines.append(f"  dcom_root        : OK       {_rel_to_skill(dcom)}")
        except Exception as exc:
            lines.append(f"  dcom_root        : BROKEN   {exc}")
            broken = True

    # --- arxml files ---
    arxml_paths: list[Path] = []
    if config is not None and dcom is not None:
        aliases = _referenced_file_aliases()
        present: list[str] = []
        missing: list[tuple[str, str]] = []
        for a in aliases:
            try:
                p = resolve_file_alias(config, a)
                arxml_paths.append(p)
                if p.exists():
                    present.append(a)
                else:
                    missing.append((a, _rel_to_skill(p)))
            except Exception as exc:
                missing.append((a, f"RESOLVE-ERROR: {exc}"))
        total = len(aliases)
        if not missing:
            lines.append(f"  arxml files      : OK       {len(present)}/{total} present")
        else:
            lines.append(f"  arxml files      : DEGRADED {len(present)}/{total} present")
            for alias, where in missing:
                lines.append(f"                         - MISSING {alias}: {where}")
            degraded = True

    # --- snapshot freshness ---
    newest_input = _newest_mtime(
        arxml_paths + ([VALUES_PATH] if VALUES_PATH.exists() else []))
    for name, path, soft in (
        ("landing_report",   OUTPUTS_DIR / "landing_report.txt",    True),
        ("FSCS",             OUTPUTS_DIR / "FSCS.txt",              True),
    ):
        state = _freshness(path, newest_input)
        lines.append(f"  {name:<16} : {state:<8} {_rel_to_skill(path)}")
        if state == "STALE" and soft:
            degraded = True

    if broken:
        status = "BROKEN"
        rc = 2
    elif degraded:
        status = "DEGRADED"
        rc = 1
    else:
        status = "READY"
        rc = 0
    lines.append(f"OVERALL: {status}")
    print("\n".join(lines))
    return rc


# ---------------------------------------------------------------------------
# gen-schema / export-catalog


def cmd_gen_schema(args: argparse.Namespace) -> int:
    txt = args.input or schema_mod.DEFAULT_TXT
    out = args.output or schema_mod.DEFAULT_SCHEMA

    if getattr(args, "check", False):
        in_sync, diff = _build_schema_drift(txt, out)
        if in_sync:
            print(f"[gen-schema --check] {out.name} is in sync with {txt.name}")
            return 0
        print(f"[gen-schema --check] DRIFT: {out.name} differs from "
              f"what {txt.name} would regenerate.\n"
              f"Run `pipeline.py gen-schema` to refresh.\n")
        _safe_print(diff)
        return 1

    path = schema_mod.generate(txt_path=txt, out_path=out)
    print(f"[gen-schema] wrote {path}")
    return 0


def cmd_export_catalog(args: argparse.Namespace) -> int:
    target = args.output or CATALOG_TARGET
    if not target.exists():
        print(f"[export-catalog] target not found: {_rel_to_skill(target)}")
        return 2
    block = _render_catalog_table(PARAM_MAP)
    existing = target.read_text(encoding="utf-8")
    new_text, had_fences = _inject_catalog(existing, block)

    if getattr(args, "check", False):
        if new_text == existing:
            print(f"[export-catalog --check] {target.name} "
                  f"is in sync with mapping.yaml")
            return 0
        import difflib
        diff = "".join(difflib.unified_diff(
            existing.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{target.name} (on disk)",
            tofile=f"{target.name} (regenerated from mapping.yaml)",
            n=3,
        ))
        print(f"[export-catalog --check] DRIFT: {target.name} differs "
              f"from what mapping.yaml would produce.\n"
              f"Run `pipeline.py export-catalog` to refresh.\n")
        _safe_print(diff)
        return 1

    if new_text == existing:
        print(f"[export-catalog] no changes needed ({target.name} already in sync)")
        return 0
    # newline="\n": target is reference/landing_spots.md which lives in the
    # repo. Letting Python's default translation mangle LF -> CRLF on
    # Windows would churn the file on every export-catalog run with a
    # pointless CRLF/LF flip.
    target.write_text(new_text, encoding="utf-8", newline="\n")
    action = "updated" if had_fences else "appended (fences were missing)"
    print(f"[export-catalog] {action}: {_rel_to_skill(target)} "
          f"({len(PARAM_MAP)} entries)")
    return 0


# ---------------------------------------------------------------------------
# validate / apply / fscs


def cmd_validate(args: argparse.Namespace) -> int:
    # Lazy-seed gate: an explicit --input bypasses the default values
    # path (CI pointing at a test fixture, for example), but the common
    # case falls through to _ensure_values_or_seed so the user's very
    # first `validate` run auto-creates DiagComm_values.json.
    if not args.input:
        unified, rc = _ensure_values_or_seed("validate")
        if rc != 0:
            return rc
    else:
        if not args.input.exists():
            print(f"[validate] --input file not found: {args.input}")
            return 1
        unified = _read_input_file(args.input)
    config, values = split_unified(unified)
    _inject_runtime_options(config, values)
    schema = load_json(SCHEMA_PATH) if SCHEMA_PATH.exists() else None

    # Fillness gate: refuse to validate a still-untouched template.
    # Runs BEFORE _inject_derived_values so derived defaults do not
    # mask user-required fields.
    unfilled = _check_template_fillness(config, values, schema)
    if unfilled:
        _print_fillness_report(unfilled, command="validate")
        return 2

    _inject_derived_values(values)

    errors: list[str] = []
    warnings: list[str] = []

    # Semantic / cross-field checks (CAN ID range vs format, STmin cap,
    # PaddingByte range). These run before locator checks because an
    # invalid ID or out-of-range byte should be flagged even if the
    # arxml files are missing.
    sem_errors, sem_warnings = _semantic_checks(values)
    errors.extend(sem_errors)
    warnings.extend(sem_warnings)

    if schema:
        # v2 input split: `product_type` is project identity and lives
        # in config["project"], not in `parameters`. Allow it to live
        # in either block so the warning doesn't fire on a perfectly
        # valid v2 file.
        project_block = config.get("project") or {}
        identity_keys = {"product_type"}
        for key in schema["fields"]:
            if schema["fields"][key].get("type") == "object":
                continue
            if key in values:
                continue
            if key in identity_keys and key in project_block and project_block[key]:
                continue
            warnings.append(f"missing field in values: {key}")

    required_aliases = (CANTP_COMMON, DCM_COMMON, DCM_SERVICES_COMMON,
                        CANTP_FEATURE_FILE, DCM_FEATURE_FILE, CAN_PT_FILE)
    for alias in required_aliases:
        path = resolve_file_alias(config, alias)
        if not path.exists():
            errors.append(f"arxml not found: {path}")

    plan, plan_warnings = _plan_entries(config, values)
    warnings.extend(plan_warnings)

    from arxml_patcher import find_matches, load

    for file_path, entries in plan.items():
        if not file_path.exists():
            continue
        tree = load(file_path)
        root = tree.getroot()
        for entry, _new in entries:
            if not find_matches(root, entry["locator"]):
                msg = f"{file_path.name}: no match for {entry['param']} locator={entry['locator']}"
                if entry.get("optional"):
                    warnings.append(msg + " (optional)")
                else:
                    warnings.append(msg)

    report = ["[validate]",
              f"  inputs file: {args.input or _pretty_path(XLSX_PATH)}",
              f"  cache dir  : {_pretty_path(VALUES_PATH.parent)}",
              f"  errors     : {len(errors)}",
              f"  warnings   : {len(warnings)}"]
    for e in errors:
        report.append(f"  ERROR   {e}")
    for w in warnings:
        report.append(f"  WARN    {w}")
    text = "\n".join(report)
    print(text)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / "validation_report.txt").write_text(text + "\n", encoding="utf-8")
    return 0 if not errors else 2


def cmd_fscs(args: argparse.Namespace) -> int:
    """Regenerate ``outputs/FSCS.txt`` from the current values file.

    Independent of ``apply`` so you can refresh the snapshot after
    hand-editing ``inputs/DiagComm_values.json`` without having to run
    a full dry-run + arxml parse pass.
    """
    if args.input:
        if not args.input.exists():
            print(f"[fscs] --input file not found: {args.input}")
            return 1
        unified = _read_input_file(args.input)
    else:
        unified, rc = _ensure_values_or_seed("fscs")
        if rc != 0:
            return rc
    config, values = split_unified(unified)
    _inject_runtime_options(config, values)
    schema = load_json(SCHEMA_PATH) if SCHEMA_PATH.exists() else None
    unfilled = _check_template_fillness(config, values, schema)
    if unfilled:
        _print_fillness_report(unfilled, command="fscs")
        return 2
    _inject_derived_values(values)
    out = _write_fscs(values, config, mode="SNAPSHOT")
    if out is None:
        print(f"[fscs] schema not found: {SCHEMA_PATH}")
        print("[fscs] run `pipeline.py gen-schema` first.")
        return 1
    print(f"[fscs] wrote {out}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    from arxml_patcher import PatchReport, apply_to_file

    # Lazy-seed gate (mirrors cmd_validate): an explicit --input is
    # used as-is; the default path auto-seeds on a fresh project.
    if args.input:
        if not args.input.exists():
            print(f"[apply] --input file not found: {args.input}")
            return 1
        values_path = args.input
        unified = _read_input_file(values_path)
    else:
        unified, rc = _ensure_values_or_seed("apply")
        if rc != 0:
            return rc
        values_path = VALUES_PATH
    config, values = split_unified(unified)
    _inject_runtime_options(config, values)
    schema = load_json(SCHEMA_PATH) if SCHEMA_PATH.exists() else None
    unfilled = _check_template_fillness(config, values, schema)
    if unfilled:
        _print_fillness_report(unfilled, command="apply")
        return 2
    _inject_derived_values(values)

    # Fail-fast semantic checks: never apply a CAN ID that doesn't fit the
    # selected format, an STmin above the 127 ms cap, or a PaddingByte
    # outside 0..0xFF. These would silently produce wrong arxml.
    sem_errors, _ = _semantic_checks(values)
    if sem_errors:
        print("[apply] semantic check failed:")
        for e in sem_errors:
            print(f"  ERROR {e}")
        print("[apply] refusing to run; fix inputs/DiagComm.xlsx and re-run.")
        return 2

    plan, warnings = _plan_entries(config, values)

    if not plan:
        print("[apply] nothing to do")
        return 0

    files = [p for p in plan if p.exists()]
    missing = [p for p in plan if not p.exists()]
    for p in missing:
        warnings.append(f"arxml not found, skipped: {p}")

    dry = bool(args.dry_run) or (
        not args.apply and config["options"].get("dry_run_default", False))

    aggregate = PatchReport()
    aggregate.warnings.extend(warnings)

    for file_path in files:
        entries = plan[file_path]
        rep = apply_to_file(file_path, entries, dry_run=dry)
        aggregate.extend(rep)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    header = [
        f"[apply] mode: {'DRY-RUN' if dry else 'WRITE'}",
        f"        values:  {values_path}",
        f"        dcom:    {resolve_dcom_root(config)}",
    ]
    text = "\n".join(header) + "\n\n" + aggregate.as_text()
    (OUTPUTS_DIR / "diff_report.txt").write_text(text, encoding="utf-8")
    print(text)

    # Refresh the human-readable snapshot so every apply session leaves
    # both the diff (per-node audit) AND FSCS.txt (one-page summary) on
    # disk. Mode label mirrors the apply mode so reviewers can tell at
    # a glance whether the snapshot corresponds to a committed write or
    # a proposal that still needs --apply.
    _write_fscs(values, config, mode=("DRY-RUN" if dry else "APPLIED"))

    if aggregate.errors:
        return 2
    return 0


# ---------------------------------------------------------------------------
# Seed helpers: reverse-walk arxml -> inputs/DiagComm_values.json
#
# One file, one lifecycle:
#   * If ``inputs/DiagComm_values.json`` already exists, every command
#     uses it as-is.
#   * If it is missing, ``_ensure_values_or_seed`` reverse-walks the
#     live arxml, writes a fully pre-filled values file at that path,
#     prints a banner, and tells the caller to exit 1 (DEGRADED) so
#     the user can review and edit before re-running.
#
# There is no intermediate "outputs/project_defaults.json" anymore:
# the values file IS the single source of truth the user hand-edits.


def _seed_values_from_arxml(config: dict[str, Any],
                            can_channel: int,
                            product_type: str) -> tuple[dict[str, Any], list[str]]:
    """Reverse-walk the live arxml for ``(product_type, can_channel)`` and
    return a parameters-shaped dict ready to be written to
    ``DiagComm_values.json::parameters``.

    For every non-derived ``PARAM_MAP`` entry the first locator hit is
    reverse-transformed (ms, hex, bool, enum label, â€¦) back into user
    space. Nested params (``CAN_DLC.rx_dl`` etc.) land under a nested
    dict so ``json.dump`` produces schema-shaped output.

    ``product_type`` is a project-identity field (lives under
    ``project.product_type`` in the v2 file); it does NOT end up in
    the returned parameters dict. Only ``CAN_Channel`` is carried back
    because v2 considers the channel a true parameter.

    Returns ``(parameters, notes)``. ``notes`` lists the params that
    could not be read (file missing, no locator match, reverse
    transform unavailable) â€” the caller decides whether to surface
    them.
    """
    from arxml_patcher import load as load_arxml

    config.setdefault("project", {})["product_type"] = product_type
    _inject_runtime_options(config, {"CAN_Channel": can_channel})

    values: dict[str, Any] = {}
    notes: list[str] = []
    tree_cache: dict[Path, Any] = {}

    def _has_nested(container: dict[str, Any], parts: list[str]) -> bool:
        cur: Any = container
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return False
            cur = cur[p]
        return True

    def _set_nested(container: dict[str, Any], parts: list[str],
                    value: Any) -> None:
        cur: dict[str, Any] = container
        for p in parts[:-1]:
            nxt = cur.get(p)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[p] = nxt
            cur = nxt
        cur[parts[-1]] = value

    for entry in PARAM_MAP:
        param = entry["param"]
        if entry.get("derived"):
            continue

        parts = param.split(".")
        if _has_nested(values, parts):
            continue

        file_path = resolve_file_alias(config, entry["file"])
        if not file_path.exists():
            notes.append(f"{param}: file missing ({file_path})")
            continue

        tree = tree_cache.get(file_path)
        if tree is None:
            tree = load_arxml(file_path)
            tree_cache[file_path] = tree
        raw = _read_current_value(tree.getroot(), entry)
        if raw is None:
            notes.append(f"{param}: no locator match in {file_path.name}")
            continue

        transform_name = entry.get("transform", "identity")
        rev = REVERSE_TRANSFORMS.get(transform_name)
        if rev is None:
            notes.append(
                f"{param}: no reverse transform for {transform_name!r}")
            continue
        try:
            user_value = rev(raw)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{param}: reverse transform failed ({exc})")
            continue

        _set_nested(values, parts, user_value)

    # CAN_Channel has no PARAM_MAP entry to reverse-walk. Carry the
    # effective channel the seed was parameterised with so the written
    # file is a round-trippable snapshot. product_type stays out of the
    # parameters block (lives in project.product_type).
    values.setdefault("CAN_Channel", can_channel)
    return values, notes


def _build_initial_values(parameters: dict[str, Any],
                          *,
                          project_name: str | None = None,
                          product_type: str | None = None
                          ) -> dict[str, Any]:
    """Build the v2 ``DiagComm_values.json`` shape (project +
    parameters) from a parameters dict.

    Project identity defaults to ``<fill-me>`` so
    ``_check_template_fillness`` can flag them with one stable
    placeholder name on first run.
    """
    project_block: dict[str, Any] = {
        "name": project_name if project_name else "<fill-me>",
        "product_type": product_type if product_type else "<fill-me>",
    }
    return {
        "$schema":    "diagcomm-toolkit/v2",
        "project":    project_block,
        "parameters": parameters,
    }


def _build_initial_config() -> dict[str, Any]:
    """Build the v2 ``DiagComm_config.json`` shape (paths + options)
    from the standard Bosch CusDiag defaults. Set once per project,
    rarely touched after that.
    """
    return {
        "$schema": "diagcomm-toolkit/v2",
        "paths":   dict(DEFAULT_PATHS),
        "options": dict(DEFAULT_OPTIONS),
    }


# Kept for backward-compat / tests / fixtures: builds the merged
# in-memory shape that ``split_unified`` consumes (i.e. project +
# parameters PLUS paths + options in the same dict). The on-disk
# split is implemented by ``_write_v2_input_pair`` below.
def _build_initial_skeleton(parameters: dict[str, Any],
                            *,
                            project_name: str | None = None,
                            product_type: str | None = None
                            ) -> dict[str, Any]:
    values = _build_initial_values(
        parameters, project_name=project_name, product_type=product_type)
    config = _build_initial_config()
    return {
        "$schema":    values["$schema"],
        "project":    values["project"],
        "paths":      config["paths"],
        "options":    config["options"],
        "parameters": values["parameters"],
    }


def _write_json_file(payload: dict[str, Any], path: Path) -> None:
    """Write ``payload`` to ``path`` as pretty JSON (UTF-8, trailing
    newline) -- the exact format a user would hand-edit. Caller is
    responsible for honouring the ownership contract (never overwrite
    a user-edited file).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_v2_input_pair(parameters: dict[str, Any],
                         *,
                         values_path: Path,
                         config_path: Path,
                         project_name: str | None = None,
                         product_type: str | None = None) -> None:
    """Write both halves of the v2 user input pair side-by-side:
    ``DiagComm_values.json`` (project + parameters) and
    ``DiagComm_config.json`` (paths + options).

    Atomicity note: writes are best-effort sequential. On a partial
    failure (e.g. disk full after the first write) the user gets one
    file but not the other; subsequent loads then fail loudly with the
    incomplete-pair error. We intentionally do not auto-clean the
    surviving half because deleting user-facing artefacts is exactly
    the kind of move the ownership contract forbids.
    """
    _write_json_file(
        _build_initial_values(parameters, project_name=project_name,
                              product_type=product_type),
        values_path,
    )
    _write_json_file(_build_initial_config(), config_path)


# Old name kept so fixtures and external callers don't break; it just
# writes both halves of the pair next to ``path``.
def _write_unified_file(unified: dict[str, Any], path: Path) -> None:
    parameters = dict(unified.get("parameters") or {})
    project_block = unified.get("project") or {}
    project_name = project_block.get("name") if isinstance(project_block, dict) else None
    product_type = project_block.get("product_type") if isinstance(project_block, dict) else None
    config_path = path.parent / CONFIG_FILENAME
    _write_v2_input_pair(
        parameters,
        values_path=path,
        config_path=config_path,
        project_name=project_name if isinstance(project_name, str) else None,
        product_type=product_type if isinstance(product_type, str) else None,
    )


# ---------------------------------------------------------------------------
# Template fillness check
#
# Since 1.19.0 the bundled inputs/{DiagComm_values, DiagComm_config}.json
# are committed templates with placeholders for every field the user
# really has to set:
#   - project.name / project.product_type      -> "<fill-me>"
#   - prompt_required parameters (CAN IDs,
#     CAN_DLC sub-fields, ...)                 -> null
# Any pipeline command that consumes user values runs this check first
# so the user gets a precise "fill these N fields" list instead of an
# obscure schema validation error five layers deeper.

PLACEHOLDER_VALUES = frozenset({
    "<fill-me>",
    "<set-me>",
    "<set-me-on-first-launch>",
    "<bootstrap>",
})


def _is_unfilled(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return True
        if s in PLACEHOLDER_VALUES:
            return True
    return False


def _check_template_fillness(
    config: dict[str, Any],
    parameters: dict[str, Any],
    schema: dict[str, Any] | None,
) -> list[str]:
    """Return one human-readable line per still-unfilled prompt-required
    field. Empty list = template is ready to use.

    Covered:
      - ``project.name``  (always required; no schema entry)
      - ``project.product_type``  (schema-required, enum-typed)
      - every ``parameters.*`` field (recursively) flagged
        ``prompt_required: true`` in ``assets/DiagComm_schema.json``

    A field is "unfilled" when missing, JSON ``null``, an empty
    string, or one of the documented placeholder strings (see
    ``PLACEHOLDER_VALUES``).
    """
    unfilled: list[str] = []
    project = config.get("project") or {}

    if _is_unfilled(project.get("name")):
        unfilled.append("project.name           -- 项目名（自由文本，例如 'MyProject'）")

    fields = (schema or {}).get("fields")
    if not isinstance(fields, dict):
        fields = {}

    if _is_unfilled(project.get("product_type")):
        spec = fields.get("product_type") or {}
        allowed = spec.get("allowed")
        hint = "平台变种"
        if isinstance(allowed, list) and allowed:
            hint += f"，可选: {' / '.join(map(str, allowed))}"
        unfilled.append(f"project.product_type   -- {hint}")

    def _walk(parent_path: str, sub_schema: dict[str, Any],
              sub_values: Any) -> None:
        for key, spec in sub_schema.items():
            if not isinstance(spec, dict):
                continue
            if not parent_path and key == "product_type":
                continue  # project identity, already covered above
            full_path = (
                f"parameters.{key}" if not parent_path
                else f"{parent_path}.{key}"
            )
            if spec.get("type") == "object":
                child = sub_values.get(key) if isinstance(sub_values, dict) else None
                if not isinstance(child, dict):
                    child = {}
                _walk(full_path, spec.get("fields") or {}, child)
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
                    bits.append("in: " + " / ".join(map(str, allowed)))
                if spec.get("unit"):
                    bits.append(str(spec["unit"]))
                hint = ", ".join(bits) if bits else "user-required"
                unfilled.append(f"{full_path:<22} -- {hint}")

    _walk("", fields, parameters)
    return unfilled


def _print_fillness_report(unfilled: list[str], *, command: str) -> None:
    """Pretty-print a fillness gap report in a stable format. Caller
    decides whether to also exit with a non-zero status.
    """
    print(f"[{command}] inputs/DiagComm.xlsx 还有 {len(unfilled)} 个必填字段未填：")
    for line in unfilled:
        print(f"  - {line}")
    print("")
    print("  inputs/DiagComm.xlsx 是 skill 自带的可编辑表格，跟着 git 走。")
    print("  打开它，到 Sheet 'Project & Parameters'，把红色背景的 Value 单元格")
    print("  填完整（下拉菜单 + 范围校验已配好），保存后重跑同一条命令即可。")
    print("  Notes 列里有每个字段的 type / 取值范围 / 单位 / schema default。")
    print("  其余 timer / 标志位字段（N_*, P2 timer, STmin, BS, PaddingByte,")
    print("  StrictDlcCheck, ...）已先填好 schema 默认值占位 — pipeline 不会拦你，")
    print("  但 apply 前请对照项目 spec 逐项 review，不一致就直接改这里。")


def _read_input_file(path: Path) -> dict[str, Any]:
    """Read an alternate values file passed via ``--input``.

    The flag accepts three shapes:

      * **v2 split (recommended)** — ``{$schema, project, parameters}``.
        Paths / options merge in from the sibling ``DiagComm_config.json``
        next to ``path`` if it exists; otherwise from the canonical
        ``inputs/DiagComm_config.json`` next to the skill; otherwise
        from ``DEFAULT_PATHS`` / ``DEFAULT_OPTIONS``.
      * **v2 single-file (legacy fixture)** — ``{$schema, project,
        paths, options, parameters}``. Used as-is; the inline
        paths / options win over any sibling file.
      * **v1 / flat** — top-level ``project_name`` + ``values`` (v1)
        or a bare flat parameters dict. Auto-migrated in memory and
        wrapped in the standard skeleton with default paths /
        options. ``product_type`` -- if present in a flat dict for
        round-trip convenience -- is hoisted into the ``project``
        sub-block.
    """
    raw = strip_doc_keys(load_json(path))
    if "parameters" in raw and isinstance(raw["parameters"], dict):
        if "paths" in raw or "options" in raw:
            return raw  # legacy single-file v2 fixture
        # v2 split: merge with sibling config (or canonical default)
        sibling_cfg: dict[str, Any] | None = _read_config_for(path)
        if sibling_cfg is None and CONFIG_PATH.exists():
            sibling_cfg = strip_doc_keys(load_json(CONFIG_PATH))
        if sibling_cfg is None:
            sibling_cfg = {"paths": dict(DEFAULT_PATHS),
                           "options": dict(DEFAULT_OPTIONS)}
        return merge_values_with_config(raw, sibling_cfg)
    if "values" in raw and isinstance(raw["values"], dict):
        return _migrate_v1_to_v2_in_memory(raw)
    flat = dict(raw)
    pt = flat.pop("product_type", None)
    return _build_initial_skeleton(flat, product_type=pt if isinstance(pt, str) else None)


def _parameters_block_from_file(path: Path) -> dict[str, Any]:
    """Return the ``parameters`` sub-dict from a v2 unified file on disk
    (auto-migrating v1 ``values`` if needed), or an empty dict if the
    file is unreachable / not unified-shaped.
    """
    try:
        raw = load_json(path)
    except Exception:  # noqa: BLE001
        return {}
    if isinstance(raw.get("parameters"), dict):
        return raw["parameters"]
    if isinstance(raw.get("values"), dict):
        migrated = _migrate_v1_to_v2_in_memory(raw)
        if isinstance(migrated.get("parameters"), dict):
            return migrated["parameters"]
    return {}


def _resolve_can_channel(args: argparse.Namespace,
                         schema: dict[str, Any] | None) -> int:
    """Pick an effective CAN channel for a seed / reseed run.

    Priority: ``--can-channel`` CLI arg > existing values file >
    schema default > hard fallback ``0``.
    """
    if getattr(args, "can_channel", None) is not None:
        return int(args.can_channel)
    if VALUES_PATH.exists():
        try:
            return int(_parameters_block_from_file(VALUES_PATH).get("CAN_Channel", 0))
        except Exception:  # noqa: BLE001
            pass
    if schema is not None:
        try:
            return int(schema["fields"]["CAN_Channel"]["default"])
        except Exception:  # noqa: BLE001
            pass
    return 0


def _resolve_product_type(args: argparse.Namespace,
                          schema: dict[str, Any] | None,
                          config: dict[str, Any] | None = None) -> str:
    """Pick an effective ``product_type`` for a seed / reseed run.

    Priority:
      1. ``--product-type`` CLI arg
      2. existing ``inputs/DiagComm_values.json::project.product_type``
         (if the file exists and has the field)
      3. filesystem probe: glob the project for the one ``RBAPLCust/cfg/<PT>/``
         folder that actually ships a matching arxml. Succeeds only when
         exactly one variant exists; otherwise falls through.
      4. schema default
      5. hard fallback ``"DPB"``

    Step 3 is the ergonomic win: on a fresh project the reseed command
    is effectively zero-arg, because the filesystem itself tells us
    which product is deployed.
    """
    if getattr(args, "product_type", None):
        return str(args.product_type)

    if VALUES_PATH.exists():
        try:
            raw = load_json(VALUES_PATH)
            project_block = raw.get("project") if isinstance(raw, dict) else None
            if isinstance(project_block, dict):
                pt = project_block.get("product_type")
                if isinstance(pt, str) and pt and not pt.startswith("<"):
                    return pt
            # v1 fallback: legacy values.product_type
            legacy_values = raw.get("values") if isinstance(raw, dict) else None
            if isinstance(legacy_values, dict):
                pt = legacy_values.get("product_type")
                if isinstance(pt, str) and pt:
                    return pt
        except Exception:  # noqa: BLE001
            pass

    if config is not None:
        pt = _probe_product_type_from_fs(config)
        if pt is not None:
            return pt

    if schema is not None:
        try:
            default = schema["fields"]["product_type"]["default"]
            if isinstance(default, str) and default:
                return default
        except Exception:  # noqa: BLE001
            pass

    return "DPB"


def _probe_product_type_from_fs(config: dict[str, Any]) -> str | None:
    """Probe the filesystem for a single deployed product_type folder.

    Reads ``paths.can_pt_file`` from ``config``, replaces the two
    placeholders with glob wildcards, and looks for matching files
    under the resolved ``dcom_root``. If the glob hits files that all
    come from the same ``{product_type}`` folder, return that value.
    Any ambiguity (0 hits, multiple product types, resolver error)
    returns ``None`` and the caller falls back to the next rule.
    """
    try:
        template = config.get("paths", {}).get("can_pt_file")
        if not isinstance(template, str) or "{product_type}" not in template:
            return None
        dcom = resolve_dcom_root(config)
    except Exception:  # noqa: BLE001
        return None

    prefix = template.split("{product_type}", 1)[0]
    pattern = template.replace("{product_type}", "*").replace("{can_channel}", "*")

    try:
        matches = list(dcom.glob(pattern))
    except Exception:  # noqa: BLE001
        return None
    if not matches:
        return None

    products: set[str] = set()
    for m in matches:
        rel = m.relative_to(dcom).as_posix()
        if not rel.startswith(prefix):
            continue
        tail = rel[len(prefix):]
        first_sep = tail.find("/")
        if first_sep == -1:
            continue
        products.add(tail[:first_sep])

    if len(products) == 1:
        return next(iter(products))
    return None


def _bootstrap_unified() -> dict[str, Any]:
    """Refresh ``.cache/`` from ``inputs/DiagComm.xlsx``.

    Since 1.20.0 the user-editable input lives in
    ``inputs/DiagComm.xlsx`` (a single Excel workbook with
    data-validation dropdowns) and ``scripts/excel_loader.py``
    materialises it into the legacy JSON / YAML cache files under
    ``.cache/``. This function is now a thin wrapper around
    ``runtime.load_user_inputs()`` -- the cache regeneration is the
    only "bootstrap" left.

    If ``inputs/DiagComm.xlsx`` is missing, ``load_user_inputs``
    raises ``SystemExit`` with the exact "cp ..." command needed to
    recover from ``assets/inputs_template.xlsx``; that bubbles up to
    the caller (``cmd_status`` etc) which surfaces it as a BROKEN
    status.
    """
    from runtime import load_user_inputs as _load
    unified = _load()
    print(f"[bootstrap] refreshed .cache/ from inputs/DiagComm.xlsx")
    print(f"            edit inputs/DiagComm.xlsx (Sheet 'Project & Parameters')")
    print(f"            to fill any REQUIRED cell, then re-run.")
    return unified


def _build_blank_parameters_template() -> dict[str, Any]:
    """Return the parameters block as shipped under
    ``inputs/DiagComm_values.json``.

    Layout (since 1.19.1): list **every** parameter, so the user sees
    the full set instead of an opaque "fields you didn't write get
    schema defaults" rule.

      - ``prompt_required: true``  -> ``None`` (fillness check refuses
        to apply until set; covers project.product_type at the top
        level and CAN_DLC sub-fields recursively).
      - any other field            -> the schema default value
        (visible placeholder; user is expected to review against the
        project spec, but apply still works out of the box if defaults
        happen to match).

    The shape is derived from ``assets/DiagComm_schema.json`` so a
    schema regeneration (gen-schema) automatically picks up new
    parameters next time someone runs ``reseed`` or the lazy bootstrap.

    ``project.product_type`` is *not* a parameter and is omitted here;
    it lives at ``project.product_type`` in the values file.
    """
    schema = load_json(SCHEMA_PATH)
    fields = schema.get("fields", {})

    def _walk(sub_fields: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, spec in sub_fields.items():
            if not isinstance(spec, dict):
                continue
            if name == "product_type":
                continue
            if spec.get("type") == "object":
                out[name] = _walk(spec.get("fields") or {})
                continue
            if spec.get("prompt_required"):
                out[name] = None
            else:
                out[name] = spec.get("default")
        return out

    return _walk(fields)


def _ensure_values_or_seed(command_tag: str) -> tuple[dict[str, Any] | None, int]:
    """Guarantee ``VALUES_PATH`` exists. Return ``(unified, exit_code)``.

    * If the file already exists -> ``(loaded_unified_dict, 0)``; the
      caller continues as normal (typically ``split_unified()`` and
      then runs the command body).
    * If the file is missing -> bootstrap a full skeleton (paths +
      options + reverse-walked values), write it, print a banner, and
      return ``(None, 1)``. The caller propagates exit code 1
      (DEGRADED) so the user can review the new file before re-running.
    * If the bootstrap itself cannot run (no schema, arxml resolve
      error) -> ``(None, 2)`` with a BROKEN-style error line.
    """
    _check_legacy_layout()
    if VALUES_PATH.exists():
        return load_unified(), 0

    try:
        _bootstrap_unified()
    except Exception as exc:  # noqa: BLE001
        print(f"[{command_tag}] cannot seed DiagComm_values.json: {exc}")
        return None, 2
    return None, 1


# ---------------------------------------------------------------------------
# reseed
#
# Explicit, user-invoked seeding of inputs/DiagComm_values.json from
# the live arxml. Kept as a discoverable synonym for "the lazy-seed
# path, but ran on purpose".
#
# Ownership invariant:
#   inputs/DiagComm_values.json is the USER'S canvas. This skill never
#   overwrites it. ``reseed`` therefore only writes when the file is
#   MISSING; it refuses if the file already exists. If you want to
#   throw away your edits and re-sync from arxml, you must delete the
#   file yourself (``rm inputs/DiagComm_values.json``) and then run
#   ``reseed`` (or any pipeline command -- they all auto-seed on
#   first run). Deleting is a deliberate act of ownership by the user;
#   the skill never makes that decision on its own.


def cmd_reseed(args: argparse.Namespace) -> int:
    """Reverse-walk the live arxml and write the resulting parameter
    values to a *suggestion* file under ``outputs/`` for the user to
    review and copy into ``inputs/DiagComm.xlsx``.

    Two modes:
      - default (1.20.0+): print "the Excel template already ships
        pre-filled with schema defaults; nothing to do" and exit 0.
        ``inputs/DiagComm.xlsx`` is git-tracked and ships in every
        clone; there is no longer a "missing input file" branch to
        re-bootstrap from.
      - ``--from-arxml``: reverse-walk the live arxml and write a
        ``outputs/reseed_suggestion.json`` snapshot. The user opens
        the file, transcribes interesting values into the Excel sheet,
        and re-runs ``validate`` / ``apply``. Cache-safe: never writes
        to ``.cache/`` because the cache is auto-regenerated from
        Excel on every load.

    Exit codes:
        0 = OK (no-op or suggestion written)
        2 = hard error (legacy layout, --from-arxml read failure, ...).
    """
    try:
        _check_legacy_layout()
    except SystemExit as exc:
        print(str(exc))
        return 2

    if not getattr(args, "from_arxml", False):
        print("[reseed] no-op: since 1.20.0 the user template lives in")
        print(f"         {_pretty_path(XLSX_PATH)} and")
        print("         ships pre-filled with schema defaults.")
        print("         To restore the blank template:")
        print(f"           python {SKILL_ROOT.as_posix()}/scripts/pipeline.py --init-project --force")
        print("         To pre-fill from the current project's arxml, re-run with")
        print(f"           python {SKILL_ROOT.as_posix()}/scripts/pipeline.py reseed --from-arxml")
        return 0

    # --from-arxml: write a suggestion snapshot the user can transcribe.
    schema = load_json(SCHEMA_PATH) if SCHEMA_PATH.exists() else None
    synth_config: dict[str, Any] = {
        "project": {"name": "<bootstrap>"},
        "paths": dict(DEFAULT_PATHS),
        "options": dict(DEFAULT_OPTIONS),
    }
    can_channel = _resolve_can_channel(args, schema)
    product_type = _resolve_product_type(args, schema, synth_config)

    try:
        seed_values, notes = _seed_values_from_arxml(
            synth_config, can_channel, product_type)
    except Exception as exc:  # noqa: BLE001
        print(f"[reseed --from-arxml] failed to read arxml: {exc}")
        return 2

    suggestion = {
        "$schema": "diagcomm-toolkit/v2",
        "_README": [
            "Auto-generated by `pipeline.py reseed --from-arxml`.",
            "These are the values reverse-walked from the project's live arxml.",
            f"Open inputs/DiagComm.xlsx, Sheet 'Project & Parameters', and",
            "transcribe whichever values you want to keep into the Value column.",
            "Then re-run `pipeline.py validate`.",
        ],
        "project": {"product_type": product_type},
        "parameters": seed_values,
    }
    suggestion_path = OUTPUTS_DIR / "reseed_suggestion.json"
    suggestion_path.parent.mkdir(parents=True, exist_ok=True)
    suggestion_path.write_text(
        json.dumps(suggestion, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"[reseed --from-arxml] wrote {_pretty_path(suggestion_path)}")
    print(f"         project.product_type={product_type}, "
          f"parameters.CAN_Channel={can_channel}, "
          f"{_count_leaf_values(seed_values)} leaf parameters captured")
    print("         confirm against project spec, then transcribe into")
    print(f"         {_pretty_path(XLSX_PATH)} (Sheet 'Project & Parameters')")
    print("         before running validate / apply.")
    if notes:
        print(f"         {len(notes)} field(s) could not be read:")
        for n in notes:
            print(f"           - {n}")
    return 0


# ---------------------------------------------------------------------------
# landing-report


def cmd_landing_report(args: argparse.Namespace) -> int:
    """Enumerate every landing spot in the current project's arxml and
    write a human-readable report to ``outputs/landing_report.txt``.

    Use this to verify that the invariant catalog in
    ``reference/landing_spots.md`` matches what actually ships in the
    project: any missing or unexpected hit points to a divergence that
    needs extending either ``PARAM_MAP`` or ``config.paths``.

    The report groups entries by parameter, lists the locator + target
    file + current VALUE for every hit, and prints a grand total. It
    does NOT read ``DiagComm_values.json`` â€” it only observes the
    arxml as it is on disk.
    """
    from datetime import datetime

    from arxml_patcher import AR_NS, find_matches
    from arxml_patcher import load as load_arxml

    # landing-report doesn't need the values block (only locator
    # discovery against live arxml), but we still load the unified file
    # for project_name + paths. If the user hasn't seeded the file yet
    # we hand back the standard "BROKEN" hint so they bootstrap with a
    # cheaper command first (status / reseed) instead of trying to
    # report against a synthesized config.
    try:
        _check_legacy_layout()
    except SystemExit as exc:
        print(str(exc))
        return 2
    if not XLSX_PATH.exists():
        print(f"[landing-report] {_pretty_path(XLSX_PATH)} "
              "not found; restore via:\n"
              f"  python {SKILL_ROOT.as_posix()}/scripts/pipeline.py --init-project --force")
        return 2

    unified = load_unified()
    config, _values = split_unified(unified)
    schema = load_json(SCHEMA_PATH) if SCHEMA_PATH.exists() else None

    can_channel = _resolve_can_channel(args, schema)
    product_type = _resolve_product_type(args, schema, config)
    _inject_runtime_options(
        config,
        {"CAN_Channel": can_channel, "product_type": product_type},
    )

    dcom_root = resolve_dcom_root(config)

    by_param: dict[str, list[dict[str, Any]]] = {}
    for entry in PARAM_MAP:
        by_param.setdefault(entry["param"], []).append(entry)

    lines: list[str] = []
    lines.append("# DiagComm landing-spot live report")
    lines.append(f"generated_at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"dcom_root   : {str(dcom_root).replace(chr(92), '/')}")
    lines.append(f"product_type: {product_type}")
    lines.append(f"can_channel : {can_channel}")
    lines.append("")

    total_hits = 0
    total_locators = 0
    total_unmatched = 0

    tree_cache: dict[Path, Any] = {}
    for param in sorted(by_param):
        lines.append(f"== {param} ==")
        for entry in by_param[param]:
            locator = entry["locator"]
            transform_name = entry.get("transform", "identity")
            optional = " [optional]" if entry.get("optional") else ""
            suffix = locator.get("def_suffix")
            if isinstance(suffix, list):
                suffix_str = "|".join(suffix)
            else:
                suffix_str = str(suffix)
            anc = (locator.get("ancestor_short_name") or
                   locator.get("ancestor_short_name_prefix") or "")
            lines.append(
                f"  locator: def={suffix_str}  anc={anc}  transform={transform_name}{optional}"
            )
            total_locators += 1

            file_path = resolve_file_alias(config, entry["file"])
            rel = str(file_path).replace(str(dcom_root), "").lstrip("\\/").replace("\\", "/")
            if not file_path.exists():
                lines.append(f"    file : {rel}  (MISSING)")
                total_unmatched += 1
                continue

            tree = tree_cache.get(file_path)
            if tree is None:
                tree = load_arxml(file_path)
                tree_cache[file_path] = tree
            root = tree.getroot()
            hits = find_matches(root, locator)
            lines.append(f"    file : {rel}  ({len(hits)} hit(s))")
            if not hits:
                total_unmatched += 1
                continue
            for pv in hits:
                chain = _ancestor_short_name_chain(pv)
                value_el = pv.find(f"{{{AR_NS}}}VALUE")
                raw = (value_el.text or "").strip() if value_el is not None else ""
                def_ref = pv.find(f"{{{AR_NS}}}DEFINITION-REF")
                leaf = ""
                if def_ref is not None and def_ref.text:
                    leaf = def_ref.text.rsplit("/", 1)[-1]
                lines.append(f"      * {chain} :: {leaf} = {raw!r}")
                total_hits += 1
        lines.append("")

    lines.append(f"TOTAL parameters : {len(by_param)}")
    lines.append(f"TOTAL locators   : {total_locators}")
    lines.append(f"TOTAL hits       : {total_hits}")
    lines.append(f"unmatched locators: {total_unmatched}")

    text = "\n".join(lines) + "\n"
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUTS_DIR / "landing_report.txt"
    out_path.write_text(text, encoding="utf-8")

    print(f"[landing-report] wrote {out_path}")
    print(f"  parameters       : {len(by_param)}")
    print(f"  locators         : {total_locators}")
    print(f"  total hits       : {total_hits}")
    print(f"  unmatched locators: {total_unmatched}")
    return 0 if total_unmatched == 0 else 0  # non-zero is informational


# ---------------------------------------------------------------------------
# init-project (workspace bootstrap)
#
# This is the v2.0.0 entry point that scaffolds a per-project workspace
# under ``<cwd>/.DCOM_AI/DiagComm_Toolkit_PRJ/``. It is intentionally NOT
# wired into the regular subparser tree because:
#
#   * every other command refuses to run without an initialised workspace
#     (loud SystemExit from runtime._check_workspace_initialized), and
#   * we want users to discover the bootstrap step via a dedicated flag
#     name that mirrors did-toolkit (``--init-project``) rather than a
#     buried subcommand.
#
# The handler is dispatched by ``main()`` *before* argparse runs the
# subparser tree.


def _localize_readme_placeholders(xlsx_path: Path) -> bool:
    """Substitute every ``<skill>`` placeholder on the README sheet of a
    freshly-copied ``inputs/DiagComm.xlsx`` with the resolved skill
    path, so the in-workbook Trouble-shooting hints are copy-paste-able
    on this user's machine.

    The bundled ``assets/inputs_template.xlsx`` ships with ``<skill>``
    as a placeholder because that template is shared across every
    install. At init-time we know the skill root, so we localize.

    Best-effort: returns False on any openpyxl / write failure so a
    keyring / read-only filesystem glitch can never block init.
    """
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        return False
    try:
        wb = openpyxl.load_workbook(xlsx_path)
        if "README" not in wb.sheetnames:
            wb.close()
            return False
        ws = wb["README"]
        replacement = SKILL_ROOT.as_posix()
        touched = False
        for row in ws.iter_rows(values_only=False):
            for cell in row:
                if isinstance(cell.value, str) and "<skill>" in cell.value:
                    cell.value = cell.value.replace("<skill>", replacement)
                    touched = True
        if touched:
            wb.save(xlsx_path)
        wb.close()
        return touched
    except Exception:
        return False


def _scaffold_workspace(workspace_root: Path,
                        template_src: Path,
                        skeleton_src: Path,
                        *,
                        force: bool) -> tuple[bool, list[str]]:
    """Create ``workspace_root`` and seed it with the bundled templates.

    Returns ``(any_change, summary_lines)`` where ``any_change`` is True
    if any file or directory was created / overwritten this run. The
    summary lines are printable as-is (already prefixed with status
    glyphs).
    """
    summary: list[str] = []
    any_change = False

    subdirs = ("inputs", "outputs", "state", ".cache")
    for sub in subdirs:
        target = workspace_root / sub
        if target.exists():
            summary.append(f"  [skip ] {sub}/  (already exists)")
            continue
        target.mkdir(parents=True, exist_ok=True)
        any_change = True
        summary.append(f"  [mkdir] {sub}/")

    # Drop a tiny .gitignore inside the workspace so the user's project
    # repo doesn't accidentally commit the regenerable bits. We only
    # create it once (never overwrite) -- the user owns it after that.
    gitignore = workspace_root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "# diagcomm-toolkit workspace -- auto-generated content; safe to ignore.\n"
            "# Keep `inputs/` (your hand-edited Excel) and `state/` (DOORS upload\n"
            "# state) in git; let `outputs/` and `.cache/` regenerate on demand.\n"
            ".cache/\n"
            "outputs/\n"
            "~$*.xlsx\n"
            "inputs/.~lock.*\n"
            "inputs/~$*\n",
            encoding="utf-8",
        )
        any_change = True
        summary.append("  [write] .gitignore")

    xlsx_target = workspace_root / "inputs" / "DiagComm.xlsx"
    if xlsx_target.exists() and not force:
        summary.append(f"  [skip ] inputs/DiagComm.xlsx  (already filled; "
                       "pass --force to overwrite with the blank template)")
    else:
        if not template_src.is_file():
            raise SystemExit(
                f"\n[diagcomm-toolkit] template missing: {template_src}\n"
                "The skill checkout is incomplete. Restore from git:\n"
                "  git checkout -- assets/inputs_template.xlsx\n"
            )
        import shutil
        shutil.copyfile(template_src, xlsx_target)
        any_change = True
        verb = "overwrite" if (xlsx_target.exists() and force) else "copy  "
        summary.append(f"  [{verb}] inputs/DiagComm.xlsx  "
                       f"<- {_pretty_path(template_src)}")
        if _localize_readme_placeholders(xlsx_target):
            summary.append("  [patch ] inputs/DiagComm.xlsx::README  "
                           "(substituted <skill> with resolved skill path)")

    return any_change, summary


def cmd_init_project(argv: list[str]) -> int:
    """Scaffold ``<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/``.

    With no arguments this targets ``<cwd>/.DCOM_AI/...``; pass an
    explicit project root to override (handy for CI / scripted setup).
    """
    parser = argparse.ArgumentParser(
        prog="pipeline.py --init-project",
        description="Scaffold a diagcomm-toolkit workspace inside the given "
                    "project root (or cwd by default). Idempotent: safe to "
                    "re-run; existing files are preserved unless --force.",
    )
    parser.add_argument(
        "project_root", nargs="?", type=Path, default=Path.cwd(),
        help="Project root that will own the .DCOM_AI/DiagComm_Toolkit_PRJ/ "
             "workspace (default: current working directory).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing inputs/DiagComm.xlsx with the blank "
             "template baseline. Use this only after backing up your edits.",
    )
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    workspace = project_root / DCOM_AI_DIRNAME / WORKSPACE_NAME

    # Refuse to scaffold inside the skill checkout itself -- that would
    # mean the user forgot to ``cd`` to their project root and would
    # quietly write project data into the user-level skill clone.
    try:
        workspace_in_skill = workspace.resolve().is_relative_to(
            SKILL_ROOT.resolve())
    except (ValueError, OSError):
        workspace_in_skill = False
    if workspace_in_skill:
        raise SystemExit(
            "\n[diagcomm-toolkit] refusing to scaffold a workspace inside "
            "the skill checkout:\n"
            f"  skill     : {SKILL_ROOT}\n"
            f"  workspace : {workspace}\n\n"
            "cd to your real project root first (the directory that owns "
            "the AUTOSAR tree), then re-run --init-project.\n"
        )

    print("diagcomm-toolkit --init-project")
    print(f"  skill     : {SKILL_ROOT}")
    print(f"  project   : {project_root}")
    print(f"  workspace : {workspace}")
    print()

    workspace.mkdir(parents=True, exist_ok=True)

    any_change, summary = _scaffold_workspace(
        workspace_root=workspace,
        template_src=TEMPLATE_PATH,
        skeleton_src=ASSETS_DIR / "doors_mapping_skeleton.yaml",
        force=args.force,
    )
    for line in summary:
        print(line)

    print()
    if any_change:
        print("Workspace scaffolded. Next steps:")
    else:
        print("Workspace already initialised. Next steps:")
    rel_xlsx = (workspace / "inputs" / "DiagComm.xlsx")
    print(f"  1. Open {rel_xlsx}")
    print( "     Fill the red-highlighted required cells on Sheet "
           "'Project & Parameters'")
    print( "     and the matching paths on Sheet 'Paths & Options'.")
    print(f"  2. From {project_root}, run:")
    print(f"     python {SKILL_ROOT.as_posix()}/scripts/pipeline.py status")
    return 0


# ---------------------------------------------------------------------------
# CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diagcomm-toolkit",
        description="Modify CusDiag stack arxml files from DiagComm parameter inputs.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    sp = subs.add_parser(
        "status",
        help="Readiness dashboard: one-shot check of config + schema + values + "
             "arxml + snapshot freshness (exit 0/1/2 = READY/DEGRADED/BROKEN).",
    )
    sp.set_defaults(func=cmd_status)

    sp = subs.add_parser("gen-schema", help="DiagComm.txt -> DiagComm_schema.json")
    sp.add_argument("--input", type=Path)
    sp.add_argument("--output", type=Path)
    sp.add_argument("--check", action="store_true",
                    help="Don't write; exit 1 if the on-disk schema differs from "
                         "what DiagComm.txt would regenerate (print a unified diff).")
    sp.set_defaults(func=cmd_gen_schema)

    sp = subs.add_parser(
        "export-catalog",
        help="Render PARAM_MAP as a markdown table and inject it into "
             "reference/landing_spots.md between auto:catalog-begin/end fences."
    )
    sp.add_argument("--output", type=Path,
                    help="Target markdown file (default: reference/landing_spots.md)")
    sp.add_argument("--check", action="store_true",
                    help="Don't write; exit 1 if the on-disk catalog block differs "
                         "from what mapping.yaml would produce.")
    sp.set_defaults(func=cmd_export_catalog)

    sp = subs.add_parser(
        "landing-report",
        help="Enumerate every landing spot in the current project -> outputs/landing_report.txt",
    )
    sp.add_argument("--can-channel", type=int,
                    help="CAN channel for the per-channel Can<N>_CusDiag arxml lookup.")
    sp.add_argument("--product-type",
                    choices=["DPB", "ESP", "IPB", "RBU"],
                    help="Product variant for the {product_type} path "
                         "placeholder. Defaults to values file, then "
                         "filesystem probe, then schema default.")
    sp.set_defaults(func=cmd_landing_report)

    sp = subs.add_parser(
        "reseed",
        help="Recreate inputs/DiagComm_{values,config}.json. Default "
             "writes the bundled BLANK template (instant, no arxml IO); "
             "pass --from-arxml to pre-fill from current project ARXML "
             "(slower). Only runs when both files are MISSING; refuses "
             "otherwise (inputs/ is user-owned -- delete first to redo).",
    )
    sp.add_argument("--from-arxml", action="store_true",
                    help="Pre-fill every parameter by reverse-walking the "
                         "live arxml under DEFAULT_PATHS. Slower but useful "
                         "if the project already has working arxml and you "
                         "want the current state mirrored back into JSON.")
    sp.add_argument("--can-channel", type=int,
                    help="(--from-arxml only) CAN channel index for the "
                         "per-channel Can<N>_CusDiag arxml lookup. "
                         "Defaults to schema default (0).")
    sp.add_argument("--product-type",
                    choices=["DPB", "ESP", "IPB", "RBU"],
                    help="(--from-arxml only) product variant (folder name "
                         "under RBAPLCust/cfg/). Priority: this flag > "
                         "filesystem probe > schema default.")
    sp.set_defaults(func=cmd_reseed)

    sp = subs.add_parser("validate",
                         help="Check values file + mapping coverage")
    sp.add_argument("--input", type=Path)
    sp.set_defaults(func=cmd_validate)

    sp = subs.add_parser("apply", help="Rewrite arxml files")
    sp.add_argument("--input", type=Path)
    sp.add_argument("--dry-run", action="store_true",
                    help="Preview changes without writing files")
    sp.add_argument("--apply", action="store_true",
                    help="Force real write even when dry_run_default=true")
    sp.set_defaults(func=cmd_apply)

    sp = subs.add_parser(
        "fscs",
        help="Regenerate outputs/FSCS.txt from inputs/DiagComm.xlsx "
             "(one-page summary of the final user-space configuration).",
    )
    sp.add_argument("--input", type=Path,
                    help="Alternate values file (v2 JSON shape; default: "
                         "auto-generated .cache/DiagComm_values.json).")
    sp.set_defaults(func=cmd_fscs)

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # ``--init-project`` is dispatched before argparse runs the
    # subparser tree because it has to scaffold the workspace BEFORE
    # any of the subcommands (which all assume an initialised
    # workspace) can resolve their default paths.
    if raw and raw[0] in ("--init-project", "init-project"):
        return cmd_init_project(raw[1:])

    args = build_parser().parse_args(raw)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
