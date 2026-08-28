"""
31service-toolkit - Scan project arxml files for RoutineControl (0x31) RIDs.
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arxml_utils import parse_arxml, get_routine_containers, extract_routine_info, find_services_arxml_files


def scan_project(project_root):
    """
    Scan all Dcm_CusDiag_Services*.arxml files for routines.
    Returns list of dicts with routine info.
    """
    arxml_files = find_services_arxml_files(project_root)
    all_routines = []

    for rel_path, abs_path, product_type in arxml_files:
        try:
            tree, root = parse_arxml(abs_path)
            routines = get_routine_containers(root)
            for container, _ in routines:
                info = extract_routine_info(container)
                if info:
                    info["product_type"] = product_type
                    info["arxml_path"] = rel_path
                    info["arxml_absolute"] = abs_path
                    all_routines.append(info)
        except Exception as e:
            print(f"[WARN] Failed to parse {rel_path}: {e}", file=sys.stderr)

    # Sort by product_type then rid_decimal
    all_routines.sort(key=lambda x: (x["product_type"], x["rid_decimal"]))
    return all_routines


def save_scan_metadata(project_root, routines, output_dir):
    """Save scan metadata for future reference."""
    meta = {
        "project_root": project_root,
        "scan_time": datetime.now().isoformat(),
        "total_routines": len(routines),
        "products": sorted(set(r["product_type"] for r in routines)),
        "files": sorted(set(r["arxml_path"] for r in routines))
    }
    meta_path = os.path.join(output_dir, "state", "scan_metadata.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Scan project for RoutineControl RIDs")
    parser.add_argument("--project-root", required=True, help="Project root directory (deprecated: auto-detected when used via orchestrator)")
    parser.add_argument("--output-dir", required=True, help="Workspace output directory")
    args = parser.parse_args()

    import warnings
    warnings.warn(
        "--project-root is deprecated; project root is auto-detected when using orchestrator.",
        DeprecationWarning,
        stacklevel=2
    )

    routines = scan_project(args.project_root)
    print(f"Found {len(routines)} routines")
    for r in routines[:10]:
        print(f"  [{r['product_type']}] {r['short_name']}: {r['rid_decimal']} ({r['rid_hex']}) in {r['arxml_path']}")
    if len(routines) > 10:
        print(f"  ... and {len(routines) - 10} more")

    meta_path = save_scan_metadata(args.project_root, routines, args.output_dir)
    print(f"Metadata saved to: {meta_path}")
