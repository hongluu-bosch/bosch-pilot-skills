"""Phase 4: build and optionally upload a DOORS workbook for Service 0x19 snapshot content.

The 19-service flow exports ONE service-level two-row block:
1. FS / ARXML row  -> Positive Response Message text + one ARXML basename
2. CS / C-code row -> Available Snapshot Data text + newline-joined C basenames
"""

from __future__ import annotations

import getpass
import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from io_encoding import save_text

DEFAULT_COLUMNS: List[str] = [
    "Number",
    "Destination Object",
    "isPicture",
    "Absolute Number",
    "Object Heading",
    "Object Text",
    "RB_RS_CP_Status",
    "RB_RS_MS_Status",
    "RB_Product",
    "RB_Configuration",
    "RB_Realizing_SWComponent",
    "RB_Realizing_SWitem",
    "RB_VerificationType",
    "RB_VerificationCriteria",
    "RB_Analysis_Results",
    "RB_Referenced_Testcase",
    "RB_TestEnvironment",
]

COMMON_TOKEN = "Common"
KEYRING_SERVICE = "19service-toolkit:doors"

_SKILL_ROOT = pathlib.Path(__file__).resolve().parent.parent
_DID_TOOLKIT_ROOT = _SKILL_ROOT.parent / "did-toolkit"


@dataclass
class AnchorMatch:
    anchor_text: str
    anchor_address: str
    absolute_number: str


def run_phase4(workspace: pathlib.Path, args: Any) -> int:
    fscs_txt = workspace / "outputs" / "fscs" / "FSCS_19.txt"
    fscs_json = workspace / "outputs" / "fscs" / "fscs.json"
    mapping_path = workspace / "inputs" / "doors_mapping.yaml"
    export_path = workspace / "outputs" / "doors" / "doors_export.json"
    out_dir = workspace / "outputs" / "doors"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not fscs_txt.exists():
        print(f"[ERROR] {fscs_txt} not found. Run --phase fscs first.")
        return 1
    if not fscs_json.exists():
        print(f"[ERROR] {fscs_json} not found. Run --phase fscs first.")
        return 1
    if not mapping_path.exists():
        print(f"[ERROR] {mapping_path} not found. Prepare doors_mapping.yaml first.")
        return 1

    mapping = _load_yaml(mapping_path)
    module_uuid = _module_uuid(mapping, allow_placeholder=args.no_upload)
    doc = json.loads(fscs_json.read_text(encoding="utf-8"))
    sections = _split_fscs_sections(fscs_txt)
    product_value = _rb_product_value(doc, mapping)
    arxml_basename, c_basenames = _collect_realizing_items(doc, workspace)

    anchor = None

    # Fetch export opportunistically when we have credentials and the caller did
    # not suppress it. This enables a real anchor lookup even in preview mode.
    if args.user_nt and not args.no_fetch:
        try:
            _fetch_export(module_uuid=module_uuid, user_nt=args.user_nt, out_path=export_path)
        except Exception as exc:  # noqa: BLE001
            if not args.no_upload:
                raise
            print(f"[WARN] DOORS fetch failed during preview: {exc}")

    if export_path.exists():
        anchor = _resolve_anchor(export_path, mapping)

    xlsx_path = out_dir / "doors_upload_19.xlsx"
    _write_doors_xlsx(
        xlsx_path=xlsx_path,
        mapping=mapping,
        anchor=anchor,
        product_value=product_value,
        positive_text=sections[0],
        available_text=sections[1],
        arxml_basename=arxml_basename,
        c_basenames=c_basenames,
    )

    # Build-only mode stops after the workbook is written.
    if args.no_upload:
        report = out_dir / "doors_upload_report.txt"
        save_text(report, _build_report(xlsx_path=xlsx_path, anchor=anchor,
                                        product_value=product_value,
                                        arxml_basename=arxml_basename,
                                        c_basenames=c_basenames,
                                        upload_mode="preview",
                                        module_uuid=module_uuid))
        print(f"[OK] DOORS payload built: {xlsx_path}")
        print("[AGENT STOP] Preview ready. Remove --no-upload and provide --user-nt to upload.")
        return 0

    if not args.user_nt:
        print("[ERROR] --user-nt is required for DOORS upload.")
        return 1

    keyring_mod = _try_import_keyring(False)
    if args.forget_credentials:
        _keyring_delete(keyring_mod, args.user_nt)
        return 0

    password, pwd_source = _resolve_password(
        cli_password=getattr(args, "password", None),
        user_nt=args.user_nt,
        keyring_mod=keyring_mod,
        allow_prompt=True,
    )
    if not password:
        print("[ERROR] No DOORS password available. Use --password, DOORS_PWD, keyring, or interactive prompt.")
        return 1
    if args.save_credentials:
        _keyring_set(keyring_mod, args.user_nt, password)

    if not export_path.exists() and not args.no_fetch:
        _fetch_export(module_uuid=module_uuid, user_nt=args.user_nt, out_path=export_path)
        anchor = _resolve_anchor(export_path, mapping)

    result = _upload_one(
        excel_path=xlsx_path,
        module_uuid=module_uuid,
        user_nt=args.user_nt,
        password=password,
    )

    report = out_dir / "doors_upload_report.txt"
    save_text(report, _build_report(xlsx_path=xlsx_path, anchor=anchor,
                                    product_value=product_value,
                                    arxml_basename=arxml_basename,
                                    c_basenames=c_basenames,
                                    upload_mode="uploaded",
                                    module_uuid=module_uuid,
                                    upload_result=result.get("message", "")))

    print(f"[OK] DOORS payload built and uploaded: {xlsx_path}")
    print("[AGENT STOP] DOORS upload completed.")
    return 0


