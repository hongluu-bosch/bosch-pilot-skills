---
name: diagnosisroutineanalysis
description: >
  Analyze why a diagnostic 31 Service (RoutineControl) returned positive response (71)
  with abnormal results. Triggered by mentions of 31 service, RoutineControl, dataOut
  abnormal, RBAPLEOL, RBAPLCUST routine, or routine execution tracing in automotive
  diagnostic stacks.
---

# DiagnosisRoutineAnalysis

Intelligent root-cause analysis for UDS Routine 31 (`RoutineControl`) positive-response abnormalities.

## What It Is

A diagnostic analysis toolkit for tracing UDS Service $31 Routine failures — specifically when the ECU returns a positive response (`71`) but the routine itself reports abnormal completion (e.g., `dataOut1=Aborted`, `dataOut2=GenericError`).

### What the analysis covers

1. **Response decoding** — Parses `dataOut1`/`dataOut2` from the diagnostic response
2. **Code Tracking** - includes the "RBAPLCUST" client layer,"RBAPLEOL" platform state machine,"RBDHP" hydraulic protection submodule, etc.
3. **Root cause identification** — Pinpoints the exact condition (e.g., which `ProtectionState` bit, which valve/pump motor fault, which line of code)
4. **Build-option validation** — Cross-checks against actual compiled code using `SwitchSettings.csv` and `Diamant__FWUsed_*.txt` to avoid chasing inactive `#if` blocks

### What you get

A reproducible, code-backed root-cause report with file names, function names, line numbers, and actionable investigation steps — no guesswork, no reliance on DTCs or field measurements.

## When to Use

| Scenario | Example |
|----------|---------|
| Customer sends a diagnostic screenshot with `71 03 2C 64 01 0D` and asks "why did it fail?" "why response 01 0D?" | Use this |
| Routine returns `dataOut1=Aborted` or `dataOut2=HydraulicProtectionError` | Use this |
| You need to know which DHP protection bit triggered the failure | Use this |
| Routine returns NRC (`7f 31 xx`) | Not for NRC — this is for positive-response abnormalities only |

## Prerequisites

| Item | Required | Notes |
|------|----------|-------|
| `31 03` response (e.g. `71 03 02 23 00 01`) | Yes | Entry point — must contain full dataOut parameters |
| Project absolute path + build option | Yes | Different build options have different `#if` switches |
| `31 01` response or full communication log | Strongly recommended | Validates start state, session switches, interference |

### Environment prepare

1. Install `Anaconda Python`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306600/01+Base+Tools+Anaconda+VS+Code+Node.js)
2. Install `Opencode` **desktop** version. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094307517/03+%E5%AE%89%E8%A3%85OpenCode+%E5%92%8C+Cline)
3. Apply `Kimi API Key`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306832/02+Kimi+API+Key%E7%94%B3%E8%AF%B7)

### Start to use

**Provide information:**

1. **stream path** -- Project path, e.g. `C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB`
2. **request** -- The full request message, e.g. `31 03 2c 38`
3. **response** -- The failed response, e.g. `71 03 2c 38 01 0d`

**Example question:** Why request 31 03 2c 38 response 71 03 2c 38 01 0d, stream C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB

## If the user has not provided enough information

- **Missing `31 03` response**: Cannot determine dataOut1/dataOut2. Refuse analysis and ask for a diagnostic screenshot or message log.
- **Missing project path / build option**: Cannot confirm code version and conditional compilation switches. Refuse analysis and ask for workspace path and build option name.
- **Missing `31 01` / communication log**: Continue analysis but note: "Because the full communication log is missing, the following conclusions do not consider session switching / interfering requests."

## Difference from NRC Analysis

| Scenario | Response Code | Analysis Focus |
|----------|--------------|----------------|
| **NRC Analysis** | `7f 31 xx` | DCM framework pre-checks, Application condition checks |
| **Positive-Response Abnormal** | `71 31 ...` | Routine execution logic, RBAPLEOL state machine, buffer data |

## Code Architecture Layers

Important: 31 service code spans two layers. Distinguish them during investigation.

