"""Path-resolution helpers (product_type expansion, placeholder substitution).

Separated from the orchestrator so that any caller that just wants to
know "where would this path go for ESP?" can compute it without building
a full :class:`ImplementationGenerator` instance.

v1.22.0 added :func:`resolve_mirror_path` to handle the new
``paths.per_product`` overrides (schema 2.1). The legacy
:func:`resolve_path` is unchanged — it still expands placeholders
against a single template — but Phase 2 / Phase 3 now route through
``resolve_mirror_path`` so per-PT ``null`` (skip) and per-PT literal
overrides are honoured uniformly across the two phases.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


_DEFAULT_PRODUCT_TYPE_MAP = {
    'ESP': 'esp10',
    'DPB': 'dpb',
    'ESPCL': 'esp10cl',
    'IPB': 'ipb',
    'RBU': 'rbu',
}


# v1.21.0: ``Common`` is the cross-product wildcard slot. Bosch's actual
# tree uses the title-case ``Common/`` directory (alongside ``DPB/`` /
# ``ESP/`` / ...), so all three legacy placeholders collapse to the
# title-case literal under Common — a build-target ``Common`` should
# never produce a ``COMMON/`` or ``common/`` path segment.
COMMON_TOKEN = 'Common'

# v1.21.0: Common's ARXML mirror file is named
# ``Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml`` in the Bosch
# tree (no ``_Common`` suffix). Per-product variants stay
# ``..._<PT>.arxml``. The ``{product_type_suffix}`` placeholder
# captures this asymmetry: it expands to the upper-case product short
# name for real products and to ``SingleCANID`` for the ``Common``
# wildcard, so a single ``paths.arxml_file`` template covers both.
_COMMON_ARXML_SUFFIX = 'SingleCANID'


def _is_common(product_type: str) -> bool:
    return product_type.strip().lower() == COMMON_TOKEN.lower()


def product_type_lower(config: Optional[Dict[str, Any]], product_type: str) -> str:
    """Resolve ``product_type`` to its lowercase short form.

    Precedence: hard-coded defaults -> ``product_type.lower()``.
    Returns empty string when ``product_type`` is empty.

    v1.21.0: ``Common`` is special-cased to return the title-case
    literal ``'Common'`` rather than ``'common'`` so the
    ``{product_type_lower}`` placeholder collapses to the same
    Bosch-tree directory name as ``{product_type_upper}``. The five
    production products keep their existing lowercase short forms
    (``esp10`` / ``dpb`` / ...).

    v1.19.0: the previous ``config['product_type_mapping']``
    override was dropped along with the rest of the schema cull.
    The five Bosch products in :data:`_DEFAULT_PRODUCT_TYPE_MAP`
    have been stable for the lifetime of the toolkit; a sixth
    product would be a deliberate code change here, not a config
    edit. ``config`` is kept in the signature so existing call
    sites compile unchanged.
    """
    if not product_type:
        return ''
    _ = config  # signature back-compat; v1.19.0 ignores config-level overrides
    if _is_common(product_type):
        return COMMON_TOKEN
    return _DEFAULT_PRODUCT_TYPE_MAP.get(product_type) or product_type.lower()


def product_type_upper(product_type: str) -> str:
    """Resolve ``product_type`` to its uppercase short form.

    Mirrors :func:`product_type_lower`'s Common special-case: a
    ``Common`` build-target expands to the title-case literal
    ``'Common'`` (matching the Bosch tree's ``cfg/Common/`` /
    ``src/Common/`` directory naming), not ``'COMMON'``.
    """
    if not product_type:
        return ''
    if _is_common(product_type):
        return COMMON_TOKEN
    return product_type.upper()


def product_type_suffix(product_type: str) -> str:
    """Resolve ``product_type`` to its ARXML-filename tag.

    Bosch's mirror tree puts the ``Common`` DID ARXML at
    ``cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml``
    (no ``_Common`` in the filename), while every per-product DID
    ARXML follows ``cfg/<PT>/Dcm_CusDiag_Services_EcucValues_<PT>.arxml``.
    The ``{product_type_suffix}`` placeholder lets a single
    ``paths.arxml_file`` template cover both spellings:

    * Real products (DPB / ESP / ESPCL / IPB / RBU)
        → uppercase short form (``DPB`` / ``ESP`` / ...)
    * ``Common`` wildcard
        → ``SingleCANID``
    """
    if not product_type:
        return ''
    if _is_common(product_type):
        return _COMMON_ARXML_SUFFIX
    return product_type.upper()


def product_type_arxml_folder(product_type: str) -> str:
    """Resolve ``product_type`` to the Phase-2 ARXML *folder* name.

    v1.24.0 Phase-2 path-alias dispatcher. Behaves identically to
    :func:`product_type_upper` **except** for products listed in
    :data:`scripts.fscs.product_workset._PHASE2_PRODUCT_ALIASES`,
    which are rewritten to their alias target's canonical folder
    spelling. Currently the only entry is ``ESPCL → ESP``: an
    ESPCL Phase-2 iteration writes its ARXML into ``cfg/ESP/`` (not
    ``cfg/ESPCL/``) under the canonical Bosch naming
    ``Dcm_CusDiag_Services_EcucValues_ESPCL.arxml``.

    The ``{product_type_arxml_folder}`` placeholder in
    ``paths.arxml_file`` templates expands to this value. Phase 3
    templates (``paths.c_output_subdir`` / ``paths.config_settings_h``
    / etc.) deliberately do not use it — Phase 3 keeps ESPCL as a
    distinct PT (own ``src/ESPCL/`` mirror, own
    ``esp10cl/dcompr/cfg/...`` ConfigSettings).

    The alias map lives in :mod:`scripts.fscs.product_workset` to
    keep PT taxonomy concerns in one place; we lazy-import it here
    to avoid a circular dependency (``fscs.__init__`` already
    imports :data:`COMMON_TOKEN` from this module).
    """
    if not product_type:
        return ''
    # Lazy import: ``fscs.product_workset`` itself imports
    # ``COMMON_TOKEN`` from this module (paths.py); a top-level
    # import here would create an import cycle observable in
    # certain test orderings.
    from fscs.product_workset import phase2_alias_target_for
    target = phase2_alias_target_for(product_type)
    if target:
        return target  # canonical alias-target spelling (e.g. 'ESP')
    return product_type_upper(product_type)


def resolve_path(config: Optional[Dict[str, Any]],
                 path_template: str,
                 product_type: Optional[str] = None) -> Path:
    """Expand placeholders in a path template and return a :class:`Path`.

    Supported placeholders (all optional):

    * ``{product_type}``               — lowercase short form
                                         (``esp10``/``dpb``/...); collapses
                                         to literal ``Common`` under the
                                         ``Common`` wildcard (v1.21.0).
    * ``{product_type_lower}``         — alias of ``{product_type}``.
    * ``{product_type_upper}``         — uppercase short form
                                         (``ESP``/``DPB``/...); collapses to
                                         literal ``Common`` under the
                                         ``Common`` wildcard (v1.21.0).
                                         **Not** alias-aware — Phase 3
                                         templates rely on this distinct
                                         per-PT value (``src/ESPCL/`` !=
                                         ``src/ESP/``).
    * ``{product_type_suffix}``        — ARXML-filename tag (v1.21.0).
                                         Equals ``{product_type_upper}`` for
                                         real products; ``SingleCANID`` for
                                         ``Common``.
    * ``{product_type_arxml_folder}``  — v1.24.0 Phase-2 path alias.
                                         Equals ``{product_type_upper}``
                                         except for alias source PTs
                                         (currently ``ESPCL`` → ``ESP``)
                                         which expand to the alias target
                                         folder. Use this in
                                         ``paths.arxml_file`` so an ESPCL
                                         Phase-2 iteration writes to
                                         ``cfg/ESP/Dcm_..._ESPCL.arxml``
                                         next to ESP's own
                                         ``Dcm_..._ESP.arxml``.

    v1.19.0 dropped ``{customer_name}`` placeholder support: the
    schema cull removed ``project.customer_name`` after auditing
    that no path template ever referenced the placeholder. Customer
    is baked literally into ``paths.*`` strings by ``init_project``.

    Placeholders that are not provided are left untouched, so a
    caller can compose resolutions without this helper raising. A
    template that uses no placeholders (e.g. an operator who hand-
    edited ``paths.arxml_file`` to a fully-resolved literal path) is
    returned verbatim — Phase 2 / Phase 3 still mirror to it
    correctly.
    """
    if product_type:
        lower_variant = product_type_lower(config, product_type)
        upper_variant = product_type_upper(product_type)
        suffix_variant = product_type_suffix(product_type)
        arxml_folder_variant = product_type_arxml_folder(product_type)
        path_template = path_template.replace('{product_type}', lower_variant)
        path_template = path_template.replace('{product_type_lower}', lower_variant)
        path_template = path_template.replace('{product_type_upper}', upper_variant)
        path_template = path_template.replace('{product_type_suffix}', suffix_variant)
        path_template = path_template.replace(
            '{product_type_arxml_folder}', arxml_folder_variant,
        )
    return Path(path_template)


# ---------------------------------------------------------------------------
# v1.22.0: per-product Bosch mirror resolution (paths.per_product overrides)
# ---------------------------------------------------------------------------


class MirrorResolution(str, Enum):
    """Provenance + verdict from :func:`resolve_mirror_path`.

    Each value tells the caller WHY the resolver returned what it
    returned, so log lines can be specific (``[SKIP] paths.per_product
    .ESPCL.arxml_file=null`` reads better than a generic ``[SKIP]``).

    Members:
      * :attr:`OVERRIDE` — value came from
        ``paths.per_product[<PT>][<key>]`` (a literal path string).
        The caller should use the returned :class:`Path` for the
        Bosch mirror destination.
      * :attr:`TEMPLATE` — value came from the top-level
        ``paths[<key>]`` template with placeholders expanded. This
        is the v1.21.0 behaviour; the v1.22.0 resolver simply wraps
        it in the same return shape.
      * :attr:`SKIP` — operator pinned this (PT, key) to ``null``
        in ``paths.per_product``; the artefact is intentionally not
        produced for this product. Returned :class:`Path` is None.
      * :attr:`UNSET` — neither override nor template configured
        (template is empty / missing). Same observable behaviour
        as :attr:`SKIP` but without the explicit operator opt-in;
        callers may want to log this differently (e.g. as a
        v1.21.0-style silent-degradation notice).
    """

    OVERRIDE = "override"
    TEMPLATE = "template"
    SKIP = "skip"
    UNSET = "unset"


def _extract_paths_block(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return ``config['paths']`` as a dict, or an empty dict.

    Tolerates ``None`` configs and configs without a ``paths`` key
    (early-bootstrap callers, unit-test fixtures, etc.). The
    Pydantic schema (``ProjectPaths``) defaults every field, so a
    missing ``paths`` block has the same observable shape as a
    fully-defaulted one.
    """
    if not isinstance(config, dict):
        return {}
    paths = config.get("paths")
    if not isinstance(paths, dict):
        return {}
    return paths


