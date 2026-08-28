# PDM Branch Resolution

## Goal

Identify the exact PDM file and the exact branch that the current build
configuration really uses.

## Required Evidence

Use generated evidence first:

- `Gen/<variant>/src_out/tmp/pdm_includes.h`
- `Gen/<variant>/src_out/tmp/Cfg_DBFiles_GenMake.csv`
- `Gen/<variant>/out/SwitchSettings_*.csv`

Then use source-side configuration:

- `RBCM_CSWPrSettings.h`
- project cfg headers that define the active `RBFS_ProjectVariant` and
  project-specific build routing

## Resolution Order

1. Determine the active `RBFS_BUILDCONFIG` from `SwitchSettings_*.csv`.
2. Determine `RBFS_ProjectVariant` and `RBFS_ApbDistributed` from the
   project cfg headers and `RBCM_CSWPrSettings.h`.
3. Confirm which `Dem_PRJ.pdm` was included by reading
   `pdm_includes.h`.
4. Confirm the same file appears in `Cfg_DBFiles_GenMake.csv`.
5. Open that `Dem_PRJ.pdm` and resolve the active `#if` / `#elif`
   branch using the computed `RBFS_*` values.

## Hard Rules

- Never guess the active PDM file from file naming alone.
- Never assume `OBD` or `NonOBD`; prove it from generated includes.
- Never assume a branch is active because it looks similar to the build
  name; prove it from `RBFS_ApbDistributed` and surrounding conditions.

## Output

Always report:

- active PDM file path
- active branch condition
- why that branch is active
- the exact `use dataitem` family currently selected there
