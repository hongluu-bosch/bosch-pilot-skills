"""Render a starter project.json for visual inspection.

Spits out both the mirror-enabled and mirror-disabled shapes so you can
eyeball what `--init-project` produces under each detection outcome.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))

from init_project import _build_starter_config

mirror_on = _build_starter_config(
    name="ExampleProject",
    customer_name="<customer>",
    project_root="<project_root>",
    base_dir="/abs/path/to/project-container",
    mirror_enabled=True,
)
print("=" * 72)
print("CASE A: mirror enabled (Bosch tree was detected at init time)")
print("=" * 72)
print(json.dumps(mirror_on, indent=2))

print()
print("=" * 72)
print("CASE B: mirror disabled (no Bosch tree under workspace; outputs-only)")
print("=" * 72)
mirror_off = _build_starter_config(
    name="ExampleProject",
    customer_name="<customer>",
    project_root="<project_root>",
    base_dir="/abs/path/to/no-bosch-workspace",
    mirror_enabled=False,
)
print(json.dumps(mirror_off, indent=2))
