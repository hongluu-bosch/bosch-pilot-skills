#!/usr/bin/env python3
"""CLI: legacy ``FSCS_*.txt`` -> ``outputs/fscs/fscs.json``.

Intended as a one-shot migration tool for projects that predate the
FSCS data source governance upgrade. Point it at the two legacy
plaintext files; get back a validated ``fscs.json`` that the rest of
the pipeline can ingest natively.

Example
-------

::

    python scripts/fscs_import.py \\
        --fscs-22 outputs/fscs/FSCS_22.txt \\
        --fscs-2e outputs/fscs/FSCS_2E.txt \\
        --output   outputs/fscs/fscs.json

If you only have one of the two text files, pass whichever is
available; the CLI treats the missing service as ``supported=False``
for the affected DIDs.

The importer is deliberately lossy on structural details that the
``.txt`` format cannot represent unambiguously (sub_fields table, CJK
names, enum keys+descriptions together). Callers that need the full
fidelity should regenerate ``fscs.json`` from the original
``inputs/*.json`` via ``generate_fscs.py`` instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_encoding import reconfigure_stdio_utf8  # noqa: E402
from fscs import FSCSProject, import_fscs_txt, save_fscs_json  # noqa: E402

reconfigure_stdio_utf8()


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import legacy FSCS_*.txt files into fscs.json"
    )
    parser.add_argument(
        "--fscs-22", type=Path, default=None,
        help="Path to FSCS_22.txt (Service 22 - Read)",
    )
    parser.add_argument(
        "--fscs-2e", type=Path, default=None,
        help="Path to FSCS_2E.txt (Service 2E - Write)",
    )
    parser.add_argument(
        "--output", "-o", type=Path, required=True,
        help="Where to write the generated fscs.json",
    )
    parser.add_argument(
        "--customer-name", default=None,
        help="Optional project metadata to embed under project.customer_name",
    )
    parser.add_argument(
        "--product-type", default=None,
        help="When set, freshly-imported DIDs that don't already "
             "carry a per-DID product_type are auto-stamped with "
             "this value so the migrated fscs.json passes the "
             "Phase 2 build-target filter without manual CSV "
             "editing. v1.16.0 dropped the global "
             "project.product_type field, so this flag no longer "
             "lands in project metadata — it only fills the "
             "per-DID column. Single-product workflows pass "
             "--product-type DPB / ESP / ESPCL / IPB / RBU here.",
    )
    return parser


def main(argv=None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)

    if not args.fscs_22 and not args.fscs_2e:
        parser.error("at least one of --fscs-22 / --fscs-2e must be provided")

    for label, path in (("--fscs-22", args.fscs_22), ("--fscs-2e", args.fscs_2e)):
        if path is not None and not path.is_file():
            parser.error(f"{label} points at a non-existent file: {path}")

    # v1.16.0 (schema 1.5): FSCSProject no longer carries
    # product_type. ``--product-type`` migrated to a per-DID stamp
    # applied below via apply_product_type_defaults.
    project = FSCSProject(
        customer_name=args.customer_name,
    )

    document = import_fscs_txt(
        fscs_22_path=args.fscs_22,
        fscs_2e_path=args.fscs_2e,
        project=project,
    )

    if args.product_type:
        from fscs import apply_product_type_defaults
        apply_product_type_defaults(
            document, default_product_type=args.product_type,
        )

    save_fscs_json(document, args.output)
    print(f"Wrote {args.output} with {len(document.dids)} DID(s).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