def _load_yaml(path: pathlib.Path) -> Dict[str, Any]:
    import yaml
    loaded = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("doors_mapping.yaml must be a top-level mapping")
    return loaded


def _module_uuid(mapping: Dict[str, Any], *, allow_placeholder: bool = False) -> str:
    module_uuid = str(mapping.get("module_uuid") or "").strip()
    placeholder = (not module_uuid) or ("PUT-" in module_uuid) or ("TODO" in module_uuid)
    if placeholder:
        if allow_placeholder:
            return module_uuid or "(placeholder)"
        raise ValueError("inputs/doors_mapping.yaml needs a real module_uuid.")
    return module_uuid


def _try_import_keyring(disabled: bool):
    if disabled:
        return None
    try:
        import keyring  # type: ignore
    except ImportError:
        return None
    return keyring


def _keyring_get(keyring_mod, user_nt: str) -> Optional[str]:
    if keyring_mod is None or not user_nt:
        return None
    try:
        return keyring_mod.get_password(KEYRING_SERVICE, user_nt)
    except Exception:
        return None


def _keyring_set(keyring_mod, user_nt: str, password: str) -> bool:
    if keyring_mod is None or not user_nt or not password:
        return False
    try:
        keyring_mod.set_password(KEYRING_SERVICE, user_nt, password)
    except Exception:
        return False
    return True


def _keyring_delete(keyring_mod, user_nt: str) -> bool:
    if keyring_mod is None or not user_nt:
        return False
    try:
        existing = keyring_mod.get_password(KEYRING_SERVICE, user_nt)
        if existing is None:
            return True
        keyring_mod.delete_password(KEYRING_SERVICE, user_nt)
        return True
    except Exception:
        return False


