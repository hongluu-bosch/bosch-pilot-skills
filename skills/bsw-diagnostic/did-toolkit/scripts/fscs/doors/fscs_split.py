"""Split a generated FSCS_22.txt / FSCS_2E.txt into per-DID blocks.

Each block is rendered by ``scripts/fscs/renderer.py`` in the form::

    Identifier $5001h - Vehicle mode

    Description
    This identifier returns the Vehicle mode
    ...
    Behavior:
    interface:

    ================================================================================

    Identifier $3400h - Usage mode
    ...

The renderer always emits ``Identifier $<HEX>h - <Name>`` as the first
non-blank line of each DID, then a blank separator, then the body, then
an ``=================`` separator before the next DID.

This module owns the parsing contract that the DOORS payload builder
depends on: returning, for each DID, the heading line (which becomes
``Object Heading`` in DOORS) and the trimmed body (which becomes
``Object Text``).

The file-level header banner emitted by the renderer (``# Generated
from outputs/fscs/fscs.json -- do not edit ...``) is stripped before
parsing so authoring tweaks to the banner never leak into DOORS rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional


_SEP_RE = re.compile(r"^=+\s*$")
_HEADER_RE = re.compile(
    r"^Identifier\s+\$(?P<hex>[0-9A-Fa-f]{1,4})h\s*-\s*(?P<name>.*?)\s*$"
)


@dataclass(frozen=True)
class DIDBlock:
    """A single DID rendered by the FSCS renderer.

    Attributes
    ----------
    did_hex : str
        Uppercase hex with ``0x`` prefix, e.g. ``"0x5001"``. Always
        4 hex digits (zero-padded).
    did_name : str
        English name of the DID (the bit after ``Identifier $XXXXh -``).
        Stripped of trailing whitespace; never ``None``.
    heading : str
        The first non-blank line of the block, verbatim. This is the
        line we put in DOORS ``Object Heading``.
    body : str
        Everything after ``heading``, with the leading blank line
        between heading and body trimmed off and trailing whitespace
        stripped. This is the cell content for DOORS ``Object Text``.
    """

    did_hex: str
    did_name: str
    heading: str
    body: str


def _strip_banner(lines: Iterable[str]) -> List[str]:
    """Drop the renderer banner (leading ``#`` lines + the blank line
    that follows it). Pure ``#`` lines elsewhere in the file are kept
    because the renderer does not currently emit any, but if it ever
    starts to we want to surface them inside the body rather than
    silently swallow them.
    """
    out: List[str] = []
    in_banner = True
    for line in lines:
        if in_banner:
            stripped = line.strip()
            if stripped.startswith("#") or stripped == "":
                continue
            in_banner = False
        out.append(line)
    return out


def _split_into_blocks(lines: List[str]) -> List[List[str]]:
    """Split the file into per-DID line groups using the
    ``==================`` separator that the renderer always emits
    between DIDs. The trailing separator (if any) is also handled.
    """
    blocks: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if _SEP_RE.match(line):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _normalise_block(block_lines: List[str]) -> Optional[DIDBlock]:
    """Turn one ``[line, line, ...]`` group into a ``DIDBlock`` or
    ``None`` when the group is just whitespace (which happens at the
    very end of the file when the renderer trails the last separator
    with a blank line)."""
    while block_lines and not block_lines[0].strip():
        block_lines.pop(0)
    while block_lines and not block_lines[-1].strip():
        block_lines.pop()
    if not block_lines:
        return None

    heading_line = block_lines[0]
    match = _HEADER_RE.match(heading_line)
    if not match:
        return None

    hex_raw = match.group("hex").upper().zfill(4)
    name = match.group("name").strip()
    did_hex = f"0x{hex_raw}"

    body_lines = block_lines[1:]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    body = "\n".join(body_lines).rstrip()

    return DIDBlock(
        did_hex=did_hex,
        did_name=name,
        heading=heading_line.rstrip(),
        body=body,
    )


def split_text(text: str) -> List[DIDBlock]:
    """Parse a full FSCS_22.txt / FSCS_2E.txt string into ``DIDBlock``
    instances, in the order the renderer wrote them. Block-less files
    (e.g. only a banner, no DIDs) return ``[]``."""
    raw_lines = text.splitlines()
    body_lines = _strip_banner(raw_lines)
    blocks: List[DIDBlock] = []
    for group in _split_into_blocks(body_lines):
        block = _normalise_block(group)
        if block is not None:
            blocks.append(block)
    return blocks


def split_file(path: Path) -> List[DIDBlock]:
    """Convenience wrapper around :func:`split_text` that reads the
    file with the same UTF-8-with-optional-BOM encoding the renderer
    writes."""
    if not path.is_file():
        raise FileNotFoundError(f"FSCS text file missing: {path}")
    return split_text(path.read_text(encoding="utf-8-sig"))


__all__ = ["DIDBlock", "split_text", "split_file"]
