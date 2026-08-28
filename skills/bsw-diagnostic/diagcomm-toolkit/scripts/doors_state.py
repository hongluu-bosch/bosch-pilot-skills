"""diagcomm-toolkit -> DOORS upload state (Step 8 helper).

Schema v3: state is keyed by `module_uuid`. Each module tracks **one**
DOORS row that is grown over time, not overwritten on every upload.

Conceptual model (per the user-facing spec):

    1. The parameter set (DiagComm_values.json::values, including
       CAN_Channel) is *unique* at any moment in time.
    2. (project_name, product_type) pairs are *not* unique -- one
       parameter set may serve many projects/products.
    3. Therefore the DOORS row tracked under each module_uuid is a
       LIVING record:
          - RB_Product       grows  (every product that ever used this row)
          - RB_Realizing_SWitem grows  (every arxml path under this row)
          - Object Text      grows  (each upload appends a section)

    Insert (auto) only happens when:
        - state has no entry for module_uuid (first ever upload), OR
        - the parameter fingerprint AND (project OR product) BOTH
          changed since the last successful upload (a genuinely new
          context warrants a fresh row).

    Otherwise -> update, with the build_doors_payload step generating
    a row whose multi-value cells are the union (history U current)
    and whose Object Text is (state.last_object_text + new appended
    section). Skip ("no_change") when literally everything matches the
    last successful upload.

State file layout (v3):

    {
      "version": 3,
      "modules": {
        "<module_uuid>": {
          "last_success_abs":           "576",
          "last_upload_at":             "2026-05-06T10:21:33",
          "current_project_name":       "MyProject",
          "current_product_type":       "ESP",
          "current_param_fingerprint":  "sha256:...",
          "current_fscs_sha256":        "sha256:...",
          "covered_projects":           ["MyProject"],
          "covered_products":           ["ESP", "IPB"],
          "covered_arxml_paths":        ["RBAPLCust/cfg/.../foo.arxml", ...],
          "last_object_text":           "...",
          "history": [
            {"ts": "...", "project": "...", "product": "...",
             "param_fingerprint": "...", "fscs_sha256": "...",
             "change_kind": "first_insert" | "params_changed" | ...,
             "abs_n": "576"}
          ]
        }
      }
    }

`change_kind` values (returned by `classify_change()`):

    "first_insert"           - state had no entry for this uuid
    "params_and_pp_changed"  - both params and project/product differ
                                from the last upload (insert-trigger)
    "params_changed"         - params differ; project+product unchanged
    "pp_only_changed"        - params identical; project or product
                                differs (or both)
    "fscs_only_changed"      - params + project + product all match;
                                only FSCS sha differs
    "no_change"              - everything matches; skip-eligible
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

STATE_VERSION = 3

# Fields excluded from the parameter fingerprint -- they describe
# project/product identity, not parameter values.
_FINGERPRINT_EXCLUDED_KEYS = {"product_type"}

CHANGE_KIND_FIRST_INSERT = "first_insert"
CHANGE_KIND_PARAMS_AND_PP = "params_and_pp_changed"
CHANGE_KIND_PARAMS = "params_changed"
CHANGE_KIND_PP_ONLY = "pp_only_changed"
CHANGE_KIND_FSCS_ONLY = "fscs_only_changed"
CHANGE_KIND_NONE = "no_change"

# change kinds that resolve to mode=insert
_INSERT_KINDS = {CHANGE_KIND_FIRST_INSERT, CHANGE_KIND_PARAMS_AND_PP}


# -- fingerprint helpers ------------------------------------------------- #


def compute_param_fingerprint(parameters_block: Dict[str, Any]) -> str:
    """Stable sha256 over `DiagComm_values.json::parameters`.

    In v2 (1.13.0+) `product_type` lives under `project.product_type`,
    not in `parameters`, so the parameter set hashed here is exactly
    "the unique parameter contents" with no special-casing required.
    The `_FINGERPRINT_EXCLUDED_KEYS` filter is kept as a safety net
    so legacy v1 inputs that still carry `product_type` inside
    parameters yield the same hash as their v2-shaped equivalents.
    """
    filtered = {k: v for k, v in parameters_block.items()
                if k not in _FINGERPRINT_EXCLUDED_KEYS}
    payload = json.dumps(filtered, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_file_sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def union_preserve_order(existing: Iterable[Any], additions: Iterable[Any]) -> List[Any]:
    """Append items from `additions` to `existing`, dropping duplicates
    while preserving first-seen order. Used to grow the multi-value
    cells (RB_Product, RB_Realizing_SWitem, covered_projects, ...).
    """
    seen: set = set()
    out: List[Any] = []
    for item in list(existing) + list(additions):
        key = (type(item).__name__, item) if not isinstance(item, str) else item
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


# -- I/O ----------------------------------------------------------------- #


def load_state(path: Path) -> Dict[str, Any]:
    """Load state JSON; auto-migrate older schemas to v3."""
    if not path.exists():
        return {"version": STATE_VERSION, "modules": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"state file is corrupt at {path}: {exc}\n"
            "  Delete it (or `git checkout`) and re-run."
        )
    if not isinstance(data, dict):
        raise SystemExit(f"state file at {path} must be a top-level object")

    file_version = data.get("version")
    if file_version == STATE_VERSION:
        if not isinstance(data.get("modules"), dict):
            raise SystemExit(
                f"state.modules must be a dict at {path}; got "
                f"{type(data.get('modules')).__name__}"
            )
        return data

    if file_version == 2:
        return _migrate_v2_to_v3(data)
    if file_version == 1:
        return _migrate_v2_to_v3(_migrate_v1_to_v2(data))

    raise SystemExit(
        f"state file version mismatch at {path}: got {file_version!r}, "
        f"expected {STATE_VERSION} (or 1/2 for auto-migration). "
        "Delete it and re-run."
    )


def _migrate_v1_to_v2(v1_data: Dict[str, Any]) -> Dict[str, Any]:
    """Collapse v1's per-(uuid, project, product) entries into one
    entry per uuid (the most recent one wins). Returns v2 state.
    """
    v1_entries = v1_data.get("entries") or {}
    if not isinstance(v1_entries, dict):
        raise SystemExit("v1 state has no `entries` dict; cannot migrate.")

    by_uuid: Dict[str, Dict[str, Any]] = {}
    dropped = 0
    for k, entry in v1_entries.items():
        if not isinstance(entry, dict):
            continue
        uuid_part = (k.split("|", 1) or [""])[0].strip()
        if not uuid_part:
            uuid_part = str(entry.get("module_uuid") or "").strip()
        if not uuid_part:
            continue
        prev = by_uuid.get(uuid_part)
        if prev is None:
            by_uuid[uuid_part] = entry
        else:
            new_ts = str(entry.get("last_upload_at") or "")
            old_ts = str(prev.get("last_upload_at") or "")
            if new_ts > old_ts:
                by_uuid[uuid_part] = entry
            dropped += 1

    modules: Dict[str, Dict[str, Any]] = {}
    for uuid, e in by_uuid.items():
        modules[uuid] = {
            "last_success_abs": str(e.get("last_success_abs") or ""),
            "last_upload_at":   str(e.get("last_upload_at") or ""),
            "project_name":     str(e.get("project_name") or ""),
            "product_type":     str(e.get("product_type") or ""),
            "param_fingerprint": e.get("param_fingerprint"),
            "fscs_sha256":       e.get("fscs_sha256"),
        }

    sys.stderr.write(
        f"[doors_state] migrated state v1 -> v2: "
        f"{len(modules)} module(s) kept, {dropped} historical entry/entries dropped.\n"
    )
    return {"version": 2, "modules": modules}


def _migrate_v2_to_v3(v2_data: Dict[str, Any]) -> Dict[str, Any]:
    """v2 had a single (project, product, fingerprint) per module.
    v3 grows lists. The migrated v3 entry treats the v2 entry as the
    sole "first_insert" history record; covered_* lists are seeded
    with the single recorded value. last_object_text is unknown
    (v2 didn't store it) -- we leave it None and the next update will
    surface that gap honestly in the appended block.
    """
    v2_modules = v2_data.get("modules") or {}
    if not isinstance(v2_modules, dict):
        raise SystemExit("v2 state has no `modules` dict; cannot migrate.")

    new_modules: Dict[str, Dict[str, Any]] = {}
    for uuid, e in v2_modules.items():
        if not isinstance(e, dict):
            continue
        proj = str(e.get("project_name") or "")
        prod = str(e.get("product_type") or "")
        new_modules[uuid] = {
            "last_success_abs": str(e.get("last_success_abs") or ""),
            "last_upload_at":   str(e.get("last_upload_at") or ""),
            "current_project_name": proj,
            "current_product_type": prod,
            "current_param_fingerprint": e.get("param_fingerprint"),
            "current_fscs_sha256":       e.get("fscs_sha256"),
            "covered_projects":          [proj] if proj else [],
            "covered_products":          [prod] if prod else [],
            "covered_arxml_paths":       [],
            "last_object_text":          None,
            "history": [
                {
                    "ts": str(e.get("last_upload_at") or ""),
                    "project": proj,
                    "product": prod,
                    "param_fingerprint": e.get("param_fingerprint"),
                    "fscs_sha256": e.get("fscs_sha256"),
                    "change_kind": CHANGE_KIND_FIRST_INSERT,
                    "abs_n": str(e.get("last_success_abs") or ""),
                    "_migrated_from": "v2",
                }
            ],
        }

    sys.stderr.write(
        f"[doors_state] migrated state v2 -> v3: "
        f"{len(new_modules)} module(s) carried over; "
        "covered_arxml_paths and last_object_text start empty -- "
        "the next update will append on top of that.\n"
    )
    return {"version": STATE_VERSION, "modules": new_modules}


def save_state(path: Path, data: Dict[str, Any]) -> None:
    """Atomic write: write to a sibling tmp, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False, sort_keys=False)
            fp.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# -- classification & decision ------------------------------------------ #


