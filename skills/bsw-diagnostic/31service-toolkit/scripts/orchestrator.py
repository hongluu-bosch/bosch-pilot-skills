"""
31service-toolkit - Main orchestrator.
Coordinates the full workflow:
  auto-resolve project root -> scan -> parse requirement -> calculate changes
  -> generate diff + Excel summary -> (confirm or --yes) -> apply -> log
"""

import sys
import os
import io
import json
import glob
from datetime import datetime

# Fix Windows console encoding for Chinese characters
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Ensure we can import sibling scripts
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from scan_routines import scan_project, save_scan_metadata
from requirement_parser import parse_requirement
from rid_calculator import apply_command_to_routines, check_conflicts, summarize_changes
from diff_generator import generate_diff, generate_diff_preview
from generate_excel import generate_change_summary_excel
from update_arxml import apply_updates
from product_resolver import format_ambiguity_prompt
from rid_adder import add_routine


COMMON_AUTO_SYNC_FILE = "common_auto_sync.json"

def get_common_auto_sync_path(state_dir):
    return os.path.join(state_dir, COMMON_AUTO_SYNC_FILE)


def load_common_auto_sync(state_dir):
    """Load common_auto_sync.json if exists. Returns dict or None."""
    path = get_common_auto_sync_path(state_dir)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_common_auto_sync(state_dir, data):
    """Save common_auto_sync.json."""
    path = get_common_auto_sync_path(state_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def reset_common_auto_sync(state_dir):
    """Delete common_auto_sync.json if exists."""
    path = get_common_auto_sync_path(state_dir)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def save_product_ranges(state_dir, product_ranges):
    """
    Save per-product assigned ranges to product_ranges.json.
    product_ranges: dict of product_type -> [(start, end), ...]
    """
    path = os.path.join(state_dir, "product_ranges.json")
    # Load existing
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    
    # Merge: append new ranges, avoiding duplicates
    for pt, ranges in product_ranges.items():
        if pt not in existing:
            existing[pt] = []
        for r in ranges:
            if r not in existing[pt]:
                existing[pt].append(r)
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)


