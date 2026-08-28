"""Pydantic schema for ``config/project.json`` (schema 2.2).

Pre-release skill — no migration shims for any prior shape. The
``schema_version`` validator only accepts the current value
(:data:`SCHEMA_VERSION`); anything else hard-fails at load with a
pointer here.

Phase 2 / Phase 3 always write directly into the Bosch project tree
(skip-if-exists for files, macro-level skip for headers,
deduplicated container merge for ARXML). ``.DCOM_AI/DID_Toolkit_PRJ/outputs/`` keeps
only reports (validation / review / generation_report). The merge is
non-destructive, so there is no rolling backup — ``options`` is an
empty placeholder kept with ``extra='forbid'`` to fail loud on stale
keys from older schemas.

``paths.per_product`` lets the operator (or ``--init-project``
auto-detect) pin per-PT path overrides or ``null`` "skip this
mirror" sentinels for asymmetric trees — e.g. ``ESPCL`` has no ARXML
directory of its own, ``Common`` has no
``dcompr/cfg/RBDCOM_ConfigSettings.h``, and ``IPB``'s ConfigSettings
lives at ``RBDCOM_ConfigSettings_IPB.h`` rather than the plain
template name.

Fields (paths block plus an empty options block):

* ``schema_version``                  — version pin
* ``paths.base_dir``                  — mirror anchor; consumed by every Phase 2/3
                                        write site (required for Phase 2 / 3)
* ``paths.{pdm_file, config_h,        — six Phase 2 / Phase 3 mirror targets,
   config_elements_h,                   resolved through ``implementation.paths.
   config_settings_h, c_output_subdir,  resolve_path`` (supports
   arxml_file}``                        ``{product_type_upper}`` /
                                        ``{product_type_lower}`` /
                                        ``{product_type_suffix}`` placeholders)
* ``paths.input_did_json``            — basename of the chosen Phase 1 input
                                        recorded by ``--init-project``
* ``paths.per_product``               — per-PT overrides + skip sentinel
* ``options``                         — empty placeholder; ``extra='forbid'``
                                        rejects stale keys from older schemas.
"""

from __future__ import annotations

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


SCHEMA_VERSION = "2.2"
"""Pydantic schema version. The only value the validator accepts.

Pre-release skill, so every previous shape (1.0 / 1.1 / 2.0 / 2.1)
hard-fails ``schema_version`` validation rather than silently
migrating. Operators on an older shape regenerate via
``pipeline.py --init-project``.
"""


_RECOGNISED_PRODUCT_KEYS = frozenset({
    "DPB", "ESP", "ESPCL", "IPB", "RBU", "Common",
})
"""v1.22.0 product whitelist for ``paths.per_product`` keys.

Mirrors :data:`scripts.fscs.product_workset.RECOGNISED_PRODUCTS`
case-insensitively but keys here must use the canonical spellings
(upper-case for production products, title-case ``Common``) so a
typo (``"DPC"``, ``"common"``) fails loud at load time rather
than silently shadowing nothing at runtime.
"""

_PER_PRODUCT_PATH_KEYS = frozenset({
    "pdm_file", "config_h", "config_elements_h",
    "config_settings_h", "c_output_subdir", "arxml_file",
})
"""Path keys legal under each ``per_product[<PT>]`` sub-block.

Excludes ``base_dir`` because it's not per-product; including it
in an override would just be confusing (operators should set
``paths.base_dir`` once at the top level).
"""


class _Strict(BaseModel):
    """Base model with ``extra='forbid'`` so typos raise loudly.

    A misspelled key under any block fails validation rather than
    being silently dropped.
    """

    model_config = ConfigDict(extra="forbid")


