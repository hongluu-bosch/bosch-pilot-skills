"""
31service-toolkit - ARXML routine inserter.

Generates complete DcmDspRoutine XML fragments and inserts them into target ARXML files.
Uses pure text replacement to preserve XML formatting.

Indentation rules (matches project ARXML style, +2 spaces per level):
  DcmDspRoutine container:                    32 spaces
    SHORT-NAME, DEFINITION-REF, PARAMS:       34 spaces
    SUB-CONTAINERS:                           34 spaces
      DcmDspStartRoutine container:           36 spaces
        SHORT-NAME, DEFINITION-REF, PARAMS:   38 spaces
        REFERENCE-VALUES:                     38 spaces
        SUB-CONTAINERS:                       38 spaces
          DcmDspStartRoutineIn/Out:           40 spaces
            SHORT-NAME, DEFINITION-REF:       42 spaces
            SUB-CONTAINERS:                   42 spaces
              Signal container:               44 spaces
                PARAM values:                 48 spaces
"""

import os
import re


def _sp(n):
    """Return n spaces for indentation."""
    return " " * n


# Base indentation levels
R_ROUTINE = 32          # DcmDspRoutine ECUC-CONTAINER-VALUE
R_CHILD = 34            # Routine direct children
R_SUB = 34              # Routine SUB-CONTAINERS

SR_ROUTINE = 36         # DcmDspStartRoutine container
SR_CHILD = 38           # StartRoutine direct children
SR_SUB = 38             # StartRoutine SUB-CONTAINERS

SIO_ROUTINE = 40        # StartRoutineIn/Out container
SIO_CHILD = 42          # StartRoutineIn/Out direct children
SIO_SUB = 42            # StartRoutineIn/Out SUB-CONTAINERS

SIG_ROUTINE = 44        # Signal container
SIG_CHILD = 46          # Signal direct children
SIG_PARAM = 48          # Signal parameter values
SIG_VALUE = 50          # Signal innermost VALUE

ST_ROUTINE = 36         # DcmDspStopRoutine container
ST_CHILD = 38           # StopRoutine direct children
ST_SUB = 38             # StopRoutine SUB-CONTAINERS

STO_ROUTINE = 40        # DcmDspStopRoutineOut container
STO_CHILD = 42          # StopRoutineOut direct children
STO_SUB = 42            # StopRoutineOut SUB-CONTAINERS

RR_ROUTINE = 36         # DcmDspRequestRoutineResults container
RR_CHILD = 38           # RequestRoutineResults direct children
RR_SUB = 38             # RequestRoutineResults SUB-CONTAINERS

RRO_ROUTINE = 40        # DcmDspRequestRoutineResultsOut container
RRO_CHILD = 42          # RequestRoutineResultsOut direct children
RRO_SUB = 42            # RequestRoutineResultsOut SUB-CONTAINERS


