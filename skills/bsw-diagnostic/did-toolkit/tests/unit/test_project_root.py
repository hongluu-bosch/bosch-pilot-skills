"""Unit tests for the project-root resolver.

The four-tier policy in ``scripts/project_root.py`` — explicit
CLI > env var > CWD walk > skill-root fallback — is the foundation
for the global / multi-project skill. Every tier needs deterministic
test coverage so a future refactor (e.g. swapping the marker file)
can't quietly change resolution semantics.

The only recognised workspace shape is
``<container>/.DCOM_AI/DID_Toolkit_PRJ/{config,inputs,outputs,scripts,state}/``
— a two-level hidden path that namespaces this skill's workspace
(``DID_Toolkit_PRJ/``) under the generic AI-tooling umbrella
(``.DCOM_AI/``). Every test below scaffolds the workspace via the
``_scaffold_workspace`` helper and asserts the resolver returns the
workspace path (not the container).

Tests are dependency-injected via the ``cli_arg``, ``env``, ``cwd``,
and ``skill_root`` keyword arguments on :func:`resolve_project_root`,
so nothing here touches the real environment or working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from project_root import (
    DCOM_AI_UMBRELLA_DIR,
    DCOM_AI_WORKSPACE_DIR,
    ENV_VAR,
    PROJECT_MARKER_PATH,
    TOOLKIT_SUBDIR,
    find_project_root_upward,
    is_project_root,
    resolve_project_root,
    workspace_for,
)


# ---------------------------------------------------------------------------
# is_project_root + find_project_root_upward (the cheap building blocks)
# ---------------------------------------------------------------------------


def _scaffold_workspace(container: Path) -> Path:
    """Create a minimal
    ``<container>/.DCOM_AI/DID_Toolkit_PRJ/config/project.json`` so
    ``container`` satisfies :func:`is_project_root`. Returns the
    *workspace* path
    (``container / .DCOM_AI / DID_Toolkit_PRJ``), i.e. the path
    the resolver will hand to ``controller.base_dir`` consumers."""
    workspace = container / DCOM_AI_UMBRELLA_DIR / TOOLKIT_SUBDIR
    (workspace / "config").mkdir(parents=True, exist_ok=True)
    (workspace / "config" / "project.json").write_text("{}", encoding="utf-8")
    return workspace


def test_is_project_root_true_when_marker_exists(tmp_path):
    _scaffold_workspace(tmp_path)
    assert is_project_root(tmp_path) is True


def test_is_project_root_false_for_empty_dir(tmp_path):
    assert is_project_root(tmp_path) is False


def test_is_project_root_false_for_flat_config(tmp_path):
    """The flat layout is not recognised: a bare
    ``<container>/config/project.json`` (no
    ``.DCOM_AI/DID_Toolkit_PRJ/`` wrapping) does not count as a
    workspace. Catches a regression that silently re-adds backward
    compatibility."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "project.json").write_text("{}", encoding="utf-8")
    assert is_project_root(tmp_path) is False


def test_is_project_root_false_for_single_level_dcom_ai(tmp_path):
    """An old single-level ``.DCOM_AI/config/project.json`` (without
    the ``DID_Toolkit_PRJ/`` namespace) does not count as a
    workspace. Pinned so v2.2.0's no-backward-compat decision can't
    silently regress into accepting legacy layouts."""
    (tmp_path / DCOM_AI_UMBRELLA_DIR / "config").mkdir(parents=True)
    (tmp_path / DCOM_AI_UMBRELLA_DIR / "config" / "project.json").write_text(
        "{}", encoding="utf-8"
    )
    assert is_project_root(tmp_path) is False


def test_is_project_root_false_when_marker_is_a_directory(tmp_path):
    """A *directory* named ``project.json`` shouldn't satisfy the
    marker check; only a *file* counts. Catches a future bug where
    someone copies a tree wrong and the toolkit silently picks a
    non-project path."""
    bad = tmp_path / DCOM_AI_WORKSPACE_DIR / "config" / "project.json"
    bad.mkdir(parents=True)
    assert is_project_root(tmp_path) is False


def test_marker_path_constant_is_stable():
    """Pin the marker path so docs that quote it stay accurate.

    The marker path is relative to the **container** (not the
    workspace) and includes the two-level
    ``.DCOM_AI/DID_Toolkit_PRJ/`` hop."""
    assert PROJECT_MARKER_PATH == ".DCOM_AI/DID_Toolkit_PRJ/config/project.json"
    assert DCOM_AI_WORKSPACE_DIR == ".DCOM_AI/DID_Toolkit_PRJ"
    assert DCOM_AI_UMBRELLA_DIR == ".DCOM_AI"
    assert TOOLKIT_SUBDIR == "DID_Toolkit_PRJ"