class ProjectPaths(_Strict):
    """``paths.*`` block: where each artefact lands when mirroring.

    Templates may include ``{product_type_upper}`` /
    ``{product_type_lower}`` / ``{product_type_suffix}``
    placeholders. :func:`scripts.implementation.paths.resolve_path`
    expands them per-product during the v1.21.0 fan-out, so a
    single ``project.json`` drives every product without
    re-setup.

    Empty strings are sentinel "no target configured" — the
    generators skip the corresponding mirror site rather than
    raising.

    v1.22.0 (schema 2.1) added :attr:`per_product` for the
    "this PT diverges from the template" cases. See module
    docstring for the full motivation; in short: real Bosch trees
    aren't fully template-symmetric (``ESPCL`` has no ARXML
    directory, ``IPB``'s ConfigSettings is variant-suffixed,
    ``Common`` has no ``dcompr/cfg/``), and ``per_product`` lets
    the operator pin those exceptions without giving up
    placeholders for the symmetric majority.
    """

    base_dir: str = Field(
        default="",
        description=(
            "Anchor for every other path. Absolute or relative; "
            "relative paths are resolved against the workspace "
            "root by ``pipeline.py``."
        ),
    )
    pdm_file: str = Field(default="", description="Phase 3 PDM mirror target.")
    config_h: str = Field(default="", description="Phase 3 ``RBAPLCUST_Config.h`` mirror target.")
    config_elements_h: str = Field(
        default="", description="Phase 3 ``RBAPLCUST_ConfigElements.h`` mirror target."
    )
    config_settings_h: str = Field(
        default="", description="Phase 3 ``RBDCOM_ConfigSettings.h`` mirror target."
    )
    c_output_subdir: str = Field(
        default="",
        description=(
            "Phase 3 directory into which new ``RBAPLCUST_RDBI_*.c`` / "
            "``WDBI_*.c`` files are *created* (never overwritten)."
        ),
    )
    arxml_file: str = Field(
        default="",
        description=(
            "Phase 2 ARXML target (project tree). The generated "
            "``DID_Config.arxml`` is merged into the existing Bosch "
            "ARXML (deduplicated by ``SHORT-NAME`` under "
            "``DcmDsp/SUB-CONTAINERS``); pre-existing containers win. "
            "This is the SOLE Phase 2 sink — there is no "
            "``outputs/arxml/...`` mirror, and ``output_mode`` is "
            "not a supported field."
        ),
    )
    input_did_json: str = Field(
        default="",
        description=(
            "v1.28.0: basename of the chosen ``*_did.json`` under "
            "``.DCOM_AI/DID_Toolkit_PRJ/inputs/`` for Phase 1. Recorded by "
            "``--init-project`` after the operator confirms which "
            "questionnaire to use (numbered picker in TTY when "
            "multiple are present; ``--input`` CLI flag in non-TTY). "
            "Phase 1 reads this as the default when no ``--input`` "
            "override is passed; an empty value falls back to the "
            "pre-v1.28.0 auto-discovery contract "
            "(single-file -> auto-pick, multiple -> exit 3)."
        ),
    )
    per_product: Dict[str, Dict[str, Optional[str]]] = Field(
        default_factory=dict,
        description=(
            "v1.22.0 per-product overrides + skip sentinel.\n"
            "\n"
            "Outer keys: canonical product short names (``DPB`` / "
            "``ESP`` / ``ESPCL`` / ``IPB`` / ``RBU`` / ``Common``). "
            "Other spellings raise a validation error so a typo "
            "(``DPC``, ``common``) fails loud at config load.\n"
            "\n"
            "Inner keys: a subset of the six mirror path fields "
            "(``pdm_file`` / ``config_h`` / ``config_elements_h`` / "
            "``config_settings_h`` / ``c_output_subdir`` / "
            "``arxml_file``). Anything else raises.\n"
            "\n"
            "Inner values:\n"
            "  * ``null`` → SKIP both local generation and the Bosch-"
            "    tree mirror for this (PT, key). For Phase 2's only "
            "    key (``arxml_file``) this skips the entire product "
            "    iteration — no ``outputs/arxml/<PT>/`` directory is "
            "    produced. For Phase 3 keys it skips just that one "
            "    artefact for that product (other artefacts still "
            "    flow normally).\n"
            "  * non-empty ``str`` → literal override path used in "
            "    place of the top-level template + placeholder "
            "    expansion. Local artefact still lands under "
            "    ``outputs/{arxml,implementation}/<PT>/...``; only "
            "    the Bosch mirror destination changes.\n"
            "  * absent → the top-level template is used.\n"
            "\n"
            "``--init-project`` auto-populates this block by "
            "scanning the live Bosch tree (e.g. detects "
            "``cfg/ESPCL/`` is missing → sets "
            "``per_product.ESPCL.arxml_file = null``)."
        ),
    )

    @field_validator("per_product")
    @classmethod
    def _validate_per_product(
        cls, value: Dict[str, Dict[str, Optional[str]]]
    ) -> Dict[str, Dict[str, Optional[str]]]:
        """Pin the (PT, key) whitelists so typos fail loud at load."""
        for pt, overrides in value.items():
            if pt not in _RECOGNISED_PRODUCT_KEYS:
                raise ValueError(
                    f"paths.per_product key {pt!r} is not in the recognised "
                    f"product whitelist; expected one of: "
                    f"{sorted(_RECOGNISED_PRODUCT_KEYS)}. "
                    "Use the canonical spelling (upper-case for production "
                    "products, title-case ``Common``)."
                )
            if not isinstance(overrides, dict):
                raise ValueError(
                    f"paths.per_product[{pt!r}] must be a dict mapping "
                    f"path keys to ``null`` or override path strings; "
                    f"got {type(overrides).__name__}."
                )
            for path_key, override in overrides.items():
                if path_key not in _PER_PRODUCT_PATH_KEYS:
                    raise ValueError(
                        f"paths.per_product[{pt!r}][{path_key!r}] is not a "
                        f"recognised path key; expected one of: "
                        f"{sorted(_PER_PRODUCT_PATH_KEYS)}. "
                        "(``base_dir`` is intentionally excluded — set it "
                        "once at the top level instead.)"
                    )
                if override is not None and not isinstance(override, str):
                    raise ValueError(
                        f"paths.per_product[{pt!r}][{path_key!r}] must be "
                        f"``null`` (skip mirror) or a non-empty path string "
                        f"(override mirror); got {type(override).__name__}."
                    )
                if isinstance(override, str) and not override.strip():
                    raise ValueError(
                        f"paths.per_product[{pt!r}][{path_key!r}] is an "
                        f"empty string. Use ``null`` to mean ``SKIP this "
                        f"mirror`` or a non-empty path to mean ``OVERRIDE "
                        f"to this path``; an empty string is ambiguous."
                    )
        return value


