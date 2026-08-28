"""ARXML merge logic for Phase 2 project-tree mirroring.

The generated ``outputs/arxml/DID_Config.arxml`` and the existing
Bosch-supplied ``Dcm_CusDiag_Services_EcucValues_<PRODUCT>.arxml`` share
the exact same container layout:

    AR-PACKAGES/RB/UBK/Project/EcucModuleConfigurationValuess
      /Dcm/DcmConfigSet/DcmDsp/SUB-CONTAINERS
        <ECUC-CONTAINER-VALUE>            <- one per DID (DcmDspData /
        <ECUC-CONTAINER-VALUE>               DcmDspDid / DcmDspDidInfo,
        <ECUC-CONTAINER-VALUE>               all peers at this level)

So "merging" means: pick up every direct child of ``DcmDsp/SUB-CONTAINERS``
from the generated file whose ``SHORT-NAME`` is not yet present in the
target, and append it just before the target's closing
``</SUB-CONTAINERS>``. Order inside the target is preserved, the newly
added containers keep their generated order, and all existing bytes
upstream and downstream of the splice point stay byte-identical (so the
user's diff review only shows *actual* additions).

This module is a pure function (no I/O); the orchestrator
(``generate_arxml.ARXMLGenerator`` / ``pipeline.py``) owns ``--dry-run``
concerns.
"""

from __future__ import annotations

import re
from typing import List, Tuple
from xml.etree import ElementTree as ET


AR_NS = "http://autosar.org/schema/r4.0"


def _qn(tag: str) -> str:
    """Qualified name inside the AUTOSAR namespace."""
    return f"{{{AR_NS}}}{tag}"


def _short_name(container: ET.Element) -> str:
    sn = container.find(_qn("SHORT-NAME"))
    if sn is None or sn.text is None:
        return ""
    return sn.text.strip()


def _find_dcmdsp(root: ET.Element):
    """Return the ``DcmDsp`` ECUC-CONTAINER-VALUE element, or ``None``."""
    for container in root.iter(_qn("ECUC-CONTAINER-VALUE")):
        if _short_name(container) == "DcmDsp":
            return container
    return None


def extract_dcmdsp_short_names(xml_text: str) -> List[str]:
    """Return the ``SHORT-NAME`` of every direct child container under
    ``DcmDsp/SUB-CONTAINERS``. Order follows document order."""
    root = ET.fromstring(xml_text)
    dcmdsp = _find_dcmdsp(root)
    if dcmdsp is None:
        return []
    sub = dcmdsp.find(_qn("SUB-CONTAINERS"))
    if sub is None:
        return []
    return [_short_name(c) for c in sub.findall(_qn("ECUC-CONTAINER-VALUE"))]


def _locate_dcmdsp_sub_end(xml_text: str) -> Tuple[int, str]:
    """Find the byte offset of the ``</SUB-CONTAINERS>`` tag that closes
    ``DcmDsp``'s direct ``<SUB-CONTAINERS>``, plus the indent string used
    by the last container sibling at that level.

    We do this by regex scan + depth counting so we can splice new text
    without reformatting the entire file.
    """
    dcmdsp_match = re.search(r"<SHORT-NAME>DcmDsp</SHORT-NAME>", xml_text)
    if dcmdsp_match is None:
        raise ValueError("DcmDsp SHORT-NAME not found in target ARXML")
    search_start = dcmdsp_match.end()

    open_sub = re.search(r"<SUB-CONTAINERS>", xml_text[search_start:])
    if open_sub is None:
        raise ValueError(
            "No <SUB-CONTAINERS> after DcmDsp SHORT-NAME in target ARXML"
        )
    cursor = search_start + open_sub.end()

    tag_re = re.compile(r"<(/?)SUB-CONTAINERS>")
    depth = 1
    while depth > 0:
        m = tag_re.search(xml_text, cursor)
        if m is None:
            raise ValueError(
                "Unbalanced <SUB-CONTAINERS> tags while locating DcmDsp close"
            )
        if m.group(1) == "":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                close_start = m.start()
                # Detect leading-whitespace indent on the line hosting
                # the closing tag so we can prepend children with the
                # same indentation + one extra level.
                line_start = xml_text.rfind("\n", 0, close_start) + 1
                indent = xml_text[line_start:close_start]
                return close_start, indent
        cursor = m.end()
    raise ValueError("Failed to locate matching </SUB-CONTAINERS> for DcmDsp")


