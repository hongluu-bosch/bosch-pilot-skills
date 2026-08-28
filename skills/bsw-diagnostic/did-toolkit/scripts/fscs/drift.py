"""Detect drift between ``outputs/fscs/fscs.json`` and ``FSCS_*.txt``.

Why this exists
---------------

With the Step-3 migration ``fscs.json`` is authoritative: every
consumer (ARXML, implementation, reviewer, xlsx edit) reads JSON and the
plaintext FSCS files are downgraded to human-review / future-Excel
artifacts. Nothing in that contract *prevents* someone from
hand-editing ``FSCS_22.txt`` or ``FSCS_2E.txt`` though, and a stale
text file in the repo is confusing: reviewers might diff it and
assume the JSON is wrong.

This module renders the JSON to in-memory text via
:mod:`scripts.fscs.renderer` and compares against the file(s) on
disk. When they disagree we emit a ``WARN`` on ``stderr`` (never an
error -- drift is a data governance hint, not a pipeline failure)
and return ``False`` from :func:`check_fscs_drift` so callers can
surface the warning in their own way if they wish.

The public API is deliberately tiny:

* :func:`check_fscs_drift` -- programmatic entry point returning a
  :class:`DriftReport`. Also emits the WARN line (once per file) when
  drift is present so casual invocations don't need to care about the
  return value.
* :func:`main` -- CLI wrapper used by ``scripts/pipeline.py`` and by
  anyone running ``python -m scripts.fscs.drift``. Always exits ``0``;
  the WARN goes to stderr.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .loader import load_fscs_json
from .renderer import render_fscs_22_txt, render_fscs_2e_txt
from .schema import FSCSDocument


@dataclass
class DriftReport:
    """Outcome of a drift check over the ``outputs/fscs/`` directory."""

    json_path: Path
    checked: List[Path] = field(default_factory=list)
    drifted: List[Path] = field(default_factory=list)
    missing: List[Path] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.drifted) or bool(self.missing)


def check_fscs_drift(
    outputs_dir: Path,
    *,
    stream=None,
    emit_warning: bool = True,
) -> DriftReport:
    """Compare ``fscs.json`` in ``outputs_dir/fscs/`` against the two .txt files.

    Parameters
    ----------
    outputs_dir:
        Project outputs directory (``outputs/`` by convention). The
        FSCS triplet is expected under ``<outputs_dir>/fscs/``.
    stream:
        File-like used for the ``WARN`` output. Defaults to
        ``sys.stderr``. Tests pass :class:`io.StringIO` to capture.
    emit_warning:
        When ``False``, the report is returned without writing a warning
        line. Useful for tooling that wants to format its own message.

    Returns
    -------
    DriftReport
        Populated with the paths that drifted or were missing. If
        ``fscs.json`` itself is missing the report is empty (no JSON to
        compare *against*) and ``has_drift`` is ``False``.
    """
    stream = stream if stream is not None else sys.stderr
    fscs_dir = outputs_dir / "fscs"
    json_path = fscs_dir / "fscs.json"

    report = DriftReport(json_path=json_path)

    if not json_path.is_file():
        # No JSON means nothing to drift-check against; legacy-only
        # projects haven't migrated yet and that's fine. drift.py is
        # strictly a consistency guard, never a coverage enforcer.
        return report

    document = load_fscs_json(json_path)
    checks = [
        (fscs_dir / "FSCS_22.txt", render_fscs_22_txt(document)),
        (fscs_dir / "FSCS_2E.txt", render_fscs_2e_txt(document)),
    ]

    for path, expected in checks:
        report.checked.append(path)
        if not path.is_file():
            report.missing.append(path)
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            report.drifted.append(path)

    if emit_warning and report.has_drift:
        _emit_warning(report, document, stream)

    return report


def _emit_warning(report: DriftReport, document: FSCSDocument, stream) -> None:
    """Write a single multi-line ``WARN`` block describing the drift.

    The message is purposefully actionable: we tell the user exactly
    which files diverged and how to realign them. Grouping everything
    into one block keeps logs readable when the pipeline runs under
    CI.
    """
    lines: List[str] = []
    lines.append(
        "WARN [fscs.drift] outputs/fscs/*.txt are out of sync with fscs.json."
    )
    lines.append(f"       source of truth : {report.json_path}")
    lines.append(
        f"       generated_at     : {document.generated_at} "
        f"(generator: {document.generator.tool})"
    )
    for path in report.drifted:
        lines.append(f"       drift            : {path}")
    for path in report.missing:
        lines.append(f"       missing          : {path}")
    lines.append(
        "       remediation      : re-run `python scripts/generate_fscs.py` "
        "to rebuild the .txt files from fscs.json."
    )
    stream.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check that outputs/fscs/FSCS_22.txt and FSCS_2E.txt are "
            "consistent with the authoritative outputs/fscs/fscs.json."
        ),
    )
    parser.add_argument(
        "--outputs",
        type=Path,
        default=Path("outputs"),
        help="Project outputs directory (defaults to ./outputs).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point; always returns ``0`` so the pipeline never aborts."""
    args = _build_parser().parse_args(argv)
    check_fscs_drift(args.outputs.resolve())
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI glue
    raise SystemExit(main())
