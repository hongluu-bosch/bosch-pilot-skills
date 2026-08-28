# Phase 1 — FSCS

Phase 1 turns a diagnostic questionnaire into the authoritative
`outputs/fscs/fscs.json` and a human-editable `fscs_edit.xlsx`.

## Input

Place the diagnostic questionnaire under `inputs/`. The built-in Excel
parser handles common `$19` / `19service` / `snapshot` / `freezeframe`
sheet layouts.

The parser auto-detects columns such as:

- `DTCSnapshotRecordNumber` / `DTCExtendedDataRecordNumber`
- `DID number` / `DID`
- `DID Description(E)` / `DID含义(英文)`
- `Length (Bytes)` / `Length`
- `Byte`, `Bit`, `sub Data Name(E)`
- `Storage Pos.`, `Access`

Rows whose cells are formatted with **strikethrough** (`font.strike`)
are treated as deleted and are ignored.

## Outputs

| File | Role |
|---|---|
| `outputs/fscs/fscs.json` | Authoritative freeze-frame FSCS. |
| `outputs/fscs/fscs_edit.xlsx` | Operator edit table. |
| `outputs/fscs/FSCS_19.txt` | Human-readable 19-service FSCS (templates A + B). |
| `outputs/fscs/fscs_review_report.txt` | Advisory review report. |

## FSCS JSON schema

```json
{
  "service": "19",
  "subfunction": "0x04",
  "dtc_snapshot_record_numbers": ["0x01", "0xFF"],
  "snapshot_record_number_descriptions": {
    "0x01": "The 1st Snapshot record",
    "0x02": "The last Snapshot record",
    "0xFF": "All snapshot record"
  },
  "freeze_frame_class": "DemFreezeFrameClass_RBAPLCUST",
  "freeze_frame_rec_num_class": "DemFreezeFrameRecNumClass_RBAPLCUST",
  "type_of_freeze_frame_record_numeration": "FF_RECNUM_CONFIGURED",
  "product_types": ["Common"],
  "dids": [
    {
      "did_hex": "0x1100",
      "did_name_en": "Wheel Speed and vehicle speed at Last Fault Code Set",
      "did_name_zh": "轮速及车速",
      "size_bytes": 10,
      "read_fnc": "RBAPLCUST_1100_WheelSpeedAndVehicleSpeed_ReadData",
      "product_type": "Common",
      "used": true,
      "sub_fields": [
        {
          "byte": "1",
          "bit": "All",
          "name_en": "Wheel Speed Front Left",
          "name_zh": "左前轮轮速",
          "range_min": "0",
          "range_max": "240",
          "unit": "km/h",
          "resolution": "0.05625",
          "offset": "0",
          "method_en": "Resolution=0.05625 Offset=0",
          "method_zh": "分辨率=0.05625 偏移量=0"
        }
      ]
    }
  ]
}
```

### Snapshot record numbers

`dtc_snapshot_record_numbers` is extracted from the questionnaire when the
parser can locate a `DTCSnapshotRecordNumber` / `Snapshot Record Number` /
`Record Number` / `快照记录号` column or label.  If the questionnaire does not
contain this information, the default `["0x01", "0xFF"]` is used.

The operator may edit the value later in `fscs_edit.xlsx` (`record_number`
column) and re-run `--phase xlsx-import`.

### Structured resolution / offset

Each `sub_fields` entry now contains the parsed `resolution` and `offset`
values extracted from `method_en` (e.g. `Resolution=0.05625 Offset=0`).
These fields are editable in `fscs_edit.xlsx` and are used when rendering the
`FSCS_19.txt` template.

### Implementation input column

`fscs_edit.xlsx::FSCS_19` now carries one optional implementation-input
column per DID:

- `impl_notes`

This column is consumed by Phase 3 (snapshot C generation / later fill-in).

#### `impl_notes`

Free-text implementation intent. The agent reads `impl_notes`, parses the
described byte/bit/condition/scaling requirements, searches the current project
for supporting signal / getter / enum / qualifier evidence, and then decides
whether to generate a real implementation, a scaffold, or keep the TODO stub.

The notes remain free-form, but the agent is more reliable when the text uses
simple, explicit patterns such as:

- `Data[0] = ...`
- `if ... then Data[1] = ... else Data[1] = 0xFF`
- `bit0=...`, `bit1=...`
- `byte0 uses ...; byte1 uses ...`
- `low nibble`, `high nibble`
- `*0.1`, `resolution=...`, `offset=...`

Examples of useful `impl_notes` content:

- qualifier validity conditions
- invalid fill policy
- bit / nibble packing rules
- special scaling / ordering constraints

If `impl_notes` are still insufficient to infer a concrete implementation,
Phase 3 must keep the `TODO(agent)` stub (or emit a higher-quality scaffold)
and report the DID as skipped for fill due to insufficient evidence.

## `FSCS_19.txt` output format

`FSCS_19.txt` contains both templates required by the project:

### Template A — Positive Response Message

```
Positive Response Message:
Byte 1       $59 = Response Service Id "ReadDTCInformation"

Byte 2       subFunction = [reportType]
             $04 = reportDTCSnapshotRecordByDTCNumber

Byte 3       DTCHighByte
Byte 4       DTCMiddleByte
Byte 5       DTCLowByte
Byte 6       statusOfDTC


Byte 7       DTCSnapshotRecordNumber
             $01: The 1st Snapshot record
             $FF: All snapshot record

Byte 8       DTCSnapshotRecordNumberOfIdentifiers = 2

DTCSnapshotRecord
Byte 9       DataIdentifier#1: Vehicle Speed (MSB) = $31
Byte 10      DataIdentifier#1: Vehicle Speed (LSB) = $00
Byte 11-12   Vehicle Speed Value
             Resolution: 0.05625km/h
             Range: 0 ~ 296km/h
```

- Bytes 1–6 are fixed.
- Byte 7 lists the configured snapshot record numbers.
- Byte 8 is the count of effective (`used=True`) DIDs.
- Bytes 9 onward list each DID: MSB/LSB identifier lines, followed by the
  value byte(s), resolution and range (when available), or size + read
  function when sub-field data is missing.

### Template B — Available Snapshot Data

```
Available Snapshot Data

Function interfaces:RBAPLCUST_VehicleSpeed_ReadData will be used for snapshot data record configuration
Function interfaces:RBAPLCUST_BatteryVoltage_ReadData will be used for snapshot data record configuration
```

Only DIDs with `used=True` are listed.

## `DTCSnapshotRecordNumberOfIdentifiers`

Computed from the number of effective DIDs in the freeze-frame class.
