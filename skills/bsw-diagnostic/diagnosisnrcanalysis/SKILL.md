---
name: diagnosisnrcanalysis
description: >
  Analyze the root cause of diagnostic NRC (negative response, 7F). Triggered by mentions
  of NRC, negative response, UDS error code, DCM error, or why a diagnostic command was
  rejected.
---

# Diagnosis NRC Analysis Skill

> Automotive Diagnostic Negative Response Code Analyzer
>
> **Tags:** UDS, DCM, RBAPLCust, AUTOSAR, NRC, 负响应

## What It Does

This skill analyzes the **root cause** when a diagnostic service returns an **NRC (Negative Response Code)**, such as `7F XX YY`.

It examines **Application** source code and **CUBAS** logic to trace exactly why a diagnostic command was rejected.

## When to Use

Use this skill when:

- A diagnostic command returned `7F XX YY` (Negative Response Service, NRC)
- The user asks "Why did I get NRC 0x22?" or similar questions
- Analyzing C source files for diagnostic service implementations
- Debugging session transitions, DID access, or routine control failures
- Investigating UDS diagnostic errors in `AUTOSAR DCM` stacks

**Trigger Keywords:** `NRC`, `诊断`, `负响应`, `UDS`, `DCM`, `RBAPLCust`, `7F response`

## Inputs Needed

Ask the user for (or infer from context):
1. **stream path**: Project path, e.g. `C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB`
2. **service ID**: Diagnostic service ID, e.g. `10 04`
3. **request**: The full request message (optional)
4. **response**: The NRC response, e.g. `7f 10 22`

### Environment prepare

1. Install `Anaconda Python`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306600/01+Base+Tools+Anaconda+VS+Code+Node.js)
2. Install `Opencode` **desktop** version. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094307517/03+%E5%AE%89%E8%A3%85OpenCode+%E5%92%8C+Cline)
3. Apply `Kimi API Key`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306832/02+Kimi+API+Key%E7%94%B3%E8%AF%B7)

### Start to use

**Provide information:**

1. **stream path** -- Project path, e.g. `C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB`
2. **request** -- The full request message, e.g. `10 02`
3. **response** -- The NRC response, e.g. `7f 10 22`

**Example question:** Why request 10 02 response 7f 10 22, stream C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB

## Service ID to Source File Mapping

> **Important**: Source files in the project typically use **abbreviated names**, not full service names. Use **glob patterns** (e.g. `RBAPLCUST_RDBI*.c`), not exact filenames.

| Service ID | Service Name | Source File Glob Pattern | Notes |
|------------|-------------|-------------------------|-------|
| 10 | DiagnosticSessionControl | `RBAPLCUST_DiagnosticSessionControl*.c` | — |
| 11 | ECUReset | `RBAPLCUST_ECUReset*.c` / `RBAPLCUST_EcuReset*.c` | — |
| 14 | ClearDiagnosticInformation | `RBAPLCUST_ClearDiagnosticInformation*.c` | — |
| 19 | ReadDTCInformation | `RBAPLCUST_ReadDTCInformation*.c` | — |
| 22 | ReadDataByIdentifier | `RBAPLCUST_RDBI*.c` | RDBI = Read Data By Identifier |
| 27 | SecurityAccess | `RBAPLCUST_SecurityAccess*.c` / `RBAPLCUST_Seca*.c` | — |
| 2E | WriteDataByIdentifier | `RBAPLCUST_WDBI*.c` | WDBI = Write Data By Identifier |
| 2F | InputOutputControlByIdentifier | `RBAPLCUST_InputOutputControl*.c` / `RBAPLCUST_IOC*.c` / `RBAPLCUST_IOControl*.c` | IOC = Input Output Control |
| 31 | RoutineControl | `RBAPLCUST_RoutineControl*.c` / `RBAPLCUST_RC*.c` | — |
| 34 | RequestDownload | `RBAPLCUST_RequestDownload*.c` | — |
| 36 | TransferData | `RBAPLCUST_TransferData*.c` | — |
| 37 | RequestTransferExit | `RBAPLCUST_RequestTransferExit*.c` | — |
| 3E | TesterPresent | `RBAPLCUST_TesterPresent*.c` | — |

### Supplementary Notes
- **DID-related services** (22/2E/2F) heavily use abbreviations: `RDBI`, `WDBI`, `IOC`
- **RoutineControl** (31) commonly uses `RoutineControl` prefix, possibly with routine-specific suffixes like `RoutineControl_DynamicTest.c`
- The same service may have **multiple source files** (e.g. service 22 may correspond to dozens of `RDBI_*.c` files); further narrow down by specific DID
- Use `glob` with `*` wildcard when searching, e.g.:
  ```
  glob pattern: RBAPLCust/src/RBAPLCUST_RDBI_*.c
  ```

