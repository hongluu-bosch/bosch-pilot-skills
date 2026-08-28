"""
31service-toolkit - RID calculator.
Applies parsed commands to scanned routines and performs conflict detection.
"""

from requirement_parser import compute_new_rid


def _build_sorted_routines(routines, modify_products):
    """Build sorted list of in-scope routines. Common always first, then by user-specified order."""
    def _is_in_scope(routine):
        if not modify_products:
            return True
        return routine.get("product_type", "") in modify_products
    
    def _sort_key(r):
        pt = r.get("product_type", "")
        if modify_products and pt in modify_products:
            if pt == "Common":
                priority = 0
            else:
                priority = modify_products.index(pt) + 1
        else:
            priority = 999
        return (priority, r["rid_decimal"])
    
    return sorted([r for r in routines if _is_in_scope(r)], key=_sort_key)


def _assign_sequential_with_dedup(sorted_routines, start, end):
    """
    Sequential assign with per-product deduplication.
    Within each product type, routines with the same short_name share the same new RID.
    Returns dict mapping (product_type, short_name, arxml_path) -> new_rid.
    """
    capacity = end - start + 1
    
    # Count unique entries per product: dedup by (product_type, short_name)
    seen = set()
    total_needed = 0
    for r in sorted_routines:
        key = (r.get("product_type"), r["short_name"])
        if key not in seen:
            seen.add(key)
            total_needed += 1
    
    if total_needed > capacity:
        return None, (
            f"Range 0x{start:04X}-0x{end:04X} ({capacity} values) is too small "
            f"for {total_needed} unique (product, name) combinations (after dedup). "
            f"Please expand the range."
        )
    
    # Assign RIDs
    rid_map = {}  # (product_type, short_name, arxml_path) -> new_rid
    offset = 0
    assigned = {}  # (product_type, short_name) -> new_rid
    
    for r in sorted_routines:
        pt = r.get("product_type")
        name = r["short_name"]
        path = r["arxml_path"]
        key = (pt, name)
        
        if key not in assigned:
            assigned[key] = start + offset
            offset += 1
        
        rid_map[(pt, name, path)] = assigned[key]
    
    return rid_map, None


def apply_command_to_routines(routines, command):
    """
    Apply a parsed command to all routines.
    
    Args:
        routines: list of dicts from scan_routines.py (each with short_name, rid_decimal, etc.)
        command: parsed command dict from requirement_parser.parse_requirement()
    
    Returns:
        changes: list of change dicts with keys:
            routine, new_rid_decimal, new_rid_hex, old_rid_decimal, old_rid_hex, changed
        errors: list of error strings
    """
    explicit_products = command.get("explicit_products", [])
    modify_products = command.get("modify_products", explicit_products)
    
    # Determine which routines are in scope for modification
    def _is_in_scope(routine):
        if not modify_products:
            return True
        return routine.get("product_type", "") in modify_products
    
    changes = []
    errors = []
    
    # For sequential assign, pre-compute with deduplication
    if command["command_type"] == "sequential_assign":
        sorted_routines = _build_sorted_routines(routines, modify_products)
        start = command["parameters"]["start"]
        end = command["parameters"]["end"]
        rid_map, err = _assign_sequential_with_dedup(sorted_routines, start, end)
        if err:
            errors.append(err)
            return changes, errors
        
        for routine in routines:
            if not _is_in_scope(routine):
                old_rid = routine["rid_decimal"]
                changes.append({
                    "routine": routine,
                    "old_rid_decimal": old_rid,
                    "old_rid_hex": f"0x{old_rid:04X}",
                    "new_rid_decimal": old_rid,
                    "new_rid_hex": f"0x{old_rid:04X}",
                    "changed": False
                })
                continue
            
            key = (routine.get("product_type"), routine["short_name"], routine["arxml_path"])
            new_rid = rid_map.get(key)
            if new_rid is None:
                # Fallback: find by (product, name)
                for k, v in rid_map.items():
                    if k[0] == routine.get("product_type") and k[1] == routine["short_name"]:
                        new_rid = v
                        break
            
            old_rid = routine["rid_decimal"]
            changed = (new_rid is not None and new_rid != old_rid)
            if new_rid is None:
                new_rid = old_rid
            
            changes.append({
                "routine": routine,
                "old_rid_decimal": old_rid,
                "old_rid_hex": f"0x{old_rid:04X}",
                "new_rid_decimal": new_rid,
                "new_rid_hex": f"0x{new_rid:04X}",
                "changed": changed
            })
    else:
        # For other command types, use existing logic with sorted list
        sorted_routines = _build_sorted_routines(routines, modify_products)
        
        for routine in routines:
            if not _is_in_scope(routine):
                old_rid = routine["rid_decimal"]
                changes.append({
                    "routine": routine,
                    "old_rid_decimal": old_rid,
                    "old_rid_hex": f"0x{old_rid:04X}",
                    "new_rid_decimal": old_rid,
                    "new_rid_hex": f"0x{old_rid:04X}",
                    "changed": False
                })
                continue
            
            new_rid, err = compute_new_rid(routine, command, all_routines_sorted=sorted_routines)
            if err:
                errors.append(err)
                continue
            
            old_rid = routine["rid_decimal"]
            changed = (new_rid != old_rid)
            
            changes.append({
                "routine": routine,
                "old_rid_decimal": old_rid,
                "old_rid_hex": f"0x{old_rid:04X}",
                "new_rid_decimal": new_rid,
                "new_rid_hex": f"0x{new_rid:04X}",
                "changed": changed
            })
    
    return changes, errors


