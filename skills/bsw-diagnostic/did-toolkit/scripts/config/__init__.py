"""Strongly-typed loader for ``config/project.json`` (schema 2.2).

Pydantic-validated surface so:

* Typos in keys raise at load time instead of silently flipping a
  feature off (``extra="forbid"``).
* The schema doubles as documentation — every field has a docstring
  visible in the IDE and in ``ProjectConfig.model_json_schema()``.
* The version field (``schema_version``) is a hard pin: only the
  current :data:`SCHEMA_VERSION` loads (pre-release skill, no
  migration shim).

Dict-style consumers can pass ``config.model_dump()`` to legacy
helpers; hotspots that benefit from strong typing
(Phase 2 / Phase 3 orchestrators, the per-product mirror resolver,
the cross-product reviewer) take :class:`ProjectConfig` directly.

See :mod:`scripts.config.schema` for the field reference and
:mod:`scripts.config.loader` for I/O.
"""

from __future__ import annotations

from .loader import load_project_config, save_project_config
from .schema import (
    PER_PRODUCT_PATH_KEYS,
    RECOGNISED_PRODUCT_KEYS,
    SCHEMA_VERSION,
    ProjectConfig,
    ProjectOptions,
    ProjectPaths,
)

__all__ = [
    "PER_PRODUCT_PATH_KEYS",
    "RECOGNISED_PRODUCT_KEYS",
    "SCHEMA_VERSION",
    "ProjectConfig",
    "ProjectOptions",
    "ProjectPaths",
    "load_project_config",
    "save_project_config",
]
