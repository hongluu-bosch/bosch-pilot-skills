"""diagcomm-toolkit preflight — run once after cloning the skill, plus
any time after an ``--init-project`` to verify the workspace.

v2.0.0 split: the preflight is now two-stage by design.

* SKILL stage  -- always runs. Verifies the skill checkout itself
  (Python version, importable deps, bundled assets all on disk).
* WORKSPACE stage -- only runs when a ``.DCOM_AI/DiagComm_Toolkit_PRJ/``
  workspace is reachable from the current cwd. Verifies
  ``inputs/DiagComm.xlsx`` exists, parses, and has the three data
  sheets; soft-checks the default ``base_dir`` resolves to a project
  tree.

The script makes no network calls, installs nothing, and writes
nothing. It only prints.

Exit codes: ``0`` = ready, ``1`` = at least one hard skill check
failed; ``2`` = skill is fine but no workspace exists yet (user needs
to run ``--init-project``).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent

WORKSPACE_NAME = "DiagComm_Toolkit_PRJ"
DCOM_AI_DIRNAME = ".DCOM_AI"
WORKSPACE_ROOT = (Path.cwd() / DCOM_AI_DIRNAME / WORKSPACE_NAME).resolve()

# Files we must see in the cloned tree. If any are missing the clone is
# broken (someone deleted half the repo, or got cut off mid-clone).
REQUIRED_SKILL_FILES = (
    "SKILL.md",
    "README.md",
    "VERSION",
    "assets/DiagComm.txt",
    "assets/DiagComm_schema.json",
    "assets/doors_template.xlsx",
    "assets/inputs_template.xlsx",
    "assets/doors_mapping_skeleton.yaml",
    "scripts/context.py",
    "scripts/pipeline.py",
    "scripts/excel_loader.py",
    "scripts/mapping.yaml",
    "scripts/requirements.txt",
)

# Default ``paths.dcom_root`` glob (kept in sync with DEFAULT_PATHS in
# scripts/runtime.py). If this glob resolves to at least one directory
# under the default ``base_dir``, the canonical install layout is
# correct and ``status`` will work without any user edits.
DEFAULT_DCOM_GLOB = "*/rb/as/*/core/app/dcom"


def _row(status: str, label: str, detail: str = "") -> None:
    """Print a single check row. ``status`` ∈ {OK, ok, WARN, FAIL}."""
    tag = f"[{status}]".ljust(7)
    line = f"{tag} {label}"
    if detail:
        line = f"{line}  -- {detail}"
    print(line)


def _check_python() -> bool:
    v = sys.version_info
    label = f"Python {v.major}.{v.minor}.{v.micro}"
    if v >= (3, 12):
        _row("OK", label)
        return True
    _row("FAIL", label, "need >= 3.12")
    return False


def _check_module(import_name: str, install_name: str, *, optional: bool = False) -> bool:
    found = importlib.util.find_spec(import_name) is not None
    if found:
        _row("ok" if optional else "OK", f"{install_name} importable")
        return True
    if optional:
        _row("ok", f"{install_name} not found (optional)")
        return True
    req = (SKILL_ROOT / "scripts" / "requirements.txt").as_posix()
    _row("FAIL", f"{install_name} not found",
         f"run: python -m pip install -r {req}")
    return False


def _check_skill_files() -> bool:
    missing = [rel for rel in REQUIRED_SKILL_FILES
               if not (SKILL_ROOT / rel).is_file()]
    if not missing:
        _row("OK",
             f"skill files present ({len(REQUIRED_SKILL_FILES)}/{len(REQUIRED_SKILL_FILES)})")
        return True
    _row("FAIL", "skill files missing",
         ", ".join(missing) + " -- re-clone the repo")
    return False


def _check_user_xlsx() -> bool:
    """Verify ``<workspace>/inputs/DiagComm.xlsx`` exists and parses cleanly."""
    xlsx = WORKSPACE_ROOT / "inputs" / "DiagComm.xlsx"
    template = SKILL_ROOT / "assets" / "inputs_template.xlsx"
    rel_xlsx = xlsx.relative_to(Path.cwd().resolve()) \
        if xlsx.is_relative_to(Path.cwd().resolve()) else xlsx

    if not xlsx.is_file():
        _row("FAIL", f"{rel_xlsx} missing",
             "recover by running --init-project (or copy the template manually)")
        return False

    if not template.is_file():
        _row("WARN", "assets/inputs_template.xlsx missing (skill tree incomplete)")

    try:
        import openpyxl  # type: ignore[import-not-found]
    except ImportError:
        req = (SKILL_ROOT / "scripts" / "requirements.txt").as_posix()
        _row("WARN", f"{rel_xlsx} present but openpyxl missing",
             f"install with: python -m pip install -r {req}")
        return True
    try:
        wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        _row("FAIL", f"{rel_xlsx} cannot be opened: {exc}",
             "re-run --init-project --force to restore the template")
        return False
    expected = {"Project & Parameters", "Paths & Options", "DOORS Upload"}
    missing = expected - set(wb.sheetnames)
    wb.close()
    if missing:
        _row("FAIL",
             f"{rel_xlsx} is missing sheet(s): {sorted(missing)}",
             "re-run --init-project --force to restore the template")
        return False
    _row("OK", f"{rel_xlsx} parses cleanly", "3 data sheets present")
    return True


def _check_base_dir() -> bool:
    """Soft check: does the workspace's default ``base_dir = ../..``
    actually contain a CusDiag tree at the default ``dcom_root`` glob?
    If yes, the user cd'd into the right project. If no, just warn -- the
    user might have a custom layout and edit ``paths.base_dir`` later."""
    base = (WORKSPACE_ROOT / ".." / "..").resolve()
    if not base.is_dir():
        _row("WARN", f"default base_dir does not exist: {base}",
             "edit paths.base_dir on Sheet 'Paths & Options' in inputs/DiagComm.xlsx")
        return True

    try:
        matches = list(base.glob(DEFAULT_DCOM_GLOB))
    except (PermissionError, OSError) as exc:
        _row("WARN", f"default base_dir not searchable: {base}", repr(exc))
        return True

    if matches:
        rel = matches[0].relative_to(base)
        _row("OK", f"default layout resolves a CusDiag tree at {base}",
             f"dcom_root -> {rel}")
        return True
    _row("WARN", f"no CusDiag tree under default base_dir: {base}",
         "either cd to the right project root or edit paths.base_dir / "
         "paths.dcom_root on Sheet 'Paths & Options' in inputs/DiagComm.xlsx")
    return True


def _check_schema_drift() -> bool:
    """Run the same drift check the CI uses, but inline (no subprocess
    so we keep going if pipeline.py would shell out elsewhere)."""
    try:
        sys.path.insert(0, str(SKILL_ROOT / "scripts"))
        import schema as schema_mod  # type: ignore[import-not-found]
    except Exception as exc:
        _row("WARN", "could not import scripts/schema.py", repr(exc))
        return True

    try:
        in_sync, _ = _build_schema_drift(schema_mod)
    except Exception as exc:
        _row("WARN", "schema drift check raised", repr(exc))
        return True

    if in_sync:
        _row("OK", "DiagComm_schema.json in sync with DiagComm.txt")
        return True
    _row("WARN", "DiagComm_schema.json drifted from DiagComm.txt",
         f"run: python {SKILL_ROOT / 'scripts' / 'pipeline.py'} gen-schema")
    return True


def _build_schema_drift(schema_mod) -> tuple[bool, str]:
    """Tiny re-implementation of pipeline._build_schema_drift to avoid
    pulling in pipeline.py's heavier import chain (lxml, runtime, etc.)
    just for a stdlib drift check.
    """
    import json
    txt = SKILL_ROOT / "assets" / "DiagComm.txt"
    out = SKILL_ROOT / "assets" / "DiagComm_schema.json"
    fresh = schema_mod.build_schema(txt_path=txt)
    on_disk = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return (fresh == on_disk, "")


def main() -> int:
    print(f"diagcomm-toolkit preflight")
    print(f"  skill     : {SKILL_ROOT}")
    print(f"  workspace : {WORKSPACE_ROOT}"
          f" {'(missing)' if not WORKSPACE_ROOT.exists() else ''}")
    print("-" * 60)

    print("[skill]")
    skill_checks = [
        _check_python(),
        _check_module("lxml", "lxml"),
        _check_module("yaml", "PyYAML"),
        _check_module("openpyxl", "openpyxl"),
        _check_skill_files(),
    ]
    _check_module("pytest", "pytest", optional=True)
    _check_schema_drift()

    pipeline_py = (SKILL_ROOT / "scripts" / "pipeline.py").as_posix()

    print("\n[workspace]")
    if not WORKSPACE_ROOT.exists():
        _row("FAIL", "no workspace at .DCOM_AI/DiagComm_Toolkit_PRJ/",
             f"scaffold with: python {pipeline_py} --init-project")
        print("-" * 60)
        if all(skill_checks):
            print("Skill is ready, but no workspace yet. cd to your project root and run:")
            print(f"  python {pipeline_py} --init-project")
            return 2
        print("Status: NOT READY. Fix the [FAIL] rows above and re-run preflight.")
        return 1

    workspace_checks = [
        _check_user_xlsx(),
    ]
    _check_base_dir()

    print("-" * 60)
    if all(skill_checks) and all(workspace_checks):
        print("Status: READY. Next:")
        print(f"  python {pipeline_py} status")
        return 0
    print("Status: NOT READY. Fix the [FAIL] rows above and re-run preflight.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