## Search Paths

Primary search path:
```
<stream_path>\rb\as\*\core\app\dcom\RBAPLCust\src
```

Also search these paths for configuration and DCM framework logic:
- `Gen/*/Rte_Dcm_Type.h` — session definitions and macros
- `make/hdr_lnk/*.h` — feature switches and compile flags
- `rba/CUBAS/Diagnosis/Dcm/src/Dsp/Uds/` — DCM framework layer (e.g. `DcmDspUds_Dsc.c`, `DcmDspUds_Rc.c`)
- `rba/CUBAS/Diagnosis/Dcm/src/Dsp/` — DCM DSP layer

## Workflow

Follow this sequence when analyzing an NRC:

1. **Parse the service ID** (e.g. `10` = DiagnosticSessionControl)
2. **Map to source file glob pattern** using the table above (e.g. `22` -> `RBAPLCUST_RDBI*.c`)
3. **Glob-search** for matching files in the RBAPLCust/src path
4. **Read the source files** and identify the service handler
5. **Search for the NRC constant** (e.g. `DCM_E_CONDITIONSNOTCORRECT`, `DCM_E_SUBFUNCTIONNOTSUPPORTED`)
6. **Trace upward** through the if-else chain to find the condition logic
7. **Distinguish the source layer** — Application vs DCM framework (see Layer Distinction below)
8. **Report findings** using the Output Format Template

## Key Principles

### Never Assume Standard Service Meanings
> Standard UDS says `10 02` = Programming Session, `10 03` = Extended Session. **Always verify in the project.**

In this project:
- `10 01` = DCM_DEFAULT_SESSION (0x01)
- `10 02` = DCM_PROGRAMMING_SESSION (0x02)
- `10 03` = DCM_EXTENDED_DIAGNOSTIC_SESSION (0x03)
- **`10 04` = DCM_ROLLER_BENCH_SESSION (0x04)** ← project-specific!

**How to verify**:
- Search `Rte_Dcm_Type.h` or generated session definitions
- Search for `DCM_PROGRAMMING_SESSION`, `DCM_ROLLER_BENCH_SESSION` macros
- Check `RBAPLCUST_SessionChange.h` and similar headers

### NRC 0x22 Is Only the Symptom — Find the Real Condition
> Seeing `*ErrorCode = DCM_E_CONDITIONSNOTCORRECT` is just the assignment point. **Trace upward to the actual condition logic.**

```c
// Don't stop here
*ErrorCode = DCM_E_CONDITIONSNOTCORRECT;

// Trace the full if-else chain
if (RBAPLCUST_IsPreConditionCheckPass()) {
    // pass
} else {
    *ErrorCode = DCM_E_CONDITIONSNOTCORRECT;  // NRC 22
}

// Then dig into IsPreConditionCheckPass() to see all failure conditions
```

### Use Multi-Path Cross-Validation
| Search Target | Path/Method |
|--------------|-------------|
| NRC assignment point | `grep DCM_E_CONDITIONSNOTCORRECT` in `RBAPLCust/src` |
| Session definitions | `grep DCM_PROGRAMMING_SESSION` in `Gen/*/Rte_Dcm_Type.h` |
| Actual macro values | `grep DCM_ROLLER_BENCH_SESSION` in `make/hdr_lnk/*.h` |
| DCM core logic | `grep DCM_E_CONDITIONSNOTCORRECT` in `rba/CUBAS/Diagnosis/Dcm` |

### Distinguish Application Layer vs DCM Framework Layer

| Layer | Location | Responsibility |
|-------|----------|---------------|
| **Application** | `RBAPLCust/src/RBAPLCUST_*.c` | Custom business logic conditions |
| **DCM Framework** | `rba/CUBAS/Diagnosis/Dcm/src/Dsp/Uds/*.c` | Session config checks, state machine transitions, request validation |

**Typical DCM fallback logic**:
```c
// DcmDspUds_Dsc.c
if(*dataNegRespCode_u8 == 0u) {
    *dataNegRespCode_u8 = DCM_E_CONDITIONSNOTCORRECT;  // default fallback NRC 22
}
```

**Critical**: DCM performs pre-checks (security level, session type, request length) **before** calling Application `ReadData()`/`WriteData()`. If these fail, DCM returns the NRC directly and **never enters the Application layer**.

