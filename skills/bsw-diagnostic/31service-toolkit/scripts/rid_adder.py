"""
31service-toolkit - RID adder workflow.

Main controller for adding new DcmDspRoutine entries to ARXML files.
Handles file selection (especially for Common), RID uniqueness checks,
signal parsing, XML generation, insertion, and validation.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from scan_routines import scan_project
from arxml_utils import find_services_arxml_files
from signal_parser import parse_signal_string
from arxml_inserter import build_routine_xml, insert_routine_into_file, validate_insertion
from validate_rid import parse_rid


def _find_target_files(project_root, product_type):
    """
    Find all ARXML files for a given product type.
    Returns list of (rel_path, abs_path) tuples.
    """
    all_files = find_services_arxml_files(project_root)
    matching = [(rel, abs_path) for rel, abs_path, pt in all_files if pt == product_type]
    return matching


def _check_rid_unique_in_file(abs_path, rid_decimal):
    """
    Check if a RID is already used in the given ARXML file.
    Returns (is_unique, existing_routine_name or None).
    """
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(abs_path)
        root = tree.getroot()
    except Exception:
        return False, None  # Can't parse, assume not unique for safety

    ns = {"ns": "http://autosar.org/schema/r4.0"}
    routines = root.findall(".//ns:ECUC-CONTAINER-VALUE", ns)

    for routine in routines:
        param_values = routine.findall("ns:PARAMETER-VALUES/ns:ECUC-NUMERICAL-PARAM-VALUE", ns)
        for pv in param_values:
            def_ref = pv.find("ns:DEFINITION-REF", ns)
            if def_ref is not None and "DcmDspRoutineIdentifier" in def_ref.text:
                value_elem = pv.find("ns:VALUE", ns)
                if value_elem is not None:
                    try:
                        if int(value_elem.text) == rid_decimal:
                            name_elem = routine.find("ns:SHORT-NAME", ns)
                            name = name_elem.text if name_elem is not None else "unknown"
                            return False, name
                    except ValueError:
                        pass
                break

    return True, None


def _check_name_unique_in_file(abs_path, routine_name):
    """
    Check if a routine name already exists in the given ARXML file.
    The routine_name should already include the RBAPLCUST_ prefix if applicable.
    Returns (is_unique, existing_rid or None).
    """
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(abs_path)
        root = tree.getroot()
    except Exception:
        return False, None

    ns = {"ns": "http://autosar.org/schema/r4.0"}
    routines = root.findall(".//ns:ECUC-CONTAINER-VALUE", ns)

    for routine in routines:
        name_elem = routine.find("ns:SHORT-NAME", ns)
        if name_elem is not None and name_elem.text == routine_name:
            # Found existing, get its RID
            param_values = routine.findall("ns:PARAMETER-VALUES/ns:ECUC-NUMERICAL-PARAM-VALUE", ns)
            for pv in param_values:
                def_ref = pv.find("ns:DEFINITION-REF", ns)
                if def_ref is not None and "DcmDspRoutineIdentifier" in def_ref.text:
                    value_elem = pv.find("ns:VALUE", ns)
                    if value_elem is not None:
                        try:
                            return False, int(value_elem.text)
                        except ValueError:
                            return False, None
            return False, None

    return True, None


def _format_common_file_selection_prompt(common_files):
    """Format an interactive prompt for Common file selection."""
    lines = [
        "检测到 Common 配置存在多个 ARXML 文件:",
        "",
    ]
    for i, (rel_path, abs_path) in enumerate(common_files, 1):
        lines.append(f"  {i}. {rel_path}")
    lines.extend([
        "",
        "请指定要插入的目标文件编号（多个用逗号分隔，或输入 'all' 插入到所有文件）:",
    ])
    return "\n".join(lines)


def add_routine(project_root, request, file_hint=None, dry_run=False):
    """
    Add a single routine to the project.

    Args:
        project_root: Project root path
        request: Dict with keys:
            - product: Product type (e.g., 'Common', 'IPB', 'ESP')
            - rid: RID value (decimal or hex string)
            - routine_name: Routine short name (without RBAPLCUST_ prefix)
            - signals_start_in: Signal string or None
            - signals_start_out: Signal string or None
            - signals_stop_out: Signal string or None
            - signals_result_out: Signal string or None
        file_hint: For Common, the selected file path(s). None = auto-detect/ask.
        dry_run: If True, don't modify files

    Returns:
        Dict with status and details:
        - status: 'success', 'need_common_file_selection', 'error'
        - message: Human-readable message
        - target_file: The file that was modified (if success)
        - rid_decimal: The parsed RID decimal value
        - routine_name: The full routine name
    """
    product = request.get("product", "").strip()
    rid_raw = request.get("rid")
    routine_name = request.get("routine_name", "").strip()

    # --- Validate inputs ---
    if not product:
        return {"status": "error", "message": "Product type is required"}
    if not routine_name:
        return {"status": "error", "message": "Routine name is required"}
    if rid_raw is None:
        return {"status": "error", "message": "RID is required"}

    rid_decimal, rid_err = parse_rid(rid_raw)
    if rid_err:
        return {"status": "error", "message": f"Invalid RID: {rid_err}"}

    # --- Find target files ---
    target_files = _find_target_files(project_root, product)
    if not target_files:
        return {"status": "error", "message": f"No ARXML files found for product '{product}'"}

    # --- Common file selection ---
    if product == "Common" and len(target_files) > 1:
        if file_hint is None:
            # Need user to select
            return {
                "status": "need_common_file_selection",
                "message": _format_common_file_selection_prompt(target_files),
                "common_files": target_files,
                "request": request
            }
        else:
            # file_hint is provided - can be index list or 'all'
            if file_hint.lower() == "all":
                selected_files = target_files
            else:
                try:
                    indices = [int(x.strip()) - 1 for x in str(file_hint).split(",")]
                    selected_files = []
                    for idx in indices:
                        if 0 <= idx < len(target_files):
                            selected_files.append(target_files[idx])
                        else:
                            return {"status": "error", "message": f"Invalid file selection index: {idx + 1}"}
                except ValueError:
                    return {"status": "error", "message": f"Invalid file selection format: {file_hint}"}
    else:
        selected_files = target_files

    # --- Parse signals ---
    sig_start_in, err = parse_signal_string(request.get("signals_start_in"))
    if err:
        return {"status": "error", "message": f"Start input signal parse error: {err}"}

    sig_start_out, err = parse_signal_string(request.get("signals_start_out"))
    if err:
        return {"status": "error", "message": f"Start output signal parse error: {err}"}

    sig_stop_out, err = parse_signal_string(request.get("signals_stop_out"))
    if err:
        return {"status": "error", "message": f"Stop output signal parse error: {err}"}

    sig_result_out, err = parse_signal_string(request.get("signals_result_out"))
    if err:
        return {"status": "error", "message": f"Result output signal parse error: {err}"}

    # Note: Default for signals_start_out (UINT8_N(8bit)) is applied inside
    # build_routine_xml(). signals_stop_out / signals_result_out stay None
    # (no container) unless explicitly provided.

    # --- Validate uniqueness in each target file ---
    full_routine_name = routine_name if routine_name.startswith("RBAPLCUST_") else f"RBAPLCUST_{routine_name}"

    for rel_path, abs_path in selected_files:
        rid_unique, existing_name = _check_rid_unique_in_file(abs_path, rid_decimal)
        if not rid_unique:
            return {
                "status": "error",
                "message": f"RID 0x{rid_decimal:04X} ({rid_decimal}) already exists in {rel_path} as '{existing_name}'"
            }

        name_unique, existing_rid = _check_name_unique_in_file(abs_path, full_routine_name)
        if not name_unique:
            return {
                "status": "error",
                "message": f"Routine name '{full_routine_name}' already exists in {rel_path} with RID 0x{existing_rid:04X}"
            }

    # --- Generate and insert XML ---
    routine_xml = build_routine_xml(
        routine_name,
        rid_decimal,
        signals_start_in=sig_start_in,
        signals_start_out=sig_start_out,
        signals_stop_out=sig_stop_out,
        signals_result_out=sig_result_out
    )

    inserted_files = []
    errors = []

    for rel_path, abs_path in selected_files:
        success, err = insert_routine_into_file(abs_path, routine_xml, dry_run=dry_run)
        if not success:
            errors.append(f"{rel_path}: {err}")
            continue

        if not dry_run:
            # Validate insertion
            valid, val_err = validate_insertion(abs_path, full_routine_name, rid_decimal)
            if not valid:
                errors.append(f"{rel_path}: Validation failed - {val_err}")
                continue

        inserted_files.append(rel_path)

    if errors:
        return {
            "status": "partial_success" if inserted_files else "error",
            "message": "; ".join(errors),
            "inserted_files": inserted_files,
            "rid_decimal": rid_decimal,
            "routine_name": full_routine_name
        }

    return {
        "status": "success",
        "message": f"Successfully added routine '{full_routine_name}' (RID 0x{rid_decimal:04X}) to {len(inserted_files)} file(s)",
        "target_files": inserted_files,
        "rid_decimal": rid_decimal,
        "routine_name": full_routine_name
    }


if __name__ == "__main__":
    # Self-test with a mock request
    test_request = {
        "product": "Common",
        "rid": "0xF200",
        "routine_name": "TestRoutine_Add",
        "signals_start_in": "UINT8 + UINT16",
        "signals_start_out": None,
        "signals_stop_out": None,
        "signals_result_out": None
    }
    print("Test request:", test_request)
    print("This module should be called from orchestrator.py with a real project root.")
