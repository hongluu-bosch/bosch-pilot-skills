"""Phase 2: fscs.json -> Dem ARXML merge using lxml."""

import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

from lxml import etree

from io_encoding import save_text


# Words removed when deriving a descriptive SHORT-NAME suffix from a DID name.
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "at", "in", "on", "of", "to", "for",
    "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "last", "fault", "code", "set",
}


def run_phase2(workspace: pathlib.Path, args: Any) -> int:
    config_path = workspace / "config" / "project.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    doc = json.loads((workspace / "outputs" / "fscs" / "fscs.json").read_text(encoding="utf-8"))

    base_dir = pathlib.Path(config["base_dir"])
    project_root = config.get("project_root", "")
    cubas_dem_dir = base_dir / project_root / config["paths"]["cubas_dem_dir"]
    if not cubas_dem_dir.exists():
        cubas_dem_dir = base_dir / config["paths"]["cubas_dem_dir"]
    suffix_map = config["paths"].get("product_type_to_arxml_suffix", {})
    pattern = config["paths"].get("arxml_file_pattern", "DemEnvData_RBAPLCUST_EcucValues{suffix}.arxml")

    products = _compute_workset(doc)
    if not products:
        print("[WARN] No product work-set; nothing to generate.")
        return 0

    reports_dir = workspace / "outputs" / "arxml"
    reports_dir.mkdir(parents=True, exist_ok=True)

    for pt in products:
        target = _resolve_target(cubas_dem_dir, pattern, pt, suffix_map)
        if not target:
            print(f"[ERROR] Could not resolve ARXML target for product={pt}")
            return 1

        dids = [d for d in doc["dids"] if d.get("used", True) and (d.get("product_type") or "Common") == pt]
        if not dids:
            print(f"[INFO] No active DIDs for product={pt}; skipping.")
            continue

        if args.dry_run:
            print(f"[DRY-RUN] Would merge {len(dids)} DIDs into {target}")
            continue

        skipped, added, added_refs = _merge_arxml(target, doc, dids)
        report = reports_dir / f"merge_report_{pt}.txt"
        save_text(report, _report(target, pt, dids, skipped, added, added_refs))

    print("[OK] Phase 2 complete.")
    return 0


def _compute_workset(doc: Dict[str, Any]) -> List[str]:
    pts = set()
    for did in doc.get("dids", []):
        if not did.get("used", True):
            continue
        pt = did.get("product_type") or "Common"
        pts.add(pt)
    if not pts:
        pts.update(doc.get("product_types", ["Common"]))
    return sorted(pts)


def _resolve_target(cubas_dem_dir: pathlib.Path, pattern: str, product_type: str,
                    suffix_map: Dict[str, str]) -> Optional[pathlib.Path]:
    if not cubas_dem_dir.exists():
        return None

    suffix = suffix_map.get(product_type, f"_{product_type}")
    preferred_name = pattern.format(suffix=suffix)
    fallback_name = pattern.format(suffix="")

    preferred = cubas_dem_dir / preferred_name
    if preferred.exists():
        return preferred

    fallback = cubas_dem_dir / fallback_name
    if fallback.exists():
        return fallback

    # Try loose suffix search
    stem = pattern.format(suffix="").replace(".arxml", "")
    candidates = list(cubas_dem_dir.glob(f"{stem}*.arxml"))
    if len(candidates) == 1:
        return candidates[0]

    return None