def classify_change(
    state: Dict[str, Any],
    module_uuid: str,
    *,
    project_name: str,
    product_type: str,
    param_fingerprint: str,
    fscs_sha256: Optional[str],
) -> str:
    """Compute the change_kind based on the recorded "current_*"
    snapshot in the state entry vs. the values for this run. The
    returned kind drives BOTH the auto insert/update decision AND
    the Object Text append template selected by build_doors_payload.
    """
    entry = (state.get("modules") or {}).get(module_uuid)
    if not entry or not entry.get("last_success_abs"):
        return CHANGE_KIND_FIRST_INSERT

    rec_fp = entry.get("current_param_fingerprint")
    rec_proj = str(entry.get("current_project_name") or "")
    rec_prod = str(entry.get("current_product_type") or "")
    rec_fscs = entry.get("current_fscs_sha256")

    fp_changed = (rec_fp != param_fingerprint)
    pp_changed = (rec_proj != project_name) or (rec_prod != product_type)
    fscs_changed = (
        fscs_sha256 is not None and rec_fscs is not None and rec_fscs != fscs_sha256
    )

    if fp_changed and pp_changed:
        return CHANGE_KIND_PARAMS_AND_PP
    if fp_changed:
        return CHANGE_KIND_PARAMS
    if pp_changed:
        return CHANGE_KIND_PP_ONLY
    if fscs_changed:
        return CHANGE_KIND_FSCS_ONLY
    return CHANGE_KIND_NONE