def test_workspace_for_appends_two_level_hop(tmp_path):
    """``workspace_for(container)`` returns
    ``container/.DCOM_AI/DID_Toolkit_PRJ`` — the path the pipeline
    treats as ``self.base_dir`` once :func:`is_project_root`
    confirmed the marker is present. The leaf segment is the
    skill's namespace (``DID_Toolkit_PRJ``); the umbrella sits one
    level up."""
    workspace = _scaffold_workspace(tmp_path)
    assert workspace_for(tmp_path) == workspace
    assert workspace_for(tmp_path).name == TOOLKIT_SUBDIR
    assert workspace_for(tmp_path).parent.name == DCOM_AI_UMBRELLA_DIR


def test_find_project_root_returns_workspace(tmp_path):
    """``find_project_root_upward`` returns the workspace (i.e.
    ``container/.DCOM_AI/DID_Toolkit_PRJ/``), not the container —
    so ``self.base_dir`` consumers (Phase 1/2/3, DOORS) see
    ``inputs/`` / ``outputs/`` / ``state/`` etc. relative to the
    workspace transparently."""
    workspace = _scaffold_workspace(tmp_path / "ws")
    assert find_project_root_upward(tmp_path / "ws") == workspace


def test_find_project_root_walks_upward_from_workspace_subdir(tmp_path):
    """Operator running the pipeline from inside a Phase output dir
    (e.g. ``.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/``) still finds
    the workspace by walking ancestors."""
    workspace = _scaffold_workspace(tmp_path / "ws")
    deep = workspace / "outputs" / "fscs" / "subdir"
    deep.mkdir(parents=True)
    assert find_project_root_upward(deep) == workspace


def test_find_project_root_walks_upward_from_bosch_subdir(tmp_path):
    """Operator running the pipeline from inside the Bosch tree
    (e.g. ``Fe_Super/rb/as/.../core/``) also finds the workspace —
    the walker climbs out of the Bosch tree into the container and
    then hops into ``.DCOM_AI/DID_Toolkit_PRJ/``."""
    container = tmp_path / "bosch_project"
    container.mkdir()
    workspace = _scaffold_workspace(container)
    bosch_subdir = container / "Fe_Super" / "rb" / "as" / "rbcn" / "core"
    bosch_subdir.mkdir(parents=True)
    assert find_project_root_upward(bosch_subdir) == workspace


def test_find_project_root_walks_upward_from_umbrella_dir(tmp_path):
    """Operator who ``cd``-d into the ``.DCOM_AI/`` umbrella itself
    (one hop short of the workspace) still resolves: the upward
    walker climbs out into the container and then hops back down
    into the full ``.DCOM_AI/DID_Toolkit_PRJ/`` workspace."""
    container = tmp_path / "container"
    container.mkdir()
    workspace = _scaffold_workspace(container)
    umbrella = container / DCOM_AI_UMBRELLA_DIR
    assert find_project_root_upward(umbrella) == workspace


def test_find_project_root_returns_none_when_no_marker(tmp_path):
    deep = tmp_path / "no_workspace_here"
    deep.mkdir()
    assert find_project_root_upward(deep) is None


# ---------------------------------------------------------------------------
# resolve_project_root: the four tiers, in priority order
# ---------------------------------------------------------------------------


def test_cli_arg_takes_precedence_over_everything(tmp_path):
    cli_ws = _scaffold_workspace(tmp_path / "cli_pick")
    env_ws = _scaffold_workspace(tmp_path / "env_pick")
    walk_ws = _scaffold_workspace(tmp_path / "walk_pick")
    fallback = _scaffold_workspace(tmp_path / "fallback")

    result = resolve_project_root(
        cli_arg=str(tmp_path / "cli_pick"),
        env={ENV_VAR: str(tmp_path / "env_pick")},
        cwd=walk_ws,
        skill_root=fallback,
    )
    assert result == cli_ws


def test_cli_arg_missing_raises_filenotfounderror(tmp_path):
    """Typo in --project-root should fail loud (not silently fall back)."""
    bogus = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError, match="--project-root"):
        resolve_project_root(cli_arg=str(bogus), env={}, cwd=tmp_path)


