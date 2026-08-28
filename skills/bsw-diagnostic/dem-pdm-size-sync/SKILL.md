---
name: dem-pdm-size-sync
description: >-
  Analyze and minimally sync DEM Event Memory PDM block sizes
  (`NVM_ID_EVMEM_LOC_*`) to the real `Dem_EvMemEventMemoryType` size for
  a specific Bosch-style AUTOSAR build configuration. Use this skill
  whenever the user mentions `NVM_ID_EVMEM_LOC`, `Dem_PRJ.pdm`,
  `pdmdb`, `Dem_Cfg_AssertionChk.h`, `Dem_EvMemEventMemoryType`,
  `error #94`, freeze-frame/snapshot changes causing DEM/NvM size
  mismatches, or wants to update PDM size after DEM ARXML changes. This
  skill first performs a read-only analysis, then applies only the
  smallest confirmed change to the current project after explicit user
  approval.
---

# dem-pdm-size-sync

Specialized helper for Bosch-style DEM Event Memory to PDM size
alignment.

Use this skill when freeze-frame / snapshot / DEM ARXML changes alter
the effective `Dem_EvMemEventMemoryType` layout and the project must
update `NVM_ID_EVMEM_LOC_*` mappings to match the real NvM block length.
It also supports DEM Generic NV Data analysis through
`Dem_GenericNvDataType` and `NVM_ID_DEM_GENERIC_NV_DATA_*`.

Project-local runtime outputs live under:

```text
<project-root>/.DCOM_AI/DEM_PDM_Size_Sync_PRJ/
```

## In Scope

- Analyze one specific `RBFS_BUILDCONFIG` / generated variant at a time.
- Resolve the active `Dem_PRJ.pdm` file and the exact active branch.
- Compute the real `Dem_EvMemEventMemoryType` size.
- Compare it against current `NVM_ID_EVMEM_LOC_*` size.
- Compare Generic NV Data against current
  `NVM_ID_DEM_GENERIC_NV_DATA_*` size.
- Reuse existing `pdmdb` dataitems when possible.
- Append new `pdmdb` dataitems only when the target size does not exist.
- Apply only the minimum required edits to the current project after
  user confirmation.
- Warn about shared-branch impact on other build configurations.

## Python Environment

Use a Python 3.11 or 3.12 interpreter available on the current machine.
Do not assume a fixed local path.

```text
python
```

If the target machine uses `python3`, a virtual environment, or a Conda
environment, substitute the local command or full interpreter path that
is valid on that machine.

The bundled scripts are stdlib-only and require no package
installation.

## Toolkit Commands

Initialize the project-local workspace first:

```text
python <skill-root>/scripts/pipeline.py init-project \
  --project-root <project-root>
```

Check workspace status:

```text
python <skill-root>/scripts/pipeline.py status \
  --project-root <project-root>
```

Run analysis:

```text
python <skill-root>/scripts/pipeline.py analyze \
  --project-root <project-root> \
  --buildconfig <RBFS_BUILDCONFIG> \
  --target <evmem|generic>
```

Apply after review:

```text
python <skill-root>/scripts/pipeline.py apply \
  --project-root <project-root> \
  --buildconfig <RBFS_BUILDCONFIG> \
  --target <evmem|generic>
```

Verify generated outputs:

```text
python <skill-root>/scripts/pipeline.py verify \
  --project-root <project-root> \
  --buildconfig <RBFS_BUILDCONFIG> \
  --target <evmem|generic>
```

Add `--json` when a machine-readable report is needed. Reports are also
written to `.DCOM_AI/DEM_PDM_Size_Sync_PRJ/outputs/`.

Use `--force-fallback` only for debugging the manual struct-size path
when a `.lst` exists but should be ignored intentionally.

When the target size family is missing, the current implementation can
append a new `NVM_ID_EVMEM_LOC_<size>_0..9` block to `pdmdb` using the
next free ids, then update the active `Dem_PRJ.pdm` branch.

`apply` is implemented for both `evmem` and `generic`. For `generic`,
the skill appends a single `NVM_ID_DEM_GENERIC_NV_DATA_<size>` item in
the OBD Memory Records section when the target family is missing.

## Out Of Scope

