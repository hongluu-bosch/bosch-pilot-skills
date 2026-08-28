#!/usr/bin/env python3
"""diagcomm-toolkit -> DOORS payload builder (Step 8 helper, v7).

1.16.0 layout polish (no rule changes vs v7):
  * The FSCS body produced by ``scripts/reports.py`` now uses a
    three-line ``#`` header and a grid-aligned two-column parameter
    table (label column left-padded to the longest leaf name, value
    column right-padded to the longest rendered value). This file
    consumes the FSCS verbatim, so Object Text inherits the new
    layout for free.
  * ``_build_delta_text`` (the ``params_changed`` append block) now
    matches that new style: two-line ``# Update`` banner and a label
    column sized to the params that actually changed in this run, so
    the FSCS body and the appended delta read as one continuous
    report rather than two visually disjointed sections.

v7 change vs v6 ("trim Object Text" rework, 1.15.0):
  * Object Text on update is no longer a monotonically-growing log
    that re-attaches the full FSCS on every change. Behaviour now
    splits on whether the parameter set actually changed:
        params_changed        -> APPEND a compact delta-only block
                                  (one line per changed parameter,
                                  aligned with FSCS body width). No
                                  "Refreshed FSCS" replay.
        pp_only_changed       -> REPLACE Object Text with current FSCS.
                                  parameters didn't change so re-
                                  appending would create pure
                                  redundancy.
        fscs_only_changed     -> REPLACE Object Text with current FSCS.
                                  Same rationale -- the only thing
                                  that changed is the FSCS rendering
                                  itself; just rewrite it in place.
        no_change             -> APPEND a single-line marker (only
                                  emitted with --force-no-skip).
    Insert kinds (first_insert / params_and_pp_changed) still seed
    the row with the current FSCS verbatim.

    `RB_Product` / `RB_Realizing_SWitem` are unchanged: they remain
    growing unions across runs, so multi-mapping coverage is still
    discoverable from the row even after Object Text gets replaced.

v6 change vs v5 (the "append-style update" rework, superseded by v7):
  * The DOORS row tracked under each module_uuid is treated as a
    LIVING record. In update mode:
        - `RB_Product`        = state.covered_products  U  current product
        - `RB_Realizing_SWitem` = state.covered_arxml_paths  U  current paths
        - `Object Text`       = (governed by v7 rules above; the v6
                                  always-append model has been retired)
    In insert mode (first_insert / params_and_pp_changed) the row is
    seeded fresh: covered_* lists reset to the single current values
    and Object Text equals the current FSCS.txt verbatim.
  * New extras the mapping yaml can bind to:
        extras.rb_product_value     RB_Product cell content (mapped per
                                    item via value_maps.RB_Product, then
                                    joined with newlines)
        extras.rb_realizing_value   RB_Realizing_SWitem cell content
                                    (newline-joined union of paths)
        extras.appended_block       just the block appended this run
                                    (transparency / debugging)
  * `build_payload()` now accepts `existing_state` (the state.modules
    entry dict, or None) and `change_kind` so the orchestrator
    (`doors_sync.py`) can drive the append behaviour without each
    caller re-implementing classification.

v5 change vs v4:
  * `row.object_text` is an authoritative per-row field; mapping yaml
    binds `Object Text` to it. (v6 still honours this binding; the
    value is now built by `_build_object_text_for_kind`.) The
    deprecated `extras.fscs_hybrid_text` is still emitted for
    backward compat but new mappings should NOT bind to it.

v4 change vs v3:
  * Output xlsx is now produced with xlsxwriter (DOORS-native format)
    instead of openpyxl. This removes the "openpyxl-generated xlsx
    silently hangs DOORS upload" failure mode that previously required a
    separate fix_upload_file.py post-processing step. The template at
    The bundled assets/doors_template.xlsx is still consulted for the
    canonical column order, but is never copied / written back into.

v3 change vs v2:
  * No more hand-picked per-arxml `destinations` map.
  * The DOORS-side insertion point is found *dynamically* in
    outputs/doors_export.json via an Object-Heading lookup, so this file
    is portable across projects.

Layout model (unchanged):
    The bundled DOORS-side Excel template is column-based (see assets/doors_template.xlsx):
        row 1   meta header  (sizeRow / sizeColumn)
        row 2   column headers
        row 3+  data rows (one per arxml that diagcomm-toolkit modified)

Modes:
    insert  : (default) anchor's *AbsoluteNumber* -> column "Destination
              Object" (DOORS expects the bare number, NOT the full
              identifier string like <DOC>_SWFS_<SECTION>_NNN), column
              "Absolute Number" left blank. DOORS lays the rows down
              sequentially after the anchor in upload order.
    update  : per-arxml AbsoluteNumber -> column "Absolute Number",
              column "Destination Object" left blank. DOORS overwrites
              the existing rows in place.

Inputs:
    outputs/FSCS.txt              (apply's FSCS of record)
    outputs/diff_report.txt       (apply's per-arxml change list)
    outputs/doors_export.json     (downloaded by agent via doors MCP)
    assets/doors_template.xlsx    (bundled DOORS template)
    inputs/doors_mapping.yaml     (user-owned mapping)
    inputs/DiagComm_values.json   (project_name + product_type)

Outputs:
    outputs/doors_upload.xlsx     (filled, ready for upload)
    outputs/doors_payload_report.txt

Exit codes:
    0  success
    1  degraded (e.g. anchor matched a fallback rule, or some warning)
    2  fatal -- read the report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import doors_state  # noqa: E402  (imported after sys.path tweak)

# Default separator for multi-value DOORS cells (RB_Product /
# RB_Realizing_SWitem). DOORS renders newline-separated entries inside
# a single cell as a vertical list. Made explicit here so the day we
# need to switch (e.g. semicolons), the change is one line.
MULTIVALUE_SEPARATOR = "\n"

SKILL_ROOT = HERE.parent
# v2.0.0: outputs/, state/, .cache/ all live in the per-project workspace
# at <project>/.DCOM_AI/DiagComm_Toolkit_PRJ/. The skill checkout itself
# carries no user data anymore. WORKSPACE_ROOT is cwd-anchored at import
# time -- callers cd into the project root before invoking the skill.
WORKSPACE_ROOT = (Path.cwd() / ".DCOM_AI" / "DiagComm_Toolkit_PRJ").resolve()
CACHE_DIR = WORKSPACE_ROOT / ".cache"
OUTPUTS_DIR = WORKSPACE_ROOT / "outputs"
DEFAULT_FSCS = OUTPUTS_DIR / "FSCS.txt"
DEFAULT_DIFF = OUTPUTS_DIR / "diff_report.txt"
DEFAULT_EXPORT = OUTPUTS_DIR / "doors_export.json"
DEFAULT_MAPPING = CACHE_DIR / "doors_mapping.yaml"
DEFAULT_VALUES = CACHE_DIR / "DiagComm_values.json"
DEFAULT_UPLOAD = OUTPUTS_DIR / "doors_upload.xlsx"
DEFAULT_REPORT = OUTPUTS_DIR / "doors_payload_report.txt"


# -- yaml / json loaders --------------------------------------------------- #


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError:
        raise SystemExit(
            f"PyYAML missing. Run: python -m pip install -r "
            f"{(SKILL_ROOT / 'scripts' / 'requirements.txt').as_posix()}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8-sig"))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


# v2 input pair (since 1.13.0 split): the user-edited file is
# DiagComm_values.json and the rarely-touched sibling is
# DiagComm_config.json. The DOORS step only needs `paths` (for
# `_collect_realizing_arxmls`) so this helper merges the two
# whenever something asks for the values dict, falling back
# silently when the sibling is absent (build still works as long
# as the values file alone names a `paths` block).
_V2_CONFIG_FILENAME = "DiagComm_config.json"


def _load_values_with_config(values_path: Path) -> Dict[str, Any]:
    """Load ``values_path`` and shallow-merge in the sibling
    ``DiagComm_config.json``'s ``paths`` and ``options`` blocks (only
    when not already present in the values file). Returns the merged
    in-memory dict; never mutates either file.
    """
    cfg = _load_json(values_path)
    if not isinstance(cfg, dict):
        return cfg
    sibling = values_path.parent / _V2_CONFIG_FILENAME
    if sibling.exists():
        try:
            sib = _load_json(sibling)
        except Exception:  # noqa: BLE001
            sib = None
        if isinstance(sib, dict):
            for key in ("paths", "options"):
                if key in sib and key not in cfg:
                    cfg[key] = sib[key]
    return cfg


# -- DiagComm stack helpers ------------------------------------------------ #


def _collect_realizing_arxmls(
    paths_block: Dict[str, Any],
    product_type: Any,
    can_channel: Any,
) -> List[str]:
    """Pull every arxml basename from `inputs/DiagComm_values.json::paths`.

    Each value in `paths` is either a container path (no `.arxml`) or a
    relative arxml location possibly templated with `{product_type}` and
    `{can_channel}`. We keep only the templated arxml leaves, expand the
    placeholders, take the basename, and de-dupe while preserving the
    insertion order of the dict.
    """
    out: List[str] = []
    seen: set = set()
    fmt_args = {
        "product_type": str(product_type),
        "can_channel": str(can_channel),
    }
    for raw_value in paths_block.values():
        if not isinstance(raw_value, str):
            continue
        if not raw_value.lower().endswith(".arxml"):
            continue
        try:
            expanded = raw_value.format(**fmt_args)
        except KeyError:
            expanded = raw_value
        basename = expanded.replace("\\", "/").rsplit("/", 1)[-1]
        if basename and basename not in seen:
            seen.add(basename)
            out.append(basename)
    return out


# -- FSCS parsing ---------------------------------------------------------- #


_FSCS_KV = re.compile(r"^([^#:][\w\.\-]*?)\s*:\s*(.*?)\s*$")


def parse_fscs(fscs_path: Path) -> Tuple[str, Dict[str, str]]:
    full_text = fscs_path.read_text(encoding="utf-8-sig")
    fields: Dict[str, str] = {}
    for raw_line in full_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _FSCS_KV.match(raw_line)
        if not m:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key:
            fields[key] = val
    return full_text, fields


# -- diff_report.txt parsing ---------------------------------------------- #


_DIFF_LINE = re.compile(
    r"^\s+(?P<path>[^\s].+?\.arxml)\s+::\s+(?P<param>\S+)\s+\[(?P<elem>[^\]]+)\]\s+'(?P<old>[^']*)'\s+->\s+'(?P<new>[^']*)'"
)


def parse_diff_report(diff_path: Path) -> Dict[str, List[Dict[str, str]]]:
    by_arxml: Dict[str, List[Dict[str, str]]] = {}
    for line in diff_path.read_text(encoding="utf-8-sig").splitlines():
        m = _DIFF_LINE.match(line)
        if not m:
            continue
        full = m.group("path").replace("\\", "/")
        basename = full.rsplit("/", 1)[-1]
        by_arxml.setdefault(basename, []).append({
            "path": full,
            "param": m.group("param"),
            "elem": m.group("elem"),
            "old": m.group("old"),
            "new": m.group("new"),
        })
    return by_arxml


# -- delta / hybrid Object Text builders ---------------------------------- #


_DELTA_SEP_WIDTH = 62  # matches old `===` banner width so existing
                       # downstream consumers that line-wrap on 62 cols
                       # don't reflow when we switch to thin rules.
_DELTA_LABEL_FALLBACK = 26  # used only when the delta has no parsable
                            # entries; otherwise the label width is
                            # sized to the actual params in this run
                            # so the block lines up with the FSCS body
                            # rendered above it (see reports.py since
                            # 1.16.0 for the matching dynamic-width
                            # FSCS layout).


def _build_delta_text(
    by_arxml: Dict[str, List[Dict[str, str]]],
    project_name: str,
    product_type: str,
    timestamp: str,
) -> str:
    """Render the compact ``params_changed`` delta block.

    Layout (since 1.16.0; matches the three-line FSCS header + dynamic
    label/value column widths, so the cell flows visually as one
    continuous report):

        --------------------------------------------------------------
        # Update <ts>
        # parameters changed  (<project> / <product>)
        --------------------------------------------------------------
        <param>                  : <old> -> <new>
        <param>                  :
          [<arxml>] <old> -> <new>             (only when same param has
          [<arxml>] <old> -> <new>              divergent old/new tuples)
        ...

    No heavy ``===`` banners, no "Refreshed FSCS" replay, no per-file
    section: the goal is to keep the appended block roughly the size of
    the underlying change rather than drowning it in formatting.

    If there are zero parsable diff lines we still emit the header so
    the cell isn't visually misleading, plus a single explanatory line.
    """
    sep = "-" * _DELTA_SEP_WIDTH
    lines: List[str] = [
        sep,
        f"# Update {timestamp}",
        f"# parameters changed  ({project_name} / {product_type})",
        sep,
    ]

    if not by_arxml:
        lines.append("(no parsed diff entries -- last apply may have been a no-op)")
        return "\n".join(lines)

    by_param: Dict[str, List[Tuple[str, str, str]]] = {}
    for arxml, entries in by_arxml.items():
        for e in entries:
            by_param.setdefault(e["param"], []).append((arxml, e["old"], e["new"]))

    label_w = max(
        (len(param) for param in by_param),
        default=_DELTA_LABEL_FALLBACK,
    )

    for param in sorted(by_param):
        bumps = by_param[param]
        unique = {(o, n) for _, o, n in bumps}
        if len(unique) == 1:
            _, old, new = bumps[0]
            lines.append(f"{param:<{label_w}} : {old} -> {new}")
        else:
            lines.append(f"{param:<{label_w}} :")
            for arxml, old, new in bumps:
                lines.append(f"  [{arxml}] {old} -> {new}")
    return "\n".join(lines)


def _build_hybrid_text(full_fscs: str, delta_block: str) -> str:
    """Concatenate full FSCS + blank line + delta block.

    full_fscs is preserved verbatim (including any trailing newline). We
    add exactly one blank line between sections so the separator stays
    visually distinct.

    .. deprecated:: v6
        The mapping yaml should bind `Object Text` to `row.object_text`
        (which `_build_object_text_for_kind` populates correctly for
        every change_kind). This helper is kept only for backward-compat
        with mappings that still reference `extras.fscs_hybrid_text`.
    """
    sep = "\n\n" if not full_fscs.endswith("\n\n") else ""
    return full_fscs + sep + delta_block


# -- Object Text composition (since 1.15.0) -------------------------------- #
#
# Rules:
#
#   * insert kinds (first_insert / params_and_pp_changed)
#       → cell starts fresh = current FSCS verbatim. Both returned
#         strings (final, appended) equal full_fscs.
#
#   * parameters unchanged (pp_only_changed / fscs_only_changed)
#       → REPLACE the cell with the current FSCS. No append block, no
#         carry-over of prev_object_text. The user's request from
#         1.15.0 was "parameters 没变就别新起追加内容，直接在原本的内容
#         中改"; replace-with-current is the simplest realisation of
#         that. RB_Product / RB_Realizing_SWitem still grow as unions
#         (those cells are governed elsewhere) so multi-mapping
#         coverage is still discoverable from the row.
#
#   * params_changed
#       → APPEND a thin delta block on top of prev_object_text. The
#         block lists *only* the parameter old→new pairs (no full FSCS
#         replay) so the cell grows by roughly the size of the change
#         rather than doubling each time.
#
#   * no_change (only emitted with --force-no-skip)
#       → APPEND a single-line marker.
#
# Only `params_changed` and `no_change` produce a "block" distinct from
# the full cell content. For every other kind, `appended_block` equals
# `final_object_text` (kept this way so the report logging in
# build_payload still prints meaningful lengths).


def _build_no_change_block(timestamp: str) -> str:
    """Single-line marker emitted with --force-no-skip on otherwise
    semantically-unchanged runs. Designed to be unobtrusive: appended
    on top of whatever the cell already holds, just enough to leave a
    timestamped paper trail."""
    return f"# Update {timestamp}  -  re-uploaded (no semantic change)"


# Separator used when joining accumulated `covered_projects` /
# `covered_products` into the Object Text header. Single space + slash
# + space matches the rest of the FSCS body's "/" style (e.g.
# ``CAN_DLC.rx_frame_type``) and keeps the line readable in DOORS even
# when the row has picked up several mappings.
_HEADER_UNION_SEPARATOR = " / "


def _rewrite_object_text_header(
    full_fscs: str,
    projects: List[str],
    products: List[str],
) -> str:
    """Return ``full_fscs`` with its 4-line ``#`` header rewritten so
    the project / product lines reflect the DOORS row's accumulated
    coverage instead of just the current run.

    A row that started as ``(MyProject, ESP)`` and later picked up
    ``IPB`` without parameter changes (``pp_only_changed``) renders
    its Object Text as::

        # DiagComm FSCS
        # MyProject
        # ESP / IPB
        # 2026-05-07 14:40:00

        CAN_Channel               :       0
        ...

    `FSCS.txt` itself stays single-project/single-product (it is a
    current-apply snapshot, not the row's history); the union view is
    a DOORS-side Object Text concern only, so this rewrite happens
    inside the payload builder and never touches ``outputs/FSCS.txt``.

    The body (everything from the first non-``#`` line on) is
    preserved verbatim. If ``full_fscs`` doesn't have the expected
    4-line header (e.g. an older 1.16.0 three-line snapshot, or a
    legacy 1.15.0 one-liner) it's returned unchanged so the cell
    still shows *something* meaningful while the upstream FSCS
    catches up.
    """
    if not full_fscs:
        return full_fscs

    lines = full_fscs.split("\n")
    header_end = 0
    for ln in lines:
        if ln.startswith("#"):
            header_end += 1
        else:
            break

    # Need at least: marker (line 0) / project (1) / product (2) /
    # timestamp (3). If the on-disk FSCS is older than 1.16.1, leave
    # the cell alone -- we'd rather show stale content than mangle
    # something we can't parse.
    if header_end < 4:
        return full_fscs

    project_str = _HEADER_UNION_SEPARATOR.join(p for p in projects if p)
    product_str = _HEADER_UNION_SEPARATOR.join(p for p in products if p)

    new_header = [
        lines[0],
        f"# {project_str}" if project_str else lines[1],
        f"# {product_str}" if product_str else lines[2],
        *lines[3:header_end],
    ]
    return "\n".join(new_header + lines[header_end:])


def _join_with_blank_line(prev: Optional[str], block: str) -> str:
    """Concatenate `prev` and `block` with exactly one blank line in
    between. Returns `block` verbatim when `prev` is None / empty.
    """
    if not prev:
        return block
    return prev.rstrip("\n") + "\n\n" + block


def _build_object_text_for_kind(
    *,
    change_kind: str,
    full_fscs: str,
    delta_block: str,
    project_name: str,  # noqa: ARG001 -- kept for API stability
    product_type: str,  # noqa: ARG001 -- kept for API stability
    timestamp: str,
    prev_object_text: Optional[str],
) -> Tuple[str, str]:
    """Produce (final_object_text, appended_block).

    See module-level "Object Text composition" comment for the full
    rule table. The `project_name` / `product_type` arguments are no
    longer consumed (they used to feed banner lines that have been
    removed) but are retained in the signature so existing callers
    don't break.
    """
    if change_kind in (doors_state.CHANGE_KIND_FIRST_INSERT,
                       doors_state.CHANGE_KIND_PARAMS_AND_PP):
        return full_fscs, full_fscs

    if change_kind in (doors_state.CHANGE_KIND_PP_ONLY,
                       doors_state.CHANGE_KIND_FSCS_ONLY):
        # parameters didn't change -> REPLACE with current FSCS; do not
        # carry prev_object_text forward and do not emit a banner.
        return full_fscs, full_fscs

    if change_kind == doors_state.CHANGE_KIND_PARAMS:
        block = delta_block.rstrip("\n")
        return _join_with_blank_line(prev_object_text, block), block

    if change_kind == doors_state.CHANGE_KIND_NONE:
        block = _build_no_change_block(timestamp)
        return _join_with_blank_line(prev_object_text, block), block

    raise ValueError(f"unknown change_kind: {change_kind!r}")


# -- v6 RB_Product / RB_Realizing_SWitem cell builders -------------------- #


def _apply_rb_product_map(
    products: Iterable[str],
    value_maps: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Apply value_maps['RB_Product'] (if present) to each product in
    order. Falls back to the raw value with a stderr warning when no
    entry exists; drops empty / None entries.
    """
    table = (value_maps or {}).get("RB_Product") or {}
    out: List[str] = []
    for p in products:
        if p is None or p == "":
            continue
        key = str(p)
        if key in table:
            out.append(str(table[key]))
        else:
            sys.stderr.write(
                f"[build_doors_payload] WARN: value_maps.RB_Product has no entry "
                f"for product_type={key!r}; using the raw value. Add it to "
                "inputs/doors_mapping.yaml.\n"
            )
            out.append(key)
    return out


# -- anchor finder -------------------------------------------------------- #


def find_anchor(
    rows: List[Dict[str, Any]],
    anchor_cfg: Dict[str, Any],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Find the DOORS anchor row.

    Tries, in order:
        1. by_identifier  (exact match on row.identifier)
        2. by_heading     (exact match on row[heading_field])
        3. by_absolute_number (exact match on row.AbsoluteNumber, str-coerced)

    Returns (row_dict_or_None, human_readable_match_reason).
    """
    by_id = anchor_cfg.get("by_identifier")
    if by_id:
        for r in rows:
            if r.get("identifier") == by_id:
                return r, f"identifier=={by_id!r}"

    by_heading = anchor_cfg.get("by_heading")
    heading_field = anchor_cfg.get("heading_field", "DescriptionOfRequirementRB")
    if by_heading:
        for r in rows:
            if r.get(heading_field) == by_heading:
                return r, f"{heading_field}=={by_heading!r}"

    by_abs = anchor_cfg.get("by_absolute_number")
    if by_abs is not None:
        target = str(by_abs)
        for r in rows:
            if str(r.get("AbsoluteNumber") or "") == target:
                return r, f"AbsoluteNumber=={target!r}"

    return None, "no rule matched"


# -- doors_helper bridge --------------------------------------------------- #


def _show_target_inproc(mapping_path: Path) -> Tuple[int, str, str]:
    """Run doors_helper.cmd_show_target without spawning a subprocess.

    Returns (returncode, stdout-equivalent, stderr-equivalent).
    """
    import io
    import argparse as _argparse
    from contextlib import redirect_stdout, redirect_stderr

    from doors_helper import cmd_show_target

    args = _argparse.Namespace(mapping=str(mapping_path), out=None)
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        rc = cmd_show_target(args)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def _lint_excel_inproc(xlsx_path: Path) -> Tuple[int, str, str]:
    """Run the generic xlsx lint without spawning a subprocess."""
    from excel_io import lint_workbook

    issues = lint_workbook(xlsx_path)
    if not issues:
        return 0, f"[doors] lint-excel: {xlsx_path} OK\n", ""
    fatal = any("not found" in line or "could not load" in line for line in issues)
    return (2 if fatal else 1), "", "\n".join(f"[doors][WARN] lint: {ln}" for ln in issues) + "\n"


# -- column resolution ---------------------------------------------------- #


def _resolve_source(
    source: str,
    extras: Dict[str, str],
    row_ctx: Dict[str, Any],
    value_maps: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Any:
    if source.startswith("literal:"):
        return _expand_placeholders(source[len("literal:"):], extras, row_ctx)
    if source.startswith("extras."):
        key = source[len("extras."):]
        if key not in extras:
            raise KeyError(f"extras.{key} not provided")
        return extras[key]
    if source.startswith("row."):
        key = source[len("row."):]
        if key not in row_ctx:
            raise KeyError(f"row.{key} not provided in row_ctx")
        return row_ctx[key]
    if source.startswith("map:"):
        body = source[len("map:"):]
        if ":" not in body:
            raise KeyError(
                f"map: source must be of the form 'map:<map_name>:<inner_source>', got {source!r}"
            )
        map_name, inner = body.split(":", 1)
        map_name = map_name.strip()
        inner = inner.strip()
        if not value_maps or map_name not in value_maps:
            raise KeyError(
                f"map source {source!r} but no value_maps.{map_name} block in mapping yaml"
            )
        raw = _resolve_source(inner, extras, row_ctx, value_maps)
        raw_key = str(raw)
        table = value_maps[map_name]
        if raw_key not in table:
            allowed = sorted(str(k) for k in table)
            raise KeyError(
                f"value_maps.{map_name} has no entry for {raw_key!r} "
                f"(known keys: {allowed}); add it to inputs/doors_mapping.yaml"
            )
        return table[raw_key]
    raise KeyError(f"unsupported source prefix: {source!r}")


_PLACEHOLDER = re.compile(r"(extras\.\w+|row\.\w+)")


def _expand_placeholders(
    text: str,
    extras: Dict[str, str],
    row_ctx: Dict[str, Any],
) -> str:
    def repl(m: re.Match) -> str:
        token = m.group(0)
        try:
            return str(_resolve_source(token, extras, row_ctx))
        except KeyError:
            return token
    return _PLACEHOLDER.sub(repl, text)


# -- workbook writer ------------------------------------------------------ #


def _read_template_columns(
    template_path: Path,
    sheet_name: str,
    header_row: int,
) -> List[str]:
    """Pull the ordered column header list from the user-owned template.

    The template is consulted only for column order/membership; we never
    write back into it. Output is produced from scratch with xlsxwriter
    (see write_workbook).
    """
    try:
        import openpyxl
    except ImportError:
        raise SystemExit(
            f"openpyxl missing. Run: python -m pip install -r "
            f"{(SKILL_ROOT / 'scripts' / 'requirements.txt').as_posix()}"
        )

    wb = openpyxl.load_workbook(template_path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise KeyError(
            f"sheet {sheet_name!r} not in template; available: {wb.sheetnames}"
        )
    ws = wb[sheet_name]

    columns: List[str] = []
    for row in ws.iter_rows(
        min_row=header_row, max_row=header_row, values_only=True,
    ):
        for v in row:
            if v is None:
                continue
            label = str(v).strip()
            if label:
                columns.append(label)
        break
    wb.close()

    if not columns:
        raise ValueError(
            f"no column headers found at row {header_row} of sheet {sheet_name!r}"
        )
    return columns


def write_workbook(
    template_path: Path,
    sheet_name: str,
    header_row: int,
    data_start: int,
    size_row: int,
    rows_data: List[Dict[str, Any]],
    out_path: Path,
) -> Tuple[int, List[str]]:
    """Write the upload xlsx in DOORS-native format using xlsxwriter.

    Why xlsxwriter (not openpyxl):
        DOORS' module-import service rejects xlsx files whose
        `docProps/app.xml` lists an `Application` other than
        "Microsoft Excel" (e.g. "Openpyxl 3.1.5"). xlsxwriter writes
        Microsoft-Excel-compatible xlsx with a sharedStrings part, which
        DOORS accepts. The template is still consulted for the canonical
        column order, but never written back into.

    Layout (1-indexed rows):
        size_row       sizeRow / N(str) / sizeColumn / M(str)
        header_row     col1 .. colM
        data_start..   one row per entry in rows_data
    """
    try:
        import xlsxwriter
    except ImportError:
        raise SystemExit(
            f"xlsxwriter missing. Run: python -m pip install -r "
            f"{(SKILL_ROOT / 'scripts' / 'requirements.txt').as_posix()}"
        )

    warnings: List[str] = []
    columns = _read_template_columns(template_path, sheet_name, header_row)
    known = set(columns)

    for offset, row_data in enumerate(rows_data):
        target_row = data_start + offset
        for header_name in row_data:
            if header_name not in known:
                warnings.append(
                    f"row {target_row}: column header {header_name!r} not in template (skipped)"
                )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(out_path))
    worksheet = workbook.add_worksheet(sheet_name)

    total_rows = (data_start - 1) + len(rows_data)
    total_cols = len(columns)

    sr0 = size_row - 1
    worksheet.write(sr0, 0, "sizeRow")
    worksheet.write(sr0, 1, str(total_rows))
    worksheet.write(sr0, 2, "sizeColumn")
    worksheet.write(sr0, 3, str(total_cols))

    hr0 = header_row - 1
    for ci, header_name in enumerate(columns):
        worksheet.write(hr0, ci, header_name)

    ds0 = data_start - 1
    for ri, row_data in enumerate(rows_data):
        for ci, header_name in enumerate(columns):
            value = row_data.get(header_name, "")
            if value is None or value == "":
                worksheet.write_blank(ds0 + ri, ci, None)
            else:
                worksheet.write(ds0 + ri, ci, value)

    workbook.close()
    return len(rows_data), warnings


# -- main builder --------------------------------------------------------- #


def build_payload(
    fscs_path: Path,
    diff_path: Path,
    export_path: Path,
    mapping_path: Path,
    values_path: Path,
    upload_out: Path,
    report_out: Path,
    cli_mode: Optional[str],
    cli_updates: Dict[str, str],
    *,
    existing_state: Optional[Dict[str, Any]] = None,
    change_kind: Optional[str] = None,
    cli_target_abs: Optional[str] = None,
) -> int:
    """Build the DOORS upload xlsx + payload report.

    `existing_state` is the state.modules[<uuid>] entry (v3 schema)
    when called from `doors_sync.py`; None otherwise. When provided in
    update mode, the row's RB_Product / RB_Realizing_SWitem cells are
    grown by union with the recorded `covered_*` lists and Object Text
    is appended (rather than replaced) on top of `last_object_text`.

    `change_kind` selects the Object Text append template (see
    `_build_object_text_for_kind`). When None, defaults to the
    "first_insert" template for `cli_mode=insert` and "params_changed"
    for `cli_mode=update` (best-effort fallback for hand-driven
    callers that bypass `doors_sync.py`).

    `cli_target_abs` provides the AbsoluteNumber for `single_row +
    update` runs in which `by_arxml` may legitimately be empty (only
    project/product changed). Overrides the per-arxml lookup in
    `cli_updates` when set.
    """
    report_lines: List[str] = []
    report_lines.append("# diagcomm-toolkit -> DOORS payload report (v6)")
    report_lines.append(f"# generated : {datetime.now():%Y-%m-%d %H:%M:%S}")
    report_lines.append("")

    def _bail(msg_lines: List[str], code: int = 2) -> int:
        # Mirror the bail message to stderr too -- previously _bail only
        # wrote to the on-disk report file, which made cold-start failures
        # (e.g. missing FSCS / diff / export on a fresh checkout) silently
        # return rc=2 to the caller. Writing to stderr keeps the log file
        # behaviour while making the failure visible in the terminal.
        for line in msg_lines:
            print(f"[build_doors_payload] {line}", file=sys.stderr)
        report_lines.extend(msg_lines)
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        return code

    if not mapping_path.exists():
        return _bail([f"ERROR: mapping yaml missing: {mapping_path}"])

    rc, stdout, stderr = _show_target_inproc(mapping_path)
    report_lines.append("[show-target]")
    if stdout.strip():
        report_lines.append(stdout.strip())
    if stderr.strip():
        report_lines.append(stderr.strip())
    if rc == 2:
        return _bail(["ERROR: doors block missing/invalid. Stopping."])
    if rc == 1:
        return _bail([
            "ERROR: doors_mapping.yaml still has the placeholder UUID.",
            "  Fill in `doors.document_uuid`, then re-run.",
        ])
    report_lines.append("")

    if not fscs_path.exists():
        return _bail([
            f"ERROR: FSCS file missing: {fscs_path}",
            f"  Run `python {HERE / 'pipeline.py'} apply --apply` first.",
        ])
    if not diff_path.exists():
        return _bail([
            f"ERROR: diff_report missing: {diff_path}",
            f"  Run `python {HERE / 'pipeline.py'} apply --apply` first.",
        ])
    if not export_path.exists():
        return _bail([
            f"ERROR: DOORS export missing: {export_path}",
            "  Agent should call `get_doors_module` MCP tool first and save",
            "  the response to that path. See SKILL.md Step 7.5/8a.",
        ])

    mapping = _load_yaml(mapping_path)
    if not isinstance(mapping, dict):
        return _bail(["ERROR: mapping yaml must have a top-level mapping."])

    template_block = mapping.get("template") or {}
    template_path_raw = template_block.get("path", "assets/doors_template.xlsx")
    template_path = (SKILL_ROOT / template_path_raw).resolve()
    sheet_name = template_block.get("sheet", "CS Data")
    header_row = int(template_block.get("header_row", 2))
    data_start = int(template_block.get("data_start", 3))
    size_row = int(template_block.get("size_row", 1))

    if not template_path.exists():
        return _bail([
            f"ERROR: Excel template missing: {template_path}",
            "  assets/doors_template.xlsx ships with the skill; if it is",
            "  missing the install is incomplete -- restore it from git",
            "  (`git checkout -- assets/doors_template.xlsx`). Never ask",
            "  the user to hand-edit the template.",
        ])

    strategy = mapping.get("strategy", "per_arxml")
    if strategy not in ("per_arxml", "single_row"):
        return _bail([f"ERROR: unsupported strategy: {strategy!r}"])

    mode = (cli_mode or mapping.get("mode") or "insert").lower()
    if mode not in ("insert", "update"):
        return _bail([f"ERROR: unsupported mode: {mode!r}  (expected insert|update)"])

    # Default change_kind when caller didn't classify (rare; doors_sync.py
    # always provides one). The fallback keeps hand-driven CLI runs
    # behaving the way they did pre-v6 -- insert seeds a fresh row,
    # update appends a "params_changed" block.
    if not change_kind:
        change_kind = (
            doors_state.CHANGE_KIND_FIRST_INSERT
            if mode == "insert"
            else doors_state.CHANGE_KIND_PARAMS
        )

    updates_cfg: Dict[str, Any] = mapping.get("updates") or {}
    updates: Dict[str, str] = {k: str(v) for k, v in updates_cfg.items()}
    updates.update(cli_updates)

    defaults: Dict[str, Any] = mapping.get("defaults") or {}
    columns_block: Dict[str, str] = mapping.get("columns") or {}
    value_maps: Dict[str, Dict[str, Any]] = mapping.get("value_maps") or {}

    full_fscs_text, fscs_fields = parse_fscs(fscs_path)
    by_arxml = parse_diff_report(diff_path)

    # An empty diff is OK in update mode + single_row strategy when the
    # change is purely about (project, product) -- the Object Text
    # appended block describes the change instead. In every other case
    # an empty diff is a bug (apply was a no-op).
    allow_empty_diff = (
        mode == "update"
        and strategy == "single_row"
        and change_kind in (
            doors_state.CHANGE_KIND_PP_ONLY,
            doors_state.CHANGE_KIND_NONE,
        )
    )
    if not by_arxml and not allow_empty_diff:
        return _bail([
            "ERROR: diff_report has no parseable change lines.",
            "  Was the last apply a no-op? Re-run `pipeline.py apply --apply`.",
        ])

    overall_rc = 0
    anchor_id: str = ""
    anchor_abs: str = ""

    if mode == "insert":
        export = _load_json(export_path)
        export_data = export.get("data", export) if isinstance(export, dict) else export
        rows = export_data.get("rows", []) if isinstance(export_data, dict) else []
        if not rows:
            return _bail([
                "ERROR: doors_export.json has no `rows` array.",
                "  Re-run `get_doors_module` MCP tool to refresh the export.",
            ])
        anchor_cfg = mapping.get("anchor") or {}
        if not anchor_cfg:
            return _bail([
                "ERROR: insert mode requires an `anchor:` block in doors_mapping.yaml.",
            ])
        anchor_row, reason = find_anchor(rows, anchor_cfg)
        if anchor_row is None:
            return _bail([
                f"ERROR: anchor not found in doors_export.json ({reason}).",
                "  Either:",
                "    (a) the heading text in `anchor.by_heading` does not match any row,",
                "        re-check it against the live DOORS module, or",
                "    (b) switch to `mode: update` and supply explicit AbsoluteNumbers.",
            ])
        anchor_id = str(anchor_row.get("identifier") or "")
        anchor_abs = str(anchor_row.get("AbsoluteNumber") or "")
        report_lines.append("[anchor]")
        report_lines.append(f"  rule         : {reason}")
        report_lines.append(f"  identifier   : {anchor_id}")
        report_lines.append(f"  AbsoluteNumber: {anchor_abs}")
        report_lines.append("")

    elif mode == "update":
        if not by_arxml and not cli_target_abs and not updates:
            return _bail([
                "ERROR: update mode requires an AbsoluteNumber to overwrite.",
                "  Either pass --cli-target-abs (orchestrator path), fill",
                "  `updates:` in doors_mapping.yaml, or pass `--update-abs",
                "  <arxml>=<n>` on the CLI.",
            ])
        if by_arxml and not cli_target_abs and not updates:
            return _bail([
                "ERROR: update mode requires per-arxml AbsoluteNumbers.",
                "  Either fill `updates:` in doors_mapping.yaml, or pass",
                "  `--update-abs <arxml>=<n>` flags on the CLI (one per arxml).",
            ])
        if not cli_target_abs:
            missing = [a for a in by_arxml if a not in updates]
            if missing:
                return _bail([
                    "ERROR: update mode but some arxml in the diff have no",
                    "  `updates` entry:",
                    *(f"    - {a}" for a in missing),
                    "  Add them to `updates:` or pass via --update-abs.",
                ])
        report_lines.append("[updates]")
        if cli_target_abs:
            report_lines.append(f"  cli_target_abs (single_row): {cli_target_abs}")
        for a, n in updates.items():
            report_lines.append(f"  {a:50s} -> AbsoluteNumber={n}")
        report_lines.append("")

    project_name = "(unknown)"
    product_type = "(unknown)"
    can_channel: Any = 0
    paths_block: Dict[str, Any] = {}
    if values_path.exists():
        try:
            cfg = _load_values_with_config(values_path)
            # v2 shape (preferred): {project: {name, product_type}, parameters: {...}, paths: {...}}
            project_block = cfg.get("project") if isinstance(cfg, dict) else None
            parameters_block = cfg.get("parameters") if isinstance(cfg, dict) else None
            if isinstance(project_block, dict):
                if isinstance(project_block.get("name"), str):
                    project_name = project_block["name"]
                if isinstance(project_block.get("product_type"), str):
                    product_type = project_block["product_type"]
            if isinstance(parameters_block, dict):
                can_channel = parameters_block.get("CAN_Channel", can_channel)
            # v1 fallback (will disappear once everyone is on v2): top-level
            # project_name + values block carrying product_type + CAN_Channel.
            if project_name == "(unknown)" and isinstance(cfg.get("project_name"), str):
                project_name = cfg["project_name"]
            legacy_values = cfg.get("values") if isinstance(cfg, dict) else None
            if isinstance(legacy_values, dict):
                if product_type == "(unknown)" and isinstance(legacy_values.get("product_type"), str):
                    product_type = legacy_values["product_type"]
                if can_channel == 0 and "CAN_Channel" in legacy_values:
                    can_channel = legacy_values["CAN_Channel"]
            paths_block = cfg.get("paths", {}) or {}
        except Exception as exc:
            report_lines.append(f"WARN: could not read values json: {exc}")

    realizing_arxmls = _collect_realizing_arxmls(
        paths_block, product_type, can_channel,
    )

    # ---------------------------------------------------------------- #
    # v6: pull accumulated context out of state (None for insert / for
    # hand-driven CLI runs without a state hook). For inserts we ignore
    # state entirely so the row starts fresh; for updates we union with
    # the recorded `covered_*` lists.
    # ---------------------------------------------------------------- #
    if mode == "insert" or existing_state is None:
        prior_projects: List[str] = []
        prior_products: List[str] = []
        prior_arxml_paths: List[str] = []
        prior_object_text: Optional[str] = None
    else:
        prior_projects = list(existing_state.get("covered_projects") or [])
        prior_products = list(existing_state.get("covered_products") or [])
        prior_arxml_paths = list(existing_state.get("covered_arxml_paths") or [])
        prior_object_text = existing_state.get("last_object_text")

    final_projects = doors_state.union_preserve_order(
        prior_projects, [project_name] if project_name else [],
    )
    final_products = doors_state.union_preserve_order(
        prior_products, [product_type] if product_type else [],
    )
    final_realizing = doors_state.union_preserve_order(
        prior_arxml_paths, realizing_arxmls,
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    delta_block = _build_delta_text(by_arxml, project_name, product_type, generated_at)
    hybrid_text = _build_hybrid_text(full_fscs_text, delta_block)  # legacy alias

    # Object Text uses an FSCS variant whose header reflects the row's
    # accumulated (project, product) coverage. FSCS.txt itself is the
    # single-project/single-product snapshot of the *current* apply
    # (extras.fscs_full_text and extras.fscs_hybrid_text bind to the
    # original text); only the cell content seen by DOORS gets the
    # union view. For first_insert / params_and_pp_changed the unions
    # collapse to the single current value, so the rewrite is a no-op.
    fscs_for_object_text = _rewrite_object_text_header(
        full_fscs_text, final_projects, final_products,
    )

    final_object_text, appended_block = _build_object_text_for_kind(
        change_kind=change_kind,
        full_fscs=fscs_for_object_text,
        delta_block=delta_block,
        project_name=project_name,
        product_type=product_type,
        timestamp=generated_at,
        prev_object_text=prior_object_text,
    )

    rb_product_items = _apply_rb_product_map(final_products, value_maps)
    rb_product_value = MULTIVALUE_SEPARATOR.join(rb_product_items)
    rb_realizing_value = MULTIVALUE_SEPARATOR.join(final_realizing)

    extras: Dict[str, str] = {
        "project_name": project_name,
        "product_type": product_type,
        "generated_at": generated_at,
        "fscs_full_text": full_fscs_text,
        "fscs_delta_text": delta_block,
        "fscs_hybrid_text": hybrid_text,        # deprecated; kept for back-compat
        "realizing_arxmls": MULTIVALUE_SEPARATOR.join(realizing_arxmls),  # CURRENT run only
        "rb_product_value": rb_product_value,    # v6: cell-ready, mapped + joined union
        "rb_realizing_value": rb_realizing_value,  # v6: cell-ready, joined union
        "appended_block": appended_block,        # v6: just the new block (debug / report)
        "change_kind": change_kind,
    }
    for k, v in fscs_fields.items():
        extras[f"fscs_field_{re.sub(r'[^A-Za-z0-9_]', '_', k)}"] = v

    report_lines.append(f"change_kind        : {change_kind}")
    if prior_projects or prior_products or prior_arxml_paths:
        report_lines.append("[state.covered_*]  (carried over from last upload)")
        report_lines.append(f"  projects     : {prior_projects}")
        report_lines.append(f"  products     : {prior_products}")
        report_lines.append(f"  arxml paths  : {len(prior_arxml_paths)}")
    report_lines.append("[final cells]  (after union with current run)")
    report_lines.append(f"  RB_Product (raw)    : {final_products}")
    report_lines.append(f"  RB_Product (mapped) : {rb_product_items}")
    report_lines.append(f"  RB_Realizing_SWitem : {len(final_realizing)} path(s)")
    for ax in final_realizing:
        report_lines.append(f"    - {ax}")
    # 1.15.0: insert kinds and parameters-unchanged updates REPLACE the
    # cell; only `params_changed` / `no_change` truly APPEND on top of
    # prev_object_text. We surface that explicitly so the report is
    # easier to skim than the bare lengths.
    _replace_kinds = {
        doors_state.CHANGE_KIND_FIRST_INSERT,
        doors_state.CHANGE_KIND_PARAMS_AND_PP,
        doors_state.CHANGE_KIND_PP_ONLY,
        doors_state.CHANGE_KIND_FSCS_ONLY,
    }
    _op = "REPLACE" if change_kind in _replace_kinds else "APPEND"
    report_lines.append(f"  Object Text op      : {_op}")
    report_lines.append(f"  Object Text len     : {len(final_object_text)} chars "
                        f"(prev: {len(prior_object_text or '')}, "
                        f"new block: {len(appended_block)})")
    report_lines.append("")

    report_lines.append(f"mode               : {mode}")
    report_lines.append(f"strategy           : {strategy}")
    report_lines.append(f"template           : {template_path}")
    report_lines.append(f"arxml in diff      : {len(by_arxml)}")
    for arxml, entries in by_arxml.items():
        distinct = sorted({e['param'] for e in entries})
        report_lines.append(f"  - {arxml:50s}  {len(entries):3d} hits / {len(distinct)} params")
    report_lines.append("")

    rows_data: List[Dict[str, Any]] = []

    arxmls_to_emit: List[str]
    if strategy == "per_arxml":
        arxmls_to_emit = list(by_arxml.keys())
    else:
        arxmls_to_emit = ["__single__"]

    for arxml in arxmls_to_emit:
        if strategy == "per_arxml":
            entries = by_arxml[arxml]
            distinct_params = sorted({e['param'] for e in entries})
            fscs_chunk_lines: List[str] = [
                f"{p}: {fscs_fields.get(p, '(not in FSCS.txt)')}"
                for p in distinct_params
            ]
            fscs_chunk = "\n".join(fscs_chunk_lines)
            diff_chunk = "\n".join(
                f"{e['param']} [{e['elem']}] {e['old']!r} -> {e['new']!r}"
                for e in entries
            )

            if mode == "insert":
                destination = anchor_abs
                absolute_no = ""
            else:
                destination = ""
                absolute_no = cli_target_abs or updates[arxml]

            row_ctx = {
                "arxml": arxml,
                "destination": destination,
                "absolute_no": absolute_no,
                "fscs_chunk": fscs_chunk,
                "diff_chunk": diff_chunk,
                "param_count": len(distinct_params),
                "object_text": final_object_text,
            }
        else:
            all_arxmls = MULTIVALUE_SEPARATOR.join(by_arxml.keys())
            if mode == "insert":
                destination = anchor_abs
                absolute_no = ""
            else:
                if cli_target_abs:
                    absolute_no = cli_target_abs
                else:
                    distinct_abs = {str(v).strip() for v in updates.values() if str(v).strip()}
                    if not distinct_abs:
                        return _bail([
                            "ERROR: single_row + update mode requires at least one "
                            "AbsoluteNumber in updates (all entries blank).",
                        ])
                    if len(distinct_abs) != 1:
                        return _bail([
                            "ERROR: single_row + update mode requires all updates entries "
                            "to point at the SAME AbsoluteNumber (because the strategy "
                            "merges every arxml into one row). Got distinct values: "
                            f"{sorted(distinct_abs)}",
                        ])
                    absolute_no = distinct_abs.pop()
                destination = ""
            row_ctx = {
                "arxml": all_arxmls,
                "destination": destination,
                "absolute_no": absolute_no,
                "fscs_chunk": full_fscs_text,
                "diff_chunk": (
                    diff_path.read_text(encoding="utf-8-sig")
                    if diff_path.exists() else ""
                ),
                "param_count": sum(len(v) for v in by_arxml.values()),
                "object_text": final_object_text,
            }

        row: Dict[str, Any] = {}
        for header_name, default_val in defaults.items():
            row[header_name] = default_val
        for header_name, source in columns_block.items():
            try:
                row[header_name] = _resolve_source(source, extras, row_ctx, value_maps)
            except KeyError as exc:
                return _bail([
                    f"ERROR: column {header_name!r} source {source!r}: {exc}",
                ])
        rows_data.append(row)

    n_written, warns = write_workbook(
        template_path, sheet_name, header_row, data_start, size_row,
        rows_data, upload_out,
    )
    report_lines.append("[write-workbook]")
    report_lines.append(f"  rows written : {n_written}")
    for w in warns:
        report_lines.append(f"  WARN: {w}")
        overall_rc = max(overall_rc, 1)
    report_lines.append("")

    rc, stdout, stderr = _lint_excel_inproc(upload_out)
    report_lines.append("[lint-excel]")
    if stdout.strip():
        report_lines.append(stdout.strip())
    if stderr.strip():
        report_lines.append(stderr.strip())
    if rc == 2:
        report_lines.append("ERROR: lint-excel rejected the file. Stopping.")
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        return 2
    if rc == 1:
        overall_rc = max(overall_rc, 1)
    report_lines.append("")

    report_lines.append("=" * 60)
    report_lines.append(f"OUTPUT  : {upload_out}")
    report_lines.append(f"EXIT    : {overall_rc}")
    report_lines.append(
        f"Next step: run `python {HERE / 'doors_upload.py'} <upload_out> "
        "<module_uuid> <user_nt> <password>` (see SKILL.md Step 8c)."
    )
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return overall_rc


# -- argparse plumbing ---------------------------------------------------- #


def _parse_kv_list(items: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for kv in items or []:
        if "=" not in kv:
            raise SystemExit(f"--update-abs entry must be key=value, got {kv!r}")
        k, v = kv.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="diagcomm-toolkit/build_doors_payload.py",
        description="Build the Excel payload that uploads FSCS into DOORS.",
    )
    p.add_argument("--fscs", default=str(DEFAULT_FSCS))
    p.add_argument("--diff", default=str(DEFAULT_DIFF))
    p.add_argument("--export", default=str(DEFAULT_EXPORT))
    p.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    p.add_argument("--values", default=str(DEFAULT_VALUES))
    p.add_argument("--upload-out", default=str(DEFAULT_UPLOAD))
    p.add_argument("--report-out", default=str(DEFAULT_REPORT))
    p.add_argument("--mode", choices=("insert", "update"), default=None,
                   help="override doors_mapping.yaml::mode")
    p.add_argument("--update-abs", action="append", default=[],
                   help="for `--mode update`: <arxml-basename>=<AbsoluteNumber>; repeat per arxml")
    p.add_argument(
        "--target-abs", default=None,
        help="for `single_row` + update: the single AbsoluteNumber to overwrite; "
             "lets the script handle empty diffs (pp_only_changed). The orchestrator "
             "scripts/doors_sync.py passes this automatically.",
    )
    p.add_argument(
        "--change-kind",
        choices=(
            doors_state.CHANGE_KIND_FIRST_INSERT,
            doors_state.CHANGE_KIND_PARAMS_AND_PP,
            doors_state.CHANGE_KIND_PARAMS,
            doors_state.CHANGE_KIND_PP_ONLY,
            doors_state.CHANGE_KIND_FSCS_ONLY,
            doors_state.CHANGE_KIND_NONE,
        ),
        default=None,
        help="select the Object Text append template; defaults to first_insert "
             "(insert) or params_changed (update). The orchestrator passes this "
             "automatically based on state classification.",
    )
    p.add_argument(
        "--state-file", default=None,
        help="optional path to state/doors_upload_state.json. When set AND the "
             "mapping yaml's document_uuid has an entry, the row is built with "
             "the recorded covered_*/last_object_text. Hand-driven CLI use only; "
             "scripts/doors_sync.py drives this automatically.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Auto-refresh .cache/ from inputs/DiagComm.xlsx when running against
    # the default cache paths (since 1.20.0). Skipped when the user pinned
    # --values / --mapping to a non-default location.
    try:
        if (Path(args.values).resolve() == DEFAULT_VALUES.resolve()
                and Path(args.mapping).resolve() == DEFAULT_MAPPING.resolve()):
            sys.path.insert(0, str(HERE))
            import excel_loader  # noqa: PLC0415  -- lazy: heavy openpyxl import
            excel_loader.load_or_refresh()
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"[build_doors_payload] WARN: cache refresh from "
            f"inputs/DiagComm.xlsx failed: {exc}; proceeding with stale "
            f".cache/ files (if any).\n"
        )

    existing_state: Optional[Dict[str, Any]] = None
    if args.state_file:
        state_path = Path(args.state_file)
        if state_path.exists():
            try:
                state_doc = doors_state.load_state(state_path)
                mapping_doc = _load_yaml(Path(args.mapping)) or {}
                uuid_str = str((mapping_doc.get("doors") or {}).get("document_uuid") or "").strip()
                if uuid_str:
                    existing_state = doors_state.get_module_entry(state_doc, uuid_str)
            except SystemExit:
                raise
            except Exception as exc:
                sys.stderr.write(
                    f"[build_doors_payload] WARN: could not read state file "
                    f"{state_path}: {exc}; proceeding without state context.\n"
                )

    return build_payload(
        fscs_path=Path(args.fscs),
        diff_path=Path(args.diff),
        export_path=Path(args.export),
        mapping_path=Path(args.mapping),
        values_path=Path(args.values),
        upload_out=Path(args.upload_out),
        report_out=Path(args.report_out),
        cli_mode=args.mode,
        cli_updates=_parse_kv_list(args.update_abs),
        existing_state=existing_state,
        change_kind=args.change_kind,
        cli_target_abs=args.target_abs,
    )


if __name__ == "__main__":
    raise SystemExit(main())