| Layer | Path | Characteristics | Change Frequency |
|-------|------|-----------------|------------------|
| **Platform** | `rba/CUBAS/Diagnosis/Dcm` | DCM framework (session/security/length checks) | Very low |
| **Platform** | `rb/as/core/app/dcom/RBAPLEOL/src` | Routine core state machine (`TogglingProcess`, etc.) | Low (platform code) |
| **Customer** | `rb/as/ms/core/app/dcom/RBAPLCust/src/RBAPLCUST_RoutineControl*.c` | Routine wrapper, DID mapping, parameter validation | High (customer code) |
| **Customer** | `rb/as/ms/core/app/dcom/RBAPLCust/src/RBAPLCUST_RC*.c` | Routine control (abbreviated form) | High (customer code) |

**Recommended investigation order**:
1. First look at **RBAPLCUST** customer layer (`*_RequestResult()` function) — confirm dataOut assembly logic
2. Then dive into **RBAPLEOL** platform layer — confirm state machine and error code sources
3. Finally check **DCM framework** — confirm if it's framework fallback behavior

## 31 Service Response Structure

### `31 01` (StartRoutine) Positive Response

```
71 01 {RID_H} {RID_L} {dataOut1} ...
│  │   │        │      │
│  │   │        │      └── dataOut1 (routine status, project-specific)
│  │   └────────┴──────── Routine ID
│  └────────────────────── Subfunction = 0x01 (Start)
└───────────────────────── Service = 0x71 (Positive Response)
```

### `31 03` (RequestRoutineResults) Positive Response

```
71 03 {RID_H} {RID_L} {dataOut1} {dataOut2} ...
│  │   │        │      │          │
│  │   │        │      │          └── dataOut2 (detailed status/error code, project-specific)
│  │   │        │      └───────────── dataOut1 (routine execution status, project-specific)
│  │   └────────┴──────────────────── Routine ID
│  └────────────────────────────────── Subfunction = 0x03 (RequestResults)
└───────────────────────────────────── Service = 0x71 (Positive Response)
```

## Core Analysis Workflow

### Human-AI Division of Labor

Principle: Fixed flows go to scripts (collect facts); variable logic goes to AI (understand and judge).

| Phase | Responsible | Task | Output |
|-------|-------------|------|--------|
| **Phase 1** | Script | Parse Dcm_Lcfg -> function names + dataOut count | Entry function name, confirm if dataOut2 exists |
| **Phase 2** | Script | Locate RBAPLCUST/RBAPLEOL files | File paths |
| **Phase 3** | Script | Read SwitchSettings, verify compile switches | Which `#if` blocks are active |
| **Phase 4** | Script + AI | Determine routine architecture type + extract step sequences | TYPE_A/B/C, CMD list |
| **Phase 5** | Script | Extract CMD failure blocks from ValvesToggling.c | Failure branch raw code |
| **Phase 6** | **AI** | Parse condition expression meanings, classify root causes, judge DEM Event | Human-readable investigation report |

**Scripts available**: `scripts/routine31_mapper.py` (Phases 1-2), `scripts/routine31_analyzer.py` (Phases 1-5)

### Phase 1-2: Automated via Script (Recommended)

Run the mapper script to automatically resolve the Routine configuration:

```bash
python scripts/routine31_mapper.py <project_root> --rid 0x2C39
```

**Output**:
```
Routine ID: 0x2C39
Config Name: RBAPLCUST_2C39_IPBBrakeFluidChange
Handler Function: Dcm_Dsp_RC_RBAPLCUST_2C39_IPBBrakeFluidChange_Func
Start Function: RBAPLCUST_IPBBrakeFluidChange_start
Stop Function: RBAPLCUST_IPBBrakeFluidChange_stop
RequestResult Function: RBAPLCUST_IPBBrakeFluidChange_RequestResult
```

For full automated analysis (Phases 1-5):

```bash
python scripts/routine31_analyzer.py <project_root> --rid 0x2C39 [--build-option MM21xSoftECUxECC]
```

Important: When selecting a build option, exclude Bootloader directories (`RBBLDR`, `OEMBLDR`, `BMGR`). If no valid directory remains after exclusion, the project's BCT has not compiled successfully yet — prompt the user to provide a path with at least one successful BCT build.

### Manual Fallback (if script unavailable)

**Step A**: In `Dcm_Lcfg_DspUds.c`, search for `Dcm_Cfg_NormalRoutineConfig_cast`, find the target RID, and record `routineCommonIndex_u16`.

**Step B**: In `Dcm_Cfg_RoutineExtendedConfig_cast[routineCommonIndex_u16]`, find `routineHandler_pfct`, then search the handler function's switch-case (case 1u=start, 2u=stop, 3u=requestResult).

