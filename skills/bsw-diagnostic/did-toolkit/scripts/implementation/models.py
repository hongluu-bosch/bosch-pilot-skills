"""Data models for the implementation phase.

Two models live here:

* :class:`DIDImplementationInfo` -- the legacy dataclass used throughout the
  generator pipeline. It carries already-parsed FSCS fields and validation
  errors; every downstream helper (naming / parsers / generators) reads and
  writes attributes on this object.

* :class:`DIDInput` / :class:`DIDSubField` -- a pydantic v2 model that
  validates a single raw DID entry straight out of ``inputs/<project>.json``.
  The pipeline currently does not yet round-trip these models (that's a
  future step); they are exposed now so callers that want fail-fast JSON
  validation can opt in via :meth:`DIDInput.model_validate`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


@dataclass
class DIDImplementationInfo:
    """DID information for implementation generation.

    Populated by :func:`scripts.fscs.adapter.to_did_implementation_infos`
    from the authoritative :class:`FSCSDocument`. Kept as a plain
    dataclass (not pydantic) because generation code mutates
    ``validation_errors`` in place and relies on free attribute access.

    v1.27.0 added the three ``behavior_*`` / ``did_name_zh`` /
    ``product_type`` fields so the read/write body generators can
    embed the operator-curated FSCS Behavior text directly into the
    ``TODO(agent)`` block of each non-EEPROM ``.c`` stub. Briefs (the
    old per-DID ``_briefs/<HEX>_<svc>.md`` artefacts) were dropped in
    favour of self-contained ``.c`` stubs so the agent can fill in
    every DID without a second round-trip.
    """

    did_hex: str
    did_name: str
    data_type: str
    storage_pos: str
    size_bytes: str
    rw_state: str  # 'R' or 'RW'
    nvm_item: str = ""
    value_range: str = ""
    is_enum: bool = False
    enum_values: List[str] = field(default_factory=list)
    numeric_min: str = ""
    numeric_max: str = ""
    security_level: str = "L0"
    sessions: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    did_name_zh: str = ""
    product_type: str = ""
    behavior_22: str = ""
    behavior_2e: str = ""

    def __post_init__(self) -> None:
        if not self.sessions:
            self.sessions = ['defaultSession']
        if not self.validation_errors:
            self.validation_errors = []


class DIDSubField(BaseModel):
    """A single sub-field entry inside a DID's ``sub_fields`` array.

    All fields are optional / permissive on purpose because real inputs have
    drifted over time and we do not want validation to reject legacy JSON.
    What we DO enforce is that values remain strings (to match the
    hand-written parsers in :mod:`scripts.implementation.parsers`).
    """

    model_config = ConfigDict(extra='allow')

    byte: Optional[str] = None
    bit: Optional[str] = None
    name_en: Optional[str] = None
    name_zh: Optional[str] = None
    range_min_phy: Optional[str] = None
    range_max_phy: Optional[str] = None
    unit: Optional[str] = None
    method_en: Optional[str] = None
    method_zh: Optional[str] = None
    default_value_phy: Optional[str] = None


class DIDInput(BaseModel):
    """A single DID definition from ``inputs/<project>.json``.

    Validates enough fields to catch shape-level mistakes early:

    * ``did_hex`` / ``did_name_en`` must be non-empty strings,
    * ``rw_state`` is restricted to ``"R"`` or ``"RW"``,
    * ``supported_by_ecu`` must be ``"Y"`` or ``"N"``.

    Everything else is permissive (``extra='allow'``) so fields that appear
    only in some vehicle variants pass through unchanged; the generators
    never fail on unknown keys.
    """

    model_config = ConfigDict(extra='allow')

    did_hex: str = Field(min_length=1)
    did_name_en: str = Field(min_length=1)
    did_name_zh: Optional[str] = None
    cvt: Optional[str] = None
    supported_by_ecu: str = Field(pattern=r'^[YN]$')
    rw_state: str = Field(pattern=r'^(R|RW)$')
    size_bytes: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    storage_pos: str = Field(min_length=1)
    access: Dict[str, Any] = Field(default_factory=dict)
    sub_fields: List[DIDSubField] = Field(default_factory=list)

    @classmethod
    def validate_many(cls, raw: List[Dict[str, Any]]) -> List["DIDInput"]:
        """Validate a JSON array. Raises ``pydantic.ValidationError`` on the
        first bad entry, with a path pointing at the offending field."""
        return [cls.model_validate(item) for item in raw]