| Check Item | DCM Returns NRC | Enters Application? |
|-----------|-----------------|---------------------|
| Insufficient security level | **0x33** | No |
| Wrong request length | **0x13** | No |
| Session type not supported | **0x7F / 0x31** | No |
| Subfunction not supported | **0x12** | No |
| Conditions not correct (framework) | **0x22** | No |

**Corollary**:
- NRC **0x33 / 0x13 / 0x12** → cause is in **DCM configuration or the request itself**
- NRC **0x22 after entering** `WriteData()`/`ReadData()` → cause is in **Application internal logic**
- **Never confuse the layers!**

### NRC 0x12 Special Attention: Distinguish the Source

NRC 12 (`subFunctionNotSupported`) can come from **two completely different layers**:

| Source Layer | File | Meaning | Investigation |
|-------------|------|---------|---------------|
| **DCM Framework** | `DcmDspUds_Dsc.c` | Session ID **not configured in DCM config table** | Check `Dcm_Lcfg_DspUds.c` — `Dcm_Dsp_Session[]` array |
| **Application** | `RBAPLCUST_*.c` | Session is configured but **disabled by business logic / compile switch** | Check compile switches like `RBFS_OEMBootloader` |

**Investigation steps**:
1. First check `Dcm_Lcfg_DspUds.c` to confirm if the session is configured
2. If configured, then check `RBAPLCUST_DiagnosticSessionControl.c` for compile switches or runtime conditions
3. **Don't look only at the Application layer** — DCM config layer is the more common source of NRC 12

### Compile Switches / Feature Switches Are a Frequent Cause of NRC 12

When a project has multiple variants / hexblocks, `#if` conditional compilation is the primary means of disabling features.

Common pattern:
```c
#if (RBFS_OEMBootloader != RBFS_OEMBootloader_Yes)
    *ErrorCode = DCM_E_SUBFUNCTIONNOTSUPPORTED;  // NRC 12
    l_Result = E_NOT_OK;
#endif
```

**Must check**:
- `make/hdr_lnk/RBCM_CSWPrSettings_ESPhevX.h` for switch definitions
- Different variants may have different switch values
- Confirm the variant configuration for the current stream path

### Never Guess Threshold Values
> When mentioning specific values (speed thresholds, voltage limits, etc.), **always look them up in source code** — never guess from experience.

**Wrong**: "Vehicle speed must be 0"
**Right**:
- Find the macro or constant used in the condition function (e.g. `C_DCOMXiaoMiSpeedLimit_f`)
- Trace the macro definition to confirm the actual value (e.g. `0.84 m/s = 3 km/h`)
- If the macro depends on other variables, keep tracing until you find the concrete value

### Analyze All Branches of Compound Conditions

Code `if-else if-else` chains may have multiple branches. **Don't list only one passing case** — analyze the logic for all branches.

**Wrong**: "PtRdyFlg should be Inactive"
**Right**:
- Map out the complete condition decision tree
- List all passing condition combinations and rejecting condition combinations
- Example: `(Qualifier=Invalid, any)` and `(Qualifier=Valid, PtRdyFlg=Inactive)` both pass; only `(Qualifier=Valid, PtRdyFlg=Active)` rejects

### Use Elimination to Pinpoint the Root Cause (Especially for Service 31 / RoutineControl)

When receiving an NRC, don't guess — **eliminate impossible options one by one**.

Example process:
1. Confirm no other path in the Application layer returns NRC 31 (actuator ID validation already passed)
2. Check DCM framework layer `DcmDspUds_Rc.c` for Session/Security check code
3. Discover Session check returns **NRC 31**, Security check returns **NRC 33**
4. Build an elimination table:

| Possible Cause | Returns NRC | Matches? |
|---------------|-------------|----------|
| Session is not Extended | **0x31** | **Match** |
| Insufficient security level | **0x33** | No match |
| Invalid Actuator ID | **0x31** | Already ruled out |
| Wrong request length | **0x13** | No match |
| Subfunction not supported | **0x12** | No match |

**Conclusion**: The only match is **Session is not Extended**.

**Key lesson**: Don't say "it's usually XXX" from experience — always check the code to confirm exactly which NRC is returned.

### Distinguish ReadData() and ReadDataNRC() Call Relationship

The DCM NRC function (e.g. `ReadDataNRC`) **is only called after `ReadData()` returns `E_NOT_OK`** — it is a fallback for setting the NRC after failure, not a place for active condition checks.

