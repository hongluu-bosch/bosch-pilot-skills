# DiagComm landing-spot catalog (project-invariant)

Authoritative description of **where each DiagComm parameter lands**
in the ARXML tree. Human-readable companion to
`scripts/mapping.py::PARAM_MAP`. Locators depend only on AUTOSAR ECUC
definitions and Bosch CusDiag naming — they are project-invariant.

For per-project values (absolute paths, observed hit counts):

```bash
python <skill>/scripts/pipeline.py landing-report
# -> outputs/landing_report.txt
```

If the live report disagrees with the tables below, the project
either ships non-standard SHORT-NAMEs (extend `PARAM_MAP`) or
relocated a file (override the affected key under
`inputs/DiagComm.xlsx::Sheet 'Paths & Options'::paths.*`).

---

## 1. File aliases

Every locator targets a file by **alias**; the alias is resolved to
a concrete path at run-time using `inputs/DiagComm.xlsx::Sheet
'Paths & Options'::paths.*` plus the two user-selected path
selectors under `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'`
(`project.product_type` → `config.project.product_type`,
`parameters.CAN_Channel` → `config.options.can_channel`; both
copied by `_inject_runtime_options`). Aliases used by the catalog:

| Alias | Purpose | Relative path template (under resolved `dcom_root`) |
|---|---|---|
| `cantp_common` | Customer CAN-TP EcucValues (timers, flow-control, addressing) | `RBAPLCust/cfg/Common/CanTp_CusDiag_EcucValues.arxml` |
| `cantp_feature_file` | CAN-TP feature flags (FD flag, padding byte, strict DLC) | `Cubas/cfg/CanTp_Feature_EcucValues.arxml` |
| `dcm_feature_file` | Dcm feature flags (NRC 0x78 max count, declined-request flag) | `Cubas/cfg/Dcm_Feature_EcucValues.arxml` |
| `dcm_services_common` | Dcm session timing (P2 / P2*) — `*Max` only | `RBAPLCust/cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml` |
| `dcm_common` | Dcm protocol row — **reference only, never written** (`*Adjust` lives here) | `RBAPLCust/cfg/Common/Dcm_CusDiag_Can_EcucValues.arxml` |
| `can_pt_file` | Per-product / per-channel CAN layer (IDs, Pdu, CanIdType) | `RBAPLCust/cfg/{product_type}/Can{can_channel}_CusDiag_EcucValues_{product_type}.arxml` |

Both placeholders come from `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'`:
`{product_type}` ∈ `DPB | ESP | IPB | RBU` (REQ — no default);
`{can_channel}` = the `parameters.CAN_Channel` integer (schema default `0`).

---

## 2. CanTp timers & flow-control (file alias: `cantp_common`)

Common locator rule: ancestor `CanTpTxNSdu` (TX) or `CanTpRxNSdu`
(RX), DEFINITION-REF suffix = timer name. All timers use forward
transform `ms_to_seconds`; `BS` uses `int_str`; `Addressing_Method`
uses `addressing_format`.

| Parameter | Ancestor SHORT-NAME | DEFINITION-REF suffix(es) | Transform | Hits per channel |
|---|---|---|---|---|
| `N_As` | `CanTpTxNSdu` | `CanTpNas` | `ms_to_seconds` | 1 (CusDiagXMT) |
| `N_Ar` | `CanTpRxNSdu` | `CanTpNar` | `ms_to_seconds` | 2 (CusDiagPhy + CusDiagFunc) |
| `N_Bs` | `CanTpTxNSdu` | `CanTpNbs` | `ms_to_seconds` | 1 |
| `N_Br` | `CanTpRxNSdu` | `CanTpNbr` | `ms_to_seconds` | 2 |
| `N_Cs` | `CanTpTxNSdu` | `CanTpNcs` | `ms_to_seconds` | 1 |
| `N_Cr` | `CanTpRxNSdu` | `CanTpNcr` | `ms_to_seconds` | 2 |
| `BS` | `CanTpRxNSdu` | `CanTpBs` | `int_str` | 2 |
| `STmin` | `CanTpRxNSdu` | `CanTpSTmin` \| `CanTpStMin` | `ms_to_seconds` | 2 *(optional)* |
| `Addressing_Method` | — | `CanTpAddressingFormat` \| `CanTpRxAddressingFormat` \| `CanTpTxAddressingFormat` | `addressing_format` | 3 *(optional)* |

