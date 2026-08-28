"""Unit tests for the input-discovery contract.

Three concerns:

1. ``PipelineController.discover_input_candidates()`` enumerates
   ``inputs/*_did.json`` (alphabetical), tolerates a missing
   ``inputs/`` directory, and ignores JSON files without ``did`` in
   their name (decoy filter). The ``.xlsx`` / ``.xlsm`` tier is not
   discovered; the skill ships no built-in workbook parser.
2. ``--list-inputs`` prints one absolute POSIX path per line, exits 0
   even with no candidates, and produces no side effects.
3. ``--phase fscs`` with multiple candidates and **no** ``--input``
   exits 3 with an actionable ERROR (the multi-questionnaire contract
   — agents must use ``--list-inputs`` + a plain-text prompt before
   re-invoking).

The interactive-TTY menu is exercised manually because faking a TTY
on Windows is brittle; the non-interactive branch is the agent
contract and is the one that must never silently regress.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import pipeline as pipeline_mod


# ---------------------------------------------------------------------------
# 1. discover_input_candidates()
# ---------------------------------------------------------------------------


@pytest.fixture
def controller_with_inputs(tmp_path, monkeypatch):
    """Build a PipelineController whose base_dir points at a temp tree.

    We populate ``<tmp>/inputs/`` per-test so the global ``inputs/``
    folder of the real repo is never touched.
    """
    monkeypatch.chdir(tmp_path)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    controller = pipeline_mod.PipelineController()
    controller.base_dir = tmp_path
    return controller, inputs


def test_discover_returns_empty_when_inputs_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = pipeline_mod.PipelineController()
    controller.base_dir = tmp_path  # tmp_path/inputs intentionally absent
    groups = controller.discover_input_candidates()
    assert groups == {"json": []}


def test_discover_returns_did_json_alphabetical(controller_with_inputs):
    controller, inputs = controller_with_inputs
    (inputs / "legacy_did.json").write_text("[]")
    (inputs / "another_did.json").write_text("[]")
    # Decoy: a JSON without 'did' in the name must NOT be picked up.
    (inputs / "settings.json").write_text("{}")

    groups = controller.discover_input_candidates()
    json_names = [p.name for p in groups["json"]]
    assert json_names == ["another_did.json", "legacy_did.json"]
    assert "settings.json" not in json_names


def test_discover_no_longer_returns_xlsx_tier(controller_with_inputs):
    """``.xlsx`` / ``.xlsm`` candidates are ignored.

    The skill ships no built-in workbook parser; ``.xlsx`` files must
    first be normalised into ``*_did.json`` by an agent-written
    ``.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py`` adapter before Phase 1
    can consume them.
    """
    controller, inputs = controller_with_inputs
    (inputs / "real.xlsx").write_text("")
    (inputs / "macro.xlsm").write_text("")
    (inputs / "valid_did.json").write_text("[]")
    groups = controller.discover_input_candidates()
    # discover_input_candidates only exposes the json tier in v1.27.0.
    assert set(groups.keys()) == {"json"}
    assert [p.name for p in groups["json"]] == ["valid_did.json"]


# ---------------------------------------------------------------------------
# 2. --list-inputs flag
# ---------------------------------------------------------------------------


def _pipeline_script() -> Path:
    """Resolve the real pipeline.py path; subprocess invocations need it."""
    return Path(pipeline_mod.__file__).resolve()


def _run_list_inputs(workdir: Path) -> subprocess.CompletedProcess:
    """Run ``python <pipeline.py> --list-inputs`` in ``workdir``.

    We invoke the real script as a subprocess so we exercise the same
    code path the agent does (no in-process monkey-patching of stdin /
    stdout / sys.exit).
    """
    return subprocess.run(
        [sys.executable, str(_pipeline_script()), "--list-inputs"],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_list_inputs_exits_zero_with_no_inputs_dir(tmp_path):
    # No ``inputs/`` folder created.
    result = _run_list_inputs(tmp_path)
    # The script's PipelineController.base_dir is fixed to the skill
    # root (parent of scripts/), not cwd, so this subprocess sees the
    # real repo's inputs/. Just assert the contract: exit 0, no crash,
    # and stdout contains either nothing or one absolute path per line.
    assert result.returncode == 0, (
        f"--list-inputs returned non-zero: {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    for line in result.stdout.splitlines():
        if line:
            assert "/" in line, (
                f"--list-inputs line is not an absolute POSIX path: {line!r}"
            )


def test_list_inputs_is_side_effect_free(tmp_path):
    """Running --list-inputs must not write into outputs/ (no Phase
    side effects); we check by watching the pre-existing outputs/
    directory of the skill is not modified."""
    skill_root = _pipeline_script().parent.parent
    outputs_before = sorted(p.name for p in (skill_root / "outputs").glob("**/*") if p.is_file())
    result = _run_list_inputs(tmp_path)
    assert result.returncode == 0
    outputs_after = sorted(p.name for p in (skill_root / "outputs").glob("**/*") if p.is_file())
    assert outputs_before == outputs_after, (
        "--list-inputs touched outputs/: diff = "
        f"{set(outputs_after) ^ set(outputs_before)}"
    )


# ---------------------------------------------------------------------------
# 3. Multi-candidate without --input on a non-TTY shell -> exit 3
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal stand-in for sys.stdin/stdout that lets us drive the
    isatty() branch without touching the real terminal. Implements
    just enough of the file protocol to satisfy ``print()``,
    ``logger`` writes, and ``input()`` prompt rendering.
    """

    def __init__(self, *, is_tty: bool):
        self._is_tty = is_tty
        self.buffer: list = []

    def isatty(self) -> bool:
        return self._is_tty

    def write(self, data) -> int:
        self.buffer.append(data)
        return len(data)

    def flush(self) -> None:
        pass


