"""XLSX round-trip helpers for operator edits to ``fscs.json``.

The workbook (``fscs_edit.xlsx``) is a spreadsheet-friendly projection
of the authoritative ``FSCSDocument``. It is not a second source of
truth: export always starts from ``fscs.json`` and import re-validates
back into the Pydantic model before rewriting JSON and the derived
FSCS text views.

UX features applied at export time:

* **Data-validation drop-downs** on seven constrained columns
  (``used_flag``, ``product_type``, ``rw_state``,
  ``service_22_support``, ``service_2e_support``, ``data_type``,
  ``storage_position``). Operators pick from the canonical enum list
  instead of free-typing — the import-side Pydantic validator still
  catches anyone pasting raw text over a drop-down cell.
* **Auto-fit column widths** based on header + cell content (capped
  at 60 chars; CJK glyphs counted at 1.7× ASCII width).
* **Frozen header row** + **autofilter** so long DID lists stay
  navigable without losing the column legend.

The library split is deliberate:

* ``xlsxwriter`` is write-only and is the right tool for building a
  workbook with formatting + validations. Already pinned for the
  DOORS payload builder.
* ``openpyxl`` is read-only at import time (``read_only=True``,
  ``data_only=True``) so the import path stays memory-light even for
  large workbooks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

import openpyxl
import xlsxwriter

from .loader import load_fscs_json
from .schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSSecurityLevel,
    normalize_did_hex,
)


XLSX_COLUMNS: List[str] = [
    "used_flag",
    # Per-DID product-type tag — single source of truth for both
    # the Phase 2 multi-product filter and the Phase 4 DOORS
    # ``RB_Product`` cell. Default ``Common`` (applies to every
    # product); a non-empty non-Common value (e.g. ``DPB`` /
    # ``ESP``) restricts the DID to runs targeting that product
    # and supplies the value for the DOORS upload's
    # ``RB_Product`` column. Positioned right after ``used_flag``
    # so the operator's review eye flows from "is this DID in
    # scope?" to "which product does it apply to?" before the
    # identity columns.
    "product_type",
    "did_hex",
    "did_name",
    "did_name_zh",
    "rw_state",
    "service_22_support",
    "service_2e_support",
    "data_type",
    "storage_position",
    "size_bytes",
    "nvm_item",
    "service_22_behavior",
    "service_22_sessions",
    "service_22_security_levels",
    "service_2e_behavior",
    "service_2e_sessions",
    "service_2e_security_levels",
]


# Canonical allowed values per constrained column. The export side
# attaches Excel ``list``-type data validations sourced from these
# tuples; the import side relies on the Pydantic validators (the
# schema's ``DataType`` / ``StoragePos`` / ``RwState`` Literal types)
# to enforce the same set after the workbook is read back. Keeping
# the lists here (not just at the schema) lets the spreadsheet
# render the drop-down without importing Pydantic into xlsxwriter.
_BOOL_VALUES: Tuple[str, ...] = ("TRUE", "FALSE")
_PRODUCT_VALUES: Tuple[str, ...] = (
    "Common", "DPB", "ESP", "ESPCL", "IPB", "RBU",
)
_RW_VALUES: Tuple[str, ...] = ("R", "W", "RW")
_DATA_TYPE_VALUES: Tuple[str, ...] = (
    "ASCII", "Unsigned", "Signed", "HEX", "Bytefield",
    "Texttable", "enum", "Linear", "Identity",
)
_STORAGE_VALUES: Tuple[str, ...] = ("EEPROM", "RAM", "ROM")

VALIDATIONS: dict[str, Tuple[str, ...]] = {
    "used_flag": _BOOL_VALUES,
    "product_type": _PRODUCT_VALUES,
    "rw_state": _RW_VALUES,
    "service_22_support": _BOOL_VALUES,
    "service_2e_support": _BOOL_VALUES,
    "data_type": _DATA_TYPE_VALUES,
    "storage_position": _STORAGE_VALUES,
}


# Column-width fudge constants. Excel's default font (Calibri 11)
# renders a single CJK glyph at roughly 1.7× the width of an ASCII
# glyph; the column-width unit is "character widths of the '0'
# digit". A flat 1.7 multiplier on every CJK char overshoots Latin
# text in mixed cells, so we attribute the extra width per-glyph.
_CJK_EXTRA_WIDTH = 1.0
_MIN_COL_WIDTH = 8.0
_MAX_COL_WIDTH = 60.0
_WIDTH_PADDING = 2.0


def export_fscs_xlsx(fscs_json: Path, xlsx_path: Path) -> int:
    """Write an editable XLSX projection of ``fscs_json``.

    Returns the number of DID rows exported. The workbook lands at
    ``xlsx_path`` and contains a single sheet named ``fscs_edit``.
    Header row is bold + frozen + autofiltered; constrained columns
    carry drop-down validations; column widths auto-fit to content.
    """

    doc = load_fscs_json(fscs_json)
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)

    rows: List[dict[str, str]] = [_did_to_row(did) for did in doc.dids]

    workbook = xlsxwriter.Workbook(str(xlsx_path))
    try:
        header_format = workbook.add_format({
            "bold": True,
            "bg_color": "#D9E1F2",
            "border": 1,
            "align": "left",
            "valign": "vcenter",
        })
        cell_format = workbook.add_format({
            "valign": "top",
        })

        worksheet = workbook.add_worksheet("fscs_edit")

        for col_idx, column in enumerate(XLSX_COLUMNS):
            worksheet.write_string(0, col_idx, column, header_format)

        for row_idx, row in enumerate(rows, start=1):
            for col_idx, column in enumerate(XLSX_COLUMNS):
                worksheet.write_string(
                    row_idx, col_idx, row.get(column, ""), cell_format,
                )

        n_rows = len(rows)
        n_cols = len(XLSX_COLUMNS)

        if n_rows == 0:
            data_last_row = 1
        else:
            data_last_row = n_rows

        for column, allowed in VALIDATIONS.items():
            col_idx = XLSX_COLUMNS.index(column)
            worksheet.data_validation(
                1, col_idx, data_last_row, col_idx,
                {
                    "validate": "list",
                    "source": list(allowed),
                    "input_title": f"Pick {column}",
                    "input_message": (
                        f"Allowed: {', '.join(allowed)}"
                    ),
                    "error_title": "Invalid value",
                    "error_message": (
                        f"{column} must be one of: {', '.join(allowed)}"
                    ),
                },
            )

        for col_idx, column in enumerate(XLSX_COLUMNS):
            width = _column_width(column, rows)
            worksheet.set_column(col_idx, col_idx, width, cell_format)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, max(data_last_row, 1), n_cols - 1)
    finally:
        workbook.close()

    return len(rows)


def import_fscs_xlsx(fscs_json: Path, xlsx_path: Path) -> FSCSDocument:
    """Apply operator edits from ``xlsx_path`` onto ``fscs_json``.

    The workbook must contain one row per existing DID. DID identity
    is matched by ``did_hex`` (``0x0101`` on export; common hex
    spellings are accepted on import); reordering rows is allowed,
    but adding or deleting DID rows is rejected so accidental
    spreadsheet edits do not silently change scope.

    Only the first sheet is read. Cells are coerced to strings on
    the fly so a numeric cell (e.g. ``size_bytes`` typed as a
    number in Excel) still round-trips correctly.
    """

    doc = load_fscs_json(fscs_json)
    by_did = {did.did_hex: did for did in doc.dids}

    workbook = openpyxl.load_workbook(
        filename=str(xlsx_path), data_only=True, read_only=True,
    )
    try:
        sheet = workbook.worksheets[0]
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            raise ValueError(
                "fscs_edit.xlsx has no header row"
            )

        headers = [
            (str(cell).strip() if cell is not None else "")
            for cell in header_row
        ]
        present = set(h for h in headers if h)
        missing_columns = [col for col in XLSX_COLUMNS if col not in present]
        if missing_columns:
            raise ValueError(
                "XLSX missing required column(s): "
                + ", ".join(missing_columns)
            )

        col_index = {h: i for i, h in enumerate(headers) if h}

        seen: set[str] = set()
        for line_no, raw_row in enumerate(rows_iter, start=2):
            row = _cells_to_row(raw_row, headers)
            if not any(value for value in row.values()):
                continue

            did_hex_raw = row.get("did_hex", "").strip()
            did_hex = normalize_did_hex(did_hex_raw)
            if not did_hex:
                raise ValueError(
                    f"Row {line_no}: did_hex is required"
                )
            if did_hex in seen:
                raise ValueError(
                    f"Row {line_no}: duplicate did_hex {did_hex}"
                )
            if did_hex not in by_did:
                raise ValueError(
                    f"Row {line_no}: DID {did_hex} does not exist in fscs.json"
                )
            seen.add(did_hex)
            _apply_row(by_did[did_hex], row, line_no=line_no)
    finally:
        workbook.close()

    missing_rows = sorted(set(by_did) - seen)
    if missing_rows:
        raise ValueError(
            "XLSX is missing DID row(s): " + ", ".join(missing_rows)
        )

    return FSCSDocument.model_validate(doc.model_dump())


def _did_to_row(did: DIDFscsEntry) -> dict[str, str]:
    return {
        "used_flag": _bool_to_cell(did.service_22.used or did.service_2e.used),
        "did_hex": _format_did_hex(did.did_hex),
        "did_name": did.did_name,
        "did_name_zh": did.did_name_zh or "",
        "rw_state": did.rw_state,
        "service_22_support": _bool_to_cell(did.service_22.supported),
        "service_2e_support": _bool_to_cell(did.service_2e.supported),
        "data_type": did.data_type,
        "storage_position": did.storage_position,
        "size_bytes": str(did.size_bytes),
        "nvm_item": did.nvm_item,
        "service_22_behavior": did.service_22.behavior,
        "service_22_sessions": _list_to_cell(did.service_22.sessions),
        "service_22_security_levels": _security_to_cell(did.service_22.security_levels),
        "service_2e_behavior": did.service_2e.behavior,
        "service_2e_sessions": _list_to_cell(did.service_2e.sessions),
        "service_2e_security_levels": _security_to_cell(did.service_2e.security_levels),
        "product_type": did.product_type or "Common",
    }


def _cells_to_row(
    raw_row: Tuple, headers: List[str],
) -> dict[str, str]:
    """Coerce one openpyxl row tuple to ``column -> str`` mapping."""
    row: dict[str, str] = {}
    for col_idx, header in enumerate(headers):
        if not header:
            continue
        if col_idx >= len(raw_row):
            row[header] = ""
            continue
        value = raw_row[col_idx]
        if value is None:
            row[header] = ""
        elif isinstance(value, bool):
            row[header] = "TRUE" if value else "FALSE"
        elif isinstance(value, float) and value.is_integer():
            row[header] = str(int(value))
        else:
            row[header] = str(value)
    return row


def _apply_row(did: DIDFscsEntry, row: dict[str, str], *, line_no: int) -> None:
    used_flag = _cell_to_bool(_required(row, "used_flag", line_no), line_no)

    did.did_name = _required(row, "did_name", line_no)
    did.did_name_zh = _optional(row, "did_name_zh")
    did.rw_state = _required(row, "rw_state", line_no)
    product_type_value = _optional(row, "product_type")
    did.product_type = product_type_value or "Common"
    did.data_type = _required(row, "data_type", line_no)
    did.storage_position = _required(row, "storage_position", line_no)
    did.size_bytes = _positive_int(_required(row, "size_bytes", line_no), line_no)
    did.nvm_item = _optional(row, "nvm_item") or ""

    did.service_22.supported = _cell_to_bool(
        _required(row, "service_22_support", line_no), line_no
    )
    did.service_22.used = used_flag
    did.service_22.behavior = row.get("service_22_behavior") or ""
    did.service_22.sessions = _cell_to_list(row.get("service_22_sessions", ""))
    did.service_22.security_levels = _cell_to_security(
        row.get("service_22_security_levels", ""), line_no
    )
    did.service_2e.supported = _cell_to_bool(
        _required(row, "service_2e_support", line_no), line_no
    )
    did.service_2e.used = used_flag
    did.service_2e.behavior = row.get("service_2e_behavior") or ""
    did.service_2e.sessions = _cell_to_list(row.get("service_2e_sessions", ""))
    did.service_2e.security_levels = _cell_to_security(
        row.get("service_2e_security_levels", ""), line_no
    )


def _column_width(column: str, rows: List[dict[str, str]]) -> float:
    """Heuristic column width for xlsxwriter ``set_column``.

    Excel measures column width in "characters of the default font's
    '0' digit". We approximate it by counting characters in the
    header + every cell, applying a CJK fudge so Chinese names don't
    end up truncated. Capped at 60 to keep the layout sane when a
    long behaviour-text cell sneaks in.
    """
    samples = [column]
    samples.extend(row.get(column, "") for row in rows)
    raw_max = max((_visual_width(s) for s in samples), default=0.0)
    width = raw_max + _WIDTH_PADDING
    if width < _MIN_COL_WIDTH:
        return _MIN_COL_WIDTH
    if width > _MAX_COL_WIDTH:
        return _MAX_COL_WIDTH
    return width


def _visual_width(text: str) -> float:
    """Approximate visual width of a string in Calibri 11 units.

    Latin char ≈ 1.0; CJK glyph ≈ 1.0 + ``_CJK_EXTRA_WIDTH`` (default
    1.7×). Treats the longest line if the text contains newlines.
    """
    if not text:
        return 0.0
    longest = max(text.splitlines() or [text], key=len)
    width = 0.0
    for ch in longest:
        if _is_cjk(ch):
            width += 1.0 + _CJK_EXTRA_WIDTH
        else:
            width += 1.0
    return width


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0xFF00 <= code <= 0xFFEF
    )


def _required(row: dict[str, str], column: str, line_no: int) -> str:
    value = (row.get(column) or "").strip()
    if not value:
        raise ValueError(f"Row {line_no}: {column} is required")
    return value


def _optional(row: dict[str, str], column: str) -> str | None:
    value = (row.get(column) or "").strip()
    return value or None


def _positive_int(raw: str, line_no: int) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"Row {line_no}: size_bytes must be an integer") from exc
    if value < 1:
        raise ValueError(f"Row {line_no}: size_bytes must be positive")
    return value


def _bool_to_cell(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _format_did_hex(did_hex: str) -> str:
    return f"0x{did_hex.upper()}"


def _cell_to_bool(raw: str, line_no: int) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Row {line_no}: expected TRUE/FALSE boolean, got {raw!r}")


def _list_to_cell(values: Iterable[str]) -> str:
    return ";".join(values)


def _cell_to_list(raw: str) -> List[str]:
    return [item.strip() for item in raw.split(";") if item.strip()]


def _security_to_cell(values: Iterable[FSCSSecurityLevel]) -> str:
    parts = []
    for item in values:
        parts.append(f"{item.level}:{item.note or ''}")
    return ";".join(parts)


def _cell_to_security(raw: str, line_no: int) -> List[FSCSSecurityLevel]:
    result: List[FSCSSecurityLevel] = []
    for part in _cell_to_list(raw):
        level, sep, note = part.partition(":")
        if not sep:
            level, note = part, ""
        try:
            result.append(FSCSSecurityLevel(level=level.strip(), note=note.strip() or None))
        except Exception as exc:  # noqa: BLE001 - add XLSX row context
            raise ValueError(
                f"Row {line_no}: invalid security level entry {part!r}"
            ) from exc
    return result
