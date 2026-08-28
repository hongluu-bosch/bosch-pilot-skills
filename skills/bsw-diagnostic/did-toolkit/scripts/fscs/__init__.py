"""FSCS data model, I/O, and rendering.

FSCS used to be a text-only concern (the plaintext ``FSCS_22.txt`` /
``FSCS_2E.txt`` files were both the authoritative source and the
human-readable view). That caused three parser implementations to
drift (Phase 3 / Review / XLSX edit) and a latent "RAM + empty NVM" regex
bug that kept appearing.

This package consolidates FSCS into a single authoritative JSON
source with a text rendering on the side:

* :mod:`schema`   -- pydantic models (``FSCSDocument`` + children),
                     the contract downstream consumers rely on.
* :mod:`loader`   -- JSON read/write: ``load_fscs_json`` /
                     ``save_fscs_json``.
* :mod:`renderer` -- pure functions turning an ``FSCSDocument`` into
                     JSON bytes (``render_fscs_json``) or into the two
                     ``FSCS_*.txt`` human-readable files
                     (``render_fscs_22_txt`` / ``render_fscs_2e_txt``).
                     Kept as imperative Python -- FSCS's tab-aligned
                     layout and byte-offset state machine are clearer
                     as ``lines.append(...)`` than as Jinja2 with
                     whitespace-control tags.
* :mod:`importer` -- one-shot migration of legacy ``.txt`` pairs into
                     a populated ``FSCSDocument`` (Step 2).
* :mod:`drift`    -- compares the rendered ``.txt`` against what's on
                     disk and emits a report (Step 5).

Downstream code should only ever import from :mod:`scripts.fscs`
(this package's public surface) rather than poking at submodules.
"""

from .adapter import load_fscs, to_did_implementation_infos, to_review_dicts
from .builder import (
    FSCSBuildReport,
    FSCSBuildSkip,
    NVM_ID_PREFIX,
    apply_product_scope_defaults,  # legacy alias kept for v1.15 callers
    apply_product_type_defaults,
    build_fscs_document,
    build_fscs_document_with_report,
)
from .drift import DriftReport, check_fscs_drift
from .xlsx_edit import VALIDATIONS, XLSX_COLUMNS, export_fscs_xlsx, import_fscs_xlsx
from .importer import import_fscs_txt
from .loader import load_fscs_json, save_fscs_json
from .product_workset import (
    RECOGNISED_PRODUCTS,
    ProductWorkset,
    UnknownProductTypeError,
    compute_workset,
    phase2_alias_source_for,
    phase2_alias_target_for,
)
from .save import atomic_write, fscs_paths, save_all
from .renderer import (
    TXT_HEADER,
    render_fscs_22_txt,
    render_fscs_2e_txt,
    render_fscs_json,
)
from .schema import (
    DIDFscsEntry,
    FSCSDocument,
    FSCSFreeText,
    FSCSGeneratorMeta,
    FSCSProject,
    FSCSSecurityLevel,
    FSCSServiceAccess,
    FSCSSubField,
    FSCSValueRange,
    FSCSValueRangeComposite,
    FSCSValueRangeEnum,
    FSCSValueRangeNone,
    FSCSValueRangeNumeric,
    SCHEMA_VERSION,
    SubFieldDataType,
    SubFieldEncoding,
    normalize_did_hex,
    normalize_sub_field_data_type,
    normalize_sub_field_encoding,
)

__all__ = [
    # schema
    "DIDFscsEntry",
    "FSCSDocument",
    "FSCSFreeText",
    "FSCSGeneratorMeta",
    "FSCSProject",
    "FSCSSecurityLevel",
    "FSCSServiceAccess",
    "FSCSSubField",
    "FSCSValueRange",
    "FSCSValueRangeComposite",
    "FSCSValueRangeEnum",
    "FSCSValueRangeNone",
    "FSCSValueRangeNumeric",
    "SCHEMA_VERSION",
    "SubFieldDataType",
    "SubFieldEncoding",
    "normalize_did_hex",
    "normalize_sub_field_data_type",
    "normalize_sub_field_encoding",
    # adapter (consumer-side glue)
    "load_fscs",
    "to_did_implementation_infos",
    "to_review_dicts",
    # builder
    "FSCSBuildReport",
    "FSCSBuildSkip",
    "NVM_ID_PREFIX",
    "apply_product_scope_defaults",
    "apply_product_type_defaults",
    "build_fscs_document",
    "build_fscs_document_with_report",
    # drift
    "DriftReport",
    "check_fscs_drift",
    # xlsx_edit
    "VALIDATIONS",
    "XLSX_COLUMNS",
    "export_fscs_xlsx",
    "import_fscs_xlsx",
    # importer
    "import_fscs_txt",
    # product_workset
    "RECOGNISED_PRODUCTS",
    "ProductWorkset",
    "UnknownProductTypeError",
    "compute_workset",
    "phase2_alias_source_for",
    "phase2_alias_target_for",
    # loader
    "load_fscs_json",
    "save_fscs_json",
    "atomic_write",
    "fscs_paths",
    "save_all",
    # renderer
    "TXT_HEADER",
    "render_fscs_22_txt",
    "render_fscs_2e_txt",
    "render_fscs_json",
]
