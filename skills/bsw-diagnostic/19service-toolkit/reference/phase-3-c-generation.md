# Phase 3 — Snapshot C Stub Generation

Phase 3 reads `outputs/fscs/fscs.json` and generates per-DID C stub files
for Service 0x19 snapshot read functions directly into the Bosch project tree.

## Scope

- Only read-function `.c` stubs are generated.
- No headers, Config.h, ConfigSettings.h, ConfigElements.h or PDM are generated.
- Existing `.c` files always win (skip-if-exists).
- The generated bodies intentionally remain `TODO(agent)` stubs; Phase 3 does
  not fill project-specific MESG / RBMESG / direct-interface logic.

## Input

- `outputs/fscs/fscs.json`
- `config/project.json`

## Output

- Bosch tree: `<base_dir>/<project_root>/rb/as/<customer>/core/app/dcom/RBAPLCust/src/<PT>/RBAPLCUST_19Snapshot_<DID>_<Name>.c`
- Reports: `.DCOM_AI/19Service_Toolkit_PRJ/outputs/c/<PT>/generation_report.txt`

## Product fan-out

Phase 3 generates files once per effective DID product type (`used=True`). The
target directory is resolved from:

- `per_product.<PT>.snapshot_c_output_subdir` when present, or
- `paths.snapshot_c_output_subdir` with `{product_type}` substituted.

`--init-project` auto-detects `RBAPLCust/src/<PT>/` folders and writes the
relative paths into `per_product` so the skill stays project-agnostic.

## Generated file template

Each stub contains:

- Bosch-style file header
- Snapshot DID identity block
- Function signature matching `fscs.json::read_fnc`
- Inline `TODO(agent)` block carrying:
  - DID identity
  - size
  - product type
  - record numbers
  - sub-field layout summary
  - heuristic source hint (MESG / RBMESG / getter / direct struct)
- `(void)Data;` + `return E_NOT_OK;`

## `fscs.json` back-write

After generation, each effective DID gains:

```json
{
  "generated_c_file": "C:/.../RBAPLCUST_19Snapshot_1100_WheelSpeedAndVehicleSpeed.c"
}
```

This lets later review/fill-in tooling locate the exact stub file without
re-scanning the Bosch tree.