def decide_mode_from_kind(
    state: Dict[str, Any],
    module_uuid: str,
    change_kind: str,
) -> Tuple[str, Optional[str], str]:
    """Translate a change_kind into (mode, target_abs, reason).

    Auto-insert triggers (consistent with v1.11.0): no state, OR both
    params and project/product changed. Everything else is update.
    """
    entry = (state.get("modules") or {}).get(module_uuid) or {}
    abs_n = str(entry.get("last_success_abs") or "").strip()

    if change_kind == CHANGE_KIND_FIRST_INSERT:
        return "insert", None, f"no state entry for module_uuid {module_uuid!r}"

    if change_kind == CHANGE_KIND_PARAMS_AND_PP:
        rec_proj = entry.get("current_project_name") or ""
        rec_prod = entry.get("current_product_type") or ""
        return (
            "insert",
            None,
            f"params changed AND project/product changed "
            f"(was {rec_proj}/{rec_prod}); carving a new DOORS row",
        )

    if not abs_n:
        return (
            "insert",
            None,
            f"state entry for module_uuid {module_uuid!r} has no last_success_abs",
        )

    if change_kind == CHANGE_KIND_PARAMS:
        return "update", abs_n, "params changed; appending delta to row"
    if change_kind == CHANGE_KIND_PP_ONLY:
        rec_proj = entry.get("current_project_name") or ""
        rec_prod = entry.get("current_product_type") or ""
        return (
            "update",
            abs_n,
            f"params unchanged; mapping a new (project, product) onto row "
            f"(was {rec_proj}/{rec_prod})",
        )
    if change_kind == CHANGE_KIND_FSCS_ONLY:
        return "update", abs_n, "FSCS text refreshed; appending to row"
    if change_kind == CHANGE_KIND_NONE:
        return "update", abs_n, "no semantic changes since last upload"

    return "insert", None, f"unknown change_kind {change_kind!r}; defaulting to insert"


def decide_mode(
    state: Dict[str, Any],
    module_uuid: str,
    *,
    project_name: str,
    product_type: str,
    param_fingerprint: str,
    fscs_sha256: Optional[str] = None,
) -> Tuple[str, Optional[str], str]:
    """Convenience: classify_change then decide_mode_from_kind. Kept
    for callers that don't need the change_kind themselves.
    """
    kind = classify_change(
        state, module_uuid,
        project_name=project_name,
        product_type=product_type,
        param_fingerprint=param_fingerprint,
        fscs_sha256=fscs_sha256,
    )
    return decide_mode_from_kind(state, module_uuid, kind)


# -- post-upload bookkeeping --------------------------------------------- #


