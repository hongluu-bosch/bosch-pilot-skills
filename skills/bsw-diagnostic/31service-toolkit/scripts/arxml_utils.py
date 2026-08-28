"""
31service-toolkit - ARXML parsing utilities
Handles AUTOSAR XML namespace and routine extraction.
"""

import xml.etree.ElementTree as ET
import os

# AUTOSAR schema namespace used in arxml files
AUTOSAR_NS = "http://autosar.org/schema/r4.0"
NSMAP = {"ns": AUTOSAR_NS}


def parse_arxml(filepath):
    """Parse an arxml file and return the root element. Preserves namespace formatting."""
    # Register namespace to prevent ElementTree from adding ns0: prefix on write
    ET.register_namespace("", AUTOSAR_NS)
    tree = ET.parse(filepath)
    return tree, tree.getroot()


def findall_with_ns(element, xpath):
    """Execute xpath with AUTOSAR namespace prefix."""
    return element.findall(xpath, NSMAP)


def get_text(child, tag_name):
    """Get text content of a child tag with namespace."""
    tag = f"{{{AUTOSAR_NS}}}{tag_name}"
    child_elem = child.find(tag)
    return child_elem.text if child_elem is not None else None


def get_routine_containers(root):
    """
    Find all ECUC-CONTAINER-VALUE nodes that represent DcmDspRoutine.
    Returns a list of (container_element, definition_ref) tuples.
    """
    routines = []
    # Find all ECUC-CONTAINER-VALUE elements
    all_containers = findall_with_ns(root, ".//ns:ECUC-CONTAINER-VALUE")
    for container in all_containers:
        def_ref_elem = container.find(f"{{{AUTOSAR_NS}}}DEFINITION-REF")
        if def_ref_elem is not None and def_ref_elem.text:
            def_ref = def_ref_elem.text
            if "DcmDspRoutine" in def_ref and "DcmDspStartRoutine" not in def_ref and "DcmDspStopRoutine" not in def_ref:
                routines.append((container, def_ref))
    return routines


def extract_routine_info(container):
    """
    Extract routine information from a DcmDspRoutine container.
    Returns dict with: short_name, rid_decimal, rid_hex, or None if invalid.
    """
    short_name = get_text(container, "SHORT-NAME")
    if not short_name:
        return None

    rid_decimal = None
    # Find DcmDspRoutineIdentifier parameter value
    param_values = findall_with_ns(container, "ns:PARAMETER-VALUES/ns:ECUC-NUMERICAL-PARAM-VALUE")
    for pv in param_values:
        def_ref = pv.find(f"{{{AUTOSAR_NS}}}DEFINITION-REF")
        if def_ref is not None and def_ref.text and "DcmDspRoutineIdentifier" in def_ref.text:
            value_elem = pv.find(f"{{{AUTOSAR_NS}}}VALUE")
            if value_elem is not None and value_elem.text:
                try:
                    rid_decimal = int(value_elem.text)
                except ValueError:
                    rid_decimal = None
            break

    if rid_decimal is None:
        return None

    return {
        "short_name": short_name,
        "rid_decimal": rid_decimal,
        "rid_hex": f"0x{rid_decimal:04X}"
    }


def find_services_arxml_files(root_dir):
    """
    Recursively find Dcm_CusDiag_Services*.arxml files under dcom/RBAPLCust/cfg.
    Searches anywhere under root_dir (handles variant subdirectories like <variant>/).
    Skips hidden directories (starting with '.') like SCM metadata.
    Returns list of (relative_path, absolute_path, product_type) tuples.
    """
    results = []
    search_pattern = os.path.join(root_dir, "**", "dcom", "RBAPLCust", "cfg")
    
    import glob
    for cfg_dir in glob.glob(search_pattern, recursive=True):
        if not os.path.isdir(cfg_dir):
            continue
        # Skip if any parent directory is hidden (starts with '.')
        if any(part.startswith('.') for part in cfg_dir.split(os.sep)):
            continue
        for dirpath, _, filenames in os.walk(cfg_dir):
            for fname in filenames:
                if fname.startswith("Dcm_CusDiag_Services") and fname.endswith(".arxml"):
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path, root_dir)
                    # Skip if inside hidden dir
                    if any(part.startswith('.') for part in rel_path.split(os.sep)):
                        continue
                    # Infer product type from directory name
                    product_type = _infer_product_type(dirpath)
                    results.append((rel_path, abs_path, product_type))
    
    return sorted(results, key=lambda x: (x[2], x[0]))


def _infer_product_type(dirpath):
    """Infer product type from the path segments under cfg/."""
    parts = dirpath.split(os.sep)
    try:
        cfg_idx = parts.index("cfg")
        if cfg_idx + 1 < len(parts):
            return parts[cfg_idx + 1]
    except ValueError:
        pass
    return "Unknown"


def update_routine_rid(container, new_rid_decimal):
    """
    [DEPRECATED] Update the DcmDspRoutineIdentifier VALUE in a routine container.
    This function uses ElementTree mutation which may alter XML formatting.
    Use update_arxml.apply_updates() with pure text replacement instead.
    Returns True if updated, False if not found.
    """
    param_values = findall_with_ns(container, "ns:PARAMETER-VALUES/ns:ECUC-NUMERICAL-PARAM-VALUE")
    for pv in param_values:
        def_ref = pv.find(f"{{{AUTOSAR_NS}}}DEFINITION-REF")
        if def_ref is not None and def_ref.text and "DcmDspRoutineIdentifier" in def_ref.text:
            value_elem = pv.find(f"{{{AUTOSAR_NS}}}VALUE")
            if value_elem is not None:
                value_elem.text = str(new_rid_decimal)
                return True
    return False
