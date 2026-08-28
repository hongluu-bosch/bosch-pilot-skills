# C Code Templates Reference

Authoritative C code bodies used by Phase 3 for RDBI (Service 0x22) and WDBI (Service 0x2E). The templates live as Jinja2 files under `scripts/templates/impl/*.j2`; this document is the human-readable specification of what they render.

Read this when debugging an unexpected generated `.c`, tweaking a template, or validating the RAM vs EEPROM storage branch.

## Template Overview

| Template | File Pattern | Storage Type | Description |
|----------|--------------|--------------|-------------|
| Read (RAM) | `RBAPLCUST_RDBI_{Name}.c` | RAM/Non-EEPROM | Read data from memory without NVM |
| Read (NVM) | `RBAPLCUST_RDBI_{Name}.c` | EEPROM | Read data from NVM using `DCOM_ReadDataByNVMId` |
| Write (RAM) | `RBAPLCUST_WDBI_{Name}.c` | RAM/Non-EEPROM | Write data to memory without NVM |
| Write (NVM) | `RBAPLCUST_WDBI_{Name}.c` | EEPROM | Write data to NVM using `DCOM_WriteDataByNVMId` |

## Placeholder Variables

| Placeholder | Description | Example |
|-------------|-------------|---------|
| `{func_name}` | Full function name | `RBAPLCUST_0101_VariantCoding_ReadData` |
| `{func_name_only}` | Function name without suffix | `0101_VariantCoding` |
| `{fs_macro}` | Feature switch macro name | `RBFS_DCOM_0101_VARIANTCODING` |
| `{did.did_hex}` | DID hexadecimal identifier | `0x0101` |
| `{did.did_name}` | DID description | `Variant Coding` |
| `{did.size_bytes}` | Data size in bytes | `16` |
| `{nvm_id}` | NVM block identifier | `NVM_ID_DCOM_0101_VARIANTCODING` |

## Read Function Template (RAM / ROM / Flash — skeleton)

> **Scope note.** Any DID whose canonical `storage_position` is not
> `EEPROM` (i.e. `RAM` or `ROM` — the latter also covering the `Flash`
> input alias) renders this skeleton. The body carries a kind-tagged
> comment (`(RAM storage)` vs `(ROM/Flash storage)`) plus a matching
> `TODO: Implement <KIND>-backed read logic` marker so reviewers can
> tell the two apart at a glance; future releases will split the skeleton
> into `memcpy`-from-static-table for ROM/Flash and an in-memory
> getter for RAM without touching the template selection logic.

Template for Read Data By Identifier (Service 0x22) without EEPROM storage:

```c
/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_RDBI_{func_name_only}.c
 * Contains function to read Information.
 *
 * {func_name}_ReadData -- Read the {func_name_only} Information
 *
 * \copyright
 * Robert Bosch GmbH reserves all rights even in the event of industrial property rights.
 * We reserve all rights of disposal such as copying and passing on to third parties.
 */


/* used interfaces */

#include "RBAPLCUST_Global.h"

/* realized interfaces */

/* Assert supported configurations: switches, parameters, constants, ... */
RB_ASSERT_SWITCH_SETTINGS({fs_macro},
						  {fs_macro}_ON,
						  {fs_macro}_OFF);


/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  {func_name}_ReadData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Read the {func_name_only} Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- corresponding buffer for updating {func_name_only} information
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType {func_name}_ReadData (uint8 * Data)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if({fs_macro} == {fs_macro}_ON)
	/* DID: {did.did_hex} - {did.did_name}
	 * Operation: Read data ({KIND} storage)   /* {KIND} = RAM | ROM/Flash */
	 * Size: {did.size_bytes} bytes
	 * TODO: Implement {KIND}-backed read logic for this DID */
#endif
	return retVal;
}

/** @}
 * End ingroup 'RBAPLCust'
 */
```

**Key Characteristics:**
- Single include: `RBAPLCUST_Global.h`
- Feature switch protection with `RB_ASSERT_SWITCH_SETTINGS`
- Returns `E_NOT_OK` when feature switch is OFF
- Includes TODO marker for manual implementation

## Read Function Template (EEPROM/NVM)

