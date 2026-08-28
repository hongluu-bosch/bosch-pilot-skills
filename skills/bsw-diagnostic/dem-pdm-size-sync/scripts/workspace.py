#!/usr/bin/env python3
"""Workspace helpers for dem-pdm-size-sync."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_DIRNAME = "DEM_PDM_Size_Sync_PRJ"


@dataclass(frozen=True)
class WorkspacePaths:
    project_root: Path
    skill_root: Path
    workspace_root: Path
    config_dir: Path
    outputs_dir: Path
    state_dir: Path
    logs_dir: Path
    project_json: Path
    gitignore_path: Path


def resolve_paths(project_root: Path, skill_root: Path) -> WorkspacePaths:
    workspace_root = project_root / ".DCOM_AI" / WORKSPACE_DIRNAME
    return WorkspacePaths(
        project_root=project_root,
        skill_root=skill_root,
        workspace_root=workspace_root,
        config_dir=workspace_root / "config",
        outputs_dir=workspace_root / "outputs",
        state_dir=workspace_root / "state",
        logs_dir=workspace_root / "logs",
        project_json=workspace_root / "config" / "project.json",
        gitignore_path=workspace_root / ".gitignore",
    )


def init_workspace(paths: WorkspacePaths) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)

    asset_gitignore = paths.skill_root / "assets" / "workspace_gitignore.txt"
    if asset_gitignore.exists() and not paths.gitignore_path.exists():
        paths.gitignore_path.write_text(asset_gitignore.read_text(encoding="utf-8"), encoding="utf-8", newline="")

    if not paths.project_json.exists():
        payload = {
            "project_root": str(paths.project_root),
            "workspace_root": str(paths.workspace_root),
            "notes": "Fill buildconfig/target defaults here if desired. Runtime commands can still override them.",
            "defaults": {
                "buildconfig": "",
                "target": "evmem",
            },
        }
        paths.project_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8", newline="")


def load_project_config(paths: WorkspacePaths) -> dict:
    if not paths.project_json.exists():
        return {}
    return json.loads(paths.project_json.read_text(encoding="utf-8"))


def save_report(paths: WorkspacePaths, stem: str, payload: dict, text: str) -> None:
    (paths.outputs_dir / f"{stem}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8", newline=""
    )
    (paths.outputs_dir / f"{stem}.txt").write_text(text, encoding="utf-8", newline="")