def test_cli_arg_accepts_container_and_hops_to_workspace(tmp_path):
    """``--project-root <container>`` returns the
    ``.DCOM_AI/DID_Toolkit_PRJ/`` workspace, not the container
    path — so the operator can pass the friendlier container path
    (which is also where the Bosch tree lives) and have the
    resolver follow the two-level hop transparently."""
    container = tmp_path / "container"
    container.mkdir()
    workspace = _scaffold_workspace(container)

    result = resolve_project_root(
        cli_arg=str(container), env={}, cwd=tmp_path, skill_root=None,
    )
    assert result == workspace


def test_cli_arg_accepts_umbrella_and_hops_one_level(tmp_path):
    """Operators who pass the ``.DCOM_AI/`` umbrella path also
    succeed — the validator hops down one level into
    ``DID_Toolkit_PRJ/`` when the marker is present there."""
    container = tmp_path / "container"
    container.mkdir()
    workspace = _scaffold_workspace(container)

    result = resolve_project_root(
        cli_arg=str(container / DCOM_AI_UMBRELLA_DIR),
        env={}, cwd=tmp_path, skill_root=None,
    )
    assert result == workspace


def test_cli_arg_accepts_workspace_path_directly(tmp_path):
    """Operators who pass the
    ``.DCOM_AI/DID_Toolkit_PRJ/`` workspace path directly also
    succeed — the validator is symmetric across the three
    acceptable inputs (container, umbrella, workspace)."""
    container = tmp_path / "container"
    container.mkdir()
    workspace = _scaffold_workspace(container)

    result = resolve_project_root(
        cli_arg=str(workspace), env={}, cwd=tmp_path, skill_root=None,
    )
    assert result == workspace


def test_env_var_picked_when_no_cli(tmp_path):
    env_ws = _scaffold_workspace(tmp_path / "env_pick")
    walk_ws = _scaffold_workspace(tmp_path / "walk_pick")

    result = resolve_project_root(
        cli_arg=None,
        env={ENV_VAR: str(tmp_path / "env_pick")},
        cwd=walk_ws,
    )
    assert result == env_ws


def test_env_var_missing_path_raises(tmp_path):
    bogus = tmp_path / "nope"
    with pytest.raises(FileNotFoundError, match=ENV_VAR):
        resolve_project_root(cli_arg=None, env={ENV_VAR: str(bogus)}, cwd=tmp_path)


def test_env_var_empty_string_treated_as_unset(tmp_path):
    """An ENV that's literally empty (or only whitespace) shouldn't
    poison resolution; treat it as if the variable wasn't set."""
    walk_ws = _scaffold_workspace(tmp_path / "walk_pick")
    result = resolve_project_root(
        cli_arg=None,
        env={ENV_VAR: "   "},
        cwd=walk_ws,
    )
    assert result == walk_ws


def test_env_var_hops_container_to_workspace(tmp_path):
    """Same container/umbrella/workspace symmetry for the env-var tier:
    setting ``$DID_TOOLKIT_PROJECT_ROOT`` to the container resolves
    to the ``.DCOM_AI/DID_Toolkit_PRJ/`` workspace, not the
    container itself."""
    container = tmp_path / "container"
    container.mkdir()
    workspace = _scaffold_workspace(container)

    result = resolve_project_root(
        cli_arg=None, env={ENV_VAR: str(container)}, cwd=tmp_path,
        skill_root=None,
    )
    assert result == workspace


def test_cwd_walk_finds_workspace(tmp_path):
    """Walking from inside a workspace subdir (Phase output) finds
    the workspace via :func:`find_project_root_upward`."""
    workspace = _scaffold_workspace(tmp_path / "ws")
    deep = workspace / "outputs" / "arxml"
    deep.mkdir(parents=True)

    result = resolve_project_root(cli_arg=None, env={}, cwd=deep)
    assert result == workspace


def test_falls_back_to_skill_root_when_nothing_else_hits(tmp_path):
    nowhere = tmp_path / "no_workspace_anywhere_below"
    nowhere.mkdir()
    skill = tmp_path / "skill_install"
    skill.mkdir()

    result = resolve_project_root(
        cli_arg=None, env={}, cwd=nowhere, skill_root=skill,
    )
    assert result == skill.resolve()


def test_no_fallback_raises_runtime_error(tmp_path):
    """Tests that opt-in callers (passing ``skill_root=None``) get a
    descriptive error instead of an implicit fallback. Production
    pipeline.py always supplies a skill_root so this branch is
    test-only, but it pins the contract."""
    nowhere = tmp_path / "absolutely_nothing"
    nowhere.mkdir()
    with pytest.raises(RuntimeError, match="--init-project"):
        resolve_project_root(cli_arg=None, env={}, cwd=nowhere, skill_root=None)
