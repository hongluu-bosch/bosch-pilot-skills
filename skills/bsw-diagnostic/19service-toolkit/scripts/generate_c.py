"""Phase 3: generate snapshot read-function C stubs."""

from __future__ import annotations

import pathlib
from typing import Any

from implementation.orchestrator import run_snapshot_c_generation


def run_phase3(workspace: pathlib.Path, args: Any) -> int:
    return run_snapshot_c_generation(workspace, args)
