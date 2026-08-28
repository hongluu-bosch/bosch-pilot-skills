#!/usr/bin/env python3
"""diagcomm-toolkit -> DOORS helper CLI.

Self-contained inside diagcomm-toolkit; no sibling-skill dependency
(v2.0.0 cut the previous link to a separate doors-toolkit). Subcommands:

    show-target    print the `doors:` block of a mapping yaml as JSON
                   (UUID validation; exits 1 on placeholder, 2 if missing)
    inspect        peek at a JSON dump's top-level structure
    extract        single-query extraction from a JSON dump (dotted path)
    extract-many   batch extraction driven by a yaml `extract:` block
    lint-excel     openpyxl-based sanity check on an xlsx
    lint-doors-xlsx  STRICT lint: rejects xlsx that DOORS will not accept
                   (openpyxl-generated, missing sharedStrings, etc.)

All commands print human-readable lines to stderr and machine output to stdout.

Exit codes:
    0  success
    1  degraded / partial
    2  fatal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _log import info, warn, err  # noqa: E402
from json_query import query  # noqa: E402


# -- shared helpers ------------------------------------------------------- #


def _load_json(path: Path) -> Any:
    if not path.exists():
        err("json file not found: %s", path)
        raise SystemExit(2)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        err("json parse error in %s: %s", path, exc)
        raise SystemExit(2)


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ImportError:
        err("PyYAML not installed. Run: python -m pip install -r %s",
            (HERE.parent / "scripts" / "requirements.txt").as_posix())
        raise SystemExit(2)
    if not path.exists():
        err("yaml file not found: %s", path)
        raise SystemExit(2)
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        err("yaml parse error in %s: %s", path, exc)
        raise SystemExit(2)


def _scalar(values: List[Any]) -> Any:
    if isinstance(values, list) and len(values) == 1:
        return values[0]
    return values


def _atomize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


# -- subcommand: show-target ---------------------------------------------- #


_REQUIRED_TARGET_KEYS = ("document_uuid",)
_PLACEHOLDER_PATTERNS = ("PUT-", "TODO", "<", "...")


def cmd_show_target(args: argparse.Namespace) -> int:
    mapping = _load_yaml(Path(args.mapping))
    if not isinstance(mapping, dict):
        err("mapping yaml must be a top-level mapping (got %s)", type(mapping).__name__)
        return 2

    target = mapping.get("doors")
    if not isinstance(target, dict):
        err("mapping yaml has no `doors:` block")
        return 2

    missing = [k for k in _REQUIRED_TARGET_KEYS if not target.get(k)]
    placeholder = []
    for k, v in target.items():
        if isinstance(v, str) and any(p in v for p in _PLACEHOLDER_PATTERNS):
            placeholder.append(f"{k}={v!r}")

    output = json.dumps(target, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(output + "\n", encoding="utf-8")
        info("wrote %s", args.out)
    sys.stdout.write(output + "\n")

    if missing:
        for k in missing:
            err("required field missing in `doors:` block: %s", k)
        return 2
    if placeholder:
        for line in placeholder:
            warn("placeholder value detected -- update before running Step 8: %s", line)
        return 1
    return 0


# -- subcommand: inspect -------------------------------------------------- #


def _summarize(node: Any, depth: int = 0, max_depth: int = 2) -> List[str]:
    out: List[str] = []
    pad = "  " * depth
    if isinstance(node, dict):
        out.append(f"{pad}<object> ({len(node)} keys)")
        if depth < max_depth:
            for k, v in list(node.items())[:20]:
                out.append(f"{pad}  {k}:")
                out.extend(_summarize(v, depth + 2, max_depth))
    elif isinstance(node, list):
        out.append(f"{pad}<array> (len={len(node)})")
        if node and depth < max_depth:
            out.extend(_summarize(node[0], depth + 1, max_depth))
    else:
        s = repr(node)
        if len(s) > 80:
            s = s[:77] + "..."
        out.append(f"{pad}{s}")
    return out


def cmd_inspect(args: argparse.Namespace) -> int:
    data = _load_json(Path(args.json_file))
    for line in _summarize(data, max_depth=args.depth):
        sys.stdout.write(line + "\n")
    return 0


# -- subcommand: extract -------------------------------------------------- #


def cmd_extract(args: argparse.Namespace) -> int:
    data = _load_json(Path(args.json_file))
    try:
        results = query(data, args.query)
    except ValueError as exc:
        err("bad query: %s", exc)
        return 2
    if not results:
        if args.allow_empty:
            warn("no match for %s (allow-empty -> writing empty file)", args.query)
            out = ""
            exit_code = 1
        else:
            err("no match for %s", args.query)
            return 2
    else:
        out = _atomize(_scalar(results))
        exit_code = 0
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(out, encoding="utf-8")
        info("wrote %s (%d chars)", args.out, len(out))
    sys.stdout.write(out + "\n")
    return exit_code


# -- subcommand: extract-many --------------------------------------------- #


def _walk_extract_specs(node: Any, prefix: str = "") -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    if not isinstance(node, dict):
        return out
    for key, val in node.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict) and "json_path" in val:
            out.append((full, val))
        elif isinstance(val, dict):
            out.extend(_walk_extract_specs(val, full))
    return out


def cmd_extract_many(args: argparse.Namespace) -> int:
    data = _load_json(Path(args.json_file))
    mapping = _load_yaml(Path(args.mapping))
    extract_block = mapping.get("extract") if isinstance(mapping, dict) else None
    if not extract_block:
        err("mapping has no `extract:` block")
        return 2
    specs = _walk_extract_specs(extract_block)
    if not specs:
        err("`extract:` block contains no `json_path` leaves")
        return 2

    result: Dict[str, Any] = {}
    missing_required: List[str] = []
    missing_optional: List[str] = []

    for name, spec in specs:
        path = spec["json_path"]
        required = bool(spec.get("required", True))
        try:
            matches = query(data, path)
        except ValueError as exc:
            err("bad json_path for %s: %s", name, exc)
            return 2
        if not matches:
            (missing_required if required else missing_optional).append(name)
            continue
        result[name] = _scalar(matches)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    info("wrote %s (%d keys)", args.out, len(result))

    for name in missing_optional:
        warn("optional miss: %s", name)
    if missing_required:
        for name in missing_required:
            err("required miss: %s", name)
        return 2
    if missing_optional:
        return 1
    return 0


# -- subcommand: lint-excel / lint-doors-xlsx ----------------------------- #


def cmd_lint_excel(args: argparse.Namespace) -> int:
    from excel_io import lint_workbook
    issues = lint_workbook(args.excel)
    if not issues:
        info("lint-excel: %s OK", args.excel)
        return 0
    for line in issues:
        warn("lint: %s", line)
    if any("not found" in line or "could not load" in line for line in issues):
        return 2
    return 1


def cmd_lint_doors_xlsx(args: argparse.Namespace) -> int:
    """Strict lint: a *DOORS-acceptance* check, not a generic xlsx check.

    Catches the 3 failure modes hit before we switched to xlsxwriter:
      - Application != "Microsoft Excel"
      - xl/sharedStrings.xml missing
      - sizeRow / sizeColumn meta cells written as numbers (DOORS wants strings)
    """
    import re
    import zipfile
    p = Path(args.excel)
    if not p.exists():
        err("file not found: %s", p)
        return 2

    issues: List[str] = []
    try:
        with zipfile.ZipFile(p) as z:
            names = set(z.namelist())
            if "xl/sharedStrings.xml" not in names:
                issues.append(
                    "xl/sharedStrings.xml missing -- DOORS upload will hang or "
                    "reject. Use xlsxwriter (not openpyxl) to produce the file."
                )
            try:
                app_xml = z.read("docProps/app.xml").decode("utf-8", errors="replace")
                m = re.search(r"<Application>([^<]+)</Application>", app_xml)
                gen = m.group(1) if m else "<missing>"
                if gen != "Microsoft Excel":
                    issues.append(
                        f"Application={gen!r}; DOORS expects exactly 'Microsoft Excel'. "
                        "openpyxl writes 'Openpyxl 3.x'; switch to xlsxwriter."
                    )
            except KeyError:
                issues.append("docProps/app.xml missing -- not a valid xlsx?")
    except zipfile.BadZipFile:
        err("not a zip / xlsx file: %s", p)
        return 2

    try:
        from openpyxl import load_workbook
        wb = load_workbook(p, read_only=True, data_only=True)
        ws = wb.active
        meta = [ws.cell(row=1, column=c).value for c in range(1, 5)]
        if meta and meta[0] == "sizeRow":
            for label_idx, val_idx in ((0, 1), (2, 3)):
                if isinstance(meta[val_idx], (int, float)):
                    issues.append(
                        f"meta cell {meta[label_idx]!r} value is numeric "
                        f"({meta[val_idx]!r}); DOORS expects a string."
                    )
        wb.close()
    except Exception as exc:
        issues.append(f"openpyxl could not load workbook for meta check: {exc}")

    if not issues:
        info("lint-doors-xlsx: %s OK (DOORS-acceptable)", p)
        return 0
    for line in issues:
        warn("lint-doors: %s", line)
    return 1


# -- argparse plumbing ---------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="diagcomm-toolkit/doors_helper.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser(
        "show-target",
        help="print mapping yaml's `doors:` block as JSON (UUID etc.)",
    )
    p_st.add_argument("--mapping", required=True)
    p_st.add_argument("--out", help="optional output file")
    p_st.set_defaults(func=cmd_show_target)

    p_in = sub.add_parser("inspect", help="peek at a JSON dump's top-level structure")
    p_in.add_argument("--json-file", required=True)
    p_in.add_argument("--depth", type=int, default=2)
    p_in.set_defaults(func=cmd_inspect)

    p_ex = sub.add_parser("extract", help="extract a single value via dotted path")
    p_ex.add_argument("--json-file", required=True)
    p_ex.add_argument("--query", required=True)
    p_ex.add_argument("--out")
    p_ex.add_argument("--allow-empty", action="store_true")
    p_ex.set_defaults(func=cmd_extract)

    p_em = sub.add_parser("extract-many", help="batch extraction via mapping yaml")
    p_em.add_argument("--json-file", required=True)
    p_em.add_argument("--mapping", required=True)
    p_em.add_argument("--out", required=True)
    p_em.set_defaults(func=cmd_extract_many)

    p_le = sub.add_parser("lint-excel", help="generic openpyxl sanity check")
    p_le.add_argument("--excel", required=True)
    p_le.set_defaults(func=cmd_lint_excel)

    p_ld = sub.add_parser(
        "lint-doors-xlsx",
        help="STRICT: detect xlsx that DOORS will reject (Application/sharedStrings/meta types)",
    )
    p_ld.add_argument("--excel", required=True)
    p_ld.set_defaults(func=cmd_lint_doors_xlsx)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
