# DiagnosisRoutineAnalysis

Intelligent root-cause analysis for UDS Routine 31 (`RoutineControl`) positive-response abnormalities.

---

## What It Is

A diagnostic analysis toolkit for tracing UDS Service $31 Routine failures — specifically when the ECU returns a positive response (`71`) but the routine itself reports abnormal completion (e.g., `dataOut1=Aborted`, `dataOut2=GenericError`).

### What the analysis covers

1. **Response decoding** — Parses `dataOut1`/`dataOut2` from the diagnostic response
2. **Code Tracking** - includes the "RBAPLCUST" client layer,"RBAPLEOL" platform state machine,"RBDHP" hydraulic protection submodule, etc.
3. **Root cause identification** — Pinpoints the exact condition (e.g., which `ProtectionState` bit, which valve/pump motor fault, which line of code)
4. **Build-option validation** — Cross-checks against actual compiled code using `SwitchSettings.csv` and `Diamant__FWUsed_*.txt` to avoid chasing inactive `#if` blocks

### What you get

A reproducible, code-backed root-cause report with file names, function names, line numbers, and actionable investigation steps — no guesswork, no reliance on DTCs or field measurements.

---

## When to Use

| Scenario | Example |
|----------|---------|
| Customer sends a diagnostic screenshot with `71 03 2C 64 01 0D` and asks "why did it fail?" "why response 01 0D?" | ✅ Use this |
| Routine returns `dataOut1=Aborted` or `dataOut2=HydraulicProtectionError` | ✅ Use this |
| You need to know which DHP protection bit triggered the failure | ✅ Use this |
| Routine returns NRC (`7f 31 xx`) | ❌ Not for NRC — this is for positive-response abnormalities only |

---

## Prerequisites

| Item | Required | Notes |
|------|----------|-------|
| `31 03` response (e.g. `71 03 02 23 00 01`) | ✅ Yes | Entry point — must contain full dataOut parameters |
| Project absolute path + build option | ✅ Yes | Different build options have different `#if` switches |
| `31 01` response or full communication log | ⚠️ Strongly recommended | Validates start state, session switches, interference |

---

## How to Use

1. Install `Anaconda Python`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306600/01+Base+Tools+Anaconda+VS+Code+Node.js)

2. Install `Opencode` **desktop** version. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094307517/03+%E5%AE%89%E8%A3%85OpenCode+%E5%92%8C+Cline)

3. Apply `Kimi API Key`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306832/02+Kimi+API+Key%E7%94%B3%E8%AF%B7)


### Configuration update
1. Replace the `'apiKey'` field in `opencode.json` with your Kimi API Key.


### Start to use

#### provide information:

1. **stream path** -- Project path, e.g. `C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB`
2. **request** -- The full request message, e.g. `31 03 2c 38`
3. **response** -- The failed response, e.g. `71 03 2c 38 01 0d`


**e.g. Question:** Why request 31 03 2c 38 response 71 03 2c 38 01 0d, stream C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB

