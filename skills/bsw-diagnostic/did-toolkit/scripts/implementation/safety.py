"""Safety layer: dry-run-aware writes.

Phase 2 / Phase 3 are non-destructive: existing project-tree files /
containers / macros are never overwritten — they are skip-on-conflict,
with the skip events surfaced in ``generation_report.txt``. There is
no rolling-backup machinery; the pre-existing file IS the backup.

:func:`guarded_project_write` is a thin ``--dry-run`` guard so the
safety-by-default posture is impossible to forget at each call site.
"""

from __future__ import annotations

from pathlib import Path


def guarded_project_write(path: Path, content: str,
                          dry_run: bool, action: str) -> bool:
    """Write ``content`` to a project-tree file, honoring ``dry_run``.

    Returns True if the write actually happened. In dry-run mode prints
    ``[DRY-RUN] Would <action>`` with path + byte count and no file
    system side effect.
    """
    if dry_run:
        print(f"[DRY-RUN] Would {action}: {path} ({len(content)} B)")
        return False
    path.write_text(content, encoding='utf-8')
    return True
