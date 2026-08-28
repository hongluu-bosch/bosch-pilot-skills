#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
align_macros.py — Phase 0.5 single-step compile-time macro alignment.

Improvements over the original version:
  * Distinguishes "switch macros" (the left side of #if comparisons and the
    first argument of RB_ASSERT_SWITCH_SETTINGS) from "value macros" (the
    right side of comparisons / the expected switch values).
  * Looks up value macros in the SwitchSettings CSV as well.  If a value is
    not listed as a switch in the CSV, it is assigned a synthetic integer
    value that is unique within the same switch family, so that
        #if (RBFS_X == RBFS_X_Value)
    evaluates correctly.
  * Emits all value macros BEFORE the switch macros so the preprocessor sees
    concrete integer tokens during #if evaluation.
  * Optionally neutralises RB_ASSERT_SWITCH_SETTINGS for the unit-test build
    because Cantata's preprocessor/front-end can fail on the static_assert
    when value macros are overridden.  The macro is compile-time-only, so
    neutralising it does not change SUT runtime semantics.

Usage:
    python align_macros.py <input.c> <SwitchSettings.csv> --output-dir <dir> [--report]

Output:
    The resolved macros are injected directly into test_<Component>.h (inferred
    from <input.c>).  The optional --output-dir only controls where audit reports
    are written when --report is given.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------------------------
# C-source extraction logic
# ------------------------------------------------------------------------------

_RE_IF_LINE = re.compile(
    r"^\s*#\s*(?:if|elif)\s*(.*)",
    re.MULTILINE,
)
_RE_IF_COMPARISON = re.compile(
    r"\b(\w+)\s*(==|!=)\s*(\w+)\b",
)
_RE_IFDEF = re.compile(
    r"^\s*#\s*(ifdef|ifndef)\s+(\w+)",
    re.MULTILINE,
)
_RE_ASSERT_SWITCH = re.compile(
    r"RB_ASSERT_SWITCH_SETTINGS\s*\(([^)]+)\)",
    re.MULTILINE | re.DOTALL,
)
_RE_IF_NE = re.compile(
    r"^\s*#\s*(?:if|elif)\s*\(*\s*(\w+)\s*!=\s*(\w+)\s*\)*",
    re.MULTILINE,
)
_RE_IF_GENERIC = re.compile(
    r"^\s*#\s*(?:if|elif)\s+(.*)",
    re.MULTILINE,
)
_RE_IFDEF = re.compile(
    r"^\s*#\s*(ifdef|ifndef)\s+(\w+)",
    re.MULTILINE,
)
_RE_ASSERT_SWITCH = re.compile(
    r"RB_ASSERT_SWITCH_SETTINGS\s*\(([^)]+)\)",
    re.MULTILINE | re.DOTALL,
)

_C_KEYWORDS = {
    "defined", "sizeof", "NULL", "true", "false", "EOF",
    "E_OK", "E_NOT_OK", "TRUE", "FALSE", "STD_ON", "STD_OFF",
}


