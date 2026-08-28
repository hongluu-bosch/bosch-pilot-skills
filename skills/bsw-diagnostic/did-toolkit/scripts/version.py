"""Version resolution and cross-file consistency check for did-toolkit.

The skill declares its version in **three** places that must stay in
sync for every release cut:

1. ``SKILL.md`` YAML frontmatter ``version:`` field — what Claude /
   Cursor and other skill hosts pick up when loading the skill.
2. ``VERSION`` — a single-line plain-text file at the skill root. This
   is the machine-readable anchor; scripts, CI gates, and the
   ``pipeline.py --version`` self-check read from here first.
3. ``CHANGELOG.md`` — the top entry's ``## [X.Y.Z]`` header is what
   humans actually read when deciding whether to upgrade.

Drift between these three is a classic release-hygiene failure: someone
bumps one and forgets the other two, and downstream consumers end up
believing different things about what they just pulled. This module
centralises the reading logic and provides
:func:`check_version_consistency` so a single ``pipeline.py --version``
invocation can fail loudly on drift.

Design notes
------------

* **``VERSION`` is the source of truth.** It's one line, easy to read
  from any language, and has no markup to parse. ``SKILL.md`` and
  ``CHANGELOG.md`` are validated *against* it, not the other way
  round. When bumping, edit ``VERSION`` first, then mirror into the
  other two files.
* **SemVer regex is deliberately lax on suffixes.** We accept
  ``1.2.3``, ``1.2.3-rc1``, ``1.2.3+build.42`` so pre-release cuts
  don't trip the check, but we reject free-form marketing strings like
  ``"v1.0 RC"``.
* **The CHANGELOG check only inspects the top version header.** Older
  entries are historical records — rewriting them post-hoc is
  explicitly discouraged — so we don't police them.
* **All file reads are UTF-8** because ``CHANGELOG.md`` contains CJK
  entries in Chinese-localised docs and because the rest of the
  toolkit universally assumes UTF-8.

Public API
----------

- :func:`read_version` — returns the canonical version string.
- :func:`check_version_consistency` — returns ``(ok, diagnostics)``
  tuple suitable for CLI exit codes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

_SKILL_ROOT = Path(__file__).resolve().parent.parent

_SEMVER_RE = re.compile(
    r"^(?P<core>\d+\.\d+\.\d+)"      # X.Y.Z
    r"(?:-[0-9A-Za-z.-]+)?"            # optional -rc1, -alpha.2, ...
    r"(?:\+[0-9A-Za-z.-]+)?$"          # optional +build.42
)


def _read_version_file(root: Path = _SKILL_ROOT) -> str:
    """Return the canonical version string from ``VERSION``.

    Raises :class:`FileNotFoundError` if the file is missing (treat
    that as a setup bug — the skill always ships with ``VERSION``).
    """
    return (root / "VERSION").read_text(encoding="utf-8").strip()


def _read_skill_frontmatter_version(root: Path = _SKILL_ROOT) -> str | None:
    """Pull ``version:`` out of ``SKILL.md``'s YAML frontmatter.

    Returns ``None`` when the file has no frontmatter or no ``version``
    key — the caller surfaces this as a drift diagnostic rather than
    an exception so the full report can list every source of drift at
    once.
    """
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    frontmatter = text[3:end]
    for line in frontmatter.splitlines():
        line = line.strip()
        if line.startswith("version:"):
            # ``version: 1.0.0`` or ``version: "1.0.0"``.
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def _read_changelog_top_version(root: Path = _SKILL_ROOT) -> str | None:
    """Extract ``X.Y.Z`` from the top ``## [X.Y.Z]`` header.

    The canonical format is ``## [1.0.0] — 2026-04-20`` (Keep a
    Changelog convention). Anything matching ``## [...]`` wins; a
    bracketed ``Unreleased`` section above it is deliberately
    tolerated so drafts can accumulate without failing the check.
    """
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    for match in re.finditer(r"^##\s*\[([^\]]+)\]", text, re.MULTILINE):
        candidate = match.group(1).strip()
        if candidate.lower() == "unreleased":
            continue
        return candidate
    return None


def read_version(root: Path = _SKILL_ROOT) -> str:
    """Return the canonical version string from ``VERSION``.

    Convenience wrapper used by ``pipeline.py --version`` so callers
    don't have to know where the source of truth lives.
    """
    return _read_version_file(root)


def check_version_consistency(
    root: Path = _SKILL_ROOT,
) -> Tuple[bool, List[str]]:
    """Verify all three version sources agree.

    Returns ``(ok, diagnostics)``. ``ok`` is ``True`` when every
    readable source matches ``VERSION`` **and** the canonical string
    parses as SemVer. ``diagnostics`` is a list of human-readable
    strings: the first is always the authoritative version line
    (``did-toolkit X.Y.Z``); subsequent entries describe each
    discrepancy found, suitable for printing on stderr.
    """
    try:
        canonical = _read_version_file(root)
    except FileNotFoundError:
        return False, ["VERSION file missing from skill root"]

    diagnostics: List[str] = [f"did-toolkit {canonical}"]

    if not _SEMVER_RE.match(canonical):
        diagnostics.append(
            f"VERSION contents '{canonical}' is not valid SemVer "
            f"(expected X.Y.Z[-pre][+build])"
        )
        return False, diagnostics

    sources: Dict[str, str | None] = {
        "SKILL.md frontmatter": _read_skill_frontmatter_version(root),
        "CHANGELOG.md top entry": _read_changelog_top_version(root),
    }

    ok = True
    for label, value in sources.items():
        if value is None:
            diagnostics.append(f"[drift] {label}: no version found")
            ok = False
        elif value != canonical:
            diagnostics.append(
                f"[drift] {label}: '{value}' != VERSION '{canonical}'"
            )
            ok = False

    return ok, diagnostics