- Freeze-frame questionnaire extraction.
- General DEM ARXML authoring.
- Service 0x19 C stub generation.
- DOORS upload.
- Fee/Fls capacity checks by default.
- Automatic multi-project or cross-branch rollout.

If the user asks for broader freeze-frame generation, ARXML synthesis,
or Service 0x19 implementation work, use the appropriate dedicated skill
instead.

## Core Rules

1. Always start in read-only Analyze mode.
2. Never edit anything before explicit user confirmation.
3. Require a concrete build configuration, for example
   `<RBFS_BUILDCONFIG>`.
4. Resolve the active PDM file from generated evidence; never guess.
5. Prefer current generated evidence over historical build artefacts.
6. Prefer `.lst`-based size extraction over manual struct math when the
   listing exists.
7. Use manual struct-size calculation only as the fallback path.
8. Reuse an existing `NVM_ID_EVMEM_LOC_<size>_*` block when it already
   exists in `pdmdb`.
9. Respect the `pdmdb` rule: append only, never modify or delete an
   existing dataitem.
10. Apply only the smallest change in the active branch of the active
    PDM file; do not rewrite whole files.

## Analyze Workflow

Follow these steps in order.

### 1. Validate Inputs

Require a concrete build configuration from the user.

Resolve the generated variant root:

```text
<project-root>/Gen/<buildconfig>/
```

Key files to locate:

- `out/SwitchSettings_*.csv`
- `src_out/obj/Dem_EvMem.lst`
- `src_out/tmp/pdm_includes.h`
- `src_out/tmp/Cfg_DBFiles_GenMake.csv`
- `src_out/bct/_out/Dem_Cfg_AssertionChk.h`
- `src_out/bct/RBPDM_gen_NvM_EcucValues.arxml`

If the generated variant folder or the minimum evidence set is missing,
stop and tell the user exactly what artefact is unavailable.

### 2. Resolve Context

Use these sources together:

- `SwitchSettings_*.csv`
- `RBCM_CSWPrSettings.h`
- project cfg headers such as `*_ropp41_main.h`
- `pdm_includes.h`
- `Cfg_DBFiles_GenMake.csv`

Determine and report:

- current `RBFS_BUILDCONFIG`
- current `RBFS_ProjectVariant`
- current `RBFS_ApbDistributed`
- whether the active file is the project-specific `Dem_PRJ.pdm` under
  the active DEM configuration subtree
- the exact active `#if` / `#elif` branch in that file

Never infer the active branch from file names alone; use generated
evidence to confirm it.

### 3. Compute Real Struct Size

Preferred path:

1. Read `Dem_EvMem.lst`.
2. Find `_Dem_EvMemEventMemory` total size.
3. Resolve `DEM_CFG_EVMEM_EVENTMEMORY_LENGTH`.
4. Compute:

```text
sizeof(Dem_EvMemEventMemoryType) = total_array_size / DEM_CFG_EVMEM_EVENTMEMORY_LENGTH
```

Fallback path when the listing is unavailable:

- Read `Dem_EvMemTypes.h`.
- Read `Dem_PrjEvmemProjectExtension.h`.
- Read current generated `Dem_Cfg*.h` files from the active variant.
- Compute the structure size field by field.
- Apply GHS alignment rules and struct tail padding.

Important:

- `SwitchSettings_*.csv` is useful for `RBFS_*` context, but not for all
  `DEM_CFG_*` values.
- Read `DEM_CFG_*` from current generated headers under
  `src_out/bct/_out/`.
- Do not use an old `.map` file when a current `.lst` exists.
- When using array-size evidence, divide by
  `DEM_CFG_EVMEM_EVENTMEMORY_LENGTH`, not by primary-entry count.

### 4. Resolve Current PDM Mapping

Read all of the following:

- active `Dem_PRJ.pdm`
- the resolved project `pdmdb` file
- `Dem_Cfg_AssertionChk.h`
- `RBPDM_gen_NvM_EcucValues.arxml`
- `NvM_Cfg.h` when available

Build the full chain:

```text
active Dem_PRJ.pdm branch
  -> use dataitem NVM_ID_EVMEM_LOC_<size>_<idx>
  -> pdmdb dataitem definition
  -> generated NvM block length
  -> DEM static assertion size
```

Report both the current mapped size and the target size.

### 5. Check Whether Target Size Already Exists

Search the resolved project `pdmdb` for:

