"""Locate per-service anchor rows inside a downloaded DOORS export.

The DOORS export from the MCP `get_doors_module` tool is a dict shaped
like::

    {"code": 0, "message": "OK",
     "data": {"rows": [{"AbsoluteNumber": "401",
                        "DescriptionOfRequirementRB": "...",
                        ...}, ...]}}

(or, on some legacy exports, the rows live at the top level rather
than under ``data.rows`` -- the loader below handles both.)

The DID-toolkit DOORS upload uses TWO anchors in the same module:

* the row that introduces the ReadDataByIdentifier ($22) section, and
* the row that introduces the WriteDataByIdentifier ($2E) section.

Both anchors are configured in ``.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`` under
``anchors.service_22.text`` and ``anchors.service_2e.text`` as the
exact ``DescriptionOfRequirementRB`` text the row carries. The user
explicitly supplied these strings; the lookup here is a verbatim
match (after trimming surrounding whitespace and collapsing internal
whitespace) so wraparound differences across exports do not matter.

A ``by_absolute_number`` override lets the user pin the anchor by
hand if the keyword text ever changes upstream.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class AnchorMatch:
    """Result of resolving one anchor.

    Attributes
    ----------
    service : str
        ``"22"`` or ``"2E"``.
    anchor_address : str
        The DOORS row identifier (read from the export's
        ``AbsoluteNumber`` field) of the anchor row. New INSERT
        rows will carry this value in their ``Destination Object``
        cell so DOORS lays them down sequentially after this row.
        Always a string -- DOORS' upload xlsx wants the cell as
        text and this lets us round-trip leading zeros without
        accidental truncation.

        v1.17.2 rename note: this field used to be called
        ``absolute_number`` but operators kept confusing it with
        the upload xlsx's ``"Absolute Number"`` column header
        (which is what UPDATE rows put their recorded landing in).
        ``anchor_address`` makes the role clear at every read site
        (``anchor.anchor_address``) without touching the DOORS API
        field name (we still ``row.get("AbsoluteNumber")`` from the
        export — that's a DOORS-side constraint) or the upload
        column header (operator template constraint).
    rule : str
        Human-readable description of how the anchor was resolved
        (``"by_absolute_number"`` / ``"by_text"`` / ``"by_text+normalized"``).
    raw_row : dict | None
        The raw row dict from the export, for diagnostic dumps. ``None``
        when the anchor was resolved by ``by_absolute_number`` and we
        never had to look at any rows.
    """

    service: str
    anchor_address: str
    rule: str
    raw_row: Optional[Dict[str, Any]]


_WS_RE = re.compile(r"\s+")


def _normalise(text: Optional[str]) -> str:
    """Collapse all whitespace runs to a single space and strip ends."""
    if text is None:
        return ""
    return _WS_RE.sub(" ", text).strip()


def load_export(path: Path) -> List[Dict[str, Any]]:
    """Load a DOORS export JSON and return its row list, regardless of
    which of the two known shapes the file uses."""
    if not path.is_file():
        raise FileNotFoundError(
            f"DOORS export missing: {path}\n"
            "  Run `python scripts/fscs/doors/doors_fetch.py` first, "
            "or hand-place the export from the doors MCP `get_doors_module` "
            "tool."
        )
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"DOORS export must be a JSON object, got {type(payload).__name__}")

    data_block = payload.get("data") if isinstance(payload.get("data"), dict) else None
    if data_block is not None and isinstance(data_block.get("rows"), list):
        return [r for r in data_block["rows"] if isinstance(r, dict)]
    if isinstance(payload.get("rows"), list):
        return [r for r in payload["rows"] if isinstance(r, dict)]
    raise ValueError(
        "DOORS export has neither `data.rows` nor `rows`; cannot locate anchor."
    )


def _resolve_one(
    rows: List[Dict[str, Any]],
    *,
    service: str,
    cfg: Dict[str, Any],
) -> AnchorMatch:
    by_abs = cfg.get("by_absolute_number")
    if by_abs not in (None, ""):
        return AnchorMatch(
            service=service,
            anchor_address=str(by_abs),
            rule="by_absolute_number",
            raw_row=None,
        )

    text = cfg.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(
            f"anchors.service_{service.lower()}.text is empty and no "
            "by_absolute_number override is set."
        )
    field = cfg.get("heading_field") or "DescriptionOfRequirementRB"

    needle = text.strip()
    needle_norm = _normalise(needle)

    for row in rows:
        cell = row.get(field)
        if not isinstance(cell, str):
            continue
        if cell.strip() == needle:
            return AnchorMatch(service, str(row.get("AbsoluteNumber") or ""), "by_text", row)

    for row in rows:
        cell = row.get(field)
        if not isinstance(cell, str):
            continue
        if _normalise(cell) == needle_norm:
            return AnchorMatch(
                service,
                str(row.get("AbsoluteNumber") or ""),
                "by_text+normalized",
                row,
            )

    snippet = needle.splitlines()[0][:80] if needle else ""
    raise LookupError(
        f"Anchor for service ${service} not found in DOORS export.\n"
        f"  Looked under field {field!r} for text starting with: {snippet!r}\n"
        f"  Either the export is stale -- re-run `doors_fetch` -- or set\n"
        f"  anchors.service_{service.lower()}.by_absolute_number in "
        ".DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml."
    )


def resolve_anchors(
    rows: List[Dict[str, Any]],
    anchors_cfg: Dict[str, Any],
    *,
    services: Iterable[str] = ("22", "2E"),
) -> Dict[str, AnchorMatch]:
    """Resolve every requested service anchor.

    Parameters
    ----------
    rows
        Row list from :func:`load_export`.
    anchors_cfg
        The ``anchors:`` block of ``.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`` -- a
        dict with ``service_22`` / ``service_2e`` sub-blocks.
    services
        Which services to resolve. Defaults to both. Pass a single
        service for a partial run.
    """
    if not isinstance(anchors_cfg, dict):
        raise ValueError("anchors block in doors_mapping.yaml must be a mapping")

    out: Dict[str, AnchorMatch] = {}
    for service in services:
        key = f"service_{service.lower()}"
        cfg = anchors_cfg.get(key)
        if not isinstance(cfg, dict):
            raise ValueError(
                f"anchors.{key} block missing in doors_mapping.yaml; "
                "every emitted service needs an anchor."
            )
        out[service] = _resolve_one(rows, service=service, cfg=cfg)
    return out


__all__ = ["AnchorMatch", "load_export", "resolve_anchors"]
