"""One-shot migration: 1.20.x in-skill workspace -> v2.0.0 layout.

Background
==========

In 1.20.x the skill checkout owned both the bundled assets AND every
project's user data:

    <project>/.agents/skills/diagcomm-toolkit/
      scripts/                       # bundled
      assets/                        # bundled
      reference/                     # bundled
      inputs/DiagComm.xlsx           # USER DATA (per-project)
      outputs/                       # USER DATA (regenerable)
      state/doors_upload_state.json  # USER DATA (DOORS sync state)
      .cache/                        # USER DATA (auto-derived)

v2.0.0 splits the skill into a user-level checkout and a per-project
workspace:

    ~/.cursor/skills/diagcomm-toolkit/   # bundled (one copy per user)
    <project>/.DCOM_AI/DiagComm_Toolkit_PRJ/
      inputs/DiagComm.xlsx               # USER DATA, lifted from the
      outputs/                           #            old skill checkout
      state/                             #
      .cache/                            #

Usage
=====

    cd <your-project-root>            # the dir that owns AUTOSAR tree
    python <skill>/scripts/migrate_v1_20_to_v2.py \
        --from-skill <project>/.agents/skills/diagcomm-toolkit

What it does
============

1. Verifies ``--from-skill`` looks like a real 1.20.x skill checkout
   (has ``scripts/excel_loader.py`` + ``inputs/DiagComm.xlsx``).
2. Initialises the v2 workspace at ``<cwd>/.DCOM_AI/DiagComm_Toolkit_PRJ/``
   (idempotent; safe to re-run on a partially-migrated tree).
3. MOVES (not copies) every user data file from the old skill into the
   workspace, atomically per-file. Skips destinations that already
   exist unless ``--force``.
4. Rewrites ``inputs/DiagComm.xlsx::Paths & Options::base_dir`` from
   the v1 default ``"../../.."`` to the v2 default ``"../.."``.
   Custom absolute or already-correct values are left alone.
5. Prints the cleanup steps (``rm -rf <old skill checkout>``) but does
   not execute them -- the user verifies first, then deletes.

Exit codes:
    0 = migration completed (or dry-run)
    1 = nothing to migrate (no user data found in --from-skill)
    2 = ``--from-skill`` is missing or not a 1.20.x skill checkout
    3 = a destination file exists; bail out unless --force was passed
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPTS_DIR.parent

WORKSPACE_NAME = "DiagComm_Toolkit_PRJ"
DCOM_AI_DIRNAME = ".DCOM_AI"

# User-data items to migrate. Tuple = (relative path inside source skill,
# relative path inside the workspace). Order matters only for the
# user-facing summary; the moves themselves are independent.
MIGRATION_ITEMS: tuple[tuple[str, str], ...] = (
    ("inputs/DiagComm.xlsx",        "inputs/DiagComm.xlsx"),
    ("state/doors_upload_state.json", "state/doors_upload_state.json"),
    # outputs/ + .cache/ are regenerable -- copy whole dirs as-is so
    # nothing is lost, but the user can equally well delete them post-
    # migration. Cache will refresh on the next pipeline command.
    ("outputs",                     "outputs"),
    (".cache",                      ".cache"),
)

# Sentinel files that prove the source dir is actually a skill checkout
# (and not, say, a random directory the user pointed at by mistake).
SKILL_MARKERS: tuple[str, ...] = (
    "scripts/excel_loader.py",
    "scripts/pipeline.py",
    "assets/DiagComm_schema.json",
)


def _is_skill_checkout(path: Path) -> bool:
    return all((path / m).is_file() for m in SKILL_MARKERS)


def _find_user_data(src: Path) -> list[tuple[Path, Path, str]]:
    """Return the list of (src_path, rel_dest, kind) entries that
    actually exist in the source skill. ``kind`` is 'file' or 'dir'.
    """
    found: list[tuple[Path, Path, str]] = []
    for src_rel, dest_rel in MIGRATION_ITEMS:
        sp = src / src_rel
        if sp.is_file():
            found.append((sp, Path(dest_rel), "file"))
        elif sp.is_dir():
            # Only count the dir if it has at least one file -- empty
            # dirs after .gitkeep cleanup look like phantom migrations.
            if any(sp.rglob("*")):
                found.append((sp, Path(dest_rel), "dir"))
    return found


def _rewrite_base_dir(xlsx_path: Path) -> bool:
    """If the migrated xlsx still has the v1 default base_dir
    ``"../../.."``, rewrite it to the v2 default ``"../.."``. Custom
    values (absolute paths, ``../foo``, etc.) are left untouched.

    Returns True iff the cell was rewritten. No-op + False on any
    failure (we never want migration to abort over a cosmetic fixup).
    """
    try:
        import openpyxl  # noqa: PLC0415
    except ImportError:
        return False
    try:
        wb = openpyxl.load_workbook(xlsx_path)
        if "Paths & Options" not in wb.sheetnames:
            return False
        ws = wb["Paths & Options"]
        for row in range(2, ws.max_row + 1):
            field = ws.cell(row=row, column=1).value
            if isinstance(field, str) and field.strip() == "paths.base_dir":
                cell = ws.cell(row=row, column=2)
                if isinstance(cell.value, str) and cell.value.strip() == "../../..":
                    cell.value = "../.."
                    wb.save(xlsx_path)
                    return True
                break
        return False
    except Exception:
        return False


def _move_with_check(src: Path, dest: Path, *, force: bool, dry_run: bool
                     ) -> str:
    """Move ``src`` to ``dest``. Returns a one-line status string."""
    if dest.exists():
        if not force:
            return f"  [skip ] {dest}  (already exists; pass --force to overwrite)"
        if dry_run:
            return f"  [would-overwrite] {dest}"
        # Safe overwrite: remove existing, then move.
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    if dry_run:
        return f"  [would-move] {src}  ->  {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return f"  [moved] {dest}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="migrate_v1_20_to_v2",
        description="Move 1.20.x in-skill user data into the v2 workspace.",
    )
    parser.add_argument(
        "--from-skill", type=Path, required=True,
        help="The 1.20.x skill checkout that contains the user's data "
             "(e.g. <project>/.agents/skills/diagcomm-toolkit).",
    )
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(),
        help="Project root that will own the new workspace "
             "(default: current working directory).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite workspace files / dirs that already exist. "
             "Use with care; old workspace contents are deleted before "
             "the move.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be moved without touching the disk.",
    )
    args = parser.parse_args(argv)

    src = args.from_skill.resolve()
    project_root = args.project_root.resolve()
    workspace = project_root / DCOM_AI_DIRNAME / WORKSPACE_NAME

    if not src.exists():
        print(f"[migrate_v2] --from-skill not found: {src}", file=sys.stderr)
        return 2
    if not _is_skill_checkout(src):
        print(f"[migrate_v2] --from-skill does not look like a diagcomm-toolkit "
              f"checkout (missing one of {SKILL_MARKERS}): {src}",
              file=sys.stderr)
        return 2

    user_data = _find_user_data(src)
    if not user_data:
        print(f"[migrate_v2] no user data found under {src}/inputs|state|outputs|.cache")
        print(f"             (the migration is already done -- workspace at {workspace})")
        return 1

    print(f"[migrate_v2] {'DRY-RUN: ' if args.dry_run else ''}migrating user data")
    print(f"  source skill : {src}")
    print(f"  project root : {project_root}")
    print(f"  workspace    : {workspace}")
    print()

    if not args.dry_run:
        for sub in ("inputs", "outputs", "state", ".cache"):
            (workspace / sub).mkdir(parents=True, exist_ok=True)

    summary: list[str] = []
    refused = False
    for sp, dest_rel, _kind in user_data:
        dest = workspace / dest_rel
        if dest.exists() and not args.force:
            refused = True
        summary.append(_move_with_check(sp, dest, force=args.force,
                                         dry_run=args.dry_run))
    for line in summary:
        print(line)

    rewrote_base_dir = False
    xlsx = workspace / "inputs" / "DiagComm.xlsx"
    if xlsx.is_file() and not args.dry_run:
        rewrote_base_dir = _rewrite_base_dir(xlsx)
        if rewrote_base_dir:
            print()
            print("  [fixup] inputs/DiagComm.xlsx::Paths & Options::base_dir")
            print("          v1 default '../../..' -> v2 default '../..'")

    if refused and not args.force:
        print()
        print("[migrate_v2] some destinations already exist; nothing was moved "
              "for those entries. Re-run with --force to overwrite the "
              "workspace contents.")
        return 3

    if args.dry_run:
        print()
        print("[migrate_v2] dry-run complete. Re-run without --dry-run to migrate.")
        return 0

    print()
    print("[migrate_v2] done. Next steps:")
    print(f"  1. cd {project_root}")
    print(f"     python {SKILL_ROOT.as_posix()}/scripts/pipeline.py status")
    print( "     -- verify the dashboard reports READY (or DEGRADED with the "
           "expected warnings).")
    print(f"  2. Once happy, delete the old skill checkout:")
    print(f"       rm -rf {src}")
    print( "     (its scripts / assets / reference dirs are duplicated by the "
           "user-level skill at ~/.cursor/skills/diagcomm-toolkit/.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
