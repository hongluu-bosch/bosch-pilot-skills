"""Project-root resolution for the multi-project skill.

The toolkit cleanly separates two concepts:

* **Skill root** — where the immutable code + reference assets
  live (``scripts/``, ``reference/``, ``templates/``, ``tests/``).
  Same path the toolkit was installed at; never relocated at
  runtime.
* **Project root** — where the operator's *data* lives (``inputs/``,
  ``outputs/``, ``config/``, ``state/``). One operator may have
  several of these, each pointing at a different real Bosch tree.

This module owns the resolution policy. The ``PipelineController``
calls :func:`resolve_project_root` once at construction and re-
roots every data path off the result; the rest of the pipeline
keeps using ``self.base_dir`` and stays oblivious to the
multi-project distinction.

Workspace layout
----------------

Every Bosch project container hosts the toolkit's workspace at
``<container>/.DCOM_AI/DID_Toolkit_PRJ/`` — a two-level hidden
path that namespaces the did-toolkit's artefacts under the
generic ``.DCOM_AI/`` umbrella (so the same container can later
host other AI tooling under sibling subdirectories). The
workspace holds ``config/``, ``inputs/``, ``outputs/``,
``scripts/``, ``state/``.

The dot-prefixed top level mirrors the ``.git/`` convention so
file-tree viewers (Bosch tooling, IDE explorers) hide the
toolkit's artefacts by default; the second-level
``DID_Toolkit_PRJ`` is a fixed namespace owned by this skill.

Resolution policy
-----------------

Four-tier search, first hit wins:

1. **Explicit CLI flag** ``--project-root <path>`` — handed in by
   the caller. Always absolute on return; non-existent paths
   raise ``FileNotFoundError`` so a typo is loud.
2. **Environment variable** ``DID_TOOLKIT_PROJECT_ROOT`` — convenient
   for shell sessions or CI that always target one workspace.
   Same validation as the CLI flag.
3. **CWD walk** — search the current working directory and every
   ancestor for a directory that has a
   ``.DCOM_AI/DID_Toolkit_PRJ/config/project.json`` child. The
   first match becomes the project container; the resolver
   returns ``<container>/.DCOM_AI/DID_Toolkit_PRJ/`` as the
   workspace, mirroring how ``git`` finds the repo root from any
   subdirectory.
4. **Skill root fallback** — when nothing else hits, default to
   the skill folder. Lets a fresh checkout still resolve
   *somewhere* sensible before ``--init-project`` runs.

``--project-root`` and ``$DID_TOOLKIT_PROJECT_ROOT`` accept any
of the three sensible shapes: the **container path** (resolver
hops down through ``.DCOM_AI/DID_Toolkit_PRJ/`` automatically),
the ``.DCOM_AI/`` parent path (one hop into ``DID_Toolkit_PRJ``),
or the workspace path itself.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


DCOM_AI_UMBRELLA_DIR = ".DCOM_AI"
"""Top-level namespace under the project container for any AI tooling
artefacts (this skill and potential future siblings). Dot-prefixed
so file-tree viewers hide it by default, like ``.git/``."""


TOOLKIT_SUBDIR = "DID_Toolkit_PRJ"
"""Second-level namespace owned by **this** skill. Lives under
``DCOM_AI_UMBRELLA_DIR`` so the same project container can later
host parallel AI tools under sibling subdirectories without
colliding with the did-toolkit's ``config/`` / ``inputs/`` /
``outputs/`` / ``state/`` tree.

