"""
31service-toolkit - Apply RID updates to arxml files.
Uses pure text replacement to preserve exact XML formatting.
Locates the VALUE by routine context, not by old value matching.
"""

import sys
import os
import json
import re

from arxml_text_utils import replace_routine_rid_in_text


def apply_updates(project_root, updates, dry_run=False):
    """
    Apply RID updates to arxml files using pure text replacement.
    This preserves XML declaration quotes, comments, indentation, and all formatting.
    
    updates: list of dicts with keys arxml_path, routine_name, new_rid_decimal, current_rid_decimal
    dry_run: if True, only report what would change
    Returns (success_count, error_list)
    """
    # Group updates by arxml file
    files_to_update = {}
    for u in updates:
        arxml_path = u["arxml_path"]
        if arxml_path not in files_to_update:
            files_to_update[arxml_path] = []
        files_to_update[arxml_path].append(u)

    success_count = 0
    errors = []

    for arxml_rel_path, file_updates in files_to_update.items():
        abs_path = os.path.join(project_root, arxml_rel_path)
        if not os.path.exists(abs_path):
            errors.append(f"File not found: {arxml_rel_path}")
            continue

        try:
            # Read original file text to preserve all formatting
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()

            updated_in_file = 0
            for update in file_updates:
                routine_name = update["routine_name"]
                new_rid = str(update["new_rid_decimal"])
                old_rid = str(update.get("current_rid_decimal", "unknown"))

                if dry_run:
                    print(f"[DRY-RUN] Would update {arxml_rel_path}: {routine_name} {old_rid} -> {new_rid}")
                    updated_in_file += 1
                    continue

                result = replace_routine_rid_in_text(content, routine_name, new_rid)
                if result is not None:
                    content = result
                    print(f"[UPDATED] {arxml_rel_path}: {routine_name} {old_rid} -> {new_rid}")
                    updated_in_file += 1
                else:
                    errors.append(f"Failed to locate and replace RID for {routine_name} in {arxml_rel_path}")

            if not dry_run and updated_in_file > 0:
                with open(abs_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"  Saved: {arxml_rel_path} ({updated_in_file} updates)")

            success_count += updated_in_file

        except Exception as e:
            errors.append(f"Error processing {arxml_rel_path}: {e}")

    return success_count, errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Apply RID updates to arxml files")
    parser.add_argument("--project-root", required=True, help="Project root directory (deprecated: auto-detected when used via orchestrator)")
    parser.add_argument("--updates-json", required=True, help="JSON file with updates")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()

    import warnings
    warnings.warn(
        "--project-root is deprecated; project root is auto-detected when using orchestrator.",
        DeprecationWarning,
        stacklevel=2
    )

    with open(args.updates_json, "r", encoding="utf-8") as f:
        updates = json.load(f)

    print(f"Applying {len(updates)} updates (dry_run={args.dry_run})...")
    success, errors = apply_updates(args.project_root, updates, dry_run=args.dry_run)

    print(f"\nSummary: {success} successful updates")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
