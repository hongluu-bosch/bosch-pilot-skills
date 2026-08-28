"""Multi-config selection for the global / multi-project skill (v1.14.0).

A single project workspace may host several configuration files —
typically when one Bosch tree feeds multiple products (DPB + ESP)
or multiple customers off the same source. Drop them next to
``config/project.json`` as ``config/project.<tag>.json`` (e.g.
``config/project.dpb.json``, ``config/project.esp.json``); the
toolkit picks one per run via the policy below.

Selection policy
----------------

Mirrors the v1.12.1 multi-input "agent contract" so an LLM driver
already familiar with that flow needs zero new vocabulary:

1. **``--config <path>``** — explicit win, skipping discovery
   entirely. Relative paths resolve against the project root
   (``<project>/config/project.dpb.json`` is selectable as just
   ``--config config/project.dpb.json``); absolute paths pass
   through unchanged. Path must exist or :class:`FileNotFoundError`
   fires with a remediation hint.
2. **Single discovered config** — exactly one match in the project
   workspace silently auto-selects, identical to v1.13.x behaviour.
   The bare ``config/project.json`` IS the match in the
   single-config common case.
3. **Multiple discovered configs + TTY** — interactive numbered
   menu. The operator picks one by index (1..N) or by exact tag.
4. **Multiple discovered configs + non-TTY (agent)** — hard error
   to stderr listing every candidate, exit code 4, identical
   contract to ``--list-inputs`` ambiguity. The driving agent
   re-prompts the user, gets a tag back, and re-invokes pipeline
   with ``--config <chosen>``.

Discovery scans only ``<project>/config/`` non-recursively for
``project*.json`` so an unrelated ``config/foo.json`` doesn't
pollute the menu.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


_DISCOVERY_GLOB = "project*.json"
"""Glob applied inside ``<project>/config/`` for auto-discovery.
Matches ``project.json`` and any ``project.<tag>.json`` sibling but
deliberately *not* schemas, settings, or other unrelated configs.
"""


_AMBIGUOUS_EXIT_CODE = 4
"""Reserved exit code for "multiple configs and the agent must pick".
Distinct from the v1.12.1 multi-input contract (exit 4 there too)
so any wrapper script can branch on a single sentinel for both
ambiguity classes."""


def discover_configs(project_root: Path) -> List[Path]:
    """List every ``config/project*.json`` candidate in the workspace.

    Returns sorted absolute paths so the order is deterministic
    across operating systems (Windows / Linux disagree on raw
    glob ordering). Sort key is the filename so
    ``config/project.dpb.json`` predictably comes before
    ``config/project.esp.json`` and the bare ``config/project.json``
    sorts first because it's lexicographically shortest. Empty list
    when the ``config/`` folder is missing or has no matches; the
    caller decides what to do (init prompt, fallback, etc.).
    """
    config_dir = Path(project_root) / "config"
    if not config_dir.is_dir():
        return []
    matches = sorted(
        (p for p in config_dir.glob(_DISCOVERY_GLOB) if p.is_file()),
        key=lambda p: p.name,
    )
    return matches


def _config_tag(path: Path) -> str:
    """Short label for a config: ``"default"`` for the bare file,
    otherwise the dotted infix. So ``project.json`` -> ``"default"``,
    ``project.dpb.json`` -> ``"dpb"``, ``project.gac_olympus.json``
    -> ``"gac_olympus"``. Used for the interactive-menu legend and
    for exact-tag matching."""
    name = path.name
    if name == "project.json":
        return "default"
    if name.startswith("project.") and name.endswith(".json"):
        return name[len("project.") : -len(".json")]
    return name


def format_candidates(configs: List[Path], project_root: Path) -> List[str]:
    """Human-readable lines for an ambiguity diagnostic.

    Each line is ``"<tag>\\t<relative-path>"`` so an agent can split
    on tab to pull out either field; an operator just sees the
    tag-and-path columns. Relative-to-``project_root`` so the lines
    don't drag absolute filesystem noise into the prompt.
    """
    out = []
    for cfg in configs:
        try:
            rel = cfg.relative_to(project_root)
        except ValueError:
            rel = cfg
        out.append(f"{_config_tag(cfg)}\t{rel.as_posix()}")
    return out


def _resolve_explicit(cli_arg: str, project_root: Path) -> Path:
    """Resolve ``--config <cli_arg>`` against the project root.

    Absolute paths pass through verbatim; relatives anchor at
    ``project_root`` so an agent can pass either ``config/project.dpb.json``
    or ``project.dpb.json`` and both work.
    """
    p = Path(cli_arg).expanduser()
    if not p.is_absolute():
        candidate_full = (project_root / p).resolve()
        candidate_inside_config = (project_root / "config" / p).resolve()
        # Try `<project>/<arg>` first, falling back to
        # `<project>/config/<arg>` for the agent who naturally
        # thinks in terms of "project.dpb.json".
        if candidate_full.is_file():
            return candidate_full
        if candidate_inside_config.is_file():
            return candidate_inside_config
        raise FileNotFoundError(
            f"--config {cli_arg!r} not found. Tried:\n"
            f"  - {candidate_full}\n"
            f"  - {candidate_inside_config}\n"
            f"Use --list-configs to see what's available in this workspace."
        )
    p = p.resolve()
    if not p.is_file():
        raise FileNotFoundError(
            f"--config {cli_arg!r} does not exist. Did you mean a "
            f"workspace-relative path like 'config/project.dpb.json'?"
        )
    return p


def _interactive_choose(configs: List[Path], project_root: Path) -> Path:
    """TTY menu loop. Tail-recursive on bad input.

    Accepts either a 1-based index or the exact tag, so the
    operator can type ``2`` or ``dpb`` for the same effect. Ctrl-C
    propagates so the operator can escape.
    """
    print()
    print("Multiple configurations found in this workspace:")
    for idx, cfg in enumerate(configs, start=1):
        try:
            rel = cfg.relative_to(project_root).as_posix()
        except ValueError:
            rel = str(cfg)
        print(f"  {idx}. [{_config_tag(cfg)}]  {rel}")
    print()
    while True:
        raw = input("Pick one (number or tag): ").strip()
        if not raw:
            print("  ! Please enter a number or a tag.")
            continue
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(configs):
                return configs[idx]
            print(f"  ! Index {raw} out of range; pick 1..{len(configs)}.")
            continue
        match = next((c for c in configs if _config_tag(c) == raw), None)
        if match is not None:
            return match
        print(f"  ! Unknown tag {raw!r}; pick one of "
              f"{[_config_tag(c) for c in configs]}.")


def select_config(
    *,
    cli_arg: Optional[str],
    project_root: Path,
    interactive: Optional[bool] = None,
) -> Path:
    """Resolve which ``config/project*.json`` to load this run.

    Implements the four-step policy documented at the top of the
    module. Returns an absolute :class:`Path` to the chosen config
    file, ready to feed :func:`scripts.config.load_project_config`.

    :param cli_arg: Value of ``--config`` from argparse, or ``None``.
    :param project_root: The already-resolved project workspace.
    :param interactive: ``None`` (default) auto-detects via
      :func:`sys.stdin.isatty`; tests pin it explicitly.

    :raises FileNotFoundError: when an explicit ``--config`` path
      doesn't resolve.
    :raises SystemExit: with :data:`_AMBIGUOUS_EXIT_CODE` when
      multiple candidates are found in non-TTY mode and the agent
      hasn't disambiguated. The accompanying stderr message lists
      every candidate so the agent can re-prompt.
    """
    if cli_arg:
        return _resolve_explicit(cli_arg, project_root)

    candidates = discover_configs(project_root)

    if not candidates:
        # No config at all -- caller handles the empty-workspace
        # case (typically by falling through to defaults). We
        # return the conventional path so error messages downstream
        # name the file the operator most likely expects to see.
        return project_root / "config" / "project.json"

    if len(candidates) == 1:
        return candidates[0]

    if interactive is None:
        interactive = bool(sys.stdin.isatty())

    if interactive:
        try:
            return _interactive_choose(candidates, project_root)
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            print("Aborted; no config selected.", file=sys.stderr)
            sys.exit(_AMBIGUOUS_EXIT_CODE)

    print(
        "ERROR: Multiple did-toolkit configurations found in "
        f"{project_root / 'config'} and no --config <path> was given.",
        file=sys.stderr,
    )
    print("Candidates (tag<TAB>relative-path):", file=sys.stderr)
    for line in format_candidates(candidates, project_root):
        print(f"  {line}", file=sys.stderr)
    print(
        "Re-run with --config <path> (relative to the workspace, e.g. "
        "'config/project.dpb.json') or --list-configs to enumerate.",
        file=sys.stderr,
    )
    sys.exit(_AMBIGUOUS_EXIT_CODE)


__all__ = [
    "discover_configs",
    "format_candidates",
    "select_config",
]