Template for Read Data By Identifier (Service 0x22) with EEPROM storage:

```c
/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_RDBI_{func_name_only}.c
 * Contains function to read Information.
 *
 * {func_name}_ReadData -- Read the {func_name_only} Information
 *
 * \copyright
 * Robert Bosch GmbH reserves all rights even in the event of industrial property rights.
 * We reserve all rights of disposal such as copying and passing on to third parties.
 */


/* used interfaces */

#include "RBAPLCUST_Global.h"
#include "RBAPLCUST_NVMGeneric.h"

/* realized interfaces */

/* Assert supported configurations: switches, parameters, constants, ... */
RB_ASSERT_SWITCH_SETTINGS({fs_macro},
						  {fs_macro}_ON,
						  {fs_macro}_OFF);


/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  {func_name}_ReadData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Read the {func_name_only} Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- corresponding buffer for updating {func_name_only} information
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType {func_name}_ReadData (uint8 * Data)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if({fs_macro} == {fs_macro}_ON)
	/* DID: {did.did_hex} - {did.did_name}
	 * Operation: Read data from NVM (EEPROM)
	 * NVM Block: {nvm_id}
	 * Size: {did.size_bytes} bytes
	 * Default value: 0xFF */
	retVal = DCOM_ReadDataByNVMId(NvMConf_NvMBlockDescriptor_{nvm_id}, Data, NVM_CFG_NV_BLOCK_LENGTH_{nvm_id}, 0xFF);
#endif
	return retVal;
}

/** @}
 * End ingroup 'RBAPLCust'
 */
```

**Key Characteristics:**
- Additional include: `RBAPLCUST_NVMGeneric.h`
- Uses `DCOM_ReadDataByNVMId()` API
- Includes NVM block information in comments
- Default fill value: `0xFF`

## Write Function Template (RAM — skeleton)

> ROM/Flash DIDs are always `rw_state: R` (compile-time constants
> cannot be written), so no write skeleton is emitted for them. If a
> customer input ever tries `storage_pos: "ROM"` with `rw_state: "RW"`,
> the adapter demotes it to read-only rather than emitting a write
> stub that would fail at link time.

Template for Write Data By Identifier (Service 0x2E) without EEPROM storage:

```c
/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_WDBI_{func_name_only}.c
 * Contains function to write Information.
 *
 * {func_name}_WriteData -- Write the {func_name_only} Information
 *
 * \copyright
 * Robert Bosch GmbH reserves all rights even in the event of industrial property rights.
 * We reserve all rights of disposal such as copying and passing on to third parties.
 */


/* used interfaces */

#include "RBAPLCUST_Global.h"

/* realized interfaces */

/* Assert supported configurations: switches, parameters, constants, ... */
RB_ASSERT_SWITCH_SETTINGS({fs_macro},
						  {fs_macro}_ON,
						  {fs_macro}_OFF);


/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  {func_name}_WriteData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Write the {func_name_only} Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- information requested for updating {func_name_only} information
 *  ErrorCode -- information about the error caused
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType {func_name}_WriteData (const uint8 * Data, Dcm_NegativeResponseCodeType * ErrorCode)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if({fs_macro} == {fs_macro}_ON)
	/* DID: {did.did_hex} - {did.did_name}
	 * Operation: Write data ({KIND} storage)   /* {KIND} = RAM */
	 * Size: {did.size_bytes} bytes
	 * TODO: Implement {KIND}-backed write logic for this DID */
#endif
	return retVal;
}

/** @}
 * End ingroup 'RBAPLCust'
 */
```

**Key Characteristics:**
- Takes `ErrorCode` parameter for negative response codes
- Feature switch protection with `RB_ASSERT_SWITCH_SETTINGS`
- Returns `E_NOT_OK` when feature switch is OFF
- Includes TODO marker for manual implementation

## Write Function Template (EEPROM/NVM)

Template for Write Data By Identifier (Service 0x2E) with EEPROM storage:

