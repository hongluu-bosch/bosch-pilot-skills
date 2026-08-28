# Input Format Reference

> **This file is the only fixed contract for Phase 1 input.** Every
> record in the list Phase 1 consumes — produced by an agent-written
> one-off extractor at `.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py`
> emitting `.DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json` — must match the
> schema below verbatim. *How* the JSON gets produced is dynamic and
> per-questionnaire (see [`excel-ingestion.md`](excel-ingestion.md));
> *what* the JSON looks like is fixed here.
>
> Read this file before writing any extractor, before hand-editing any
> `inputs/<...>_did.json`, and before debugging mismatched downstream
> output.
>
> Phase 1 accepts `*_did.json` only — the skill carries no built-in
> workbook parser, so every questionnaire flows through an
> agent-written one-off extractor.

Full specification of the per-DID record consumed by Phase 1, plus
reference examples of the FSCS text views (`FSCS_22.txt` /
`FSCS_2E.txt`) emitted by the generator.

## DID Definition Schema

```json
{
  "did_hex": "string - Hex identifier (e.g., '0x0101')",
  "did_name_en": "string - English name (spaces allowed; stripped when used in file/macro/function names)",
  "did_name_zh": "string - Chinese name (optional)",
  "cvt": "string - CVT status (U/C/T)",
  "supported_by_ecu": "string - Y/N flag",
  "rw_state": "string - R/W/RW",
  "size_bytes": "string - Size in bytes",
  "data_type": "string - enum/numeric/string/raw",
  "storage_pos": "string - EEPROM/RAM",
  "access": {
    "service_22": {
      "application": {
        "default": "string - Y/N",
        "extended": "string - Y/N"
      },
      "security": {
        "level0": "string - Y/N",
        "level1": "string - Y/N"
      }
    },
    "service_2e": { /* Same structure as service_22 */ }
  }
}
```

## Full JSON Input Example

