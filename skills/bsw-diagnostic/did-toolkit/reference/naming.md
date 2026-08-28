# Naming Conventions Reference

Full naming conventions for functions, files, macros, NVM IDs, value-range macros, and ARXML elements. Read this whenever you are generating, modifying, or validating any Bosch diagnostic artefact — the pipeline relies on strict consistency across ARXML / C code / FSCS / PDM.

## Function Naming

### Format

```
RBAPLCUST_<DID_HEX>_<DID_Name>_<Operation>
```

### Components

| Component | Description | Example |
|-----------|-------------|---------|
| `RBAPLCUST_` | Fixed prefix | - |
| `<DID_HEX>` | DID hex identifier (uppercase, no 0x) | `0101`, `F197` |
| `<DID_Name>` | Cleaned DID name | `VariantCoding` |
| `<Operation>` | Operation type | `ReadData`, `WriteData` |

### Examples

```c
// DID 0x0101 VariantCoding
RBAPLCUST_0101_VariantCoding_ReadData
RBAPLCUST_0101_VariantCoding_WriteData

// DID 0xF199 ProgrammingDateDataIdentifier
RBAPLCUST_F199_ProgrammingDateDataIdentifier_ReadData
RBAPLCUST_F199_ProgrammingDateDataIdentifier_WriteData

// DID 0x0110 Manufactory mode
RBAPLCUST_0110_Manufactorymode_ReadData
RBAPLCUST_0110_Manufactorymode_WriteData
```

### Important Notes

- **Must include DID_HEX**: Ensures function name uniqueness
- **DID_Name cleaning rules**:
  - Remove all spaces
  - Remove special characters (keep alphanumeric only)
  - First letter uppercase
  - Example: `Manufactory mode` → `Manufactorymode`

## File Naming

### Format

```
RBAPLCUST_{RDBI|WDBI}_{DID_Name}.c
```

### Rules

- **No DID_HEX**: Keep file names concise
- **Use short name**: Use cleaned DID name (without DID_HEX)
- **Unified prefix**:
  - Read: `RBAPLCUST_RDBI_`
  - Write: `RBAPLCUST_WDBI_`

### Examples

```
RBAPLCUST_RDBI_VariantCoding.c          # NOT RDBI_0101_VariantCoding.c
RBAPLCUST_WDBI_VariantCoding.c          # Write file
RBAPLCUST_RDBI_Manufactorymode.c
RBAPLCUST_RDBI_ProgrammingDateDataIdentifier.c
```

### Difference from Function Names

| Type | Format | Example |
|------|--------|---------|
| **Function Name** | Includes DID_HEX | `RBAPLCUST_0101_VariantCoding_ReadData` |
| **File Name** | Excludes DID_HEX | `RBAPLCUST_RDBI_VariantCoding.c` |

**Reason**:
- Function names need uniqueness (referenced in ARXML)
- File names need readability (for developer identification)

## Feature Switch Macro Naming

### Base Macro

```
RBFS_DCOM_<DID_Name>
```

### ON/OFF Value Macros

```
RBFS_DCOM_<DID_Name>_ON
RBFS_DCOM_<DID_Name>_OFF
```

### Examples

```c
// Config.h - Default OFF
#ifndef RBFS_DCOM_VariantCoding
#define RBFS_DCOM_VariantCoding        RBFS_DCOM_VariantCoding_OFF
#endif

// ConfigSettings.h - Configure ON
#define RBFS_DCOM_VariantCoding        RBFS_DCOM_VariantCoding_ON

// ConfigElements.h - Value definitions
#define RBFS_DCOM_VariantCoding_ON                                              1
#define RBFS_DCOM_VariantCoding_OFF                                             2
```

### Alignment Specification

```c
/* ------------------------------------------------------------------------ */
/* RBFS_DCOM_VariantCoding                                                */
/* ------------------------------------------------------------------------ */
/*DE|Feature Switch for DID $0101h - Variant Coding |*/
#ifndef RBFS_DCOM_VariantCoding
#define RBFS_DCOM_VariantCoding        RBFS_DCOM_VariantCoding_OFF
#endif
```

- Separator line: 70 characters (`/* --- */`)
- Macro name: Left-aligned, maximum width 70 characters
- Value: Use tab to align to 8th tab stop

## NVM ID Naming

