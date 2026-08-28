"""Construct an :class:`FSCSDocument` from legacy ``FSCS_*.txt`` files.

Purpose
-------

Until Step 2 of the FSCS data source governance migration, the two
``FSCS_*.txt`` files were the *only* source of truth. Old projects may
still have these plaintext files without a sibling ``fscs.json``. This
module reads both files and produces a validated :class:`FSCSDocument`
so the rest of the code path (renderer, xlsx edit, consumers) can treat them
identically to the native JSON source.

Scope / non-goals
-----------------

* This is deliberately a one-shot bridge. New projects produce
  ``fscs.json`` directly via :mod:`scripts.fscs.builder`.
* The importer parses the same fields the legacy
  :func:`scripts.implementation.parsers.parse_fscs` extracts plus a
  handful more (description prose, request/response overrides). Fields
  we cannot recover from text (e.g. ``did_name_zh``, per-sub-field
  ``method_zh``) come back as ``None`` / empty.
* Sub-fields are *not* reconstructed from the Positive Response
  Message table. The table is lossy: FSCS .txt renders enum details
  as ``0x00: Normal`` which cannot be reversed into the original
  ``method_en="0x00=Normal\\n..."`` spelling reliably. Downstream
  consumers that need structured sub_fields should regenerate
  ``fscs.json`` from the original ``inputs/*.json`` via
  :func:`scripts.fscs.builder.build_fscs_document`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSGeneratorMeta,
    FSCSProject,
    FSCSSecurityLevel,
    FSCSServiceAccess,
    FSCSValueRange,
    FSCSValueRangeEnum,
    FSCSValueRangeNone,
    FSCSValueRangeNumeric,
    normalize_did_hex,
    normalize_storage_position,
)


BLOCK_SEPARATOR = "=" * 80

# Every regex uses ``[^\S\n]`` (horizontal whitespace only) so we never
# repeat the ``\s*(\S+)`` over-match-across-newline bug the migration
# set out to fix.
_HWS = r"[^\S\n]*"

_IDENT_RE = re.compile(rf"Identifier{_HWS}\$([0-9A-Fa-f]+)h{_HWS}-{_HWS}(.+?)(?:\n|$)")
_DATA_TYPE_RE = re.compile(rf"Data Type:{_HWS}([^\n]*)")
_STORAGE_RE = re.compile(rf"Storage Position:{_HWS}([^\n]*)")
_SIZE_RE = re.compile(rf"Size:{_HWS}(\S+){_HWS}bytes")
_RW_RE = re.compile(rf"R/W State:{_HWS}(\S+)")
_NVM_RE = re.compile(rf"NVM Item:{_HWS}([^\n]*)")
_VALUE_RANGE_RE = re.compile(rf"Value Range:{_HWS}([^\n]*)")
_SECURITY_LINE_RE = re.compile(rf"{_HWS}(L[01])(?:{_HWS}(\(.+?\)))?{_HWS}$", re.MULTILINE)
_SESSION_BLOCK_RE = re.compile(
    r"Supported in the following diagnostic sessions:\s*\n((?:- \S+\s*\n?)*)",
)
_DESCRIPTION_RE = re.compile(r"Description\n([^\n]*)")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def import_fscs_txt(
    *,
    fscs_22_path: Optional[Path] = None,
    fscs_2e_path: Optional[Path] = None,
    project: Optional[FSCSProject] = None,
) -> FSCSDocument:
    """Merge one or both legacy ``FSCS_*.txt`` files into an ``FSCSDocument``.

    * Either path may be ``None`` if the corresponding file is absent.
    * DIDs appearing in both files are merged: ``rw_state`` is promoted
      to ``"RW"`` and each service's availability block comes from its
      respective source file.
    * Missing structural data (sub_fields, Chinese names, etc.) is
      left empty; callers in need of the full fidelity should
      regenerate ``fscs.json`` from ``inputs/*.json``.
    """
    entries_22 = _parse_file(fscs_22_path, is_write=False) if fscs_22_path else {}
    entries_2e = _parse_file(fscs_2e_path, is_write=True) if fscs_2e_path else {}

    all_hexes = sorted(set(entries_22) | set(entries_2e))

    merged: List[DIDFscsEntry] = []
    for hex_ in all_hexes:
        read = entries_22.get(hex_)
        write = entries_2e.get(hex_)

        base = read or write
        if base is None:
            continue

        rw_state = _merge_rw_state(read is not None, write is not None)
        service_22 = (
            read.service_22 if read is not None
            else FSCSServiceAccess(supported=False)
        )
        service_2e = (
            write.service_2e if write is not None
            else FSCSServiceAccess(supported=False)
        )

        merged.append(
            base.model_copy(update={
                "rw_state": rw_state,
                "service_22": service_22,
                "service_2e": service_2e,
            })
        )

    document = FSCSDocument(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        generator=FSCSGeneratorMeta(
            tool="did-toolkit/fscs_import.py",
            source_inputs=_format_source_inputs(fscs_22_path, fscs_2e_path),
        ),
        project=project or FSCSProject(),
        dids=merged,
    )
    # v1.16.0 (schema 1.5): legacy-text imports no longer auto-fill
    # ``product_type`` from the (removed) ``project.product_type``
    # config knob. Operators who want a default for a single-product
    # workflow should pass ``--default-product-type`` to
    # ``fscs_import.py`` (or just edit the resulting CSV). Lazy
    # import is kept for the rare caller that does want to apply a
    # default after the fact.
    from .builder import apply_product_type_defaults  # noqa: F401  (still importable)
    return document


# ---------------------------------------------------------------------------
# Per-file parsing
# ---------------------------------------------------------------------------


def _parse_file(path: Path, *, is_write: bool) -> Dict[str, DIDFscsEntry]:
    text = Path(path).read_text(encoding="utf-8")
    entries: Dict[str, DIDFscsEntry] = {}
    for block in text.split(BLOCK_SEPARATOR):
        block = block.strip()
        if not block:
            continue
        entry = _parse_block(block, is_write=is_write)
        if entry is not None:
            entries[entry.did_hex] = entry
    return entries


def _parse_block(block: str, *, is_write: bool) -> Optional[DIDFscsEntry]:
    ident = _IDENT_RE.search(block)
    if not ident:
        return None
    did_hex = normalize_did_hex(ident.group(1))
    did_name = ident.group(2).strip()

    data_type = _first_group(_DATA_TYPE_RE, block, default="Unsigned").strip()
    storage_pos_raw = _first_group(_STORAGE_RE, block, default="RAM").strip()
    storage_pos = (
        normalize_storage_position(storage_pos_raw) if storage_pos_raw else "RAM"
    )
    if storage_pos not in {"EEPROM", "RAM"}:
        # Legacy files occasionally mis-spell the storage kind; default
        # to RAM so the schema still validates. ``normalize_storage_position``
        # already maps the ``NVM`` alias to ``EEPROM``, so anything still
        # landing here is a genuine typo. Drift detection flags the anomaly
        # separately.
        storage_pos = "RAM"

    size_raw = _first_group(_SIZE_RE, block, default="1")
    size_bytes = int(size_raw) if size_raw.isdigit() else 1

    nvm_item = _first_group(_NVM_RE, block, default="").rstrip()
    value_range_str = _first_group(_VALUE_RANGE_RE, block, default="").strip()
    value_range = _parse_value_range_str(value_range_str)

    sessions = _parse_sessions(block)
    security = _parse_security_levels(block)
    access = FSCSServiceAccess(
        supported=True,
        sessions=sessions,
        security_levels=security,
    )

    return DIDFscsEntry(
        did_hex=did_hex,
        did_name=did_name,
        data_type=data_type if data_type in _ALLOWED_DATA_TYPES else "Unsigned",
        storage_position=storage_pos,
        size_bytes=max(1, size_bytes),
        rw_state="W" if is_write else "R",
        nvm_item=nvm_item,
        service_22=access if not is_write else FSCSServiceAccess(supported=False),
        service_2e=access if is_write else FSCSServiceAccess(supported=False),
        sub_fields=[],  # lossy; see module docstring
        value_range=value_range,
    )


def _first_group(pattern: re.Pattern, text: str, *, default: str) -> str:
    match = pattern.search(text)
    return match.group(1) if match else default


_ALLOWED_DATA_TYPES = {
    "ASCII", "Unsigned", "Signed", "HEX", "Bytefield",
    "Texttable", "enum", "Linear", "Identity",
}


def _parse_sessions(block: str) -> List[str]:
    match = _SESSION_BLOCK_RE.search(block)
    if not match:
        return []
    out: List[str] = []
    for session in re.findall(r"- (\S+)", match.group(1)):
        if session in {"defaultSession", "extendedDiagnosticSession"}:
            out.append(session)
    return out


def _parse_security_levels(block: str) -> List[FSCSSecurityLevel]:
    """Extract the indented ``L0 [note]`` / ``L1 [note]`` lines.

    ``Security Level:`` introduces a small region; we slice from that
    header to the next blank line so we don't spuriously match an ``L0``
    appearing later in the text.
    """
    start = block.find("Security Level:")
    if start < 0:
        return []
    region = block[start:]
    # Trim to the first blank line so we don't grab later noise.
    blank = region.find("\n\n")
    if blank >= 0:
        region = region[:blank]

    out: List[FSCSSecurityLevel] = []
    for match in _SECURITY_LINE_RE.finditer(region):
        level = match.group(1)
        note = match.group(2)
        out.append(FSCSSecurityLevel(level=level, note=note))
    return out


def _parse_value_range_str(raw: str) -> FSCSValueRange:
    """Reverse-engineer the ``value_range`` field from its .txt form."""
    if not raw:
        return FSCSValueRangeNone()
    if raw.startswith("Enum:"):
        values = [v.strip() for v in raw[len("Enum:"):].split(",") if v.strip()]
        return FSCSValueRangeEnum(values=values) if values else FSCSValueRangeNone()
    if "~" in raw:
        parts = raw.split("~", 1)
        if len(parts) == 2:
            min_val = parts[0].strip()
            tail = parts[1].strip().split(maxsplit=1)
            max_val = tail[0] if tail else ""
            unit = tail[1] if len(tail) > 1 else ""
            if min_val and max_val:
                return FSCSValueRangeNumeric(min=min_val, max=max_val, unit=unit)
    return FSCSValueRangeNone()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _merge_rw_state(has_read: bool, has_write: bool) -> str:
    if has_read and has_write:
        return "RW"
    if has_write:
        return "W"
    return "R"


def _format_source_inputs(
    p22: Optional[Path], p2e: Optional[Path],
) -> str:
    parts: List[str] = []
    if p22:
        parts.append(str(p22))
    if p2e:
        parts.append(str(p2e))
    return "; ".join(parts)
