"""Compute the per-run product fan-out work-set from an FSCSDocument.

Phase 2 / Phase 3 do not take a ``--product-type`` CLI flag. They fan
out over the set of products that actually appear on a ``used`` DID
in ``fscs.json``. This module is the single place that decides "which
products is this run going to build for?" so the orchestrators have
one normalised list to iterate.

Contract:

* Input: a fully-loaded :class:`scripts.fscs.FSCSDocument` plus the
  recognised product whitelist.
* Output: a stable, deterministically-ordered tuple of canonical
  product short names. Canonical = upper-case for the five real
  products (``DPB`` / ``ESP`` / ``ESPCL`` / ``IPB`` / ``RBU``) and
  the title-case literal ``Common`` for the cross-product wildcard
  (matching :data:`scripts.implementation.paths.COMMON_TOKEN`).
* Side-effects: none. Caller decides what to do with an empty
  work-set (Phase 2 / Phase 3 print a warning and skip; downstream
  phases like Phase 4 / DOORS still read ``fscs.json`` directly).

Filtering rules:

1. ``used_flag``-driven: only DIDs where
   ``service_22.used or service_2e.used`` contribute. Operator-
   deselected DIDs (both services off) are silently excluded — they
   were already DESELECTED in Phase 2's validation report.
2. Empty / missing ``product_type`` → silently treated as
   ``Common`` (legacy semantics: an unset tag means "applies
   everywhere").
3. Case-insensitive matching against the recognised whitelist; the
   canonical spelling is what we return. ``DpB`` → ``DPB``.
4. Non-recognised values are a hard error: the function raises
   :class:`UnknownProductTypeError` with the offending DID hex,
   the offending raw value, and the legal whitelist. Phase 2 / 3
   surface this as an exit-code-4 fail-loud (Q6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, List, Tuple

from .schema import FSCSDocument
from implementation.paths import COMMON_TOKEN  # absolute: scripts/ on sys.path

# Hard-coded recognised product set. New products are a deliberate
# code change, not a config edit (mirrors the
# :data:`scripts.implementation.paths._DEFAULT_PRODUCT_TYPE_MAP`
# convention).  Stored upper-case for canonical comparison; the
# Common token uses its title-case literal so the work-set tuple
# round-trips through path resolution unchanged.
RECOGNISED_PRODUCTS: FrozenSet[str] = frozenset({
    "DPB", "ESP", "ESPCL", "IPB", "RBU", COMMON_TOKEN,
})

# Deterministic display order: production products first
# (alphabetical) then the wildcard. Phase 2 / 3 iterate the
# work-set in this order so console output and ``outputs/`` listings
# are stable across runs and across operators.
_PRODUCT_DISPLAY_ORDER: Tuple[str, ...] = (
    "DPB", "ESP", "ESPCL", "IPB", "RBU", COMMON_TOKEN,
)


# v1.24.0: Phase-2-only product **path** aliases. ESPCL is
# conceptually a variant of ESP and the Bosch tree has no
# ``cfg/ESPCL/`` directory; instead, ESPCL's ARXML lands inside
# ``cfg/ESP/`` with an ``..._ESPCL.arxml`` filename suffix
# distinguishing it from ESP's own ``..._ESP.arxml``. The local
# ``outputs/arxml/`` layout mirrors this: ESPCL writes
# ``outputs/arxml/ESP/DID_Config_ESPCL.arxml`` next to ESP's own
# ``DID_Config_ESP.arxml``.
#
# This is **NOT** a DID fold-in (the v1.23.0 semantic): ESPCL
# still iterates as a distinct PT, processes its own ESPCL+Common
# DIDs through the standard single-target Phase 2 filter, and
# writes its own ARXML / validation report / review report. Only
# the *output paths* are alias-rewritten so ESP and ESPCL share
# a folder. Phase 3 ignores this alias entirely (it's Phase-2
# specific).
#
# Mapping shape: ``alias_source -> alias_target``. Where the
# alias appears:
#
# 1. ``{product_type_arxml_folder}`` placeholder in
#    ``paths.arxml_file`` resolves to ``alias_target`` for an
#    alias-source PT (so the Bosch mirror lands in the target's
#    ``cfg/<target>/`` directory).
# 2. ``pipeline.run_phase2`` calls
#    :func:`scripts.implementation.paths.product_type_arxml_folder`
#    (which consults this map) to compute the local output
#    directory under ``outputs/arxml/`` so the local layout
#    mirrors the Bosch one.
# 3. ``init_project._detect_per_product_overrides`` does **not**
#    seed an auto-null ``per_product.<source>.arxml_file = null``
#    when ``cfg/<source>/`` is missing; it emits an
#    ``[INFO] Phase 2 path alias active: <source> → <target>``
#    line instead.
#
# Why hard-coded rather than configurable: ESPCL → ESP reflects a
# physical Bosch convention (ESPCL shares ESP's ECU-level
# configuration slot for diagnostics), not an operator preference.
# A future variant of this kind would be a deliberate code change
# here, not a project.json edit.
_PHASE2_PRODUCT_ALIASES: dict[str, str] = {
    "ESPCL": "ESP",
}


def phase2_alias_source_for(target: str) -> Tuple[str, ...]:
    """Return the alias source PTs whose Phase-2 outputs land in ``target``'s folder.

    Empty tuple when ``target`` is not the destination of any
    alias. Used by ``init_project`` for the ``[INFO] Phase 2 path
    alias active`` detector message ("ESP's folder also receives
    ESPCL's ARXML"). Comparison is case-insensitive; returned
    source spellings stay canonical.
    """
    if not target:
        return ()
    canon = target.strip().upper()
    return tuple(
        src for src, tgt in _PHASE2_PRODUCT_ALIASES.items()
        if tgt.upper() == canon
    )


def phase2_alias_target_for(source: str) -> str | None:
    """Return the alias target PT for ``source``, or ``None``.

    Used by Phase 2's path resolver to decide which folder /
    ``{product_type_arxml_folder}`` value to use. Comparison is
    case-insensitive; the returned target spelling stays
    canonical (matching the dict values).
    """
    if not source:
        return None
    canon = source.strip().upper()
    for src, tgt in _PHASE2_PRODUCT_ALIASES.items():
        if src.upper() == canon:
            return tgt
    return None


class UnknownProductTypeError(ValueError):
    """A DID's ``product_type`` is not in :data:`RECOGNISED_PRODUCTS`.

    Carries the offending DID hex + raw spelling so the orchestrator
    can render an actionable error message ("DID 0xF190 has
    product_type='DPC'; did you mean DPB? Recognised values: ...").
    """

    def __init__(self, did_hex: str, raw_value: str,
                 recognised: Iterable[str]):
        self.did_hex = did_hex
        self.raw_value = raw_value
        self.recognised = sorted(recognised)
        super().__init__(
            f"DID 0x{did_hex} has unrecognised product_type "
            f"{raw_value!r}; expected one of: "
            f"{', '.join(self.recognised)}"
        )


@dataclass(frozen=True)
class ProductWorkset:
    """Per-run product fan-out plan.

    Attributes:
      products: Canonical product names in display order (production
        products first, ``Common`` last). Empty when no ``used`` DID
        in the document carries any recognised ``product_type`` —
        Phase 2 / 3 treat this as "nothing to build" (warning + skip,
        exit 0; see Q5 in the v1.21.0 design).
      used_did_count: Total ``used`` DIDs that contributed. Surfaced
        for the warning message when ``products`` is empty.
    """

    products: Tuple[str, ...]
    used_did_count: int

    def is_empty(self) -> bool:
        return not self.products


def _canonicalise(raw: str) -> str:
    """Map a raw CSV cell to the canonical spelling.

    Returns the canonical form when the upper-case match lands in
    :data:`RECOGNISED_PRODUCTS`; raises ``KeyError`` (caller handles)
    when it doesn't.

    ``Common`` is kept in title-case (matching its literal in
    :data:`RECOGNISED_PRODUCTS`); the production products collapse to
    upper-case.
    """
    upper = raw.strip().upper()
    if upper == COMMON_TOKEN.upper():
        return COMMON_TOKEN
    if upper in RECOGNISED_PRODUCTS:
        return upper
    raise KeyError(raw)


def compute_workset(document: FSCSDocument) -> ProductWorkset:
    """Determine the fan-out work-set for a Phase 2 / Phase 3 run.

    See module docstring for the filtering rules. Raises
    :class:`UnknownProductTypeError` on any unrecognised non-empty
    ``product_type`` cell so a typo (``DPC`` instead of ``DPB``)
    fails loud rather than silently spawning an extra build target.
    """
    seen: set[str] = set()
    used_count = 0

    for entry in document.dids:
        if not (entry.service_22.used or entry.service_2e.used):
            continue
        used_count += 1
        raw = (entry.product_type or "").strip()
        if not raw:
            # Empty / unset ``product_type`` collapses to Common
            # (legacy semantics — an absent tag has always meant
            # "applies everywhere"). Q5 alternative was to hard
            # fail; we deliberately picked the lenient default so
            # Phase 1 -builder-defaulted FSCSDocuments keep building
            # without operator intervention.
            seen.add(COMMON_TOKEN)
            continue
        try:
            seen.add(_canonicalise(raw))
        except KeyError as exc:
            raise UnknownProductTypeError(
                did_hex=entry.did_hex,
                raw_value=raw,
                recognised=RECOGNISED_PRODUCTS,
            ) from exc

    ordered: List[str] = [p for p in _PRODUCT_DISPLAY_ORDER if p in seen]
    return ProductWorkset(
        products=tuple(ordered),
        used_did_count=used_count,
    )
