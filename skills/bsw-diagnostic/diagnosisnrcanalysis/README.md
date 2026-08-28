# Diagnosis NRC Analysis Skill

> Automotive Diagnostic Negative Response Code Analyzer
>
> **Tags:** UDS, DCM, RBAPLCust, AUTOSAR, NRC, 负响应

---

## What It Does

This skill analyzes the **root cause** when a diagnostic service returns an **NRC (Negative Response Code)**, such as `7F XX YY`.

It examines **Application** source code and **CUBAS** logic to trace exactly why a diagnostic command was rejected.

---

## When to Use

Use this skill when:

- A diagnostic command returned `7F XX YY` (Negative Response Service, NRC)
- The user asks "Why did I get NRC 0x22?" or similar questions
- Analyzing C source files for diagnostic service implementations
- Debugging session transitions, DID access, or routine control failures
- Investigating UDS diagnostic errors in `AUTOSAR DCM` stacks

**Trigger Keywords:** `NRC`, `诊断`, `负响应`, `UDS`, `DCM`, `RBAPLCust`, `7F response`

---

## How to Use

### Environment prepare
1. Install `Anaconda Python`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306600/01+Base+Tools+Anaconda+VS+Code+Node.js)

2. Install `Opencode` **desktop** version. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094307517/03+%E5%AE%89%E8%A3%85OpenCode+%E5%92%8C+Cline)

3. Apply `Kimi API Key`. (https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306832/02+Kimi+API+Key%E7%94%B3%E8%AF%B7)


### Configuration update
1. Replace the `'apiKey'` field in `opencode.json` with your Kimi API Key.


### Start to use

#### provide information:

1. **stream path** -- Project path, e.g. `C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB`
2. **request** -- The full request message, e.g. `10 02`
3. **response** -- The NRC response, e.g. `7f 10 22`


**e.g. Question:** Why request 10 02 response 7f 10 22, stream C:\...\ESP10HB\Gen\MM21ESP4DPBxEV881031xD4xECB