> `STmin` uses `CanTpStMin` on older BSW deliveries and `CanTpSTmin`
> on newer ones — both spellings are accepted. The locator is marked
> optional because some projects omit the parameter entirely.
> `Addressing_Method` is optional for the same reason: projects using
> only `CANTP_STANDARD` sometimes leave it defaulted.

**Section total: 9 parameters, expected ~16 hits/channel on a typical
3-Pdu CusDiag stack.**

---

## 3. CanTp feature flags (file alias: `cantp_feature_file`)

Single container `CanTpGeneral`; each parameter has exactly one hit
across the file.

| Parameter | DEFINITION-REF suffix | Transform | Hits |
|---|---|---|---|
| `CAN_DLC.flexible_fd` *(derived)* | `CanTpFlexibleDataRateSupport` | `bool_str` | 1 |
| `PaddingByte` | `CanTpPaddingByte` | `hex_to_decimal` | 1 |
| `StrictDlcCheck` | `CanTpRbStrictDlcCheck` \| `CanTpStrictDlcCheck` | `bool_str` | 1 |

> `CAN_DLC.flexible_fd` is an **internal synthetic key** (no user-facing
> field). Computed at apply-time by
> `pipeline._inject_derived_values` as `rx_frame_type == CANFD OR
> tx_frame_type == CANFD`. The PARAM_MAP entry is flagged
> `derived=True` so the lazy-seed reverse walk skips it and the field
> never surfaces in `inputs/DiagComm.xlsx`.
>
> `StrictDlcCheck` lists two DEFINITION-REF variants; Bosch-customised
> stacks use `CanTpRbStrictDlcCheck`, vanilla AUTOSAR uses
> `CanTpStrictDlcCheck`. The locator accepts either — first match wins.

**Section total: 3 entries (2 user + 1 derived), 3 hits.**

---

## 4. Dcm session timing (file alias: `dcm_services_common`)

Each parameter lands on every `DcmDspSessionRow` (typically
`DEFAULT_SESSION`, `EXTENDED_DIAGNOSTIC_SESSION`,
`PROGRAMMING_SESSION`). The skill **only writes the `*Max` family**;
the `*Adjust` nodes in `dcm_common` are intentionally untouched.

| Parameter | DEFINITION-REF suffix | Transform | Typical hits |
|---|---|---|---|
| `P2_Max` | `DcmDspSessionP2ServerMax` | `ms_to_seconds` | 3 (one per session row) |
| `P2_Star_Max` | `DcmDspSessionP2StarServerMax` | `ms_to_seconds` | 3 |

**Section total: 2 parameters, ~6 hits per project.**

---

## 4b. Dcm feature flags (file alias: `dcm_feature_file`)

Single container `DcmDslDiagResp`; the locator is pinned via ancestor
SHORT-NAME so that unrelated containers sharing the `*RespPend` suffix
(if any are introduced later) cannot be accidentally rewritten.

| Parameter | Ancestor SHORT-NAME | DEFINITION-REF suffix | Transform | Hits |
|---|---|---|---|---|
| `NRC78_Times` | `DcmDslDiagResp` | `DcmDslDiagRespMaxNumRespPend` | `int_str` | 1 |

> Sibling bool `DcmDslDiagRespOnSecondDeclinedRequest` lives in the
> same container but is intentionally **not** managed by the skill.

**Section total: 1 parameter, 1 hit.**

---

## 5. CAN layer, per product/channel (file alias: `can_pt_file`)

This file is selected by `{product_type}` + `{can_channel}`. All
locators below target a single instance of this file.

### 5.1 Bit format & DLC (split RX / TX)

RX and TX are configured independently so projects can express
asymmetric setups (e.g. RX=Classic-or-FD + TX=FD-only). Each direction
has its own frame_type + DL pair; the ancestor SHORT-NAME prefix pins
the locator to the right Pdu chain.