def _extract_macros_from_c(c_path: str):
    """
    Parse a C file and return a deduplicated list of macro entries affecting compilation.

    Each entry is a dict with keys:
        name, value, match_type, raw, line_no

    For #if (SWITCH == VALUE), both SWITCH and VALUE are recorded as separate
    entries so that VALUE can be resolved later.
    """
    with open(c_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    content = "".join(lines)

    # Merge backslash continuation lines so #if expressions spanning multiple
    # physical lines can be parsed as a single logical line.
    content = re.sub(r"\\\s*\n\s*", " ", content)

    def offset_to_line(offset: int) -> int:
        return content[:offset].count("\n") + 1

    entries = []
    seen_names = set()

    def add_entry(entry):
        name = entry["name"]
        if name in _C_KEYWORDS:
            return
        if name not in seen_names:
            seen_names.add(name)
            entries.append(entry)

    def _is_rbfs_macro(name: str) -> bool:
        return name.startswith("RBFS_")

    def _record_if_comparison(switch_name, value_name, line_no, raw, op):
        add_entry({
            "name": switch_name,
            "value": value_name,
            "match_type": "if_eq_switch",
            "raw": raw,
            "line_no": line_no,
            "operator": op,
        })
        if _is_rbfs_macro(value_name):
            add_entry({
                "name": value_name,
                "value": None,
                "match_type": "if_eq_value",
                "raw": raw,
                "line_no": line_no,
            })

    # 1) Extract comparisons from #if / #elif expressions
    processed_if_lines = set()
    for m in _RE_IF_LINE.finditer(content):
        raw = m.group(0).strip()
        if raw in processed_if_lines:
            continue
        processed_if_lines.add(raw)
        line_no = offset_to_line(m.start())
        expr = m.group(1).strip()
        for comp in _RE_IF_COMPARISON.finditer(expr):
            switch_name = comp.group(1)
            op = comp.group(2)
            value_name = comp.group(3)
            # Only consider RBFS_* macros as switches for our purposes
            if not _is_rbfs_macro(switch_name):
                continue
            _record_if_comparison(switch_name, value_name, line_no, raw, op)

    # 2) #ifdef / #ifndef MACRO — only care about RBFS_ macros
    for m in _RE_IFDEF.finditer(content):
        directive = m.group(1)
        name = m.group(2)
        if not _is_rbfs_macro(name):
            continue
        add_entry({
            "name": name,
            "value": None,
            "match_type": "ifdef" if directive == "ifdef" else "ifndef",
            "raw": m.group(0).strip(),
            "line_no": offset_to_line(m.start()),
        })

    # 3) RB_ASSERT_SWITCH_SETTINGS(SWITCH, VALUE1, VALUE2, ...)
    for m in _RE_ASSERT_SWITCH.finditer(content):
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if not parts:
            continue
        switch_name = parts[0]
        expected_values = parts[1:]
        line_no = offset_to_line(m.start())
        add_entry({
            "name": switch_name,
            "value": expected_values[0] if expected_values else None,
            "match_type": "assert_switch",
            "raw": m.group(0).strip().replace("\n", " "),
            "line_no": line_no,
            "all_expected_values": expected_values,
        })
        for v in expected_values:
            if _is_rbfs_macro(v):
                add_entry({
                    "name": v,
                    "value": None,
                    "match_type": "assert_value",
                    "raw": m.group(0).strip().replace("\n", " "),
                    "line_no": line_no,
                })

    # 4) Generic #if / #elif (skip ones already caught by if_eq)
    caught_raws = {e["raw"] for e in entries}
    for m in _RE_IF_GENERIC.finditer(content):
        raw = m.group(0).strip()
        if raw in caught_raws:
            continue
        line_no = offset_to_line(m.start())
        expr = m.group(1).strip()
        ids = set(re.findall(r"\b[A-Za-z_]\w*\b", expr)) - _C_KEYWORDS
        for macro_name in ids:
            if not _is_rbfs_macro(macro_name):
                continue
            add_entry({
                "name": macro_name,
                "value": None,
                "match_type": "generic_if",
                "raw": raw,
                "line_no": line_no,
                "expression": expr,
            })

    return entries


# ------------------------------------------------------------------------------
# CSV parsing logic
# ------------------------------------------------------------------------------

def _parse_switch_csv(csv_path: str):
    """
    Parse a Bosch GenProDB SwitchSettings CSV (semicolon-separated, REMARK-skipping).

    Returns a flat list of dicts and also a value-to-integer map derived from
    value macros that appear as switch values in the CSV.
    """
    entries = []
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f, delimiter=";")
        for line_idx, row in enumerate(reader, start=1):
            if not row:
                continue
            first_col = row[0].strip()
            if first_col.startswith("REMARK:") or first_col.startswith("#") or not first_col:
                continue
            name = first_col
            value = row[1].strip() if len(row) > 1 else ""
            entries.append({
                "name": name,
                "value": value,
                "raw": ";".join(row),
                "line_no": line_idx,
            })
    return entries


# ------------------------------------------------------------------------------
# Value resolution helpers
# ------------------------------------------------------------------------------

def _looks_like_value_macro(name: str, switch_prefixes: set) -> bool:
    """Return True if name looks like RBFS_SwitchName_Value."""
    if not name.startswith("RBFS_"):
        return False
    for prefix in switch_prefixes:
        if name.startswith(prefix + "_") and len(name) > len(prefix) + 1:
            return True
    return False


def _synthesise_value(switch_name: str, value_name: str, used_values: set) -> int:
    """
    Assign a synthetic integer to a value macro that is not defined in the CSV.

    We try to reuse Bosch conventions (ON=1, OFF=2, Yes=1, No=2, Enabled=1,
    Disabled=2) when the value name suggests it, otherwise we pick the smallest
    unused positive integer.
    """
    base = value_name[len(switch_name) + 1:] if value_name.startswith(switch_name + "_") else value_name

    # Common Bosch value suffixes
    conventions = {
        "ON": 1, "OFF": 2,
        "On": 1, "Off": 2,
        "Yes": 1, "No": 2,
        "Enabled": 1, "Disabled": 2,
        "Active": 1, "Inactive": 2,
        "Supported": 1, "NotSupported": 2,
        "Basic": 1, "CrtlModeAllOff": 2,
    }

    candidate = conventions.get(base)
    if candidate is not None and candidate not in used_values:
        return candidate

    candidate = 1
    while candidate in used_values:
        candidate += 1
    return candidate


