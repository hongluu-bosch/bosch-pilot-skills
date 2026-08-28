"""openpyxl helpers used by pipeline.py (diagcomm-toolkit).

Kept small and side-effect-free. Two surfaces:

    write_cells(template_path, sheet, cell_value_map, out_path)
        Open `template_path`, write each cell -> value, save as `out_path`.
        `sheet` may be None (means: active sheet).

    lint_workbook(xlsx_path) -> list[str]
        Returns a list of human-readable warnings/errors. Empty list = clean.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


def _require_openpyxl():
    try:
        import openpyxl  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on env
        req = (Path(__file__).resolve().parent / "requirements.txt").as_posix()
        raise SystemExit(
            "diagcomm-toolkit: 'openpyxl' is not installed. "
            f"Run: python -m pip install -r {req}"
        ) from exc


def write_cells(
    template_path: str | Path,
    sheet: Optional[str],
    cell_value_map: Dict[str, Any],
    out_path: str | Path,
) -> None:
    _require_openpyxl()
    import openpyxl

    template_path = Path(template_path)
    out_path = Path(out_path)
    if not template_path.exists():
        raise FileNotFoundError(f"template not found: {template_path}")

    wb = openpyxl.load_workbook(template_path)
    if sheet is None or sheet == "":
        ws = wb.active
    else:
        if sheet not in wb.sheetnames:
            raise KeyError(
                f"sheet {sheet!r} not in template; available: {wb.sheetnames}"
            )
        ws = wb[sheet]

    for cell_ref, value in cell_value_map.items():
        ws[cell_ref] = value

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)


def lint_workbook(xlsx_path: str | Path) -> List[str]:
    _require_openpyxl()
    import openpyxl

    xlsx_path = Path(xlsx_path)
    issues: List[str] = []
    if not xlsx_path.exists():
        return [f"file not found: {xlsx_path}"]
    if xlsx_path.suffix.lower() != ".xlsx":
        issues.append(f"unexpected extension: {xlsx_path.suffix} (want .xlsx)")
    try:
        wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    except Exception as exc:
        return [f"openpyxl could not load workbook: {exc}"]

    if not wb.sheetnames:
        issues.append("workbook has no sheets")
        return issues

    populated_any = False
    for name in wb.sheetnames:
        ws = wb[name]
        max_row = ws.max_row or 0
        max_col = ws.max_column or 0
        if max_row >= 1 and max_col >= 1:
            for row in ws.iter_rows(values_only=True, max_row=min(max_row, 50)):
                if any(cell not in (None, "") for cell in row):
                    populated_any = True
                    break
        if populated_any:
            break

    if not populated_any:
        issues.append("workbook appears empty (no non-blank cells in first 50 rows)")

    return issues
