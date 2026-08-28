"""Consumer-side glue between ``FSCSDocument`` and legacy data shapes.

After the FSCS data source governance migration (Parts 5 and 6 of
``REFACTOR_BRIEF.txt``), ``outputs/fscs/fscs.json`` is the **only**
runtime source of truth. All Phase 2 / Phase 3 / Review code paths
resolve the document through :func:`load_fscs` below, which is a thin
wrapper around :func:`scripts.fscs.load_fscs_json` that adds a single
piece of operator-friendly behaviour: if the JSON is missing it raises
``FileNotFoundError`` with a message pointing at Phase 1.

Legacy ``FSCS_*.txt`` ingestion still exists for one-shot migration of
pre-governance projects, but it lives in :mod:`scripts.fscs.importer`
and is driven exclusively by the ``scripts/fscs_import.py`` CLI. The
runtime consumers never fall back to text parsing, so a typo in
``--fscs-json`` now fails loudly instead of silently regressing to a
stale text view.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .loader import load_fscs_json
from .schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSValueRangeEnum,
    FSCSValueRangeNumeric,
)


# ---------------------------------------------------------------------------
# Source resolution (JSON-only runtime path)
# ---------------------------------------------------------------------------


_PHASE1_HINT = (
    "Run Phase 1 first to regenerate it, e.g.:\n"
    "    python scripts/pipeline.py --phase fscs --input <your-did>.json\n"
    "  or, to migrate a legacy project that only has FSCS_*.txt:\n"
    "    python scripts/fscs_import.py --fscs-22 outputs/fscs/FSCS_22.txt "
    "--fscs-2e outputs/fscs/FSCS_2E.txt -o outputs/fscs/fscs.json"
)


def load_fscs(
    *,
    fscs_json: Optional[Path] = None,
    fscs_22: Optional[Path] = None,
    fscs_2e: Optional[Path] = None,
) -> FSCSDocument:
    """Resolve an authoritative :class:`FSCSDocument` for runtime consumers.

    Resolution order:

    1. Explicit ``fscs_json`` when it points at an existing file.
    2. A sibling ``fscs.json`` next to ``fscs_22`` / ``fscs_2e`` when
       either is supplied (kept for CLI backwards compatibility so the
       legacy ``--fscs-22`` flags still resolve correctly without every
       caller migrating simultaneously).

    Anything else raises :class:`FileNotFoundError` with a remediation
    hint. The runtime path deliberately does **not** fall back to
    parsing ``FSCS_*.txt`` -- that would reintroduce the drift window
    the Part 5/6 governance migration closed.
    """
    if fscs_json is not None and Path(fscs_json).is_file():
        return load_fscs_json(Path(fscs_json))

    for sibling_hint in (fscs_22, fscs_2e):
        if sibling_hint is None:
            continue
        candidate = Path(sibling_hint).parent / "fscs.json"
        if candidate.is_file():
            return load_fscs_json(candidate)

    # Nothing resolvable. Assemble a message that names the paths we
    # tried so users don't have to re-read code to figure out what went
    # wrong.
    tried: List[str] = []
    if fscs_json is not None:
        tried.append(str(fscs_json))
    for sibling_hint in (fscs_22, fscs_2e):
        if sibling_hint is not None:
            tried.append(str(Path(sibling_hint).parent / "fscs.json"))
    tried_block = "\n  - ".join(tried) if tried else "(no candidate path supplied)"
    raise FileNotFoundError(
        "fscs.json not found. FSCS data source governance requires a "
        "canonical fscs.json for all runtime consumers.\n"
        f"Tried:\n  - {tried_block}\n\n{_PHASE1_HINT}"
    )


# ---------------------------------------------------------------------------
# Projections onto legacy dataclasses
# ---------------------------------------------------------------------------


def to_did_implementation_infos(
    document: FSCSDocument,
) -> Tuple[List["DIDImplementationInfo"], List[Dict]]:
    """Project an ``FSCSDocument`` onto the legacy Phase 3 shape.

    Mirrors the old ``parse_both_fscs`` return signature exactly so the
    orchestrator can consume the JSON-derived document without any
    downstream change:

    * Returns ``(valid_dids, validation_report)``.
    * ``valid_dids`` are :class:`DIDImplementationInfo` objects with
      ``rw_state`` already promoted to ``"RW"`` for dual-service DIDs.
    * ``validation_report`` is a list of per-DID dicts
      (``did_hex``, ``did_name``, ``status``, ``errors``) suitable for
      writing to ``validation_report.txt``.
    """
    # Imported lazily to avoid a cycle when implementation.parsers is
    # loaded before scripts.fscs (both sit on sys.path roots).
    from implementation.models import DIDImplementationInfo  # type: ignore

    validation_report: List[Dict] = []
    valid: List[DIDImplementationInfo] = []

    # Legacy ``parse_both_fscs`` iterated ``sorted(all_did_hexes)``, so
    # downstream artifacts (validation_report.txt, pdm_entries.txt,
    # header_*.txt, etc.) all grouped DIDs in hex-ascending order.
    # Preserve that contract here so the JSON-first path is byte-for-byte
    # compatible with the historical text-first path on the same inputs.
    sorted_dids = sorted(document.dids, key=lambda d: d.did_hex)

    for did in sorted_dids:
        hex_with_prefix = f"0x{did.did_hex}"
        report: Dict = {
            "did_hex": hex_with_prefix,
            "did_name": did.did_name,
            "status": "SUCCESS",
            "errors": [],
        }

        # Operator has opted this DID out of downstream emission via
        # the xlsx edit table. The entry stays in
        # ``fscs.json`` (so the document is still a full mirror of the
        # input) but we skip it here the same way we'd skip a DID that
        # fundamentally doesn't support either service: record as
        # ``DESELECTED`` for visibility in validation_report.txt, then
        # move on so the generated C/ARXML exactly matches what the
        # reviewer selected.
        if not did.service_22.effective and not did.service_2e.effective:
            report["status"] = "DESELECTED"
            report["errors"].append(
                "DID deselected in FSCS CSV (used=False on both services); "
                "excluded from generated artefacts by operator choice."
            )
            validation_report.append(report)
            continue

        # Case 1: write-only -- the legacy pipeline refuses these.
        # We use ``effective`` (supported AND used) so a DID whose 22
        # side was deselected is treated the same as one that
        # structurally lacks Read support.
        if did.service_2e.effective and not did.service_22.effective:
            report["status"] = "ERROR"
            report["errors"].append(
                "DID found only in FSCS_2E.txt, write-only DIDs are not supported"
            )
            validation_report.append(report)
            continue

        # Case 2 & 3: RDBI-only or RDBI+WDBI. The extra validation
        # rules (write must use extendedDiagnosticSession + L1) fire
        # only when 2E is also effective (structurally supported AND
        # not deselected by the operator).
        if did.service_2e.effective:
            write = did.service_2e
            if "extendedDiagnosticSession" not in write.sessions:
                report["errors"].append(
                    f"Write must support extendedDiagnosticSession, "
                    f"current: {write.sessions}"
                )
            write_levels = {sl.level for sl in write.security_levels}
            if write_levels != {"L1"}:
                report["errors"].append(
                    f"Write must use security level L1, current: "
                    f"{sorted(write_levels)}"
                )

        info = _to_info(did, DIDImplementationInfo)
        # Operator may have deselected only the 2E half of an RW DID;
        # demote rw_state so downstream emits read-only C without the
        # write function. Effective read is guaranteed to be True here
        # because the two gate branches above already filtered out the
        # all-deselected and write-only cases.
        info.rw_state = "RW" if did.service_2e.effective else "R"
        if report["errors"]:
            # Legacy ``parse_both_fscs`` uses ``SKIPPED`` for recoverable
            # per-DID issues and reserves ``ERROR`` for the hard
            # write-only case above. Mirror that for byte-for-byte
            # parity of the validation report.
            report["status"] = "SKIPPED"
        else:
            valid.append(info)
        validation_report.append(report)

    return valid, validation_report


def to_review_dicts(document: FSCSDocument) -> List[Dict]:
    """Project an ``FSCSDocument`` onto the dict shape review tools expect.

    ``review_arxml`` and ``review_impl`` were historically fed the raw
    ``inputs/*.json`` list-of-dicts and reach into fields like
    ``did_name_en``, ``access.service_22``, ``sub_fields[].method_en``.
    After Part 6 they read ``fscs.json`` instead, but we project back to
    the same dict shape so every ``review_*`` method stays untouched --
    the review *logic* is the same, only the source of truth moved.

    Key mappings:

    * ``did_hex``          -- ``"F190"`` (bare upper; the reviewers strip
                              any ``0x`` prefix anyway).
    * ``did_name_en``      -- ``did.did_name``. FSCSDocument doesn't
                              carry the legacy ``_en``/``_zh`` split;
                              ``did_name`` is the English form.
    * ``supported_by_ecu`` -- always ``"Y"``: every DID in
                              ``fscs.json`` is by definition effective
                              (Phase 1 filters at generation time).
    * ``storage_pos``      -- ``did.storage_position`` (same string
                              literals ``"EEPROM"`` / ``"RAM"``).
    * ``access.service_22/_2e`` -- flat ``{"_": "Y"/"N"}`` stub so
                              :meth:`ImplReviewer._supports_any` returns
                              the same verdict as the original nested
                              Y/N tree would have.
    * ``sub_fields[].method_en/range_min_phy/range_max_phy``
                           -- remapped from ``FSCSSubField`` (``enum_mapping``,
                              ``range_min``, ``range_max``) so the
                              ``_has_range`` heuristic keeps working.
    """
    out: List[Dict] = []
    for did in document.dids:
        # Operator-deselected DIDs (``used=False`` on both services)
        # never made it into FSCS_*.txt / ARXML / C, so surfacing them
        # in a reviewer cross-check would be a false-positive forest
        # of "expected but absent" warnings. The reviewer is cross-
        # checking *emitted* artefacts, so we project only the
        # effective set; fully deselected DIDs are silently omitted
        # the same way ``supported=False`` structurally-excluded DIDs
        # always were.
        if not did.service_22.effective and not did.service_2e.effective:
            continue

        sub_fields: List[Dict] = []
        for sub in did.sub_fields:
            sub_fields.append({
                "method_en": sub.enum_mapping or "",
                "range_min_phy": sub.range_min or "",
                "range_max_phy": sub.range_max or "",
                "name_en": sub.name_en,
            })
        out.append({
            "did_hex": did.did_hex,
            "did_name_en": did.did_name,
            "size_bytes": did.size_bytes,
            "rw_state": did.rw_state,
            "storage_pos": did.storage_position,
            "supported_by_ecu": "Y",
            "nvm_item": did.nvm_item,
            "access": {
                # ``effective`` (supported AND used) -- see Adapter
                # docstring. Reviewers consume the emitted set, so the
                # per-service ``Y``/``N`` reflects whether the service
                # actually lands in downstream artefacts.
                "service_22": {
                    "_": "Y" if did.service_22.effective else "N",
                },
                "service_2e": {
                    "_": "Y" if did.service_2e.effective else "N",
                },
            },
            "sub_fields": sub_fields,
        })
    return out


def _to_info(did: DIDFscsEntry, info_cls):
    """Build a :class:`DIDImplementationInfo` from an :class:`DIDFscsEntry`.

    The impl dataclass expects:

    * ``did_hex``      -- ``"0xF190"`` form (with prefix) because Phase
                         3 uses it verbatim in generated source code.
    * ``value_range``  -- the plain-text rendering, not the tagged
                         union. Other consumers re-parse it into enum
                         vs numeric via the ``is_enum`` / ``enum_values``
                         / ``numeric_min`` / ``numeric_max`` fields the
                         projection populates explicitly.
    * ``security_level`` -- a single ``"L0"``/``"L1"`` string (the first
                         read-side level, which matches legacy
                         behaviour for phase-3 code generation).
    * ``sessions``    -- read-side sessions only; Phase 3 ignores the
                         write-side list.
    """
    did_hex = f"0x{did.did_hex}"

    enum_values: List[str] = []
    numeric_min = ""
    numeric_max = ""
    value_range_str = ""
    is_enum = False

    vr = did.value_range
    if isinstance(vr, FSCSValueRangeEnum):
        is_enum = True
        enum_values = list(vr.values)
        value_range_str = f"Enum: {', '.join(vr.values)}"
    elif isinstance(vr, FSCSValueRangeNumeric):
        numeric_min = vr.min
        numeric_max = vr.max
        unit = f" {vr.unit}" if vr.unit else ""
        value_range_str = f"{vr.min} ~ {vr.max}{unit}".rstrip()

    read = did.service_22
    security_level = "L0"
    if read.security_levels:
        security_level = read.security_levels[0].level

    return info_cls(
        did_hex=did_hex,
        did_name=did.did_name,
        data_type=did.data_type,
        storage_pos=did.storage_position,
        size_bytes=str(did.size_bytes),
        rw_state=did.rw_state,
        nvm_item=did.nvm_item,
        value_range=value_range_str,
        is_enum=is_enum,
        enum_values=enum_values,
        numeric_min=numeric_min,
        numeric_max=numeric_max,
        security_level=security_level,
        sessions=list(read.sessions),
        validation_errors=[],
        # v1.27.0: thread Chinese name, product tag, and behaviour
        # text into Phase 3 so the agent's TODO(agent) block can
        # render a self-contained brief inline (no separate
        # ``_briefs/<HEX>_<svc>.md`` artefact).
        did_name_zh=did.did_name_zh or "",
        product_type=did.product_type or "",
        behavior_22=did.service_22.behavior or "",
        behavior_2e=did.service_2e.behavior or "",
    )