**Correct analysis order**:
1. First analyze the conditions under which `ReadData()` returns `E_NOT_OK`
2. If `ReadData()` does not set an NRC internally, DCM will call `ReadDataNRC()` for the default NRC
3. **Don't reverse the causal relationship!**

### NVM-Related NRC Issues

When DID reading involves NVM (Non-Volatile Memory), NRC 22 often comes from NVM operation failures.

| NVM Error State | Meaning | Common Causes |
|-----------------|---------|---------------|
| `NVM_REQ_INTEGRITY_FAILED` | Data integrity failure | CRC error, data corruption, block never written, write interrupted |
| `NVM_REQ_NV_INVALIDATED` | Block marked invalid | Software invalidated (`NvM_InvalidateNvBlock`), old data discarded before update |
| `NVM_REQ_NOT_OK` | Generic error | Hardware failure, storage medium damage |

**Investigation tips**:
- Check if the NVM block is correctly initialized and written
- If it's a new controller / unprogrammed state, the NVM block may be empty
- Check if another service (e.g. 2E/31) needs to write this NVM block first

### Multi-Stage Async Operations (DCM_E_PENDING)

For services using `DCM_E_PENDING` polling, **failure can occur on any poll cycle**. Don't analyze only the first request.

Check:
- Which stage the state machine is currently in
- The status code returned on each poll
- Completion status of async operations (CSM/HSM/NVM)
- Whether the state machine was abnormally interrupted mid-way

### Never Give Vague Assumptions

When a user asks why a specific NRC was received, **never** give answers based on "most ECU implementations". Always ask for the project path first, then locate the exact root cause in that specific project's source code and configuration.

### How to Determine the Most Likely Cause

When multiple code paths can lead to the same NRC, evaluate by priority:

| Priority | Dimension | Description | Example |
|---------|-----------|-------------|---------|
| **1** | **Code path active?** | Check function pointer (NULL_PTR?), config enabled | Path 2 (CDI callback) pointer is NULL -> excluded |
| **2** | **Common vs boundary scenario** | Common scenario > boundary exception | Path 1 (speed check): vehicle moving = common scenario |
| **3** | **Code source & architecture** | Customer custom code > platform stable code | `RBAPLCust` is customer-developed per-project, less stable than platform code |
| **4** | **Business requirement / comment** | OEM requirement comment > defensive fallback | Path 1 has comment: `/*XiaoMi requirement is NRC22*/` |
| **5** | **Direct service association** | Service-specific Mode Rule > generic error mapping | Path 1 is DSD direct interception for `$14` |

**Architecture layer distinction:**

| Layer | Typical Path | Characteristics | Investigation Priority |
|-------|-------------|-----------------|----------------------|
| **Platform code** | `rba/CUBAS/`, `rb/as/core/` | Reused across projects, high stability, high reliability | Lower |
| **Customer code** | `rb/as/xx/core/app/dcom/RBAPLCust/` | Developed per OEM requirements, high project variance, slightly lower reliability | **Higher** |

**Evaluation steps:**
1. **Eliminate impossible**: Exclude inactive code paths (NULL pointers, disabled configs)
2. **Filter by architecture layer**: Prioritize customer custom code (`RBAPLCust`), then platform code (`CUBAS`, `core`)
3. **Compare remaining paths**: By common scenario / requirement support / service association
4. **Validate against actual environment**: Ask for test conditions (vehicle state, signal values)

## Case Studies

### Case 1: $31 Returns $31 Instead of $7E (ESP10HB)

**User Question**: In `$10 01` (Default Session), sending `$31 01 2C 65` returns NRC `$31`, not `$7E`.

**Root Cause Analysis**:

1. **DSD Layer**: Service `$31` is explicitly excluded from sub-service verification. Config `allowedSessions_u32 = 0xffffffffuL` -> supported in all sessions. No `$7E` from DSD.
2. **RID Config** (`Dcm_Lcfg_DspUds.c`):
   ```c
   RID 0x2C65
   allowedSessions_u32       = 0x4uL   // Extended Diagnostic Session only
   allowedSecurityLevels_u32 = 0x2uL
   ```
3. **DSP Layer** (`DcmDspUds_Rc.c`, `Dcm_RCSessionCheck()`):
   ```c
   *dataNegRespCode_u8 = DCM_E_REQUESTOUTOFRANGE;  // NRC 0x31
   ```

**Conclusion**: DSP routine-level session check returns `$31` (requestOutOfRange), not `$7E`. The NRC source depends on which layer and which config item triggers the rejection.

