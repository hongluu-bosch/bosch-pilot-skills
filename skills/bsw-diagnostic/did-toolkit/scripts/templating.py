#!/usr/bin/env python3
"""Jinja2 templating helper for did-toolkit generators.

Rationale
---------
Phase 6 of the refactor moves large multi-line f-string blocks in
``generate_implementation.py`` and ``generate_arxml.py`` into
``scripts/templates/*.j2`` files. This keeps byte-identical output
contracts (see tests/golden files) while making the output shape
reviewable without reading Python code.

Design choices
--------------
* **Custom delimiters.** The generated C code and ARXML both contain
  literal ``{`` / ``}`` and ``<tag>`` characters, which collide with
  Jinja2's default delimiters. We therefore use::

      {{ var }}  -> << var >>
      {% tag %}  -> <% tag %>
      {# comm #} -> <# comm #>

  ``<<`` and ``<%`` never appear in the legacy f-string bodies, so the
  templates render verbatim output except at their substitution points.

* **``keep_trailing_newline=True``.** Golden files preserve the trailing
  newline produced by the legacy f-strings that end on a literal
  newline.

* **``StrictUndefined``.** Any missing variable becomes a
  ``UndefinedError`` at render time rather than an empty string, so
  typos in context dicts fail fast instead of silently corrupting the
  output tree.

* **Singleton environment.** Templates are cheap to cache; loading from
  disk once keeps phase 3 generation fast when iterating over hundreds
  of DIDs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, StrictUndefined


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@lru_cache(maxsize=1)
def get_env() -> Environment:
    """Return the process-wide Jinja2 environment.

    Cached so every generator call reuses the same parsed templates.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
        autoescape=False,
        undefined=StrictUndefined,
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
    )
    return env


def render(template_name: str, context: Dict[str, Any]) -> str:
    """Render ``template_name`` with ``context`` and return the string.

    ``template_name`` is relative to :data:`TEMPLATE_DIR`, e.g.
    ``"impl/pdm_entry.j2"``.
    """
    return get_env().get_template(template_name).render(**context)
