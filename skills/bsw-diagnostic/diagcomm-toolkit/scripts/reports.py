"""Output / report generators for the diagcomm-toolkit pipeline.

Everything that turns runtime state into a human- or agent-readable
artifact lives here:

  * ``_build_schema_drift``          -- schema vs DiagComm.txt unified diff
  * ``_render_catalog_table`` / ``_inject_catalog``
                                     -- mapping.yaml -> reference/landing_spots.md
  * FSCS (``_render_fscs``, ``_write_fscs``, ...)
                                     -- outputs/FSCS.txt one-page summary
  * ``_read_current_value``          -- first locator hit's <VALUE> text;
                                        used by cmd_landing_report and by
                                        the lazy-seed reverse walk in
                                        ``pipeline._seed_values_from_arxml``
  * ``_ancestor_short_name_chain``   -- helper used by cmd_landing_report

Pure rendering logic -- no argparse. File I/O is limited to reading the
inputs needed to compute the report and writing the final artifact.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime import (
    OUTPUTS_DIR,
    SCHEMA_PATH,
    SKILL_ROOT,
    _rel_to_skill,
    load_json,
)

# ---------------------------------------------------------------------------
# Schema drift (gen-schema --check + status drift indicator)


def _build_schema_drift(txt_path: Path,
                        schema_path: Path) -> tuple[bool, str]:
    """Regenerate the schema in-memory from ``txt_path`` and compare to
    ``schema_path``. Returns ``(in_sync, diff_text)``.

    ``in_sync=True`` if on-disk JSON == regenerated JSON (byte-for-byte
    after canonical serialisation) OR the on-disk file does not exist
    (in which case there is nothing to drift *from* -- caller decides
    whether missing counts as drift). ``diff_text`` is a unified diff
    suitable for printing when drift is detected.
    """
    import difflib

    import schema as schema_mod
    regenerated = schema_mod.build_schema(txt_path)
    new_text = json.dumps(regenerated, indent=2, ensure_ascii=False) + "\n"
    if not schema_path.exists():
        return False, "<no on-disk schema to diff against>\n"
    old_text = schema_path.read_text(encoding="utf-8")
    if old_text == new_text:
        return True, ""
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"{schema_path.name} (on disk)",
        tofile=f"{schema_path.name} (regenerated from {txt_path.name})",
        n=3,
    )
    return False, "".join(diff)


# ---------------------------------------------------------------------------
# Catalog: PARAM_MAP -> markdown table in reference/landing_spots.md

CATALOG_FENCE_BEGIN = "<!-- auto:catalog-begin -->"
CATALOG_FENCE_END = "<!-- auto:catalog-end -->"
CATALOG_TARGET = SKILL_ROOT / "reference" / "landing_spots.md"


def _render_catalog_table(param_map: list[dict[str, Any]]) -> str:
    """Build a markdown table from ``PARAM_MAP`` entries.

    Output includes every field a reader needs to understand the mapping
    at a glance: user key, file alias, locator shape, transform, multi /
    optional / derived flags. Keeps locator compact by flattening the
    most-common keys to a single cell.
    """
    lines: list[str] = []
    lines.append(CATALOG_FENCE_BEGIN)
    lines.append("")
    lines.append("> Auto-generated from `<skill>/scripts/mapping.yaml`. "
                 "Do not edit by hand -- run "
                 "`python <skill>/scripts/pipeline.py export-catalog` to refresh.")
    lines.append("")
    lines.append(
        "| # | Param | File alias | Locator | Transform | multi | opt | derived |"
    )
    lines.append(
        "|---|-------|-----------|---------|-----------|:----:|:---:|:-------:|"
    )
    tick = "\u2713"  # ✓
    in_sym = "\u2208"  # ∈
    for i, entry in enumerate(param_map, start=1):
        loc = entry["locator"]
        loc_type = loc.get("type", "?")
        bits: list[str] = []
        def_suffix = loc.get("def_suffix")
        if isinstance(def_suffix, list):
            bits.append(f"def_suffix {in_sym} [{', '.join(def_suffix)}]")
        elif def_suffix is not None:
            bits.append(f"def_suffix={def_suffix}")
        for k in ("context_container_def_suffix", "ancestor_short_name",
                  "ancestor_short_name_prefix"):
            if k in loc:
                bits.append(f"{k}={loc[k]}")
        loc_cell = f"`{loc_type}`<br/>" + "<br/>".join(f"\u00b7 {b}" for b in bits)
        multi_m = tick if entry.get("multi") else ""
        opt_m = tick if entry.get("optional") else ""
        der_m = tick if entry.get("derived") else ""
        lines.append(
            f"| {i} "
            f"| `{entry['param']}` "
            f"| `{entry['file']}` "
            f"| {loc_cell} "
            f"| `{entry['transform']}` "
            f"| {multi_m} "
            f"| {opt_m} "
            f"| {der_m} |"
        )
    lines.append("")
    lines.append(f"Total entries: **{len(param_map)}**")
    lines.append("")
    lines.append(CATALOG_FENCE_END)
    return "\n".join(lines) + "\n"


def _inject_catalog(existing: str, new_block: str) -> tuple[str, bool]:
    """Replace content between the fence markers in ``existing`` with
    ``new_block``. If fences are missing, append a new section at EOF.

    Returns ``(new_text, had_fences)``.
    """
    begin = CATALOG_FENCE_BEGIN
    end = CATALOG_FENCE_END
    if begin in existing and end in existing:
        pre = existing.split(begin, 1)[0]
        post = existing.split(end, 1)[1]
        return pre.rstrip() + "\n\n" + new_block.rstrip() + "\n" + post.lstrip("\n"), True
    appended = (
        existing.rstrip()
        + "\n\n---\n\n## 9. Auto-generated locator table\n\n"
        + new_block.rstrip()
        + "\n"
    )
    return appended, False


# ---------------------------------------------------------------------------
# FSCS: final skill-configuration snapshot (human-readable)
#
# outputs/ already carries:
#   - diff_report.txt       -- per-apply audit (node-by-node diff)
#   - validation_report.txt -- per-validate diagnostics
#   - landing_report.txt    -- live locator inventory
# FSCS.txt fills the remaining gap: a one-page, DiagComm.txt-style summary
# of WHAT WAS CONFIGURED (user-facing values + derived flags), so reviewers
# can eyeball the final state without re-reading ARXML or walking the diff
# line by line. Regenerated on every ``apply`` (dry-run or write) and
# refreshable standalone via ``pipeline.py fscs``.

# Fallback label width used by the ``params_changed`` delta block in
# ``build_doors_payload._build_delta_text`` when the run-specific labels
# are not available. The FSCS body itself sizes its label column
# dynamically (see ``_render_fscs``); this constant exists only so the
# delta block has a sensible default that lines up with the typical
# DiagComm parameter set.
FSCS_LABEL_WIDTH = 26


def _fscs_format_leaf(spec: dict[str, Any], value: Any) -> str:
    """Render one leaf value for FSCS.txt (user-space only, no arxml)."""
    if value is None:
        return "<not set>"
    t = spec.get("type")
    unit = spec.get("unit")
    if t == "bool":
        return "true" if bool(value) else "false"
    if unit == "ms":
        return f"{value} ms"
    return str(value)


def _fscs_line(label: str, rendered: str,
               *, label_width: int = FSCS_LABEL_WIDTH,
               value_width: int = 0) -> str:
    """Format one FSCS body line as ``<label> : <value>``.

    Labels are left-padded to ``label_width`` and values are
    right-padded to ``value_width`` so that, when ``label_width`` and
    ``value_width`` are computed from the longest label / value in the
    block, every line forms a clean rectangle in monospace -- the
    parameter table reads as a two-column grid with the colon column
    aligned and value right-edges aligned (e.g. ``70 ms`` / ``5000 ms``
    stack at the ``ms`` suffix). ``value_width=0`` falls back to the
    legacy left-aligned-value formatting for callers that don't size
    the value column ahead of time.
    """
    if value_width <= 0:
        return f"{label:<{label_width}} : {rendered}"
    return f"{label:<{label_width}} : {rendered:>{value_width}}"


def _render_fscs(values: dict[str, Any],
                 config: dict[str, Any],
                 schema: dict[str, Any],
                 mode: str) -> str:
    """Compose the FSCS.txt body.

    Intentionally minimal: only what the user authored across the v2
    pair (``DiagComm_values.json::{project,parameters}`` plus
    ``DiagComm_config.json::{paths,options}``), rendered one-leaf-per-
    line in the order declared by ``assets/DiagComm.txt``. Derived
    flags, landing summaries, and path/channel metadata are
    deliberately omitted -- they live in ``diff_report.txt`` /
    ``landing_report.txt`` / ``DiagComm_config.json::paths`` instead.

    Layout (since 1.16.1):

    * Four-line ``#`` header so each piece of identity sits on its
      own row (toolkit tag, project, product, timestamp/mode) --
      easier to scan both in ``outputs/FSCS.txt`` and inside the
      DOORS Object Text cell, and crucially makes "project" and
      "product" independently extensible: when a DOORS row picks up
      a second product without changing parameters, the Object Text
      composer in ``build_doors_payload.py`` only has to widen the
      product line (``# ESP / IPB``) instead of re-flowing a single
      "project / product" combo string. ``FSCS.txt`` itself stays
      single-project / single-product (it's a current-snapshot
      artefact); accumulation lives in Object Text only.

      Layout::

          # DiagComm FSCS
          # <project>
          # <product>
          # <timestamp>[  [<mode>]]

      The ``[<mode>]`` tag is only appended when it deviates from the
      default ``SNAPSHOT`` (i.e. dry-run / applied previews); DOORS
      uploads run ``pipeline.py fscs`` in SNAPSHOT mode, so the cell
      stays clean.

    * The parameter block is rendered as a two-column grid with the
      label column left-aligned and the value column right-aligned to
      the widest value in this run. That means same-unit values
      (``70 ms`` / ``150 ms`` / ``5000 ms``) stack at the ``ms``
      suffix and shorter values don't drift off into trailing
      whitespace.

    * ``product_type`` is rendered in the header only -- the body line
      is suppressed because it would just duplicate the header value
      (and ``RB_Product`` already carries the same datum on the DOORS
      side).
    """
    project_block = config.get("project") or {}
    project_name = project_block.get("name") or "<unset>"
    project_pt = project_block.get("product_type")
    pt_display = project_pt if (isinstance(project_pt, str) and project_pt) else "<unset>"

    effective_values: dict[str, Any] = dict(values) if isinstance(values, dict) else {}

    timestamp = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    timestamp_line = f"# {timestamp}"
    if isinstance(mode, str) and mode and mode != "SNAPSHOT":
        timestamp_line += f"  [{mode}]"

    lines: list[str] = [
        "# DiagComm FSCS",
        f"# {project_name}",
        f"# {pt_display}",
        timestamp_line,
        "",
    ]

    # First pass: collect (label, rendered) pairs in declared order.
    # Second pass formats them with widths sized to this run, so the
    # grid always fits the actual data without padding shorter labels
    # into pointless trailing whitespace.
    leaf_pairs: list[tuple[str, str]] = []
    for key, spec in schema.get("fields", {}).items():
        if key == "product_type":
            # Header already carries this; suppressing avoids redundancy.
            continue
        if spec.get("type") == "object":
            sub_vals = effective_values.get(key) if isinstance(effective_values, dict) else None
            if not isinstance(sub_vals, dict):
                sub_vals = {}
            for sub_key, sub_spec in (spec.get("fields") or {}).items():
                label = f"{key}.{sub_key}"
                raw = sub_vals.get(sub_key)
                leaf_pairs.append((label, _fscs_format_leaf(sub_spec, raw)))
        else:
            raw = effective_values.get(key) if isinstance(effective_values, dict) else None
            leaf_pairs.append((key, _fscs_format_leaf(spec, raw)))

    if leaf_pairs:
        label_w = max(len(label) for label, _ in leaf_pairs)
        value_w = max(len(rendered) for _, rendered in leaf_pairs)
    else:
        label_w = FSCS_LABEL_WIDTH
        value_w = 0

    for label, rendered in leaf_pairs:
        lines.append(_fscs_line(label, rendered,
                                label_width=label_w,
                                value_width=value_w))

    return "\n".join(lines) + "\n"


def _write_fscs(values: dict[str, Any],
                config: dict[str, Any],
                mode: str) -> Path | None:
    """Render + persist ``outputs/FSCS.txt``. Returns the path, or None
    when the schema is missing (in which case we quietly skip -- the
    snapshot only makes sense once ``gen-schema`` has run).
    """
    if not SCHEMA_PATH.exists():
        return None
    schema = load_json(SCHEMA_PATH)
    text = _render_fscs(values, config, schema, mode)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUTS_DIR / "FSCS.txt"
    out.write_text(text, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Reverse-walk helpers (used by cmd_landing_report and by the lazy-seed
# / cmd_reseed flow in pipeline.py)


def _read_current_value(tree_root: Any,
                        entry: dict[str, Any]) -> str | None:
    """Return the first arxml match's <VALUE> text for an entry, or None."""
    from arxml_patcher import AR_NS, find_matches

    hits = find_matches(tree_root, entry["locator"])
    if not hits:
        return None
    value_el = hits[0].find(f"{{{AR_NS}}}VALUE")
    if value_el is None:
        return None
    return (value_el.text or "").strip()


# ---------------------------------------------------------------------------
# Landing-report helpers


def _ancestor_short_name_chain(pv: Any) -> str:
    """Return 'A/B/C' SHORT-NAME chain from root to (but not including) pv."""
    from arxml_patcher import AR_NS

    names: list[str] = []
    cur = pv.getparent()
    while cur is not None:
        sn = cur.find(f"{{{AR_NS}}}SHORT-NAME")
        if sn is not None and sn.text:
            names.append(sn.text.strip())
        cur = cur.getparent()
    return "/".join(reversed(names))