def check_conflicts(changes):
    """
    Check for conflicts in calculated changes.
    
    Conflict rules:
    1. Two DIFFERENT routines get the SAME new RID -> conflict
    
    Returns:
        conflicts: list of conflict description strings
    """
    conflicts = []
    
    # Only consider actually changed items
    changed_items = [c for c in changes if c["changed"]]
    
    # Check 1: Same new RID assigned to different routine names
    rid_to_routines = {}
    for c in changed_items:
        rid = c["new_rid_decimal"]
        name = c["routine"]["short_name"]
        if rid not in rid_to_routines:
            rid_to_routines[rid] = set()
        rid_to_routines[rid].add(name)
    
    for rid, routine_names in rid_to_routines.items():
        if len(routine_names) > 1:
            conflicts.append(
                f"CONFLICT: RID {rid} (0x{rid:04X}) assigned to multiple different routines: {', '.join(sorted(routine_names))}"
            )
    
    return conflicts


def summarize_changes(changes):
    """
    Generate a human-readable summary of changes.
    
    Returns dict with statistics.
    """
    total = len(changes)
    changed = [c for c in changes if c["changed"]]
    unchanged = [c for c in changes if not c["changed"]]
    
    files_affected = set()
    for c in changed:
        files_affected.add(c["routine"].get("arxml_path", "unknown"))
    
    return {
        "total_routines": total,
        "changed_count": len(changed),
        "unchanged_count": len(unchanged),
        "files_affected": len(files_affected),
        "file_list": sorted(files_affected)
    }


if __name__ == "__main__":
    # Self-test with Common deduplication
    dummy_routines = [
        {"short_name": "Common_A", "rid_decimal": 0x1000, "rid_hex": "0x1000", "product_type": "Common", "arxml_path": "file1.arxml"},
        {"short_name": "Common_A", "rid_decimal": 0x1001, "rid_hex": "0x1001", "product_type": "Common", "arxml_path": "file2.arxml"},
        {"short_name": "Common_B", "rid_decimal": 0x1002, "rid_hex": "0x1002", "product_type": "Common", "arxml_path": "file1.arxml"},
        {"short_name": "IPB_A", "rid_decimal": 0xF100, "rid_hex": "0xF100", "product_type": "IPB", "arxml_path": "ipb1.arxml"},
        {"short_name": "IPB_A", "rid_decimal": 0xF101, "rid_hex": "0xF101", "product_type": "IPB", "arxml_path": "ipb2.arxml"},
        {"short_name": "IPB_B", "rid_decimal": 0xF102, "rid_hex": "0xF102", "product_type": "IPB", "arxml_path": "ipb1.arxml"},
    ]
    
    from requirement_parser import parse_requirement
    cmd = parse_requirement("assign all RIDs sequentially to 0x3000-0x30FF", available_products=["Common", "IPB"])
    changes, errors = apply_command_to_routines(dummy_routines, cmd)
    print("Changes:")
    for c in changes:
        print(f"  {c['routine']['short_name']} ({c['routine']['product_type']}): {c['old_rid_hex']} -> {c['new_rid_hex']} {'(changed)' if c['changed'] else '(no change)'}")
    
    conflicts = check_conflicts(changes)
    if conflicts:
        print("Conflicts:")
        for cf in conflicts:
            print(f"  {cf}")
    else:
        print("No conflicts.")
    
    summary = summarize_changes(changes)
    print(f"Summary: {summary}")