Fixed string (not configurable per project) so the resolver's
CWD-walk marker check stays cheap and the documentation can name
one canonical path."""


DCOM_AI_WORKSPACE_DIR = f"{DCOM_AI_UMBRELLA_DIR}/{TOOLKIT_SUBDIR}"
"""Composite relative path from the project container to the
toolkit's workspace (``.DCOM_AI/DID_Toolkit_PRJ``). Kept as a
single constant so callers that want the whole two-level segment
in error messages / templates have one source of truth."""


PROJECT_MARKER_PATH = f"{DCOM_AI_WORKSPACE_DIR}/config/project.json"
"""Relative-to-container path of the file whose existence identifies
a directory as a did-toolkit workspace. The marker is checked by
:func:`is_project_root` and :func:`find_project_root_upward`."""


ENV_VAR = "DID_TOOLKIT_PROJECT_ROOT"
"""Environment variable consulted by :func:`resolve_project_root`."""


def is_project_root(path: Path) -> bool:
    """True iff ``path`` is a project container hosting a workspace.

    The predicate hits when
    ``path/.DCOM_AI/DID_Toolkit_PRJ/config/project.json`` exists
    as a file. The contents are not validated here (that's
    :mod:`scripts.config.loader`'s job); we only check existence so
    the discovery walk is fast and side-effect-free.

    Callers that need the actual workspace ``Path`` use
    :func:`workspace_for` (which appends the two-level
    ``.DCOM_AI/DID_Toolkit_PRJ/`` hop) rather than treating
    ``path`` as the workspace itself.
    """
    return (Path(path) / PROJECT_MARKER_PATH).is_file()


def workspace_for(container: Path) -> Path:
    """Map a project container to its workspace directory.

    Companion to :func:`is_project_root`: when called on a path
    that satisfies the predicate, returns
    ``container / .DCOM_AI / DID_Toolkit_PRJ`` — the directory the
    pipeline treats as ``self.base_dir`` (where ``config/`` /
    ``inputs/`` / ``outputs/`` / ``scripts/`` / ``state/`` live).

    Returns the joined path unconditionally; callers are
    responsible for satisfying :func:`is_project_root` first if
    they want guaranteed existence.
    """
    return Path(container) / DCOM_AI_UMBRELLA_DIR / TOOLKIT_SUBDIR


def find_project_root_upward(start: Path) -> Optional[Path]:
    """Walk ``start`` and its ancestors looking for a workspace.

    Returns the first ``container/.DCOM_AI/`` workspace found, or
    ``None`` when the walk exhausts the filesystem root. Pure
    read-only — no I/O beyond ``stat`` calls.

    The walk hits the container regardless of whether the operator
    ``cd``-d into the container itself, the ``.DCOM_AI/`` umbrella,
    or all the way into ``.DCOM_AI/DID_Toolkit_PRJ/`` — pathlib's
    ``parents`` chain eventually surfaces a container that satisfies
    :func:`is_project_root`, so the pipeline launches from any of
    those locations.
    """
    start = Path(start).resolve()
    for candidate in [start, *start.parents]:
        if is_project_root(candidate):
            return workspace_for(candidate)
    return None


def _validate_explicit(path_str: str, *, source: str) -> Path:
    """Resolve ``path_str`` and confirm it points at a workspace.

    Used by both the CLI-flag and env-var paths so the error
    surface is identical: a typo in either route raises
    ``FileNotFoundError`` with a remediation hint that names the
    *source* of the bad value (so the operator knows whether to fix
    the shell line or the env file).

    Three acceptable input shapes — checked in order; first hit
    wins:

    * **Container path** (typical) — ``path_str`` is the project
      container; we hop to
      ``path_str/.DCOM_AI/DID_Toolkit_PRJ/`` automatically as long
      as the marker file is present there.
    * **Umbrella path** — ``path_str`` is the ``.DCOM_AI/`` dir;
      we hop into ``DID_Toolkit_PRJ/`` as long as the marker is
      present.
    * **Workspace path** — ``path_str`` is already the
      ``.DCOM_AI/DID_Toolkit_PRJ/`` workspace dir; returned as-is
      when the marker is present.

    A directory that does not exist (typo / un-scaffolded path)
    raises ``FileNotFoundError`` so the failure is loud; an
    existing directory that doesn't match any of the three shapes
    is returned as-is and the caller (typically the pipeline
    controller) surfaces the missing-config error downstream.
    """
    p = Path(path_str).expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(
            f"{source} points at {p!s}, which does not exist or is not a "
            f"directory. Either create the directory (and run "
            f"`pipeline.py --init-project {p!s}` to scaffold it as a "
            f"did-toolkit workspace) or fix the {source!r} value."
        )
    container_workspace = p / DCOM_AI_UMBRELLA_DIR / TOOLKIT_SUBDIR
    if (container_workspace / "config" / "project.json").is_file():
        return container_workspace
    if p.name == DCOM_AI_UMBRELLA_DIR:
        umbrella_workspace = p / TOOLKIT_SUBDIR
        if (umbrella_workspace / "config" / "project.json").is_file():
            return umbrella_workspace
    if (
        p.name == TOOLKIT_SUBDIR
        and p.parent.name == DCOM_AI_UMBRELLA_DIR
        and (p / "config" / "project.json").is_file()
    ):
        return p
    return p


def resolve_project_root(
    *,
    cli_arg: Optional[str] = None,
    env: Optional[dict] = None,
    cwd: Optional[Path] = None,
    skill_root: Optional[Path] = None,
) -> Path:
    """Resolve the project workspace per the four-tier policy.

    All inputs are dependency-injected so the function is unit-test
    friendly: tests can pass a fake ``env`` dict and ``cwd`` without
    touching the real environment or working directory.

    :param cli_arg: Value of ``--project-root`` from argparse, or
        ``None`` when the operator didn't pass it.
    :param env: ``os.environ``-shaped mapping; defaults to
        ``os.environ`` so production callers don't pass it. Tests
        inject a small dict to control the env-var path
        deterministically.
    :param cwd: Starting directory for the upward walk; defaults to
        :func:`Path.cwd`. Tests pass a tmp path here.
    :param skill_root: Final-tier fallback when none of the above
        hit. Production callers pass the resolved skill folder so a
        v1.13.x-style single-workspace install keeps working.
        ``None`` makes the function raise instead of falling back,
        which the tests use to pin "no implicit default" behaviour.
    :returns: An absolute :class:`Path` to a project workspace.
    :raises FileNotFoundError: when an explicit CLI / env path does
        not exist or is not a directory.
    :raises RuntimeError: when none of the four tiers resolve and no
        ``skill_root`` fallback was provided -- only happens when
        callers deliberately opt out of the legacy fallback.
    """
    if cli_arg:
        return _validate_explicit(cli_arg, source="--project-root")

    env_map = env if env is not None else os.environ
    env_val = env_map.get(ENV_VAR, "").strip()
    if env_val:
        return _validate_explicit(env_val, source=f"${ENV_VAR}")

    walk_start = Path(cwd) if cwd is not None else Path.cwd()
    found = find_project_root_upward(walk_start)
    if found is not None:
        return found

    if skill_root is not None:
        return Path(skill_root).resolve()

    raise RuntimeError(
        "Could not resolve a did-toolkit project root.\n"
        "  • Pass --project-root <path>, OR\n"
        f"  • Set ${ENV_VAR}=<path>, OR\n"
        "  • cd into a directory whose tree contains\n"
        f"    {PROJECT_MARKER_PATH}, OR\n"
        "  • Run `pipeline.py --init-project <path>` to scaffold a new\n"
        "    workspace and a starter config/project.json."
    )


__all__ = [
    "DCOM_AI_UMBRELLA_DIR",
    "DCOM_AI_WORKSPACE_DIR",
    "ENV_VAR",
    "PROJECT_MARKER_PATH",
    "TOOLKIT_SUBDIR",
    "find_project_root_upward",
    "is_project_root",
    "resolve_project_root",
    "workspace_for",
]