| Parameter | Ancestor filter (prefix) | DEFINITION-REF suffix | Transform | Hits |
|---|---|---|---|---|
| `CAN_ID_Format` | — | `CanIdType` | `can_id_type` | 3 (CusDiagRCV, CusDiagRCVFunc, CusDiagXMT) |
| `CAN_DLC.rx_frame_type` | `CusDiagRCV` | `CanIfRxPduCanIdType` | `canfd_pdu_id_type` | 2 (CusDiagRCV + CusDiagRCVFunc) |
| `CAN_DLC.tx_frame_type` | `CusDiagXMT` | `CanIfTxPduCanIdType` | `canfd_pdu_id_type` | 1 |
| `CAN_DLC.rx_dl` | `CusDiagRCV` | `PduLength` | `int_str` | 6 (2 RX Pdu chains × 3 layers: CanTp2PduR / Npdu_CanIf2CanTp / PduR2DCM) |
| `CAN_DLC.tx_dl` | `CusDiagXMT` | `PduLength` | `int_str` | 3 (DCM2PduR / PduR2CanTp / Npdu_CanTp2CanIf) |

> The ancestor prefix `CusDiagRCV` covers both `CusDiagRCV*`
> (physical) and `CusDiagRCVFunc*` (functional) SHORT-NAMEs — the two
> RX Pdu chains share a single `rx_frame_type` / `rx_dl` setting by
> design. A single `STANDARD_CAN` vs `STANDARD_FD_CAN` literal is
> written to each direction (see `_canfd_pdu_id_type`). The global
> `CanTpFlexibleDataRateSupport` flag is handled in section 3 as a
> derived entry.
>
> Semantic check (enforced): when `{rx,tx}_frame_type=ClassicCAN` the
> matching `{rx,tx}_dl` MUST be 8. Validate rejects the combination
> and `apply` exits with code 2 rather than writing an invalid pair.

### 5.2 CAN IDs (6 total landing spots)

Each of the three user-visible IDs is written to **two** arxml nodes
(one on the hardware filter, one on the CanIf Pdu). The ancestor
SHORT-NAME disambiguates which traffic class the ID belongs to.

| Parameter | Ancestor SHORT-NAME | DEFINITION-REF suffix | Transform | Hits |
|---|---|---|---|---|
| `CAN_Functional_Request_ID` | `CusDiagRCVFunc` | `CanHwFilterCode` | `hex_to_decimal` | 1 |
| `CAN_Functional_Request_ID` | `CusDiagRCVFunc` | `CanIfRxPduCanId` | `hex_to_decimal` | 1 |
| `CAN_Physical_Request_ID` | `CusDiagRCV` | `CanHwFilterCode` | `hex_to_decimal` | 1 |
| `CAN_Physical_Request_ID` | `CusDiagRCV` | `CanIfRxPduCanId` | `hex_to_decimal` | 1 |
| `CAN_Response_ID` | `CusDiagXMT` | `CanIfTxPduCanId` | `hex_to_decimal` | 1 |
| `CAN_Response_ID` | `CusDiagXMT` | `CanHwFilterCode` | `hex_to_decimal` | 1 |

**All 6 are non-optional**: a missing hit is a hard warning in
`validate`, surfaced so the user can extend the mapping or check the
project shape.

**Section total: 7 user-facing parameters + the 6 CAN ID locators →
typically 21 hits per channel** (3 CanIdType + 2 RX id-type + 1 TX
id-type + 6 PduLength hits for RX + 3 for TX + 6 CAN ID spots).

---

## 6. Parameters NOT written to arxml

Both path selectors live in `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'` as the
single source of truth and never get patched into any arxml -- they
just pick which arxml files the pipeline touches.

| Parameter | Where it lives |
|---|---|
| `project.product_type` | `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'::project.product_type` (enum `DPB\|ESP\|IPB\|RBU`, **REQ**). Copied into `config.project.product_type` at run-time to fill `{product_type}` in `can_pt_file`. |
| `parameters.CAN_Channel` | `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'::parameters.CAN_Channel` (int, default `0`). Copied into `config.options.can_channel` at run-time to fill `{can_channel}` in `can_pt_file`. |

---

## 7. Grand totals (reference project shape)

On a standard Bosch DPB / ESP / IPB / RBU delivery with one CAN
channel and the 3 default Dcm sessions, the skill resolves roughly:

