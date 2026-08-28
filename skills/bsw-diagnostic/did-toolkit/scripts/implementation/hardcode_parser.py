"""HardCode behavior parser — extract per-byte hex values from FSCS text.

v2.4.0: ROM/Flash DIDs can declare their constant byte values in the
``service_22_behavior`` field using a standard ``HardCode:`` block.
This module parses that block so the generator can emit the matching
``#define`` ladder automatically.

Standard format
---------------

The behavior text must start with ``HardCode:`` (case-insensitive) and
contain one line per byte in the form::

    C_DID_<DidName>_Byte<N>_UB = 0x<HH>

* ``<DidName>`` — the PascalCase DID name (spaces removed), matching the
  ``did_name_en`` field sanitised by :func:`naming.clean_name`.
* ``<N>`` — zero-based byte index, contiguous from ``0`` to ``size_bytes-1``.
* ``<HH>`` — two-digit upper-case hex, with ``0x`` prefix.

Example (0xF18A, 9 bytes)::

    HardCode:
    C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB = 0x42
    C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB = 0x6F
    C_DID_SystemSupplierIdentifierDataIdentifier_Byte2_UB = 0x73
    ...

Parsing contract
----------------

* **Complete match** — every byte from ``0`` to ``size_bytes-1`` is found
  in the behavior text → all ``#define``s use the parsed hex values.
* **Partial match** — some bytes are present, others missing → parsed
  values are used where available; missing bytes fall back to ``0x00u``
  with a ``TODO(agent)`` comment.
* **No match** — the text does not start with ``HardCode:`` or no lines
  match the regex → every byte falls back to ``0x00u`` with a TODO.

The parser is intentionally permissive (whitespace-tolerant,
case-insensitive on the ``HardCode:`` header) so minor formatting
variations in operator-edited Excel cells don't break the pipeline.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


# Whitespace-tolerant: allows "= 0x42" or "=0x42" or "  =  0x42"
_HARDCODE_LINE_RE = re.compile(
    r"C_DID_(\w+)_Byte(\d+)_UB\s*=\s*(0x[0-9A-Fa-f]{2})",
    re.IGNORECASE,
)


def parse_hardcode_values(
    behavior: str,
    did_name: str,
    size_bytes: int,
) -> List[Tuple[int, str, bool]]:
    """Parse the HardCode block from *behavior* and return a per-byte list.

    Args:
        behavior: The raw ``service_22_behavior`` text from FSCS.
        did_name: The sanitised DID name (used for validation, not
            transformation — the caller already has the clean name).
        size_bytes: Expected number of bytes (from FSCS ``size_bytes``).

    Returns:
        A list of ``(byte_index, hex_value, is_parsed)`` tuples, one per
        byte from ``0`` to ``size_bytes-1``.  ``is_parsed`` is ``True``
        when the value was successfully extracted from the behavior text,
        ``False`` when it is a fallback ``0x00u``.
    """
    if not behavior:
        return _fallback_all(size_bytes)

    stripped = behavior.strip()
    if not stripped:
        return _fallback_all(size_bytes)

    # Case-insensitive header check; tolerate "HardCode:", "Hardcode:", etc.
    if not re.match(r"HardCode\s*:", stripped, re.IGNORECASE):
        return _fallback_all(size_bytes)

    # Extract all (byte_index, hex_value) pairs from the text.
    parsed: Dict[int, str] = {}
    for match in _HARDCODE_LINE_RE.finditer(stripped):
        _matched_name = match.group(1)
        byte_idx = int(match.group(2))
        hex_val = match.group(3).upper().replace("0X", "").replace("0x", "")
        # Only accept bytes within the declared size.
        if 0 <= byte_idx < size_bytes:
            parsed[byte_idx] = hex_val

    result: List[Tuple[int, str, bool]] = []
    for i in range(size_bytes):
        if i in parsed:
            result.append((i, parsed[i], True))
        else:
            result.append((i, "00", False))
    return result


def _fallback_all(size_bytes: int) -> List[Tuple[int, str, bool]]:
    """Return a list where every byte is the fallback ``0x00u``."""
    return [(i, "00", False) for i in range(size_bytes)]


def build_define_lines(
    did_name: str,
    byte_values: List[Tuple[int, str, bool]],
) -> List[str]:
    """Render ``#define C_DID_<Name>_Byte<N>_UB 0x<HH>u`` lines.

    Missing bytes (``is_parsed == False``) get ``0x00u`` plus an inline
    ``/* TODO(agent): verify */`` comment.
    """
    lines: List[str] = []
    for idx, hex_val, is_parsed in byte_values:
        macro_name = f"C_DID_{did_name}_Byte{idx}_UB"
        # Align columns: macro name padded to a consistent width (80 chars
        # is generous enough for even very long DID names).
        padding = max(1, 72 - len(macro_name))
        val_str = f"0x{hex_val}u"
        if is_parsed:
            lines.append(f"#define {macro_name}{' ' * padding}{val_str}")
        else:
            lines.append(
                f"#define {macro_name}{' ' * padding}{val_str}"
                f"    /* TODO(agent): verify — no HardCode value found */"
            )
    return lines