```c
/**
 * @ingroup 'RBAPLCust'
 * @{
 *
 * RBAPLCUST_WDBI_{func_name_only}.c
 * Contains function to write NVM Information into EEPROM
 *
 * {func_name}_WriteData -- Write the {func_name_only} Information
 *
 * \copyright
 * Robert Bosch GmbH reserves all rights even in the event of industrial property rights.
 * We reserve all rights of disposal such as copying and passing on to third parties.
 */


/* used interfaces */

#include "RBAPLCUST_Global.h"
#include "RBAPLCUST_NVMGeneric.h"

/* realized interfaces */

/* Assert supported configurations: switches, parameters, constants, ... */
RB_ASSERT_SWITCH_SETTINGS({fs_macro},
						  {fs_macro}_ON,
						  {fs_macro}_OFF);


/*
 * --------------------------------------------------------------------------
 * FUNCTION_NAME:
 *  {func_name}_WriteData
 * FUNCTION_NAME_END:
 * --------------------------------------------------------------------------
 * FUNCTION_DESCRIPTION:
 *  Write the {func_name_only} Information
 * FUNCTION_DESCRIPTION_END:
 * --------------------------------------------------------------------------
 * FUNCTION_PARAMETER:
 *  Data --- information requested for updating {func_name_only} information
 *  ErrorCode -- information about the error caused
 * FUNCTION_PARAMETER_END:
 * --------------------------------------------------------------------------
 * FUNCTION_RETURN:
 *  E_OK -- means the function is executed successfully
 *  E_NOT_OK -- means the function is not completed / error code
 * FUNCTION_RETURN_END:
 * --------------------------------------------------------------------------
 */

Std_ReturnType {func_name}_WriteData (const uint8 * Data, Dcm_NegativeResponseCodeType * ErrorCode)
{
	/* Return value initialization */
	Std_ReturnType retVal = E_NOT_OK;
#if({fs_macro} == {fs_macro}_ON)
	/* DID: {did.did_hex} - {did.did_name}
	 * Operation: Write data to NVM (EEPROM) without value range restriction
	 * Size: {did.size_bytes} bytes
	 * NVM Block: {nvm_id} */
	retVal = DCOM_WriteDataByNVMId(NvMConf_NvMBlockDescriptor_{nvm_id}, Data, ErrorCode);
#else
	/* Feature switch disabled - return request out of range */
	*ErrorCode = DCM_E_REQUESTOUTOFRANGE;
#endif
	return retVal;
}

/** @}
 * End ingroup 'RBAPLCust'
 */
```

**Key Characteristics:**
- Uses `DCOM_WriteDataByNVMId()` API
- Includes `#else` branch for feature switch OFF case
- Sets `DCM_E_REQUESTOUTOFRANGE` error code when disabled
- NVM block information in comments

## Template Selection Logic

The generation script selects templates based on:

1. **Service Type**: Service 0x22 (Read) or Service 0x2E (Write)
2. **Storage Position**: `EEPROM` or `RAM` (from input JSON)
3. **File Organization**:
   - Read functions → `RBAPLCUST_RDBI_{Name}.c`
   - Write functions → `RBAPLCUST_WDBI_{Name}.c`

**Selection Matrix:**

| Service | Storage | Template | API Function |
|---------|---------|----------|--------------|
| 0x22 (Read) | RAM | RBAPLCUST_RDBI_Template | Manual implementation |
| 0x22 (Read) | EEPROM | RBAPLCUST_RDBI_NVM_Template | `DCOM_ReadDataByNVMId` |
| 0x2E (Write) | RAM | RBAPLCUST_WDBI_Template | Manual implementation |
| 0x2E (Write) | EEPROM | RBAPLCUST_WDBI_NVM_Template | `DCOM_WriteDataByNVMId` |

## Comment Standards

All generated C code must include:

1. **File Header**: Doxygen-style with `@ingroup` and `@{`
2. **Copyright Notice**: Robert Bosch GmbH standard text
3. **Interface Documentation**: `FUNCTION_NAME`, `FUNCTION_DESCRIPTION`, `FUNCTION_PARAMETER`, `FUNCTION_RETURN` blocks
4. **Implementation Comments**:
   - DID identifier and description
   - Operation type (Read/Write)
   - Storage type (EEPROM/RAM)
   - Size information
   - TODO markers for unimplemented logic
