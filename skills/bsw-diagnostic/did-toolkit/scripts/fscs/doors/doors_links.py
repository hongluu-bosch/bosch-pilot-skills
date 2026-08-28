#!/usr/bin/env python3
"""Build the DOORS-Link upload workbook for the DID FSCS pipeline.

After the two FSCS content workbooks are uploaded successfully, every
DID in the DOORS module exists as TWO consecutive rows:

    row N      (FS) -- carries Object Heading
    row N+1    (CS) -- carries Object Text

The skill then has to call the MCP `update_doors_links` tool with one
xlsx that points each CS row at its matching FS row (i.e. the
"Customer Spec implements Functional Spec" relationship). DOORS
rejects link xlsx files whose layout doesn't match its expected
columns; the convention is::

    sizeRow / N(str) / sizeColumn / 6(str)
    | Source Module | Source AbsoluteNumber | Target Module | Target AbsoluteNumber | Link Type | Link Module |
    | <doc_uuid>    | <CS_abs>              | <doc_uuid>    | <FS_abs>              | Realisation | <link_module_uuid> |
    ...

The ``Link Type`` and ``Link Module`` come from the
``links:`` block of ``.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`` -- both are project
specific, so the orchestrator NO-OPs link generation (with a warning)
when either is blank.

This module does NOT try to download a fresh export to discover the
real CS/FS AbsoluteNumbers -- that is the orchestrator's job (see
``doors_sync.reconcile_did_rows``). It accepts the ready-to-link
mapping ``[(cs_abs, fs_abs), ...]`` from its caller.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SKILL_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = SKILL_ROOT / "outputs" / "doors" / "doors_upload_links.xlsx"

LINK_COLUMNS: List[str] = [
    "Source Module",
    "Source AbsoluteNumber",
    "Target Module",
    "Target AbsoluteNumber",
    "Link Type",
    "Link Module",
]


@dataclass(frozen=True)
class LinkEntry:
    """One row in the link upload workbook."""
    cs_abs: str
    fs_abs: str
    did_hex: str
    service: str  # "22" or "2E"


def _write_xlsx(
    *,
    out_path: Path,
    rows: List[Dict[str, Any]],
    sheet_name: str = "Links",
    size_row: int = 1,
    header_row: int = 2,
    data_start: int = 3,
) -> int:
    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "xlsxwriter is required to build the DOORS link xlsx. "
            "Install with: python -m pip install xlsxwriter"
        ) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(str(out_path))
    try:
        worksheet = workbook.add_worksheet(sheet_name)
        total_rows = (data_start - 1) + len(rows)
        total_cols = len(LINK_COLUMNS)

        sr0 = size_row - 1
        worksheet.write(sr0, 0, "sizeRow")
        worksheet.write(sr0, 1, str(total_rows))
        worksheet.write(sr0, 2, "sizeColumn")
        worksheet.write(sr0, 3, str(total_cols))

        hr0 = header_row - 1
        for ci, header_name in enumerate(LINK_COLUMNS):
            worksheet.write(hr0, ci, header_name)

        ds0 = data_start - 1
        for ri, row_data in enumerate(rows):
            for ci, header_name in enumerate(LINK_COLUMNS):
                v = row_data.get(header_name, "")
                if v is None or v == "":
                    worksheet.write_blank(ds0 + ri, ci, None)
                else:
                    worksheet.write(ds0 + ri, ci, v)
    finally:
        workbook.close()
    return len(rows)


def build_link_xlsx(
    *,
    out_path: Path,
    entries: Iterable[LinkEntry],
    source_module_uuid: str,
    target_module_uuid: str,
    link_type: str,
    link_module_uuid: str,
    direction: str = "cs_to_fs",
    sheet_name: str = "Links",
) -> int:
    """Render the link xlsx.

    `direction='cs_to_fs'` (the default, matches the user's spec):
        Source = CS row, Target = FS row.
    `direction='fs_to_cs'` is provided for symmetry; flip the role of
        the CS / FS arguments instead of editing this file.
    """
    rows: List[Dict[str, Any]] = []
    for entry in entries:
        if direction == "cs_to_fs":
            src_abs, tgt_abs = entry.cs_abs, entry.fs_abs
        elif direction == "fs_to_cs":
            src_abs, tgt_abs = entry.fs_abs, entry.cs_abs
        else:
            raise ValueError(f"unsupported direction: {direction!r}")
        if not src_abs or not tgt_abs:
            continue
        rows.append({
            "Source Module": source_module_uuid,
            "Source AbsoluteNumber": str(src_abs),
            "Target Module": target_module_uuid,
            "Target AbsoluteNumber": str(tgt_abs),
            "Link Type": link_type,
            "Link Module": link_module_uuid,
        })
    return _write_xlsx(out_path=out_path, rows=rows, sheet_name=sheet_name)


def _service_for_idx(
    idx: int,
    service_ranges: Optional[Dict[str, Tuple[int, int]]],
) -> str:
    """Return the service whose ``[start, end)`` range contains ``idx``.

    Returns ``""`` when ``service_ranges`` is None (legacy callers
    that still want unannotated entries) or when ``idx`` falls
    outside every range (e.g. a heading match BEFORE the first
    anchor — should not happen in practice).
    """
    if not service_ranges:
        return ""
    for svc, (start, end) in service_ranges.items():
        if start <= idx < end:
            return svc
    return ""


def reconcile_did_rows(
    *,
    rows: List[Dict[str, Any]],
    did_hex_to_heading: Dict[str, str],
    heading_field: str = "DescriptionOfRequirementRB",
    service_ranges: Optional[Dict[str, Tuple[int, int]]] = None,
) -> List[LinkEntry]:
    """Walk a fresh DOORS export's row list and pair up each DID's FS
    row (the row whose `heading_field` equals the FS heading text)
    with the row immediately after it (the CS row that carries the
    Object Text we just uploaded).

    Returns one `LinkEntry` per matched DID×service. DIDs that
    cannot be located are silently skipped — the caller
    (orchestrator) is expected to log them.

    v1.17.1: ``service_ranges`` lets the caller carve the row list
    into per-service slices using the resolved anchor row indices.
    A DID effective in both services then yields TWO ``LinkEntry``
    instances (one with ``service="22"`` and the actual 22-block
    AbsoluteNumbers, one with ``service="2E"`` and the 2E-block
    AbsoluteNumbers). Without ``service_ranges`` the function
    falls back to v1.16.0 behaviour and stamps ``service=""``,
    leaving the disambiguation to the caller (which only works
    when no DID is in both services). Pre-v1.17.1 callers stay
    source-compatible because the parameter is optional.

    The dict shape is ``{"22": (start_inclusive, end_exclusive),
    "2E": (start_inclusive, end_exclusive)}``; the orchestrator
    builds it from the resolved anchor positions in the fresh
    export.
    """
    out: List[LinkEntry] = []
    if not isinstance(rows, list):
        return out

    heading_to_did = {str(v).strip(): k for k, v in did_hex_to_heading.items() if str(v).strip()}

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        cell = row.get(heading_field)
        if not isinstance(cell, str):
            continue
        text = cell.strip()
        did_hex = heading_to_did.get(text)
        if did_hex is None:
            continue
        fs_abs = str(row.get("AbsoluteNumber") or "")
        cs_abs = ""
        if idx + 1 < len(rows):
            nxt = rows[idx + 1]
            if isinstance(nxt, dict):
                cs_abs = str(nxt.get("AbsoluteNumber") or "")
        if fs_abs and cs_abs:
            service = _service_for_idx(idx, service_ranges)
            out.append(LinkEntry(
                cs_abs=cs_abs, fs_abs=fs_abs,
                did_hex=did_hex, service=service,
            ))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    """Standalone CLI: read a JSON list of `[cs_abs, fs_abs, did_hex,
    service]` tuples and produce the link xlsx. Used for hand-driven
    repairs; the orchestrator wires `build_link_xlsx` directly."""
    p = argparse.ArgumentParser(
        prog="did-toolkit/doors_links.py",
        description="Build the DOORS-Link upload workbook for the DID FSCS pipeline.",
    )
    p.add_argument("entries_json", help="Path to JSON list of entries (cs_abs, fs_abs, did_hex, service)")
    p.add_argument("--source-module-uuid", required=True)
    p.add_argument("--target-module-uuid", required=True)
    p.add_argument("--link-type", default="Realisation")
    p.add_argument("--link-module-uuid", default="")
    p.add_argument("--direction", default="cs_to_fs", choices=("cs_to_fs", "fs_to_cs"))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    args = p.parse_args(argv)

    raw = json.loads(Path(args.entries_json).read_text(encoding="utf-8-sig"))
    entries = [
        LinkEntry(
            cs_abs=str(item.get("cs_abs", item.get("CS", ""))),
            fs_abs=str(item.get("fs_abs", item.get("FS", ""))),
            did_hex=str(item.get("did_hex", "")),
            service=str(item.get("service", "")),
        )
        for item in raw
        if isinstance(item, dict)
    ]
    n = build_link_xlsx(
        out_path=Path(args.out),
        entries=entries,
        source_module_uuid=args.source_module_uuid,
        target_module_uuid=args.target_module_uuid,
        link_type=args.link_type,
        link_module_uuid=args.link_module_uuid,
        direction=args.direction,
    )
    print(json.dumps({"rows_written": n, "out": args.out}, ensure_ascii=False))
    return 0


__all__ = ["LinkEntry", "build_link_xlsx", "reconcile_did_rows"]


if __name__ == "__main__":
    raise SystemExit(main())