def _build_signal_container_xml(signal_specs, container_short_name, definition_ref_path,
                                 signal_def_ref_path, signal_name_prefix, base_indent):
    """
    Build XML for a signal container (e.g., DcmDspStartRoutineIn).

    Args:
        signal_specs: list of dicts with type, length, pos
        container_short_name: e.g. "DcmDspStartRoutineIn"
        definition_ref_path: full DEFINITION-REF path for the container
        signal_def_ref_path: full DEFINITION-REF path for the signal type
        signal_name_prefix: e.g. "DcmDspStartRoutineInSignal"
        base_indent: indentation level for the container's parent (e.g., SR_SUB)

    Returns:
        XML string fragment or "" if signal_specs is empty.
    """
    if not signal_specs:
        return ""

    con = base_indent + 2          # container level
    child = base_indent + 4        # container children
    sig = base_indent + 6          # signal container
    sig_child = base_indent + 8    # signal children
    sig_param = base_indent + 10   # signal parameters
    sig_value = base_indent + 12   # signal innermost values

    lines = [
        f'{_sp(con)}<ECUC-CONTAINER-VALUE>',
        f'{_sp(child)}<SHORT-NAME>{container_short_name}</SHORT-NAME>',
        f'{_sp(child)}<DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">{definition_ref_path}</DEFINITION-REF>',
        f'{_sp(child)}<SUB-CONTAINERS>',
    ]

    for idx, sig_spec in enumerate(signal_specs):
        sig_name = f"{signal_name_prefix}_{idx}"
        type_value = sig_spec["type"]

        lines.extend([
            f'{_sp(sig)}<ECUC-CONTAINER-VALUE>',
            f'{_sp(sig_child)}<SHORT-NAME>{sig_name}</SHORT-NAME>',
            f'{_sp(sig_child)}<DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">{signal_def_ref_path}</DEFINITION-REF>',
            f'{_sp(sig_child)}<PARAMETER-VALUES>',
            f'{_sp(sig_param)}<ECUC-TEXTUAL-PARAM-VALUE>',
            f'{_sp(sig_value)}<DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">{signal_def_ref_path}/DcmDspRoutineSignalEndianness</DEFINITION-REF>',
            f'{_sp(sig_value)}<VALUE>BIG_ENDIAN</VALUE>',
            f'{_sp(sig_param)}</ECUC-TEXTUAL-PARAM-VALUE>',
            f'{_sp(sig_param)}<ECUC-NUMERICAL-PARAM-VALUE>',
            f'{_sp(sig_value)}<DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">{signal_def_ref_path}/DcmDspRoutineSignalLength</DEFINITION-REF>',
            f'{_sp(sig_value)}<VALUE>{sig_spec["length"]}</VALUE>',
            f'{_sp(sig_param)}</ECUC-NUMERICAL-PARAM-VALUE>',
            f'{_sp(sig_param)}<ECUC-NUMERICAL-PARAM-VALUE>',
            f'{_sp(sig_value)}<DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">{signal_def_ref_path}/DcmDspRoutineSignalPos</DEFINITION-REF>',
            f'{_sp(sig_value)}<VALUE>{sig_spec["pos"]}</VALUE>',
            f'{_sp(sig_param)}</ECUC-NUMERICAL-PARAM-VALUE>',
            f'{_sp(sig_param)}<ECUC-TEXTUAL-PARAM-VALUE>',
            f'{_sp(sig_value)}<DEFINITION-REF DEST="ECUC-ENUMERATION-PARAM-DEF">{signal_def_ref_path}/DcmDspRoutineSignalType</DEFINITION-REF>',
            f'{_sp(sig_value)}<VALUE>{type_value}</VALUE>',
            f'{_sp(sig_param)}</ECUC-TEXTUAL-PARAM-VALUE>',
            f'{_sp(sig_child)}</PARAMETER-VALUES>',
            f'{_sp(sig)}</ECUC-CONTAINER-VALUE>',
        ])

    lines.extend([
        f'{_sp(child)}</SUB-CONTAINERS>',
        f'{_sp(con)}</ECUC-CONTAINER-VALUE>',
    ])

    return "\n".join(lines)