def _merge_arxml(target: pathlib.Path, doc: Dict[str, Any], dids: List[Dict[str, Any]]) -> Tuple[List[str], List[str], int]:
    from lxml import etree

    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(target), parser)
    root = tree.getroot()
    ns = root.nsmap.get(None)
    if ns is None:
        raise RuntimeError("ARXML has no default namespace")
    nsmap = {"a": ns}

    dem_general = _find_dem_general(root, nsmap)
    sub_containers = dem_general.find("a:SUB-CONTAINERS", nsmap)
    if sub_containers is None:
        sub_containers = etree.SubElement(dem_general, "{%s}SUB-CONTAINERS" % ns)

    existing_short_names = {
        _text(child.find("a:SHORT-NAME", nsmap))
        for child in sub_containers
        if child.tag == "{%s}ECUC-CONTAINER-VALUE" % ns
    }
    original_short_names = set(existing_short_names)

    # Map DemDidIdentifier VALUE -> existing DemDidClass SHORT-NAME so we do
    # not create duplicate DID classes when the existing file uses descriptive
    # suffixes (e.g. DemDidClass_0x1100_WheelSpeed).
    did_id_to_short_name = _map_existing_did_identifiers(sub_containers, ns, nsmap)

    # Map DemDidIdentifier VALUE -> existing DemDataElementClass SHORT-NAME by
    # following DemDidClass -> DemDidDataElementClassRef.
    did_int_to_data_elem_name = _map_existing_data_elements_by_did_ref(
        sub_containers, ns, nsmap, did_id_to_short_name
    )

    module_path = _module_path(root, nsmap)
    ff_class_name = doc["freeze_frame_class"]
    ff_recnum_class_name = doc["freeze_frame_rec_num_class"]

    skipped: List[str] = []
    added: List[str] = []
    added_refs = 0

    # Ensure DemFreezeFrameClass exists
    ff_class = _find_or_create_container(
        sub_containers, ff_class_name, ns, nsmap,
        definition_ref="/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemFreezeFrameClass",
        dest="ECUC-PARAM-CONF-CONTAINER-DEF",
    )
    ff_refs = ff_class.find("a:REFERENCE-VALUES", nsmap)
    if ff_refs is None:
        ff_refs = etree.SubElement(ff_class, "{%s}REFERENCE-VALUES" % ns)
    existing_ref_targets = {
        _text(ref.find("a:VALUE-REF", nsmap))
        for ref in ff_refs.findall("a:ECUC-REFERENCE-VALUE", nsmap)
    }

    ref_def = "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemFreezeFrameClass/DemDidClassRef"

    for did in dids:
        did_hex = did["did_hex"]
        did_int = int(did_hex, 16)
        short = _short_name(did_hex)
        suffix = _sanitize_suffix(did.get("did_name_en", ""))
        plain_data_elem_name = f"DemDataElementClass_{short}"
        plain_did_class_name = f"DemDidClass_{short}"
        desc_data_elem_name = f"{plain_data_elem_name}_{suffix}" if suffix else plain_data_elem_name
        desc_did_class_name = f"{plain_did_class_name}_{suffix}" if suffix else plain_did_class_name

        # If a DID with the same identifier already exists, reuse everything.
        existing_did_class_name = did_id_to_short_name.get(did_int)
        if existing_did_class_name is not None:
            did_class_name = existing_did_class_name
            existing_data_elem_name = did_int_to_data_elem_name.get(did_int)
            if existing_data_elem_name is not None:
                skipped.append(
                    f"{plain_data_elem_name} (reusing existing {existing_data_elem_name})"
                )
            else:
                skipped.append(f"{plain_data_elem_name} (reusing existing DID class)")
        else:
            # Create DataElementClass using a descriptive suffix when possible.
            if desc_data_elem_name in existing_short_names:
                # Descriptive name already taken by something else: fall back to plain name.
                data_elem_name = _unique_short_name(
                    existing_short_names, plain_data_elem_name
                )
                skipped.append(
                    f"{desc_data_elem_name} already exists; using {data_elem_name}"
                )
            else:
                data_elem_name = desc_data_elem_name

            _add_data_element_class(
                sub_containers, did, ns, nsmap, module_path,
                short_name=data_elem_name,
            )
            existing_short_names.add(data_elem_name)
            added.append(data_elem_name)

            # Create DID class using a matching descriptive suffix.
            if desc_did_class_name in existing_short_names:
                did_class_name = _unique_short_name(
                    existing_short_names, plain_did_class_name
                )
                skipped.append(
                    f"{desc_did_class_name} already exists; using {did_class_name}"
                )
            else:
                did_class_name = desc_did_class_name

            _add_did_class(
                sub_containers, did, ns, nsmap, module_path,
                short_name=did_class_name,
                data_elem_name=data_elem_name,
            )
            existing_short_names.add(did_class_name)
            did_id_to_short_name[did_int] = did_class_name
            did_int_to_data_elem_name[did_int] = data_elem_name
            added.append(did_class_name)

        # Freeze-frame reference
        ref_target = f"{module_path}/DemGeneral/{did_class_name}"
        if ref_target in existing_ref_targets:
            skipped.append(f"{ff_class_name} -> {did_class_name}")
        else:
            _add_ref(ff_refs, ref_def, ref_target, ns, nsmap)
            existing_ref_targets.add(ref_target)
            added_refs += 1

    _write_tree(tree, target)
    _verify_merge(target, original_short_names, nsmap)
    return skipped, added, added_refs