### Principle

**Use FSCS value directly, no modification!**

### Standard Format

```
NVM_ID_DCOM_<DID_Name>
```

### Usage Locations

**PDM File**:
```pdm
use dataitem NVM_ID_DCOM_VariantCoding
```

**C Code**:
```c
// Read
DCOM_ReadDataByNVMId(
    NvMConf_NvMBlockDescriptor_NVM_ID_DCOM_VariantCoding,
    Data,
    NVM_CFG_NV_BLOCK_LENGTH_NVM_ID_DCOM_VariantCoding,
    0xFF
);

// Write
DCOM_WriteDataByNVMId(
    NvMConf_NvMBlockDescriptor_NVM_ID_DCOM_VariantCoding,
    Data,
    ErrorCode
);
```

### Important Reminders

- **Do not add prefix**: If FSCS shows `NVM_ID_DCOM_XXX`, use it directly
- **Do not remove prefix**: If FSCS shows `CST_NvM`, use `CST_NvM` directly
- **Exact match**: NVM ID in PDM and C code must match FSCS exactly

## Value Range Macro Naming

### Format

```
DID_<DID_HEX>_<SUFFIX>
```

### Suffix Types

| Type | Suffix | Example |
|------|--------|---------|
| Minimum | `MIN` | `DID_0101_MIN` |
| Maximum | `MAX` | `DID_0101_MAX` |
| Enum Value | `VAL_<index>` | `DID_0101_VAL_0` |

### Examples

```c
// Numeric range
#define DID_0101_MIN        0
#define DID_0101_MAX        255

// Enum values
#define DID_0110_VAL_0      0x00
#define DID_0110_VAL_1      0x01
#define DID_0110_VAL_2      0x02
```

## ARXML Element Naming

### DcmDspData

```xml
<SHORT-NAME>RBAPLCUST_{DID}_{Name}Data</SHORT-NAME>
```

Example: `RBAPLCUST_0101_VariantCodingData`

### DcmDspDataReadFnc

```xml
<VALUE>RBAPLCUST_{DID}_{Name}_ReadData</VALUE>
```

Example: `RBAPLCUST_0101_VariantCoding_ReadData`

### DcmDspDataWriteFnc

```xml
<VALUE>RBAPLCUST_{DID}_{Name}_WriteData</VALUE>
```

Example: `RBAPLCUST_0101_VariantCoding_WriteData`

### DcmDspDid

```xml
<SHORT-NAME>RBAPLCUST_{DID}_{Name}DataDid</SHORT-NAME>
```

Example: `RBAPLCUST_0101_VariantCodingDataDid`

### DcmDspDidIdentifier

```xml
<VALUE>{decimal_did}</VALUE>
```

Example: `257` (corresponds to 0x0101)

## Consistency Checklist

- [ ] C function names match `DcmDspDataReadFnc`/`WriteFnc` in ARXML exactly
- [ ] C file names exclude DID_HEX, but function names include DID_HEX
- [ ] Feature Switch macros use `RBFS_DCOM_<Name>` format
- [ ] NVM IDs match `NVM Item:` in FSCS exactly
- [ ] Value range macros use `DID_<HEX>_<SUFFIX>` format
- [ ] German comment format: `/*DE|...*/`

## Naming Generation Code

The implementations live in `scripts/implementation/naming.py` (pure helpers).

### Function Name Generation

```python
def _get_func_name(self, did: DIDImplementationInfo) -> str:
    """Generate: RBAPLCUST_<DID_HEX>_<DID_Name>"""
    did_hex_clean = did.did_hex.replace('0x', '').upper()
    clean_name = self._clean_name(did.did_name)
    return f"RBAPLCUST_{did_hex_clean}_{self._capitalize_first(clean_name)}"
```

### File Name Generation

```python
def generate_read_code(self, did: DIDImplementationInfo) -> str:
    func_name_only = self._capitalize_first(self._clean_name(did.did_name))
    filename = f"RBAPLCUST_RDBI_{func_name_only}.c"
```

### Feature Switch Macro

```python
def _get_fs_macro(self, did_name: str) -> str:
    """Generate: RBFS_DCOM_<Name>"""
    clean = self._clean_name(did_name)
    clean = self._capitalize_first(clean)
    return f"{self.fs_prefix}{clean}"
```
