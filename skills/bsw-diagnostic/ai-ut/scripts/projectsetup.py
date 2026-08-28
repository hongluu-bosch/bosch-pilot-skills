#!/usr/bin/env python3
"""Phase 0: create Cantata++/Cook-san test tree for a SUT .c (or skip if already present)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_COOK_SAN_PATH = r"C:\TCC\Tools\cook_san\v2.0.0_WIN64"
SUT_OUTSIDE_WORKSPACE_ERROR = "SUT_OUTSIDE_WORKSPACE"
SUT_OUTSIDE_WORKSPACE_MESSAGE = (
    "ERROR: The provided .c file is outside the current workspace boundary.\n"
    "This task has been stopped."
)


def detect_workspace_root() -> Path:
    script_path = Path(__file__).resolve()
    for candidate in script_path.parents:
        if (candidate / ".agents").exists():
            return candidate
    raise ValueError(
        "Unable to auto-detect workspace root from script location; pass --workspace-root explicitly."
    )


def resolve_workspace_root(raw_workspace_root: str | None) -> Path:
    workspace_root = Path(raw_workspace_root).resolve() if raw_workspace_root else detect_workspace_root()
    if not workspace_root.exists():
        raise ValueError(f"Workspace root not found: {workspace_root}")
    if not workspace_root.is_dir():
        raise ValueError(f"Workspace root is not a directory: {workspace_root}")
    return workspace_root


def validate_sut_path(raw_sut_path: str, workspace_root: Path) -> Path:
    sut = Path(raw_sut_path).resolve()
    if not sut.exists():
        raise ValueError(f"SUT not found: {sut}")
    if not sut.is_file():
        raise ValueError(f"SUT is not a file: {sut}")
    if sut.suffix.lower() != ".c":
        raise ValueError(f"SUT must be a .c file: {sut}")

    try:
        sut.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(
            f"{SUT_OUTSIDE_WORKSPACE_ERROR}: SUT must stay inside workspace root {workspace_root}: {sut}"
        ) from exc

    return sut


def test_project_ready(sut: Path) -> tuple[bool, Path]:
    name = sut.stem
    test_dir = sut.parent / f"test_{name}"
    need = (
        test_dir / f"test_{name}.h",
        test_dir / f"test_{name}.cpp",
        test_dir / "work" / "cantata_coverage.bat",
    )
    return test_dir.exists() and all(p.exists() for p in need), test_dir


def print_run_hint(test_dir: Path) -> None:
    work = test_dir / "work"
    print(f'Next: cd "{work}" && .\\cantata_coverage.bat')


def terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        proc.terminate()


def stream_output(pipe) -> None:
    if pipe is None:
        return

    for line in pipe:
        print(line, end="")


def format_command(command: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(command)
    return " ".join(command)


def snapshot_tree(root: Path) -> list[str]:
    if not root.exists():
        return []

    snapshot: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        snapshot.append(f"{rel}/" if path.is_dir() else rel)
    return snapshot


def write_reinit_audit(
    sut: Path,
    workspace_root: Path,
    test_dir: Path,
    command: list[str],
    before_snapshot: list[str],
    after_snapshot: list[str],
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = sut.parent / f".projectsetup-reinit-{sut.stem}-{timestamp}.json"
    before_set = set(before_snapshot)
    after_set = set(after_snapshot)
    payload = {
        "timestamp_utc": timestamp,
        "workspace_root": str(workspace_root),
        "sut": str(sut),
        "test_project": str(test_dir),
        "command": command,
        "before_snapshot": before_snapshot,
        "after_snapshot": after_snapshot,
        "added_entries": sorted(after_set - before_set),
        "removed_entries": sorted(before_set - after_set),
    }
    log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return log_path


def main() -> int:
    p = argparse.ArgumentParser(description="UT Phase 0: init or verify test_<SUT>.")
    p.add_argument("sut_file", help="Path to SUT .c")
    p.add_argument("--cook-san-path", default=DEFAULT_COOK_SAN_PATH)
    p.add_argument(
        "--workspace-root",
        help="Workspace root containing the SUT; defaults to the auto-detected directory that contains .agents",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Allow re-running setup, but existing test_<SUT> directories still require an explicit reinit acknowledgement",
    )
    p.add_argument(
        "--allow-existing-test-project-reinit",
        action="store_true",
        help="Acknowledge that re-running Cook-san against an existing test_<SUT> directory may overwrite or rebuild files",
    )
    p.add_argument("--timeout", type=int, default=180, help="Max seconds to wait for setup")
    p.add_argument(
        "--ready-grace-period",
        type=int,
        default=10,
        help="Extra seconds to wait after test tree is ready before stopping trailing processes",
    )
    args = p.parse_args()

    if args.allow_existing_test_project_reinit and not args.force:
        print("ERROR: --allow-existing-test-project-reinit requires --force")
        return 1

    try:
        workspace_root = resolve_workspace_root(args.workspace_root)
        sut = validate_sut_path(args.sut_file, workspace_root)
    except ValueError as exc:
        message = str(exc)
        if message.startswith(f"{SUT_OUTSIDE_WORKSPACE_ERROR}:"):
            print(SUT_OUTSIDE_WORKSPACE_ERROR)
            print(SUT_OUTSIDE_WORKSPACE_MESSAGE)
        else:
            print(f"ERROR: {message}")
        return 1

    setup_bat = (Path(args.cook_san_path).resolve() / "setup_project.bat")
    ok, test_dir = test_project_ready(sut)
    if ok and not args.force:
        print(f"[OK] Test project exists: {test_dir}")
        print_run_hint(test_dir)
        return 0

    if test_dir.exists() and not args.force:
        print(f"ERROR: Existing test project directory detected: {test_dir}")
        print(
            "Refusing to modify an existing test project automatically. Back up or remove it first, "
            "or rerun with both --force and --allow-existing-test-project-reinit."
        )
        return 1

    if not setup_bat.exists():
        print(f"ERROR: Missing {setup_bat} (set --cook-san-path)")
        return 1

    before_snapshot: list[str] | None = None
    if test_dir.exists() and args.force:
        if not args.allow_existing_test_project_reinit:
            print(
                "ERROR: Existing test project detected. "
                "Pass --allow-existing-test-project-reinit together with --force only after backup/review."
            )
            return 1

        before_snapshot = snapshot_tree(test_dir)
        print("[!] --force: re-running setup against an existing test project")
        print("[!] Existing test project changes will be audited to a sibling JSON log.")

    cmd = ["cmd.exe", "/d", "/c", "call", str(setup_bat), str(sut)]
    print(f"Running: {format_command(cmd)}")
    proc = subprocess.Popen(
        cmd,
        cwd=str(sut.parent),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    if proc.stdin is not None:
        try:
            proc.stdin.write("\n")
            proc.stdin.close()
        except OSError:
            pass
    output_thread = threading.Thread(target=stream_output, args=(proc.stdout,), daemon=True)
    output_thread.start()

    start_time = time.monotonic()
    ready_since: float | None = None

    while True:
        return_code = proc.poll()
        ok_now, _ = test_project_ready(sut)

        if ok_now:
            if return_code is not None:
                break
            if ready_since is None:
                ready_since = time.monotonic()
                print("[INFO] Test project detected; waiting briefly for setup to finish.")
            elif time.monotonic() - ready_since >= args.ready_grace_period:
                print("[WARN] Test project is ready but setup is still running; stopping trailing process.")
                terminate_process_tree(proc)
                break

        if return_code is not None:
            break

        if time.monotonic() - start_time >= args.timeout:
            print(f"ERROR: setup timed out after {args.timeout}s")
            terminate_process_tree(proc)
            break

        time.sleep(1.0)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        terminate_process_tree(proc)
        proc.wait(timeout=5)

    output_thread.join(timeout=5)

    if before_snapshot is not None:
        after_snapshot = snapshot_tree(test_dir)
        try:
            audit_log = write_reinit_audit(
                sut=sut,
                workspace_root=workspace_root,
                test_dir=test_dir,
                command=cmd,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
            print(f"[INFO] Reinit audit written: {audit_log}")
        except OSError as exc:
            print(f"[WARN] Failed to write reinit audit log: {exc}")

    ok_after, _ = test_project_ready(sut)
    if ok_after:
        print(f"[OK] Test project: {test_dir}")
        print_run_hint(test_dir)
        return 0

    print("[FAIL] Expected test_* layout not found after setup.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