def _verify_merge(target: pathlib.Path, original_short_names: set, nsmap: Dict[str, str]) -> None:
    from lxml import etree
    tree = etree.parse(str(target))
    root = tree.getroot()
    dem_general = _find_dem_general(root, nsmap)
    sub_containers = dem_general.find("a:SUB-CONTAINERS", nsmap)
    if sub_containers is None:
        raise RuntimeError("SUB-CONTAINERS missing after merge")
    current_short_names = {
        _text(child.find("a:SHORT-NAME", nsmap))
        for child in sub_containers
        if child.tag == "{%s}ECUC-CONTAINER-VALUE" % nsmap["a"]
    }
    missing = original_short_names - current_short_names
    if missing:
        raise RuntimeError(f"Merge verification failed: existing containers were removed: {sorted(missing)}")


def _map_existing_did_identifiers(sub_containers: etree._Element, ns: str,
                                   nsmap: Dict[str, str]) -> Dict[int, str]:
    """Return mapping from DemDidIdentifier VALUE to parent SHORT-NAME."""
    result: Dict[int, str] = {}
    did_id_def = "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDidClass/DemDidIdentifier"
    for child in sub_containers.findall("a:ECUC-CONTAINER-VALUE", nsmap):
        sn = child.find("a:SHORT-NAME", nsmap)
        if sn is None or not sn.text or not sn.text.startswith("DemDidClass_"):
            continue
        for pval in child.findall(".//a:ECUC-NUMERICAL-PARAM-VALUE", nsmap):
            defref = pval.find("a:DEFINITION-REF", nsmap)
            if defref is None or defref.text != did_id_def:
                continue
            value_elem = pval.find("a:VALUE", nsmap)
            if value_elem is None or value_elem.text is None:
                continue
            try:
                result[int(value_elem.text)] = sn.text
            except ValueError:
                pass
            break
    return result


def _map_existing_data_elements_by_did_ref(
    sub_containers: etree._Element, ns: str, nsmap: Dict[str, str],
    did_id_to_short_name: Dict[int, str],
) -> Dict[int, str]:
    """Return mapping from DemDidIdentifier VALUE to referenced DemDataElementClass SHORT-NAME.

    For each existing DemDidClass, follow its DemDidDataElementClassRef to find
    the DemDataElementClass container that actually provides the data.  This
    lets the merger reuse existing descriptive-suffix DataElementClass containers
    (e.g. DemDataElementClass_0x1100_WheelSpeed) instead of creating duplicates.
    """
    result: Dict[int, str] = {}
    ref_def = "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDidClass/DemDidDataElementClassRef"

    for did_int, did_class_name in did_id_to_short_name.items():
        did_class = None
        for child in sub_containers.findall("a:ECUC-CONTAINER-VALUE", nsmap):
            sn = child.find("a:SHORT-NAME", nsmap)
            if sn is not None and sn.text == did_class_name:
                did_class = child
                break
        if did_class is None:
            continue

        rvalues = did_class.find("a:REFERENCE-VALUES", nsmap)
        if rvalues is None:
            continue

        for rv in rvalues.findall("a:ECUC-REFERENCE-VALUE", nsmap):
            dref = rv.find("a:DEFINITION-REF", nsmap)
            if dref is None or dref.text != ref_def:
                continue
            vref = rv.find("a:VALUE-REF", nsmap)
            if vref is None or not vref.text:
                continue
            # VALUE-REF is a full path like /RB/UBK/Project/.../DemDataElementClass_0x1100_WheelSpeed
            result[did_int] = vref.text.rsplit("/", 1)[-1]
            break

    return result