```json
[
  {
    "did_hex": "0x0101",
    "did_name_en": "VariantCoding",
    "did_name_zh": "车辆配置码",
    "cvt": "U",
    "supported_by_ecu": "Y",
    "rw_state": "RW",
    "size_bytes": "16",
    "data_type": "enum",
    "storage_pos": "EEPROM",
    "access": {
      "service_22": {
        "application": {
          "default": "N",
          "programming": "N",
          "extended": "Y"
        },
        "boot": {
          "default": "N",
          "programming": "N",
          "extended": "N"
        },
        "security": {
          "level0": "Y",
          "level1": "Y",
          "level_fbl": "N"
        }
      },
      "service_2e": {
        "application": {
          "default": "N",
          "programming": "N",
          "extended": "Y"
        },
        "boot": {
          "default": "N",
          "programming": "N",
          "extended": "N"
        },
        "security": {
          "level0": "N",
          "level1": "Y",
          "level_fbl": "N"
        }
      }
    },
    "sub_fields": [
      {
        "byte": "0",
        "bit": "All",
        "name_en": "Project Name",
        "name_zh": "项目代号",
        "range_min_phy": "0x00",
        "range_max_phy": "0xFF",
        "unit": "null",
        "method_en": "0x00=AY5-TM Small Caliper\n0x01=AY5-TM Large Caliper\n0x02=TBD",
        "method_zh": "0x00=AY5-TM 小卡钳\n0x01=AY5-TM 大卡钳\n0x02=TBD",
        "default_value_phy": "null"
      },
      {
        "byte": "1",
        "bit": "0-1",
        "name_en": "Booster Type",
        "name_zh": "助力器类型",
        "range_min_phy": "0x0",
        "range_max_phy": "0x3",
        "unit": "null",
        "method_en": "0x0=vacuum booster\n0x1=Ebooster\n0x2-0x3=reserved",
        "method_zh": "0x0=真空助力器\n0x1=电子助力器\n0x2-0x3=保留",
        "default_value_phy": "null"
      }
    ]
  }
]
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `did_hex` | string | 十六进制标识符 (如 "0x0101") |
| `did_name_en` | string | 英文名称（允许空格，生成文件名/宏名/函数名时会自动去除） |
| `did_name_zh` | string | 中文名称（可选） |
| `cvt` | string | CVT 状态 (U/C/T) |
| `supported_by_ecu` | string | ECU 支持标志 (Y/N) |
| `rw_state` | string | 读写状态 (R/W/RW) |
| `size_bytes` | string | 字节大小 |
| `data_type` | string | 数据类型 (enum/numeric/string/raw) |
| `storage_pos` | string | 存储位置 (EEPROM / RAM / ROM；`NVM` 作为 `EEPROM` 的同义词被接受) |
| `access` | object | 服务访问配置 |
| `sub_fields` | array | 子字段定义数组 |

### sub_fields 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `byte` | string | 字节位置 |
| `bit` | string | 位范围 (如 "0-1", "All") |
| `name_en` | string | 子字段英文名称 |
| `name_zh` | string | 子字段中文名称 |
| `range_min_phy` | string | 物理最小值 |
| `range_max_phy` | string | 物理最大值 |
| `unit` | string | 单位 |
| `method_en` | string | 枚举值定义（英文） |
| `method_zh` | string | 枚举值定义（中文） |
| `default_value_phy` | string | 默认值 |

## Storage-Position Values (`storage_pos`)

Three canonical storage kinds + two aliases, and three distinct C-skeleton flavors:

| Input value | Canonical form in `fscs.json` | NVM item? | PDM entry? | Phase 3 C skeleton | Typical use |
|---|---|---|---|---|---|
| `EEPROM` | `EEPROM` | yes (`NVM_ID_DCOM_<Name>`) | yes | Full body: `DCOM_ReadDataByNVMId` / `DCOM_WriteDataByNVMId` | Non-volatile, writable via UDS 0x2E. |
| `NVM` *(alias → `EEPROM`)* | `EEPROM` | yes | yes | same as EEPROM | Bosch DCOM synonym; collapsed on input so downstream only sees `EEPROM`. |
| `RAM` | `RAM` | no (empty string) | no | TODO skeleton, commented `(RAM storage)` + `Implement RAM-backed …` | Volatile runtime state. |
| `ROM` | `ROM` | no (empty string) | no | TODO skeleton, commented `(ROM/Flash storage)` + `Implement ROM/Flash-backed …` | Read-only flash constants — e.g. `systemSupplierECUSoftwareVersion`. ECU rejects any UDS 0x2E against this DID regardless of `access`. |
| `Flash` *(alias → `ROM`)* | `ROM` | no | no | same as ROM | Customer inputs sometimes spell flash-constant storage `"Flash"`; canonicalised to `ROM`. |

Case-insensitive on input — `"eeprom"`, `"nvm"`, `"Ram"`, `"flash"`, `"ROM"` all normalise. Anything outside this set (e.g. `"OTP"`, `"HSM"`) fails validation with a clear message pointing at the offending record — on purpose, so genuine typos don't silently degrade.

**Phase 2 (ARXML) is storage-agnostic** — every non-deselected DID produces an ECUC container regardless of `storage_position`. **Phase 3 (C code) branches on the canonical value**: EEPROM gets the full NvM-backed body, RAM gets a TODO skeleton for agent fill-in, and **ROM/Flash DIDs (v2.4.0+) are auto-generated** — the generator parses the FSCS `behavior` text for a `HardCode:` block and emits the `#define` ladder + `Data[i] = C_DID_..._UB;` copy body automatically.

## HardCode Behavior Format (ROM / Flash DIDs)

> **When to use this.** Your DID's `storage_pos` is `ROM` (or `Flash`) and you want Phase 3 to **automatically generate** the per-byte constant header and the matching read function body, instead of leaving a `TODO(agent)` stub.

### Standard format

The `service_22_behavior` field (in `fscs_edit.xlsx`) must contain a `HardCode:` header followed by one line per output byte:

```text
HardCode:
C_DID_<DidName>_Byte0_UB = 0xXX
C_DID_<DidName>_Byte1_UB = 0xXX
...
C_DID_<DidName>_Byte<N-1>_UB = 0xXX
```

