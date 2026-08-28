"""
31service-toolkit - Diff generator.
Generates unified diff text for arxml file changes (RID value modifications only).
"""

import os
import difflib
from datetime import datetime

from arxml_text_utils import replace_routine_rid_in_text


def generate_diff(project_root, updates, command_text, output_dir, ts_str=None):
    """
    Generate unified diff for RID changes.
    
    Args:
        project_root: absolute path to project root
        updates: list of update dicts (same format as update_arxml.py input)
        command_text: original user requirement text for metadata
        output_dir: directory to save the diff file
        ts_str: optional timestamp string (YYYYMMDD_HHMMSS) to unify with log filename
    
    Returns:
        diff_path: path to saved diff file
        diff_content: the full diff text string
    """
    # Group updates by arxml file
    files_to_update = {}
    for u in updates:
        arxml_path = u["arxml_path"]
        if arxml_path not in files_to_update:
            files_to_update[arxml_path] = []
        files_to_update[arxml_path].append(u)
    
    diff_parts = []
    
    # Header
    diff_parts.append(f"# 31service-toolkit RID Change Diff")
    if ts_str:
        diff_parts.append(f"# Generated: {ts_str[:4]}-{ts_str[4:6]}-{ts_str[6:8]} {ts_str[9:11]}:{ts_str[11:13]}:{ts_str[13:15]}")
    else:
        diff_parts.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    diff_parts.append(f"# Command: {command_text}")
    diff_parts.append(f"# Total changes: {len(updates)} routines in {len(files_to_update)} files")
    diff_parts.append("")
    
    for arxml_rel_path, file_updates in sorted(files_to_update.items()):
        abs_path = os.path.join(project_root, arxml_rel_path)
        if not os.path.exists(abs_path):
            diff_parts.append(f"# WARNING: File not found: {arxml_rel_path}")
            continue
        
        with open(abs_path, "r", encoding="utf-8") as f:
            original_lines = f.read().splitlines(keepends=False)
        
        # Compute modified content for this file
        modified_content = _apply_changes_to_file(abs_path, file_updates)
        modified_lines = modified_content.splitlines(keepends=False)
        
        # Generate unified diff
        file_diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=arxml_rel_path,
            tofile=arxml_rel_path,
            lineterm=""
        )
        
        file_diff_lines = list(file_diff)
        if file_diff_lines:
            diff_parts.extend(file_diff_lines)
            diff_parts.append("")  # blank line between files
    
    diff_content = "\n".join(diff_parts)
    
    # Save to file
    os.makedirs(output_dir, exist_ok=True)
    if ts_str is None:
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    diff_path = os.path.join(output_dir, f"rid_changes_{ts_str}.diff")
    with open(diff_path, "w", encoding="utf-8") as f:
        f.write(diff_content)
    
    return diff_path, diff_content


def _apply_changes_to_file(abs_path, file_updates):
    """
    Apply RID changes to a file in memory (for diff generation).
    Uses the same logic as update_arxml.py but returns modified text instead of writing.
    """
    with open(abs_path, "r", encoding="utf-8") as f:
        content = f.read()

    for update in file_updates:
        routine_name = update["routine_name"]
        new_rid = str(update["new_rid_decimal"])
        result = replace_routine_rid_in_text(content, routine_name, new_rid)
        if result is not None:
            content = result
        else:
            print(f"[WARN] Failed to locate routine '{routine_name}' for diff generation")

    return content


def generate_diff_preview(changes, max_lines=50):
    """
    Generate a short text preview of changes for display to user.
    
    Args:
        changes: list of change dicts from rid_calculator.apply_command_to_routines()
        max_lines: maximum number of changed items to show
    
    Returns:
        preview_text: human-readable preview string
    """
    changed = [c for c in changes if c["changed"]]
    if not changed:
        return "No changes to apply."
    
    lines = []
    lines.append(f"=== RID Change Preview ({len(changed)} routines) ===")
    lines.append("")
    
    # Group by file
    by_file = {}
    for c in changed:
        fpath = c["routine"].get("arxml_path", "unknown")
        if fpath not in by_file:
            by_file[fpath] = []
        by_file[fpath].append(c)
    
    count = 0
    for fpath, items in sorted(by_file.items()):
        lines.append(f"File: {fpath}")
        for c in items:
            rname = c["routine"]["short_name"]
            old_h = c["old_rid_hex"]
            new_h = c["new_rid_hex"]
            lines.append(f"  {rname}: {old_h} -> {new_h}")
            count += 1
            if count >= max_lines:
                remaining = len(changed) - max_lines
                lines.append(f"  ... and {remaining} more changes")
                return "\n".join(lines)
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Self-test stub
    print("diff_generator loaded. Run via orchestrator for full functionality.")