def _sanitize_suffix(name: str) -> str:
    """Derive a CamelCase descriptive suffix from a DID English name.

    Stop words and short/empty tokens are removed.  The result is suitable for
    appending to SHORT-NAMEs such as DemDidClass_0x1100_WheelSpeed.
    """
    if not name:
        return ""
    tokens = re.split(r"[^a-zA-Z0-9]+", name)
    filtered: List[str] = []
    for token in tokens:
        if not token or len(token) <= 1:
            continue
        lower = token.lower()
        if lower in _STOP_WORDS:
            continue
        filtered.append(token[0].upper() + token[1:])
    return "".join(filtered)


def _unique_short_name(existing: set, base: str) -> str:
    """Return a SHORT-NAME that is not already in use."""
    if base not in existing:
        return base
    idx = 2
    while f"{base}_{idx}" in existing:
        idx += 1
    return f"{base}_{idx}"


def _find_dem_general(root: etree._Element, nsmap: Dict[str, str]) -> etree._Element:
    for gen in root.xpath('.//a:ECUC-CONTAINER-VALUE/a:SHORT-NAME[text()="DemGeneral"]', namespaces=nsmap):
        return gen.getparent()
    raise RuntimeError("DemGeneral container not found in ARXML")


def _module_path(root: etree._Element, nsmap: Dict[str, str]) -> str:
    """Return the absolute path prefix for ECUC container VALUE-REFs."""
    for modconf in root.xpath(".//a:ECUC-MODULE-CONFIGURATION-VALUES", namespaces=nsmap):
        sn = modconf.find("a:SHORT-NAME", nsmap)
        if sn is None or sn.text != "Dem":
            continue
        parts = []
        node = modconf
        ns = nsmap["a"]
        autosar_tag = "{%s}AUTOSAR" % ns
        while node is not None and node.tag != autosar_tag:
            sn2 = node.find("a:SHORT-NAME", nsmap)
            if sn2 is not None and sn2.text:
                parts.insert(0, sn2.text)
            node = node.getparent()
        return "/" + "/".join(parts)
    raise RuntimeError("Dem ECUC-MODULE-CONFIGURATION-VALUES not found")


def _find_or_create_container(parent: etree._Element, short_name: str, ns: str,
                              nsmap: Dict[str, str], definition_ref: str,
                              dest: str) -> etree._Element:
    for child in parent:
        if child.tag != "{%s}ECUC-CONTAINER-VALUE" % ns:
            continue
        sn = child.find("a:SHORT-NAME", nsmap)
        if sn is not None and sn.text == short_name:
            return child
    child = etree.SubElement(parent, "{%s}ECUC-CONTAINER-VALUE" % ns)
    sn = etree.SubElement(child, "{%s}SHORT-NAME" % ns)
    sn.text = short_name
    defref = etree.SubElement(child, "{%s}DEFINITION-REF" % ns)
    defref.set("DEST", dest)
    defref.text = definition_ref
    return child