| Element | Rule |
|---------|------|
| Header | Must start with `HardCode:` (case-insensitive). |
| `<DidName>` | The PascalCase DID name (spaces removed), matching the `did_name_en` field. Example: `SystemSupplierIdentifierDataIdentifier`. |
| `<N>` | Zero-based byte index, contiguous from `0` to `size_bytes - 1`. |
| `0x<HH>` | Two-digit upper-case hex with `0x` prefix. |

### Complete example (0xF18A, 9 bytes)

```text
HardCode:
C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB = 0x42
C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB = 0x6F
C_DID_SystemSupplierIdentifierDataIdentifier_Byte2_UB = 0x73
C_DID_SystemSupplierIdentifierDataIdentifier_Byte3_UB = 0x63
C_DID_SystemSupplierIdentifierDataIdentifier_Byte4_UB = 0x68
C_DID_SystemSupplierIdentifierDataIdentifier_Byte5_UB = 0x30
C_DID_SystemSupplierIdentifierDataIdentifier_Byte6_UB = 0x30
C_DID_SystemSupplierIdentifierDataIdentifier_Byte7_UB = 0x30
C_DID_SystemSupplierIdentifierDataIdentifier_Byte8_UB = 0x30
```

### Parsing contract

The generator is intentionally permissive (whitespace-tolerant, case-insensitive on the `HardCode:` header) so minor formatting variations in Excel cells don't break the pipeline:

| Scenario | Generator behavior |
|----------|-------------------|
| **Complete match** — every byte found | All `#define`s use parsed hex values; `.c` body uses macros. |
| **Partial match** — some bytes missing | Parsed values used where available; missing bytes fall back to `0x00u` with `/* TODO(agent): verify */`. |
| **No match** — no `HardCode:` or no matching lines | Every byte falls back to `0x00u`; Agent must review and fill. |

### ASCII string shorthand

When the behavior describes an ASCII string (e.g. `"Bosch"`), write the hex values explicitly — the parser does **not** perform ASCII conversion:

```text
HardCode:
C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB = 0x42  /* B */
C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB = 0x6F  /* o */
C_DID_SystemSupplierIdentifierDataIdentifier_Byte2_UB = 0x73  /* s */
C_DID_SystemSupplierIdentifierDataIdentifier_Byte3_UB = 0x63  /* c */
C_DID_SystemSupplierIdentifierDataIdentifier_Byte4_UB = 0x68  /* h */
```

### What the generator produces

Given a valid HardCode block, Phase 3 emits **two files**:

1. **Header** (`api/RBAPLCUST_RDBI_<DidName>.h`):
   ```c
   #define C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB    0x42u
   #define C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB    0x6Fu
   /* ... */
   ```

2. **C body** (`src/Common/RBAPLCUST_RDBI_<DidName>.c`):
   ```c
   #include "RBAPLCUST_RDBI_SystemSupplierIdentifierDataIdentifier.h"
   /* ... */
   Data[0] = C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB;
   Data[1] = C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB;
   /* ... */
   retVal = E_OK;
   ```

Both files use **skip-if-exists** — once created, they are never overwritten, so hand-tuned values are safe across re-runs.

## `fscs.json` Selection Flag (`used_22` / `used_2e`)

Neither the diagnostic-questionnaire `.xlsx` nor the legacy input JSON above carries `used_XX` or `behavior` fields — every DID starts as selected, and Phase 1 seeds side-specific behavior templates. The internal fields are introduced by Phase 1 when it builds `outputs/fscs/fscs.json`. In `outputs/fscs/fscs_edit.xlsx`, operators use one global `used_flag` column to decide whether the DID participates in Phase 2 / Phase 3, `service_22_support` / `service_2e_support` to decide which services are supported, and `service_22_behavior` / `service_2e_behavior` to edit the FSCS Behavior text.

```json
{
  "did_hex": "0x0101",
  "service_22": { "supported": true, "used": true,  "sessions": [...], "security_levels": [...], "behavior": "Read from NVM item: ..." },
  "service_2e": { "supported": true, "used": false, "sessions": [...], "security_levels": [...], "behavior": "Write to NVM item: ..." }
}
```

