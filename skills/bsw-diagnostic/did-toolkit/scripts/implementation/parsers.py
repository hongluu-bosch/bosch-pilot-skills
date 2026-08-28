"""Value-range string helpers used by Phase 3 code generation.

Prior to the Part 6 cleanup this module also housed two plaintext
FSCS parsers (``parse_fscs`` / ``parse_both_fscs``). Those paths are
now deleted -- ``outputs/fscs/fscs.json`` is the one runtime source and
``scripts.fscs.adapter.to_did_implementation_infos`` projects it onto
:class:`DIDImplementationInfo` for Phase 3. Only the two pure
``value_range`` string helpers remain, because the generators and a
handful of unit tests still rely on the original token shapes.
"""

from __future__ import annotations

from typing import List, Tuple


def parse_enum_values(value_range: str) -> List[str]:
    """Extract enum literals from an FSCS Value Range string.

    Accepts the ``"Enum: 0x00, 0x01, 0x02"`` shape; anything else yields
    ``[]``. Whitespace around values is trimmed; empty tokens (trailing
    commas) are dropped.
    """
    if 'Enum:' in value_range:
        enum_part = value_range.split('Enum:')[1].strip()
        values = [v.strip() for v in enum_part.split(',')]
        return [v for v in values if v]
    return []


def parse_numeric_range(value_range: str) -> Tuple[str, str]:
    """Extract ``(min, max)`` from an FSCS Value Range string.

    Accepts ``"0 ~ 255"`` / ``"0x00 ~ 0xFF"`` / ``"-128 ~ 127"``; an
    optional trailing unit ("0 ~ 255 degC") is stripped off. Enum ranges
    are skipped entirely (caller should branch on
    :func:`parse_enum_values` first). Returns ``("", "")`` for anything
    that does not match the ``min ~ max`` shape.
    """
    if '~' in value_range and 'Enum:' not in value_range:
        parts = value_range.split('~')
        if len(parts) == 2:
            min_val = parts[0].strip()
            max_val = parts[1].strip().split()[0]
            return min_val, max_val
    return "", ""
