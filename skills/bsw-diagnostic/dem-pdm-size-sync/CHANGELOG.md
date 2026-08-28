# Changelog

## 0.1.0

Initial public toolkit release.

### Added

- Global user-level `dem-pdm-size-sync` skill structure.
- Toolkit-style `pipeline.py` entrypoint with:
  - `init-project`
  - `status`
  - `analyze`
  - `apply`
  - `verify`
- Project-local workspace under:
  - `.DCOM_AI/DEM_PDM_Size_Sync_PRJ/`
- Structured report output to workspace `outputs/`.
- Support for `evmem` target:
  - `Dem_EvMemEventMemoryType`
  - `NVM_ID_EVMEM_LOC_*`
- Support for `generic` target:
  - `Dem_GenericNvDataType`
  - `NVM_ID_DEM_GENERIC_NV_DATA_*`
- `.lst`-based size extraction.
- Fallback struct-size calculation for Bosch-style DEM layouts.
- Minimal apply logic for active project / active branch only.
- `pdmdb` append support for missing target families.
- Generic NV Data append placement after the OBD Memory Records section.
- Context-sensitive `dataitem` prefix reuse from the active `pdmdb`.
- User-facing README written as an operation manual.
- Reference docs for workspace model, size calculation, PDM branch
  resolution, and apply rules.
- Initial eval prompts under `evals/evals.json`.

### Notes

- The toolkit does not run project-specific regeneration chains.
- Fee/Fls capacity checks are intentionally out of scope by default.
- Impact analysis is conservative and may list more shared buildconfigs
  than are strictly necessary.