- `supported` (service support, initially derived from `rw_state`) — editable in the CSV through `service_22_support` / `service_2e_support`.
- `used` (selection, default `true`) — operator-owned through CSV `used_flag`. `fscs.json` always keeps every DID; `FSCS_22.txt` / `FSCS_2E.txt` / ARXML / generated C only include DIDs where **both** flags are `true` for that service.
- `behavior` (side-specific FSCS implementation hint) — generated by Phase 1 from `storage_position` and editable through `service_22_behavior` / `service_2e_behavior`. CSV import renders it after `Value Range` in the matching `FSCS_*.txt`.
- Re-running `--phase fscs` after an input change preserves previously-set `used` flags and behavior text for DIDs that still exist; new DIDs default to `used=true` and storage-derived behavior templates.
- Legacy `fscs.json` files without a `used` field load fine (Pydantic applies the `true` default).

## FSCS Output Format Examples

> **Note:** `FSCS_22.txt` and `FSCS_2E.txt` are **read-only human-review views** regenerated from `outputs/fscs/fscs.json` by `python scripts/pipeline.py --phase xlsx-import`. Do not hand-edit; edit `outputs/fscs/fscs_edit.xlsx` or re-run Phase 1 after updating inputs.

### Read-only DID (Service 0x22 only)

**Input** (standard-compliant read-only configuration):
```json
{
  "did_hex": "0x0200",
  "did_name_en": "ReprogrammingCounter",
  "rw_state": "R",
  "access": {
    "service_22": {
      "application": { "default": "Y", "extended": "Y" },
      "security":    { "level0": "Y", "level1": "N" }
    }
  }
}
```

**`FSCS_22.txt` output:**
```
================================================================================
Identifier $0200h - ReprogrammingCounter

Description
This identifier returns the ReprogrammingCounter

Availability
Supported in the following diagnostic sessions:
- defaultSession
- extendedDiagnosticSession

Security Level:
		L0 (means no security access assurance)

Request Message:
Byte 1		$22 = Request Service Id "ReadDataByIdentifier"
Byte 2-3	$0200 = ReprogrammingCounter

Positive Response Message:
Byte 1		$62 = Response Service Id "ReadDataByIdentifier"
Byte 2-3	$0200 = ReprogrammingCounter
Byte 4-5		Data Record

Data Type:		Linear
Storage Position:	EEPROM
Size:			2 bytes
R/W State:		R
NVM Item:		NVM_ID_DCOM_ReprogrammingCounter
Value Range:		

================================================================================
```

✓ **Compliant**: supports defaultSession + extendedDiagnosticSession, uses L0.

### RW DID (Service 0x2E)

**Input** (standard-compliant write configuration):
```json
{
  "did_hex": "0x0101",
  "did_name_en": "VariantCoding",
  "rw_state": "RW",
  "access": {
    "service_2e": {
      "application": { "default": "N", "extended": "Y" },
      "security":    { "level0": "N", "level1": "Y" }
    }
  }
}
```

**`FSCS_2E.txt` output:**
```
================================================================================
Identifier $0101h - Variant Coding

Description
This identifier write the Variant Coding

Availability
Supported in the following diagnostic sessions:
- extendedDiagnosticSession

Security Level:
		L1

Request Message:
Byte 1		$2E = Request Service Id "WriteDataByIdentifier"
Byte 2-3	$0101 = Variant Coding
Byte 4-19		Data Record

Positive Response Message:
Byte 1		$6E = Response Service Id "WriteDataByIdentifier"
Byte 2-3	$0101 = Variant Coding

Data Type:		enum
Storage Position:	EEPROM
Size:			16 bytes
R/W State:		RW
NVM Item:		NVM_ID_DCOM_VariantCoding
Value Range:		

================================================================================
```

✓ **Compliant**: only extendedDiagnosticSession, uses L1.

**Note:** RW DIDs appear in **both** `FSCS_22.txt` and `FSCS_2E.txt`.
