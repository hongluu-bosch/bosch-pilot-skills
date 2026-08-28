"""File I/O helpers for ``config/project.json`` (v1.13.0).

Two thin functions that paper over Pydantic's ``model_validate`` /
``model_dump`` while pinning encoding, indentation, sort order, and
trailing newline. Same convention as ``scripts/fscs/`` uses for
``fscs.json``.

Behaviour matrix
----------------

* ``path`` does not exist        -> :class:`ProjectConfig` defaults
* ``path`` exists but is empty   -> :class:`ProjectConfig` defaults
* ``path`` exists with valid JSON-> validated :class:`ProjectConfig`
* ``path`` exists with bad JSON  -> :class:`ValueError` with line/col
* ``path`` exists with unknown
  keys / wrong types             -> :class:`pydantic.ValidationError`

The first two cases are intentional: an unconfigured install is a
valid configuration ("operator hasn't pointed me at a project tree
yet"), not a bug -- Phase 1 / Phase 4 (DOORS) both run fine
without ``project.json``; only Phase 2 / Phase 3 (which write into
the Bosch tree) hard-gate on a populated ``paths.base_dir`` and
the matching Bosch-tree path template. The other two cases are
loud so a typo in a hand-edited config doesn't get rounded down
to silence (this class of bug was the primary motivation for the
v1.13.0 Pydantic migration).
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import ProjectConfig


def load_project_config(path: Path) -> ProjectConfig:
    """Load ``project.json`` if present, else return defaults.

    Missing / empty files yield a default :class:`ProjectConfig`
    rather than raising — see the module docstring for the full
    behaviour matrix and rationale.

    Pre-release skill, no migration shim: any stored
    ``schema_version`` other than the current
    :data:`scripts.config.schema.SCHEMA_VERSION` raises a
    :class:`pydantic.ValidationError` with a pointer at
    ``--init-project``.

    :param path: Path to the JSON config file. Typically
        ``<skill>/config/project.json``.
    :returns: A validated :class:`ProjectConfig` instance.
    :raises ValueError: when the file exists but is not valid JSON
        (re-wrapped from ``json.JSONDecodeError`` so callers can show
        a friendly line/col message).
    :raises pydantic.ValidationError: when the JSON parses but the
        shape doesn't match the schema (unknown keys, wrong types,
        out-of-range values, etc.).
    """
    if not path.is_file():
        return ProjectConfig()
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return ProjectConfig()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Re-wrap so callers (CLI, agent) can surface a readable
        # location instead of a stock "Expecting value:..." message.
        raise ValueError(
            f"failed to parse project config {path}: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})"
        ) from exc
    return ProjectConfig.model_validate(data)


def save_project_config(path: Path, config: ProjectConfig) -> None:
    """Write ``config`` to ``path`` as pretty-printed UTF-8 JSON.

    * Two-space indent, sorted keys for human-readable diffs.
    * Trailing newline so POSIX tools / git don't grumble.
    * ``ensure_ascii=False`` so Chinese customer names / paths
      survive the round-trip without ``\\uXXXX`` escaping.
    * Parents are created lazily; first-time setup can save without
      pre-creating ``config/``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="json")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


__all__ = ["load_project_config", "save_project_config"]
