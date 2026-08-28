#!/usr/bin/env python3
"""Analyze DEM Event Memory PDM size alignment for one build configuration."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


TARGETS = {
    "evmem": {
        "display_name": "Dem_EvMemEventMemoryType",
        "lst_symbol": "_Dem_EvMemEventMemory",
        "size_mode": "array",
        "assertion_macro": "DEM_NVM_ID_EVMEM_LOC_0_SIZE",
        "nvm_cfg_macro": "NVM_CFG_NV_BLOCK_LENGTH_NVM_ID_EVMEM_LOC_0",
        "pdm_alias_regex": r"use dataitem\s+(NVM_ID_EVMEM_LOC_[^\s]+)\s+as\s+(NVM_ID_EVMEM_LOC_0)",
        "family_extract_regex": r"NVM_ID_EVMEM_LOC_(\d+)_0",
        "reuse_pattern": "NVM_ID_EVMEM_LOC_{size}_0",
        "apply_supported": True,
    },
    "generic": {
        "display_name": "Dem_GenericNvDataType",
        "lst_symbol": "_Dem_GenericNvData",
        "size_mode": "direct",
        "assertion_macro": "DEM_NVM_ID_DEM_GENERIC_NV_DATA_SIZE",
        "nvm_cfg_macro": "NVM_CFG_NV_BLOCK_LENGTH_NVM_ID_DEM_GENERIC_NV_DATA",
        "pdm_alias_regex": r"use dataitem\s+(NVM_ID_DEM_GENERIC_NV_DATA_[^\s]+)\s+as\s+(NVM_ID_DEM_GENERIC_NV_DATA)",
        "family_extract_regex": r"NVM_ID_DEM_GENERIC_NV_DATA_(\d+)",
        "reuse_pattern": "NVM_ID_DEM_GENERIC_NV_DATA_{size}",
        "apply_supported": True,
    },
}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def find_one(base: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        matches = list(base.glob(pattern))
        if matches:
            return matches[0]
    return None


def find_existing_path(base: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        matches = sorted(base.glob(pattern))
        if matches:
            return matches[0]
    return None


def find_existing_paths(base: Path, patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for match in sorted(base.glob(pattern)):
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found


def parse_switch_settings(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        reader = csv.reader(fh, delimiter=";")
        next(reader, None)
        for row in reader:
            if len(row) >= 2 and row[0]:
                values[row[0].strip()] = row[1].strip()
    return values


def extract_define(text: str, name: str) -> str | None:
    match = re.search(rf"^\s*#define\s+{re.escape(name)}\s+(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def parse_lst_size(path: Path, symbol: str) -> int | None:
    text = read_text(path)
    match = re.search(rf"\.size\s+{re.escape(symbol)}\s*,\s*(\d+)", text)
    return int(match.group(1)) if match else None


def align_up(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    return ((value + alignment - 1) // alignment) * alignment


def parse_int_like(value: str | None) -> int:
    if value is None:
        raise ValueError("missing integer-like value")
    cleaned = value.strip().strip("()")
    parts = [p.strip() for p in cleaned.split("+")]
    total = 0
    for part in parts:
        token = part.rstrip("uUlL")
        total += int(token, 0)
    return total


def bool_define(text: str, name: str) -> bool:
    value = extract_define(text, name)
    return value == "TRUE"


def compute_struct_size_fallback(variant_root: Path, project_root: Path) -> int:
    evmem_types = find_existing_path(
        project_root,
        [
            "rba/CUBAS/Diagnosis/Dem/src/evmem/Dem_EvMemTypes.h",
            "**/Dem/src/evmem/Dem_EvMemTypes.h",
        ],
    )
    prj_ext = find_existing_path(
        project_root,
        [
            "rb/as/**/core/app/dsm/**/Dem_PrjEvmemProjectExtension.h",
            "**/Dem_PrjEvmemProjectExtension.h",
        ],
    )
    if evmem_types is None or prj_ext is None:
        raise SystemExit("Fallback calculation inputs are missing")

    cfg_out = variant_root / "src_out" / "bct" / "_out"
    dem_cfg = read_text(cfg_out / "Dem_Cfg.h")
    evmem_cfg = read_text(cfg_out / "Dem_Cfg_EvMem.h")
    env_cfg = read_text(cfg_out / "Dem_Cfg_EnvMain.h")
    env_elem_cfg = read_text(cfg_out / "Dem_Cfg_EnvDataElement.h")
    obd_cfg = read_text(cfg_out / "rba_DemObdBasic_Cfg_Main.h") if (cfg_out / "rba_DemObdBasic_Cfg_Main.h").exists() else ""
    prj_ext_text = read_text(prj_ext)

    env_size = parse_int_like(extract_define(env_cfg, "DEM_CFG_ENVMINSIZE_OF_MULTIPLE_RAWENVDATA"))
    aging_max = parse_int_like(extract_define(evmem_cfg, "DEM_CFG_EVMEM_AGING_COUNTER_MAX"))
    occ_max = parse_int_like(extract_define(evmem_cfg, "DEM_CFG_EVMEM_OCCURRENCE_COUNTER_MAX"))
    aging_size = 1 if aging_max <= 0xFF else 2
    occ_size = 1 if occ_max <= 0xFF else 2
    obd_on = extract_define(dem_cfg, "DEM_CFG_OBD") == "DEM_CFG_OBD_ON"
    obd_uds_on = extract_define(obd_cfg, "DEM_CFG_OBD_ON_UDS_FREEZEFRAME_SUPPORTED") == "DEM_CFG_OBD_ON_UDS_ON"
    wwh_obd = bool_define(dem_cfg, "DEM_CFG_WWH_OBD_SUPPORTED")

    project_extension_size = 0
    if bool_define(evmem_cfg, "DEM_CFG_EVMEM_PROJECT_EXTENSION"):
        uint8_count = len(re.findall(r"^\s*uint8\s+\w+;", prj_ext_text, re.MULTILINE))
        uint16_count = len(re.findall(r"^\s*uint16\s+\w+;", prj_ext_text, re.MULTILINE))
        boolean_count = len(re.findall(r"^\s*boolean\s+\w+;", prj_ext_text, re.MULTILINE))
        offset = 0
        for _ in range(uint8_count):
            offset += 1
        for _ in range(uint16_count):
            offset = align_up(offset, 2)
            offset += 2
        for _ in range(boolean_count):
            offset += 1
        project_extension_size = align_up(offset, 2)

    offset = 0
    max_align = 4
    offset = align_up(offset, 2)
    offset += 4  # Dem_EvMemHdrType
    if bool_define(evmem_cfg, "DEM_CFG_EVMEM_MIRROR_MEMORY_DTC_STATUS_STORED"):
        offset += 1
    if bool_define(env_elem_cfg, "DEM_CFG_READDEM_CYCLES_SINCE_FIRST_FAILED_SUPPORTED"):
        offset += 1
    if bool_define(env_elem_cfg, "DEM_CFG_READDEM_CYCLES_SINCE_LAST_FAILED_SUPPORTED"):
        offset += 1
    if bool_define(env_elem_cfg, "DEM_CFG_READDEM_CYCLES_SINCE_LAST_FAILED_EXCLUDING_TNC_SUPPORTED"):
        offset += 1
    if bool_define(env_elem_cfg, "DEM_CFG_READDEM_FAILED_CYCLES_SUPPORTED"):
        offset += 1
    offset += env_size
    offset += 1  # FailureCounter
    if bool_define(evmem_cfg, "DEM_CFG_EVMEM_FREEZE_FRAME_SUPPORTED"):
        offset += 1
    if bool_define(env_elem_cfg, "DEM_CFG_READDEM_MAX_FDC_DURING_CURRENT_CYCLE_SUPPORTED"):
        offset += 1
    if bool_define(env_elem_cfg, "DEM_CFG_READDEM_MAX_FDC_SINCE_LAST_CLEAR_SUPPORTED"):
        offset += 1
    if obd_on:
        offset += 1  # ObdMilCounter
        offset += 1  # ObdMilResetThisCycle
        offset += 1  # ObdFreezeFrameAvailable
        if wwh_obd:
            offset += 1
        if obd_uds_on:
            offset += 1
    if bool_define(evmem_cfg, "DEM_CFG_EVMEM_AGING_COUNTER_SUPPORTED"):
        offset = align_up(offset, aging_size)
        offset += aging_size
    if bool_define(read_text(cfg_out / "Dem_Cfg_Events.h"), "DEM_CFG_TFSLC_RESET_AFTER_AGING_AND_DISPLACEMENT"):
        offset = align_up(offset, aging_size)
        offset += aging_size
    if bool_define(evmem_cfg, "DEM_CFG_EVMEM_OCCURRENCE_COUNTER_SUPPORTED"):
        offset = align_up(offset, occ_size)
        offset += occ_size
    if bool_define(evmem_cfg, "DEM_CFG_EVMEM_EXTENDED_DATA_SUPPORTED") or bool_define(evmem_cfg, "DEM_CFG_EVMEM_FREEZE_FRAME_SUPPORTED"):
        offset += 1  # Dem_TriggerType
    offset = align_up(offset, 4)
    offset += 4  # TimeId
    if obd_on:
        offset = align_up(offset, 4)
        offset += 4  # ObdFFTimeId
        if obd_uds_on:
            offset = align_up(offset, 4)
            offset += 4
    if project_extension_size:
        offset = align_up(offset, 2)
        offset += project_extension_size
    if bool_define(read_text(cfg_out / "Dem_Cfg_DTCs.h"), "DEM_CFG_REPORT_CHRONOLOGICAL_ORDER_HOOKS_ENABLED"):
        offset = align_up(offset, 4)
        offset += 4
    return align_up(offset, max_align)


def compute_generic_nvdata_size_fallback(variant_root: Path, project_root: Path) -> int:
    generic_nv_path = find_existing_path(
        project_root,
        [
            "rba/CUBAS/Diagnosis/Dem/src/main/Dem_GenericNvData.h",
            "**/Dem_GenericNvData.h",
        ],
    )
    if generic_nv_path is None:
        raise SystemExit("Fallback calculation input Dem_GenericNvData.h is missing")

    cfg_out = variant_root / "src_out" / "bct" / "_out"
    dem_cfg = read_text(cfg_out / "Dem_Cfg.h")
    evmem_cfg = read_text(cfg_out / "Dem_Cfg_EvMem.h")
    generic_text = read_text(generic_nv_path)

    offset = 0
    max_align = 4
    obd_on = extract_define(dem_cfg, "DEM_CFG_OBD") == "DEM_CFG_OBD_ON"
    if obd_on:
        offset = align_up(offset, 4)
        offset += 4  # rba_DemObd_PidDataType

    # Dem_OperationCycleList observed usage in current projects is a 32-bit bitmask.
    offset = align_up(offset, 4)
    offset += 4

    if bool_define(evmem_cfg, "DEM_CFG_EVMEMGENERIC_SUPPORTED"):
        overflow_size = parse_int_like(extract_define(evmem_cfg, "DEM_EVMEMGEN_OVERFLOW_ARRAYSIZE")) if extract_define(evmem_cfg, "DEM_EVMEMGEN_OVERFLOW_ARRAYSIZE") else 10
        dtcids_size = parse_int_like(extract_define(evmem_cfg, "DEM_EVMEMGEN_DTCIDS_BY_OCCURRENCE_TIME_ARRAYSIZE")) if extract_define(evmem_cfg, "DEM_EVMEMGEN_DTCIDS_BY_OCCURRENCE_TIME_ARRAYSIZE") else 9
        offset += overflow_size  # boolean[]
        offset = align_up(offset, 2)
        offset += dtcids_size * 2  # Dem_DtcIdType assumed uint16

    eobd_projectext = extract_define(dem_cfg, "DEM_CFG_EOBD_SUPPORT_PROJECTEXT")
    eobd_projectext_off = extract_define(dem_cfg, "DEM_CFG_EOBD_SUPPORT_PROJECTEXT_OFF")
    if obd_on and eobd_projectext is not None and eobd_projectext_off is not None and eobd_projectext != eobd_projectext_off:
        offset += 2

    return align_up(offset, max_align)


def parse_generic_lst_size(variant_root: Path) -> int | None:
    generic_lst = variant_root / "src_out" / "obj" / "Dem_GenericNvData.lst"
    if not generic_lst.exists():
        return None
    return parse_lst_size(generic_lst, "_Dem_GenericNvData")


def parse_effective_pdm(pdm_includes: Path, cfg_dbfiles: Path) -> str | None:
    include_text = read_text(pdm_includes)
    include_match = re.search(r'#include\s+"([^"]*Dem[^\"]*/Dem_PRJ\.pdm)"', include_text)
    if include_match:
        return include_match.group(1).replace("/", "\\")

    cfg_text = read_text(cfg_dbfiles)
    cfg_match = re.search(r"PDM;([^;]*Dem(?:\\[^;]+)?\\Dem_PRJ\.pdm);", cfg_text)
    return cfg_match.group(1) if cfg_match else None


def parse_current_dataitems(pdm_path: Path, alias_regex: str) -> list[tuple[int, str, str]]:
    items: list[tuple[int, str, str]] = []
    pattern = re.compile(alias_regex)
    for i, line in enumerate(read_text(pdm_path).splitlines(), start=1):
        match = pattern.search(line)
        if match:
            items.append((i, match.group(1), match.group(2)))
    return items


def parse_active_branch_ranges(pdm_path: Path, apbdistributed_value: str) -> list[tuple[int, int]]:
    lines = read_text(pdm_path).splitlines()
    active_ranges: list[tuple[int, int]] = []

    def branch_matches(condition: str) -> bool:
        cond = condition.replace(" ", "")
        if apbdistributed_value.endswith("OneBoxMainSystem"):
            return (
                "RBFS_ApbDistributed_OneBoxMainSystem" in cond
                and "RBFS_ApbDistributed_TwoBoxMainSystem" not in cond
            )
        if apbdistributed_value.endswith("None"):
            return "RBFS_ApbDistributed_None" in cond
        if apbdistributed_value.endswith("TwoBoxMainSystem"):
            return "RBFS_ApbDistributed_TwoBoxMainSystem" in cond
        return False

    current_start: int | None = None
    current_active = False

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#if") or stripped.startswith("#elif"):
            if current_active and current_start is not None:
                active_ranges.append((current_start, idx - 1))
            condition = stripped[stripped.find("f") + 1 :].strip()
            current_start = idx
            current_active = branch_matches(condition)
        elif stripped.startswith("#else"):
            if current_active and current_start is not None:
                active_ranges.append((current_start, idx - 1))
            current_start = idx
            current_active = False
        elif stripped.startswith("#endif"):
            if current_active and current_start is not None:
                active_ranges.append((current_start, idx - 1))
            current_start = None
            current_active = False
    return active_ranges


def replace_active_branch_items(
    pdm_path: Path,
    active_ranges: list[tuple[int, int]],
    current_size: int,
    target_size: int,
) -> list[tuple[int, str, str]]:
    lines = read_text(pdm_path).splitlines(True)
    changes: list[tuple[int, str, str]] = []
    pattern = re.compile(
        rf"(use\s+dataitem\s+NVM_ID_EVMEM_LOC_){current_size}(_\d+\s+as\s+NVM_ID_EVMEM_LOC_\d+)"
    )
    for start, end in active_ranges:
        for line_no in range(start, end + 1):
            original = lines[line_no - 1]
            updated = pattern.sub(rf"\g<1>{target_size}\g<2>", original)
            if updated != original:
                lines[line_no - 1] = updated
                changes.append((line_no, original.rstrip("\r\n"), updated.rstrip("\r\n")))
    if changes:
        pdm_path.write_text("".join(lines), encoding="utf-8", newline="")
    return changes


def verify_generated_macro(variant_root: Path, macro_name: str, target_size: int) -> tuple[bool | None, str | None]:
    assertion_hdr = variant_root / "src_out" / "bct" / "_out" / "Dem_Cfg_AssertionChk.h"
    if assertion_hdr.exists():
        value = extract_define(read_text(assertion_hdr), macro_name)
        if value is not None:
            return value.rstrip("uU") == str(target_size), value
    return None, None


def verify_generated_outputs(variant_root: Path, target_size: int, target: str) -> dict[str, object]:
    profile = TARGETS[target]
    result: dict[str, object] = {
        "target_size": target_size,
        "assertion_matches": False,
        "arxml_matches": False,
        "nvm_cfg_matches": None,
        "details": {},
    }

    assertion_hdr = variant_root / "src_out" / "bct" / "_out" / "Dem_Cfg_AssertionChk.h"
    if assertion_hdr.exists():
        assertion_val = extract_define(read_text(assertion_hdr), profile["assertion_macro"])
        result["details"]["assertion_size"] = assertion_val
        if assertion_val is not None:
            result["assertion_matches"] = assertion_val.rstrip("uU") == str(target_size)

    arxml_path = variant_root / "src_out" / "bct" / "RBPDM_gen_NvM_EcucValues.arxml"
    if arxml_path.exists():
        arxml_text = read_text(arxml_path)
        short_name = "NVM_ID_EVMEM_LOC_0" if target == "evmem" else "NVM_ID_DEM_GENERIC_NV_DATA"
        match = re.search(
            rf"<SHORT-NAME>{re.escape(short_name)}</SHORT-NAME>.*?<DEFINITION-REF DEST=\"ECUC-INTEGER-PARAM-DEF\">(?:/AUTOSAR|/AUTOSAR_NvM).*?NvMNvBlockLength</DEFINITION-REF>\s*<VALUE>(\d+)</VALUE>",
            arxml_text,
            re.DOTALL,
        )
        if match:
            arxml_val = match.group(1)
            result["details"]["arxml_nvm_block_length"] = arxml_val
            result["arxml_matches"] = int(arxml_val) == target_size

    nvm_cfg = variant_root / "src_out" / "bct" / "_out" / "NvM_Cfg.h"
    if nvm_cfg.exists():
        text = read_text(nvm_cfg)
        match = re.search(rf"{re.escape(profile['nvm_cfg_macro'])}\s*\((\d+)u\)", text)
        if match:
            nvm_val = int(match.group(1))
            result["details"]["nvm_cfg_length"] = nvm_val
            result["nvm_cfg_matches"] = nvm_val == target_size

    return result


def existing_size_family(pdmdb_path: Path, target_size: int, target: str) -> bool:
    text = read_text(pdmdb_path)
    return TARGETS[target]["reuse_pattern"].format(size=target_size) in text


def next_dataitem_id(pdmdb_path: Path, prefix_pattern: str) -> int:
    text = read_text(pdmdb_path)
    ids = [int(m.group(1)) for m in re.finditer(prefix_pattern + r"\s*\{?id\s*=\s*(\d+)", text)]
    if not ids:
        raise SystemExit("Unable to determine next dataitem id from pdmdb")
    return max(ids) + 1


def render_pdmdb_block(target_size: int, start_id: int, task_id: str = "AUTO") -> str:
    blocks: list[str] = []
    for idx in range(10):
        data_id = start_id + idx
        blocks.extend(
            [
                "/* -------------------------------------------------------------------------- */\n",
                f"@brief      {{Event Memory (Record {idx}), Size {target_size} Bytes}}\n",
                f"@task       {{{task_id}}}\n",
                "@asil       {ASIL QM}\n",
                "@desc       {\n",
                "- Component: DEM Event Memory\n",
                "- REPROG info: use case REPROG must be set (data must be reset after reprogramming)!\n",
                f"Event Memory Record {idx}\n",
                f"Size {target_size} Bytes\n",
                "}\n",
                f"dataitem NVM_ID_EVMEM_LOC_{target_size}_{idx}{{id = {data_id}; size = {target_size}; write_abort_result = old_or_new; corruption_result = current; }}\n",
                "\n",
            ]
        )
    return "".join(blocks)


def detect_dataitem_prefix(pdmdb_path: Path) -> str:
    text = read_text(pdmdb_path)
    match = re.search(r"^\s*([A-Za-z0-9_]+)\s+dataitem\s+NVM_ID_EVMEM_LOC_\d+_\d+", text, re.MULTILINE)
    return match.group(1) if match else ""


def detect_generic_dataitem_prefix(pdmdb_path: Path) -> str:
    text = read_text(pdmdb_path)
    match = re.search(r"^\s*([A-Za-z0-9_]+)\s+dataitem\s+NVM_ID_DEM_GENERIC_NV_DATA_\d+", text, re.MULTILINE)
    return match.group(1) if match else detect_dataitem_prefix(pdmdb_path)


def find_generic_insert_context(pdmdb_path: Path) -> dict[str, int]:
    lines = read_text(pdmdb_path).splitlines(True)
    last_obd_line = None
    last_obd_id = None
    next_data_line = None
    for idx, line in enumerate(lines, start=1):
        if "NVM_ID_OBD_IUMPR_DATA" in line:
            last_obd_line = idx
            match = re.search(r"id\s*=\s*(\d+)", line)
            if match:
                last_obd_id = int(match.group(1))
        elif last_obd_line is not None and next_data_line is None:
            if re.search(r"\bdataitem\b", line) and "NVM_ID_OBD_" not in line:
                next_data_line = idx
                break
    if last_obd_line is None or last_obd_id is None:
        raise SystemExit("Unable to resolve OBD Memory Records section in pdmdb")
    next_id = None
    if next_data_line is not None:
        match = re.search(r"id\s*=\s*(\d+)", lines[next_data_line - 1])
        if match:
            next_id = int(match.group(1))
    return {
        "insert_line": next_data_line - 1 if next_data_line is not None else len(lines),
        "start_id": last_obd_id + 1,
        "limit_id": (next_id - 1) if next_id is not None else last_obd_id + 999,
    }


def append_pdmdb_block(pdmdb_path: Path, target_size: int) -> dict[str, object]:
    if existing_size_family(pdmdb_path, target_size):
        return {"appended": False, "reason": "target family already exists"}

    text = read_text(pdmdb_path)
    start_id = next_evmem_id(pdmdb_path)
    prefix = detect_dataitem_prefix(pdmdb_path)
    block = render_pdmdb_block(target_size, start_id).replace(
        "dataitem NVM_ID_EVMEM_LOC_",
        f"{prefix} dataitem NVM_ID_EVMEM_LOC_" if prefix else "dataitem NVM_ID_EVMEM_LOC_",
    )

    insert_at = len(text)
    gap_match = re.search(r"(?m)^/\* -------------------------------------------------------------------------- \*/\r?\n/\* GAP: id .*", text)
    if gap_match:
        insert_at = gap_match.start()

    new_text = text[:insert_at] + block + text[insert_at:]
    pdmdb_path.write_text(new_text, encoding="utf-8", newline="")
    return {
        "appended": True,
        "target_size": target_size,
        "start_id": start_id,
        "end_id": start_id + 9,
    }


def append_generic_pdmdb_item(pdmdb_path: Path, target_size: int) -> dict[str, object]:
    if existing_size_family(pdmdb_path, target_size, "generic"):
        return {"appended": False, "reason": "target family already exists"}
    text = read_text(pdmdb_path)
    context = find_generic_insert_context(pdmdb_path)
    start_id = int(context["start_id"])
    limit_id = int(context["limit_id"])
    if start_id > limit_id:
        raise SystemExit("No free id available after OBD Memory Records for Generic NV Data")
    prefix = detect_generic_dataitem_prefix(pdmdb_path)
    line_prefix = f"{prefix} dataitem" if prefix else "dataitem"
    block = "".join(
        [
            "/* -------------------------------------------------------------------------- */\n",
            f"@brief      {{Dem Generic NV Data (Size {target_size} Bytes)}}\n",
            "@task       {AUTO}\n",
            "@asil       {ASIL QM}\n",
            "@desc       {\n",
            "- Component: DEM\n",
            "- REPROG info: use case REPROG shall be set (data must be reset after reprogramming)!\n",
            f"Dem Generic NV Data (Size {target_size} Bytes)\n",
            "}\n",
            f"{line_prefix} NVM_ID_DEM_GENERIC_NV_DATA_{target_size} {{id = {start_id}; size = {target_size}; write_abort_result = old_or_new_or_none; corruption_result = current; }}\n\n",
        ]
    )
    lines = text.splitlines(True)
    lines.insert(int(context["insert_line"]), block)
    pdmdb_path.write_text("".join(lines), encoding="utf-8", newline="")
    return {"appended": True, "target_size": target_size, "start_id": start_id, "end_id": start_id}


def impacted_buildconfigs(project_cfg_dir: Path, variant_hint: str) -> list[str]:
    impacted: list[str] = []
    pattern = re.compile(r"RBFS_BUILDCONFIG_([A-Za-z0-9x_]+)")
    for header in project_cfg_dir.glob("*.h"):
        text = read_text(header)
        if variant_hint in text or "RBFS_ApbDistributed_OneBoxMainSystem" in text or "RBFS_ApbDistributed_None" in text:
            impacted.extend(pattern.findall(text))
    seen: set[str] = set()
    ordered: list[str] = []
    for item in impacted:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def resolve_pdmdb_path(project_root: Path, effective_pdm: Path | None = None) -> Path:
    candidates = sorted(project_root.glob("rb/as/**/global/rbpdmdb/*.pdmdb"))
    if not candidates:
        raise SystemExit("Unable to locate project pdmdb under rb/as/**/global/rbpdmdb")
    if effective_pdm is not None:
        parts = effective_pdm.parts
        if "as" in parts:
            as_index = parts.index("as")
            if as_index + 1 < len(parts):
                customer = parts[as_index + 1]
                customer_candidates = [c for c in candidates if customer in c.parts]
                if customer_candidates:
                    candidates = customer_candidates
    evmem_candidates = [candidate for candidate in candidates if "NVM_ID_EVMEM_LOC_" in read_text(candidate)]
    return evmem_candidates[0] if evmem_candidates else candidates[0]


def resolve_generic_pdmdb_path(project_root: Path) -> Path:
    candidates = sorted(project_root.glob("rb/as/**/global/rbpdmdb/*.pdmdb"))
    generic_candidates = [candidate for candidate in candidates if "NVM_ID_DEM_GENERIC_NV_DATA_" in read_text(candidate)]
    if not generic_candidates:
        raise SystemExit("Unable to locate a project/global pdmdb containing NVM_ID_DEM_GENERIC_NV_DATA_* items")
    return generic_candidates[0]


def resolve_project_cfg_dir(project_root: Path) -> Path:
    candidates = sorted(project_root.glob("rb/as/**/csw/project/cfg"))
    if not candidates:
        raise SystemExit("Unable to locate project cfg directory under rb/as/**/csw/project/cfg")
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--buildconfig", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force-fallback", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--target", choices=sorted(TARGETS.keys()), default="evmem")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    profile = TARGETS[args.target]
    variant_root = project_root / "Gen" / args.buildconfig
    if not variant_root.exists():
        raise SystemExit(f"Variant folder not found: {variant_root}")

    switch_file = find_one(variant_root, ["out/SwitchSettings_*.csv"])
    lst_file = variant_root / "src_out" / "obj" / "Dem_EvMem.lst"
    pdm_includes = variant_root / "src_out" / "tmp" / "pdm_includes.h"
    cfg_dbfiles = variant_root / "src_out" / "tmp" / "Cfg_DBFiles_GenMake.csv"
    dem_cfg_evmem = variant_root / "src_out" / "bct" / "_out" / "Dem_Cfg_EvMem.h"
    assertion_hdr = variant_root / "src_out" / "bct" / "_out" / "Dem_Cfg_AssertionChk.h"
    nv_arxml = variant_root / "src_out" / "bct" / "RBPDM_gen_NvM_EcucValues.arxml"

    required = [switch_file, lst_file, pdm_includes, cfg_dbfiles, dem_cfg_evmem, assertion_hdr]
    missing = [str(p) for p in required if not p or not Path(p).exists()]
    if missing:
        raise SystemExit("Missing required evidence:\n- " + "\n- ".join(missing))

    switch_values = parse_switch_settings(switch_file)
    evmem_text = read_text(dem_cfg_evmem)
    array_length_expr = extract_define(evmem_text, "DEM_CFG_MAX_NUMBER_EVENT_ENTRY_ALL")
    primary = extract_define(evmem_text, "DEM_CFG_MAX_NUMBER_EVENT_ENTRY_PRIMARY")
    userdef = extract_define(evmem_text, "DEM_CFG_USERDEFINED_MEMORIES_NUMBER") or "0u"
    mirror = extract_define(evmem_text, "DEM_CFG_MAX_NUMBER_EVENT_ENTRY_MIRROR") or "0u"
    read_from_diff_task = extract_define(evmem_text, "DEM_CFG_EVMEM_READ_FROM_DIFFERENT_TASK")

    try:
        all_entries = int(primary.rstrip("uU")) + int(userdef.rstrip("uU")) + int(mirror.rstrip("uU"))
    except ValueError as exc:
        raise SystemExit(f"Unable to resolve entry counts from Dem_Cfg_EvMem.h: {exc}")
    eventmemory_length = all_entries * 2 if read_from_diff_task == "TRUE" else all_entries

    if args.target == "generic" and not args.force_fallback:
        total_array_size = parse_generic_lst_size(variant_root)
    else:
        total_array_size = None if args.force_fallback else (parse_lst_size(lst_file, profile["lst_symbol"]) if lst_file.exists() else None)
    size_source = "lst"
    if total_array_size is not None:
        if profile["size_mode"] == "array":
            if eventmemory_length <= 0 or total_array_size % eventmemory_length != 0:
                raise SystemExit(
                    f"Invalid event memory sizing: total={total_array_size}, eventmemory_length={eventmemory_length}"
                )
            real_size = total_array_size // eventmemory_length
        else:
            real_size = total_array_size
    else:
        if args.target == "evmem":
            real_size = compute_struct_size_fallback(variant_root, project_root)
        else:
            real_size = compute_generic_nvdata_size_fallback(variant_root, project_root)
        size_source = "fallback"

    effective_pdm_rel = parse_effective_pdm(pdm_includes, cfg_dbfiles)
    if not effective_pdm_rel:
        raise SystemExit("Unable to resolve effective Dem_PRJ.pdm from generated evidence")
    effective_pdm = project_root / effective_pdm_rel
    if not effective_pdm.exists():
        fallback_match = find_existing_path(project_root, [f"**/{Path(effective_pdm_rel).name}"])
        if fallback_match is not None:
            effective_pdm = fallback_match
    if not effective_pdm.exists():
        raise SystemExit(f"Effective PDM file not found: {effective_pdm}")

    pdmdb_path = resolve_pdmdb_path(project_root, effective_pdm) if args.target == "evmem" else resolve_generic_pdmdb_path(project_root)
    if not pdmdb_path.exists():
        raise SystemExit(f"PDMDB file not found: {pdmdb_path}")

    current_items = parse_current_dataitems(effective_pdm, profile["pdm_alias_regex"])
    target_alias = "NVM_ID_EVMEM_LOC_0" if args.target == "evmem" else "NVM_ID_DEM_GENERIC_NV_DATA"
    current_family = next((src for _, src, alias in current_items if alias == target_alias), None)
    current_size = None
    if current_family:
        match = re.search(profile["family_extract_regex"], current_family)
        current_size = int(match.group(1)) if match else None

    assertion_text = read_text(assertion_hdr)
    assertion_size = extract_define(assertion_text, profile["assertion_macro"])

    project_cfg_dir = resolve_project_cfg_dir(project_root)
    project_variant = switch_values.get("RBFS_ProjectVariant", "")
    impacted = impacted_buildconfigs(project_cfg_dir, project_variant)

    active_ranges = parse_active_branch_ranges(effective_pdm, switch_values.get("RBFS_ApbDistributed", ""))
    apply_result = None
    pdmdb_append_result = None
    verify_result = None
    if args.apply:
        if current_size is None:
            raise SystemExit("Unable to determine current active NVM_ID_EVMEM_LOC size")
        if current_size == real_size:
            apply_result = {"changed": False, "reason": "current mapping already matches target size"}
        elif not profile["apply_supported"]:
            apply_result = {"changed": False, "reason": f"apply is not implemented for target '{args.target}' yet"}
        elif not active_ranges:
            raise SystemExit("Unable to resolve active branch range in Dem_PRJ.pdm")
        else:
            if args.target == "evmem":
                if not existing_size_family(pdmdb_path, real_size, args.target):
                    pdmdb_append_result = append_pdmdb_block(pdmdb_path, real_size)
                changes = replace_active_branch_items(effective_pdm, active_ranges, current_size, real_size)
            else:
                if not existing_size_family(pdmdb_path, real_size, args.target):
                    pdmdb_append_result = append_generic_pdmdb_item(pdmdb_path, real_size)
                changes = replace_active_branch_items_regex(
                    effective_pdm,
                    active_ranges,
                    re.compile(rf"(use\s+dataitem\s+NVM_ID_DEM_GENERIC_NV_DATA_){current_size}(\s+as\s+NVM_ID_DEM_GENERIC_NV_DATA)"),
                    rf"\g<1>{real_size}\g<2>",
                )
            apply_result = {
                "changed": bool(changes),
                "change_count": len(changes),
                "changes": changes,
            }

    if args.verify:
        verify_result = verify_generated_outputs(variant_root, real_size, args.target)

    result = {
        "buildconfig": args.buildconfig,
        "variant_root": str(variant_root),
        "effective_pdm_file": str(effective_pdm),
        "rbfs_buildconfig": switch_values.get("RBFS_BUILDCONFIG", ""),
        "rbfs_apbdistributed": switch_values.get("RBFS_ApbDistributed", ""),
        "target": args.target,
        "display_name": profile["display_name"],
        "real_struct_size": real_size,
        "array_total_size": total_array_size,
        "eventmemory_length": eventmemory_length,
        "entry_count_primary": primary,
        "read_from_different_task": read_from_diff_task,
        "size_source": size_source,
        "current_dataitem_family": current_family,
        "current_pdm_size": current_size,
        "assertion_size": assertion_size,
        "target_size_exists_in_pdmdb": existing_size_family(pdmdb_path, real_size, args.target),
        "switch_settings": {
            "RBFS_BUILDCONFIG": switch_values.get("RBFS_BUILDCONFIG", ""),
            "RBFS_ApbDistributed": switch_values.get("RBFS_ApbDistributed", ""),
        },
        "impacted_buildconfigs": impacted,
        "recommended_change": {
            "target_size": real_size,
            "reuse_existing_family": existing_size_family(pdmdb_path, real_size, args.target),
            "edit_scope": "active branch in active Dem_PRJ.pdm only",
        },
        "active_branch_ranges": active_ranges,
        "apply_result": apply_result,
        "pdmdb_append_result": pdmdb_append_result,
        "verify_result": verify_result,
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print("Buildconfig")
    print(f"- {args.buildconfig}")
    print()
    print("Effective Context")
    print(f"- Active PDM file: {effective_pdm}")
    print(f"- ApbDistributed: {switch_values.get('RBFS_ApbDistributed', '')}")
    print()
    print("Size Analysis")
    print(f"- Real {profile['display_name']} size: {real_size} bytes")
    if size_source == "lst":
        print(f"- Evidence: Dem_EvMem.lst total {total_array_size} / eventmemory_length {eventmemory_length}")
    else:
        print("- Evidence: fallback struct-size calculation")
    print()
    print("Current PDM Mapping")
    print(f"- Current family: {current_family}")
    print(f"- Current PDM size: {current_size}")
    print(f"- Assertion size: {assertion_size}")
    print()
    print("Recommended Change")
    print(f"- Target size: {real_size}")
    print(f"- Reuse existing family: {'yes' if existing_size_family(pdmdb_path, real_size, args.target) else 'no'}")
    print("- Active file edit: active branch only")
    print()
    print("Impact Note")
    if impacted:
        for item in impacted[:20]:
            print(f"- {item}")
    else:
        print("- none found")
    if apply_result is not None:
        print()
        print("Apply Result")
        if pdmdb_append_result is not None:
            if pdmdb_append_result.get("appended"):
                print(
                    f"- Appended pdmdb family NVM_ID_EVMEM_LOC_{pdmdb_append_result['target_size']}_0..9 "
                    f"with ids {pdmdb_append_result['start_id']}..{pdmdb_append_result['end_id']}"
                )
            else:
                print(f"- pdmdb append skipped: {pdmdb_append_result.get('reason', 'not needed')}")
        if apply_result.get("changed"):
            print(f"- Updated lines: {apply_result['change_count']}")
            for line_no, before, after in apply_result["changes"]:
                print(f"- Line {line_no}: {before} -> {after}")
        else:
            print(f"- {apply_result.get('reason', 'no changes applied')}")
    if verify_result is not None:
        print()
        print("Verification")
        print(f"- Assertion header matches target: {verify_result['assertion_matches']}")
        print(f"- ARXML NvM block length matches target: {verify_result['arxml_matches']}")
        if verify_result.get("nvm_cfg_matches") is not None:
            print(f"- NvM_Cfg.h matches target: {verify_result['nvm_cfg_matches']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