class ProjectOptions(_Strict):
    """``options.*`` block: empty by design.

    The Bosch project tree is the sole sink for Phase 2 / Phase 3
    and the merge is non-destructive (skip-on-conflict), so neither
    the legacy output-mode knob nor a rolling-backup safety net is
    needed. The class is kept (with ``extra='forbid'``) so a stale
    ``options.*`` key in a hand-edited config fails loud at load
    rather than being silently ignored.
    """


class ProjectConfig(_Strict):
    """Top-level wrapper that mirrors ``config/project.json``.

    Construction is forgiving — every field has a sensible default,
    so ``ProjectConfig()`` is a valid "no-mirror, never-touch-
    anything" posture. Any field the operator fills in narrows the
    behaviour; we never silently turn on a destructive feature.

    Three top-level blocks: ``schema_version`` pin, ``paths`` (six
    mirror keys + ``input_did_json`` + the ``per_product`` override
    block), and ``options`` (empty placeholder).
    """

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description=(
            "Pydantic schema version. v1.22.0 ships ``2.1`` and the "
            "validator only accepts that string. Pre-release skill, "
            "so any earlier shape (``1.0`` / ``1.1`` / ``2.0``) "
            "hard-fails — regenerate via ``pipeline.py "
            "--init-project`` and hand-copy custom ``paths.*`` "
            "values across."
        ),
    )
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    options: ProjectOptions = Field(default_factory=ProjectOptions)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        """Refuse any value other than :data:`SCHEMA_VERSION`.

        Pre-release skill — there is intentionally no migration
        shim. An operator landing on an old ``schema_version``
        sees a clear error pointing them at ``--init-project``.
        """
        if value != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported config schema_version {value!r} "
                f"(this build only accepts {SCHEMA_VERSION!r}). "
                f"Pre-release skill — no migration shim. Regenerate "
                f"the file via ``pipeline.py --init-project`` and "
                f"copy any custom paths.* values across by hand."
            )
        return value


__all__ = [
    "SCHEMA_VERSION",
    "ProjectConfig",
    "ProjectOptions",
    "ProjectPaths",
    "PER_PRODUCT_PATH_KEYS",
    "RECOGNISED_PRODUCT_KEYS",
]


# Re-export the whitelists with public names so other modules
# (resolver, init_project, tests) can reuse the canonical sets
# without reaching into a private ``_``-prefixed constant.
PER_PRODUCT_PATH_KEYS = _PER_PRODUCT_PATH_KEYS
RECOGNISED_PRODUCT_KEYS = _RECOGNISED_PRODUCT_KEYS
