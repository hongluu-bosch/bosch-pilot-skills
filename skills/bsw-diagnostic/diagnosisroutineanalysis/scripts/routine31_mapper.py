#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Routine31 Mapper
Auto-resolve 31 Service Routine config from Dcm_Lcfg_DspUds.c

Usage:
    python routine31_mapper.py <project_root> [--rid 0x2C64]
    python routine31_mapper.py <project_root> --list

Example:
    python routine31_mapper.py "C:\mma5szh\05_SharCC_Workspace\X_DPB_48V_Update_Int\DPB_Dev"
    python routine31_mapper.py "C:\mma5szh\05_SharCC_Workspace\X_DPB_48V_Update_Int\DPB_Dev" --rid 0x2C39
"""

import re
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime


def find_dcm_lcfg(project_root):
    """
    Find Dcm_Lcfg_DspUds.c in Gen directories.
    Exclude Bootloader variants (RBBLDR, OEMBLDR, BMGR).
    If multiple variants exist, pick the most recently modified one.
    """
    gen_path = Path(project_root) / "Gen"
    if not gen_path.exists():
        return None

    candidates = list(gen_path.rglob("src_out/bct/_out/Dcm_Lcfg_DspUds.c"))
    if not candidates:
        return None

    # Exclude Bootloader variants
    excluded_names = ["RBBLDR", "OEMBLDR", "BMGR"]
    filtered = []
    for c in candidates:
        variant_name = c.parts[c.parts.index("Gen") + 1] if "Gen" in c.parts else ""
        if not any(ex in variant_name for ex in excluded_names):
            filtered.append(c)

    if not filtered:
        return None

    # Sort by modification time (newest first)
    filtered.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return filtered[0]


def extract_array_blocks(content, array_name):
    """
    Extract individual {...} initializer blocks from a C array.
    Returns list of block contents (strings inside outer braces).
    """
    pattern = rf'{re.escape(array_name)}\s*\[\s*\w*\s*\]\s*=\s*'
    match = re.search(pattern, content)
    if not match:
        return []

    start = match.end()
    brace_start = content.find('{', start)
    if brace_start == -1:
        return []

    blocks = []
    i = brace_start + 1
    depth = 1
    block_start = i
    in_string = False
    string_char = None

    while i < len(content) and depth > 0:
        c = content[i]
        if in_string:
            if c == '\\' and i + 1 < len(content):
                i += 2
                continue
            if c == string_char:
                in_string = False
        else:
            if c in '"\'':
                in_string = True
                string_char = c
            elif c == '{':
                if depth == 1:
                    block_start = i + 1
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 1:
                    blocks.append(content[block_start:i].strip())
        i += 1

    return blocks


def parse_comment_name(block):
    """Extract RBAPLCUST_* name from /* ... */ comment."""
    m = re.search(r'/\*\s*(RBAPLCUST[^\*/]+)', block)
    if m:
        return m.group(1).strip()
    return None


def extract_function_from_handler(content, handler_func_name):
    """
    Extract start/stop/requestresult function calls from the routine handler function.
    The handler has a switch(subFunction_u8) with cases 1u (start), 2u (stop), 3u (requestResult).
    """
    # Find the handler function definition
    func_pattern = rf'static\s+Std_ReturnType\s+{re.escape(handler_func_name)}\s*\(.*?\)\s*\{{'
    func_match = re.search(func_pattern, content, re.DOTALL)
    if not func_match:
        return None, None, None

    func_start = func_match.start()
    # Find the end of this function (next function definition or end of file)
    next_func = re.search(r'\n(static\s+(?:const\s+)?(?:Std_ReturnType|void|CONST)|#define)', content[func_match.end():])
    if next_func:
        func_body = content[func_match.end():func_match.end() + next_func.start()]
    else:
        func_body = content[func_match.end():]

    start_func = None
    stop_func = None
    req_func = None

    # Case 1u: start function
    m1 = re.search(r'case\s+1u:.*?dataRetVal_u8\s*=\s*(\w+)', func_body, re.DOTALL)
    if m1:
        start_func = m1.group(1)

    # Case 2u: stop function
    m2 = re.search(r'case\s+2u:.*?dataRetVal_u8\s*=\s*(\w+)', func_body, re.DOTALL)
    if m2:
        stop_func = m2.group(1)

    # Case 3u: request result function
    m3 = re.search(r'case\s+3u:.*?dataRetVal_u8\s*=\s*(\w+)', func_body, re.DOTALL)
    if m3:
        req_func = m3.group(1)

    return start_func, stop_func, req_func


def parse_routine_config(filepath):
    """
    Parse Dcm_Lcfg_DspUds.c to build RID -> function mapping.
    Returns dict: rid -> {
        'name': 'RBAPLCUST_xxxx_...',
        'start_func': '...',
        'stop_func': '...',
        'req_func': '...',
        'handler_func': '...'
    }
    """
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Step 1: Parse Dcm_Cfg_NormalRoutineConfig_cast -> RID and index
    normal_blocks = extract_array_blocks(content, 'Dcm_Cfg_NormalRoutineConfig_cast')
    rid_to_index = {}
    for block in normal_blocks:
        rid_match = re.search(r'0x([0-9A-Fa-f]+)\s*,\s*/\*\s*dataRId_u16', block)
        idx_match = re.search(r'(\d+)\s*,\s*/\*\s*routineCommonIndex_u16', block)
        name = parse_comment_name(block)
        if rid_match and idx_match:
            rid = int(rid_match.group(1), 16)
            idx = int(idx_match.group(1))
            rid_to_index[rid] = (idx, name)

    # Step 2: Parse Dcm_Cfg_RoutineExtendedConfig_cast by array order
    ext_blocks = extract_array_blocks(content, 'Dcm_Cfg_RoutineExtendedConfig_cast')
    extended_info = {}
    for idx, block in enumerate(ext_blocks):
        handler_m = re.search(r'&(\w+_Func)\s*,\s*/\*\s*routineHandler_pfct', block)
        name = parse_comment_name(block)
        if handler_m:
            extended_info[idx] = {
                'handler_func': handler_m.group(1),
                'name': name,
            }

    # Step 3: Extract actual function names from handler function
    results = {}
    for rid, (idx, name) in rid_to_index.items():
        if idx in extended_info:
            info = extended_info[idx]
            handler_func = info['handler_func']
            start_func, stop_func, req_func = extract_function_from_handler(content, handler_func)
            results[rid] = {
                'name': name or info['name'] or "Unknown",
                'handler_func': handler_func,
                'start_func': start_func,
                'stop_func': stop_func,
                'req_func': req_func,
            }

    return results


def print_result(rid, info):
    """Pretty print a single routine mapping."""
    print(f"\n{'='*60}")
    print(f"Routine ID: 0x{rid:04X} ({rid})")
    print(f"Config Name: {info['name']}")
    print(f"{'='*60}")
    print(f"  Handler Function:      {info['handler_func'] or 'N/A'}")
    print(f"  Start Function:        {info['start_func'] or 'N/A'}")
    print(f"  Stop Function:         {info['stop_func'] or 'N/A'}")
    print(f"  RequestResult Function: {info['req_func'] or 'N/A'}")


def main():
    parser = argparse.ArgumentParser(
        description="Resolve 31 Service Routine config from Dcm_Lcfg_DspUds.c"
    )
    parser.add_argument("project_root", help="Project root path (e.g. C:\\...\\DPB_Dev)")
    parser.add_argument("--rid", help="Specific Routine ID to look up (hex, e.g. 0x2C39)")
    parser.add_argument("--list", action="store_true", help="List all routines")
    args = parser.parse_args()

    project_root = Path(args.project_root)
    if not project_root.exists():
        print(f"Error: Project root does not exist: {project_root}")
        sys.exit(1)

    lcfg_file = find_dcm_lcfg(project_root)
    if not lcfg_file:
        print(f"Error: Dcm_Lcfg_DspUds.c not found under {project_root / 'Gen'}")
        print("Note: Excluding Bootloader variants (RBBLDR, OEMBLDR, BMGR)")
        sys.exit(1)

    print(f"Using: {lcfg_file}")
    print(f"Modified: {datetime.fromtimestamp(lcfg_file.stat().st_mtime)}")

    results = parse_routine_config(str(lcfg_file))
    if not results:
        print("Error: Failed to parse routine config.")
        sys.exit(1)

    if args.rid:
        rid = int(args.rid, 0)
        if rid in results:
            print_result(rid, results[rid])
        else:
            print(f"Routine ID 0x{rid:04X} not found.")
            sys.exit(1)
    elif args.list:
        print(f"\nFound {len(results)} routines:\n")
        for rid in sorted(results.keys()):
            info = results[rid]
            print(f"  0x{rid:04X}  {info['name']:<50s}  Req: {info['req_func'] or 'N/A'}")
    else:
        print(f"\nParsed {len(results)} routines successfully.")
        print("Use --rid 0xXXXX to look up a specific routine, or --list to show all.")


if __name__ == "__main__":
    main()
