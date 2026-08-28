# DiagComm parameter types, ranges, defaults (project-invariant)

Cross-reference between **user-input space** (what the user types
into `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'`) and
**arxml literal space** (what gets written to the ARXML). See
[`transforms.md`](./transforms.md) for the conversion functions and
[`excel_format.md`](./excel_format.md) for the Excel-side data
validation specs.

**Legend:**
- **REQ** — required cell on the Excel sheet (red-highlighted until filled).
- **DEF** — defaulted: leaving the Value cell blank uses the default
  in the table below.
- **PR** — defaulted *and* flagged "verify carefully" the first time.

The default values listed below are also visible in the `Default`
column of `inputs/DiagComm.xlsx` itself, and are encoded in
`assets/DiagComm_schema.json`. The user can preview live ARXML
defaults via `python <skill>/scripts/pipeline.py reseed --from-arxml`, which
writes a `outputs/reseed_suggestion.json` for the user to transcribe
back into Excel by hand. The skill never overwrites the user's xlsx.

Tables below mirror `scripts/schema.py::FIELD_DEFS`. After any edit,
run `python <skill>/scripts/pipeline.py gen-schema` to refresh
`assets/DiagComm_schema.json`, **and** rerun
`python <skill>/scripts/build_inputs_template.py` to refresh the Excel
template baseline (`assets/inputs_template.xlsx`).

---

## 1. Time parameters (ms in / s in arxml)

All time parameters are collected in **milliseconds**. The
`ms_to_seconds` transform divides by 1000 before writing.

| Parameter | Type | Default | Min | Max | arxml type | arxml range | Unit | Semantic check |
|---|---|---|---|---|---|---|---|---|
| `N_As` | float ms | 25 | 0 | — | ECUC-FLOAT | 0 .. 10 | s | — |
| `N_Ar` | float ms | 25 | 0 | — | ECUC-FLOAT | 0 .. 10 | s | — |
| `N_Bs` | float ms | 75 | 0 | — | ECUC-FLOAT | 0 .. 10 | s | — |
| `N_Br` | float ms | 25 | 0 | — | ECUC-FLOAT | 0 .. 10 | s | — |
| `N_Cs` | float ms | 100 | 0 | — | ECUC-FLOAT | 0 .. 10 | s | — |
| `N_Cr` | float ms | 150 | 0 | — | ECUC-FLOAT | 0 .. 10 | s | — |
| `P2_Max` | float ms | 50 | 0 | — | ECUC-FLOAT | 0 .. 65.535 | s | written only to `*Max`, `*Adjust` untouched |
| `P2_Star_Max` | float ms | 5000 | 0 | — | ECUC-FLOAT | 0 .. 6553.5 | s | same |
| `STmin` | float ms | 0 | 0 | **127** | ECUC-FLOAT | 0 .. 0.127 | s | **enforced**: >127 ms is a hard error (ISO 15765-2 cap) |

All time parameters are **DEF** (defaulted; leave the cell blank for the value above).

## 2. Integer / byte parameters

| Parameter | Type | Default | Min | Max | arxml type | arxml range | Unit | Semantic check |
|---|---|---|---|---|---|---|---|---|
| `BS` | int | 0 | 0 | 255 | ECUC-INTEGER | 0 .. 255 | frames | — |
| `PaddingByte` | hex *(accepts 0..255 decimal too)* | `"0x00"` | 0 | 255 | ECUC-INTEGER | 0 .. 255 | byte | **enforced**: out-of-range rejected |
| `NRC78_Times` | int | 10 | 0 | 255 | ECUC-INTEGER | 0 .. 255 | count | **enforced**: out-of-range rejected |

All three are **DEF**. `PaddingByte` transform is `hex_to_decimal`:
the user enters `0xFF` (preferred) or `255` in Excel, and the loader
writes a decimal literal to arxml. The reverse transform (used by
`reseed --from-arxml` to suggest live-ARXML values) renders
zero-padded two-digit hex (e.g. `0` → `"0x00"`). `NRC78_Times` uses
plain `int_str` — the user enters a decimal count (0..255) and it is
written verbatim.

## 3. Boolean parameters

| Parameter | Type | Default | arxml type | arxml accepts | Transform |
|---|---|---|---|---|---|
| `StrictDlcCheck` | bool | `false` | ECUC-BOOLEAN | `true` \| `false` | `bool_str` |

**DEF**. Reverse is a simple `"true"/"false"` → `bool` parse. The
Excel cell uses a `TRUE / FALSE` dropdown.

## 4. Enum parameters