def load_historical_ranges(state_dir):
    """
    Load all historical product ranges from product_ranges.json.
    Returns dict: product_type -> [(start, end), ...]
    """
    path = os.path.join(state_dir, "product_ranges.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Convert lists back to tuples
        historical = {}
        for pt, ranges in data.items():
            historical[pt] = [tuple(r) for r in ranges if isinstance(r, (list, tuple)) and len(r) == 2]
        return historical
    except Exception:
        return {}


def _is_valid_project_root(directory):
    """
    Check if a directory matches the project root pattern:
      - Contains at least one direct subdirectory
      - That subdirectory directly contains both 'rb' and 'rba' folders
      - The 'rb' folder directly contains 'as' folder
    """
    try:
        for item in os.listdir(directory):
            item_path = os.path.join(directory, item)
            if not os.path.isdir(item_path):
                continue

            rb_path = os.path.join(item_path, "rb")
            rba_path = os.path.join(item_path, "rba")
            as_path = os.path.join(rb_path, "as")

            if (os.path.isdir(rb_path) and
                    os.path.isdir(rba_path) and
                    os.path.isdir(as_path)):
                return True
    except (PermissionError, OSError):
        pass
    return False


def resolve_project_root(start_dir=None):
    """
    Auto-resolve project root by walking up from start_dir (or cwd).

    A valid project root must have at least one direct subdirectory that
    contains both 'rb' and 'rba', with 'rb/as' present.

    Returns the topmost (outermost) directory satisfying this condition.
    Raises RuntimeError if none found.
    """
    if start_dir is None:
        start_dir = os.getcwd()
    start_dir = os.path.abspath(start_dir)

    candidate_roots = []
    current = start_dir

    while True:
        if _is_valid_project_root(current):
            candidate_roots.append(current)

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    if not candidate_roots:
        raise RuntimeError(
            f"Could not find project root: no directory with '*/rb/as' + '*/rba' "
            f"structure found under '{start_dir}' or its parents.\n"
            f"Please run this skill from within the project workspace."
        )

    # Return the topmost (outermost) candidate
    root = candidate_roots[-1]

    # Sanity check: warn if multiple sibling projects at the outermost level
    parent_of_root = os.path.dirname(root)
    if parent_of_root and parent_of_root != root:
        siblings = []
        for item in os.listdir(parent_of_root):
            item_path = os.path.join(parent_of_root, item)
            if os.path.isdir(item_path) and _is_valid_project_root(item_path):
                siblings.append(item_path)
        if len(siblings) > 1:
            print(
                f"[WARN] Multiple potential project roots found under {parent_of_root}: "
                f"{', '.join(os.path.basename(s) for s in siblings)}. "
                f"Using the outermost match: {root}"
            )

    return root


def get_workspace_dirs(project_root):
    """Return workspace output and state directories."""
    workspace = os.path.join(project_root, ".DCOM_AI", "31Service_Toolkit_PRJ")
    outputs = os.path.join(workspace, "outputs")
    state = os.path.join(workspace, "state")
    os.makedirs(outputs, exist_ok=True)
    os.makedirs(state, exist_ok=True)
    return outputs, state


def run_workflow(requirement_text, dry_run=False, yes=False, file_hint=None):
    """
    Main workflow entry point.

    Args:
        requirement_text: user natural language requirement
        dry_run: if True, only generate diff/summary without modifying files
        yes: if True, skip confirmation prompt and apply directly
        file_hint: for Common file selection in add_routine, None = ask

    Returns:
        dict with status and file paths
    """
    now = datetime.now()
    ts_str = now.strftime("%Y%m%d_%H%M%S")
    ts_iso = now.isoformat()

    # ------------------------------------------------------------------
    # Step 1: Resolve project root (auto-detect only, no override)
    # ------------------------------------------------------------------
    project_root = resolve_project_root()
    project_root = os.path.abspath(project_root)

    print(f"[INFO] Project root: {project_root}")

    outputs_dir, state_dir = get_workspace_dirs(project_root)
    
    # ------------------------------------------------------------------
    # Step 2: Scan project
    # ------------------------------------------------------------------
    print("[SCAN] Scanning project arxml files...")
    routines = scan_project(project_root)
    
    if not routines:
        print("[WARN] No routines found. Check project structure.")
        return {"status": "no_routines", "project_root": project_root}
    
    print(f"[SCAN] Found {len(routines)} routines across {len(set(r['product_type'] for r in routines))} product types")
    
    # Save scan state
    json_path = os.path.join(state_dir, "routines.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(routines, f, indent=2, ensure_ascii=False)
    
    meta_path = save_scan_metadata(project_root, routines, os.path.dirname(outputs_dir))
    
    # ------------------------------------------------------------------
    # Step 3: Parse requirement
    # ------------------------------------------------------------------
    available_products = sorted(set(r['product_type'] for r in routines))
    print(f"[INFO] Available products: {', '.join(available_products)}")
    
    print(f"[PARSE] Parsing requirement: {requirement_text!r}")
    try:
        command = parse_requirement(requirement_text, available_products=available_products)
    except ValueError as e:
        print(f"[ERROR] Failed to parse requirement: {e}")
        return {"status": "parse_error", "error": str(e)}
    
    print(f"[PARSE] Detected command type: {command['command_type']}")
    
    # ------------------------------------------------------------------
    # Step 3.4: Route ADD_ROUTINE commands to rid_adder
    # ------------------------------------------------------------------
    if command["command_type"] == "add_routine":
        print("[ADD-ROUTINE] Routing to RID adder workflow...")
        request = command.get("parameters", {})
        if not request:
            return {"status": "error", "message": "ADD_ROUTINE command missing parameters"}
        
        result = add_routine(project_root, request, file_hint=file_hint, dry_run=dry_run)
        
        if result["status"] == "need_common_file_selection":
            return {
                "status": "need_common_file_selection",
                "project_root": project_root,
                "command": command,
                "prompt": result["message"],
                "common_files": result.get("common_files", []),
                "request": result.get("request", {})
            }
        
        if result["status"] in ("error", "partial_success"):
            print(f"[ADD-ROUTINE] {result['status'].upper()}: {result['message']}")
        else:
            print(f"[ADD-ROUTINE] {result['message']}")
        
        return {
            "status": result["status"],
            "project_root": project_root,
            "message": result.get("message", ""),
            "target_files": result.get("target_files", []),
            "rid_decimal": result.get("rid_decimal"),
            "routine_name": result.get("routine_name")
        }
    
    # ------------------------------------------------------------------
    # Step 3.5: Ambiguity check for product names
    # ------------------------------------------------------------------
    if command.get("ambiguous"):
        print("\n[AMBIGUOUS] Product name ambiguity detected!")
        prompt = format_ambiguity_prompt(command["ambiguous"])
        print(prompt)
        return {
            "status": "ambiguous_products",
            "project_root": project_root,
            "command": command,
            "prompt": prompt
        }
    
    explicit = command.get("explicit_products", [])
    modify = command.get("modify_products", explicit)
    if explicit:
        print(f"[PARSE] Explicitly mentioned products: {', '.join(explicit)}")
    else:
        print("[PARSE] No explicit product filter — applying to ALL products.")
    
    # ------------------------------------------------------------------
    # Step 3.6: Common auto-sync logic
    # ------------------------------------------------------------------
    common_synced = False
    common_auto_sync = False
    if "Common" in available_products and "Common" not in modify:
        sync_state = load_common_auto_sync(state_dir)
        if sync_state is None:
            # First time: auto-add Common
            modify = ["Common"] + list(modify)
            common_auto_sync = True
            print(f"[COMMON-SYNC] Common will auto-follow (first sync). Products to modify: {', '.join(modify)}")
        else:
            # Already synced before
            common_synced = True
            print(f"[COMMON-SYNC] Common already synced previously. Only modifying: {', '.join(modify)}")
    else:
        if modify:
            print(f"[PARSE] Products to modify: {', '.join(modify)}")
        else:
            print(f"[PARSE] Products to modify: ALL")
    
    skipped = [p for p in available_products if p not in (modify or [])]
    if skipped:
        print(f"[PARSE] Products skipped (unchanged): {', '.join(skipped)}")
    
    # Update command with potentially modified product list
    command["modify_products"] = modify
    
    # ------------------------------------------------------------------
    # Step 4: Calculate changes
    # ------------------------------------------------------------------
    print("[CALC] Calculating RID changes...")
    changes, calc_errors = apply_command_to_routines(routines, command)
    
    if calc_errors:
        print(f"[ERROR] Calculation errors ({len(calc_errors)}):")
        for err in calc_errors:
            print(f"  - {err}")
        return {"status": "calc_error", "errors": calc_errors}
    
    # ------------------------------------------------------------------
    # Step 4.5: Range overlap detection with historical ranges
    # ------------------------------------------------------------------
    if command["command_type"] in ("sequential_assign", "offset_shift"):
        # Compute per-product sub-ranges from changes
        current_ranges = {}
        for c in changes:
            if not c["changed"]:
                continue
            pt = c["routine"].get("product_type", "")
            rid = c["new_rid_decimal"]
            if pt not in current_ranges:
                current_ranges[pt] = [rid, rid]
            else:
                current_ranges[pt][0] = min(current_ranges[pt][0], rid)
                current_ranges[pt][1] = max(current_ranges[pt][1], rid)
        
        # Load historical ranges
        historical = load_historical_ranges(state_dir)
        overlap_errors = []
        for pt, (cur_start, cur_end) in current_ranges.items():
            hist = historical.get(pt, [])
            # Check overlap with other products' current ranges (different products must not overlap)
            other_items = [(k, v) for k, v in current_ranges.items() if k != pt]
            for other_pt, (other_start, other_end) in other_items:
                if pt > other_pt:  # Only report each pair once (lexicographic ordering)
                    continue
                if not (cur_end < other_start or other_end < cur_start):
                    overlap_errors.append(
                        f"OVERLAP: Product '{pt}' range 0x{cur_start:04X}-0x{cur_end:04X} "
                        f"overlaps with product '{other_pt}' range 0x{other_start:04X}-0x{other_end:04X}. "
                        f"Different products must have independent RID ranges."
                    )
            # Check overlap with historical ranges for same product
            for h_start, h_end in hist:
                if not (cur_end < h_start or h_end < cur_start):
                    if pt == "Common":
                        advice = "Please use --reset-common-auto or specify a non-overlapping range."
                    else:
                        advice = "Please specify a non-overlapping range."
                    overlap_errors.append(
                        f"OVERLAP: Product '{pt}' new range 0x{cur_start:04X}-0x{cur_end:04X} "
                        f"overlaps with previously assigned range 0x{h_start:04X}-0x{h_end:04X}. "
                        f"{advice}"
                    )
        
        if overlap_errors:
            print(f"[OVERLAP] Range overlap detected ({len(overlap_errors)}):")
            for e in overlap_errors:
                print(f"  - {e}")
            return {"status": "range_overlap", "errors": overlap_errors}
    
    # Check conflicts
    conflicts = check_conflicts(changes)
    if conflicts:
        print(f"[CONFLICT] Conflicts detected ({len(conflicts)}):")
        for c in conflicts:
            print(f"  - {c}")
        return {"status": "conflicts", "conflicts": conflicts}
    
    summary = summarize_changes(changes)
    changed_items = [c for c in changes if c["changed"]]
    
    if not changed_items:
        print("[INFO] No changes to apply.")
        return {"status": "no_changes", "project_root": project_root}
    
    print(f"[CALC] {summary['changed_count']} routines will be modified across {summary['files_affected']} file(s)")
    
    # ------------------------------------------------------------------
    # Step 5: Build update list for diff and apply
    # ------------------------------------------------------------------
    updates = []
    for c in changed_items:
        updates.append({
            "product_type": c["routine"].get("product_type", ""),
            "arxml_path": c["routine"].get("arxml_path", ""),
            "routine_name": c["routine"]["short_name"],
            "current_rid_decimal": c["old_rid_decimal"],
            "current_rid_hex": c["old_rid_hex"],
            "new_rid_decimal": c["new_rid_decimal"],
            "new_rid_hex": c["new_rid_hex"]
        })
    
    # ------------------------------------------------------------------
    # Step 6: Generate diff (pass unified timestamp)
    # ------------------------------------------------------------------
    diff_path, diff_content = generate_diff(project_root, updates, command["raw_text"], outputs_dir, ts_str=ts_str)
    print(f"[DIFF] Diff saved: {diff_path}")
    
    # ------------------------------------------------------------------
    # Step 7: Generate Excel summary
    # ------------------------------------------------------------------
    excel_path = os.path.join(outputs_dir, "rid_changes_summary.xlsx")
    generate_change_summary_excel(changes, excel_path, command["raw_text"])
    
    # ------------------------------------------------------------------
    # Step 8: Preview
    # ------------------------------------------------------------------
    preview = generate_diff_preview(changes, max_lines=50)
    print("\n" + preview)
    
    # ------------------------------------------------------------------
    # Step 9: Dry run or confirm
    # ------------------------------------------------------------------
    if dry_run:
        print("\n[DRY-RUN] No files modified. Diff and summary Excel generated for review.")
        return {
            "status": "dry_run",
            "project_root": project_root,
            "diff_path": diff_path,
            "excel_path": excel_path,
            "changes": summary
        }
    
    if not yes:
        print("\n" + "=" * 60)
        print("Please review the diff and summary Excel above.")
        print(f"  Diff:    {diff_path}")
        print(f"  Excel:   {excel_path}")
        print("\nTo apply these changes, confirm by responding with '确认' or 'yes'.")
        print("To cancel, respond with '取消' or 'cancel'.")
        print("=" * 60)
        
        # In agent mode, we return and let the caller handle confirmation
        return {
            "status": "awaiting_confirmation",
            "project_root": project_root,
            "diff_path": diff_path,
            "excel_path": excel_path,
            "changes": summary,
            "updates": updates
        }
    
    # ------------------------------------------------------------------
    # Step 10: Apply updates
    # ------------------------------------------------------------------
    print("\n[APPLY] Applying changes to arxml files...")
    success_count, apply_errors = apply_updates(project_root, updates, dry_run=False)
    
    print(f"[APPLY] {success_count} updates applied successfully")
    if apply_errors:
        print(f"[APPLY] {len(apply_errors)} errors:")
        for e in apply_errors:
            print(f"  - {e}")
    
    # If Common was auto-synced, save state
    if common_auto_sync and not apply_errors:
        # Compute range from updates
        common_updates = [u for u in updates if u.get("product_type") == "Common"]
        rids = [u["new_rid_decimal"] for u in common_updates]
        save_common_auto_sync(state_dir, {
            "auto_synced": True,
            "range_start": min(rids) if rids else None,
            "range_end": max(rids) if rids else None,
            "timestamp": ts_iso,
            "products_included": modify,
            "routine_count": len(common_updates)
        })
        print(f"[COMMON-SYNC] Saved auto-sync state for Common ({len(common_updates)} routines).")
    
    # Save per-product ranges for future overlap detection
    if not apply_errors:
        product_ranges = {}
        for c in changes:
            if not c["changed"]:
                continue
            pt = c["routine"].get("product_type", "")
            rid = c["new_rid_decimal"]
            if pt not in product_ranges:
                product_ranges[pt] = [rid, rid]
            else:
                product_ranges[pt][0] = min(product_ranges[pt][0], rid)
                product_ranges[pt][1] = max(product_ranges[pt][1], rid)
        # Convert to tuple list
        ranges_to_save = {pt: [(r[0], r[1])] for pt, r in product_ranges.items()}
        save_product_ranges(state_dir, ranges_to_save)
        print("[RANGE-SYNC] Saved per-product RID ranges.")
    
    # ------------------------------------------------------------------
    # Step 11: Save log
    # ------------------------------------------------------------------
    log_path = os.path.join(state_dir, f"update_log_{ts_str}.json")
    log_data = {
        "timestamp": ts_iso,
        "requirement": requirement_text,
        "command": command,
        "dry_run": dry_run,
        "forced": yes,
        "updates": updates,
        "conflicts": conflicts,
        "errors": apply_errors,
        "success_count": success_count,
        "diff_path": diff_path,
        "excel_path": excel_path
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)
    print(f"[LOG] Update log saved: {log_path}")
    
    return {
        "status": "success" if not apply_errors else "partial_success",
        "project_root": project_root,
        "diff_path": diff_path,
        "excel_path": excel_path,
        "log_path": log_path,
        "changes": summary,
        "errors": apply_errors
    }


def confirm_and_apply(requirement_text, file_hint=None):
    """
    Two-phase workflow helper:
      Phase 1: run_workflow() -> returns awaiting_confirmation
      Phase 2: this function receives confirmation and applies.

    In practice, the agent calls run_workflow() first, shows preview to user,
    then if user confirms, calls this function with the same args.
    """
    return run_workflow(requirement_text, dry_run=False, yes=True, file_hint=file_hint)


def main_cli():
    """Command-line entry point for testing/direct use."""
    import argparse
    parser = argparse.ArgumentParser(
        description="31service-toolkit: Manage RoutineControl (0x31) RIDs via natural language"
    )
    parser.add_argument("requirement", nargs="*", help="Natural language requirement text")
    parser.add_argument("--dry-run", action="store_true", help="Preview without modifying files")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation and apply directly")
    parser.add_argument("--reset-common-auto", action="store_true", help="Reset Common auto-sync state to allow re-sync")
    args = parser.parse_args()
    
    # Handle --reset-common-auto
    if args.reset_common_auto:
        project_root = resolve_project_root()
        project_root = os.path.abspath(project_root)
        _, state_dir = get_workspace_dirs(project_root)
        if reset_common_auto_sync(state_dir):
            print("[COMMON-SYNC] Common auto-sync state has been reset.")
            print("[COMMON-SYNC] Next non-Common product modification will trigger Common auto-sync again.")
        else:
            print("[COMMON-SYNC] No Common auto-sync state found (nothing to reset).")
        return 0
    
    requirement = " ".join(args.requirement)
    result = run_workflow(requirement, dry_run=args.dry_run, yes=args.yes)
    
    # Print result status
    print(f"\n[RESULT] Status: {result['status']}")
    if "diff_path" in result:
        print(f"[RESULT] Diff: {result['diff_path']}")
    if "excel_path" in result:
        print(f"[RESULT] Excel: {result['excel_path']}")
    
    return 0 if result["status"] in ("success", "dry_run", "no_changes") else 1


if __name__ == "__main__":
    sys.exit(main_cli())