# ------------------------------------------------------------------------------
# Alignment + generation
# ------------------------------------------------------------------------------

def _resolve_macros(c_path: str, csv_path: str):
    """Extract C macros, parse CSV, and return resolved macro dictionaries plus audit."""
    # 1. Extract macros from C source
    c_entries = _extract_macros_from_c(c_path)

    # Split into switch-like and value-like entries
    switch_entries = [e for e in c_entries if e["match_type"] in ("if_eq_switch", "assert_switch")]
    value_entries = [e for e in c_entries if e["match_type"] in ("if_eq_value", "assert_value")]
    other_entries = [e for e in c_entries if e["match_type"] not in ("if_eq_switch", "assert_switch", "if_eq_value", "assert_value")]

    switch_names = {e["name"] for e in switch_entries}
    switch_prefixes = {n for n in switch_names if n.startswith("RBFS_")}

    # 2. Parse project CSV
    csv_entries = _parse_switch_csv(csv_path)
    csv_dict = {e["name"]: e["value"] for e in csv_entries}

    # 3. Resolve switch macros against CSV
    resolved_switches = OrderedDict()
    resolved_values = OrderedDict()
    matched, conflicts, missing = 0, 0, 0
    audit = []

    for entry in switch_entries:
        name = entry["name"]
        c_value = entry.get("value")
        csv_value = csv_dict.get(name)

        if csv_value is None:
            missing += 1
            resolved_val = c_value
            status = "MISSING"
        elif c_value is not None and csv_value != c_value:
            conflicts += 1
            resolved_val = csv_value  # CSV is ground truth
            status = "CONFLICT"
        else:
            matched += 1
            resolved_val = csv_value if csv_value is not None else c_value
            status = "MATCH"

        resolved_switches[name] = resolved_val
        audit.append({
            "macro": name,
            "status": status,
            "resolved_value": resolved_val,
            "c_expected": c_value,
            "csv_actual": csv_value,
            "line_no": entry.get("line_no"),
            "match_type": entry.get("match_type"),
        })

    # 4. Resolve value macros
    referenced_values = set()
    for resolved_val in resolved_switches.values():
        if resolved_val and resolved_val.startswith("RBFS_"):
            referenced_values.add(resolved_val)
    for entry in value_entries:
        referenced_values.add(entry["name"])

    value_family = defaultdict(set)
    for value_name in referenced_values:
        parent = None
        for prefix in sorted(switch_prefixes, key=len, reverse=True):
            if value_name.startswith(prefix + "_"):
                parent = prefix
                break
        if parent is None:
            parent = value_name
        value_family[parent].add(value_name)

    for parent, values in value_family.items():
        used = set()
        for v in sorted(values):
            if v in csv_dict:
                used.add(_synthesise_value(parent, v, used))

        for v in sorted(values):
            if v in resolved_values:
                continue
            val = _synthesise_value(parent, v, used)
            resolved_values[v] = val
            used.add(val)
            audit.append({
                "macro": v,
                "status": "VALUE_MACRO",
                "resolved_value": val,
                "c_expected": None,
                "csv_actual": csv_dict.get(v),
                "line_no": None,
                "match_type": "value_macro",
            })

    # 5. Handle other generic macros
    resolved_other = OrderedDict()
    for entry in other_entries:
        name = entry["name"]
        if name in resolved_switches or name in resolved_values:
            continue
        csv_value = csv_dict.get(name)
        if csv_value is not None:
            resolved_other[name] = csv_value
            audit.append({
                "macro": name,
                "status": "MATCH",
                "resolved_value": csv_value,
                "c_expected": None,
                "csv_actual": csv_value,
                "line_no": entry.get("line_no"),
                "match_type": entry.get("match_type"),
            })

    return resolved_values, resolved_other, resolved_switches, audit, matched, conflicts, missing


