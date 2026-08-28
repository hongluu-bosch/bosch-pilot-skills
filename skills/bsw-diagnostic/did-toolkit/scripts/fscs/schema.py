"""Pydantic schema for ``outputs/fscs/fscs.json``.

This is the *authoritative* data model for FSCS content. Phase 1
produces an ``FSCSDocument`` from the raw ``inputs/*.json`` and writes
it to disk as JSON; Phase 2, Phase 3, the review pipeline and the CSV
edit round-trip all read the same model back in.

Design notes
------------

* ``did_hex`` is stored **bare uppercase** (``"F190"``) -- not
  ``"$F190h"``, not ``"0xF190"``. Callers render the prefix they want.
  :func:`normalize_did_hex` accepts all three shapes so legacy inputs
  keep working during the migration.

* ``nvm_item`` is always a string. Empty string (``""``) encodes
  "RAM-backed, no NVM" -- the historical regex bug the migration
  closes. ``None`` is deliberately not used so downstream code can
  rely on ``did.nvm_item == ""`` rather than the more error-prone
  ``did.nvm_item in (None, "")``.

* ``value_range`` is a tagged union discriminated on ``kind``.
  Downstream code switches on ``kind`` rather than re-parsing
  ``"0 ~ 255"`` / ``"Enum: 0x00, 0x01"`` free-form strings.

* ``sub_fields`` preserves the rich per-byte information from the
  original ``inputs/*.json`` so the ``.txt`` renderer can faithfully
  reproduce the Positive Response Message tables.

* ``free_text`` carries optional overrides for hand-tuned sections
  (description prose, full request/response blocks). Leaving them
  ``None`` means "auto-render"; a populated value wins over the
  generated default.

* ``service_22.behavior`` / ``service_2e.behavior`` carry side-specific
  implementation hints. Phase 1 seeds them from storage class and the
  xlsx edit loop lets operators replace the text.

* ``extra='forbid'`` is set on every model -- unknown keys fail loudly
  at load time so typos don't silently degrade.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = "1.5"


# ---------------------------------------------------------------------------
# Scalar enums / helpers
# ---------------------------------------------------------------------------


DataType = Literal[
    "ASCII", "Unsigned", "Signed", "HEX", "Bytefield",
    "Texttable", "enum", "Linear", "Identity",
]
StoragePos = Literal["EEPROM", "RAM", "ROM"]


# v1.3: per-sub-field business-semantic data type (what the byte means
# to a human reader) and bit-level encoding (how the byte is decoded
# from the raw bytestream). Kept independent so a "Numeric" sub-field
# can be either ``Signed`` or ``Unsigned`` without spawning a
# combinatorial enum. Both are optional: legacy v1.2 documents and
# minimal hand-edited records that lack the questionnaire context can
# still load.
SubFieldDataType = Literal[
    "Numeric",     # plain integer / fixed-point physical value
    "Enum",        # discrete coded values with name mapping
    "BitField",    # bit-packed flags, sub-bit semantics
    "Hex",         # raw hex display, no physical interpretation
    "ASCII",       # text payload
    "BCD",         # binary-coded decimal
    "Composite",   # placeholder for sub-fields that aggregate others
]
SubFieldEncoding = Literal[
    "Unsigned",
    "Signed",
    "Float32",
    "Float64",
    "ASCIIString",
    "RawBytes",
]


_SUB_FIELD_DATA_TYPE_ALIASES: dict[str, str] = {
    # Direct synonyms / case variations.
    "NUMERIC": "Numeric",
    "NUM": "Numeric",
    "INT": "Numeric",
    "INTEGER": "Numeric",
    # Legacy DID-level DataType literals reused at sub-field level by
    # some questionnaires. ``Identity`` (no scaling) and ``Linear``
    # (resolution+offset scaling) are both numeric in nature.
    "IDENTITY": "Numeric",
    "LINEAR": "Numeric",
    "ENUM": "Enum",
    "ENUMERATION": "Enum",
    "TEXTTABLE": "Enum",
    "BITFIELD": "BitField",
    "BIT FIELD": "BitField",
    "BITS": "BitField",
    "BIT": "BitField",
    "HEX": "Hex",
    "BYTEFIELD": "Hex",
    "RAW": "Hex",
    "ASCII": "ASCII",
    "STRING": "ASCII",
    "BCD": "BCD",
    "COMPOSITE": "Composite",
    "STRUCT": "Composite",
}
_SUB_FIELD_ENCODING_ALIASES: dict[str, str] = {
    "UNSIGNED": "Unsigned",
    "UINT": "Unsigned",
    "UINT8": "Unsigned",
    "UINT16": "Unsigned",
    "UINT32": "Unsigned",
    "U8": "Unsigned",
    "U16": "Unsigned",
    "U32": "Unsigned",
    "SIGNED": "Signed",
    "INT": "Signed",
    "SINT": "Signed",
    "INT8": "Signed",
    "INT16": "Signed",
    "INT32": "Signed",
    "SINT8": "Signed",
    "SINT16": "Signed",
    "SINT32": "Signed",
    "S8": "Signed",
    "S16": "Signed",
    "S32": "Signed",
    "FLOAT": "Float32",
    "FLOAT32": "Float32",
    "F32": "Float32",
    "REAL": "Float32",
    "DOUBLE": "Float64",
    "FLOAT64": "Float64",
    "F64": "Float64",
    "ASCIISTRING": "ASCIIString",
    "STRING": "ASCIIString",
    "ASCII": "ASCIIString",
    "RAWBYTES": "RawBytes",
    "RAW": "RawBytes",
    "BYTES": "RawBytes",
    "BYTEFIELD": "RawBytes",
    "HEX": "RawBytes",
}


def normalize_sub_field_data_type(raw: Any) -> Any:
    """Canonicalise a sub-field ``data_type`` string.

    Accepts case-insensitive synonyms (``"numeric"``, ``"int"``,
    ``"BIT FIELD"``); returns one of the seven canonical values, or
    leaves the value untouched (so pydantic raises a clear error) when
    no synonym matches. ``None`` and empty string pass through as
    ``None`` so callers can omit the field cleanly.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    key = raw.strip().upper()
    if not key:
        return None
    return _SUB_FIELD_DATA_TYPE_ALIASES.get(key, raw)