def build_routine_xml(routine_name, rid_decimal, signals_start_in=None,
                      signals_start_out=None, signals_stop_out=None,
                      signals_result_out=None):
    """
    Build a complete DcmDspRoutine ECUC-CONTAINER-VALUE XML fragment.

    Args:
        routine_name: The SHORT-NAME for the routine (RBAPLCUST_ prefix is
                      added automatically if not present).
        rid_decimal: Routine identifier as decimal integer.
        signals_start_in: list of signal specs or None (no StartRoutineIn).
        signals_start_out: list of signal specs or None (defaults to UINT8_N(8bit)).
        signals_stop_out: list of signal specs or None (no StopRoutine container).
        signals_result_out: list of signal specs or None (no RequestRoutineResults).

    Returns:
        Complete XML string for the routine container.
    """
    # Handle routine_name prefix
    if routine_name.startswith("RBAPLCUST_"):
        base_name = routine_name[len("RBAPLCUST_"):]
        short_name = routine_name
    else:
        base_name = routine_name
        short_name = f"RBAPLCUST_{routine_name}"

    # Apply defaults: start_out omitted → UINT8_N(8bit)
    if signals_start_out is None:
        signals_start_out = [{"type": "UINT8_N", "length": 8, "pos": 0}]

    lines = [
        f'{_sp(R_ROUTINE)}<ECUC-CONTAINER-VALUE>',
        f'{_sp(R_CHILD)}<SHORT-NAME>{short_name}</SHORT-NAME>',
        f'{_sp(R_CHILD)}<DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine</DEFINITION-REF>',
        f'{_sp(R_CHILD)}<PARAMETER-VALUES>',
        f'{_sp(R_CHILD + 2)}<ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 4)}<DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmRbDspReqSequenceErrorEnabled</DEFINITION-REF>',
        f'{_sp(R_CHILD + 4)}<VALUE>false</VALUE>',
        f'{_sp(R_CHILD + 2)}</ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 2)}<ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 4)}<DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmRbDspRoutineUseAsynchronousServerCallPoint</DEFINITION-REF>',
        f'{_sp(R_CHILD + 4)}<VALUE>false</VALUE>',
        f'{_sp(R_CHILD + 2)}</ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 2)}<ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 4)}<DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmRbDspStopRoutineOnSessionChange</DEFINITION-REF>',
        f'{_sp(R_CHILD + 4)}<VALUE>true</VALUE>',
        f'{_sp(R_CHILD + 2)}</ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 2)}<ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 4)}<DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineIdentifier</DEFINITION-REF>',
        f'{_sp(R_CHILD + 4)}<VALUE>{rid_decimal}</VALUE>',
        f'{_sp(R_CHILD + 2)}</ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 2)}<ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 4)}<DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineUsePort</DEFINITION-REF>',
        f'{_sp(R_CHILD + 4)}<VALUE>false</VALUE>',
        f'{_sp(R_CHILD + 2)}</ECUC-NUMERICAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 2)}<ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(R_CHILD + 4)}<DEFINITION-REF DEST="ECUC-FUNCTION-NAME-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmRbDspIsRIDAvailableFnc</DEFINITION-REF>',
        f'{_sp(R_CHILD + 4)}<VALUE>RBAPLCUST_IsAvailable</VALUE>',
        f'{_sp(R_CHILD + 2)}</ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(R_CHILD)}</PARAMETER-VALUES>',
        f'{_sp(R_CHILD)}<SUB-CONTAINERS>',
    ]

    # --- DcmDspStartRoutine (always present) ---
    start_lines = [
        f'{_sp(SR_ROUTINE)}<ECUC-CONTAINER-VALUE>',
        f'{_sp(SR_CHILD)}<SHORT-NAME>DcmDspStartRoutine</SHORT-NAME>',
        f'{_sp(SR_CHILD)}<DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStartRoutine</DEFINITION-REF>',
        f'{_sp(SR_CHILD)}<PARAMETER-VALUES>',
        f'{_sp(SR_CHILD + 2)}<ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(SR_CHILD + 4)}<DEFINITION-REF DEST="ECUC-FUNCTION-NAME-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStartRoutine/DcmDspStartRoutineFnc</DEFINITION-REF>',
        f'{_sp(SR_CHILD + 4)}<VALUE>RBAPLCUST_{base_name}_start</VALUE>',
        f'{_sp(SR_CHILD + 2)}</ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(SR_CHILD)}</PARAMETER-VALUES>',
        f'{_sp(SR_CHILD)}<REFERENCE-VALUES>',
        f'{_sp(SR_CHILD + 2)}<ECUC-REFERENCE-VALUE>',
        f'{_sp(SR_CHILD + 4)}<DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStartRoutine/DcmDspStartRoutineCommonAuthorizationRef</DEFINITION-REF>',
        f'{_sp(SR_CHILD + 4)}<VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspCommonAuthorization_ExtEol</VALUE-REF>',
        f'{_sp(SR_CHILD + 2)}</ECUC-REFERENCE-VALUE>',
        f'{_sp(SR_CHILD)}</REFERENCE-VALUES>',
        f'{_sp(SR_CHILD)}<SUB-CONTAINERS>',
    ]

    # StartRoutineIn signals (optional)
    if signals_start_in:
        in_xml = _build_signal_container_xml(
            signals_start_in,
            "DcmDspStartRoutineIn",
            "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStartRoutine/DcmDspStartRoutineIn",
            "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStartRoutine/DcmDspStartRoutineIn/DcmDspStartRoutineInSignal",
            "DcmDspStartRoutineInSignal",
            SR_SUB
        )
        start_lines.append(in_xml)

    # StartRoutineOut signals (always present, default applied above)
    out_xml = _build_signal_container_xml(
        signals_start_out,
        "DcmDspStartRoutineOut",
        "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStartRoutine/DcmDspStartRoutineOut",
        "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStartRoutine/DcmDspStartRoutineOut/DcmDspStartRoutineOutSignal",
        "DcmDspStartRoutineOutSignal",
        SR_SUB
    )
    start_lines.append(out_xml)

    start_lines.extend([
        f'{_sp(SR_CHILD)}</SUB-CONTAINERS>',
        f'{_sp(SR_ROUTINE)}</ECUC-CONTAINER-VALUE>',
    ])
    lines.append("\n".join(start_lines))

    # --- DcmDspStopRoutine (only if signals_stop_out is not None) ---
    if signals_stop_out is not None:
        stop_xml = _build_stop_routine_xml(base_name, signals_stop_out)
        lines.append(stop_xml)

    # --- DcmDspRequestRoutineResults (only if signals_result_out is not None) ---
    if signals_result_out is not None:
        result_xml = _build_request_results_xml(base_name, signals_result_out)
        lines.append(result_xml)

    lines.extend([
        f'{_sp(R_CHILD)}</SUB-CONTAINERS>',
        f'{_sp(R_ROUTINE)}</ECUC-CONTAINER-VALUE>',
    ])

    return "\n".join(lines)


