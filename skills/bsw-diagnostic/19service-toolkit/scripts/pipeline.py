"""Main entry point for 19service-toolkit."""

import argparse
import pathlib
import sys

import version
from init_project import run_init
from project_root import resolve_project_root


def main(argv=None):
    parser = argparse.ArgumentParser(prog="19service-toolkit")
    parser.add_argument("--version", action="store_true", help="Print version")
    parser.add_argument("--validate", action="store_true", help="Validate config and inputs")
    parser.add_argument("--init-project", action="store_true", help="Scaffold workspace")
    parser.add_argument("--name", help="Project name")
    parser.add_argument("--customer-name", help="Customer folder name under rb/as/")
    parser.add_argument("--project-root-name", help="Project root folder name")
    parser.add_argument(
        "--product-types",
        help="Comma-separated product types (e.g. Common,RBU,IPB). "
             "MUST be supplied explicitly by the human operator via their prompt; "
             "the agent must never infer or default this value."
    )
    parser.add_argument("--input", help="Input basename for questionnaire")
    parser.add_argument("--force", action="store_true", help="Force re-init (dangerous)")
    parser.add_argument("--phase", choices=["fscs", "xlsx-import", "arxml", "c", "doors"], help="Run a phase")
    parser.add_argument("--user-nt", help="DOORS user NT account")
    parser.add_argument("--password", help="DOORS password (optional; prefer keyring or DOORS_PWD)")
    parser.add_argument("--save-credentials", action="store_true", help="Save the DOORS password to the OS keychain")
    parser.add_argument("--forget-credentials", action="store_true", help="Delete the cached DOORS password from the OS keychain")
    parser.add_argument("--no-fetch", action="store_true", help="Skip fetching the DOORS module export")
    parser.add_argument("--no-upload", action="store_true", help="Build DOORS file without uploading")
    parser.add_argument("--dry-run", action="store_true", help="Preview Phase 2 writes")

    args = parser.parse_args(argv)

    if args.version:
        print(f"19service-toolkit {version.get_version()}")
        return 0

    if args.validate:
        return _validate(args)

    if args.init_project:
        return run_init(args)

    if not args.phase:
        parser.error("--phase is required (unless using --init-project, --validate, or --version)")

    workspace = resolve_project_root()
    config_path = workspace / "config" / "project.json"
    if not config_path.exists():
        print(f"[ERROR] No workspace found at {workspace}. Run --init-project first.")
        return 1

    if args.phase == "fscs":
        from generate_fscs import run_phase1
        return run_phase1(workspace, args)

    if args.phase == "xlsx-import":
        from fscs_import import run_xlsx_import
        return run_xlsx_import(workspace, args)

    if args.phase == "arxml":
        from generate_arxml import run_phase2
        return run_phase2(workspace, args)

    if args.phase == "c":
        from generate_c import run_phase3
        return run_phase3(workspace, args)

    if args.phase == "doors":
        from fscs_doors_sync import run_phase4
        return run_phase4(workspace, args)

    return 0


def _validate(args) -> int:
    workspace = resolve_project_root()
    config_path = workspace / "config" / "project.json"
    if not config_path.exists():
        print(f"[ERROR] Missing {config_path}")
        return 1
    import json
    config = json.loads(config_path.read_text(encoding="utf-8"))
    required = {"name", "customer_name", "base_dir", "product_types", "paths"}
    missing = required - set(config.keys())
    if missing:
        print(f"[ERROR] config/project.json missing fields: {sorted(missing)}")
        return 1
    print("[OK] config/project.json is valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