def normalize_sub_field_encoding(raw: Any) -> Any:
    """Canonicalise a sub-field ``encoding`` string."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    key = raw.strip().upper()
    if not key:
        return None
    return _SUB_FIELD_ENCODING_ALIASES.get(key, raw)


# Three semantic storage kinds + alias table:
#
# * ``EEPROM`` -- non-volatile, NvM-backed. Gets an ``NVM_ID_DCOM_*``
#   item and a PDM entry. ``NVM`` is an accepted synonym because Bosch
#   DCOM practice uses the two interchangeably for NvM-backed storage;
#   keeping distinct spellings here would only create spurious
#   validation errors on customer inputs.
# * ``RAM``    -- volatile runtime storage. No NVM item, no PDM entry.
# * ``ROM``    -- flash-constant, read-only DIDs (e.g. software-version
#   strings baked into the image). No NVM item, no PDM entry, no write
#   path. ``FLASH`` is an accepted synonym: in customer inputs "ROM"
#   and "Flash" both refer to the same compile-time-constant storage
#   class (on-chip flash holding code/const data), so we canonicalise
#   to ``ROM`` on load. Downstream generators emit the same skeleton
#   function body for either spelling; future releases may split the
#   two if the runtime behaviour diverges, at which point we simply
#   un-alias here.
#
# Unknown strings pass through upper-cased so pydantic's ``Literal``
# check still rejects typos (``"OTP"``, ``"HSM"`` etc.) with a clear
# error -- we only alias values that are genuinely synonymous.
_STORAGE_ALIASES: dict[str, str] = {
    "EEPROM": "EEPROM",
    "NVM": "EEPROM",
    "RAM": "RAM",
    "ROM": "ROM",
    "FLASH": "ROM",
}


def normalize_storage_position(raw: Any) -> Any:
    """Canonicalise a storage-position string.

    ``"NVM"`` / ``"nvm"`` / ``"Nvm"`` collapse to ``"EEPROM"``; already-
    canonical values pass through untouched. Unknown strings are
    returned as-is so pydantic's ``Literal`` check produces the usual
    type error instead of silent coercion. Non-strings pass through so
    pydantic can raise its own type error.
    """
    if not isinstance(raw, str):
        return raw
    key = raw.strip().upper()
    return _STORAGE_ALIASES.get(key, key)
RwState = Literal["R", "W", "RW"]
SessionName = Literal["defaultSession", "extendedDiagnosticSession"]
SecurityLevelCode = Literal["L0", "L1"]


_DID_HEX_RE = re.compile(r"^[0-9A-Fa-f]{1,8}$")
_BYTE_RANGE_RE = re.compile(r"^\s*(?P<start>\d+)\s*[-~]\s*(?P<end>\d+)\s*$")
_BYTE_INDEX_RE = re.compile(r"^\s*\d+\s*$")


def normalize_did_hex(raw: Any) -> str:
    """Normalise any reasonable DID hex spelling to bare uppercase.

    Accepts ``"F190"``, ``"0xF190"``, ``"$F190h"`` (case-insensitive).
    Returns the canonical form (``"F190"``) -- padded to at least four
    digits, upper-cased. Non-strings pass through unchanged so pydantic
    can raise its own type error downstream.
    """
    if not isinstance(raw, str):
        return raw
    v = raw.strip().upper()
    if v.startswith("$") and v.endswith("H"):
        v = v[1:-1]
    elif v.startswith("0X"):
        v = v[2:]
    if not _DID_HEX_RE.match(v):
        # Let pydantic surface the error with a proper message.
        return raw
    return v.zfill(4)


def _parse_legacy_byte_range(raw: Any) -> tuple[Optional[int], int]:
    """Best-effort migration for v1.1 ``byte_range`` strings."""
    if raw is None:
        return None, 1
    value = str(raw).strip()
    if not value or value.lower() in {"null", "none"}:
        return None, 1
    if value.upper() == "ALL":
        return 0, 1
    range_match = _BYTE_RANGE_RE.match(value)
    if range_match:
        start = int(range_match.group("start"))
        end = int(range_match.group("end"))
        if end < start:
            start, end = end, start
        return start, end - start + 1
    if _BYTE_INDEX_RE.match(value):
        return int(value), 1
    return None, 1


# ---------------------------------------------------------------------------
# Leaf models
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    """Base with ``extra='forbid'`` so typos surface as validation errors."""

    model_config = ConfigDict(extra="forbid")


class FSCSSecurityLevel(_Strict):
    """One line of the ``Security Level:`` block.

    The renderer emits ``"<level><space><note>"``; typical values are
    ``level="L0", note="(means no security access assurance)"`` and
    ``level="L1", note=None``. Storing them split (rather than as one
    free-form string) lets the review pipeline assert on ``level``
    without stringly-typed matching.
    """

    level: SecurityLevelCode
    note: Optional[str] = None


class FSCSSubField(_Strict):
    """One row of the Positive Response Message's data-record table.

    ``byte_idx`` is the 0-based byte position inside the DID data record
    (response ``Byte 4``); ``byte_span`` carries multi-byte signals. Legacy
    v1.1 documents that stored ``byte_range`` are migrated on load.
    """

    byte_idx: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "0-based byte position within the DID data record. None means "
            "the row continues the previous byte, typically for bit-packed fields."
        ),
    )
    byte_span: int = Field(
        default=1,
        ge=1,
        description="Number of bytes occupied by this field.",
    )
    bit: str = "All"
    name_en: str
    name_zh: Optional[str] = None
    range_min: Optional[str] = None
    range_max: Optional[str] = None
    unit: str = ""
    resolution: Optional[str] = Field(
        default=None,
        description="Physical conversion resolution; physical = logical * resolution + offset.",
    )
    offset: Optional[str] = Field(
        default=None,
        description="Physical conversion offset; physical = logical * resolution + offset.",
    )
    enum_mapping: Optional[str] = Field(
        default=None,
        description='Multi-line mapping like "0x00=Normal\\n0x01=Sport".',
    )
    default_value: Optional[str] = None
    data_type: Optional[SubFieldDataType] = Field(
        default=None,
        description=(
            "v1.3: per-sub-field business semantic. None when the source "
            "questionnaire does not declare one (legacy v1.2 documents)."
        ),
    )
    encoding: Optional[SubFieldEncoding] = Field(
        default=None,
        description=(
            "v1.3: bit-level encoding (Unsigned/Signed/Float32/Float64/"
            "ASCIIString/RawBytes). Optional; the renderer infers when "
            "absent."
        ),
    )

    @field_validator("data_type", mode="before")
    @classmethod
    def _coerce_data_type(cls, v: Any) -> Any:
        return normalize_sub_field_data_type(v)

    @field_validator("encoding", mode="before")
    @classmethod
    def _coerce_encoding(cls, v: Any) -> Any:
        return normalize_sub_field_encoding(v)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_byte_range(cls, data: Any) -> Any:
        """Translate v1.1 ``byte_range`` into ``byte_idx`` + ``byte_span``."""
        if not isinstance(data, dict) or "byte_range" not in data:
            return data
        migrated = dict(data)
        raw = migrated.pop("byte_range")
        byte_idx, byte_span = _parse_legacy_byte_range(raw)
        migrated.setdefault("byte_idx", byte_idx)
        migrated.setdefault("byte_span", byte_span)
        return migrated


class FSCSServiceAccess(_Strict):
    """Per-service (22 or 2E) availability descriptor.

    Two independent gates determine whether this service contributes to
    downstream artefacts:

    * ``supported`` -- *structural* availability derived from the DID's
      ``rw_state``. ``supported=False`` means the DID fundamentally does
      not offer this service (e.g. a read-only DID has
      ``service_2e.supported=False``). Never toggled by operator edits.
    * ``used`` -- *selection* flag owned by the operator via the
      xlsx edit table. Defaults to ``True`` so freshly-generated
      documents include every supported DID. Flipping it to ``False``
      in the CSV is how a reviewer says "this DID is in scope for FSCS,
      but I don't want it emitted into FSCS_XX.txt / ARXML / C code on
      this release".

    The effective rule is ``supported AND used``; consumers read this
    via :attr:`effective` so the "both gates must be true" convention
    lives in exactly one place. ``fscs.json`` always keeps the full
    input set -- filtering happens at render/generation time, never by
    dropping records from the authoritative document.
    """

    supported: bool
    used: bool = True
    sessions: List[SessionName] = []
    security_levels: List[FSCSSecurityLevel] = []
    behavior: str = ""

    @property
    def effective(self) -> bool:
        """True iff the DID should be emitted into downstream artefacts.

        Downstream = FSCS ``.txt`` renderers, ARXML generator, C code
        generator, and all review tooling. One helper means a future
        tweak to the gate (say, adding an ECU-availability flag) flows
        everywhere without hunting through consumers.
        """
        return self.supported and self.used


# ---------------------------------------------------------------------------
# value_range tagged union
# ---------------------------------------------------------------------------


class FSCSValueRangeNone(_Strict):
    kind: Literal["none"] = "none"


class FSCSValueRangeNumeric(_Strict):
    kind: Literal["numeric"] = "numeric"
    min: str
    max: str
    unit: str = ""


class FSCSValueRangeEnum(_Strict):
    kind: Literal["enum"] = "enum"
    values: List[str]


class FSCSValueRangeComposite(_Strict):
    """Multiple sub_fields each contributing a range.

    Rather than model the composite structurally, we keep the already-
    formatted rendering. This preserves FSCS's current habit of joining
    composite ranges with ``"; "`` without forcing a deeper model.
    """

    kind: Literal["composite"] = "composite"
    rendered: str


FSCSValueRange = Annotated[
    Union[
        FSCSValueRangeNone,
        FSCSValueRangeNumeric,
        FSCSValueRangeEnum,
        FSCSValueRangeComposite,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Free-text override slots
# ---------------------------------------------------------------------------


class FSCSFreeText(_Strict):
    """Optional hand-tuned overrides for sections the renderer auto-generates.

    ``None`` -> "auto-render"; any non-``None`` value wins. Populated
    solely by operator edits when a reviewer needs to hand-edit boilerplate
    (which they shouldn't normally need to, given Phase 1 templates
    cover the common case).
    """

    description_read: Optional[str] = None
    description_write: Optional[str] = None
    request_block_22: Optional[str] = None
    response_block_22: Optional[str] = None
    request_block_2e: Optional[str] = None
    response_block_2e: Optional[str] = None
    custom_paragraphs: List[str] = []


# ---------------------------------------------------------------------------
# DID entry
# ---------------------------------------------------------------------------


class DIDFscsEntry(_Strict):
    """One DID's worth of FSCS content -- one row in the xlsx edit table."""

    did_hex: str = Field(description="Bare uppercase hex, e.g. 'F190'")
    did_name: str = Field(min_length=1)
    did_name_zh: Optional[str] = None

    data_type: DataType
    storage_position: StoragePos
    size_bytes: int = Field(ge=1, le=4096)
    rw_state: RwState
    nvm_item: str = Field(
        default="",
        description='Empty string for RAM-backed DIDs; never None.',
    )

    service_22: FSCSServiceAccess
    service_2e: FSCSServiceAccess

    sub_fields: List[FSCSSubField] = []
    value_range: FSCSValueRange = FSCSValueRangeNone()
    free_text: FSCSFreeText = Field(default_factory=FSCSFreeText)

    # Per-DID product-type tag — the single source of truth for
    # both the Phase 2 multi-product filter and the Phase 4 DOORS
    # ``RB_Product`` cell. Defaults to the wildcard ``"Common"``
    # (Phase 2 emits for every build target; DOORS fills
    # RB_Product with every value in ``value_maps.RB_Product``
    # newline-joined). A non-empty non-Common string (e.g.
    # ``"DPB"`` / ``"ESP"``) restricts emission to runs targeting
    # that product; Phase 2 stamps mismatched DIDs
    # ``OUT_OF_SCOPE`` in ``validation_report.txt`` and excludes
    # them from the ARXML; Phase 4 DOORS fills the ``RB_Product``
    # cell from the same field. The document migrator normalises
    # ``None`` / missing / empty-string / whitespace-only values
    # to ``"Common"`` so the on-disk JSON always carries an
    # explicit value and CSV exports always render a non-empty
    # cell.
    product_type: Optional[str] = Field(
        default="Common",
        description=(
            "Per-DID product-type tag. Defaults to the wildcard "
            "``Common`` (applies to every product). A non-empty "
            "non-Common string (DPB / ESP / ESPCL / IPB / RBU) "
            "restricts the DID to runs targeting that product. "
            "Drives both the Phase 2 build-target filter and the "
            "Phase 4 DOORS RB_Product cell."
        ),
    )

    @field_validator("did_hex", mode="before")
    @classmethod
    def _coerce_did_hex(cls, v: Any) -> Any:
        return normalize_did_hex(v)

    @field_validator("storage_position", mode="before")
    @classmethod
    def _coerce_storage_position(cls, v: Any) -> Any:
        return normalize_storage_position(v)

    @field_validator("product_type", mode="before")
    @classmethod
    def _normalise_product_type(cls, v: Any) -> Any:
        """Collapse ``None`` / empty / whitespace-only to the wildcard
        ``"Common"`` so direct Python construction matches the
        on-disk migrator: the invariant is ``product_type`` is always
        a non-empty string after model build.
        """
        if v is None:
            return "Common"
        if isinstance(v, str) and not v.strip():
            return "Common"
        return v

    @field_validator("did_hex")
    @classmethod
    def _validate_did_hex(cls, v: str) -> str:
        if not _DID_HEX_RE.match(v):
            raise ValueError(
                f"did_hex must be hex digits only (got {v!r}). "
                "Use forms like 'F190', '0xF190', or '$F190h' on input; "
                "the canonical stored form is bare uppercase."
            )
        return v.upper()


