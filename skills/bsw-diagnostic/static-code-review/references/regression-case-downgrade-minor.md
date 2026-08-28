# Regression Case: Downgrade To Minor

Use this case to verify that rule violations without clear functional impact are downgraded and kept out of major or critical severities.

## Scenario

Input type:

1. Focused code snippet.
2. Optional supporting finding list or exported report.

Code under review:

```c
#include "string.h"

#define sensorTimeout 100U

uint32 counter;

void processPacket(void)
{
    /* implementation omitted */
}
```

Candidate findings:

1. System header is included with `""` instead of `<>`.
2. Macro name is not uppercase.
3. Identifier naming does not follow the required convention.
4. Exported function does not use the required prefix.

## Expected Review Outcome

Confirmed Findings:

1. Keep these findings only as `minor` if the review scope requires non-functional guideline tracking.

Open Questions:

1. None required.

Suspected But Unconfirmed Issues:

1. None required.

Severity Guardrail:

1. None of these items should remain `major` or `critical` unless the reviewer can show a concrete runtime or integration failure in the current codebase.

## Why This Case Matters

This case verifies that the workflow does not over-classify naming, include-style, or convention issues just because the original report uses severe wording.