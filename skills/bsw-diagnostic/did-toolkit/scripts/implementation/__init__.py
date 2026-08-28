"""Implementation sub-package (phase 7 split of generate_implementation.py).

Public API re-exports live here so downstream code and tests can import
them without knowing which module physically hosts each symbol:

* ``DIDImplementationInfo``      -- dataclass (models)
* ``DIDInput``                   -- pydantic input validator (models)
* ``ImplementationGenerator``    -- main orchestrator class
* ``parse_enum_values`` / ``parse_numeric_range`` -- value-range helpers (parsers)
* naming helpers (naming)
* path / product-type helpers (paths)
* guarded-write safety layer (safety)
* rendering helpers (generators)

``scripts/generate_implementation.py`` is kept as a thin backward-compatibility
shim so every existing ``from generate_implementation import X`` keeps working.
"""

from .models import DIDImplementationInfo, DIDInput, DIDSubField
from .naming import (
    FS_MACRO_PREFIX,
    NVM_ID_PREFIX,
    capitalize_first,
    clean_name,
    get_fs_macro,
    get_func_name,
    get_nvm_id,
    get_range_macro_name,
)
from .parsers import parse_enum_values, parse_numeric_range
from .paths import (
    MirrorResolution,
    product_type_lower,
    resolve_mirror_path,
    resolve_path,
)
from .safety import guarded_project_write
from .generators import (
    generate_config_macro,
    generate_config_settings_macro,
    generate_element_defs,
    generate_pdm_entry,
    generate_range_macros,
    generate_read_code,
    generate_write_code,
    generate_enum_conditions,
)
from .orchestrator import ImplementationGenerator
from .arxml_merge import (
    extract_dcmdsp_short_names,
    merge_arxml,
)

__all__ = [
    "DIDImplementationInfo",
    "DIDInput",
    "DIDSubField",
    "FS_MACRO_PREFIX",
    "NVM_ID_PREFIX",
    "capitalize_first",
    "clean_name",
    "get_fs_macro",
    "get_func_name",
    "get_nvm_id",
    "get_range_macro_name",
    "parse_enum_values",
    "parse_numeric_range",
    "MirrorResolution",
    "product_type_lower",
    "resolve_mirror_path",
    "resolve_path",
    "guarded_project_write",
    "generate_config_macro",
    "generate_config_settings_macro",
    "generate_element_defs",
    "generate_pdm_entry",
    "generate_range_macros",
    "generate_read_code",
    "generate_write_code",
    "generate_enum_conditions",
    "ImplementationGenerator",
    "extract_dcmdsp_short_names",
    "merge_arxml",
]
