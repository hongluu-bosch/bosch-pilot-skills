"""Unit tests for scripts.templating.

These tests lock down the Jinja2 environment contract so phase 6 generators
stay byte-for-byte identical to their legacy f-string predecessors. If any
of these invariants change we want a very loud failure rather than a silent
drift in generated C / ARXML.
"""

from __future__ import annotations

import pytest
from jinja2 import StrictUndefined, UndefinedError

import templating


def test_env_uses_custom_delimiters():
    """The environment must use << >>/<% %>/<# #> so templates can contain
    literal ``{``/``}`` (C code) and ``<tag>`` (ARXML) without escaping."""
    env = templating.get_env()
    assert env.variable_start_string == "<<"
    assert env.variable_end_string == ">>"
    assert env.block_start_string == "<%"
    assert env.block_end_string == "%>"
    assert env.comment_start_string == "<#"
    assert env.comment_end_string == "#>"


def test_env_disables_autoescape_and_trim_blocks():
    """Output must be byte-identical: no HTML escaping, no newline trimming."""
    env = templating.get_env()
    assert env.autoescape is False
    assert env.trim_blocks is False
    assert env.lstrip_blocks is False
    assert env.keep_trailing_newline is True


def test_env_uses_strict_undefined():
    """Missing context keys must raise, not silently expand to ``""``."""
    env = templating.get_env()
    assert env.undefined is StrictUndefined


def test_get_env_is_cached():
    """Calling get_env twice must reuse the same Environment (templates are
    cheap to cache; this also means templates added on disk after first
    call will still be picked up via the loader)."""
    assert templating.get_env() is templating.get_env()


def test_render_raises_on_missing_variable(tmp_path, monkeypatch):
    """A typo in a context dict should blow up at render time."""
    env = templating.get_env()
    tpl = env.from_string("hello << name >>")
    with pytest.raises(UndefinedError):
        tpl.render()  # no name provided


def test_render_preserves_literal_curly_braces():
    """C code contains ``{`` and ``}`` which must pass through unchanged."""
    env = templating.get_env()
    out = env.from_string("int main() {\n\treturn << rc >>;\n}\n").render(rc=0)
    assert out == "int main() {\n\treturn 0;\n}\n"


def test_render_resolves_existing_template():
    """Smoke-test: the impl/pdm_entry.j2 template must render with its
    documented context (matches generate_pdm_entry in the generator)."""
    out = templating.render("impl/pdm_entry.j2", {
        "fs_macro": "RBFS_DCOM_FOO",
        "nvm_id": "NVM_ID_DCOM_FOO",
        "writecycles": 1000,
    })
    assert "#if (RBFS_DCOM_FOO == RBFS_DCOM_FOO_ON)" in out
    assert "use dataitem NVM_ID_DCOM_FOO" in out
    assert "writecycles = 1000;" in out
    assert out.endswith("*/\n")
