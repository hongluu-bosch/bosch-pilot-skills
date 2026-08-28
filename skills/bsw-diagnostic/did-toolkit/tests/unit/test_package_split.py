"""Regression tests for the phase-7 split of ``generate_implementation.py``.

These tests pin the public contract so any future reorganisation inside
``scripts/implementation/`` is caught immediately:

* every symbol the legacy monolith exported is still importable from
  ``generate_implementation``;
* the same symbols are also importable from the new
  ``scripts.implementation`` package;
* the package re-exports are the *same objects* (not stale copies) as
  the shim module, so monkeypatching one site patches both.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import generate_implementation as legacy  # noqa: E402
import implementation as pkg  # noqa: E402


LEGACY_EXPORTS = [
    "DIDImplementationInfo",
    "DIDInput",
    "DIDSubField",
    "ImplementationGenerator",
    "clean_name",
    "capitalize_first",
    "get_fs_macro",
    "get_func_name",
    "get_nvm_id",
    "get_range_macro_name",
    "parse_enum_values",
    "parse_numeric_range",
    "product_type_lower",
    "resolve_path",
    "guarded_project_write",
    "generate_pdm_entry",
    "generate_config_macro",
    "generate_config_settings_macro",
    "generate_element_defs",
    "generate_range_macros",
    "generate_read_code",
    "generate_write_code",
    "generate_enum_conditions",
    "FS_MACRO_PREFIX",
    "NVM_ID_PREFIX",
]


def test_legacy_exports_all_present():
    missing = [name for name in LEGACY_EXPORTS if not hasattr(legacy, name)]
    assert not missing, f"generate_implementation is missing: {missing}"


def test_package_exports_all_present():
    missing = [name for name in LEGACY_EXPORTS if not hasattr(pkg, name)]
    assert not missing, f"scripts.implementation is missing: {missing}"


def test_legacy_and_package_share_identity():
    """Shim and package must point at the *same* objects, not copies."""
    for name in LEGACY_EXPORTS:
        assert getattr(legacy, name) is getattr(pkg, name), (
            f"{name!r} diverges between generate_implementation and package"
        )


def test_generator_roundtrips_through_both_import_paths():
    """A generator built via the shim should also be instance of the
    package class, confirming we really have a single class identity."""
    g = legacy.ImplementationGenerator()
    assert isinstance(g, pkg.ImplementationGenerator)
    assert g.FS_MACRO_PREFIX == pkg.FS_MACRO_PREFIX