| Parameter | Allowed (user) | Default | arxml type | arxml accepts | Transform | Fill mode |
|---|---|---|---|---|---|---|
| `CAN_ID_Format` | `11bit` \| `29bit` | `11bit` | ECUC-ENUM | `STANDARD` \| `EXTENDED` | `can_id_type` | DEF |
| `Addressing_Method` | `Normal` \| `NormalFixed` \| `Extended` | `Normal` | ECUC-ENUM | `CANTP_STANDARD` \| `CANTP_NORMALFIXED` \| `CANTP_EXTENDED` \| `CANTP_MIXED` | `addressing_format` | DEF |
| `CAN_DLC.rx_frame_type` | `ClassicCAN` \| `CANFD` | (none) | ECUC-ENUM (`CanIfRxPduCanIdType`) | `STANDARD_CAN` \| `STANDARD_FD_CAN` | `canfd_pdu_id_type` | **REQ** |
| `CAN_DLC.tx_frame_type` | `ClassicCAN` \| `CANFD` | (none) | ECUC-ENUM (`CanIfTxPduCanIdType`) | `STANDARD_CAN` \| `STANDARD_FD_CAN` | `canfd_pdu_id_type` | **REQ** |
| `CAN_DLC.rx_dl` | `8` \| `64` | (none) | ECUC-INTEGER | uint32 (8 or 64) | `int_str` | **REQ** |
| `CAN_DLC.tx_dl` | `8` \| `64` | (none) | ECUC-INTEGER | uint32 (8 or 64) | `int_str` | **REQ** |

> `CAN_DLC.rx_frame_type` and `CAN_DLC.tx_frame_type` are collected
> independently so asymmetric setups are expressible (e.g. RX accepts
> both Classic CAN and CAN-FD, TX sends only CAN-FD). The global
> `CanTpFlexibleDataRateSupport` boolean is **derived** by the pipeline
> as `rx_frame_type == CANFD OR tx_frame_type == CANFD` and has no
> user-facing field (see `reference/landing_spots.md` §3).
>
> Semantic check (enforced): when `{rx,tx}_frame_type=ClassicCAN`,
> the matching `{rx,tx}_dl` MUST be 8. Validate rejects the
> combination; apply exits with code 2.

## 5. CAN IDs (hex strings)

| Parameter | Type | Default (example only) | arxml type | arxml range per format | Transform | Fill mode |
|---|---|---|---|---|---|---|
| `CAN_Functional_Request_ID` | hex | (none) | ECUC-INTEGER | `11bit` → 0..0x7FF; `29bit` → 0..0x1FFFFFFF | `hex_to_decimal` | **REQ** |
| `CAN_Physical_Request_ID` | hex | (none) | ECUC-INTEGER | same | `hex_to_decimal` | **REQ** |
| `CAN_Response_ID` | hex | (none) | ECUC-INTEGER | same | `hex_to_decimal` | **REQ** |

**Semantic check (enforced)**: each ID is cross-checked against
`CAN_ID_Format` during `validate` and at the start of `apply`; an
out-of-range value is a hard error (exit code 2). All three are
**REQ** (no defaults — the OBD-II legislated IDs `0x7DF / 0x7E0 / 0x7E8`
are almost never right for a custom diagnostic project, so the user
must type the real values explicitly).

## 6. Path-selector parameters

These two fields live in `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'`
but are **never** patched into any arxml — they only decide which
arxml files the pipeline reads and writes. Both have no `PARAM_MAP`
entry.

| Parameter | Type | Default | Effect |
|---|---|---|---|
| `project.product_type` | enum `DPB\|ESP\|IPB\|RBU` | (none) | Copied into `config.project.product_type` at run-time to fill `{product_type}` in `paths.can_pt_file`. Must match an `RBAPLCust/cfg/<PT>/` folder actually shipped in the project. **REQ**. To preview the current ARXML's product_type, run `python <skill>/scripts/pipeline.py reseed --from-arxml` and read workspace `outputs/reseed_suggestion.json`; transcribe the value into Excel by hand. |
| `parameters.CAN_Channel` | int | `0` | Copied into `config.options.can_channel` to fill `{can_channel}` in `can_pt_file`. Only channels for which the matching arxml exists are usable. **DEF** (`0` covers most projects). |

---

## 7. Summary required / defaulted matrix

| Group | Parameters |
|---|---|
| **REQ** (9) | `project.name`, `project.product_type`, `parameters.CAN_DLC.rx_frame_type` / `tx_frame_type` / `rx_dl` / `tx_dl`, `parameters.CAN_Functional_Request_ID` / `CAN_Physical_Request_ID` / `CAN_Response_ID` |
| **DEF** (16) | `parameters.CAN_Channel`, `parameters.CAN_ID_Format`, `parameters.Addressing_Method`, `parameters.PaddingByte`, `parameters.StrictDlcCheck`, `parameters.N_As / N_Ar / N_Bs / N_Br / N_Cs / N_Cr`, `parameters.P2_Max`, `parameters.P2_Star_Max`, `parameters.BS`, `parameters.STmin`, `parameters.NRC78_Times` |

REQ fields are red-highlighted in Excel until the user fills the
Value cell; DEF fields fall back to the schema default at coercion
time when the cell is left blank.

**Total:** 23 user-facing parameters (in Sheet 1) + 2 project
identity fields (`project.name`, `project.product_type`) +
1 derived internal (`CAN_DLC.flexible_fd`, never surfaced).
