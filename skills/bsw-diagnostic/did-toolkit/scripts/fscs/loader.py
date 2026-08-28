"""File-system I/O for :class:`FSCSDocument`.

This module only handles the **happy path** -- reading a well-formed
``fscs.json`` from disk and returning a validated
:class:`FSCSDocument`. The legacy ``.txt`` -> document conversion lives
in :mod:`scripts.fscs.importer`, called out separately because it is a
one-shot migration tool rather than the normal load path downstream
consumers use.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import FSCSDocument


def load_fscs_json(path: Path) -> FSCSDocument:
    """Read and validate ``fscs.json``.

    Delegates to :meth:`pydantic.BaseModel.model_validate` so any schema
    violation (unknown fields, wrong types, missing required keys)
    surfaces as a :class:`pydantic.ValidationError` at load time. Phase
    2/3 should treat a validation error as a hard pipeline failure.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return FSCSDocument.model_validate(raw)


def save_fscs_json(doc: FSCSDocument, path: Path) -> None:
    """Write ``doc`` to ``path`` using the canonical renderer.

    Kept here (rather than on the renderer) so callers have one import
    surface for FSCS I/O.
    """
    from .renderer import render_fscs_json  # local to avoid cycle

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(render_fscs_json(doc), encoding="utf-8")