def resolve_mirror_path(
    config: Optional[Dict[str, Any]],
    key: str,
    product_type: str,
) -> Tuple[Optional[Path], MirrorResolution]:
    """Compute the Bosch-tree mirror destination for (key, product_type).

    Resolution precedence (v1.22.0 schema 2.1):

    1. ``paths.per_product[<canonical_pt>][<key>]`` is consulted
       first. If present and ``None``, return
       ``(None, MirrorResolution.SKIP)`` — the operator pinned this
       (PT, key) as "no Bosch target". If present as a non-empty
       string, return ``(Path(value), MirrorResolution.OVERRIDE)``.
    2. Otherwise fall back to the top-level template
       ``paths[<key>]``. Empty / missing template returns
       ``(None, MirrorResolution.UNSET)`` (v1.21.0
       silent-degradation behaviour); a non-empty template is
       expanded via :func:`resolve_path` and returned as
       ``(resolved, MirrorResolution.TEMPLATE)``.

    The canonical product spelling is used to look up
    ``per_product`` (so ``"common"`` and ``"COMMON"`` both find
    a ``Common`` entry); :func:`product_type_upper` collapses
    Common to title-case.

    The returned :class:`Path` is RELATIVE — callers compose it
    with ``paths.base_dir`` themselves (same convention as
    :func:`resolve_path`). Skip / Unset return ``None`` so the
    caller can short-circuit before touching ``base_dir`` at all.

    :param config: The full project config dict (or ``None``); the
        helper extracts ``config['paths']`` internally so callers
        don't have to pre-flatten it.
    :param key: One of the six per-product mirror keys
        (``arxml_file`` / ``pdm_file`` / ``config_h`` /
        ``config_elements_h`` / ``config_settings_h`` /
        ``c_output_subdir``).
    :param product_type: Build-target product (any case;
        canonicalised internally via :func:`product_type_upper`).
    """
    paths = _extract_paths_block(config)
    canonical_pt = product_type_upper(product_type) if product_type else ""

    per_product = paths.get("per_product")
    if isinstance(per_product, dict) and canonical_pt:
        pt_overrides = per_product.get(canonical_pt)
        if isinstance(pt_overrides, dict) and key in pt_overrides:
            override = pt_overrides[key]
            if override is None:
                return None, MirrorResolution.SKIP
            if isinstance(override, str) and override.strip():
                return Path(override), MirrorResolution.OVERRIDE
            # Schema validation should have already rejected empty
            # strings; treat any unexpected non-None falsy value the
            # same as ``UNSET`` defensively rather than crashing.

    template = paths.get(key, "") or ""
    if not template:
        return None, MirrorResolution.UNSET
    return resolve_path(config, template, product_type=product_type), MirrorResolution.TEMPLATE
