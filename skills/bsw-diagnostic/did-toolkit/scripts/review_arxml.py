#!/usr/bin/env python3
"""ARXML Content Review.

Cross-checks ``outputs/arxml/DID_Config.arxml`` against the Phase 1
``outputs/fscs/fscs.json`` (authoritative DID catalog). This
complements the in-file ``validation_report.txt`` which only reports
generation-side stats.

After the Part 6 cleanup this reviewer no longer reads
``inputs/*.json`` directly -- Phase 1's ``fscs.json`` is the single
source of truth for the expected DID set so ARXML and the generated
C stay in lock-step with the FSCS content.

Checks performed
----------------

* **Container coverage** : every effective DID (``supported_by_ecu=Y``)
  has a matching ``DcmDspData`` and ``DcmDspDid`` container in the XML.
* **Identifier mapping** : ``DcmDspDidIdentifier`` decimal value equals
  ``int(did_hex, 16)``.
* **Data size** : ``DcmDspDataSize`` (bits) equals ``size_bytes * 8``.
* **DidInfo ref** : RW DIDs point at ``DcmDspDidInfo_ReadAndWrite``;
  read-only DIDs point at ``DcmDspDidInfo_Read``.
* **AR-Package layout** : mandatory wrapper path
  ``/RB/UBK/Project/EcucModuleConfigurationValuess/Dcm/DcmConfigSet/DcmDsp``
  exists exactly once.
* **Function hooks** : RW DIDs reference
  ``RBAPLCUST_<HEX>_<Name>_ReadData`` AND ``_WriteData``;
  read-only DIDs reference only ``_ReadData``.

Usage
-----

::

    python scripts/review_arxml.py \\
        --arxml outputs/arxml/DID_Config.arxml \\
        --fscs-json outputs/fscs/fscs.json \\
        --output outputs/arxml/arxml_review_report.txt

``pipeline.py`` invokes :func:`run_review` after Phase 2 so the CLI and
pipeline paths share the same orchestration (same pattern as
``review_fscs.run_review`` and ``review_impl.run_review``).
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_encoding import reconfigure_stdio_utf8  # noqa: E402
from fscs import load_fscs, to_review_dicts  # noqa: E402

reconfigure_stdio_utf8()


_NS = {"ar": "http://autosar.org/schema/r4.0"}
_DCM_DSP_DID_INFO_READ = "DcmDspDidInfo_Read"
_DCM_DSP_DID_INFO_RW = "DcmDspDidInfo_ReadAndWrite"


class ARXMLReviewIssue:
    """One review finding against the ARXML output."""

    def __init__(self, issue_type: str, did: str, message: str):
        self.type = issue_type  # STRUCTURE / COVERAGE / IDENTIFIER / SIZE / INFOREF / FUNCTION
        self.did = did
        self.message = message


class ARXMLReviewer:
    """Review generated ARXML against input JSON.

    Parsing is lenient: we tolerate the default ``xmlns`` (AUTOSAR) and
    emit a clear STRUCTURE issue if the root document is malformed,
    rather than crashing.
    """

    def __init__(self):
        self.issues: List[ARXMLReviewIssue] = []
        # ``dids_json`` is the *input* set (everything ``to_review_dicts``
        # surfaces from ``fscs.json``). v1.12.x used it directly to drive
        # the per-axis checks via ``_effective_dids()`` -- which broke
        # because the generator drops DESELECTED + write-only ERROR +
        # RW-compliance SKIPPED DIDs from the emitted ARXML, but the
        # reviewer would still expect them and report COVERAGE noise.
        # v1.13.0 (differential B) keeps ``dids_json`` for the report
        # header / count line but drives the per-axis checks off
        # ``emitted`` instead -- the SUCCESS subset returned by the
        # generator's classifier ``_document_to_dids``. ``set_emitted``
        # is the one entry point that populates it.
        self.dids_json: List[Dict] = []
        self.emitted: List[Dict] = []
        self.root: Optional[ET.Element] = None
        self.ns: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def parse_arxml(self, arxml_path: Path) -> None:
        path = Path(arxml_path)
        if not path.is_file():
            self.issues.append(ARXMLReviewIssue(
                "STRUCTURE", "-", f"ARXML file not found: {path}",
            ))
            return
        try:
            tree = ET.parse(path)
        except ET.ParseError as e:
            self.issues.append(ARXMLReviewIssue(
                "STRUCTURE", "-", f"ARXML is not well-formed XML: {e}",
            ))
            return
        self.root = tree.getroot()
        # Detect the default namespace that etree stuck on every tag.
        m = re.match(r"^\{(?P<uri>[^}]+)\}", self.root.tag)
        if m:
            self.ns = {"ar": m.group("uri")}
        else:
            self.ns = {}

    def load_from_fscs_json(
        self,
        fscs_json_path: Path,
        *,
        product_type: Optional[str] = None,
    ) -> None:
        """Load expected DIDs from Phase 1's ``fscs.json``.

        Two-step contract since v1.13.0 (differential B):

        1. Load the document and project it into the dict shape via
           :func:`fscs.to_review_dicts` -- this populates
           ``self.dids_json`` for the report header (``Input DID
           count`` line, summary totals).
        2. Re-run the generator's classifier
           (``ARXMLGenerator._document_to_dids``) to compute the
           SUCCESS subset and store it as ``self.emitted``. Per-axis
           checks (``review_coverage``, ``review_identifiers``, ...)
           iterate ``emitted`` rather than ``dids_json`` so DIDs the
           generator deliberately dropped (DESELECTED, write-only
           ERROR, RW-compliance SKIPPED, OUT_OF_SCOPE) don't surface
           as COVERAGE / IDENTIFIER / SIZE / INFOREF / FUNCTION
           false positives.

        :param product_type: Forwarded to the classifier so the
            v1.13.0 product-scope filter applies (schema 1.4). Must
            match whatever the generator was invoked with for that
            run, otherwise the reviewer's ``emitted`` set would
            disagree with the ARXML on disk and the per-axis checks
            would noise up again. v1.24.0 dropped the v1.23.0
            ``accepted_scopes`` knob (the Phase-2 ESPCL → ESP alias
            is now a path-only alias, not a DID fold-in, so
            single-target filtering is back in both the generator
            and the reviewer).
        """
        document = load_fscs(fscs_json=Path(fscs_json_path))
        self.dids_json = to_review_dicts(document)
        # Lazy import to avoid a circular dependency: review_arxml is
        # imported by pipeline.py, which also imports generate_arxml.
        # Importing at module top-level would create a cycle in
        # certain test ordering. Local import has zero perf cost
        # (call happens once per review run).
        from generate_arxml import ARXMLGenerator
        valid_dids, _report = ARXMLGenerator()._document_to_dids(
            document, verbose=False, product_type=product_type,
        )
        # Build a hex -> product_type lookup so set_emitted can
        # carry the v1.13.0 (renamed in v1.16.0) per-DID product
        # tag on each row. Used by the cross-product SCOPE auditor
        # (differential C) to recognise the ``"Common"`` wildcard
        # token. Internal dict key stays ``product_scope`` so the
        # downstream auditor logic can be left untouched; only the
        # source-of-truth attribute name changed.
        scope_by_hex = {
            entry.did_hex.upper(): entry.product_type for entry in document.dids
        }
        self.set_emitted(valid_dids, scope_by_hex=scope_by_hex)

    def set_emitted(
        self,
        valid_dids,
        *,
        scope_by_hex: Optional[Dict[str, Optional[str]]] = None,
    ) -> None:
        """Record the projections the generator wrote into ARXML.

        ``valid_dids`` is the SUCCESS subset returned by
        ``ARXMLGenerator._document_to_dids`` -- the DIDs that actually
        landed in ``DID_Config.arxml``. We project each one into the
        same dict shape the legacy ``review_*`` methods consumed so
        they only need to switch their iteration source, not their
        per-row access patterns.

        :param scope_by_hex: Optional ``did_hex -> product_scope``
            map (uppercase hex keys). When provided, each emitted
            row carries a ``product_scope`` field used by the
            cross-product SCOPE auditor (v1.13.0 differential C) to
            recognise the ``"Common"`` wildcard token.
        """
        scope_by_hex = scope_by_hex or {}
        self.emitted = []
        for d in valid_dids:
            hex_key = str(d.did_hex).replace("0x", "").replace("0X", "").upper()
            self.emitted.append({
                "did_hex": d.did_hex,
                "did_name_en": d.did_name,
                "size_bytes": int(d.size_bytes) if str(d.size_bytes).isdigit() else d.size_bytes,
                "rw_state": d.rw_state,
                "product_scope": scope_by_hex.get(hex_key),
            })

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _tag(self, local: str) -> str:
        if self.ns:
            return f"{{{self.ns['ar']}}}{local}"
        return local

    def _findall(self, node: ET.Element, local: str) -> List[ET.Element]:
        return node.findall(f".//{self._tag(local)}")

    @staticmethod
    def _clean_name(name: str) -> str:
        """Must mirror ARXMLGenerator.clean_name exactly.

        ARXMLGenerator strips non-alphanumeric chars and capitalizes the
        first letter, identical to the impl-side ``_clean_name`` +
        ``_capitalize_first`` pipeline.
        """
        if not name:
            return ""
        cleaned = re.sub(r"[\u4e00-\u9fff]", "", name)
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
        if not cleaned:
            return ""
        return cleaned[0].upper() + cleaned[1:]

    @staticmethod
    def _supports_any(access_leaf: Dict) -> bool:
        if not isinstance(access_leaf, dict):
            return False
        for v in access_leaf.values():
            if isinstance(v, dict) and ARXMLReviewer._supports_any(v):
                return True
            if isinstance(v, str) and v.strip().upper() == "Y":
                return True
        return False

    def _effective_dids(self) -> List[Dict]:
        """The DIDs the generator actually emitted into the ARXML.

        v1.13.0 (differential B): switched from ``self.dids_json``
        filtered by ``supported_by_ecu`` to ``self.emitted`` (the
        SUCCESS subset returned by the generator's classifier). The
        method name is preserved so the per-axis check call sites
        (``review_coverage`` / ``review_identifiers`` / ...) keep
        their existing iteration pattern.

        Falls back to the legacy ``supported_by_ecu`` filter when
        ``self.emitted`` was never populated (e.g. unit tests that
        construct ``ARXMLReviewer`` directly and inject
        ``dids_json``); this preserves backward compatibility for
        the v1.12.x test fixtures while the new code path becomes
        the production default.
        """
        if self.emitted:
            return self.emitted
        return [
            d for d in self.dids_json
            if str(d.get("supported_by_ecu", "Y")).strip().upper() != "N"
        ]

    def _short_name_of(self, container: ET.Element) -> str:
        sn = container.find(self._tag("SHORT-NAME"))
        return sn.text.strip() if sn is not None and sn.text else ""

    def _data_container_names(self) -> List[str]:
        """SHORT-NAMEs of containers under DcmDsp that represent DcmDspData."""
        if self.root is None:
            return []
        names: List[str] = []
        for c in self._findall(self.root, "ECUC-CONTAINER-VALUE"):
            def_ref = c.find(self._tag("DEFINITION-REF"))
            if def_ref is not None and def_ref.text and def_ref.text.endswith("/DcmDspData"):
                names.append(self._short_name_of(c))
        return [n for n in names if n]

    def _did_containers(self) -> List[ET.Element]:
        """Containers whose DEFINITION-REF ends with /DcmDspDid (singular)."""
        if self.root is None:
            return []
        found: List[ET.Element] = []
        for c in self._findall(self.root, "ECUC-CONTAINER-VALUE"):
            def_ref = c.find(self._tag("DEFINITION-REF"))
            if def_ref is not None and def_ref.text and def_ref.text.endswith("/DcmDspDid"):
                found.append(c)
        return found

    # ------------------------------------------------------------------
    # Review checks
    # ------------------------------------------------------------------

    def review_structure(self) -> None:
        """Validate the required AR-Package backbone exists exactly once."""
        if self.root is None:
            return  # already reported during parse_arxml
        required_path = [
            "RB", "UBK", "Project", "EcucModuleConfigurationValuess",
        ]
        node: Optional[ET.Element] = self.root
        for expected in required_path:
            children = node.findall(f"{self._tag('AR-PACKAGES')}/{self._tag('AR-PACKAGE')}") if node is not None else []
            match = None
            for c in children:
                sn = c.find(self._tag("SHORT-NAME"))
                if sn is not None and sn.text and sn.text.strip() == expected:
                    match = c
                    break
            if match is None:
                self.issues.append(ARXMLReviewIssue(
                    "STRUCTURE", "-",
                    f"Missing AR-PACKAGE chain element: {expected}",
                ))
                return
            node = match

        # Ensure both DidInfo shared containers exist (Read + ReadAndWrite).
        short_names = {
            self._short_name_of(c)
            for c in self._findall(self.root, "ECUC-CONTAINER-VALUE")
        }
        for required in (_DCM_DSP_DID_INFO_READ, _DCM_DSP_DID_INFO_RW):
            if required not in short_names:
                self.issues.append(ARXMLReviewIssue(
                    "STRUCTURE", "-",
                    f"Required shared container missing: {required}",
                ))

    def review_coverage(self) -> None:
        """Every effective DID has a DcmDspData + DcmDspDid container."""
        if self.root is None:
            return
        data_names = set(self._data_container_names())
        did_containers = {self._short_name_of(c) for c in self._did_containers()}

        for did in self._effective_dids():
            did_hex = did.get("did_hex", "?")
            hex_stripped = str(did_hex).replace("0x", "").replace("0X", "").upper()
            clean = self._clean_name(did.get("did_name_en", ""))
            expected_data = f"RBAPLCUST_{hex_stripped}_{clean}Data"
            # DID container naming: ARXMLGenerator.generate_dcm_dsp_did
            # uses ``{data_ref_name}Did`` (e.g. RBAPLCUST_F18C_ModeSelectorDataDid).
            expected_did = f"{expected_data}Did"

            if expected_data not in data_names:
                self.issues.append(ARXMLReviewIssue(
                    "COVERAGE", did_hex,
                    f"Expected data container {expected_data} missing in ARXML",
                ))
            if expected_did not in did_containers:
                self.issues.append(ARXMLReviewIssue(
                    "COVERAGE", did_hex,
                    f"Expected DID container {expected_did} missing in ARXML",
                ))

    def _did_container_for(self, did_hex: str, did_name: str = "") -> Optional[ET.Element]:
        """Resolve the DcmDspDid container for a given hex id.

        The generator names DID containers
        ``RBAPLCUST_<HEX>_<Name>DataDid`` (i.e. data container name + "Did"
        suffix), not ``Did_0x<HEX>``. If the caller supplies ``did_name``
        we can match deterministically; otherwise we fall back to a
        prefix match on ``RBAPLCUST_<HEX>_``.
        """
        hex_stripped = str(did_hex).replace("0x", "").replace("0X", "").upper()
        if did_name:
            clean = self._clean_name(did_name)
            target = f"RBAPLCUST_{hex_stripped}_{clean}DataDid"
            for c in self._did_containers():
                if self._short_name_of(c) == target:
                    return c
            return None
        prefix = f"RBAPLCUST_{hex_stripped}_"
        for c in self._did_containers():
            name = self._short_name_of(c)
            if name.startswith(prefix) and name.endswith("DataDid"):
                return c
        return None

    def review_identifiers(self) -> None:
        """DcmDspDidIdentifier decimal value matches int(did_hex, 16)."""
        if self.root is None:
            return
        for did in self._effective_dids():
            did_hex = did.get("did_hex", "?")
            container = self._did_container_for(did_hex, did.get("did_name_en", ""))
            if container is None:
                continue  # already reported by coverage check
            params = container.findall(
                f".//{self._tag('ECUC-NUMERICAL-PARAM-VALUE')}"
            )
            expected_dec = int(str(did_hex).replace("0x", "").replace("0X", ""), 16)
            hit = False
            for p in params:
                def_ref = p.find(self._tag("DEFINITION-REF"))
                value = p.find(self._tag("VALUE"))
                if def_ref is None or value is None:
                    continue
                if not def_ref.text or not def_ref.text.endswith("/DcmDspDidIdentifier"):
                    continue
                hit = True
                try:
                    actual = int(str(value.text).strip())
                except (ValueError, TypeError):
                    self.issues.append(ARXMLReviewIssue(
                        "IDENTIFIER", did_hex,
                        f"DcmDspDidIdentifier value is not numeric: {value.text!r}",
                    ))
                    continue
                if actual != expected_dec:
                    self.issues.append(ARXMLReviewIssue(
                        "IDENTIFIER", did_hex,
                        f"DcmDspDidIdentifier={actual} does not match "
                        f"int({did_hex}, 16)={expected_dec}",
                    ))
            if not hit:
                self.issues.append(ARXMLReviewIssue(
                    "IDENTIFIER", did_hex,
                    f"DcmDspDidIdentifier param missing in DID container",
                ))

    def review_info_refs(self) -> None:
        """RW → DcmDspDidInfo_ReadAndWrite, R → DcmDspDidInfo_Read."""
        if self.root is None:
            return
        for did in self._effective_dids():
            did_hex = did.get("did_hex", "?")
            container = self._did_container_for(did_hex, did.get("did_name_en", ""))
            if container is None:
                continue
            expected_suffix = (
                _DCM_DSP_DID_INFO_RW
                if did.get("rw_state", "").upper() == "RW"
                else _DCM_DSP_DID_INFO_READ
            )
            refs = container.findall(
                f".//{self._tag('ECUC-REFERENCE-VALUE')}"
            )
            hit = False
            for r in refs:
                def_ref = r.find(self._tag("DEFINITION-REF"))
                value_ref = r.find(self._tag("VALUE-REF"))
                if def_ref is None or value_ref is None:
                    continue
                if not def_ref.text or not def_ref.text.endswith("/DcmDspDidInfoRef"):
                    continue
                hit = True
                if not value_ref.text or not value_ref.text.endswith("/" + expected_suffix):
                    self.issues.append(ARXMLReviewIssue(
                        "INFOREF", did_hex,
                        f"DcmDspDidInfoRef should target {expected_suffix}, "
                        f"got {value_ref.text}",
                    ))
            if not hit:
                self.issues.append(ARXMLReviewIssue(
                    "INFOREF", did_hex,
                    f"DcmDspDidInfoRef missing in DID container",
                ))

    def review_data_size(self) -> None:
        """DcmDspDataSize (bits) equals size_bytes * 8."""
        if self.root is None:
            return
        for did in self._effective_dids():
            did_hex = did.get("did_hex", "?")
            hex_stripped = str(did_hex).replace("0x", "").replace("0X", "").upper()
            clean = self._clean_name(did.get("did_name_en", ""))
            short = f"RBAPLCUST_{hex_stripped}_{clean}Data"
            container: Optional[ET.Element] = None
            for c in self._findall(self.root, "ECUC-CONTAINER-VALUE"):
                if self._short_name_of(c) == short:
                    container = c
                    break
            if container is None:
                continue  # reported by coverage
            try:
                expected_bits = int(str(did.get("size_bytes", "1")).strip()) * 8
            except (ValueError, TypeError):
                continue  # unexpected in a validated pipeline; skip silently

            params = container.findall(
                f".//{self._tag('ECUC-NUMERICAL-PARAM-VALUE')}"
            )
            hit = False
            for p in params:
                def_ref = p.find(self._tag("DEFINITION-REF"))
                value = p.find(self._tag("VALUE"))
                if def_ref is None or value is None:
                    continue
                if not def_ref.text or not def_ref.text.endswith("/DcmDspDataSize"):
                    continue
                hit = True
                try:
                    actual = int(str(value.text).strip())
                except (ValueError, TypeError):
                    self.issues.append(ARXMLReviewIssue(
                        "SIZE", did_hex,
                        f"DcmDspDataSize value is not numeric: {value.text!r}",
                    ))
                    continue
                if actual != expected_bits:
                    self.issues.append(ARXMLReviewIssue(
                        "SIZE", did_hex,
                        f"DcmDspDataSize={actual} bits, expected {expected_bits} "
                        f"({did.get('size_bytes')} bytes × 8)",
                    ))
            if not hit:
                self.issues.append(ARXMLReviewIssue(
                    "SIZE", did_hex,
                    f"DcmDspDataSize param missing in data container",
                ))

    def review_function_hooks(self) -> None:
        """RW DIDs reference both _ReadData and _WriteData hooks."""
        if self.root is None:
            return
        for did in self._effective_dids():
            did_hex = did.get("did_hex", "?")
            hex_stripped = str(did_hex).replace("0x", "").replace("0X", "").upper()
            clean = self._clean_name(did.get("did_name_en", ""))
            short = f"RBAPLCUST_{hex_stripped}_{clean}Data"
            container: Optional[ET.Element] = None
            for c in self._findall(self.root, "ECUC-CONTAINER-VALUE"):
                if self._short_name_of(c) == short:
                    container = c
                    break
            if container is None:
                continue

            funcs = [
                (p.find(self._tag("DEFINITION-REF")),
                 p.find(self._tag("VALUE")))
                for p in container.findall(
                    f".//{self._tag('ECUC-TEXTUAL-PARAM-VALUE')}"
                )
            ]
            read_hook = None
            write_hook = None
            for def_ref, value in funcs:
                if def_ref is None or value is None or not def_ref.text:
                    continue
                if def_ref.text.endswith("/DcmDspDataReadFnc"):
                    read_hook = value.text
                elif def_ref.text.endswith("/DcmDspDataWriteFnc"):
                    write_hook = value.text

            expected_read = f"RBAPLCUST_{hex_stripped}_{clean}_ReadData"
            expected_write = f"RBAPLCUST_{hex_stripped}_{clean}_WriteData"

            if read_hook != expected_read:
                self.issues.append(ARXMLReviewIssue(
                    "FUNCTION", did_hex,
                    f"DcmDspDataReadFnc should be {expected_read}, got {read_hook!r}",
                ))
            if did.get("rw_state", "").upper() == "RW":
                if write_hook != expected_write:
                    self.issues.append(ARXMLReviewIssue(
                        "FUNCTION", did_hex,
                        f"DcmDspDataWriteFnc should be {expected_write}, got {write_hook!r}",
                    ))
            else:
                if write_hook is not None:
                    self.issues.append(ARXMLReviewIssue(
                        "FUNCTION", did_hex,
                        f"Read-only DID unexpectedly has DcmDspDataWriteFnc={write_hook!r}",
                    ))

    # ------------------------------------------------------------------
    # Cross-product SCOPE auditing (v1.13.0 differential C)
    # ------------------------------------------------------------------

    def review_cross_product_scope(
        self,
        config,
        current_product_type: str,
    ) -> None:
        """Flag SHORT-NAMEs that appear in multiple product ARXMLs.

        For workspaces that materialise per-product ARXMLs under
        ``Fe_Super/.../{product_type}/Dcm_CusDiag_Services_EcucValues_*.arxml``,
        the same DID showing up in two product trees almost always
        means the operator forgot to set ``product_scope`` on it.
        Walk every *other* product whose template path resolves to a
        readable ARXML, collect its ``DcmDspDid`` SHORT-NAMEs, and
        emit one ``SCOPE`` issue per overlap -- except when the
        emitted entry's ``product_scope`` is ``"Common"``
        (case-insensitive), the documented opt-out for DIDs that
        truly belong everywhere.

        Skipped silently (no issue, no error) when:

        * ``config`` is ``None`` or has no ``paths.arxml_file``
          template configured.
        * The template has no ``{product_type}`` /
          ``{product_type_lower}`` / ``{product_type_upper}``
          placeholder -- a single hard-coded path means the
          workspace targets one product only.
        * No other-product ARXML files exist on disk.

        The check is intentionally read-only and additive: it never
        rewrites the ARXML or modifies ``self.emitted``.
        """
        if config is None:
            return
        try:
            arxml_template = config.paths.arxml_file
            base_dir = config.paths.base_dir
        except AttributeError:
            return
        # v1.19.0: ``project.json`` no longer carries
        # ``product_type_mapping``; we enumerate the canonical
        # five-product set directly. A project that pruned its
        # workspace to a subset of products will just see "no other
        # ARXML found" hits for the absent ones, which is fine.
        from implementation.paths import _DEFAULT_PRODUCT_TYPE_MAP  # noqa: E402,WPS433
        mapping = dict(_DEFAULT_PRODUCT_TYPE_MAP)
        if not arxml_template or not base_dir:
            return
        if "{product_type" not in arxml_template:
            return
        if not current_product_type:
            return

        # Lazy import keeps the placeholder resolver out of the
        # hot path for callers that never use this axis.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from implementation.paths import resolve_path  # noqa: E402

        config_dict = config.model_dump(mode="json") if hasattr(config, "model_dump") else config

        emitted_by_short: Dict[str, Dict] = {}
        for row in self.emitted:
            did_hex = str(row.get("did_hex", "")).replace("0x", "").replace("0X", "").upper()
            clean = self._clean_name(row.get("did_name_en", ""))
            if not did_hex or not clean:
                continue
            short = f"RBAPLCUST_{did_hex}_{clean}DataDid"
            emitted_by_short[short] = row

        if not emitted_by_short:
            return

        base_path = Path(base_dir)

        for other_product_type in mapping.keys():
            if other_product_type == current_product_type:
                continue
            try:
                rel = resolve_path(config_dict, arxml_template, other_product_type)
            except Exception:  # noqa: BLE001 -- defensive; bad template -> skip
                continue
            other_arxml = base_path / rel
            if not other_arxml.is_file():
                continue
            try:
                other_tree = ET.parse(other_arxml)
            except (ET.ParseError, OSError):
                continue
            other_root = other_tree.getroot()
            m = re.match(r"^\{(?P<uri>[^}]+)\}", other_root.tag)
            other_ns = {"ar": m.group("uri")} if m else {}
            other_short_names: set = set()
            tag_container = (
                f"{{{other_ns['ar']}}}ECUC-CONTAINER-VALUE" if other_ns else "ECUC-CONTAINER-VALUE"
            )
            short_tag = f"{{{other_ns['ar']}}}SHORT-NAME" if other_ns else "SHORT-NAME"
            def_tag = f"{{{other_ns['ar']}}}DEFINITION-REF" if other_ns else "DEFINITION-REF"
            for c in other_root.iter(tag_container):
                def_ref = c.find(def_tag)
                if def_ref is None or not def_ref.text:
                    continue
                if not def_ref.text.endswith("/DcmDspDid"):
                    continue
                sn = c.find(short_tag)
                if sn is not None and sn.text:
                    other_short_names.add(sn.text.strip())

            for short, row in emitted_by_short.items():
                if short not in other_short_names:
                    continue
                scope = (row.get("product_scope") or "").strip().lower()
                if scope == "common":
                    continue
                self.issues.append(ARXMLReviewIssue(
                    "SCOPE", row.get("did_hex", "?"),
                    f"DID {short} also appears in {other_product_type} ARXML "
                    f"({other_arxml}); set product_scope='Common' if intentional, "
                    f"or pin the DID to one product via product_scope.",
                ))

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def generate_report(self, output_path: Path) -> Dict:
        by_type: Dict[str, List[ARXMLReviewIssue]] = {}
        for issue in self.issues:
            by_type.setdefault(issue.type, []).append(issue)

        total = len(self.issues)
        effective = self._effective_dids()
        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("ARXML Content Review Report")
        lines.append("=" * 80)
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"输入 DID 数: {len(self.dids_json)}")
        lines.append(f"被 ECU 支持: {len(effective)}")
        lines.append("")

        bucket_order = [
            ("STRUCTURE", "一、AR-Package 结构 (Structure)"),
            ("COVERAGE", "二、容器覆盖 (Container Coverage)"),
            ("IDENTIFIER", "三、DcmDspDidIdentifier 映射 (Identifier Mapping)"),
            ("SIZE", "四、数据大小 (Data Size)"),
            ("INFOREF", "五、DcmDspDidInfoRef 引用 (InfoRef Binding)"),
            ("FUNCTION", "六、Read/Write 函数钩子 (Function Hooks)"),
        ]

        for key, title in bucket_order:
            lines.append("=" * 80)
            lines.append(title)
            lines.append("=" * 80)
            bucket = by_type.get(key, [])
            if not bucket:
                lines.append("  ✓ 全部通过")
            else:
                for issue in bucket:
                    tag = f"[DID {issue.did}] " if issue.did not in ("-", "", None) else ""
                    lines.append(f"  ✗ {tag}{issue.message}")
            lines.append("")

        lines.append("=" * 80)
        lines.append("汇总 (Summary)")
        lines.append("=" * 80)
        if total:
            lines.append(f"发现 {total} 个异常 (不阻断后续流程):")
            for key, title in bucket_order:
                count = len(by_type.get(key, []))
                if count:
                    lines.append(f"  - {key}: {count}个")
        else:
            lines.append("✅ 所有检查通过")
        lines.append("")
        lines.append("=" * 80)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")

        return {
            "has_issues": total > 0,
            "issues": self.issues,
            "summary": {
                "total": total,
                **{k.lower(): len(by_type.get(k, [])) for k, _ in bucket_order},
                "dids_json_count": len(self.dids_json),
                "dids_effective_count": len(effective),
            },
            "report_path": str(output_path),
        }


def run_review(
    arxml_path: Path,
    fscs_json: Path,
    output_path: Path,
    *,
    product_type: Optional[str] = None,
    config=None,
) -> Dict:
    """Shared orchestration for CLI and pipeline; mirrors review_fscs.run_review.

    ``fscs_json`` is the authoritative Phase 1 catalog. The old
    ``input_json`` parameter was dropped in Part 6 so ARXML content is
    cross-checked against the same document Phase 3 consumes, instead
    of re-reading ``inputs/*.json`` and risking drift.

    :param product_type: When provided, the reviewer's ``emitted``
        set is computed against the same product-scope filter the
        generator used (v1.13.0 / schema 1.4). Pass the same value
        you handed to ``ARXMLGenerator.generate(product_type=...)``.
        v1.24.0 dropped the v1.23.0 ``accepted_scopes`` parameter
        (Phase-2 alias is now path-only, not DID fold-in).
    :param config: Optional :class:`scripts.config.ProjectConfig`
        carrying the active project layout. When non-``None`` AND
        ``paths.arxml_file`` contains a ``{product_type}``
        placeholder, the v1.13.0 cross-product SCOPE auditor
        (differential C) inspects the *other* product ARXMLs in the
        Bosch tree and flags DIDs that appear in more than one
        product without being tagged ``product_scope='Common'``.
        Passing ``None`` (the v1.12.x default) skips that axis,
        keeping the reviewer single-tree.
    """
    reviewer = ARXMLReviewer()
    reviewer.parse_arxml(Path(arxml_path))
    reviewer.load_from_fscs_json(Path(fscs_json), product_type=product_type)
    reviewer.review_structure()
    reviewer.review_coverage()
    reviewer.review_identifiers()
    reviewer.review_info_refs()
    reviewer.review_data_size()
    reviewer.review_function_hooks()
    if config is not None and product_type:
        reviewer.review_cross_product_scope(config, product_type)
    return reviewer.generate_report(Path(output_path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ARXML Content Review - 检查生成的 DID_Config.arxml 内容合规性",
    )
    parser.add_argument("--arxml", default="outputs/arxml/DID_Config.arxml",
                        help="ARXML file path (default: outputs/arxml/DID_Config.arxml)")
    parser.add_argument("--fscs-json", default="outputs/fscs/fscs.json",
                        help="权威 fscs.json 输入路径 (default: outputs/fscs/fscs.json)")
    parser.add_argument("--output", "-o",
                        default="outputs/arxml/arxml_review_report.txt",
                        help="Review 报告输出路径")
    args = parser.parse_args()

    fscs_json_path = Path(args.fscs_json)
    if not fscs_json_path.is_file():
        print(f"❌ 错误: 找不到 fscs.json: {fscs_json_path}")
        print("   请先运行 Phase 1 生成 fscs.json, 例如:")
        print("       python scripts/pipeline.py --phase fscs --input <your-did>.json")
        return 2

    try:
        print("=" * 70)
        print("ARXML Content Review")
        print("=" * 70)
        print()
        result = run_review(
            arxml_path=Path(args.arxml),
            fscs_json=fscs_json_path,
            output_path=Path(args.output),
        )
        summary = result["summary"]
        print(f"  JSON DID 数: {summary['dids_json_count']}")
        print(f"  Effective DID 数 (supported_by_ecu=Y): {summary['dids_effective_count']}")
        print()
        if result["has_issues"]:
            print(f"⚠️  发现 {len(result['issues'])} 个问题:")
            for issue in result["issues"]:
                tag = f"[DID {issue.did}] " if issue.did not in ("-", "", None) else ""
                print(f"   [{issue.type}] {tag}{issue.message}")
            print(f"\n详细报告: {args.output}")
            return 1
        print("✅ 所有检查通过")
        return 0
    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        return 2
    except Exception as e:
        print(f"❌ Review 执行失败: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == "__main__":
    sys.exit(main())
