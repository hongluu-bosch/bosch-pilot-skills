# Apply Rules

## Default Mode

Apply only after explicit user confirmation.

Default apply mode is conservative:

- current project only
- active file only
- active branch only
- minimum line changes only

## What You May Edit

- active `Dem_PRJ.pdm` branch
- active `use dataitem NVM_ID_EVMEM_LOC_*` lines
- the resolved project `pdmdb` file only when a new target size block
  must be appended

## What You Must Not Edit

- inactive branches
- inactive PDM files
- unrelated `NVM_ID_*` items
- existing `pdmdb` dataitems in place
- unrelated formatting, comments, or ordering

## Existing Target Size Case

If `NVM_ID_EVMEM_LOC_<target-size>_0..9` already exists:

- do not append anything to `pdmdb`
- change only the 10 `use dataitem` lines in the active branch

## Missing Target Size Case

If the target size does not exist:

- append one new contiguous 10-item block to `pdmdb`
- keep the same comment style as neighboring `EVMEM_LOC` blocks
- assign the next free id range
- then update only the 10 active `use dataitem` lines

## Verification Scope

After writing, verify the directly relevant generated outputs only:

- `Dem_Cfg_AssertionChk.h`
- `RBPDM_gen_NvM_EcucValues.arxml`
- `NvM_Cfg.h` when available

Do not expand the scope unless the user asks for more.
