# Reviewer Self-Checklist — Structural Pattern Verification

## Background

In RBNET_SCL_Rx_MonitorHandler.c, a **Major** Coding Rule 4.6 defect was initially missed because `RBOBD_InputDistanceInformation_ST` was `Define`d and `Send` without ever being `Rcv`d, causing the whole struct to carry uninitialized member values.

The root cause of the miss was not ignorance of the rule, but a failure to **force-match** the rule against the actual code through an explicit checklist.

## Mandatory Practices for Future Reviews

### 1. Never Assume Pattern Completeness from Scaffolding

When a function follows a repeated multi-step pattern (e.g., Define → Rcv → Modify → Send), **do not assume every entity completes the chain**.

- List every entity that participates in **Step 1** (creation/definition).
- For each entity, tick off whether Steps 2, 3, and 4 exist.
- If Step 2 is absent, flag Rule 4.6 immediately unless the entity is fully initialized by other means in the same path.

### 2. Convert Every Relevant Coding Rule into an Observable Checklist Before Reading Code

After loading bundled guidelines, write down 2–3 concrete code patterns that would prove or disprove each rule.

| Rule | Observable Checklist |
|---|---|
| Coding Rule 4.6 (partial struct update) | For every struct sent whole: (a) Was it fully Rcv'd/initialized first? (b) Are all members assigned in this path? If neither, flag. |
| Coding Rule 4.5 (runtime-error-prone constructs) | Every division: divisor checked? Every pointer deref: NULL checked? Every array access: bounds checked? |
| Coding Rule 4.2 (external input validation) | Every value from bus/config: range-checked before use? |

Do not begin line-by-line reading until the checklist is explicit.

### 3. Handle `#if` / `#else` as Separate Translation Units

When the same signal appears inside different `#if` blocks, verify the full chain **per branch**.

- In the reported defect, the signal was handled under `RBFS_RBOBDPID2131Handler == STANDARD` **only** in Update, but was never Rcv'd in either VOYAH or DFPV paths.
- The Rcv section had no conditional guard for this signal at all, which means it was silently omitted for all configurations.

### 4. Prioritize Missing Steps Over Anomalous Steps

An empty `else { /* Do nothing */ }` is visually conspicuous and draws attention.
A **missing `Rcv` call** is invisible but structurally more severe (Rule 4.6).

- First pass: look for **omissions** (what step is missing from the chain?).
- Second pass: look for **anomalies** (why is this branch different from the others?).

### 5. Force a "Prove the Negative" Step Before Finalizing

Before declaring "No findings" or downgrading severity, explicitly ask:

> "What is the simplest way this code could violate the loaded rules without looking abnormal?"

If the answer is "a missing Rcv between Define and Send," verify that every defined entity has a matching Rcv.

### 6. Maintain Severity Discipline — But Do Not Filter Before Verification

The pipeline default `minimumDisplayedSeverity = "major"` means Minor findings are suppressed from final output. However:

- **Never** use the severity filter as a reason to stop looking for Minor findings during the verification pass.
- A Minor finding can be the **symptom** of a Major root cause. In this case, if `Rcv` had been present but the struct was still partially updated, it might have looked like a Minor naming/style issue, but the underlying Rule 4.6 violation is Major.
- Verify the defect mechanism first, classify severity second, then apply the display filter.

## Quick Reference: Common Embedded Message Patterns

For AUTOSAR/COM-style message handlers, always verify:

```
For each message_signal:
    [ ] DefineMESGDef / RBMESG_DefineMESGDef exists?
    [ ] RcvMESGDef / RBMESG_RcvMESGDef exists?
    [ ] Qualifier is updated in both valid and invalid paths?
    [ ] SendMESGDef / RBMESG_SendMESGDef exists in the path where it is needed?
    [ ] If sent whole, all struct members are initialized or restored?
```
