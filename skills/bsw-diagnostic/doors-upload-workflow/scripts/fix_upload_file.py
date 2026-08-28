#!/usr/bin/env python
"""
Fix DOORS Excel files that were modified by Excel/WPS.

This script rebuilds the first metadata row (sizeRow/sizeColumn) and rewrites
the workbook using xlsxwriter, which preserves the format expected by the
DOORS upload flow.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Tuple

import pandas as pd
import xlsxwriter


def read_broken_excel(file_path: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read all rows from a possibly damaged DOORS Excel file."""
    df = pd.read_excel(file_path, sheet_name=0, header=None)

    if len(df) < 2:
        raise ValueError("Input Excel must contain at least metadata + header rows.")

    header_row = df.iloc[1].tolist()
    columns: List[str] = []
    for idx, value in enumerate(header_row):
        if pd.notna(value):
            columns.append(str(value))
        else:
            columns.append(f"Column_{idx}")

    data_rows: List[Dict[str, str]] = []
    for row_idx in range(2, len(df)):
        row_data = df.iloc[row_idx].tolist()
        row_dict: Dict[str, str] = {}
        for col_idx, col_name in enumerate(columns):
            if col_idx < len(row_data):
                cell_value = row_data[col_idx]
                row_dict[col_name] = "" if pd.isna(cell_value) else str(cell_value)
            else:
                row_dict[col_name] = ""
        data_rows.append(row_dict)

    return columns, data_rows


def write_fixed_excel(
    output_file: str,
    columns: List[str],
    data_rows: List[Dict[str, str]],
    sheet_name: str,
) -> None:
    """Rewrite the workbook in the DOORS-friendly shape."""
    workbook = xlsxwriter.Workbook(output_file)
    worksheet = workbook.add_worksheet(sheet_name)

    total_rows = 2 + len(data_rows)
    total_cols = len(columns)

    worksheet.write(0, 0, "sizeRow")
    worksheet.write(0, 1, str(total_rows))
    worksheet.write(0, 2, "sizeColumn")
    worksheet.write(0, 3, str(total_cols))

    for col_idx, col_name in enumerate(columns):
        worksheet.write(1, col_idx, col_name)

    for row_idx, row_data in enumerate(data_rows, start=2):
        for col_idx, col_name in enumerate(columns):
            value = row_data.get(col_name, "")
            if value == "":
                worksheet.write_blank(row_idx, col_idx, None)
            else:
                worksheet.write(row_idx, col_idx, value)

    workbook.close()


def verify_output(original_file: str, fixed_file: str) -> bool:
    """Quick sanity check that header and shape match."""
    df_orig = pd.read_excel(original_file, sheet_name=0, header=None)
    df_fixed = pd.read_excel(fixed_file, sheet_name=0, header=None)

    if len(df_orig) < 2 or len(df_fixed) < 2:
        return False

    if df_orig.shape != df_fixed.shape:
        return False

    orig_header = df_orig.iloc[1].tolist()
    fixed_header = df_fixed.iloc[1].tolist()

    for a, b in zip(orig_header, fixed_header):
        if pd.isna(a) and pd.isna(b):
            continue
        if str(a) != str(b):
            return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fix a DOORS Excel file before upload."
    )
    parser.add_argument("input_file", help="Path to source Excel file")
    parser.add_argument("output_file", help="Path to write fixed Excel file")
    parser.add_argument(
        "--sheet-name",
        default="CS Data",
        help="Output worksheet name (default: CS Data)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-write verification",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not os.path.exists(args.input_file):
        print(f"[ERROR] Input file not found: {args.input_file}")
        return 1

    print("[INFO] Reading source file...")
    columns, data_rows = read_broken_excel(args.input_file)
    print(f"[INFO] Columns: {len(columns)}")
    print(f"[INFO] Data rows: {len(data_rows)}")

    print("[INFO] Writing fixed file...")
    write_fixed_excel(args.output_file, columns, data_rows, args.sheet_name)
    print(f"[OK] Fixed file created: {args.output_file}")
    print(f"[INFO] Output size: {os.path.getsize(args.output_file):,} bytes")

    if not args.skip_verify:
        ok = verify_output(args.input_file, args.output_file)
        if ok:
            print("[OK] Verification passed.")
        else:
            print("[WARN] Verification failed. Please review output manually.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