def _extract_child_blocks(xml_text: str) -> List[Tuple[str, str]]:
    """Extract each direct ``<ECUC-CONTAINER-VALUE>...</ECUC-CONTAINER-VALUE>``
    child of ``DcmDsp/SUB-CONTAINERS`` from the generated XML, returning
    ``[(short_name, raw_text), ...]`` in document order.

    We return the raw source text (including leading whitespace) so the
    spliced output preserves the exact look of the generator's output.

    Returns an empty list if the XML has no DcmDsp container -- callers
    treat this as "nothing to merge" rather than an error (e.g. an empty
    validation report with zero valid DIDs).
    """
    try:
        open_pos, _ = _locate_dcmdsp_sub_open(xml_text)
        close_pos, _ = _locate_dcmdsp_sub_end(xml_text)
    except ValueError:
        return []
    inner = xml_text[open_pos:close_pos]

    blocks: List[Tuple[str, str]] = []
    tag_re = re.compile(r"<(/?)ECUC-CONTAINER-VALUE(?:\s[^>]*)?>")
    pos = 0
    while True:
        m = tag_re.search(inner, pos)
        if m is None:
            break
        if m.group(1):  # closing tag at depth 0 -- should not happen first
            pos = m.end()
            continue
        # Found an opening tag at depth 0; walk forward counting nested
        # <ECUC-CONTAINER-VALUE> so we skip over sub-containers attached
        # to DcmDspDidInfo (which nest DcmDspDidRead / DcmDspDidWrite).
        depth = 1
        cursor = m.end()
        while depth > 0:
            nxt = tag_re.search(inner, cursor)
            if nxt is None:
                raise ValueError(
                    "Unbalanced ECUC-CONTAINER-VALUE while extracting children"
                )
            if nxt.group(1):
                depth -= 1
            else:
                depth += 1
            cursor = nxt.end()
        block_text = inner[m.start():cursor]
        # Include leading whitespace on that line so indentation stays intact.
        line_start = inner.rfind("\n", 0, m.start()) + 1
        leading_ws = inner[line_start:m.start()]
        block_with_ws = leading_ws + block_text
        # Parse SHORT-NAME of this container only (first SHORT-NAME inside
        # the block, which is the top-level one).
        sn_match = re.search(r"<SHORT-NAME>([^<]+)</SHORT-NAME>", block_text)
        short = sn_match.group(1).strip() if sn_match else ""
        blocks.append((short, "\n" + block_with_ws))
        pos = cursor
    return blocks


def _locate_dcmdsp_sub_open(xml_text: str) -> Tuple[int, str]:
    """Like :func:`_locate_dcmdsp_sub_end` but returns the offset right
    after the opening ``<SUB-CONTAINERS>`` tag inside DcmDsp."""
    dcmdsp_match = re.search(r"<SHORT-NAME>DcmDsp</SHORT-NAME>", xml_text)
    if dcmdsp_match is None:
        raise ValueError("DcmDsp SHORT-NAME not found")
    search_start = dcmdsp_match.end()
    open_sub = re.search(r"<SUB-CONTAINERS>", xml_text[search_start:])
    if open_sub is None:
        raise ValueError("No <SUB-CONTAINERS> after DcmDsp")
    return search_start + open_sub.end(), ""


def merge_arxml(existing_xml: str, generated_xml: str) -> Tuple[str, int, int, List[str]]:
    """Merge new DID containers from ``generated_xml`` into ``existing_xml``.

    Returns ``(merged_xml, inserted_count, skipped_count, inserted_names)``.

    Policy:

    * Every direct ECUC-CONTAINER-VALUE child of ``DcmDsp/SUB-CONTAINERS``
      in ``generated_xml`` is considered.
    * If a container with the same SHORT-NAME already exists under
      ``DcmDsp`` in ``existing_xml``, it is **skipped** (existing
      hand-tuned definitions win -- same policy as .c files).
    * Otherwise it is appended just before the target's closing
      ``</SUB-CONTAINERS>`` for DcmDsp, preserving formatting.

    Raises ``ValueError`` if either side's DcmDsp container cannot be
    located (malformed ARXML).
    """
    existing_names = set(extract_dcmdsp_short_names(existing_xml))
    blocks = _extract_child_blocks(generated_xml)

    close_pos, _indent = _locate_dcmdsp_sub_end(existing_xml)

    inserted_names: List[str] = []
    skipped = 0
    pieces: List[str] = []
    for short_name, block_text in blocks:
        if not short_name:
            skipped += 1
            continue
        if short_name in existing_names:
            skipped += 1
            continue
        pieces.append(block_text)
        inserted_names.append(short_name)
        existing_names.add(short_name)

    if not pieces:
        return existing_xml, 0, skipped, []

    insertion = "".join(pieces)
    # Ensure there is a trailing newline before the close tag, preserving
    # whatever indentation that close tag was already using.
    if not insertion.endswith("\n"):
        insertion += "\n"
    # The original close tag is preceded by its own line's indent; we
    # slice at close_pos which is exactly the start of that indent, so
    # inserting here puts the new blocks *before* the indent of </SUB-CONTAINERS>.
    line_start = existing_xml.rfind("\n", 0, close_pos) + 1
    # Insert right before the line that hosts </SUB-CONTAINERS>.
    merged = existing_xml[:line_start] + insertion.lstrip("\n") + "\n" + existing_xml[line_start:]
    return merged, len(inserted_names), skipped, inserted_names
