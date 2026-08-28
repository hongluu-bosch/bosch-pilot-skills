"""Build an :class:`FSCSDocument` from raw ``inputs/*.json`` records.

The legacy ``generate_fscs.py`` fused two responsibilities into one
class:

1. Mapping raw records (keyed ``did_hex``, ``sub_fields``, ``access``)
   into a semantic view.
2. Rendering that view to plaintext.

This module owns the first half. The second half lives in
:mod:`scripts.fscs.renderer`. Splitting them lets Phase 1 serialise the
semantic view to ``outputs/fscs/fscs.json`` (the authoritative source)
and *then* hand that same document to the renderer, guaranteeing the
JSON and the two ``.txt`` files stay in sync.

Input shape
-----------

The raw records look like (simplified)::

    {
      "did_hex": "0xF190",
      "did_name_en": "BaselineCounter",
      "rw_state": "R",
      "size_bytes": "1",
      "data_type": "Unsigned",
      "storage_pos": "EEPROM",
      "access": {
        "service_22": {"application": {...}, "security": {...}},
        "service_2e": {...},
      },
      "sub_fields": [
        {"byte": "0", "name_en": "...", "range_min_phy": "0",
         "range_max_phy": "255", "method_en": "...", ...},
      ],
    }

Records are divided into three buckets by :func:`build_fscs_document`:

* **kept** -- pass schema validation and land in ``FSCSDocument.dids``.
* **filtered** -- ``supported_by_ecu != "Y"`` (mirrors the legacy
  generator; tracked so the report can tell operators *why* a DID they
  expect isn't showing up).
* **skipped** -- failed Pydantic / schema validation (bad did_hex,
  unknown storage_pos, etc.). Per v1.1 these no longer abort the whole
  build; we drop the bad record, keep the rest, and surface every
  skipped row in the generation report so the input can be fixed
  incrementally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError

from .schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSGeneratorMeta,
    FSCSProject,
    FSCSSecurityLevel,
    FSCSServiceAccess,
    FSCSSubField,
    FSCSValueRange,
    FSCSValueRangeComposite,
    FSCSValueRangeEnum,
    FSCSValueRangeNone,
    FSCSValueRangeNumeric,
    normalize_did_hex,
    normalize_storage_position,
)


NVM_ID_PREFIX = "NVM_ID_DCOM_"


def apply_product_type_defaults(
    document: FSCSDocument,
    *,
    default_product_type: Optional[str] = None,
) -> int:
    """Fill per-DID ``product_type`` from ``default_product_type``
    for newly-built DIDs.

    Every DID carries an explicit ``product_type`` post-load (the
    schema migrator + field validator collapse missing / ``None``
    / blank values to the wildcard ``"Common"``). When the caller
    passes a non-empty, non-``Common`` override (typically Phase
    1's ``--product-type`` CLI flag), entries that still carry the
    default wildcard ``Common`` are replaced with the override so
    single-product workflows get every DID tagged automatically.
    Entries the operator has tagged with a specific product
    (e.g. ``DPB`` / ``ESP``) are preserved verbatim.

    Returns the count of stamped entries (zero when no override
    is given, the override is ``Common``, or every entry has
    already been operator-tagged away from the default wildcard).
    """
    default = (default_product_type or "").strip()
    if not default or default.lower() == "common":
        return 0
    filled = 0
    for entry in document.dids:
        current = (entry.product_type or "").strip()
        if not current or current.lower() == "common":
            entry.product_type = default
            filled += 1
    return filled


# Backwards-compat alias: existing import sites call the old name.
# Removed in a future minor; currently kept undocumented.
apply_product_scope_defaults = apply_product_type_defaults


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass
class FSCSBuildSkip:
    """Diagnostic for one input record that failed to enter the document.

    Populated by :func:`build_fscs_document_with_report` so Phase 1 can
    render a human-readable generation report (``kept`` vs ``skipped``
    vs ``filtered``). We keep the raw record around rather than just the
    error string so reviewers / future linters can reconstruct what the
    JSON said without re-reading the file.

    * ``index``   -- 0-based index of the record inside the input list;
                     shown in the report so operators can locate it
                     quickly in the original JSON.
    * ``did_hex`` -- best-effort identifier extracted from the raw dict,
                     ``""`` when the record doesn't even have that
                     field.
    * ``reason``  -- short reason code. ``"validation"`` for Pydantic /
                     schema failures. Reserved for future reasons
                     (duplicate did_hex, etc.) that we don't model
                     today.
    * ``details`` -- pretty-printed error list (one item per validator
                     failure), suitable for dropping straight into the
                     report under the skipped row.
    * ``raw``     -- copy of the input record; intentionally preserved
                     for debugging and potential future ``--fix``
                     tooling.
    """

    index: int
    did_hex: str
    reason: str
    details: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FSCSBuildReport:
    """Aggregate build statistics returned alongside the document.

    * ``kept_count``     -- number of ``dids`` in the returned
                            :class:`FSCSDocument` (= records that passed
                            schema validation *and* ``supported_by_ecu``).
    * ``filtered_count`` -- records dropped because
                            ``supported_by_ecu != "Y"``. Not an error:
                            this is the ECU team's explicit "the
                            hardware doesn't expose this DID" signal.
    * ``skipped``        -- one :class:`FSCSBuildSkip` per record that
                            *was* supported-by-ecu but failed schema
                            validation. Empty list ⇒ clean build.
    * ``total_count``    -- convenience; equals the number of input
                            records.
    """

    kept_count: int
    filtered_count: int
    skipped: List[FSCSBuildSkip] = field(default_factory=list)
    total_count: int = 0


def build_fscs_document(
    records: Sequence[Dict[str, Any]],
    *,
    project: Optional[FSCSProject] = None,
    source_inputs: Optional[str] = None,
    generated_at: Optional[str] = None,
    default_product_type: Optional[str] = None,
) -> FSCSDocument:
    """Transform raw input records into a validated :class:`FSCSDocument`.

    Thin back-compat shim around :func:`build_fscs_document_with_report`;
    returns only the document and discards the skip list. Pre-v1.1
    callers that don't care about individual-record skip diagnostics
    (tests, legacy migration scripts) keep working without knowing about
    the report.

    Behaviour matches the legacy generator: validation failures used to
    raise ``ValidationError`` and abort the whole build, but v1.1
    downgrades that to per-record skipping. If you need to *see* the
    skips, call :func:`build_fscs_document_with_report` instead.
    """
    document, _report = build_fscs_document_with_report(
        records,
        project=project,
        source_inputs=source_inputs,
        generated_at=generated_at,
        default_product_type=default_product_type,
    )
    return document


def build_fscs_document_with_report(
    records: Sequence[Dict[str, Any]],
    *,
    project: Optional[FSCSProject] = None,
    source_inputs: Optional[str] = None,
    generated_at: Optional[str] = None,
    default_product_type: Optional[str] = None,
) -> Tuple[FSCSDocument, FSCSBuildReport]:
    """Same as :func:`build_fscs_document` but returns a skip/filter report.

    Used by Phase 1's ``generate_fscs`` entry point so the CLI can write
    ``outputs/fscs/fscs_generation_report.txt`` alongside the JSON. Test
    fixtures also call this directly to assert specific skip reasons.

    Validation policy (v1.1):

    * A ``ValidationError`` from Pydantic (bad did_hex, unknown
      storage_pos, size_bytes out of range, ...) adds the row to
      ``report.skipped`` and carries on. The document we return excludes
      the bad row but contains every other supported record.
    * Any *other* exception (``KeyError`` from a malformed nested dict,
      ``TypeError`` from a non-string did_hex, ...) is also caught and
      recorded with ``reason="build-error"`` so one malformed record
      can't take the whole batch down. This was the old failure mode:
      a single missing ``access`` key aborted the pipeline.
    """
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    entries: List[DIDFscsEntry] = []
    skipped: List[FSCSBuildSkip] = []
    filtered_count = 0

    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            # Defensive: a non-dict at the top level of the JSON list
            # can't be anything useful. Record it so the report flags
            # the structural issue instead of the exception bubbling up.
            skipped.append(FSCSBuildSkip(
                index=idx,
                did_hex="",
                reason="structure",
                details=[f"record is not a JSON object ({type(record).__name__})"],
                raw={},
            ))
            continue

        if record.get("supported_by_ecu") != "Y":
            filtered_count += 1
            continue

        try:
            entries.append(_build_did_entry(record))
        except ValidationError as exc:
            # Pydantic's ValidationError is already well-structured:
            # every entry has ``loc`` (the failed field path) and ``msg``
            # (human text). Format them as one line per failure so the
            # generation report stays readable -- operators typically
            # fix one field per skipped row.
            details = [
                f"{'.'.join(str(p) for p in err['loc']) or '<root>'}: {err['msg']}"
                for err in exc.errors()
            ]
            skipped.append(FSCSBuildSkip(
                index=idx,
                did_hex=str(record.get("did_hex") or ""),
                reason="validation",
                details=details,
                raw=dict(record),
            ))
        except Exception as exc:  # noqa: BLE001 -- intentionally broad
            # Any other failure during ``_build_did_entry`` is treated
            # identically: skip this record, keep building. We record
            # the exception class so the report distinguishes schema
            # errors (``validation``) from e.g. a missing required dict
            # key (``build-error``). Operators debugging stubborn skips
            # can rerun under ``--verbose`` to see the full traceback;
            # here we keep the report compact.
            skipped.append(FSCSBuildSkip(
                index=idx,
                did_hex=str(record.get("did_hex") or ""),
                reason="build-error",
                details=[f"{type(exc).__name__}: {exc}"],
                raw=dict(record),
            ))

    document = FSCSDocument(
        generated_at=generated_at,
        generator=FSCSGeneratorMeta(source_inputs=source_inputs),
        project=project or FSCSProject(),
        dids=entries,
    )
    apply_product_type_defaults(document, default_product_type=default_product_type)
    report = FSCSBuildReport(
        kept_count=len(entries),
        filtered_count=filtered_count,
        skipped=skipped,
        total_count=len(records),
    )
    return document, report


# ---------------------------------------------------------------------------
# Per-DID assembly
# ---------------------------------------------------------------------------


def _build_did_entry(record: Dict[str, Any]) -> DIDFscsEntry:
    did_hex = normalize_did_hex(record.get("did_hex", ""))
    did_name = _clean_name(record.get("did_name_en", ""))
    did_name_zh = record.get("did_name_zh") or None

    storage_pos = _normalise_storage_pos(record.get("storage_pos"))
    size_bytes = _coerce_size(record.get("size_bytes"))
    rw_state = _normalise_rw_state(record.get("rw_state", "R"))
    data_type = record.get("data_type") or "Unsigned"
    access = record.get("access") or {}

    service_22 = _build_service_access(access.get("service_22") or {}, did_hex)
    service_2e = _build_service_access(access.get("service_2e") or {}, did_hex)
    # The ``service_XX.supported`` flag is derived from ``rw_state``,
    # matching legacy behaviour where R/W capability drives .txt inclusion.
    service_22.supported = "R" in rw_state.upper()
    service_2e.supported = "W" in rw_state.upper()

    sub_fields = [
        _build_sub_field(sf, did_size_bytes=size_bytes)
        for sf in (record.get("sub_fields") or [])
    ]
    value_range = _derive_value_range(sub_fields)
    nvm_item = _derive_nvm_item(did_name, storage_pos)
    behavior_22, behavior_2e = _generate_service_behaviors(
        did_name=did_name,
        storage_pos=storage_pos,
        rw_state=rw_state,
        nvm_item=nvm_item,
        size_bytes=size_bytes,
    )
    service_22.behavior = behavior_22
    service_2e.behavior = behavior_2e

    return DIDFscsEntry(
        did_hex=did_hex,
        did_name=did_name,
        did_name_zh=did_name_zh,
        data_type=data_type,
        storage_position=storage_pos,
        size_bytes=size_bytes,
        rw_state=rw_state,
        nvm_item=nvm_item,
        service_22=service_22,
        service_2e=service_2e,
        sub_fields=sub_fields,
        value_range=value_range,
    )


# ---------------------------------------------------------------------------
# Sub-field / value-range / service-access helpers
# ---------------------------------------------------------------------------


def _build_sub_field(
    raw: Dict[str, Any], *, did_size_bytes: int | None = None,
) -> FSCSSubField:
    byte_idx, inferred_span = _parse_byte_spec(
        raw.get("byte"), did_size_bytes=did_size_bytes,
    )
    byte_span = int(raw.get("byte_span") or inferred_span or 1)
    unit = _blank_to_none(raw.get("unit")) or ""
    resolution, offset = _parse_resolution_offset(raw.get("method_en") or "")
    enum_mapping_raw = raw.get("method_en") or ""
    # Store the enum mapping only when it actually looks like a mapping
    # ("key=value" or "key:value"). Legacy inputs occasionally put
    # free-form notes here; keeping them out avoids accidental parsing
    # downstream.
    enum_mapping = (
        _normalise_enum_mapping(enum_mapping_raw)
        if _is_enum_mapping(enum_mapping_raw) else None
    )

    return FSCSSubField(
        byte_idx=byte_idx,
        byte_span=byte_span,
        bit=_clean_bit(raw.get("bit")),
        name_en=_clean_subfield_name(raw.get("name_en", "")) or "Unnamed",
        name_zh=raw.get("name_zh") or None,
        range_min=_canonicalize_hex_literal(_blank_to_none(raw.get("range_min_phy"))),
        range_max=_canonicalize_hex_literal(_blank_to_none(raw.get("range_max_phy"))),
        unit=unit,
        resolution=resolution,
        offset=offset,
        enum_mapping=enum_mapping,
        default_value=_canonicalize_hex_literal(_blank_to_none(raw.get("default_value_phy"))),
        # v1.3: pass through the questionnaire-supplied data_type and
        # encoding when available. The pydantic field validator
        # canonicalises raw strings via
        # :func:`schema.normalize_sub_field_data_type` /
        # :func:`schema.normalize_sub_field_encoding`, so unknown values
        # surface as a clear validation error rather than silently
        # demoting to ``None``.
        data_type=raw.get("data_type") or None,
        encoding=raw.get("encoding") or None,
    )


def _derive_value_range(sub_fields: List[FSCSSubField]) -> FSCSValueRange:
    """Collapse per-sub-field ranges into a single document-level value_range.

    * No sub_fields / empty ranges -> ``none``.
    * Exactly one sub_field with an enum mapping -> ``enum``.
    * Exactly one sub_field with a numeric range -> ``numeric``.
    * Multiple sub_fields each contributing ranges -> ``composite``
      (pre-rendered as ``"a ~ b; c ~ d"`` to match legacy output).
    """
    if not sub_fields:
        return FSCSValueRangeNone()

    if len(sub_fields) == 1:
        sf = sub_fields[0]
        if sf.enum_mapping:
            values = [v for v, _desc in _parse_enum_pairs(sf.enum_mapping)]
            if values:
                return FSCSValueRangeEnum(values=values)
        if sf.range_min and sf.range_max:
            return FSCSValueRangeNumeric(
                min=sf.range_min, max=sf.range_max, unit=sf.unit,
            )
        return FSCSValueRangeNone()

    # Composite: collect each sub-field's rendered range and join.
    parts: List[str] = []
    for sf in sub_fields:
        if sf.enum_mapping:
            values = [v for v, _desc in _parse_enum_pairs(sf.enum_mapping)]
            if values:
                parts.append(f"Enum: {', '.join(values)}")
                continue
        if sf.range_min and sf.range_max:
            unit = f" {sf.unit}" if sf.unit else ""
            parts.append(f"{sf.range_min} ~ {sf.range_max}{unit}")

    if not parts:
        return FSCSValueRangeNone()
    if len(parts) == 1:
        # Only one sub-field actually contributed; collapse.
        first = sub_fields[0]
        if first.enum_mapping:
            values = [v for v, _desc in _parse_enum_pairs(first.enum_mapping)]
            return FSCSValueRangeEnum(values=values)
        return FSCSValueRangeNumeric(
            min=first.range_min or "", max=first.range_max or "", unit=first.unit,
        )
    return FSCSValueRangeComposite(rendered="; ".join(parts))


def _build_service_access(block: Dict[str, Any], did_hex: str) -> FSCSServiceAccess:
    """Translate one ``access.service_XX`` sub-dict.

    ``block`` is the legacy nested dict with ``application.default``,
    ``security.level0`` etc. We flatten the "Y/N" flags into the two
    ordered lists the schema expects.
    """
    app = block.get("application") or {}
    sec = block.get("security") or {}

    sessions: List[str] = []
    if app.get("default") == "Y":
        sessions.append("defaultSession")
    if app.get("extended") == "Y":
        sessions.append("extendedDiagnosticSession")

    security_levels = _derive_security_levels(
        l0=sec.get("level0") == "Y",
        l1=sec.get("level1") == "Y",
        did_hex=did_hex,
    )

    return FSCSServiceAccess(
        supported=False,  # caller overwrites based on rw_state
        sessions=sessions,
        security_levels=security_levels,
    )


def _generate_service_behaviors(
    *,
    did_name: str,
    storage_pos: str,
    rw_state: str,
    nvm_item: str,
    size_bytes: int,
) -> tuple[str, str]:
    """Seed per-service behavior text from storage class.

    This intentionally mirrors the simpler parts of did-toolkit-platform's
    FSCSBehavior templates while keeping the current skill's JSON shape as
    two operator-editable strings under ``service_22`` / ``service_2e``.
    """
    is_read = "R" in (rw_state or "").upper()
    is_write = "W" in (rw_state or "").upper()
    storage = (storage_pos or "").upper()

    read_behavior = ""
    write_behavior = ""

    if storage == "EEPROM":
        suffix = f" {nvm_item.strip()}" if nvm_item.strip() else ""
        if is_read:
            read_behavior = f"Read from NVM item:{suffix}"
        if is_write:
            write_behavior = f"Write to NVM item:{suffix}"
    elif storage == "RAM":
        if is_read:
            read_behavior = "interface: "
        if is_write:
            write_behavior = "interface: "
    elif storage == "ROM":
        if is_read:
            read_behavior = _render_rom_hardcode_lines(
                _pascal_did_name(did_name), size_bytes,
            )
        # Writes to ROM are exceptional; leave the 2E side for the operator.

    return read_behavior, write_behavior


def _render_rom_hardcode_lines(pascal_name: str, size_bytes: int) -> str:
    """Format one hardcode placeholder per DID byte."""
    span = max(1, size_bytes)
    constants = "\n".join(
        f"C_DID_{pascal_name}_Byte{i}_UB = 0x"
        for i in range(span)
    )
    return f"HardCode:\n{constants}"


def _derive_security_levels(
    *, l0: bool, l1: bool, did_hex: str,
) -> List[FSCSSecurityLevel]:
    """Reproduce legacy security-level resolution rules.

    * Both L0 and L1 supported -> emit only L0 (with explanatory note).
    * L0 only -> emit L0 + warn (handled by the caller via ``warnings``
      module when desired; the data model stays warning-free).
    * L1 only -> emit bare L1.
    * Neither -> empty list.
    """
    del did_hex  # legacy emits a runtime warning here; we stay silent
    note = "(means no security access assurance)"
    if l0 and l1:
        return [FSCSSecurityLevel(level="L0", note=note)]
    if l1 and not l0:
        return [FSCSSecurityLevel(level="L1")]
    if l0 and not l1:
        return [FSCSSecurityLevel(level="L0", note=note)]
    return []


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_BYTE_RANGE_RE = re.compile(r"^\s*(?P<start>\d+)\s*[-~]\s*(?P<end>\d+)\s*$")
_BYTE_INDEX_RE = re.compile(r"^\s*\d+\s*$")
_RESOLUTION_RE = re.compile(r"\bResolution\s*[:=]\s*(?P<value>[^\r\n;]+)", re.IGNORECASE)
_OFFSET_RE = re.compile(r"\bOffset\s*[:=]\s*(?P<value>[^\r\n;]+)", re.IGNORECASE)
_HEX_TOKEN_RE = re.compile(r"0[xX][0-9A-Fa-f]+")
_ENUM_KEY_RE = re.compile(
    r"^\s*(?:0[xX][0-9A-Fa-f]+|\d+)"
    r"(?:\s*[-~]\s*(?:0[xX][0-9A-Fa-f]+|\d+))?\s*$"
)


def _clean_name(name: Any) -> str:
    """Strip CJK characters; the FSCS .txt format is English-only."""
    if not isinstance(name, str) or not name:
        return ""
    return _CJK_RE.sub("", name).strip()


def _clean_subfield_name(name: Any) -> str:
    """Strip CJK and collapse embedded newlines / repeated whitespace."""
    if not isinstance(name, str) or not name:
        return ""
    no_cjk = _CJK_RE.sub("", name)
    return " ".join(no_cjk.split()).strip()


def _clean_bit(raw: Any) -> str:
    value = str(raw or "All").strip()
    return value if value and value.lower() not in {"null", "none"} else "All"


def _parse_byte_spec(
    raw_byte: Any, *, did_size_bytes: int | None = None,
) -> Tuple[Optional[int], int]:
    """Parse legacy input ``byte`` into structured index/span."""
    if raw_byte is None:
        return None, 1
    value = str(raw_byte).strip()
    if not value or value.lower() in {"null", "none"}:
        return None, 1
    if value.lower() == "all":
        return 0, max(1, did_size_bytes or 1)
    match = _BYTE_RANGE_RE.match(value)
    if match:
        start = int(match.group("start"))
        end = int(match.group("end"))
        if end < start:
            start, end = end, start
        return start, end - start + 1
    if _BYTE_INDEX_RE.match(value):
        return int(value), 1
    return None, 1


def _parse_resolution_offset(method_en: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract physical conversion metadata from free-form ``method_en``."""
    resolution_match = _RESOLUTION_RE.search(method_en or "")
    offset_match = _OFFSET_RE.search(method_en or "")
    resolution = _blank_to_none(resolution_match.group("value")) if resolution_match else None
    offset = _blank_to_none(offset_match.group("value")) if offset_match else None
    return resolution, offset


def _coerce_size(raw: Any) -> int:
    """Robustly parse ``size_bytes`` from the raw input.

    Legacy inputs occasionally have ``"TBD"``, ``"N/A"`` or an empty
    string. All of those collapse to 1 so downstream consumers can
    safely compute byte offsets.
    """
    if isinstance(raw, int):
        return max(1, raw)
    if isinstance(raw, str) and raw.strip().isdigit():
        return max(1, int(raw.strip()))
    return 1


def _normalise_rw_state(raw: Any) -> str:
    if not isinstance(raw, str):
        return "R"
    value = raw.strip().upper()
    return value if value in {"R", "W", "RW"} else "R"


def _normalise_storage_pos(raw: Any) -> str:
    """Accept legacy spellings like ``"eeprom"`` / ``"Eeprom"`` / ``"nvm"``.

    The schema only allows canonical ``"EEPROM"`` / ``"RAM"`` but
    :func:`normalize_storage_position` collapses the ``"NVM"`` alias
    into ``"EEPROM"`` (Bosch DCOM practice uses the two interchangeably
    for NvM-backed storage). Unknown strings are returned upper-cased
    so pydantic's ``Literal`` check still rejects typos (``"FLASH"``
    etc.) -- we only alias values that are genuinely synonymous, not
    anything that happens to be non-canonical.

    Non-strings fall back to ``"RAM"`` to preserve the legacy
    behaviour for completely missing ``storage_pos`` fields.
    """
    if not isinstance(raw, str):
        return "RAM"
    return normalize_storage_position(raw)


def _blank_to_none(raw: Any) -> Optional[str]:
    """Translate empty / legacy null markers to ``None``.

    FSCS historically uses ``"/"`` as a "not applicable" marker; we
    collapse it into ``None`` so downstream code only has to check one
    sentinel.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.lower() in {"", "/", "null", "none"}:
            return None
        return stripped
    return str(raw)


def _is_enum_mapping(raw: str) -> bool:
    """Heuristic: is this ``method_en`` a ``key=value`` mapping?"""
    if not raw:
        return False
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line or ":" in line:
            sep = "=" if "=" in line else ":"
            key = line.split(sep, 1)[0].strip()
            if _ENUM_KEY_RE.match(key):
                return True
    return False


def _normalise_enum_mapping(raw: str) -> str:
    """Normalise enum mapping text to one ``key=English desc`` per line."""
    return "\n".join(
        f"{key}={desc}" if desc else key
        for key, desc in _parse_enum_pairs(raw)
    )


def _parse_enum_pairs(raw: str) -> List["tuple[str, str]"]:
    """Extract ``(key, desc)`` pairs from an enum-mapping string.

    Accepts both ``"="`` and ``":"`` separators.  Returns ``[]`` for
    unparseable input so callers can fall back to a numeric range.
    """
    out: List[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in ("=", ":"):
            if sep in line:
                k, v = line.split(sep, 1)
                k = _normalise_enum_key(k.strip())
                v = _clean_subfield_name(v)
                if k and _ENUM_KEY_RE.match(k):
                    out.append((k, v))
                break
    return out


def _normalise_enum_key(key: str) -> str:
    """Standardise explicit 0x tokens without changing decimal enum values."""
    return _HEX_TOKEN_RE.sub(lambda m: _normalise_hex_token(m.group(0)), key)


def _normalise_hex_token(token: str) -> str:
    digits = token[2:]
    if not digits:
        return token
    width = max(2, len(digits))
    return f"0x{int(digits, 16):0{width}X}"


def _canonicalize_hex_literal(raw: Optional[str]) -> Optional[str]:
    """Normalise explicit hex literals while preserving decimal strings."""
    if raw is None:
        return None
    return _HEX_TOKEN_RE.sub(lambda m: _normalise_hex_token(m.group(0)), raw)


def _derive_nvm_item(did_name: str, storage_pos: str) -> str:
    """Mirror the legacy naming rule.

    EEPROM-backed DIDs get ``NVM_ID_DCOM_<CapitalisedName>``; RAM-backed
    DIDs get the empty string. The empty string is intentional and
    meaningful -- it's what the migration was supposed to rescue from
    the ambiguous ``in (None, "")`` dance.
    """
    if (storage_pos or "").upper() != "EEPROM":
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", did_name or "")
    if not cleaned:
        return ""
    capitalised = cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper()
    return f"{NVM_ID_PREFIX}{capitalised}"


def _pascal_did_name(did_name: str) -> str:
    """Return a C-identifier-friendly PascalCase DID name stem."""
    parts = re.findall(r"[A-Za-z0-9]+", did_name or "")
    if not parts:
        return "DID"
    return "".join(part[:1].upper() + part[1:] for part in parts)
