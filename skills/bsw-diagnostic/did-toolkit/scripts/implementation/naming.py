"""Pure naming-convention helpers.

Everything in this module is stateless; all Bosch-flavored prefixes are
either module constants or accepted as parameters. The orchestrator class
in :mod:`scripts.implementation.orchestrator` only has to remember
``self.fs_prefix`` / ``self.nvm_prefix`` and forward to these functions.

Constants
---------
``FS_MACRO_PREFIX`` -- hardcoded Bosch Feature Switch prefix
``NVM_ID_PREFIX``   -- hardcoded Bosch NVM Block ID prefix
"""

from __future__ import annotations

import re

from .models import DIDImplementationInfo


FS_MACRO_PREFIX = "RBFS_DCOM_"
NVM_ID_PREFIX = "NVM_ID_DCOM_"


def clean_name(name: str) -> str:
    """Strip everything that cannot appear in a C identifier.

    Chinese characters, spaces, slashes and punctuation all collapse to the
    empty string; an empty result falls back to ``"Unknown"`` so generated
    macro / filename tokens never end up as ``"_"``.
    """
    cleaned = re.sub(r'[^a-zA-Z0-9_]', '', name)
    return cleaned or "Unknown"


def capitalize_first(name: str) -> str:
    """Upper-case the first character only (so ``modeSelector`` ->
    ``ModeSelector`` without touching the following camelCase)."""
    if not name:
        return name
    return name[0].upper() + name[1:] if len(name) > 1 else name.upper()


def get_fs_macro(did_name: str, fs_prefix: str = FS_MACRO_PREFIX) -> str:
    """Generate Feature Switch macro name ``<fs_prefix><CapitalizedName>``.

    Drops any leading ``NVM_ID_DCOM_`` (case insensitive) from the raw name
    so DIDs whose ``did_name`` already carries a NVM prefix do not double
    up the Bosch macro namespace.
    """
    clean = clean_name(did_name)
    if clean.upper().startswith('NVM_ID_DCOM_'):
        clean = clean[12:]
    elif clean.lower().startswith('nvm_id_dcom_'):
        clean = clean[12:]
    clean = capitalize_first(clean)
    return f"{fs_prefix}{clean}"


def get_nvm_id(nvm_item: str) -> str:
    """Return the FSCS NVM item verbatim (trimmed); empty stays empty.

    The actual ``NVM_ID_DCOM_`` prefix already lives inside the FSCS text,
    so this helper is a pass-through that only trims surrounding whitespace.
    """
    if not nvm_item:
        return ""
    return nvm_item.strip()


def get_range_macro_name(did_hex: str, suffix: str) -> str:
    """Build a DID value-range macro name: ``DID_<HEX>_<SUFFIX>``.

    Uses the hex ID (not the cleaned DID name) so the macro is short and
    guaranteed unique even when two DIDs clean down to the same identifier.
    """
    did_id = did_hex.replace('0x', '').replace('$', '').upper()
    return f"DID_{did_id}_{suffix}"


def get_func_name(did: DIDImplementationInfo) -> str:
    """Build the C function name stem: ``RBAPLCUST_<HEX>_<Name>``.

    The name is capitalized on the first character only so the result is
    ``RBAPLCUST_F18C_ModeSelector`` rather than
    ``RBAPLCUST_F18C_modeSelector``.
    """
    did_hex_clean = did.did_hex.replace('0x', '').upper()
    cleaned = clean_name(did.did_name)
    return f"RBAPLCUST_{did_hex_clean}_{capitalize_first(cleaned)}"