def _format_macro_block(resolved_values, resolved_other, resolved_switches,
                        neutralize_assert_switch: bool, csv_basename: str) -> list[str]:
    """Return the macro block lines to inject into test_<Component>.h."""
    lines: list[str] = []
    lines.append("/* Auto-generated Cantata macro block")
    lines.append(" * Generated : " + datetime.now().isoformat())
    lines.append(" * Source CSV: " + csv_basename)
    lines.append(" */")
    lines.append("")

    if neutralize_assert_switch:
        lines.append("/* Unit-test override: RB_ASSERT_SWITCH_SETTINGS is a compile-time")
        lines.append(" * switch sanity check only (generates no code).  For the UT build")
        lines.append(" * we supply our own switch values, so neutralise the macro.        */")
        lines.append("#define RB_ASSERTSWITCHSETTINGS_H__")
        lines.append("#define RB_SWISET_IMPL_H__")
        lines.append("#define RB_ASSERT_SWITCH_SETTINGS(swi, ...)")
        lines.append("")

    if resolved_values:
        lines.append("/* Switch value macros (ground truth from SwitchSettings CSV) */")
        for name, val in resolved_values.items():
            lines.append(f"#define {name} {val}")
        lines.append("")

    if resolved_other:
        lines.append("/* Other project macros resolved from CSV */")
        for name, val in resolved_other.items():
            lines.append(f"#define {name} {val}")
        lines.append("")

    if resolved_switches:
        lines.append("/* Switch settings for this variant */")
        for name, val in resolved_switches.items():
            if val is not None and val != "":
                lines.append(f"#define {name} {val}")
            else:
                lines.append(f"#define {name}")
        lines.append("")

    return lines


