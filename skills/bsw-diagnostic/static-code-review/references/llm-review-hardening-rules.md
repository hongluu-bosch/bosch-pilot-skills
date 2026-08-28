# LLM Code Review Hallucination Prevention Rules

These rules are mandatory and must be followed before any rule-based or reasoning-based analysis begins.

## Rule 1: Zero-Load Before Every Review

Before starting any review or re-review:
1. Assume nothing from conversation history about the target file.
2. Use `read_file` or `grep` to re-load the entire file (or relevant sections).
3. Use `wc -l` to confirm actual line count.
4. Conversation-history references (function names, line numbers, code slices) are **not** authoritative. They are speculation until re-verified.

## Rule 2: Pre-Scan Existence Manifest

Before any rule analysis, produce a mechanical manifest:

```
File: <filename>
Actual lines: <from wc -l>

Functions present (verified by grep/read_file):
- funcA (line X-Y)
- funcB (line Z)

Variables / macros present (verified by grep):
- MacroA (line M)
- VarB (line N)

NOT present in this file (verified by grep):
- funcC — not found
- keywordX — not found
```

**No finding may reference any element listed as "NOT present".**
If a rule suggests a finding about an absent element, reject it with the note:
"Element X not found in this file by mechanical search. Finding suspended."

## Rule 3: Triple-Source Rule for Every Quotation

Every code slice, line number, or function reference in a finding must have:
- **File source**: which exact file was read
- **Line source**: from `grep -n` output or `read_file` line labels
- **Text source**: exact character copy from the most recent tool return

Deviation = hallucination. Rewrite or remove the finding.

## Rule 4: Conversation History Pollution Shield

When user says "review current file" or "review function X":
- If function X is not in the current file per grep, **do not** assume it exists elsewhere in this file.
- Instead: report "Function X not found in current file; please provide the file path containing it."
- Never "helpfully guess" line numbers, function bodies, or control flow from memory.

## Rule 5: Pattern Completion Rejection

If a variable name strongly suggests a matching function name by convention (e.g., `RBOBD_InputDistanceInformation_ST` → `RBNET_SCL_Rx_Read_InputDistanceInformation_st()`), **do not** create the function in the report unless it is found in the actual source.

Statistical likelihood ≠ source code truth.

## Rule 6: Hallucination Disclosure Header

Every formal report must include at the top of the analysis (not the HTML output):

```
Source Verification Block:
- File read via read_file: YES/NO (timestamp)
- Line count verified via wc -l: YES/NO
- Key elements verified via grep: YES/NO
- Conversation history was zeroed before analysis: YES/NO
```

If any answer is NO, the review is not valid.

## Rule 7: Cross-File Boundary Enforcement

If a .clinerules, user message, or previous conversation mentions another file (e.g., "see also file Y"), that file is **outside scope** until explicitly loaded via `read_file`
or `list_files`.
Findings about unloaded files must be marked:
- "Unconfirmed: reference to unloaded file Y"
- Not presented as confirmed findings

## Rule 8: Post-Review Self-Audit

After generating findings but before outputting the report:
1. Verify each finding's quoted line number is ≤ actual file line count.
2. Verify each quoted function name appears in grep output.
3. If any mismatch, delete or downgrade the finding to "Suspected But Unconfirmed".

## Violation Consequences

Failure to follow these rules causes the same issues observed in RBNET_SCL_Rx_MonitorHandler.c 20260608 review:
- Fictitious functions reported as real (RBNET_SCL_Rx_Read_InputDistanceInformation_st)
- Phantom line numbers (~1648 in a 241-line file)
- Fabricated code slices (float truncation, 24-bit overflow, switch statements)
- These result in researcher/developer time wasted chasing bugs that do not exist.

## Checklist Summary

Before generating any finding:

- [ ] Did I reload the target file via tools (not memory)?
- [ ] Did I run grep to confirm the element exists?
- [ ] Is the quoted line number ≤ wc -l output?
- [ ] Is the quoted text an exact copy from tool output?
- [ ] Did I check if the same function exists in this file, or only in conversation history?
- [ ] If referencing another file, was that file actually loaded?

All boxes must be checked for each individual finding.
