#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Routine31 Analyzer
Analyze 31 Service Routine failure reasons from code.

Usage:
    python routine31_analyzer.py <project_root> --rid 0x2C39 [--variant MM21xSoftECUxECC]

Phases:
    Phase 1: Parse Dcm_Lcfg -> function names + dataOut count
    Phase 2: Locate RBAPLCUST/RBAPLEOL source files
    Phase 3: Read SwitchSettings.csv -> active switches
    Phase 4: Determine architecture type (TYPE_A/B/C) + extract sequences
    Phase 5: Extract CMD failure blocks from ValvesToggling.c
    Phase 6: (AI) Analyze conditions, classify root causes

Example:
    python routine31_analyzer.py "C:\mma5szh\05_SharCC_Workspace\X_DPB_48V_Update_Int\DPB_Dev" --rid 0x2C39
"""

import re
import sys
import os
import argparse
import csv
from pathlib import Path
from datetime import datetime


# =============================================================================
# Phase 1: Dcm_Lcfg Parser (from routine31_mapper.py)
# =============================================================================

def find_dcm_lcfg(project_root, variant=None):
    """Find Dcm_Lcfg_DspUds.c. Exclude Bootloader variants."""
    gen_path = Path(project_root) / "Gen"
    if not gen_path.exists():
        return None

    if variant:
        candidate = gen_path / variant / "src_out" / "bct" / "_out" / "Dcm_Lcfg_DspUds.c"
        if candidate.exists():
            return candidate

    candidates = list(gen_path.rglob("src_out/bct/_out/Dcm_Lcfg_DspUds.c"))
    excluded_names = ["RBBLDR", "OEMBLDR", "BMGR"]
    filtered = []
    for c in candidates:
        variant_name = c.parts[c.parts.index("Gen") + 1] if "Gen" in c.parts else ""
        if not any(ex in variant_name for ex in excluded_names):
            filtered.append(c)

    if not filtered:
        return None
    filtered.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return filtered[0]


def extract_array_blocks(content, array_name):
    """Extract {...} initializer blocks from a C array."""
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
    """Extract start/stop/requestresult function calls from routine handler."""
    func_pattern = rf'static\s+Std_ReturnType\s+{re.escape(handler_func_name)}\s*\(.*?\)\s*\{{'
    func_match = re.search(func_pattern, content, re.DOTALL)
    if not func_match:
        return None, None, None

    next_func = re.search(r'\n(static\s+(?:const\s+)?(?:Std_ReturnType|void|CONST)|#define)',
                          content[func_match.end():])
    if next_func:
        func_body = content[func_match.end():func_match.end() + next_func.start()]
    else:
        func_body = content[func_match.end():]

    start_func = None
    stop_func = None
    req_func = None

    m1 = re.search(r'case\s+1u:.*?dataRetVal_u8\s*=\s*(\w+)', func_body, re.DOTALL)
    if m1:
        start_func = m1.group(1)

    m2 = re.search(r'case\s+2u:.*?dataRetVal_u8\s*=\s*(\w+)', func_body, re.DOTALL)
    if m2:
        stop_func = m2.group(1)

    m3 = re.search(r'case\s+3u:.*?dataRetVal_u8\s*=\s*(\w+)', func_body, re.DOTALL)
    if m3:
        req_func = m3.group(1)

    return start_func, stop_func, req_func


def parse_dcm_lcfg(filepath):
    """Parse Dcm_Lcfg_DspUds.c -> RID mapping."""
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

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

    ext_blocks = extract_array_blocks(content, 'Dcm_Cfg_RoutineExtendedConfig_cast')
    extended_info = {}
    for idx, block in enumerate(ext_blocks):
        handler_m = re.search(r'&(\w+_Func)\s*,\s*/\*\s*routineHandler_pfct', block)
        name = parse_comment_name(block)
        # Count output signals from requestResults_st -> outSignalConfig_past -> array length
        num_out_signals = 0
        req_results_m = re.search(r'&(\w+_RequestResults_st)', block)
        if req_results_m:
            struct_name = req_results_m.group(1)
            struct_pattern = rf'static\s+const\s+Dcm_RoutineSubFunctionConfigType_tst\s+{re.escape(struct_name)}\s*=\s*\{{'
            struct_match = re.search(struct_pattern, content, re.DOTALL)
            if struct_match:
                struct_end = content.find('};', struct_match.end())
                if struct_end != -1:
                    struct_body = content[struct_match.end():struct_end]
                    # Find outSignalConfig_past -> array name
                    arr_m = re.search(r'&(\w+_RequestResultsOutSig_ast)\[0\]', struct_body)
                    if arr_m:
                        arr_name = arr_m.group(1)
                        # Count elements in the array
                        arr_pattern = rf'static\s+const\s+Dcm_RoutineSignalConfigType_tst\s+{re.escape(arr_name)}\[\]\s*='
                        arr_match = re.search(arr_pattern, content)
                        if arr_match:
                            arr_end = content.find('};', arr_match.end())
                            if arr_end != -1:
                                arr_body = content[arr_match.end():arr_end]
                                # Count { ... } elements in array body
                                num_out_signals = len(re.findall(r'\{\s*\d+\s*,', arr_body))

        if handler_m:
            extended_info[idx] = {
                'handler_func': handler_m.group(1),
                'name': name,
                'num_out_signals': num_out_signals,
            }

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
                'num_out_signals': info['num_out_signals'],
            }

    return results


# =============================================================================
# Phase 2: File Locator
# =============================================================================

def find_rblcust_file(project_root, func_name):
    """Find RBAPLCUST source file containing the function."""
    base = Path(project_root)
    # Search under RBAPLCust/src/
    search_dirs = list(base.rglob("RBAPLCust/src"))
    for d in search_dirs:
        if d.is_dir():
            for f in d.glob("RBAPLCUST_*.c"):
                try:
                    content = f.read_text(encoding='utf-8', errors='ignore')
                    if func_name in content:
                        return f
                except:
                    pass
    return None


def find_rbleol_file(project_root, rbleol_func_names):
    """
    Find RBAPLEOL source file containing the function DEFINITION.
    Look for "void FuncName(" or "FUNC(...) FuncName(" pattern (definition, not declaration).
    Also try to infer filename from function name (e.g., StartIPBFluidChange -> IPBFluidChange).
    """
    import os
    base = Path(project_root)
    candidates = []

    for root, dirs, files in os.walk(str(base)):
        if 'Gen' in root:
            continue
        for fname in files:
            if fname.startswith("RBAPLEOL_") and fname.endswith(".c"):
                fpath = Path(root) / fname
                try:
                    content = fpath.read_text(encoding='utf-8', errors='ignore')
                    for func_name in rbleol_func_names:
                        # Look for function definition pattern
                        def_patterns = [
                            rf'void\s+{re.escape(func_name)}\s*\(',
                            rf'FUNC\([^)]+\)\s+{re.escape(func_name)}\s*\(',
                        ]
                        for pattern in def_patterns:
                            if re.search(pattern, content):
                                candidates.append((fpath, func_name, fname))
                                break
                except:
                    pass

    if not candidates:
        return None

    # Prefer files where function name closely matches filename
    # e.g., RBAPLEOL_StartIPBFluidChange -> RBAPLEOL_IPBFluidChange.c
    for fpath, func_name, fname in candidates:
        # Extract core name from function (remove RBAPLEOL_ prefix and verb prefix)
        core_from_func = re.sub(r'^RBAPLEOL_(Start|Stop|Init|Actuate|Check)?', '', func_name)
        core_from_file = fname.replace('RBAPLEOL_', '').replace('.c', '')
        if core_from_func.lower() in core_from_file.lower() or core_from_file.lower() in core_from_func.lower():
            return fpath

    # Fallback: return first candidate
    return candidates[0][0]


def extract_rbleol_calls(rblcust_content):
    """Extract RBAPLEOL_* function calls from RBAPLCUST file."""
    calls = set()
    for m in re.finditer(r'(RBAPLEOL_\w+)\s*\(', rblcust_content):
        calls.add(m.group(1))
    return sorted(calls)


def find_valves_toggling(project_root):
    """Find RBAPLEOL_ValvesToggling.c."""
    base = Path(project_root)
    for f in base.rglob("RBAPLEOL_ValvesToggling.c"):
        return f
    return None


# =============================================================================
# Phase 3: SwitchSettings Parser
# =============================================================================

def find_switch_settings(project_root, variant=None):
    """Find SwitchSettings_*.csv."""
    gen_path = Path(project_root) / "Gen"
    if not gen_path.exists():
        return None

    if variant:
        out_dir = gen_path / variant / "out"
        if out_dir.exists():
            candidates = list(out_dir.glob("SwitchSettings_*.csv"))
            if candidates:
                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                return candidates[0]

    candidates = list(gen_path.rglob("out/SwitchSettings_*.csv"))
    if candidates:
        # Exclude Bootloader variants
        excluded_names = ["RBBLDR", "OEMBLDR", "BMGR"]
        filtered = [c for c in candidates
                    if not any(ex in str(c) for ex in excluded_names)]
        if filtered:
            filtered.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return filtered[0]
    return None


def parse_switch_settings(csv_path):
    """Parse SwitchSettings CSV -> dict {switch_name: switch_value}."""
    switches = {}
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            # Skip REMARK line
            for line in f:
                line = line.strip()
                if not line or line.startswith("REMARK"):
                    continue
                parts = line.split(';')
                if len(parts) >= 2:
                    switch_name = parts[0].strip()
                    switch_value = parts[1].strip()
                    switches[switch_name] = switch_value
    except Exception as e:
        print(f"Warning: Failed to parse SwitchSettings: {e}")
    return switches


def is_switch_active(switch_name, switch_value, switches):
    """
    Check if a code block guarded by #if (SWITCH == VALUE) is active.
    Returns: True (active), False (inactive), None (unknown)
    """
    if switch_name not in switches:
        return None  # Unknown
    actual_value = switches[switch_name]
    return actual_value == switch_value


# =============================================================================
# Phase 4: Architecture Detection & Sequence Extraction
# =============================================================================

def detect_architecture(rbleol_content, rbleol_file_path=None):
    """
    Detect routine architecture type.
    TYPE_A: Has sequence array + uses TogglingProcess_V (directly or via g_Sequence_PST)
    TYPE_B: Uses TogglingProcess_V but no sequence array
    TYPE_C: Does not use TogglingProcess_V (pure MESG state machine)
    """
    has_sequence = 'RBAPLEOL_SequenceStep_ST' in rbleol_content or 'g_Sequence_PST' in rbleol_content
    uses_toggling_direct = 'RBAPLEOL_TogglingProcess_V' in rbleol_content

    # If has g_Sequence_PST, it's designed for TogglingProcess_V
    # even if the TogglingProcess_V call is in InterfaceAPL.c
    if has_sequence:
        return "TYPE_A", True
    elif uses_toggling_direct:
        return "TYPE_B", True
    else:
        return "TYPE_C", False


def extract_sequences(rbleol_content, switches):
    """
    Extract all SequenceStep_ST arrays from RBAPLEOL file.
    Returns list of dicts: [{name, steps:[{cmd, param}], active}]
    """
    sequences = []

    # Find all static const RBAPLEOL_SequenceStep_ST l_Xxx_PST[] = { ... };
    # This is tricky with #if blocks - we'll do a simplified version
    pattern = r'static\s+const\s+RBAPLEOL_SequenceStep_ST\s+(\w+_PST)\[\]\s*=\s*\{'

    for m in re.finditer(pattern, rbleol_content):
        seq_name = m.group(1)
        start = m.end() - 1  # include the {
        # Find matching }
        depth = 0
        end = start
        in_string = False
        schar = None
        for i in range(start, len(rbleol_content)):
            c = rbleol_content[i]
            if in_string:
                if c == '\\':
                    continue
                if c == schar:
                    in_string = False
            else:
                if c in '"\'':
                    in_string = True
                    schar = c
                elif c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end = i
                        break

        block = rbleol_content[start:end+1]
        steps = []
        # Extract { CMD_XXX, PARAM } entries
        for step_m in re.finditer(r'\{\s*(CMD_\w+)\s*,\s*([^}]+)\}', block):
            cmd = step_m.group(1).strip()
            param = step_m.group(2).strip()
            steps.append({'cmd': cmd, 'param': param})

        # Check if preceded by #if - simple check: look back for #if
        before = rbleol_content[max(0, m.start()-500):m.start()]
        if_m = re.search(r'#if\s*\(\s*(\w+)\s*==\s*(\w+)\s*\)', before)
        active = True
        condition = None
        if if_m:
            switch_name = if_m.group(1)
            switch_value = if_m.group(2)
            condition = f"{switch_name} == {switch_value}"
            result = is_switch_active(switch_name, switch_value, switches)
            if result is False:
                active = False

        sequences.append({
            'name': seq_name,
            'steps': steps,
            'active': active,
            'condition': condition,
        })

    return sequences


# =============================================================================
# Phase 5: Extract CMD Failure Blocks from ValvesToggling.c
# =============================================================================

def extract_preconditions(toggling_content, switches):
    """
    Extract RUNNING state preconditions from ValvesToggling.c.
    Returns list of {condition, extended_status, confidence}
    """
    preconditions = []

    # Find case RBAPLEOL_FctStRUNNING:
    running_pattern = r'case\s+RBAPLEOL_FctStRUNNING:\s*(.*?)case\s+RBAPLEOL_FctSt'
    running_match = re.search(running_pattern, toggling_content, re.DOTALL)
    if not running_match:
        return preconditions

    running_block = running_match.group(1)

    # Extract all if (...) { ... FunctionStatus = INTERRUPTED/STOP }
    # Pattern: if (condition) { ... FunctionStatus = STATUS; ... }
    # We look for lines containing FunctionStatus assignment
    for line in running_block.split('\n'):
        line = line.strip()
        if 'RBAPLEOL_RoutineExtendedStatus' in line and '=' in line:
            # Extract the extended status value
            ext_m = re.search(r'RBAPLEOL_RoutineExtendedStatus\s*=\s*(\w+)', line)
            if ext_m:
                ext_status = ext_m.group(1)
                # Find the preceding if condition (simplified)
                preconditions.append({
                    'extended_status': ext_status,
                    'raw_line': line,
                    'confidence': 'CONFIRMED'
                })

    return preconditions


def extract_cmd_failure_blocks(toggling_content, cmd_list, switches):
    """
    For each CMD in cmd_list, extract its case block and find INTERRUPTED/STOP assignments.
    Returns dict: {cmd: [{condition, extended_status, raw_code}]}
    """
    results = {}

    for cmd in cmd_list:
        # Find case CMD_XXX: from the while loop in RUNNING state
        # The pattern is: case CMD_XXX: ... break; before the next case CMD_
        cmd_pattern = rf'case\s+{re.escape(cmd)}:(.*?)(?=case\s+CMD_|\n\s*\}}\s*break;)'
        cmd_match = re.search(cmd_pattern, toggling_content, re.DOTALL)
        if not cmd_match:
            continue

        block = cmd_match.group(1)
        if not block:
            continue

        failures = []

        # Find all FunctionStatus = INTERRUPTED/STOP assignments in this block
        # Look for patterns like: if (...) { ... FunctionStatus = INTERRUPTED; }
        for m in re.finditer(r'if\s*\(([^)]+)\)', block):
            condition = m.group(1).strip()
            # Check if this if block contains FunctionStatus assignment
            if_start = m.end()
            # Find the matching brace end for this if
            brace_start = block.find('{', if_start)
            if brace_start == -1:
                continue
            brace_depth = 0
            brace_end = brace_start
            for i in range(brace_start, len(block)):
                if block[i] == '{':
                    brace_depth += 1
                elif block[i] == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        brace_end = i
                        break

            if_block = block[brace_start:brace_end+1]
            status_m = re.search(r'RBAPLEOL_RoutineExtendedStatus\s*=\s*(\w+)', if_block)
            if status_m:
                ext_status = status_m.group(1)
                failures.append({
                    'condition': condition,
                    'extended_status': ext_status,
                })

        if failures:
            results[cmd] = failures

    return results


# =============================================================================
# Main Analyzer
# =============================================================================

def analyze_routine(project_root, rid, variant=None):
    """Main analysis pipeline."""
    rid_int = int(rid, 0)
    results = {
        'rid': f"0x{rid_int:04X}",
        'rid_int': rid_int,
        'variant': variant,
        'phases': {}
    }

    # Phase 1: Parse Dcm_Lcfg
    print("=" * 60)
    print("Phase 1: Parsing Dcm_Lcfg_DspUds.c")
    print("=" * 60)

    lcfg_file = find_dcm_lcfg(project_root, variant)
    if not lcfg_file:
        print("ERROR: Dcm_Lcfg_DspUds.c not found")
        return None

    print(f"  Using: {lcfg_file}")
    dcm_results = parse_dcm_lcfg(str(lcfg_file))

    if rid_int not in dcm_results:
        print(f"ERROR: RID 0x{rid_int:04X} not found in Dcm_Lcfg")
        return None

    info = dcm_results[rid_int]
    results['dcm'] = info

    print(f"  Config Name: {info['name']}")
    print(f"  Start:       {info['start_func']}")
    print(f"  Stop:        {info['stop_func']}")
    print(f"  RequestResult: {info['req_func']}")
    print(f"  Output Signals: {info['num_out_signals']}")

    if info['num_out_signals'] == 1:
        print("  [NOTE] Only 1 output signal -> NO dataOut2. Cannot distinguish failure reason from response alone.")

    # Phase 2: Locate files
    print("\n" + "=" * 60)
    print("Phase 2: Locating source files")
    print("=" * 60)

    rblcust_file = find_rblcust_file(project_root, info['req_func'])
    rbleol_file = None
    rbleol_calls = []
    if rblcust_file:
        rblcust_content = rblcust_file.read_text(encoding='utf-8', errors='ignore')
        rbleol_calls = extract_rbleol_calls(rblcust_content)
        if rbleol_calls:
            rbleol_file = find_rbleol_file(project_root, rbleol_calls)

    print(f"  RBAPLCUST: {rblcust_file or 'NOT FOUND'}")
    print(f"  RBAPLEOL:  {rbleol_file or 'NOT FOUND'}")
    if rbleol_calls:
        print(f"  RBAPLEOL calls found: {', '.join(rbleol_calls[:5])}")

    results['files'] = {
        'rblcust': str(rblcust_file) if rblcust_file else None,
        'rbleol': str(rbleol_file) if rbleol_file else None,
    }

    # Phase 3: SwitchSettings
    print("\n" + "=" * 60)
    print("Phase 3: Reading SwitchSettings.csv")
    print("=" * 60)

    switch_csv = find_switch_settings(project_root, variant)
    switches = {}
    if switch_csv:
        print(f"  Using: {switch_csv}")
        switches = parse_switch_settings(str(switch_csv))
        print(f"  Loaded {len(switches)} switches")

        # Print relevant switches
        relevant = [k for k in switches.keys() if 'RBAPLEOL' in k or 'RBFS_RBAPLEOL' in k]
        for k in relevant[:10]:
            print(f"    {k} = {switches[k]}")
    else:
        print("  WARNING: SwitchSettings.csv not found")

    results['switches'] = switches

    # Phase 4: Architecture Detection
    print("\n" + "=" * 60)
    print("Phase 4: Detecting architecture type")
    print("=" * 60)

    if not rbleol_file:
        print("  ERROR: RBAPLEOL file not found, cannot determine architecture")
        results['architecture'] = "UNKNOWN"
        return results

    rbleol_content = rbleol_file.read_text(encoding='utf-8', errors='ignore')
    arch_type, uses_toggling = detect_architecture(rbleol_content)

    print(f"  Architecture: {arch_type}")
    print(f"  Uses TogglingProcess_V: {uses_toggling}")

    results['architecture'] = arch_type

    sequences = []
    if arch_type == "TYPE_A":
        sequences = extract_sequences(rbleol_content, switches)
        active_seqs = [s for s in sequences if s['active']]
        inactive_seqs = [s for s in sequences if not s['active']]

        print(f"  Found {len(sequences)} sequence(s)")
        print(f"    Active: {len(active_seqs)}")
        print(f"    Inactive (filtered by SwitchSettings): {len(inactive_seqs)}")

        for seq in active_seqs:
            print(f"\n    Sequence: {seq['name']}")
            for i, step in enumerate(seq['steps']):
                print(f"      Step {i}: {step['cmd']:<30s} param={step['param']}")

    results['sequences'] = sequences

    # Phase 5: Extract failure blocks from ValvesToggling.c
    if uses_toggling:
        print("\n" + "=" * 60)
        print("Phase 5: Extracting failure points from ValvesToggling.c")
        print("=" * 60)

        toggling_file = find_valves_toggling(project_root)
        if toggling_file:
            print(f"  Using: {toggling_file}")
            toggling_content = toggling_file.read_text(encoding='utf-8', errors='ignore')

            # Extract preconditions
            preconditions = extract_preconditions(toggling_content, switches)
            print(f"\n  [Preconditions] RUNNING state checks ({len(preconditions)} found):")
            for pc in preconditions:
                print(f"    -> {pc['extended_status']}")

            # Extract CMD-specific failures
            if arch_type == "TYPE_A" and sequences:
                active_seqs = [s for s in sequences if s['active']]
                if active_seqs:
                    all_cmds = set()
                    for seq in active_seqs:
                        for step in seq['steps']:
                            all_cmds.add(step['cmd'])

                    cmd_failures = extract_cmd_failure_blocks(toggling_content, sorted(all_cmds), switches)
                    print(f"\n  [CMD-specific failures] ({len(cmd_failures)} CMDs with failures):")
                    for cmd, failures in cmd_failures.items():
                        print(f"\n    {cmd}:")
                        for f in failures:
                            cond = f['condition'] or '(implicit)'
                            print(f"      Condition: {cond}")
                            print(f"      -> {f['extended_status']}")

                    results['cmd_failures'] = cmd_failures

            results['preconditions'] = preconditions
        else:
            print("  WARNING: RBAPLEOL_ValvesToggling.c not found")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Analyze 31 Service Routine failure reasons"
    )
    parser.add_argument("project_root", help="Project root path")
    parser.add_argument("--rid", required=True, help="Routine ID (hex, e.g. 0x2C39)")
    parser.add_argument("--variant", help="Specific variant (e.g. MM21xSoftECUxECC)")
    parser.add_argument("--output", help="Output JSON file")
    args = parser.parse_args()

    results = analyze_routine(args.project_root, args.rid, args.variant)

    if args.output and results:
        import json
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