def _build_stop_routine_xml(base_name, signals_stop_out):
    """Build DcmDspStopRoutine container XML."""
    lines = [
        f'{_sp(ST_ROUTINE)}<ECUC-CONTAINER-VALUE>',
        f'{_sp(ST_CHILD)}<SHORT-NAME>DcmDspStopRoutine</SHORT-NAME>',
        f'{_sp(ST_CHILD)}<DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStopRoutine</DEFINITION-REF>',
        f'{_sp(ST_CHILD)}<PARAMETER-VALUES>',
        f'{_sp(ST_CHILD + 2)}<ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(ST_CHILD + 4)}<DEFINITION-REF DEST="ECUC-FUNCTION-NAME-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStopRoutine/DcmDspStopRoutineFnc</DEFINITION-REF>',
        f'{_sp(ST_CHILD + 4)}<VALUE>RBAPLCUST_{base_name}_stop</VALUE>',
        f'{_sp(ST_CHILD + 2)}</ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(ST_CHILD)}</PARAMETER-VALUES>',
        f'{_sp(ST_CHILD)}<REFERENCE-VALUES>',
        f'{_sp(ST_CHILD + 2)}<ECUC-REFERENCE-VALUE>',
        f'{_sp(ST_CHILD + 4)}<DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStopRoutine/DcmDspStopRoutineCommonAuthorizationRef</DEFINITION-REF>',
        f'{_sp(ST_CHILD + 4)}<VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspCommonAuthorization_ExtEol</VALUE-REF>',
        f'{_sp(ST_CHILD + 2)}</ECUC-REFERENCE-VALUE>',
        f'{_sp(ST_CHILD)}</REFERENCE-VALUES>',
        f'{_sp(ST_CHILD)}<SUB-CONTAINERS>',
    ]

    if signals_stop_out:
        out_xml = _build_signal_container_xml(
            signals_stop_out,
            "DcmDspStopRoutineOut",
            "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStopRoutine/DcmDspStopRoutineOut",
            "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspStopRoutine/DcmDspStopRoutineOut/DcmDspStopRoutineOutSignal",
            "DcmDspStopRoutineOutSignal",
            ST_SUB
        )
        lines.append(out_xml)

    lines.extend([
        f'{_sp(ST_CHILD)}</SUB-CONTAINERS>',
        f'{_sp(ST_ROUTINE)}</ECUC-CONTAINER-VALUE>',
    ])
    return "\n".join(lines)