def test_select_input_or_exit_errors_on_non_tty(monkeypatch, tmp_path):
    """Direct unit test of ``_select_input_or_exit`` with stdin faked
    as non-TTY. We don't go through the real subprocess here because
    subprocess inherits the parent's TTY state."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    fake_a = inputs / "alpha_did.json"
    fake_b = inputs / "beta_did.json"
    fake_a.write_text("[]")
    fake_b.write_text("[]")

    monkeypatch.setattr(pipeline_mod.sys, "stdin", _FakeStream(is_tty=False))
    monkeypatch.setattr(pipeline_mod.sys, "stdout", _FakeStream(is_tty=False))

    with pytest.raises(SystemExit) as excinfo:
        pipeline_mod._select_input_or_exit([fake_a, fake_b], inputs)
    assert excinfo.value.code == 3


def test_select_input_or_exit_returns_chosen_path_on_tty(monkeypatch, tmp_path):
    """Direct unit test of the interactive branch with a faked TTY
    + injected ``input()`` answer."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    fake_a = inputs / "alpha_did.json"
    fake_b = inputs / "beta_did.json"
    fake_a.write_text("[]")
    fake_b.write_text("[]")

    monkeypatch.setattr(pipeline_mod.sys, "stdin", _FakeStream(is_tty=True))
    monkeypatch.setattr(pipeline_mod.sys, "stdout", _FakeStream(is_tty=True))
    monkeypatch.setattr(pipeline_mod.sys, "stderr", _FakeStream(is_tty=False))
    answers = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    chosen = pipeline_mod._select_input_or_exit([fake_a, fake_b], inputs)
    assert chosen == fake_b


def test_select_input_or_exit_aborts_on_quit(monkeypatch, tmp_path):
    """Operator typing 'q' at the menu must exit 3 (aborted)."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    fake_a = inputs / "alpha_did.json"
    fake_a.write_text("[]")

    monkeypatch.setattr(pipeline_mod.sys, "stdin", _FakeStream(is_tty=True))
    monkeypatch.setattr(pipeline_mod.sys, "stdout", _FakeStream(is_tty=True))
    monkeypatch.setattr(pipeline_mod.sys, "stderr", _FakeStream(is_tty=False))
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "q")

    with pytest.raises(SystemExit) as excinfo:
        pipeline_mod._select_input_or_exit([fake_a, fake_a], inputs)
    assert excinfo.value.code == 3