def _resolve_password(*, cli_password: Optional[str], user_nt: str, keyring_mod, allow_prompt: bool) -> Tuple[Optional[str], str]:
    if cli_password:
        return cli_password, "cli"
    env_pwd = os.environ.get("DOORS_PWD")
    if env_pwd:
        return env_pwd, "env"
    cached = _keyring_get(keyring_mod, user_nt)
    if cached:
        return cached, "keyring"
    if not allow_prompt or not sys.stdin.isatty():
        return None, "none"
    try:
        pwd = getpass.getpass(f"DOORS password for {user_nt}: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None, "none"
    if not pwd:
        return None, "none"
    return pwd, "prompt"


def _split_fscs_sections(fscs_path: pathlib.Path) -> Tuple[str, str]:
    text = fscs_path.read_text(encoding="utf-8")
    marker = "Available Snapshot Data"
    if marker not in text:
        return _extract_positive_response(text), ""
    before, after = text.split(marker, 1)
    positive = _extract_positive_response(before)
    available = (marker + after).strip()
    return positive, available


def _extract_positive_response(text: str) -> str:
    marker = "Positive Response Message:"
    if marker not in text:
        return text.strip()
    return text[text.index(marker):].strip()


def _rb_product_value(doc: Dict[str, Any], mapping: Dict[str, Any]) -> str:
    value_maps = mapping.get("value_maps") if isinstance(mapping.get("value_maps"), dict) else {}
    rb_map = value_maps.get("RB_Product") if isinstance(value_maps.get("RB_Product"), dict) else {}
    product_types = []
    for did in doc.get("dids", []):
        if not isinstance(did, dict) or not did.get("used", True):
            continue
        pt = str(did.get("product_type") or "").strip()
        if pt and pt not in product_types:
            product_types.append(pt)
    if any(pt.casefold() == COMMON_TOKEN.casefold() for pt in product_types):
        seen: List[str] = []
        for v in rb_map.values():
            text = str(v).strip()
            if text and text not in seen:
                seen.append(text)
        return "\n".join(seen)
    mapped_values: List[str] = []
    for pt in product_types:
        mapped = rb_map.get(pt, pt)
        mapped_text = str(mapped).strip()
        if mapped_text and mapped_text not in mapped_values:
            mapped_values.append(mapped_text)
    return "\n".join(mapped_values)


def _collect_realizing_items(doc: Dict[str, Any], workspace: pathlib.Path) -> Tuple[str, str]:
    config = json.loads((workspace / "config" / "project.json").read_text(encoding="utf-8"))
    suffix_map = config.get("paths", {}).get("product_type_to_arxml_suffix", {})
    customer = config.get("customer_name", "customer")
    project_root = config.get("project_root", "")
    base_dir = pathlib.Path(config.get("base_dir", ""))
    product_types = []
    for did in doc.get("dids", []):
        if isinstance(did, dict) and did.get("used", True):
            pt = str(did.get("product_type") or "").strip() or "Common"
            if pt not in product_types:
                product_types.append(pt)
    arxml_pattern = config.get("paths", {}).get("arxml_file_pattern", "DemEnvData_RBAPLCUST_EcucValues{suffix}.arxml")
    first_pt = product_types[0] if product_types else "Common"
    suffix = suffix_map.get(first_pt, "")
    arxml_basename = pathlib.Path(arxml_pattern.format(suffix=suffix)).name

    c_basenames: List[str] = []
    src_root = base_dir / project_root / "rb" / "as" / customer / "core" / "app" / "dcom" / "RBAPLCust" / "src"
    if src_root.exists():
        for path in src_root.rglob("RBAPLCUST_19Snapshot_*.c"):
            if path.name not in c_basenames:
                c_basenames.append(path.name)
    if not c_basenames:
        for did in doc.get("dids", []):
            if not isinstance(did, dict) or not did.get("used", True):
                continue
            generated = did.get("generated_c_file")
            if generated:
                name = pathlib.Path(str(generated)).name
                if name not in c_basenames:
                    c_basenames.append(name)
    return arxml_basename, "\n".join(c_basenames)


def _resolve_anchor(export_path: pathlib.Path, mapping: Dict[str, Any]) -> AnchorMatch | None:
    keyword = ((mapping.get("anchor") or {}).get("keyword") or "").strip()
    if not keyword:
        return None
    export = json.loads(export_path.read_text(encoding="utf-8-sig"))
    rows = ((export.get("data") or {}).get("rows") or []) if isinstance(export, dict) else []
    normalized_keyword = _normalize_anchor_text(keyword)
    for row in rows:
        candidate_texts = [
            str((row.get("Object Text") or "")).strip(),
            str((row.get("DescriptionOfRequirementRB") or "")).strip(),
            str((row.get("Object Heading") or "")).strip(),
        ]
        if any(normalized_keyword in _normalize_anchor_text(text) for text in candidate_texts if text):
            abs_no = str(row.get("AbsoluteNumber") or row.get("Absolute Number") or "")
            return AnchorMatch(
                anchor_text=next((text for text in candidate_texts if normalized_keyword in _normalize_anchor_text(text)), ""),
                # For insert mode, Destination Object means "insert after this row".
                # The most stable value exposed by the fetched module is the row's
                # absolute number.
                anchor_address=abs_no,
                absolute_number=abs_no,
            )
    return None


def _normalize_anchor_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _write_doors_xlsx(*, xlsx_path: pathlib.Path, mapping: Dict[str, Any], anchor: AnchorMatch | None,
                      product_value: str, positive_text: str, available_text: str,
                      arxml_basename: str, c_basenames: str) -> None:
    import xlsxwriter
    workbook = xlsxwriter.Workbook(str(xlsx_path))
    ws = workbook.add_worksheet("FSCS_19")
    for col, name in enumerate(DEFAULT_COLUMNS):
        ws.write(0, col, name)
    row_fs = _build_row(mapping, anchor, role="FS", product_value=product_value,
                        object_text=positive_text, realizing_item=arxml_basename)
    row_cs = _build_row(mapping, anchor, role="CS", product_value=product_value,
                        object_text=available_text, realizing_item=c_basenames)
    for col, name in enumerate(DEFAULT_COLUMNS):
        ws.write(1, col, row_fs.get(name, ""))
        ws.write(2, col, row_cs.get(name, ""))
    workbook.close()


def _build_row(mapping: Dict[str, Any], anchor: AnchorMatch | None, *, role: str,
               product_value: str, object_text: str, realizing_item: str) -> Dict[str, str]:
    defaults = mapping.get("defaults") if isinstance(mapping.get("defaults"), dict) else {}
    role_values = mapping.get("role_values") if isinstance(mapping.get("role_values"), dict) else {}
    role_block = role_values.get(role, {}) if isinstance(role_values.get(role), dict) else {}
    row = {name: "" for name in DEFAULT_COLUMNS}
    row.update({k: str(v) for k, v in defaults.items()})
    row.update({k: str(v) for k, v in role_block.items()})
    row["Object Heading"] = ""
    row["Object Text"] = object_text
    row["RB_Product"] = product_value
    row["RB_Realizing_SWitem"] = realizing_item
    # Current 19-service export always generates a fresh two-row block, so we
    # populate Destination Object (insert-after target) and leave Absolute Number
    # blank. Absolute Number will matter when/if a future update mode is added.
    row["Destination Object"] = anchor.anchor_address if anchor else ""
    row["Absolute Number"] = ""
    row["isPicture"] = "0"
    return row


def _fetch_export(*, module_uuid: str, user_nt: str, out_path: pathlib.Path) -> pathlib.Path:
    from importlib.util import spec_from_file_location, module_from_spec

    doors_fetch_path = _DID_TOOLKIT_ROOT / "scripts" / "fscs" / "doors" / "doors_fetch.py"
    spec = spec_from_file_location("did_doors_fetch", str(doors_fetch_path))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    payload = module.fetch_module(module_uuid=module_uuid, user_nt=user_nt)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _upload_one(*, excel_path: pathlib.Path, module_uuid: str, user_nt: str, password: str) -> Dict[str, Any]:
    from importlib.util import spec_from_file_location, module_from_spec

    upload_path = _DID_TOOLKIT_ROOT / "scripts" / "fscs" / "doors" / "doors_upload_mcp.py"
    spec = spec_from_file_location("did_doors_upload", str(upload_path))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.upload_module(excel_path=excel_path, module_uuid=module_uuid, user_nt=user_nt, password=password)


def _build_report(*, xlsx_path: pathlib.Path, anchor: AnchorMatch | None,
                  product_value: str, arxml_basename: str, c_basenames: str,
                  upload_mode: str, module_uuid: str, upload_result: str = "") -> str:
    c_items = [line for line in c_basenames.splitlines() if line.strip()]
    lines = [
        f"Built {xlsx_path}",
        "Row model: service-level 2 rows",
        f"Module UUID: {module_uuid}",
        f"Upload mode: {upload_mode}",
        f"Anchor found: {'yes' if anchor else 'no'}",
        f"Destination Object (insert after): {anchor.anchor_address if anchor else ''}",
        f"Anchor Absolute Number: {anchor.absolute_number if anchor else ''}",
        f"RB_Product: {product_value}",
        f"ARXML item: {arxml_basename}",
        f"C item count: {len(c_items)}",
        "C items:",
        c_basenames,
    ]
    if upload_result:
        lines.append(f"Upload result: {upload_result}")
    return "\n".join(lines) + "\n"
