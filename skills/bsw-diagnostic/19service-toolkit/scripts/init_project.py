"""Workspace scaffolding and state machine for --init-project."""

import json
import os
import pathlib
import sys
from typing import Any, Dict, List, Optional

from project_root import get_container, resolve_project_root

WORKSPACE_NAME = ".DCOM_AI/19Service_Toolkit_PRJ"
STATE_FILE = "state/init_state.json"
CONFIG_FILE = "config/project.json"


def run_init(args: Any) -> int:
    workspace = resolve_project_root()
    container = get_container(workspace)

    state = _load_state(workspace)

    if state == "FRESH":
        _scaffold(workspace)
        _save_state(workspace, "FOLDERS_ONLY")
        print("[OK] Workspace scaffolded.")
        print(f"[AGENT STOP] Drop a diagnostic questionnaire .xlsx under {workspace / 'inputs'} and re-run --init-project.")
        return 0

    if state == "FOLDERS_ONLY":
        xlsx_files = list((workspace / "inputs").glob("*.xlsx"))
        if not xlsx_files:
            print("[FYI] No .xlsx found in inputs/. Waiting for questionnaire.")
            print(f"[AGENT STOP] Drop a diagnostic questionnaire .xlsx under {workspace / 'inputs'} and re-run --init-project.")
            return 0
        _save_state(workspace, "QUESTIONNAIRE_READY")
        state = "QUESTIONNAIRE_READY"
        # fall through

    if state in ("QUESTIONNAIRE_READY", "COMPLETE") or (workspace / CONFIG_FILE).exists():
        if (workspace / CONFIG_FILE).exists() and not args.force:
            if state != "COMPLETE":
                _save_state(workspace, "COMPLETE")
            print("[OK] Existing config/project.json found; refusing to overwrite.")
            print("[AGENT STOP] Workspace already initialised. Run a phase (e.g. --phase fscs).")
            return 0

        product_types = _parse_product_types(args.product_types)
        if not product_types:
            print("[AGENT STOP] Product types must be supplied by the operator via their prompt.")
            print("             The agent must not infer, guess, or default product types.")
            print("             Please specify the product types for this project (e.g. Common,RBU,IPB).")
            return 4

        xlsx_files = list((workspace / "inputs").glob("*.xlsx"))
        config = _build_config(workspace, container, xlsx_files, product_types, args)
        _write_config(workspace, config)
        _save_state(workspace, "COMPLETE")
        print("[OK] config/project.json created.")
        print(f"[AGENT STOP] Workspace initialised. Run: python scripts/pipeline.py --phase fscs")
        return 0

    return 0


def _scaffold(workspace: pathlib.Path) -> None:
    for sub in ("config", "inputs", "outputs", "outputs/fscs", "outputs/arxml", "outputs/doors", "scripts", "state"):
        (workspace / sub).mkdir(parents=True, exist_ok=True)


def _load_state(workspace: pathlib.Path) -> str:
    state_path = workspace / STATE_FILE
    if not state_path.exists():
        return "FRESH"
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return data.get("state", "FRESH")
    except Exception:
        return "FRESH"


def _save_state(workspace: pathlib.Path, state: str) -> None:
    state_path = workspace / STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"state": state}, indent=2), encoding="utf-8")


def _parse_product_types(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [pt.strip() for pt in value.split(",") if pt.strip()]


def _build_config(workspace: pathlib.Path, container: pathlib.Path,
                  xlsx_files: List[pathlib.Path], product_types: List[str], args: Any) -> Dict[str, Any]:
    chosen = xlsx_files[0].name
    if len(xlsx_files) > 1 and args.input:
        chosen = args.input

    customer = args.customer_name or _detect_customer(container) or "customer"
    project_root_dir = args.project_root_name or "ProjectRoot"
    snapshot_paths = _detect_snapshot_c_output_dirs(container, project_root_dir, customer, product_types)

    return {
        "name": args.name or "Project",
        "customer_name": customer,
        "project_root": project_root_dir,
        "base_dir": str(container),
        "paths": {
            "input_xlsx": str(workspace / "inputs" / chosen),
            "cubas_dem_dir": f"rb/as/{customer}/core/app/dsm/Cubas_DEM",
            "snapshot_c_output_subdir": f"rb/as/{customer}/core/app/dcom/RBAPLCust/src/{{product_type}}",
            "arxml_file_pattern": "DemEnvData_RBAPLCUST_EcucValues{suffix}.arxml",
            "product_type_to_arxml_suffix": _default_suffix_map(product_types)
        },
        "per_product": {
            pt: {"snapshot_c_output_subdir": rel_path}
            for pt, rel_path in snapshot_paths.items()
        },
        "product_types": product_types
    }


def _detect_customer(container: pathlib.Path) -> Optional[str]:
    candidates = list((container / "rb" / "as").glob("*"))
    dirs = [c for c in candidates if c.is_dir()]
    if len(dirs) == 1:
        return dirs[0].name
    if len(dirs) > 1:
        # Prefer a folder that contains a DSM Cubas_DEM path
        for d in dirs:
            if (d / "core" / "app" / "dsm" / "Cubas_DEM").exists():
                return d.name
        return dirs[0].name
    return None


def _default_suffix_map(product_types: List[str]) -> Dict[str, str]:
    """Return the built-in ARXML suffix for each product type.

    The mapping is fixed by the toolkit. The agent must not invent, override,
    or derive suffixes from filenames or project structure.
    """
    defaults = {
        "Common": "",
        "RBU": "_RBU",
        "IPB": "_IPB",
        "ESP": "_ESP",
        "DPB": "_DPB",
        "ESPCL": "_ESPCL",
    }
    result = {}
    for pt in product_types:
        result[pt] = defaults.get(pt, f"_{pt}")
    return result


def _detect_snapshot_c_output_dirs(container: pathlib.Path, project_root_dir: str,
                                   customer: str, product_types: List[str]) -> Dict[str, str]:
    """Detect per-product RBAPLCust/src output directories for snapshot C stubs.

    The skill must stay project-agnostic, so this scans the real Bosch tree under
    <container>/<project_root>/rb/as/<customer>/core/app/dcom/RBAPLCust/src/ and
    records any matching product directories.  If a directory is missing, the
    generator will later fall back to the template in config['paths'].
    """
    result: Dict[str, str] = {}
    src_root = container / project_root_dir / "rb" / "as" / customer / "core" / "app" / "dcom" / "RBAPLCust" / "src"
    if not src_root.exists():
        return result

    for pt in product_types:
        candidate = src_root / pt
        if candidate.exists() and candidate.is_dir():
            result[pt] = f"rb/as/{customer}/core/app/dcom/RBAPLCust/src/{pt}"
        elif pt == "Common":
            common_dir = src_root / "Common"
            if common_dir.exists() and common_dir.is_dir():
                result[pt] = f"rb/as/{customer}/core/app/dcom/RBAPLCust/src/Common"
    return result


def _write_config(workspace: pathlib.Path, config: Dict[str, Any]) -> None:
    config_path = workspace / CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