- 9 parameters in `cantp_common` → ~16 hits
- 2 user parameters + 1 derived entry in `cantp_feature_file` → 3 hits
- 2 parameters in `dcm_services_common` → ~6 hits
- 1 parameter  in `dcm_feature_file`  → 1 hit
- 8 parameters in `can_pt_file` → ~21 hits
- **Total ≈ 47 landing spots** across 23 user-facing parameters
  (counting each `CAN_DLC.*` sub-field separately) + 1 derived
  internal key for the FD flag; 26 locators in `PARAM_MAP`.

Exact per-project numbers can be confirmed with `landing-report`.

---

## 8. How to extend the catalog

Adding a new parameter involves three synchronised edits:

1. **`assets/DiagComm.txt`** — add the user-facing name (one per line).
2. **`scripts/schema.py::FIELD_DEFS`** — add type / default / unit /
   min / max / `prompt_required`.
3. **`scripts/mapping.yaml`** — add one entry per arxml landing spot
   (file alias + locator + transform). This file is the single source
   of truth for `PARAM_MAP` and is loaded by `scripts/mapping.py` at
   import time.

Then regenerate and verify:

```bash
python <skill>/scripts/pipeline.py gen-schema
python <skill>/scripts/pipeline.py export-catalog       # refresh the auto-generated
                                                 # table in section 9 below
python <skill>/scripts/pipeline.py landing-report
python <skill>/scripts/pipeline.py validate
```

The drift detectors (`gen-schema --check`, `export-catalog --check`)
will fail CI if `DiagComm.txt` or `mapping.yaml` go out of sync with
their downstream artifacts.

Update this document (`reference/landing_spots.md`) and
`reference/parameter_types.md` to record the new locators.

---

## 9. Auto-generated locator table

<!-- auto:catalog-begin -->

> Auto-generated from `<skill>/scripts/mapping.yaml`. Do not edit by hand -- run `python <skill>/scripts/pipeline.py export-catalog` to refresh.