def _build_request_results_xml(base_name, signals_result_out):
    """Build DcmDspRequestRoutineResults container XML."""
    lines = [
        f'{_sp(RR_ROUTINE)}<ECUC-CONTAINER-VALUE>',
        f'{_sp(RR_CHILD)}<SHORT-NAME>DcmDspRequestRoutineResults</SHORT-NAME>',
        f'{_sp(RR_CHILD)}<DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRequestRoutineResults</DEFINITION-REF>',
        f'{_sp(RR_CHILD)}<PARAMETER-VALUES>',
        f'{_sp(RR_CHILD + 2)}<ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(RR_CHILD + 4)}<DEFINITION-REF DEST="ECUC-FUNCTION-NAME-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRequestRoutineResults/DcmDspRequestRoutineResultsFnc</DEFINITION-REF>',
        f'{_sp(RR_CHILD + 4)}<VALUE>RBAPLCUST_{base_name}_RequestResult</VALUE>',
        f'{_sp(RR_CHILD + 2)}</ECUC-TEXTUAL-PARAM-VALUE>',
        f'{_sp(RR_CHILD)}</PARAMETER-VALUES>',
        f'{_sp(RR_CHILD)}<REFERENCE-VALUES>',
        f'{_sp(RR_CHILD + 2)}<ECUC-REFERENCE-VALUE>',
        f'{_sp(RR_CHILD + 4)}<DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRequestRoutineResults/DcmDspRequestRoutineResultsCommonAuthorizationRef</DEFINITION-REF>',
        f'{_sp(RR_CHILD + 4)}<VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspCommonAuthorization_ExtEol</VALUE-REF>',
        f'{_sp(RR_CHILD + 2)}</ECUC-REFERENCE-VALUE>',
        f'{_sp(RR_CHILD)}</REFERENCE-VALUES>',
        f'{_sp(RR_CHILD)}<SUB-CONTAINERS>',
    ]

    if signals_result_out:
        out_xml = _build_signal_container_xml(
            signals_result_out,
            "DcmDspRequestRoutineResultsOut",
            "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRequestRoutineResults/DcmDspRequestRoutineResultsOut",
            "/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRequestRoutineResults/DcmDspRequestRoutineResultsOut/DcmDspRequestRoutineResultsOutSignal",
            "DcmDspRequestRoutineResultsOutSignal",
            RR_SUB
        )
        lines.append(out_xml)

    lines.extend([
        f'{_sp(RR_CHILD)}</SUB-CONTAINERS>',
        f'{_sp(RR_ROUTINE)}</ECUC-CONTAINER-VALUE>',
    ])
    return "\n".join(lines)