```text
NVM_ID_EVMEM_LOC_<target-size>_0 .. 9
```

If it exists:

- prefer reusing it
- do not append duplicates

If it does not exist:

- plan a new appended `pdmdb` block
- choose the next free contiguous id range
- preserve the existing comment and block style

### 6. Impact Analysis

Before proposing changes, identify which other build configurations share
the same active `Dem_PRJ.pdm` branch.

The default behavior is:

- warn the user about those other configurations
- do not modify them automatically
- do not fan out the same patch into other projects unless the user
  explicitly asks for it

## Apply Workflow

Only start Apply after an explicit user confirmation such as
`confirm apply`, `确认应用`, or `apply current project only`.

### Apply Case A: Target Size Already Exists

Perform the smallest possible edit:

- change only the active branch in the active `Dem_PRJ.pdm`
- replace only the 10 `use dataitem` lines for
  `NVM_ID_EVMEM_LOC_0..9`
- preserve spacing, comments, order, and surrounding formatting

Example:

```text
NVM_ID_EVMEM_LOC_236_0 -> NVM_ID_EVMEM_LOC_384_0
...
NVM_ID_EVMEM_LOC_236_9 -> NVM_ID_EVMEM_LOC_384_9
```

### Apply Case B: Target Size Does Not Exist

Perform two edits only:

1. Append a new `NVM_ID_EVMEM_LOC_<target-size>_0..9` block to `pdmdb`
2. Update the 10 `use dataitem` lines in the active `Dem_PRJ.pdm`

When appending to `pdmdb`:

- never rewrite earlier blocks
- never modify an existing dataitem in place
- keep ids contiguous
- keep comments in the same style as neighboring `EVMEM_LOC` blocks

## Minimal Edit Contract

When you apply changes, follow this contract strictly:

- modify only the active project
- modify only the active PDM file
- modify only the active branch
- modify only `NVM_ID_EVMEM_LOC_0..9`
- do not reformat the whole file
- do not reorder entries
- do not clean up unrelated comments
- do not touch an alternate `Dem_PRJ.pdm` unless analysis proves it is active
- do not touch `TwoBox` branches unless analysis proves they are active

## Verification

After Apply, verify only the directly relevant outputs unless the user
asks for more:

- `Dem_Cfg_AssertionChk.h`
- `RBPDM_gen_NvM_EcucValues.arxml`
- `NvM_Cfg.h` when present
- the latest build or generation log for disappearance of
  `BlockLengthIsInvalid` / `error #94`

Do not run Fee/Fls capacity checks by default.

## Report Format

Use this structure for Analyze results:

```text
Buildconfig
- <buildconfig>

Effective Context
- ProjectVariant: <value>
- ApbDistributed: <value>
- Active PDM file: <path>
- Active branch: <condition>

Size Analysis
- Real Dem_EvMemEventMemoryType size: <n> bytes
- Evidence: <lst-based or fallback calculation>

Current PDM Mapping
- Current NVM_ID_EVMEM_LOC size: <n> bytes
- Current dataitem family: <name>

Recommended Change
- Reuse existing target family: <yes/no>
- Active file edit: <summary>
- pdmdb append required: <yes/no>

Impact Note
- Other buildconfigs sharing this branch: <list or none>

Decision Needed
- Confirm apply to current project only?
```

Use this structure after Apply:

```text
Applied Changes
- Modified files: <paths>
- Active branch updated: <yes/no>
- pdmdb appended: <yes/no>

Verification
- Assertion header updated: <yes/no>
- NvM block length updated: <yes/no>
- Build error removed: <yes/no or not run>

Impact Reminder
- Shared branch configurations not auto-modified: <list or none>
```

## When This Skill Fits Beside Other Skills

This skill often runs after freeze-frame / snapshot ARXML work, but it
is intentionally separate from broader Service 0x19 or DEM-generation
toolkits.

- Use this skill for post-change PDM size alignment.
- Use broader ARXML or Service 0x19 skills for upstream generation work.

## References

Read these bundled references when needed:

- `reference/struct-size-calculation.md` for the fallback size
  calculation method.
- `reference/pdm-branch-resolution.md` for active-file and active-branch
  resolution.
- `reference/apply-rules.md` for exact edit boundaries.
- `reference/workspace-model.md` for the `.DCOM_AI` workspace layout.