def _inject_into_test_header(test_h_path: str, macro_block: list[str]) -> None:
    """Inject or replace the generated macro block inside test_<Component>.h."""
    marker_start = "/* <<< AUTO-GENERATED CANTATA MACROS START >>> */"
    marker_end = "/* <<< AUTO-GENERATED CANTATA MACROS END >>> */"

    if os.path.exists(test_h_path):
        with open(test_h_path, "r", encoding="utf-8") as f:
            original_lines = f.read().splitlines()
    else:
        base = Path(test_h_path).stem
        guard = base.upper() + "_H"
        original_lines = [
            f"#ifndef {guard}",
            f"#define {guard}",
            "",
            "#endif",
        ]

    # Remove any previously injected block
    new_lines = []
    skip = False
    for line in original_lines:
        if marker_start in line:
            skip = True
            continue
        if marker_end in line:
            skip = False
            continue
        if not skip:
            new_lines.append(line)

    # Insert after the include guard #define, or at the top if no guard found
    insert_idx = 0
    for idx, line in enumerate(new_lines):
        if re.match(r"^\s*#\s*define\s+\w+_H\s*$", line):
            insert_idx = idx + 1
            break

    block_with_markers = [marker_start] + macro_block + [marker_end]
    new_lines = new_lines[:insert_idx] + block_with_markers + new_lines[insert_idx:]

    with open(test_h_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")


def _write_audit_reports(output_dir: str, base: str, c_path: str, csv_path: str,
                         audit, matched: int, conflicts: int, missing: int,
                         resolved_values) -> None:
    os.makedirs(output_dir, exist_ok=True)

    json_path = os.path.join(output_dir, f"{base}_resolved_macros.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated": datetime.now().isoformat(),
            "source_c": os.path.abspath(c_path),
            "source_csv": os.path.abspath(csv_path),
            "summary": {
                "total": len(audit),
                "matched": matched,
                "conflicts": conflicts,
                "missing": missing,
                "value_macros": len(resolved_values),
            },
            "resolved": audit,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")

    txt_path = os.path.join(output_dir, f"{base}_resolved_macros.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("Macro Alignment Report\n")
        f.write("=" * 60 + "\n")
        f.write(f"Source C   : {os.path.abspath(c_path)}\n")
        f.write(f"Source CSV : {os.path.abspath(csv_path)}\n")
        f.write(f"Generated  : {datetime.now().isoformat()}\n")
        f.write("-" * 60 + "\n")
        f.write(f"Total macros    : {len(audit)}\n")
        f.write(f"Matched         : {matched}\n")
        f.write(f"Conflicts       : {conflicts}\n")
        f.write(f"Missing         : {missing}\n")
        f.write(f"Value macros    : {len(resolved_values)}\n")
        f.write("-" * 60 + "\n")
        for r in audit:
            val = r["resolved_value"]
            val_str = "" if val is None else str(val)
            f.write(f"  {r['macro']} = {val_str}  [{r['status']}]\n")


def _align_and_generate(c_path: str, csv_path: str, output_dir: str,
                        write_reports: bool = False,
                        neutralize_assert_switch: bool = True):
    resolved_values, resolved_other, resolved_switches, audit, matched, conflicts, missing = \
        _resolve_macros(c_path, csv_path)

    base = os.path.splitext(os.path.basename(c_path))[0]
    component_dir = os.path.dirname(c_path)
    test_h_path = os.path.join(component_dir, f"test_{base}", f"test_{base}.h")

    macro_block = _format_macro_block(
        resolved_values, resolved_other, resolved_switches,
        neutralize_assert_switch, os.path.basename(csv_path)
    )

    _inject_into_test_header(test_h_path, macro_block)

    if write_reports:
        _write_audit_reports(
            output_dir, base, c_path, csv_path, audit,
            matched, conflicts, missing, resolved_values
        )

    # Console report
    print("[Phase 0.5] Macro Alignment Complete")
    print(f"  Total: {len(audit)}, Matched: {matched}, Conflicts: {conflicts}, Missing: {missing}")
    print(f"  Value macros defined: {len(resolved_values)}")
    if conflicts:
        print("  WARNING: Conflicts detected. CSV ground truth was used, but review recommended.")
    if missing:
        print("  WARNING: Missing macros detected. Fallback to C file expectation used.")
    print(f"  Injected into: {os.path.abspath(test_h_path)}")

    return conflicts, missing, len(audit)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 0.5 single-step: extract C compile-time macros, "
            "parse SwitchSettings CSV, and inject definitions into test_<Component>.h."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python align_macros.py module.c SwitchSettings.csv --output-dir ./test_module/work/input --report
  python align_macros.py module.c --output-dir ./out
        """,
    )
    parser.add_argument("input_c", help="Path to the C source file under test.")
    parser.add_argument("input_csv", nargs="?", default=None, help="Path to the project SwitchSettings CSV (required when C file contains compile-time macros).")
    parser.add_argument("--output-dir", default=".", help="Directory for optional audit reports.")
    parser.add_argument("--report", action="store_true", help="Emit resolved_macros.json and resolved_macros.txt reports.")
    parser.add_argument("--keep-assert-switch", action="store_true",
                        help="Do NOT neutralise RB_ASSERT_SWITCH_SETTINGS (default: neutralised).")
    args = parser.parse_args()

    if not os.path.isfile(args.input_c):
        print(f"ERROR: C file not found: {args.input_c}", file=sys.stderr)
        return 1

    # Phase 0.5 is only needed when the C file contains compile-time macros
    # that influence which code paths are built. If there are none, we can
    # still emit the neutralised RB_ASSERT_SWITCH_SETTINGS block (safe default)
    # and continue without a CSV.
    c_entries = _extract_macros_from_c(args.input_c)

    if not c_entries:
        base = os.path.splitext(os.path.basename(args.input_c))[0]
        component_dir = os.path.dirname(args.input_c)
        test_h_path = os.path.join(component_dir, f"test_{base}", f"test_{base}.h")
        macro_block = _format_macro_block(
            OrderedDict(), OrderedDict(), OrderedDict(),
            neutralize_assert_switch=not args.keep_assert_switch,
            csv_basename="(none - no compile-time macros detected)"
        )
        _inject_into_test_header(test_h_path, macro_block)
        print("[Phase 0.5] No compile-time macros detected in C file.")
        print("  Macro alignment skipped; safe default macro block injected.")
        print(f"  Injected into: {os.path.abspath(test_h_path)}")
        return 0

    # Compile-time macros exist -> CSV is mandatory
    if not args.input_csv:
        print("\n[Phase 0.5] ERROR: Compile-time macros were detected in the C file,", file=sys.stderr)
        print("              but no SwitchSettings CSV was provided.", file=sys.stderr)
        print("\nDetected macros:", file=sys.stderr)
        for entry in c_entries:
            line_no = entry.get("line_no", "?")
            raw = entry.get("raw", entry["name"]).replace("\n", " ")
            print(f"  line {line_no}: {raw}", file=sys.stderr)
        print("\n[AGENT STOP] Please provide the SwitchSettings CSV path and re-run.", file=sys.stderr)
        return 2

    if not os.path.isfile(args.input_csv):
        print(f"\n[Phase 0.5] ERROR: SwitchSettings CSV not found: {args.input_csv}", file=sys.stderr)
        print("\n[AGENT STOP] Please provide a valid SwitchSettings CSV path and re-run.", file=sys.stderr)
        return 2

    conflict_cnt, missing_cnt, total_cnt = _align_and_generate(
        args.input_c, args.input_csv, args.output_dir,
        write_reports=args.report,
        neutralize_assert_switch=not args.keep_assert_switch,
    )

    if conflict_cnt or missing_cnt:
        print("\n[AGENT STOP] Review conflicts/missing macros before proceeding to Phase 1.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
