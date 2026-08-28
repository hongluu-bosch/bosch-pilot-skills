#!/usr/bin/env python3
"""Implementation Code Generator -- Phase 3 import shim.

Since phase 7 the actual generator lives under
``scripts/implementation/`` as a proper package. This file keeps the
original public surface (``ImplementationGenerator``,
``DIDImplementationInfo``, helper functions) so every existing
``from generate_implementation import ...`` site -- in particular the
unit tests -- keeps working.

v1.20.0 cull: the standalone
``python scripts/generate_implementation.py ...`` CLI was removed.
The Phase 3 entry point is now the single CLI in
``pipeline.py --phase implementation``, which imports
``ImplementationGenerator`` directly. The previous standalone main()
carried its own argparse (a duplicate maintenance surface) plus a
v1.16.0-stale read of ``config['project']['product_type']`` that
schema 2.0 forbids.

See :mod:`scripts.implementation` (``__init__.py``) for the full list
of re-exported symbols, and :mod:`scripts.implementation.orchestrator`
for the class itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``from generate_implementation import ...`` to resolve the
# ``implementation`` sub-package when the file is loaded by a sibling
# script.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from io_encoding import reconfigure_stdio_utf8  # noqa: E402

reconfigure_stdio_utf8()

# Re-export the full public API so legacy imports keep working.
from implementation import (  # noqa: E402,F401
    DIDImplementationInfo,
    DIDInput,
    DIDSubField,
    FS_MACRO_PREFIX,
    NVM_ID_PREFIX,
    ImplementationGenerator,
    capitalize_first,
    clean_name,
    generate_config_macro,
    generate_config_settings_macro,
    generate_element_defs,
    generate_enum_conditions,
    generate_pdm_entry,
    generate_range_macros,
    generate_read_code,
    generate_write_code,
    get_fs_macro,
    get_func_name,
    get_nvm_id,
    get_range_macro_name,
    guarded_project_write,
    parse_enum_values,
    parse_numeric_range,
    product_type_lower,
    resolve_path,
)