def _add_data_element_class(parent: etree._Element, did: Dict[str, Any], ns: str,
                            nsmap: Dict[str, str], module_path: str,
                            short_name: Optional[str] = None) -> None:
    short = _short_name(did["did_hex"])
    size = did.get("size_bytes", 1)
    read_fnc = did.get("read_fnc", f"RBAPLCUST_{did['did_hex'].replace('0x', '')}_ReadData")

    if short_name is None:
        short_name = f"DemDataElementClass_{short}"

    # Derive an inner container short-name that matches the outer style.
    if short_name.startswith("DemDataElementClass_"):
        inner_short = "DemExternalCSDataElementClass_" + short_name[len("DemDataElementClass_"):]
    else:
        inner_short = f"DemExternalCSDataElementClass_{short}"

    outer = etree.SubElement(parent, "{%s}ECUC-CONTAINER-VALUE" % ns)
    sn = etree.SubElement(outer, "{%s}SHORT-NAME" % ns)
    sn.text = short_name
    defref = etree.SubElement(outer, "{%s}DEFINITION-REF" % ns)
    defref.set("DEST", "ECUC-CHOICE-CONTAINER-DEF")
    defref.text = "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDataElementClass"

    sub_containers = etree.SubElement(outer, "{%s}SUB-CONTAINERS" % ns)
    inner = etree.SubElement(sub_containers, "{%s}ECUC-CONTAINER-VALUE" % ns)
    sn2 = etree.SubElement(inner, "{%s}SHORT-NAME" % ns)
    sn2.text = inner_short
    defref2 = etree.SubElement(inner, "{%s}DEFINITION-REF" % ns)
    defref2.set("DEST", "ECUC-PARAM-CONF-CONTAINER-DEF")
    defref2.text = "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDataElementClass/DemExternalCSDataElementClass"

    pvalues = etree.SubElement(inner, "{%s}PARAMETER-VALUES" % ns)
    _add_textual_param(pvalues, ns,
                       "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDataElementClass/DemExternalCSDataElementClass/DemDataElementReadFnc",
                       "ECUC-FUNCTION-NAME-DEF", read_fnc)
    _add_numerical_param(pvalues, ns,
                         "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDataElementClass/DemExternalCSDataElementClass/DemDataElementUsePort",
                         "ECUC-BOOLEAN-PARAM-DEF", "false")
    _add_numerical_param(pvalues, ns,
                         "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDataElementClass/DemExternalCSDataElementClass/DemDataElementProvideMonitorData",
                         "ECUC-BOOLEAN-PARAM-DEF", "false")
    _add_numerical_param(pvalues, ns,
                         "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDataElementClass/DemExternalCSDataElementClass/DemDataElementArraySize",
                         "ECUC-INTEGER-PARAM-DEF", str(size))


def _add_did_class(parent: etree._Element, did: Dict[str, Any], ns: str,
                   nsmap: Dict[str, str], module_path: str,
                   short_name: Optional[str] = None,
                   data_elem_name: Optional[str] = None) -> None:
    short = _short_name(did["did_hex"])
    did_int = int(did["did_hex"], 16)

    if short_name is None:
        short_name = f"DemDidClass_{short}"
    if data_elem_name is None:
        data_elem_name = f"DemDataElementClass_{short}"

    outer = etree.SubElement(parent, "{%s}ECUC-CONTAINER-VALUE" % ns)
    sn = etree.SubElement(outer, "{%s}SHORT-NAME" % ns)
    sn.text = short_name
    defref = etree.SubElement(outer, "{%s}DEFINITION-REF" % ns)
    defref.set("DEST", "ECUC-PARAM-CONF-CONTAINER-DEF")
    defref.text = "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDidClass"

    pvalues = etree.SubElement(outer, "{%s}PARAMETER-VALUES" % ns)
    _add_numerical_param(pvalues, ns,
                         "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDidClass/DemDidIdentifier",
                         "ECUC-INTEGER-PARAM-DEF", str(did_int))

    rvalues = etree.SubElement(outer, "{%s}REFERENCE-VALUES" % ns)
    _add_ref(rvalues,
             "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemDidClass/DemDidDataElementClassRef",
             f"{module_path}/DemGeneral/{data_elem_name}", ns, nsmap)