### Case 2: $14 Returns $22 (ESP10HB)

**User Question**: Sending `$14 FF FF FF` returns NRC `$22`.

**Root Cause Analysis**:

1. **DSD Config** (`Dcm_Lcfg_Dsd.c`): Service `$14` registers custom Mode Rule `RBAPLCUST_ServiceModeRuleCheck`.
2. **Application Mode Rule** (`RBAPLCUST_ServiceModeRuleCheck.c`):
   ```c
   if((Sid_u8 == 0x14) || (Sid_u8 == 0x85))
   {
       if(RBAPLCUST_isSpeedLimitExceeded_B(C_DCOMXiaoMiSpeedLimit_UW))
       {
           /*vehicle speed is high,XiaoMi requirement is NRC22*/
           *Nrc_u8 = DCM_E_CONDITIONSNOTCORRECT;  // NRC 0x22
           retVal = E_NOT_OK;
       }
   }
   ```
3. **Other possible paths** (ruled out or lower priority):
   - `Dcm_Prv_CDIConditionCheck()` — callback pointers are NULL_PTR, inactive
   - `Dcm_Prv_SetErrorCodeForDemOperation()` — default fallback for unexpected DEM errors, boundary scenario

**Conclusion**: Most likely cause is **vehicle speed exceeds XiaoMi limit**. The `$22` trigger is in customer-developed application code, not DCM framework internals.

**Key lesson**: When answering NRC questions, **don't stop after finding one cause**. Search comprehensively for all code paths that could set the NRC, then judge the most likely root cause by architecture layer, activation status, and scenario commonality.

## Quick Checklist

Before reporting, verify:
- [ ] Service ID and subfunction actual definitions in the project are confirmed
- [ ] Corresponding `RBAPLCUST_*.c` source files are located
- [ ] NRC code constant (e.g. `DCM_E_CONDITIONSNOTCORRECT`) is searched
- [ ] Upward if-else condition chain is traced to the decision function
- [ ] All failure conditions in the decision function are listed
- [ ] **NRC source layer is distinguished: DCM config vs Application**
- [ ] **Compile switches / Feature Switches disabling the function are checked**
- [ ] DCM framework layer fallback NRC logic is verified
- [ ] Specific triggering condition is confirmed against datalogger logs

## Common NRC Quick Reference

| NRC | Meaning | Common Causes |
|-----|---------|---------------|
| 0x10 | generalReject | Generic rejection |
| 0x11 | serviceNotSupported | Service not supported |
| 0x12 | subFunctionNotSupported | Subfunction not supported (e.g. session type not configured) |
| 0x13 | incorrectMessageLengthOrInvalidFormat | Wrong request length or format |
| 0x21 | busyRepeatRequest | Service busy |
| **0x22** | **conditionsNotCorrect** | **Conditions not met (most common)** |
| 0x24 | requestSequenceError | Wrong request sequence |
| 0x31 | requestOutOfRange | Request out of range |
| 0x33 | securityAccessDenied | Security access denied |
| 0x35 | invalidKey | Wrong key |
| 0x36 | exceedNumberOfAttempts | Too many attempts |
| 0x37 | requiredTimeDelayNotExpired | Delay not expired |
| 0x70 | uploadDownloadNotAccepted | Upload/download not accepted |

## Output Format Template

Always present findings in this order: **conclusion first, then explanation**.

```
## Most Likely Cause

**{State the most likely root cause in 1-2 sentences}**

Examples:
- Current variant does not enable OEM Bootloader; programming session is disabled by compile switch.
- Vehicle dynamic control systems (ABS/EBD/TCS/VDC) are active during roller bench session request.
- The requested Session ID is not configured in the DCM config table.

---

## Detailed Explanation

### NRC Meaning
{nrc_meaning}

### Source Code Analysis
**File**: `{filename}`
**Function**: `{function_name}()`
**Line**: {line_number}

```c
{key code snippet}
```

{explanation of the code logic}

---

## Items to Check

### 1. {check_item_1}
- **Location**: `{file_path}`
- **Method**: {specific grep or viewing step}
- **Expected Result**: {criteria for normal vs abnormal}

### 2. {check_item_2}
- **Location**: `{file_path}`
- **Method**: {specific grep or viewing step}
- **Expected Result**: {criteria for normal vs abnormal}

### 3. Suggested Verification Steps
- [ ] {actionable step 1}
- [ ] {actionable step 2}
- [ ] {actionable step 3}
```