def record_insert(
    state: Dict[str, Any],
    module_uuid: str,
    abs_n: str,
    *,
    project_name: str,
    product_type: str,
    param_fingerprint: str,
    fscs_sha256: Optional[str],
    object_text: str,
    realizing_arxml_paths: Iterable[str],
    change_kind: str = CHANGE_KIND_FIRST_INSERT,
) -> None:
    """Replace the state entry for `module_uuid` with a fresh record
    that points at the brand-new DOORS row. covered_* lists are reset
    to the single current value; history starts a new chain.
    """
    modules = state.setdefault("modules", {})
    paths_list = [p for p in realizing_arxml_paths if p]
    now = datetime.now().isoformat(timespec="seconds")
    modules[module_uuid] = {
        "last_success_abs": str(abs_n),
        "last_upload_at": now,
        "current_project_name": project_name,
        "current_product_type": product_type,
        "current_param_fingerprint": param_fingerprint,
        "current_fscs_sha256": fscs_sha256,
        "covered_projects": [project_name] if project_name else [],
        "covered_products": [product_type] if product_type else [],
        "covered_arxml_paths": list(paths_list),
        "last_object_text": object_text,
        "history": [
            {
                "ts": now,
                "project": project_name,
                "product": product_type,
                "param_fingerprint": param_fingerprint,
                "fscs_sha256": fscs_sha256,
                "change_kind": change_kind,
                "abs_n": str(abs_n),
            }
        ],
    }


def record_update(
    state: Dict[str, Any],
    module_uuid: str,
    *,
    project_name: str,
    product_type: str,
    param_fingerprint: str,
    fscs_sha256: Optional[str],
    object_text: str,
    realizing_arxml_paths: Iterable[str],
    change_kind: str,
) -> None:
    """Mutate the existing state entry in place: keep last_success_abs,
    grow covered_* lists, refresh "current_*" markers, replace the
    last_object_text snapshot with the freshly built one, and append
    to history.
    """
    modules = state.setdefault("modules", {})
    entry = modules.get(module_uuid)
    if not entry or not entry.get("last_success_abs"):
        raise RuntimeError(
            f"record_update called for module {module_uuid!r} but state has "
            "no last_success_abs -- did you mean record_insert()?"
        )

    paths_list = [p for p in realizing_arxml_paths if p]

    entry["covered_projects"] = union_preserve_order(
        entry.get("covered_projects") or [], [project_name] if project_name else [],
    )
    entry["covered_products"] = union_preserve_order(
        entry.get("covered_products") or [], [product_type] if product_type else [],
    )
    entry["covered_arxml_paths"] = union_preserve_order(
        entry.get("covered_arxml_paths") or [], paths_list,
    )
    now = datetime.now().isoformat(timespec="seconds")
    entry["last_upload_at"] = now
    entry["current_project_name"] = project_name
    entry["current_product_type"] = product_type
    entry["current_param_fingerprint"] = param_fingerprint
    entry["current_fscs_sha256"] = fscs_sha256
    entry["last_object_text"] = object_text
    history = entry.setdefault("history", [])
    history.append(
        {
            "ts": now,
            "project": project_name,
            "product": product_type,
            "param_fingerprint": param_fingerprint,
            "fscs_sha256": fscs_sha256,
            "change_kind": change_kind,
            "abs_n": str(entry.get("last_success_abs") or ""),
        }
    )


def is_no_change(
    state: Dict[str, Any],
    module_uuid: str,
    *,
    project_name: str,
    product_type: str,
    param_fingerprint: str,
    fscs_sha256: Optional[str],
) -> bool:
    """True iff every "current_*" tracked field matches this run's
    values exactly. Used by `doors_sync.py` to short-circuit literal
    no-op uploads.
    """
    return (
        classify_change(
            state, module_uuid,
            project_name=project_name,
            product_type=product_type,
            param_fingerprint=param_fingerprint,
            fscs_sha256=fscs_sha256,
        )
        == CHANGE_KIND_NONE
    )


def get_last_abs(state: Dict[str, Any], module_uuid: str) -> Optional[str]:
    """Convenience: pull the recorded last_success_abs for a module
    (used by `--force-mode update` in doors_sync)."""
    entry = (state.get("modules") or {}).get(module_uuid) or {}
    abs_n = str(entry.get("last_success_abs") or "").strip()
    return abs_n or None


def get_module_entry(state: Dict[str, Any], module_uuid: str) -> Optional[Dict[str, Any]]:
    """Read-only access to the state entry for a module. Returns None
    if not present. Callers MUST NOT mutate the returned dict.
    """
    entry = (state.get("modules") or {}).get(module_uuid)
    return entry if isinstance(entry, dict) else None
