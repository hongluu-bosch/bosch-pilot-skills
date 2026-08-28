# Struct Size Calculation

Use this reference only when `Dem_EvMem.lst` is unavailable or clearly
stale.

## Goal

Compute the real `sizeof(Dem_EvMemEventMemoryType)` for one concrete
generated variant.

## Inputs

Read all of these from the current project and current generated
variant:

- `rba/CUBAS/Diagnosis/Dem/src/evmem/Dem_EvMemTypes.h`
- `rb/.../Dem_PrjEvmemProjectExtension.h`
- generated `src_out/bct/_out/Dem_Cfg*.h`
- generated `src_out/bct/_out/rba_DemObdBasic_Cfg_Main.h`
- `SwitchSettings_*.csv` only for `RBFS_*` context, not as the sole DEM
  source of truth

## Method

1. Resolve every `#if` in `Dem_EvMemTypes.h` using current generated
   `DEM_CFG_*` values.
2. Expand typedef sizes before counting.
3. Include nested structs and unions.
4. Apply GHS alignment rules:
   - `uint8`, `sint8`, `boolean`: 1-byte alignment
   - `uint16`: 2-byte alignment
   - `uint32`: 4-byte alignment
   - struct size aligned to its maximum member alignment
5. Add explicit internal padding and final tail padding.

## Important Checks

- `DEM_CFG_ENVMINSIZE_OF_MULTIPLE_RAWENVDATA` usually dominates the size.
- `DEM_CFG_EVMEM_PROJECT_EXTENSION` can change the total size.
- `Dem_EvMemProjectExtensionType` must be counted with its own padding.
- OBD-related booleans and timestamps depend on generated OBD switches,
  not just the project name.
- Do not divide total array size by primary-entry count. When using the
  array-based method, divide by `DEM_CFG_EVMEM_EVENTMEMORY_LENGTH`.

## Preference Order

1. Current `.lst`
2. Current fallback manual calculation
3. Old `.map` only as historical context, never as the final answer when
   current generated artefacts exist