**Step C**: Use the function name to glob-search in the RBAPLCust source directory:
```bash
glob: rb/as/ms/core/app/dcom/RBAPLCust/src/RBAPLCUST_RoutineControl*.c
glob: rb/as/ms/core/app/dcom/RBAPLCust/src/RBAPLCUST_*{keyword}*.c
```

Key principle: The `RBAPLCust` directory name is stable across projects. Use it as the anchor point to locate files, even if intermediate paths differ.

## Routine Architecture Types

Determine the architecture by checking for these code patterns in the RBAPLEOL file:

| Type | Detection Condition | Typical Routines | Analysis Method |
|------|---------------------|-----------------|----------------|
| **TYPE_A** | Has `g_Sequence_PST` or `RBAPLEOL_SequenceStep_ST` array, uses `RBAPLEOL_TogglingProcess_V` | BrakeFluidChange, RepairBleed, EvacAndFill | Sequence step method: Extract CMD list -> search only these CMDs in ValvesToggling.c |
| **TYPE_B** | Uses `RBAPLEOL_TogglingProcess_V` but **no** sequence array | Some 2Box routines | Generic precondition method: Only check RUNNING state preconditions + specific sub-functions in ValvesToggling.c |
| **TYPE_C** | **Does not** use `RBAPLEOL_TogglingProcess_V`, operates MESG variables directly | VCPInfoTriggerForSlave | MESG state machine method: Analyze state transition logic in RBAPLCUST |

Don't guess the architecture type. Confirm the presence/absence of the above keywords in code.

## Investigation Steps

### Step 1: Confirm Response Type
- [ ] Is it `71` (positive) or `7f` (negative)?
- [ ] If `71`, extract `dataOut1` and `dataOut2` values

### Step 2: Locate Customer Layer Code (RBAPLCUST)
- [ ] Find corresponding `RBAPLCUST_RoutineControl*.c` or `RBAPLCUST_RC*.c` by Routine ID
- [ ] Find `*_RequestResult()` function
- [ ] Confirm dataOut1 and dataOut2 data sources (which global buffer index)

### Step 3: Find Macro Definitions / Enums (Confirm Meanings)
- [ ] Search `RBAPLCUST/api/*.h` for `RoutineCompleted`, `RoutineAborted` macros
- [ ] Search `RBAPLEOL/api/*.h` for `RBAPLEOL_RoutineExtendedStatus` enum
- [ ] Record actual values, never assume

### Step 4: Dive into RBAPLEOL Platform Layer (Locate Root Cause)
- [ ] Search for `g_EOLResultBuffer_PUB[{index}]` assignment points
- [ ] Analyze the code condition triggering that assignment
- [ ] Trace back to `RBAPLEOL_RoutineExtendedStatus` or state machine modification point
- [ ] If `g_EOLParamBuffer_PUB` is involved, check if the buffer was unexpectedly overwritten

### Step 5: Check Request Sequence (if full communication log available)
- [ ] Extract all diagnostic communication records between `31 01` and `31 03`
- [ ] Confirm if there were session switches (`10 xx`), other routine requests, or security access requests
- [ ] Session switches may cause routine interruption (`FctStSTOP`)

### Step 6: Check Global Buffer Sharing Conflicts
- [ ] `g_EOLParamBuffer_PUB` and `g_EOLResultBuffer_PUB` are **shared by all EOL routines**
- [ ] Check if another routine request attempted to start during execution (even failure may modify buffers)
- [ ] Check for array out-of-bounds writes

### Step 7: DEM/DTC Auxiliary Verification (Optional)

For routine abnormalities involving hydraulic execution (valves/pump motor/pressure), after code-based root cause analysis, **if field data is available**, cross-check with DEM Events:
- DEM Event and Routine failure share the same underlying anomaly but follow two independent paths
- DEM Event **does not cause** Routine failure; they are parallel results
- Use DEM Events for **cross-validation only**, not as root cause

## Key Principles

### 1. Positive Response != Success
`71` is only the DCM framework's protocol-level response. Routine logic-level failures are conveyed through `dataOut1/dataOut2`.

### 2. Customer vs Platform Layer
- **RBAPLCUST** is customer code, responsible for wrapper and DCM interface — **start here**
- **RBAPLEOL** is platform code, responsible for core state machine — **check when diving deeper**
- Don't confuse the two layers; investigate with clear hierarchy

