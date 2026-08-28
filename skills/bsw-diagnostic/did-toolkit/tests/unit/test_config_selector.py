"""Unit tests for the v1.14.0 multi-config selector.

Pins the four-step selection policy from
``scripts/config_selector.py``:

1. ``--config`` explicit -- absolute, workspace-relative, and
   bare-filename forms all resolve correctly.
2. Single discovered config auto-selects with no prompt.
3. Multiple + TTY -- numbered menu accepts both index and tag.
4. Multiple + non-TTY -- exits with the reserved ambiguity code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config_selector import (
    _AMBIGUOUS_EXIT_CODE,
    discover_configs,
    format_candidates,
    select_config,
)


def _ws(root: Path, *names: str) -> Path:
    """Set up a workspace at ``root`` with the named config files
    pre-created under ``config/``. Each gets a ``"{}"`` body so it
    counts as a real file under :func:`is_project_root`."""
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    for name in names:
        (config / name).write_text("{}", encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# discover_configs
# ---------------------------------------------------------------------------


def test_discover_returns_empty_when_no_config_dir(tmp_path):
    assert discover_configs(tmp_path) == []


def test_discover_skips_non_project_files(tmp_path):
    _ws(tmp_path, "project.json", "settings.json", "schema.json")
    found = discover_configs(tmp_path)
    assert [p.name for p in found] == ["project.json"]


def test_discover_returns_sorted_paths(tmp_path):
    _ws(tmp_path, "project.esp.json", "project.dpb.json", "project.json")
    found = [p.name for p in discover_configs(tmp_path)]
    # Lexicographic: bare project.json sorts first because of length;
    # then project.dpb.json, then project.esp.json.
    assert found == ["project.dpb.json", "project.esp.json", "project.json"]


# ---------------------------------------------------------------------------
# format_candidates: agent-readable diagnostic lines
# ---------------------------------------------------------------------------


def test_format_candidates_uses_tag_and_relative_path(tmp_path):
    _ws(tmp_path, "project.json", "project.dpb.json")
    lines = format_candidates(discover_configs(tmp_path), tmp_path)

    assert any(line.startswith("default\t") and "project.json" in line for line in lines)
    assert any(line.startswith("dpb\t") and "project.dpb.json" in line for line in lines)


# ---------------------------------------------------------------------------
# select_config: explicit --config
# ---------------------------------------------------------------------------


def test_explicit_workspace_relative_path(tmp_path):
    _ws(tmp_path, "project.json", "project.dpb.json")
    chosen = select_config(
        cli_arg="config/project.dpb.json",
        project_root=tmp_path,
        interactive=False,
    )
    assert chosen.name == "project.dpb.json"


def test_explicit_bare_filename_resolves_inside_config_dir(tmp_path):
    """An agent typing ``--config project.dpb.json`` (without the
    leading ``config/``) should still work -- the selector tries
    ``<project>/config/<arg>`` as a fallback."""
    _ws(tmp_path, "project.json", "project.dpb.json")
    chosen = select_config(
        cli_arg="project.dpb.json",
        project_root=tmp_path,
        interactive=False,
    )
    assert chosen.name == "project.dpb.json"


def test_explicit_absolute_path(tmp_path):
    _ws(tmp_path, "project.dpb.json")
    abs_path = (tmp_path / "config" / "project.dpb.json").resolve()
    chosen = select_config(
        cli_arg=str(abs_path),
        project_root=tmp_path,
        interactive=False,
    )
    assert chosen == abs_path


def test_explicit_missing_path_raises(tmp_path):
    _ws(tmp_path, "project.json")
    with pytest.raises(FileNotFoundError, match="--config"):
        select_config(
            cli_arg="config/project.does_not_exist.json",
            project_root=tmp_path,
            interactive=False,
        )


# ---------------------------------------------------------------------------
# select_config: discovery
# ---------------------------------------------------------------------------


def test_single_config_auto_selects(tmp_path):
    _ws(tmp_path, "project.json")
    chosen = select_config(
        cli_arg=None, project_root=tmp_path, interactive=False,
    )
    assert chosen.name == "project.json"


def test_no_config_returns_canonical_path(tmp_path):
    """Empty workspace shouldn't crash; the selector returns the
    conventional path so the loader's "missing file = defaults" rule
    keeps working downstream."""
    chosen = select_config(
        cli_arg=None, project_root=tmp_path, interactive=False,
    )
    assert chosen == tmp_path / "config" / "project.json"


def test_multiple_configs_non_tty_exits_ambiguous(tmp_path, capsys):
    _ws(tmp_path, "project.json", "project.dpb.json")
    with pytest.raises(SystemExit) as exc_info:
        select_config(
            cli_arg=None, project_root=tmp_path, interactive=False,
        )
    assert exc_info.value.code == _AMBIGUOUS_EXIT_CODE
    captured = capsys.readouterr()
    assert "Multiple did-toolkit configurations" in captured.err
    assert "project.dpb.json" in captured.err
    assert "project.json" in captured.err


# ---------------------------------------------------------------------------
# select_config: interactive menu (patched ``input``)
# ---------------------------------------------------------------------------


def test_interactive_pick_by_index(tmp_path, monkeypatch, capsys):
    _ws(tmp_path, "project.json", "project.dpb.json")
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "2")

    chosen = select_config(
        cli_arg=None, project_root=tmp_path, interactive=True,
    )
    # Sort order: project.dpb.json before project.json, so index 2 = project.json.
    assert chosen.name == "project.json"


def test_interactive_pick_by_tag(tmp_path, monkeypatch):
    _ws(tmp_path, "project.json", "project.dpb.json")
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "dpb")

    chosen = select_config(
        cli_arg=None, project_root=tmp_path, interactive=True,
    )
    assert chosen.name == "project.dpb.json"


def test_interactive_reprompts_on_bad_then_accepts(tmp_path, monkeypatch):
    _ws(tmp_path, "project.json", "project.dpb.json")
    answers = iter(["xyz", "999", "default"])
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: next(answers))

    chosen = select_config(
        cli_arg=None, project_root=tmp_path, interactive=True,
    )
    assert chosen.name == "project.json"


def test_interactive_eof_exits_ambiguous(tmp_path, monkeypatch):
    _ws(tmp_path, "project.json", "project.dpb.json")

    def _raise(*_a, **_k):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)

    with pytest.raises(SystemExit) as exc_info:
        select_config(
            cli_arg=None, project_root=tmp_path, interactive=True,
        )
    assert exc_info.value.code == _AMBIGUOUS_EXIT_CODE