def _add_freeze_frame_rec_num_class(parent: etree._Element, doc: Dict[str, Any],
                                    ns: str, nsmap: Dict[str, str]) -> None:
    short_name = doc["freeze_frame_rec_num_class"]
    value = doc.get("type_of_freeze_frame_record_numeration", "FF_RECNUM_CONFIGURED")

    outer = etree.SubElement(parent, "{%s}ECUC-CONTAINER-VALUE" % ns)
    sn = etree.SubElement(outer, "{%s}SHORT-NAME" % ns)
    sn.text = short_name
    defref = etree.SubElement(outer, "{%s}DEFINITION-REF" % ns)
    defref.set("DEST", "ECUC-PARAM-CONF-CONTAINER-DEF")
    defref.text = "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemFreezeFrameRecNumClass"

    pvalues = etree.SubElement(outer, "{%s}PARAMETER-VALUES" % ns)
    _add_textual_param(pvalues, ns,
                       "/AUTOSAR_Dem/EcucModuleDefs/Dem/DemGeneral/DemFreezeFrameRecNumClass/DemTypeOfFreezeFrameRecordNumeration",
                       "ECUC-ENUMERATION-PARAM-DEF", value)


def _add_textual_param(parent: etree._Element, ns: str, definition: str,
                       dest: str, value: str) -> None:
    pv = etree.SubElement(parent, "{%s}ECUC-TEXTUAL-PARAM-VALUE" % ns)
    dr = etree.SubElement(pv, "{%s}DEFINITION-REF" % ns)
    dr.set("DEST", dest)
    dr.text = definition
    val = etree.SubElement(pv, "{%s}VALUE" % ns)
    val.text = value


def _add_numerical_param(parent: etree._Element, ns: str, definition: str,
                         dest: str, value: str) -> None:
    pv = etree.SubElement(parent, "{%s}ECUC-NUMERICAL-PARAM-VALUE" % ns)
    dr = etree.SubElement(pv, "{%s}DEFINITION-REF" % ns)
    dr.set("DEST", dest)
    dr.text = definition
    val = etree.SubElement(pv, "{%s}VALUE" % ns)
    val.text = value


def _add_ref(parent: etree._Element, definition: str, target: str, ns: str,
             nsmap: Dict[str, str]) -> None:
    rv = etree.SubElement(parent, "{%s}ECUC-REFERENCE-VALUE" % ns)
    dr = etree.SubElement(rv, "{%s}DEFINITION-REF" % ns)
    dr.set("DEST", "ECUC-REFERENCE-DEF")
    dr.text = definition
    vr = etree.SubElement(rv, "{%s}VALUE-REF" % ns)
    vr.set("DEST", "ECUC-CONTAINER-VALUE")
    vr.text = target


def _write_tree(tree: "etree._ElementTree", target: pathlib.Path) -> None:
    # Strip whitespace-only text/tail nodes so etree.indent can format the
    # whole tree uniformly, including newly added elements, while preserving
    # the original document structure and content.
    root = tree.getroot()
    for elem in root.iter():
        if elem.text is not None and not elem.text.strip():
            elem.text = None
        if elem.tail is not None and not elem.tail.strip():
            elem.tail = None
    etree.indent(tree, space="  ")

    tree.write(str(target), xml_declaration=True, encoding="UTF-8")
    # Restore double quotes in XML declaration to match AUTOSAR convention.
    text = target.read_text(encoding="utf-8")
    if text.startswith("<?xml version='"):
        text = '<?xml version="1.0" encoding="UTF-8"?>' + text[len("<?xml version='1.0' encoding='UTF-8'?>"):]
        target.write_text(text, encoding="utf-8")


def _text(elem: Optional[etree._Element]) -> str:
    return elem.text if elem is not None else ""


def _short_name(did_hex: str) -> str:
    return f"0x{int(did_hex, 16):04X}"


def _report(target: pathlib.Path, product_type: str, dids: List[Dict[str, Any]],
            skipped: List[str], added: List[str], added_refs: int) -> str:
    lines = [
        f"Merged freeze-frame config into {target}",
        f"Product: {product_type}",
        f"DIDs processed: {len(dids)}",
        f"Containers added: {len(added)}",
        f"Freeze-frame refs added: {added_refs}",
        f"Skipped (already present): {len(skipped)}",
    ]
    if added:
        lines.append("Added containers:")
        for a in added:
            lines.append(f"  + {a}")
    if skipped:
        lines.append("Skipped (skip-on-conflict):")
        for s in skipped:
            lines.append(f"  = {s}")
    return "\n".join(lines) + "\n"