### 3. Global Shared Buffer Risk
`g_EOLParamBuffer_PUB` and `g_EOLResultBuffer_PUB` are shared by all EOL routines. If another routine is requested while one is executing (or if buffer is written out-of-bounds), the current routine will fail.

### 4. Never Assume Fixed Values
`dataOut1` and `dataOut2` meanings **may differ per project**. Always confirm the current project's macro/enum definitions through code search.

### 5. Check Complete Communication Log
A single `31 03` response cannot locate the problem. You must combine it with the `31 01` response and the complete communication record during that period.

### 6. Cross-ECU Routines Need CAN Signal Chain Check
For 2Box systems (e.g. IPB + RBU), routine execution results may be affected by remote ECU status. Error codes pass through CAN — analyze the complete chain:
- Remote ECU internal error detection -> local MESG variable
- COM Stack Tx sends CAN signal
- Local COM Stack Rx receives and converts
- Local RBAPLEOL detects remote error -> sets RoutineExtendedStatus

### 7. Always Verify Compile Switches (SwitchSettings.csv)
Before analyzing any `#if`-guarded code, confirm the code block is active:
- Do not search `#define` in source (may find multiple inactive definitions)
- Must check `Gen/{build-option}/out/SwitchSettings_*.csv` for the actual effective value
- If `SwitchValue` is `OFF`, that code block was excluded by the preprocessor — **treat as non-existent in the final binary**
- Typical case: `RBFS_RBAPLEOLRemoteActFunctionality=OFF` means `RBAPLEOL_Are2BoxConditionsGood()` check does not exist in the final binary

## Output Format Template

Always present findings in this order:

```
## Response Parsing

```
71 03 {RID} {dataOut1} {dataOut2} ...
```

| Field | Value | Source |
|-------|-------|--------|
| dataOut1 | 0x{xx} | `g_EOLResultBuffer_PUB[{index}]` |
| dataOut2 | 0x{xx} | `g_EOLResultBuffer_PUB[{index}]` |

---

## Root Cause Analysis

### Step 1: Customer Layer Code
**File**: `{RBAPLCUST_RoutineControl_xxx.c}`
**Function**: `{xxx_RequestResult()}`
**Key Finding**: {dataOut1/dataOut2 data sources}

### Step 2: Meaning Confirmation
**File**: `{project header file}`
**dataOut1**: {macro/enum name and meaning}
**dataOut2**: {macro/enum name and meaning}

### Step 3: Platform Layer Location
**File**: `{RBAPLEOL_xxx.c}`
**Line**: {line}
**Code**:
```c
{key code snippet}
```

### Step 4: Trigger Condition Analysis
{specific condition explanation}

---

## Investigation Suggestions

### 1. Check Diagnostic Log
- **Scope**: All requests between `31 01 {RID}` and `31 03 {RID}`
- **Focus**: Any other `31` services, session switches, `10` services
- **Expected**: No interfering requests during this period

### 2. Check Buffer Modification Points
```bash
# Find all assignment locations of g_EOLParamBuffer_PUB
grep "g_EOLParamBuffer_PUB\[" rb/as/core/app/dcom/RBAPLEOL/src/*.c
grep "g_EOLParamBuffer_PUB\[" rb/as/ms/core/app/dcom/RBAPLCust/src/*.c
```

### 3. Confirm DEM Event (only when root cause involves hydraulic protection)
Only prompt the user to check corresponding FW DEM Event when the root cause analysis involves `RBDHP_DiagnosisProtectionState` non-zero, `Dem_SetEventStatus` calls, or other hydraulic protection scenarios. If the root cause is unrelated to hydraulic protection (e.g. VCP info trigger, pure software state machine), do not output DEM Event related content.

### 4. Suggested Verification Steps
- [ ] {actionable step 1}
- [ ] {actionable step 2}
- [ ] {actionable step 3}
```

## Reference Files

For detailed investigation methods, DEM/DTC analysis, code path references, troubleshooting tips, and complete lessons learned, read:

- `references/detailed_guide.md` — Detailed investigation guide, quick lookup tables, DEM Event relationships, hydraulic protection reference
- `scripts/routine31_mapper.py` — Auto-resolve Routine ID to function names from Dcm_Lcfg
- `scripts/routine31_analyzer.py` — Full automated analysis pipeline (Phases 1-5)
