# Regression Case: Escalate To Critical

Use this case to verify that the standalone workflow still escalates issues to `critical` when the code evidence shows direct high-risk runtime impact.

## Scenario

Input type:

1. Focused code snippet.
2. Optional supporting finding list or exported report.

Code under review:

```c
void CopyPacket(const char *packet)
{
    char dest[8];

    strcpy(dest, packet);
}
```

Candidate finding:

1. External input is copied into a fixed-size buffer without bounds checking.

## Expected Review Outcome

Confirmed Findings:

1. Keep one `critical` finding for unsafe external-input handling that can overflow a fixed-size buffer.

Open Questions:

1. None required for the core classification.

Suspected But Unconfirmed Issues:

1. None required.

Severity Guardrail:

1. Do not downgrade this to `major` when the current code already shows a direct memory-corruption path.

## Why This Case Matters

This case verifies that the workflow remains capable of strong escalation when the evidence supports direct memory corruption or undefined behavior.