# ---------------------------------------------------------------------------
# Document root
# ---------------------------------------------------------------------------


class FSCSProject(_Strict):
    """Project-level metadata echoed back from ``project.json``.

    There is no project-level ``product_type`` field — each DID
    carries its own :attr:`DIDFscsEntry.product_type` and the build
    target is the set of products tagged on `used` DIDs. Legacy
    documents whose project block still carries a ``product_type``
    string load cleanly: :class:`FSCSDocument` strips the legacy
    key in its ``mode='before'`` migrator before pydantic gets a
    chance to enforce ``extra='forbid'``.
    """

    customer_name: Optional[str] = None


class FSCSGeneratorMeta(_Strict):
    """Provenance: which tool+inputs produced this document."""

    tool: str = "did-toolkit/generate_fscs.py"
    source_inputs: Optional[str] = None


class FSCSDocument(_Strict):
    """Top-level envelope: metadata + ordered list of DID entries."""

    schema_version: Literal["1.5"] = SCHEMA_VERSION
    generated_at: str = ""
    generator: FSCSGeneratorMeta = Field(default_factory=FSCSGeneratorMeta)
    project: FSCSProject = Field(default_factory=FSCSProject)
    dids: List[DIDFscsEntry]

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_schema(cls, data: Any) -> Any:
        """Silently bump pre-1.5 documents to the current schema.

        Each historical jump has been purely additive or a rename:

        * 1.0 / 1.1 -> per-sub-field ``byte_range`` -> ``byte_idx``
          migration (lives on :class:`FSCSSubField`).
        * 1.2 added two optional per-sub-field fields (``data_type``
          / ``encoding``); pydantic fills missing keys with ``None``.
        * 1.3 -> 1.4 added one optional per-DID field
          (``product_scope``); missing keys default to ``None`` and
          downstream code treats that as "applies to every product".
        * 1.4 -> 1.5 (this build) renamed ``product_scope`` to
          ``product_type`` per DID — the field is now the single
          source of truth for both Phase 2 filtering and DOORS
          ``RB_Product``. Legacy v1.4 docs are migrated key-by-key
          here; the now-rejected ``project.product_type`` is
          stripped at the same time.

        Loading the most recent stable version (currently ``1.5``)
        is a no-op.
        """
        if not isinstance(data, dict):
            return data

        upgraded = dict(data)
        legacy_versions = {"1.0", "1.1", "1.2", "1.3", "1.4"}
        if upgraded.get("schema_version") in legacy_versions:
            upgraded["schema_version"] = SCHEMA_VERSION

        # 1.4 -> 1.5: per-DID rename product_scope -> product_type.
        # Done unconditionally (rather than gated on schema_version)
        # so a hand-edited v1.5 doc that still carries the old key
        # also migrates cleanly. The old key is dropped after the
        # value is moved over.
        #
        # Also normalise ``product_type`` to a non-empty value here:
        # ``None`` / missing / empty-string / whitespace-only collapse
        # to the wildcard ``"Common"`` so the on-disk JSON always
        # carries an explicit tag and downstream consumers (Phase 2
        # filter, DOORS RB_Product, CSV exporter) never have to
        # special-case the absent state.
        dids = upgraded.get("dids")
        if isinstance(dids, list):
            migrated_dids = []
            for did in dids:
                if isinstance(did, dict):
                    did = dict(did)
                    if "product_scope" in did:
                        legacy_value = did.pop("product_scope")
                        did.setdefault("product_type", legacy_value)
                    raw_pt = did.get("product_type")
                    if raw_pt is None or (isinstance(raw_pt, str) and not raw_pt.strip()):
                        did["product_type"] = "Common"
                migrated_dids.append(did)
            upgraded["dids"] = migrated_dids

        # The project block carries no global ``product_type`` field.
        # Strip it silently when a legacy document still carries one
        # so loading doesn't trip the project block's
        # ``extra='forbid'``. We swallow rather than warn because the
        # data is still represented per-DID; the legacy global value
        # was only ever a default that is no longer applied.
        project = upgraded.get("project")
        if isinstance(project, dict) and "product_type" in project:
            project = {k: v for k, v in project.items() if k != "product_type"}
            upgraded["project"] = project

        return upgraded