| # | Param | File alias | Locator | Transform | multi | opt | derived |
|---|-------|-----------|---------|-----------|:----:|:---:|:-------:|
| 1 | `N_As` | `cantp_common` | `def_suffix`<br/>· def_suffix=CanTpNas<br/>· context_container_def_suffix=CanTpTxNSdu | `ms_to_seconds` | ✓ |  |  |
| 2 | `N_Bs` | `cantp_common` | `def_suffix`<br/>· def_suffix=CanTpNbs<br/>· context_container_def_suffix=CanTpTxNSdu | `ms_to_seconds` | ✓ |  |  |
| 3 | `N_Cs` | `cantp_common` | `def_suffix`<br/>· def_suffix=CanTpNcs<br/>· context_container_def_suffix=CanTpTxNSdu | `ms_to_seconds` | ✓ |  |  |
| 4 | `N_Ar` | `cantp_common` | `def_suffix`<br/>· def_suffix=CanTpNar<br/>· context_container_def_suffix=CanTpRxNSdu | `ms_to_seconds` | ✓ |  |  |
| 5 | `N_Br` | `cantp_common` | `def_suffix`<br/>· def_suffix=CanTpNbr<br/>· context_container_def_suffix=CanTpRxNSdu | `ms_to_seconds` | ✓ |  |  |
| 6 | `N_Cr` | `cantp_common` | `def_suffix`<br/>· def_suffix=CanTpNcr<br/>· context_container_def_suffix=CanTpRxNSdu | `ms_to_seconds` | ✓ |  |  |
| 7 | `BS` | `cantp_common` | `def_suffix`<br/>· def_suffix=CanTpBs<br/>· context_container_def_suffix=CanTpRxNSdu | `int_str` | ✓ |  |  |
| 8 | `STmin` | `cantp_common` | `def_suffix_any`<br/>· def_suffix ∈ [CanTpSTmin, CanTpStMin]<br/>· context_container_def_suffix=CanTpRxNSdu | `ms_to_seconds` | ✓ | ✓ |  |
| 9 | `CAN_DLC.rx_frame_type` | `can_pt_file` | `def_suffix`<br/>· def_suffix=CanIfRxPduCanIdType<br/>· ancestor_short_name_prefix=CusDiagRCV | `canfd_pdu_id_type` | ✓ |  |  |
| 10 | `CAN_DLC.tx_frame_type` | `can_pt_file` | `def_suffix`<br/>· def_suffix=CanIfTxPduCanIdType<br/>· ancestor_short_name_prefix=CusDiagXMT | `canfd_pdu_id_type` | ✓ |  |  |
| 11 | `CAN_DLC.rx_dl` | `can_pt_file` | `def_suffix`<br/>· def_suffix=PduLength<br/>· ancestor_short_name_prefix=CusDiagRCV | `int_str` | ✓ |  |  |
| 12 | `CAN_DLC.tx_dl` | `can_pt_file` | `def_suffix`<br/>· def_suffix=PduLength<br/>· ancestor_short_name_prefix=CusDiagXMT | `int_str` | ✓ |  |  |
| 13 | `CAN_DLC.flexible_fd` | `cantp_feature_file` | `def_suffix`<br/>· def_suffix=CanTpFlexibleDataRateSupport | `bool_str` | ✓ |  | ✓ |
| 14 | `Addressing_Method` | `cantp_common` | `def_suffix_any`<br/>· def_suffix ∈ [CanTpAddressingFormat, CanTpRxAddressingFormat, CanTpTxAddressingFormat] | `addressing_format` | ✓ | ✓ |  |
| 15 | `P2_Max` | `dcm_services_common` | `def_suffix`<br/>· def_suffix=DcmDspSessionP2ServerMax | `ms_to_seconds` | ✓ |  |  |
| 16 | `P2_Star_Max` | `dcm_services_common` | `def_suffix`<br/>· def_suffix=DcmDspSessionP2StarServerMax | `ms_to_seconds` | ✓ |  |  |
| 17 | `CAN_ID_Format` | `can_pt_file` | `def_suffix`<br/>· def_suffix=CanIdType | `can_id_type` | ✓ |  |  |
| 18 | `CAN_Functional_Request_ID` | `can_pt_file` | `def_suffix_under_short_name`<br/>· def_suffix=CanHwFilterCode<br/>· ancestor_short_name=CusDiagRCVFunc | `hex_to_decimal` | ✓ |  |  |
| 19 | `CAN_Functional_Request_ID` | `can_pt_file` | `def_suffix_under_short_name`<br/>· def_suffix=CanIfRxPduCanId<br/>· ancestor_short_name=CusDiagRCVFunc | `hex_to_decimal` | ✓ |  |  |
| 20 | `CAN_Physical_Request_ID` | `can_pt_file` | `def_suffix_under_short_name`<br/>· def_suffix=CanHwFilterCode<br/>· ancestor_short_name=CusDiagRCV | `hex_to_decimal` | ✓ |  |  |
| 21 | `CAN_Physical_Request_ID` | `can_pt_file` | `def_suffix_under_short_name`<br/>· def_suffix=CanIfRxPduCanId<br/>· ancestor_short_name=CusDiagRCV | `hex_to_decimal` | ✓ |  |  |
| 22 | `CAN_Response_ID` | `can_pt_file` | `def_suffix_under_short_name`<br/>· def_suffix=CanIfTxPduCanId<br/>· ancestor_short_name=CusDiagXMT | `hex_to_decimal` | ✓ |  |  |
| 23 | `CAN_Response_ID` | `can_pt_file` | `def_suffix_under_short_name`<br/>· def_suffix=CanHwFilterCode<br/>· ancestor_short_name=CusDiagXMT | `hex_to_decimal` | ✓ |  |  |
| 24 | `PaddingByte` | `cantp_feature_file` | `def_suffix`<br/>· def_suffix=CanTpPaddingByte | `hex_to_decimal` | ✓ |  |  |
| 25 | `StrictDlcCheck` | `cantp_feature_file` | `def_suffix_any`<br/>· def_suffix ∈ [CanTpRbStrictDlcCheck, CanTpStrictDlcCheck] | `bool_str` | ✓ |  |  |
| 26 | `NRC78_Times` | `dcm_feature_file` | `def_suffix_under_short_name`<br/>· def_suffix=DcmDslDiagRespMaxNumRespPend<br/>· ancestor_short_name=DcmDslDiagResp | `int_str` | ✓ |  |  |

Total entries: **26**

<!-- auto:catalog-end -->
