#!/usr/bin/env python3
"""
ARXML Generator - Phase 2

Generates AUTOSAR ARXML configuration from FSCS requirement documents.

Input: 
  - outputs/fscs/FSCS_22.txt (Service 22 - ReadDataByIdentifier)
  - outputs/fscs/FSCS_2E.txt (Service 2E - WriteDataByIdentifier)
Output: 
  - outputs/arxml/DID_Config.arxml (AUTOSAR Dcm configuration)
  - outputs/arxml/validation_report.txt (Validation report)

Follows AUTOSAR DCM (Diagnostic Communication Manager) specification.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

# Allow ``from generate_arxml import ARXMLGenerator`` to resolve when
# the file is loaded by a sibling script (the v1.20.0 cull removed
# the standalone ``python scripts/generate_arxml.py`` entry point;
# this stays as a package-style file the orchestrator imports).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_encoding import reconfigure_stdio_utf8  # noqa: E402
from templating import render as _render  # noqa: E402
from fscs import FSCSDocument, load_fscs  # noqa: E402

reconfigure_stdio_utf8()
from implementation.arxml_merge import merge_arxml  # noqa: E402
# v1.22.0: ARXML mirror destination flows through ``resolve_mirror_path``
# (imported lazily inside ``_write_to_project_tree``) so per-PT
# ``paths.per_product`` overrides / skip sentinels are honoured. The
# legacy ``resolve_path`` direct import is no longer needed here.
from implementation.safety import guarded_project_write  # noqa: E402


@dataclass
class DIDInfo:
    """Parsed DID information from FSCS"""
    did_hex: str
    did_name: str
    data_type: str
    storage_pos: str
    size_bytes: str
    rw_state: str  # 'R' or 'RW'
    nvm_item: str = ""
    security_level: str = "L0"  # Default: L0
    sessions: List[str] = field(default_factory=list)  # Default: ['defaultSession']
    validation_errors: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        if not self.sessions:
            self.sessions = ['defaultSession']
        if not self.validation_errors:
            self.validation_errors = []


class ARXMLGenerator:
    """Generate AUTOSAR ARXML configuration for Dcm module"""
    
    # Data type mapping from FSCS to ARXML
    TYPE_MAPPING = {
        'ASCII': 'UINT8_N',
        'Unsigned': 'UINT8_N',
        'Texttable': 'UINT8_N',
        'Bytefield': 'UINT8_N',
        'Signed': 'UINT8_N',
        'HEX': 'UINT8_N',
        'enum': 'UINT8_N',
        'Linear': 'UINT8_N',
        'Identity': 'UINT8_N',
    }
    
    def __init__(self, template_dir: Optional[Path] = None,
                 config: Optional[Dict[str, Any]] = None):
        # ``template_dir`` is accepted for backward compatibility only; the
        # generator no longer loads any template from disk (XML is emitted
        # from Jinja2 templates under scripts/templates/arxml/). The
        # parameter is ignored.
        _ = template_dir
        self.config = config or {}
    
    def hex_to_decimal(self, hex_str: str) -> int:
        """Convert hexadecimal string to decimal"""
        hex_clean = hex_str.replace('0x', '').replace('$', '')
        return int(hex_clean, 16)
    
    def clean_name(self, name: str) -> str:
        """Clean name for use in identifiers (capitalize first letter)."""
        if not name:
            return "Unknown"
        cleaned = re.sub(r'[^a-zA-Z0-9_]', '', name)
        if not cleaned:
            return "Unknown"
        return cleaned[0].upper() + cleaned[1:]
    
    def _document_to_dids(
        self,
        document: FSCSDocument,
        *,
        verbose: bool = True,
        product_type: Optional[str] = None,
    ) -> Tuple[List[DIDInfo], List[Dict]]:
        """Project an ``FSCSDocument`` onto ARXML's ``DIDInfo`` shape.

        Mirrors the contract of :meth:`parse_both_fscs`: returns the
        same ``(valid_dids, validation_report)`` tuple, with hex-sorted
        order. Status taxonomy:

        * ``SUCCESS``     -- emitted into ARXML.
        * ``DESELECTED``  -- both services ``used=False``; operator
          chose to drop. Not a failure.
        * ``ERROR``       -- write-only DID (only $2E used); rejected
          per the AUTOSAR DCM convention.
        * ``SKIPPED``     -- compliance violation on RW (write side
          missing extendedDiagnosticSession or non-L1 security).
        * ``OUT_OF_SCOPE`` (v1.13.0 / schema 1.4; field renamed in
          v1.16.0 / schema 1.5; semantics adjusted v1.21.0) -- DID's
          per-DID ``product_type`` does not match the current
          fan-out iteration's target. Not a failure: the DID still
          surfaces in the *other* product's pass when Phase 2
          iterates the work-set (Phase 2 calls this method once per
          product in :func:`scripts.fscs.compute_workset`). v1.24.0
          dropped the v1.23.0 multi-scope ``accepted_scopes`` knob:
          the Phase-2 ESPCL → ESP alias is now a path alias only
          (ESPCL still iterates with its own DIDs but writes into
          ``cfg/ESP/Dcm_..._ESPCL.arxml``), not a DID fold-in, so
          per-iteration filtering is back to a single target.

        :param verbose: When ``True`` (default), per-DID OK / SKIP
            lines print to stdout. When ``False``, the function is
            silent -- used by ``review_arxml.ARXMLReviewer``
            (v1.13.0 differential B) so re-running the classifier
            inside the reviewer doesn't duplicate the generator's
            console output.
        :param product_type: The current fan-out iteration's target
            product. DIDs whose per-DID ``product_type`` doesn't
            match (case-insensitive) and isn't the special
            ``"Common"`` token are stamped ``OUT_OF_SCOPE`` and
            excluded from this product's ARXML. ``None`` preserves
            the legacy v1.12.x posture: every DID is in-scope
            regardless of its ``product_type`` tag (used by
            review-only consumers that don't fan out).
        """
        _emit = print if verbose else (lambda *_args, **_kwargs: None)
        target_scope = (product_type or "").strip().lower()
        validation_report: List[Dict] = []
        valid_dids: List[DIDInfo] = []

        sorted_entries = sorted(document.dids, key=lambda d: d.did_hex)
        for entry in sorted_entries:
            did_hex = f"0x{entry.did_hex}"
            report_entry = {
                "did_hex": did_hex,
                "did_name": entry.did_name,
                "status": "SUCCESS",
                "errors": [],
            }

            # v1.13.0 (schema 1.4) product-scope filter, renamed to
            # ``product_type`` in v1.16.0 (schema 1.5); semantics
            # adjusted in v1.21.0: ``product_type`` is now the
            # current fan-out iteration's target rather than a
            # global CLI build target. v1.23.0 briefly generalised
            # this to a set (for the ESPCL → ESP fold-in alias)
            # but v1.24.0 reverted to single-target since the
            # alias is now a path alias only (ESPCL still iterates
            # with its own DID set; only the output paths get
            # rewritten). ``"Common"`` (case-insensitive) is the
            # wildcard token that means "applies in every product's
            # build"; it passes the filter the same as an unset
            # (``None``) tag, matching the DOORS-export convention.
            if target_scope:
                entry_scope = (entry.product_type or "").strip().lower()
                if entry_scope and entry_scope != "common" and entry_scope != target_scope:
                    report_entry["status"] = "OUT_OF_SCOPE"
                    report_entry["errors"].append(
                        f"product_type={entry.product_type!r}; this "
                        f"fan-out iteration targets product_type="
                        f"{product_type!r}. The DID will appear in "
                        f"the {entry.product_type!r} iteration's "
                        f"ARXML instead."
                    )
                    validation_report.append(report_entry)
                    _emit(
                        f"  [OOSCOPE] {did_hex} product_type={entry.product_type} "
                        f"(this iter: {product_type})"
                    )
                    continue

            # Operator has toggled this DID off in the xlsx edit table.
            # editor's selection panel (``used=False`` on both
            # services). It's kept in fscs.json as an input mirror,
            # but we deliberately skip emitting it into DID_Config.arxml
            # so the ARXML matches the operator's release scope. Marked
            # DESELECTED (not ERROR) so validation_report.txt reflects
            # the intent rather than flagging a failure.
            if not entry.service_22.effective and not entry.service_2e.effective:
                report_entry["status"] = "DESELECTED"
                report_entry["errors"].append(
                    "Deselected in FSCS editor; excluded from ARXML output."
                )
                validation_report.append(report_entry)
                _emit(f"  [SKIP] {did_hex} deselected by operator")
                continue

            # All subsequent gating uses ``effective`` (supported AND
            # used). The write-only check thus treats "2E used / 22
            # deselected" the same as structural write-only, since
            # emitting write-only ARXML has never been valid.
            if entry.service_2e.effective and not entry.service_22.effective:
                report_entry["status"] = "ERROR"
                report_entry["errors"].append(
                    "DID found only in FSCS_2E.txt, write-only DIDs not supported"
                )
                validation_report.append(report_entry)
                continue

            read = entry.service_22
            read_sessions = list(read.sessions) or ["defaultSession"]
            read_security = (
                read.security_levels[0].level
                if read.security_levels
                else "L0"
            )
            did = DIDInfo(
                did_hex=did_hex,
                did_name=entry.did_name,
                data_type=entry.data_type,
                storage_pos=entry.storage_position,
                size_bytes=str(entry.size_bytes),
                rw_state="R",
                nvm_item=entry.nvm_item,
                security_level=read_security,
                sessions=read_sessions,
                validation_errors=[],
            )

            if entry.service_2e.effective:
                did.rw_state = "RW"
                write = entry.service_2e
                if "extendedDiagnosticSession" not in write.sessions:
                    report_entry["errors"].append(
                        f"Write requires extendedDiagnosticSession, "
                        f"got: {list(write.sessions)}"
                    )
                write_levels = {sl.level for sl in write.security_levels}
                if write_levels != {"L1"}:
                    report_entry["errors"].append(
                        f"Write requires L1 security level, "
                        f"got: {sorted(write_levels) or ['<none>']}"
                    )

            if report_entry["errors"]:
                report_entry["status"] = "SKIPPED"
                _emit(
                    f"  [SKIP] {did_hex} skipped: "
                    f"{', '.join(report_entry['errors'])}"
                )
            else:
                valid_dids.append(did)
                _emit(f"  [OK] {did_hex} ({did.rw_state})")

            validation_report.append(report_entry)

        return valid_dids, validation_report

    def load_dids(
        self,
        fscs_json_path: Path,
        *,
        product_type: Optional[str] = None,
    ) -> Tuple[List[DIDInfo], List[Dict]]:
        """Load Phase 2 inputs from the authoritative ``fscs.json``.

        Part 6 of the governance migration deleted the TXT-parsing
        fallback. Callers must pre-gate on the existence of
        ``fscs_json_path``; missing JSON raises FileNotFoundError via
        :func:`scripts.fscs.load_fscs`.

        :param product_type: Forwarded to :meth:`_document_to_dids`
            so the v1.13.0 product-scope filter applies. ``None``
            preserves v1.12.x behaviour (no filter). v1.24.0 dropped
            the v1.23.0 ``accepted_scopes`` parameter (the Phase-2
            ESPCL → ESP alias is now a path-only alias, not a DID
            fold-in, so single-target filtering is back).
        """
        document = load_fscs(fscs_json=fscs_json_path)
        return self._document_to_dids(document, product_type=product_type)

    def generate_validation_report(
        self,
        report: List[Dict],
        report_anchor: Path,
        *,
        report_path: Optional[Path] = None,
    ):
        """Generate validation report to file (not console).

        v1.27.0: ``report_anchor`` is now the **directory** where the
        report lands (typically ``.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/``).
        Pre-v1.27 callers passed the ARXML file path and relied on
        ``.parent``; we now require the directory directly so the
        report root is unambiguous when the ARXML itself lives in the
        Bosch tree.

        :param report_anchor: Directory under which the default
            ``validation_report.txt`` is written. Ignored when
            ``report_path`` is set.
        :param report_path: Explicit report destination override. The
            Phase-2 fan-out under the ESPCL → ESP path alias has
            multiple iterations writing into the same folder, so the
            orchestrator passes a per-iteration name
            (``validation_report_<suffix>.txt``) to keep the reports
            from clobbering each other.
        """
        lines = []
        lines.append("=" * 80)
        lines.append("ARXML Generation Validation Report")
        lines.append("=" * 80)
        lines.append("")
        
        success_count = sum(1 for r in report if r['status'] == 'SUCCESS')
        skip_count = sum(1 for r in report if r['status'] == 'SKIPPED')
        error_count = sum(1 for r in report if r['status'] == 'ERROR')
        deselect_count = sum(1 for r in report if r['status'] == 'DESELECTED')
        out_of_scope_count = sum(1 for r in report if r['status'] == 'OUT_OF_SCOPE')

        lines.append(f"Total DIDs: {len(report)}")
        lines.append(f"SUCCESS: {success_count}")
        lines.append(f"SKIPPED: {skip_count}")
        lines.append(f"ERROR: {error_count}")
        # DESELECTED is a separate, non-failure bucket: the operator
        # chose to exclude these via the FSCS editor so they're not
        # bugs to fix but a scope decision worth surfacing.
        lines.append(f"DESELECTED: {deselect_count}")
        # OUT_OF_SCOPE (v1.13.0; semantics v1.21.0): the DID is
        # tagged for a different product than this fan-out iteration
        # targets. Per the v1.21.0 fan-out model, the same DID will
        # land under SUCCESS in its own iteration's report. Surfaced
        # separately so the per-product report still tells you which
        # DIDs were intentionally absent vs accidentally missing.
        lines.append(f"OUT_OF_SCOPE: {out_of_scope_count}")
        lines.append("")

        # List all DIDs with status
        lines.append("DID Processing Summary:")
        lines.append("-" * 80)
        status_symbol_map = {
            "SUCCESS": "[OK]",
            "SKIPPED": "[SKIP]",
            "ERROR": "[ERR]",
            "DESELECTED": "[DESEL]",
            "OUT_OF_SCOPE": "[SCOPE]",
        }
        for entry in report:
            status_symbol = status_symbol_map.get(entry['status'], "[?]")
            lines.append(f"{status_symbol} {entry['did_hex']} - {entry['did_name'][:50]:<50} [{entry['status']}]")

        lines.append("")

        # List failed DIDs with details (DESELECTED aren't "failures",
        # skip them here -- the summary row above is enough context).
        if skip_count > 0 or error_count > 0:
            lines.append("Failed DIDs Details:")
            lines.append("-" * 80)
            for entry in report:
                if entry['status'] != 'SUCCESS':
                    lines.append(f"\n{entry['did_hex']} - {entry['did_name']}")
                    lines.append(f"Status: {entry['status']}")
                    for error in entry['errors']:
                        lines.append(f"  - {error}")
        
        # v1.27.0: ``report_anchor`` is the directory holding the report.
        # An explicit ``report_path`` (per-iteration override) wins; this
        # is how the Phase-2 ESPCL → ESP fan-out keeps co-tenanted
        # reports from clobbering each other.
        if report_path is None:
            report_path = report_anchor / 'validation_report.txt'
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('\n'.join(lines), encoding='utf-8')
        print(f"\nValidation report saved to: {report_path}")
    
    def generate_dcm_dsp_data(self, did: DIDInfo) -> Tuple[str, str]:
        """Generate DcmDspData container XML."""
        did_id = did.did_hex.replace('0x', '').upper()
        clean_name = self.clean_name(did.did_name)

        short_name = f"RBAPLCUST_{did_id}_{clean_name}Data"
        read_func = f"RBAPLCUST_{did_id}_{clean_name}_ReadData"
        write_func = f"RBAPLCUST_{did_id}_{clean_name}_WriteData"

        arxml_type = self.TYPE_MAPPING.get(did.data_type, 'UINT8_N')

        try:
            size_bits = int(did.size_bytes) * 8
        except (ValueError, TypeError):
            size_bits = 8

        has_write = did.rw_state == 'RW'

        xml = _render("arxml/dcm_dsp_data.j2", {
            "short_name": short_name,
            "read_func": read_func,
            "write_func": write_func,
            "size_bits": size_bits,
            "arxml_type": arxml_type,
            "has_write": has_write,
        }).rstrip('\n')

        return xml, short_name
    
    def generate_dcm_dsp_did(self, did: DIDInfo, data_ref_name: str) -> str:
        """Generate DcmDspDid container XML."""
        did_id = self.hex_to_decimal(did.did_hex)
        did_container_name = f"{data_ref_name}Did"
        has_write = did.rw_state == 'RW'

        return _render("arxml/dcm_dsp_did.j2", {
            "did_container_name": did_container_name,
            "did_id": did_id,
            "data_ref_name": data_ref_name,
            "has_write": has_write,
        }).rstrip('\n')
    
    def generate_dcm_dsp_did_info(self) -> str:
        """Generate DcmDspDidInfo containers - HARD CODED"""
        # Read-only DidInfo - HARD CODED
        read_info = '''                                <ECUC-CONTAINER-VALUE>
                                  <SHORT-NAME>DcmDspDidInfo_Read</SHORT-NAME>
                                  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo</DEFINITION-REF>
                                  <PARAMETER-VALUES>
                                    <ECUC-NUMERICAL-PARAM-VALUE>
                                      <DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidDynamicallyDefined</DEFINITION-REF>
                                      <VALUE>false</VALUE>
                                    </ECUC-NUMERICAL-PARAM-VALUE>
                                  </PARAMETER-VALUES>
                                  <SUB-CONTAINERS>
                                    <ECUC-CONTAINER-VALUE>
                                      <SHORT-NAME>DcmDspDidRead</SHORT-NAME>
                                      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidRead</DEFINITION-REF>
                                    </ECUC-CONTAINER-VALUE>
                                  </SUB-CONTAINERS>
                                </ECUC-CONTAINER-VALUE>'''
        
        # Read/Write DidInfo - HARD CODED
        rw_info = '''                                <ECUC-CONTAINER-VALUE>
                                  <SHORT-NAME>DcmDspDidInfo_ReadAndWrite</SHORT-NAME>
                                  <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo</DEFINITION-REF>
                                  <PARAMETER-VALUES>
                                    <ECUC-NUMERICAL-PARAM-VALUE>
                                      <DEFINITION-REF DEST="ECUC-BOOLEAN-PARAM-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidDynamicallyDefined</DEFINITION-REF>
                                      <VALUE>false</VALUE>
                                    </ECUC-NUMERICAL-PARAM-VALUE>
                                  </PARAMETER-VALUES>
                                  <SUB-CONTAINERS>
                                    <ECUC-CONTAINER-VALUE>
                                      <SHORT-NAME>DcmDspDidWrite</SHORT-NAME>
                                      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidWrite</DEFINITION-REF>
                                      <REFERENCE-VALUES>
                                        <ECUC-REFERENCE-VALUE>
                                          <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidWrite/DcmDspDidWriteSessionRef</DEFINITION-REF>
                                          <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspSession/EXTENDED_DIAGNOSTIC_SESSION</VALUE-REF>
                                        </ECUC-REFERENCE-VALUE>
                                        <ECUC-REFERENCE-VALUE>
                                          <DEFINITION-REF DEST="ECUC-REFERENCE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidWrite/DcmDspDidWriteSecurityLevelRef</DEFINITION-REF>
                                          <VALUE-REF DEST="ECUC-CONTAINER-VALUE">/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp/DcmDspSecurity/DCM_SEC_LEV_L1</VALUE-REF>
                                        </ECUC-REFERENCE-VALUE>
                                      </REFERENCE-VALUES>
                                    </ECUC-CONTAINER-VALUE>
                                    <ECUC-CONTAINER-VALUE>
                                      <SHORT-NAME>DcmDspDidRead</SHORT-NAME>
                                      <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp/DcmDspDidInfo/DcmDspDidRead</DEFINITION-REF>
                                    </ECUC-CONTAINER-VALUE>
                                  </SUB-CONTAINERS>
                                </ECUC-CONTAINER-VALUE>'''
        
        return read_info + '\n' + rw_info
    
    def generate_from_dids(self, dids: List[DIDInfo], output_path: Path,
                           product_type: Optional[str] = None,
                           dry_run: bool = False) -> Dict[str, Any]:
        """Generate complete ARXML file from list of DIDInfo objects.

        Contract:

        * ``output_path`` is the **Bosch project-tree target** for the
          merged ARXML; there is no local source mirror. The fan-out
          caller in :func:`pipeline.run_phase2` computes the project
          target via
          :func:`scripts.implementation.paths.resolve_mirror_path`
          and passes it here.
        * The merge is skip-on-conflict (existing ``SHORT-NAME``
          containers win); nothing is ever overwritten.
        """
        print(f"\nGenerating ARXML for {len(dids)} valid DIDs...")
        
        # Generate containers
        dsp_data_containers = []
        dsp_did_containers = []
        did_ref_map = {}
        
        for did in dids:
            container_xml, data_ref_name = self.generate_dcm_dsp_data(did)
            dsp_data_containers.append(container_xml)
            did_ref_map[did.did_hex] = data_ref_name
        
        for did in dids:
            data_ref_name = did_ref_map[did.did_hex]
            container_xml = self.generate_dcm_dsp_did(did, data_ref_name)
            dsp_did_containers.append(container_xml)
        
        # Generate DidInfo containers
        dsp_did_info = self.generate_dcm_dsp_did_info()
        
        # Combine all containers: Data first, then DidInfo, then Did
        all_containers = '\n'.join(dsp_data_containers + [dsp_did_info] + dsp_did_containers)
        
        # Generate complete ARXML
        arxml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<AUTOSAR xmlns="http://autosar.org/schema/r4.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://autosar.org/schema/r4.0 AUTOSAR_00048.xsd">
  <AR-PACKAGES>
    <AR-PACKAGE>
      <SHORT-NAME>RB</SHORT-NAME>
      <AR-PACKAGES>
        <AR-PACKAGE>
          <SHORT-NAME>UBK</SHORT-NAME>
          <AR-PACKAGES>
            <AR-PACKAGE>
              <SHORT-NAME>Project</SHORT-NAME>
              <AR-PACKAGES>
                <AR-PACKAGE>
                  <SHORT-NAME>EcucModuleConfigurationValuess</SHORT-NAME>
                  <ELEMENTS>
                    <ECUC-MODULE-CONFIGURATION-VALUES>
                      <SHORT-NAME>Dcm</SHORT-NAME>
                      <DEFINITION-REF DEST="ECUC-MODULE-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm</DEFINITION-REF>
                      <CONTAINERS>
                        <ECUC-CONTAINER-VALUE>
                          <SHORT-NAME>DcmConfigSet</SHORT-NAME>
                          <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet</DEFINITION-REF>
                          <SUB-CONTAINERS>
                            <ECUC-CONTAINER-VALUE>
                              <SHORT-NAME>DcmDsp</SHORT-NAME>
                              <DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">/AUTOSAR_Dcm/EcucModuleDefs/Dcm/DcmConfigSet/DcmDsp</DEFINITION-REF>
                              <SUB-CONTAINERS>
{all_containers}
                              </SUB-CONTAINERS>
                            </ECUC-CONTAINER-VALUE>
                          </SUB-CONTAINERS>
                        </ECUC-CONTAINER-VALUE>
                      </CONTAINERS>
                    </ECUC-MODULE-CONFIGURATION-VALUES>
                  </ELEMENTS>
                </AR-PACKAGE>
              </AR-PACKAGES>
            </AR-PACKAGE>
          </AR-PACKAGES>
        </AR-PACKAGE>
      </AR-PACKAGES>
    </AR-PACKAGE>
  </AR-PACKAGES>
</AUTOSAR>'''
        
        # v1.27.0: project tree is the sole sink. ``output_path`` IS
        # the Bosch-tree target the caller resolved via
        # :func:`scripts.implementation.paths.resolve_mirror_path`;
        # the generator no longer mirrors into ``outputs/arxml/...``.
        project_stats = self._write_to_project(
            arxml_content, output_path,
            product_type=product_type,
            dry_run=dry_run,
        )

        read_only_count = sum(1 for did in dids if did.rw_state == 'R')
        read_write_count = sum(1 for did in dids if did.rw_state == 'RW')

        return {
            'total': len(dids),
            'read_only': read_only_count,
            'read_write': read_write_count,
            'output_path': str(output_path),
            **project_stats,
        }

    def _write_to_project(self, arxml_content: str, target: Path,
                          product_type: Optional[str],
                          dry_run: bool) -> Dict[str, Any]:
        """Write / merge generated ARXML into the Bosch project file.

        Contract:

        * ``target`` is the absolute Bosch-tree path the caller
          resolved via :func:`resolve_mirror_path`. We never compute a
          mirror destination here.
        * Skip-on-conflict at the container level: existing
          ``SHORT-NAME`` containers under ``DcmDsp/SUB-CONTAINERS`` are
          preserved; only new containers are spliced in. The merge is
          non-destructive, so there is no rolling backup.
        """
        stats: Dict[str, Any] = {
            'project_target': str(target),
            'project_inserted': 0,
            'project_skipped': 0,
        }

        try:
            if not target.exists():
                if not dry_run:
                    target.parent.mkdir(parents=True, exist_ok=True)
                if guarded_project_write(target, arxml_content, dry_run,
                                         'create ARXML'):
                    print(f"[CREATED] ARXML: {target}")
                return stats

            existing = target.read_text(encoding='utf-8')
            merged, inserted, skipped, names = merge_arxml(existing, arxml_content)
            stats['project_inserted'] = inserted
            stats['project_skipped'] = skipped

            if inserted == 0:
                print(f"[SKIPPED] ARXML merge: all {skipped} containers already "
                      f"present in {target}")
                return stats

            if guarded_project_write(target, merged, dry_run, 'merge ARXML'):
                print(f"[MERGED] ARXML: +{inserted} new, {skipped} skipped -> {target}")
                preview = ', '.join(names[:5])
                if len(names) > 5:
                    preview += f", ... (+{len(names) - 5} more)"
                print(f"           added: {preview}")
        except ValueError as exc:
            print(f"[ERROR] Malformed ARXML at {target}: {exc}; skipping write.")
        except OSError as exc:
            print(f"[ERROR] Failed to write ARXML to {target}: {exc}")
        return stats
    
    def generate(self, output_path: Path,
                 *,
                 fscs_json_path: Path,
                 product_type: Optional[str] = None,
                 validation_report_path: Optional[Path] = None,
                 report_dir: Optional[Path] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
        """Generate the complete ARXML file from ``fscs.json``.

        Contract:

        * ``output_path`` is the absolute Bosch-tree target the caller
          resolved via :func:`resolve_mirror_path`; there is no local
          source mirror.
        * The merge is non-destructive (existing ``SHORT-NAME``
          containers win); skip-on-conflict.
        * Validation reports land in ``report_dir`` (typically
          ``.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/``); when ``report_dir``
          is ``None`` we fall back to ``output_path.parent`` so legacy
          callers still work, but ``pipeline.run_phase2`` always
          passes the report root explicitly.

        :param validation_report_path: Optional per-iteration report
            path override (used by the fan-out so ESPCL→ESP co-tenants
            don't share a single ``validation_report.txt``).
        :param report_dir: Where the reports land. When ``None`` and
            ``validation_report_path`` is also ``None``, defaults to
            ``output_path.parent``.
        """
        print("=" * 60)
        print("Phase 2: Generating ARXML configuration (project-tree sink)")
        print("=" * 60)
        if dry_run:
            print("Dry Run:      ON (project-tree writes will be skipped)")

        valid_dids, validation_report = self.load_dids(
            fscs_json_path=fscs_json_path,
            product_type=product_type,
        )

        # Report path: explicit override wins; else fall back to a
        # ``validation_report.txt`` in ``report_dir`` (the pipeline's
        # outputs anchor). Legacy callers without ``report_dir`` keep
        # working via ``output_path.parent``.
        anchor = report_dir if report_dir is not None else output_path.parent
        self.generate_validation_report(
            validation_report, anchor,
            report_path=validation_report_path,
        )

        if not valid_dids:
            print("\n[WARNING] No valid DIDs to process!")
            return {
                'total': 0,
                'read_only': 0,
                'read_write': 0,
                'output_path': str(output_path),
                'validation_report': validation_report
            }

        stats = self.generate_from_dids(
            valid_dids, output_path,
            product_type=product_type,
            dry_run=dry_run,
        )
        stats['validation_report'] = validation_report

        return stats


# v1.20.0: standalone ``python scripts/generate_arxml.py ...`` was
# removed. The Phase 2 entry point is now the single CLI in
# ``pipeline.py --phase arxml``, which imports ``ARXMLGenerator``
# directly. The previous standalone main() carried its own argparse
# (a duplicate maintenance surface) plus a v1.16.0-stale read of
# ``config['project']['product_type']`` that schema 2.0 forbids.
# ``ARXMLGenerator`` and the dataclasses defined above remain
# importable for tests and downstream tooling.
