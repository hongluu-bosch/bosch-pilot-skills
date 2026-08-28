# Workspace Model

## Goal

Keep the skill itself global and reusable, while storing per-project
state inside the current workspace.

## Skill Root

The user-level skill lives under:

```text
~/.config/opencode/skills/dem-pdm-size-sync/
```

This area is read-only at runtime except when the skill itself is being
developed.

## Project Workspace

Each analyzed AUTOSAR project gets its own local workspace:

```text
<project-root>/.DCOM_AI/DEM_PDM_Size_Sync_PRJ/
```

## Layout

```text
config/
  project.json
outputs/
  latest_report.json
  latest_report.txt
  apply_report.json
  apply_report.txt
  verify_report.json
  verify_report.txt
state/
logs/
.gitignore
```

## Ownership

- `config/project.json`
  - toolkit-managed default metadata for this project
- `outputs/*`
  - toolkit-generated analysis and verification outputs
- `state/*`
  - reserved for future persistent run state
- `logs/*`
  - reserved for future debug logs

## Command Entry Points

- `pipeline.py init-project`
- `pipeline.py status`
- `pipeline.py analyze`
- `pipeline.py apply`
- `pipeline.py verify`
