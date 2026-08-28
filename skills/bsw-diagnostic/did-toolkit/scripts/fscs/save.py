"""Atomic persistence helpers for FSCS JSON and text views."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Dict

from .renderer import render_fscs_22_txt, render_fscs_2e_txt, render_fscs_json
from .schema import FSCSDocument


def fscs_paths(outputs_dir: Path) -> Dict[str, Path]:
    """Canonical per-file paths under ``<outputs_dir>/fscs/``."""

    fscs_dir = outputs_dir / "fscs"
    return {
        "json": fscs_dir / "fscs.json",
        "txt_22": fscs_dir / "FSCS_22.txt",
        "txt_2e": fscs_dir / "FSCS_2E.txt",
    }


def atomic_write(path: Path, content: str) -> None:
    """Write ``content`` atomically via a temp file in the same directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_all(doc: FSCSDocument, paths: Dict[str, Path]) -> None:
    """Atomically rewrite ``fscs.json`` + both ``FSCS_*.txt`` views."""

    atomic_write(paths["json"], render_fscs_json(doc))
    atomic_write(paths["txt_22"], render_fscs_22_txt(doc))
    atomic_write(paths["txt_2e"], render_fscs_2e_txt(doc))
