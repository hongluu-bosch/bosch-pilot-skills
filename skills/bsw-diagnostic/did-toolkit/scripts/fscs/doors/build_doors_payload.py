#!/usr/bin/env python3
"""Build the per-DID, two-row, two-table DOORS upload workbooks for the
DID FSCS pipeline.

For each DID emitted by the renderer (``outputs/fscs/FSCS_22.txt`` /
``outputs/fscs/FSCS_2E.txt``) we write TWO rows::

    row N    (FS) : Object Heading = first line of the DID's FSCS,
                    Object Text   = "",
                    RB_Realizing_SWitem = the .arxml basename,
                    RB_Referenced_Testcase / RB_TestEnvironment =
                       FS pair from role_values
    row N+1  (CS) : Object Heading = "",
                    Object Text   = the FULL Behavior section verbatim,
                    RB_Realizing_SWitem = the .c basename,
                    RB_Referenced_Testcase / RB_TestEnvironment =
                       CS pair from role_values

`RB_Product` is sourced PER DID from ``fscs.json::dids[].product_type``
(Phase 1 ``Product_Type`` column, renamed from ``product_scope`` in
schema 1.5). v1.16.0 dropped the global ``project.product_type``
config knob -- there is no project-wide fall-back, only the per-DID
tag plus the ``Common`` wildcard. The same value lands on BOTH rows
of the DID so DOORS' two-row block is self-contained.

Output is two workbooks under ``outputs/doors/``:

* ``doors_upload_22.xlsx`` -- every DID with `service_22.effective`
* ``doors_upload_2E.xlsx`` -- every DID with `service_2e.effective`

Each workbook is anchored against its service-specific anchor
(`anchors.service_22` / `anchors.service_2e` in the mapping yaml),
so DOORS lays the rows down sequentially after the matching anchor on
upload.

Layout matches ``assets/doors_template.xlsx`` exactly: 17 columns in
the order ``Number, Destination Object, isPicture, Absolute Number,
Object Heading, Object Text, RB_RS_CP_Status, RB_RS_MS_Status,
RB_Product, RB_Configuration, RB_Realizing_SWComponent,
RB_Realizing_SWitem, RB_VerificationType, RB_VerificationCriteria,
RB_Analysis_Results, RB_Referenced_Testcase, RB_TestEnvironment``.

The xlsx is produced with `xlsxwriter` directly (Application=Microsoft
Excel, sharedStrings, string-typed sizeRow/sizeColumn) which is the
only format the upload server accepts -- the openpyxl-tagged xlsx that
some sibling skills emit is silently rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from anchor import AnchorMatch, load_export, resolve_anchors  # noqa: E402
from content_hash import compute_pair_hash  # noqa: E402
from diff import (  # noqa: E402
    ActionPlan,
    DIDAction,
    compute_action_plan,
)
from doors_state import State, _normalise_hex  # noqa: E402
from fscs_split import DIDBlock, split_file  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parents[3]
# The DEFAULT_* constants below are argparse fallbacks. v1.26.0 moved
# the workspace to ``<container>/.DCOM_AI/DID_Toolkit_PRJ/`` so these skill-root paths
# don't exist in real invocations — ``pipeline.py --phase doors``
# always passes ``--mapping`` / ``--out-dir`` / ... explicitly. The
# constants stay so the standalone ``build_doors_payload.py`` CLI
# keeps a recognisable shape; users running it standalone must
# override every default with workspace-relative paths.
DEFAULT_MAPPING = SKILL_ROOT / "inputs" / "doors_mapping.yaml"
DEFAULT_PROJECT = SKILL_ROOT / "config" / "project.json"
DEFAULT_EXPORT = SKILL_ROOT / "outputs" / "doors" / "doors_export.json"
DEFAULT_TXT_22 = SKILL_ROOT / "outputs" / "fscs" / "FSCS_22.txt"
DEFAULT_TXT_2E = SKILL_ROOT / "outputs" / "fscs" / "FSCS_2E.txt"
DEFAULT_FSCS_JSON = SKILL_ROOT / "outputs" / "fscs" / "fscs.json"
DEFAULT_OUT_DIR = SKILL_ROOT / "outputs" / "doors"
DEFAULT_REPORT = DEFAULT_OUT_DIR / "doors_payload_report.txt"

OUTPUT_BASENAMES = {
    "22": "doors_upload_22.xlsx",
    "2E": "doors_upload_2E.xlsx",
}

# v1.16.0: 17-column DOORS template-aligned default order. Used only
# when ``.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`` is missing the
# ``columns`` block entirely (defensive fall-back; the YAML is
# committed and normally wins). Mirrors assets/doors_template.xlsx
# column-for-column.
DEFAULT_COLUMNS: List[str] = [
    "Number",
    "Destination Object",
    "isPicture",
    "Absolute Number",
    "Object Heading",
    "Object Text",
    "RB_RS_CP_Status",
    "RB_RS_MS_Status",
    "RB_Product",
    "RB_Configuration",
    "RB_Realizing_SWComponent",
    "RB_Realizing_SWitem",
    "RB_VerificationType",
    "RB_VerificationCriteria",
    "RB_Analysis_Results",
    "RB_Referenced_Testcase",
    "RB_TestEnvironment",
]

COMMON_TOKEN = "Common"

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ----------------------------------------------------------------------- #
# loaders                                                                 #
# ----------------------------------------------------------------------- #


def _load_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PyYAML is required for .DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml. "
            "Install with: python -m pip install pyyaml"
        ) from exc
    if not path.is_file():
        raise FileNotFoundError(f"mapping file missing: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("doors_mapping.yaml must be a top-level mapping")
    return loaded


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _project_meta(mapping: Dict[str, Any], project_path: Path) -> Dict[str, str]:
    """Pick `project_name` and `customer` from config/project.json
    (preferred) with fall-backs to mapping defaults so the build still
    runs in a fresh-clone smoke test.

    v1.16.0: the project meta no longer carries ``product_type`` --
    the global ``project.product_type`` knob was removed. Per-DID
    product_type is read straight from ``fscs.json`` in
    :func:`_load_per_did_product_types` instead.
    """
    project_doc = _load_json(project_path)
    project = project_doc.get("project") if isinstance(project_doc.get("project"), dict) else {}
    paths = project_doc.get("paths") if isinstance(project_doc.get("paths"), dict) else {}
    rp = mapping.get("realizing_paths") if isinstance(mapping.get("realizing_paths"), dict) else {}
    defaults = mapping.get("defaults") if isinstance(mapping.get("defaults"), dict) else {}
    customer = (
        paths.get("customer")
        if isinstance(paths.get("customer"), str)
        else rp.get("customer_default", "rbcn")
    )
    return {
        "project_name": str(
            project.get("name")
            or project.get("project_name")
            or defaults.get("RB_Project")
            or "DID FSCS"
        ).strip(),
        "customer": str(customer or "rbcn").strip(),
    }


def _load_per_did_product_types(fscs_json_path: Path) -> Dict[str, str]:
    """Load ``did_hex_uppercase -> product_type`` from outputs/fscs/fscs.json.

    Reads the raw JSON (not via the schema model) so a Phase 1 that's
    on a slightly different schema version still feeds DOORS without
    needing a migration first. Missing file -> empty dict (the DOORS
    cell will be blank, which is the v1.16.0 "no product tag" outcome
    when no override fires either).
    """
    doc = _load_json(fscs_json_path)
    out: Dict[str, str] = {}
    for entry in doc.get("dids", []):
        if not isinstance(entry, dict):
            continue
        hex_raw = str(entry.get("did_hex") or "").strip().upper()
        if not hex_raw:
            continue
        # Normalise to the same "0xNNNN" shape that DIDBlock carries
        # so the lookup later in the builder is a one-liner.
        if not hex_raw.startswith("0X"):
            hex_raw = f"0X{hex_raw}"
        # Allow either ``product_type`` (schema 1.5+) or the legacy
        # ``product_scope`` key (schema 1.4) -- the model migration
        # rewrites the JSON eventually but we shouldn't crash if a
        # caller hand-built an older fscs.json.
        token = (
            entry.get("product_type")
            or entry.get("product_scope")
            or ""
        )
        token = str(token).strip()
        if token:
            out[hex_raw.replace("0X", "0x")] = token
    return out


# ----------------------------------------------------------------------- #
# RB_Product / RB_Realizing_SWitem helpers                                #
# ----------------------------------------------------------------------- #


def _rb_product_value(
    *,
    did_hex: str,
    did_product_type: str,
    mapping: Dict[str, Any],
) -> str:
    """Resolve the RB_Product cell content for one DID.

    Resolution order (first non-empty wins):
      1. ``rb_product_overrides[did_hex]`` (case-insensitive on hex)
      2. per-DID ``product_type`` from fscs.json
      3. empty cell

    The resolved token is then mapped via ``value_maps.RB_Product``;
    if the token is the literal ``"Common"`` (case-insensitive), the
    cell content is every value in the value_map joined by newline
    (the full product set the project supports)."""
    overrides = mapping.get("rb_product_overrides") if isinstance(mapping.get("rb_product_overrides"), dict) else {}
    value_maps = mapping.get("value_maps") if isinstance(mapping.get("value_maps"), dict) else {}
    rb_map = value_maps.get("RB_Product") if isinstance(value_maps.get("RB_Product"), dict) else {}

    token = (
        overrides.get(did_hex)
        or overrides.get(did_hex.upper())
        or overrides.get(did_hex.lower())
        or did_product_type
    )
    token = (token or "").strip()
    if not token:
        return ""

    if token.casefold() == COMMON_TOKEN.casefold():
        seen: List[str] = []
        for v in rb_map.values():
            text = str(v).strip()
            if text and text not in seen:
                seen.append(text)
        return "\n".join(seen)

    mapped = rb_map.get(token)
    if mapped is None:
        return token
    return str(mapped).strip()


def _format_template(template: str, ctx: Dict[str, str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        return ctx.get(key, match.group(0))
    return _PLACEHOLDER_RE.sub(_sub, template)


def _basename_only(value: str) -> str:
    """Reduce a path-shaped string to its basename.

    DOORS' RB_Realizing_SWitem column wants the FILENAME, never a
    path. Operators sometimes paste full paths into
    ``realizing_paths.fs_template`` / ``cs_template`` (e.g. carried
    over from the v1.15.x layout) -- silently strip every directory
    prefix so both styles produce the same cell content. Empty
    strings come back unchanged.

    Handles both ``/`` and ``\\`` separators because Bosch project
    paths are POSIX-shaped on disk but operators frequently edit the
    YAML on Windows.
    """
    if not value:
        return value
    # rsplit on both separators by walking the longest tail.
    last_fwd = value.rfind("/")
    last_bwd = value.rfind("\\")
    cut = max(last_fwd, last_bwd)
    if cut < 0:
        return value
    return value[cut + 1:]


def _rb_realizing_value_for_role(
    *,
    block: DIDBlock,
    role: str,                       # "FS" or "CS"
    did_product_type: str,
    meta: Dict[str, str],
    mapping: Dict[str, Any],
) -> str:
    """Render the per-row RB_Realizing_SWitem basename.

    v1.16.0: the cell holds ONE filename per row (FS row = .arxml
    basename, CS row = .c basename). Path prefixes are dropped via
    :func:`_basename_only` so both legacy path-shaped templates and
    new basename-only templates produce the same output.

    Returns ``""`` (blank cell) when the relevant template is missing
    or evaluates to an empty string after placeholder substitution.
    """
    rp = mapping.get("realizing_paths") if isinstance(mapping.get("realizing_paths"), dict) else {}
    safe_name = re.sub(r"[^A-Za-z0-9_]+", "_", block.did_name).strip("_") or "Unnamed"
    ctx = {
        "did_hex": block.did_hex,
        "did_hex_bare": block.did_hex.removeprefix("0x").removeprefix("0X"),
        "did_name": safe_name,
        # v1.16.0: per-DID product_type drives both RB_Product and
        # any product-flavoured filename in the basename templates.
        "product_type": (did_product_type or "").strip(),
        "customer": meta.get("customer", "rbcn"),
    }
    role_key = role.upper()
    if role_key == "FS":
        template = rp.get("fs_template")
    elif role_key == "CS":
        template = rp.get("cs_template")
    else:
        template = None

    # Legacy fall-back: if the v1.15.x ``templates`` list is still
    # present (pre-rename), pull the first entry that "looks .arxml"
    # for FS and the first ".c" entry for CS. Operators upgrading
    # without touching the YAML keep getting reasonable basenames
    # until they edit the file.
    if not isinstance(template, str) or not template.strip():
        legacy = rp.get("templates") if isinstance(rp.get("templates"), list) else []
        for tpl in legacy:
            if not isinstance(tpl, str):
                continue
            if role_key == "FS" and tpl.lower().endswith(".arxml"):
                template = tpl
                break
            if role_key == "CS" and tpl.lower().endswith(".c"):
                template = tpl
                break

    if not isinstance(template, str) or not template.strip():
        return ""

    rendered = _format_template(template, ctx).strip()
    return _basename_only(rendered)


def _role_values(mapping: Dict[str, Any], role: str) -> Dict[str, str]:
    """Return the ``role_values[<role>]`` block as a string-keyed dict.

    Empty / missing blocks degrade silently to ``{}`` so the YAML can
    omit one role entirely (no role-specific override means whatever
    the ``columns`` block resolves to wins).
    """
    block = mapping.get("role_values") if isinstance(mapping.get("role_values"), dict) else {}
    pair = block.get(role.upper()) if isinstance(block.get(role.upper()), dict) else {}
    return {str(k): str(v) for k, v in pair.items()}


# ----------------------------------------------------------------------- #
# row context                                                             #
# ----------------------------------------------------------------------- #


@dataclass
class RowCtx:
    destination: str
    absolute_no: str
    heading: str
    object_text: str
    realizing: str           # per-row basename (FS=.arxml, CS=.c)
    rb_product: str
    referenced_testcase: str  # role_values[<role>].RB_Referenced_Testcase
    test_environment: str     # role_values[<role>].RB_TestEnvironment
    did_hex: str
    did_name: str
    service: str
    role: str  # "FS" or "CS"
    # v1.17.0 state-machine annotation. "insert" means
    # ``destination`` was filled from anchor.anchor_address and
    # ``absolute_no`` is blank; "update" flips them. Operator-side
    # mappings can read it via ``row.mode`` if they want.
    mode: str = "insert"

    def lookup(self, key: str) -> str:
        if not hasattr(self, key):
            raise KeyError(f"row.{key} unknown (RowCtx fields: "
                           f"{[f.name for f in self.__dataclass_fields__.values()]})")
        return str(getattr(self, key))


def _resolve_source(
    source: str,
    *,
    row: RowCtx,
    extras: Dict[str, str],
) -> str:
    """Resolve a single column source string from the mapping yaml."""
    if source is None:
        return ""
    if source.startswith("literal:"):
        text = source[len("literal:"):]
        return _expand_inline(text, row=row, extras=extras)
    if source.startswith("row."):
        try:
            return row.lookup(source[len("row."):])
        except KeyError as exc:
            raise KeyError(f"unknown column source {source!r}: {exc}") from exc
    if source.startswith("extras."):
        key = source[len("extras."):]
        if key not in extras:
            raise KeyError(f"extras.{key} not provided")
        return extras[key]
    if source == "":
        return ""
    raise KeyError(f"unsupported column source: {source!r}")


_INLINE_RE = re.compile(r"\{(row|extras)\.(\w+)\}")


def _expand_inline(text: str, *, row: RowCtx, extras: Dict[str, str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        scope, key = match.group(1), match.group(2)
        if scope == "row":
            try:
                return row.lookup(key)
            except KeyError:
                return match.group(0)
        if key in extras:
            return extras[key]
        return match.group(0)
    return _INLINE_RE.sub(_sub, text)


# ----------------------------------------------------------------------- #
# xlsx writer                                                             #
# ----------------------------------------------------------------------- #


def _resolve_columns(mapping: Dict[str, Any]) -> List[str]:
    cols = mapping.get("columns")
    if isinstance(cols, dict):
        return list(cols.keys())
    if isinstance(cols, list) and all(isinstance(c, str) for c in cols):
        return cols
    return list(DEFAULT_COLUMNS)


def _build_row_dict(
    *,
    columns: List[str],
    column_sources: Dict[str, str],
    defaults: Dict[str, Any],
    row: RowCtx,
    extras: Dict[str, str],
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for col in columns:
        if col in column_sources:
            try:
                out[col] = _resolve_source(column_sources[col], row=row, extras=extras)
            except KeyError as exc:
                raise KeyError(f"column {col!r} -> {exc}") from exc
        elif col in defaults:
            out[col] = defaults[col]
        else:
            out[col] = ""
    return out


def _write_xlsx(
    *,
    out_path: Path,
    sheet_name: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
    size_row: int = 1,
    header_row: int = 2,
    data_start: int = 3,
) -> int:
    """Write the DOORS-native xlsx via xlsxwriter. Returns the number
    of data rows written."""
    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "xlsxwriter is required to build the DOORS xlsx. "
            "Install with: python -m pip install xlsxwriter"
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(out_path))
    try:
        worksheet = workbook.add_worksheet(sheet_name)
        total_rows = (data_start - 1) + len(rows)
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
        for ri, row_data in enumerate(rows):
            for ci, header_name in enumerate(columns):
                value = row_data.get(header_name, "")
                if value is None or value == "":
                    worksheet.write_blank(ds0 + ri, ci, None)
                else:
                    worksheet.write(ds0 + ri, ci, value)
    finally:
        workbook.close()
    return len(rows)


# ----------------------------------------------------------------------- #
# main builder                                                            #
# ----------------------------------------------------------------------- #


@dataclass
class ServiceArtifact:
    service: str
    xlsx_path: Path
    anchor: AnchorMatch
    rows_written: int
    did_hexes: List[str]


@dataclass
class BuildResult:
    services: Dict[str, ServiceArtifact] = field(default_factory=dict)
    fscs_sha256: str = ""
    report_path: Optional[Path] = None
    project_meta: Dict[str, str] = field(default_factory=dict)
    # v1.17.0 state-machine outputs. ``action_plan`` summarises
    # the per-DID×service decision the build made (orchestrator
    # logs it + uses it to drive the post-upload state writeback);
    # ``did_pair_hashes`` is keyed by ``(service_uppercase, did_hex)``
    # and holds the freshly computed content hash so the orchestrator
    # can persist it without re-rendering after the upload.
    action_plan: Optional[ActionPlan] = None
    did_pair_hashes: Dict[Tuple[str, str], str] = field(default_factory=dict)


def _hash_fscs(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        if p.is_file():
            h.update(p.read_bytes())
        h.update(b"\n--\n")
    return h.hexdigest()


def _did_blocks_for_service(
    service: str,
    *,
    fscs_22: List[DIDBlock],
    fscs_2e: List[DIDBlock],
) -> List[DIDBlock]:
    if service == "22":
        return fscs_22
    if service == "2E":
        return fscs_2e
    raise ValueError(f"unsupported service: {service!r}")


def build_payload(
    *,
    mapping_path: Path = DEFAULT_MAPPING,
    project_path: Path = DEFAULT_PROJECT,
    export_path: Path = DEFAULT_EXPORT,
    txt_22_path: Path = DEFAULT_TXT_22,
    txt_2e_path: Path = DEFAULT_TXT_2E,
    fscs_json_path: Path = DEFAULT_FSCS_JSON,
    out_dir: Path = DEFAULT_OUT_DIR,
    report_path: Path = DEFAULT_REPORT,
    services: Iterable[str] = ("22", "2E"),
    require_anchors: bool = True,
    # v1.17.0 state-machine inputs. When BOTH are supplied the
    # build runs the INSERT / UPDATE / NOOP / STALE classifier
    # (``diff.compute_action_plan``) and writes only INSERT +
    # UPDATE rows. Either being None falls back to the v1.16.0
    # "everything is INSERT" behaviour, preserving existing
    # callers (the doors_payload unit suite, for one).
    state: Optional[State] = None,
    module_uuid: Optional[str] = None,
    # v1.17.0 ``--plan-only`` orchestration knob. When True the
    # builder runs Pass 1 (per-DID hashing) + the diff classifier
    # exactly as a normal run, but skips Pass 2 (no workbooks
    # written, ``BuildResult.services`` stays empty). The orchestrator
    # then prints ``format_plan_table(result.action_plan)`` and
    # exits. Useful for "what would change?" dry-runs without
    # touching disk-resident xlsx artefacts.
    plan_only: bool = False,
) -> BuildResult:
    """Full per-service build. Returns the artefacts we wrote so the
    orchestrator can chain into upload / link generation.

    `require_anchors=False` is used by the build-only smoke test --
    it lets the dry run proceed even if the DOORS export hasn't been
    fetched yet (anchor cells are filled with a placeholder string).

    ``fscs_json_path`` is consulted for per-DID ``product_type``
    values (Phase 1's Product_Type column). Missing / unreadable
    JSON degrades to an empty per-DID lookup, so the only way a row
    gets a non-empty ``RB_Product`` is via ``rb_product_overrides``
    in the mapping yaml.

    State-machine semantics (v1.17.0):

    * ``state`` AND ``module_uuid`` supplied -> compute action plan
      via :func:`diff.compute_action_plan`; write workbook rows for
      INSERT / UPDATE only; NOOP and STALE are skipped (NOOP is the
      operator's signal that "nothing changed for this DID, don't
      re-upload"; STALE is warn-only).
    * Either ``state`` or ``module_uuid`` is None -> every effective
      DID is treated as INSERT (legacy v1.16.0 behaviour, used by
      the unit-test fixtures that don't carry state).

    Both branches always populate :attr:`BuildResult.action_plan`
    and :attr:`BuildResult.did_pair_hashes` so the orchestrator
    can do the post-upload state writeback uniformly.
    """
    mapping = _load_yaml(mapping_path)
    columns = _resolve_columns(mapping)
    column_sources_raw = mapping.get("columns")
    column_sources: Dict[str, str] = (
        {k: str(v) for k, v in column_sources_raw.items()}
        if isinstance(column_sources_raw, dict)
        else {}
    )
    defaults = mapping.get("defaults") if isinstance(mapping.get("defaults"), dict) else {}

    template_block = mapping.get("template") if isinstance(mapping.get("template"), dict) else {}
    sheet_name = str(template_block.get("sheet", "CS Data"))
    size_row = int(template_block.get("size_row", 1))
    header_row = int(template_block.get("header_row", 2))
    data_start = int(template_block.get("data_start", 3))

    meta = _project_meta(mapping, project_path)
    extras = {
        "project_name": meta["project_name"],
        "customer": meta["customer"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # v1.16.0: per-DID product_type lookup, hex -> token. Used both
    # for RB_Product (via _rb_product_value) and for the
    # ``{product_type}`` placeholder in realizing_paths templates.
    per_did_product_type = _load_per_did_product_types(fscs_json_path)

    fscs_22 = split_file(txt_22_path) if txt_22_path.is_file() else []
    fscs_2e = split_file(txt_2e_path) if txt_2e_path.is_file() else []

    requested = [s.upper() for s in services]
    anchors_map: Dict[str, AnchorMatch] = {}
    if require_anchors:
        rows = load_export(export_path)
        anchors_cfg = mapping.get("anchors") if isinstance(mapping.get("anchors"), dict) else {}
        anchors_map = resolve_anchors(rows, anchors_cfg, services=requested)
    else:
        for s in requested:
            anchors_map[s] = AnchorMatch(
                service=s,
                anchor_address="",
                rule="dry-run (no export loaded)",
                raw_row=None,
            )

    # Pre-resolve role-specific values once -- they're constant per
    # role across all DIDs and services in this run.
    fs_role = _role_values(mapping, "FS")
    cs_role = _role_values(mapping, "CS")

    out_dir.mkdir(parents=True, exist_ok=True)
    result = BuildResult(fscs_sha256=_hash_fscs(txt_22_path, txt_2e_path), project_meta=meta)
    report_lines: List[str] = [
        "# did-toolkit -> DOORS payload report (per-DID two-row layout, 17 cols)",
        f"# generated_at      : {extras['generated_at']}",
        f"# project           : {meta['project_name']}",
        f"# customer          : {meta['customer']}",
        f"# fscs_sha256       : {result.fscs_sha256}",
        f"# product_type src  : per-DID fscs.json (count={len(per_did_product_type)})",
        "",
    ]

    # ----------------------------------------------------------------- #
    # Pass 1: build the per-DID×service row pair + content hash for     #
    # every effective DID. Hashing happens BEFORE the action plan so    #
    # NOOP / UPDATE / INSERT can be classified off real cell values.    #
    # The Destination Object / Absolute Number cells get fixed up in    #
    # Pass 2 once the plan is known; their placeholder values here      #
    # don't affect the hash because compute_pair_hash filters them      #
    # out (HASHED_COLUMNS excludes both).                               #
    # ----------------------------------------------------------------- #

    pending: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for service in requested:
        anchor = anchors_map[service]
        blocks = _did_blocks_for_service(service, fscs_22=fscs_22, fscs_2e=fscs_2e)

        for block in blocks:
            did_pt = per_did_product_type.get(block.did_hex, "")
            rb_product = _rb_product_value(
                did_hex=block.did_hex,
                did_product_type=did_pt,
                mapping=mapping,
            )
            realizing_fs = _rb_realizing_value_for_role(
                block=block, role="FS",
                did_product_type=did_pt,
                meta=meta, mapping=mapping,
            )
            realizing_cs = _rb_realizing_value_for_role(
                block=block, role="CS",
                did_product_type=did_pt,
                meta=meta, mapping=mapping,
            )

            fs_ctx = RowCtx(
                destination=anchor.anchor_address,
                absolute_no="",
                heading=block.heading,
                object_text="",
                realizing=realizing_fs,
                rb_product=rb_product,
                referenced_testcase=fs_role.get("RB_Referenced_Testcase", ""),
                test_environment=fs_role.get("RB_TestEnvironment", ""),
                did_hex=block.did_hex,
                did_name=block.did_name,
                service=service,
                role="FS",
                mode="insert",  # Pass 2 may flip this to "update".
            )
            cs_ctx = RowCtx(
                destination=anchor.anchor_address,
                absolute_no="",
                heading="",
                # FULL Behavior content -- DIDBlock.body already
                # holds everything after the "Identifier $XXXXh - ..."
                # heading, including multi-line Behavior sections.
                object_text=block.body,
                realizing=realizing_cs,
                rb_product=rb_product,
                referenced_testcase=cs_role.get("RB_Referenced_Testcase", ""),
                test_environment=cs_role.get("RB_TestEnvironment", ""),
                did_hex=block.did_hex,
                did_name=block.did_name,
                service=service,
                role="CS",
                mode="insert",
            )
            row_extras = {**extras, "service": service, "product_type": did_pt}
            fs_dict = _build_row_dict(
                columns=columns,
                column_sources=column_sources,
                defaults=defaults,
                row=fs_ctx,
                extras=row_extras,
            )
            cs_dict = _build_row_dict(
                columns=columns,
                column_sources=column_sources,
                defaults=defaults,
                row=cs_ctx,
                extras=row_extras,
            )
            content_hash = compute_pair_hash(fs_cells=fs_dict, cs_cells=cs_dict)
            canonical_hex = _normalise_hex(block.did_hex)
            pending[(service, canonical_hex)] = {
                "block": block,
                "anchor": anchor,
                "did_pt": did_pt,
                "rb_product": rb_product,
                "realizing_fs": realizing_fs,
                "realizing_cs": realizing_cs,
                "fs_dict": fs_dict,
                "cs_dict": cs_dict,
                "content_hash": content_hash,
            }
            result.did_pair_hashes[(service, canonical_hex)] = content_hash

    # ----------------------------------------------------------------- #
    # Action plan: state + module_uuid both supplied -> diff against    #
    # the recorded landings. Otherwise fabricate a full-INSERT plan so  #
    # the v1.16.0 single-shot tests / standalone runs keep working.     #
    # ----------------------------------------------------------------- #

    current_hashes: Dict[str, Dict[str, str]] = {svc: {} for svc in requested}
    for (service, did_hex), entry in pending.items():
        current_hashes[service][did_hex] = entry["content_hash"]

    if state is not None and module_uuid:
        plan = compute_action_plan(
            state=state,
            module_uuid=module_uuid,
            current_hashes=current_hashes,
        )
    else:
        plan = _full_insert_plan(current_hashes)

    result.action_plan = plan

    report_lines.append(f"# action plan       : {plan.summary()}")
    if module_uuid:
        report_lines.append(f"# module_uuid       : {module_uuid}")
    report_lines.append("")

    if plan_only:
        # --plan-only short-circuit: report still gets written so
        # the operator can grep it later, but no xlsx hits disk
        # and ``result.services`` stays empty (the orchestrator
        # checks for that and skips its "built ${service}" prints).
        report_lines.append("[plan-only] skipping Pass 2 / xlsx writes per CLI flag.")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        result.report_path = report_path
        return result

    # ----------------------------------------------------------------- #
    # Pass 2: write per-service workbooks per the action plan. NOOP +   #
    # STALE never reach the workbook (decision 1A + 3A); INSERT pulls  #
    # Destination Object from the anchor; UPDATE pulls Absolute Number #
    # from the recorded landings.                                      #
    # ----------------------------------------------------------------- #

    for service in requested:
        anchor = anchors_map[service]
        rows_data: List[Dict[str, Any]] = []
        emitted_hexes: List[str] = []

        report_lines.append(f"[service ${service}]")
        report_lines.append(f"  anchor.rule          : {anchor.rule}")
        report_lines.append(f"  anchor.anchor_address: {anchor.anchor_address or '(none)'}")

        actions = plan.for_workbook(service)
        report_lines.append(
            f"  actions               : {len(actions)} "
            f"({sum(1 for a in actions if a.action == 'INSERT')} INSERT, "
            f"{sum(1 for a in actions if a.action == 'UPDATE')} UPDATE)"
        )

        for action in actions:
            entry = pending.get((service, action.did_hex))
            if entry is None:
                # The plan can't legitimately reference a DID that
                # the renderer didn't produce -- if it does we're
                # better off raising than silently dropping a row.
                raise RuntimeError(
                    f"plan references {action.did_hex!r}/{service} but the "
                    f"renderer produced no row pair for it -- internal bug"
                )

            block = entry["block"]
            fs_dict = dict(entry["fs_dict"])
            cs_dict = dict(entry["cs_dict"])
            _apply_action_to_row_pair(
                action=action, anchor=anchor,
                fs_dict=fs_dict, cs_dict=cs_dict,
            )
            rows_data.append(fs_dict)
            rows_data.append(cs_dict)
            emitted_hexes.append(block.did_hex)
            report_lines.append(
                f"    - [{action.action}] {block.did_hex} {block.did_name} "
                f"(product_type={entry['did_pt']!r}, "
                f"rb_product={entry['rb_product']!r}, "
                f"realizing FS={entry['realizing_fs']!r}, "
                f"CS={entry['realizing_cs']!r})"
            )

        out_path = out_dir / OUTPUT_BASENAMES[service]
        rows_written = _write_xlsx(
            out_path=out_path,
            sheet_name=sheet_name,
            columns=columns,
            rows=rows_data,
            size_row=size_row,
            header_row=header_row,
            data_start=data_start,
        )
        result.services[service] = ServiceArtifact(
            service=service,
            xlsx_path=out_path,
            anchor=anchor,
            rows_written=rows_written,
            did_hexes=emitted_hexes,
        )
        report_lines.append(f"  rows_written          : {rows_written}")
        report_lines.append(f"  xlsx                  : {out_path}")
        report_lines.append("")

    # NOOP / STALE summary at the bottom of the report so the operator
    # can see at a glance which DIDs were skipped without re-running.
    skipped = [a for a in plan.actions if a.action in ("NOOP", "STALE")]
    if skipped:
        report_lines.append("[skipped]")
        for a in skipped:
            report_lines.append(
                f"  - [{a.action}] {a.did_hex}/{a.service} "
                f"(fs_abs={a.fs_abs}, cs_abs={a.cs_abs})"
            )
        report_lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    result.report_path = report_path
    return result


def _full_insert_plan(
    current_hashes: Dict[str, Dict[str, str]],
) -> ActionPlan:
    """Synthesize an all-INSERT plan -- the v1.16.0 single-shot
    semantics, used when ``state`` / ``module_uuid`` aren't passed
    so the existing test fixtures (which don't carry state) keep
    working unchanged.

    Iteration order matches ``current_hashes`` insertion order:
    ``build_payload`` populates that dict by walking DIDBlocks in
    FSCS-file order, so the workbook layout downstream stays in
    the same order operators see in ``FSCS_22.txt`` /
    ``FSCS_2E.txt``. Do NOT re-sort here -- the v1.16.0 unit
    suite (test_doors_payload.py) and the operator's eyeballs
    both rely on FSCS-file order.
    """
    plan = ActionPlan(module_uuid="(no-state)")
    for service, pairs in current_hashes.items():
        for did_hex, h in pairs.items():
            plan.actions.append(DIDAction(
                did_hex=_normalise_hex(did_hex),
                service=service,
                action="INSERT",
                current_hash=h,
            ))
    return plan


def _apply_action_to_row_pair(
    *,
    action: DIDAction,
    anchor: AnchorMatch,
    fs_dict: Dict[str, Any],
    cs_dict: Dict[str, Any],
) -> None:
    """Mutate the FS+CS row dicts to reflect the action's mode.

    INSERT mode: ``Destination Object`` carries the anchor's
    AbsoluteNumber (so DOORS appends after the anchor sequentially);
    ``Absolute Number`` is blank.

    UPDATE mode: ``Destination Object`` is blank (no insert);
    ``Absolute Number`` carries the previously-recorded fs_abs /
    cs_abs (so DOORS overwrites the existing row in place).

    Same key lives in BOTH columns for both rows of the pair --
    matching the shipped layout in v1.16.0. The two-column write
    is unconditional even when one side is blank, so an UPDATE
    after an INSERT (or vice versa) overwrites correctly.
    """
    if action.action == "INSERT":
        fs_dict["Destination Object"] = anchor.anchor_address or ""
        fs_dict["Absolute Number"] = ""
        cs_dict["Destination Object"] = anchor.anchor_address or ""
        cs_dict["Absolute Number"] = ""
        return

    if action.action == "UPDATE":
        fs_dict["Destination Object"] = ""
        fs_dict["Absolute Number"] = action.fs_abs or ""
        cs_dict["Destination Object"] = ""
        cs_dict["Absolute Number"] = action.cs_abs or ""
        return

    raise RuntimeError(
        f"_apply_action_to_row_pair only handles INSERT/UPDATE, got {action.action!r}"
    )


# ----------------------------------------------------------------------- #
# CLI plumbing                                                            #
# ----------------------------------------------------------------------- #


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="did-toolkit/build_doors_payload.py",
        description="Build the per-DID two-row DOORS upload workbooks (one per service).",
    )
    p.add_argument("--mapping", default=str(DEFAULT_MAPPING))
    p.add_argument("--project", default=str(DEFAULT_PROJECT))
    p.add_argument("--export", default=str(DEFAULT_EXPORT))
    p.add_argument("--txt-22", default=str(DEFAULT_TXT_22))
    p.add_argument("--txt-2e", default=str(DEFAULT_TXT_2E))
    p.add_argument(
        "--fscs-json", default=str(DEFAULT_FSCS_JSON),
        help="Authoritative fscs.json (used for per-DID product_type "
             "/ RB_Product lookup). Defaults to outputs/fscs/fscs.json.",
    )
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--report", default=str(DEFAULT_REPORT))
    p.add_argument("--services", default="22,2E", help="Comma-separated list (default 22,2E)")
    p.add_argument("--no-anchor", action="store_true",
                   help="Skip the DOORS export anchor lookup (dry-run / smoke build)")
    args = p.parse_args(argv)

    services = [s.strip().upper() for s in args.services.split(",") if s.strip()]
    try:
        result = build_payload(
            mapping_path=Path(args.mapping),
            project_path=Path(args.project),
            export_path=Path(args.export),
            txt_22_path=Path(args.txt_22),
            txt_2e_path=Path(args.txt_2e),
            fscs_json_path=Path(args.fscs_json),
            out_dir=Path(args.out_dir),
            report_path=Path(args.report),
            services=services,
            require_anchors=not args.no_anchor,
        )
    except (FileNotFoundError, ValueError, LookupError, KeyError) as exc:
        print(f"[build_doors_payload] ERROR: {exc}", file=sys.stderr)
        return 2

    summary = {
        "fscs_sha256": result.fscs_sha256,
        "project_meta": result.project_meta,
        "report": str(result.report_path) if result.report_path else None,
        "services": {
            s: {
                "xlsx": str(a.xlsx_path),
                "rows_written": a.rows_written,
                "anchor_rule": a.anchor.rule,
                "anchor_address": a.anchor.anchor_address,
                "did_count": len(a.did_hexes),
            }
            for s, a in result.services.items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