def insert_routine_into_file(arxml_path, routine_xml, dry_run=False):
    """
    Insert a routine XML fragment into the target ARXML file.

    The routine is inserted as the last ECUC-CONTAINER-VALUE within
    the DcmDsp SUB-CONTAINERS block.

    Args:
        arxml_path: absolute path to the ARXML file
        routine_xml: complete routine XML fragment string
        dry_run: if True, don't write changes

    Returns:
        (success: bool, error_message: str or None)
    """
    try:
        with open(arxml_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return False, f"Failed to read {arxml_path}: {e}"

    # Strategy: Find the DcmDsp container's SUB-CONTAINERS closing tag
    # We look for the pattern where DcmDsp's SUB-CONTAINERS ends
    # The last </ECUC-CONTAINER-VALUE> before </SUB-CONTAINERS> of DcmDsp

    # Find DcmDsp container first
    # Pattern: <SHORT-NAME>DcmDsp</SHORT-NAME> ... <SUB-CONTAINERS> ... </SUB-CONTAINERS>
    dcm_dsp_pattern = re.compile(
        r'(<SHORT-NAME>DcmDsp</SHORT-NAME>.*?<SUB-CONTAINERS>)(.*?)(</SUB-CONTAINERS>\s*?</ECUC-CONTAINER-VALUE>)',
        re.DOTALL
    )

    match = dcm_dsp_pattern.search(content)
    if not match:
        return False, "Could not find DcmDsp container's SUB-CONTAINERS block in the file"

    # Find the last </ECUC-CONTAINER-VALUE> before the closing </SUB-CONTAINERS>
    sub_containers_content = match.group(2)
    sub_start = match.start(2)

    # Find the last </ECUC-CONTAINER-VALUE> in the sub-containers
    last_container_end = sub_containers_content.rfind("</ECUC-CONTAINER-VALUE>")
    if last_container_end == -1:
        return False, "No existing ECUC-CONTAINER-VALUE found in DcmDsp SUB-CONTAINERS"

    # Calculate absolute position
    insert_pos = sub_start + last_container_end + len("</ECUC-CONTAINER-VALUE>")

    # Build the insertion: newline + routine_xml
    insert_text = "\n" + routine_xml

    new_content = content[:insert_pos] + insert_text + content[insert_pos:]

    if dry_run:
        return True, None

    try:
        with open(arxml_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return False, f"Failed to write {arxml_path}: {e}"

    return True, None


def validate_insertion(arxml_path, routine_name, rid_decimal):
    """
    Validate that the insertion was successful by re-parsing the file.

    Returns:
        (is_valid: bool, error_message: str or None)
    """
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(arxml_path)
        root = tree.getroot()
    except Exception as e:
        return False, f"Re-parse failed: {e}"

    ns = {"ns": "http://autosar.org/schema/r4.0"}

    # Find all routine containers
    routines = root.findall(".//ns:ECUC-CONTAINER-VALUE", ns)
    found_name = False
    found_rid = False

    for routine in routines:
        short_name_elem = routine.find("ns:SHORT-NAME", ns)
        if short_name_elem is not None and short_name_elem.text == routine_name:
            found_name = True
            # Check RID
            param_values = routine.findall("ns:PARAMETER-VALUES/ns:ECUC-NUMERICAL-PARAM-VALUE", ns)
            for pv in param_values:
                def_ref = pv.find("ns:DEFINITION-REF", ns)
                if def_ref is not None and "DcmDspRoutineIdentifier" in def_ref.text:
                    value_elem = pv.find("ns:VALUE", ns)
                    if value_elem is not None and value_elem.text == str(rid_decimal):
                        found_rid = True
                        break

    if not found_name:
        return False, f"Routine '{routine_name}' not found after insertion"
    if not found_rid:
        return False, f"Routine '{routine_name}' found but RID {rid_decimal} mismatch"

    # Check for duplicate RIDs across ALL containers in the file
    all_rids = {}
    for routine in routines:
        short_name_elem = routine.find("ns:SHORT-NAME", ns)
        if short_name_elem is None:
            continue
        name = short_name_elem.text

        param_values = routine.findall("ns:PARAMETER-VALUES/ns:ECUC-NUMERICAL-PARAM-VALUE", ns)
        for pv in param_values:
            def_ref = pv.find("ns:DEFINITION-REF", ns)
            if def_ref is not None and "DcmDspRoutineIdentifier" in def_ref.text:
                value_elem = pv.find("ns:VALUE", ns)
                if value_elem is not None:
                    try:
                        rid = int(value_elem.text)
                        if rid in all_rids and all_rids[rid] != name:
                            return False, f"Duplicate RID {rid} detected: '{all_rids[rid]}' and '{name}'"
                        all_rids[rid] = name
                    except ValueError:
                        pass
                break

    return True, None


if __name__ == "__main__":
    # Self-test: generate a sample routine
    test_routine = build_routine_xml(
        "TestRoutine",
        0xF200,
        signals_start_in=[{"type": "UINT8", "length": 8, "pos": 0}, {"type": "UINT16", "length": 16, "pos": 8}],
        signals_start_out=None,  # default
        signals_stop_out=None,   # no stop
        signals_result_out=None  # no result
    )
    print("Generated routine XML:")
    print(test_routine)
    print("\n" + "=" * 60)
    print("Validation: checking indentation consistency...")
    for i, line in enumerate(test_routine.split("\n"), 1):
        stripped = line.lstrip()
        if stripped.startswith("<ECUC-CONTAINER-VALUE>") and "SHORT-NAME" not in line:
            indent = len(line) - len(line.lstrip())
            print(f"  Line {i}: container at {indent} spaces")
