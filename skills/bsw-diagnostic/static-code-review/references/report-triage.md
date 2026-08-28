# Report Triage Reference

Use this reference when the input is an auto-generated review report, a list of findings, or a user question about whether the report grading is reasonable.

## Goal

Determine which findings are:

1. Confirmed and correctly classified.
2. Real but over-classified.
3. Real but under-classified.
4. Duplicated, ambiguous, or not well supported by the code.

## Triage Order

Review report findings in this order:

1. `critical`
2. `major`
3. `minor`
4. `info`

## Triage Procedure

For each finding, perform these checks:

1. Confirm the finding is grounded in the code.
2. Confirm the rule mapping is reasonable.
3. Confirm the impact statement is justified.
4. Reassess severity by functional impact.
5. Check for duplicates.
6. Check whether the finding is actionable.

## Common Downgrade Cases

Downgrade findings when the report language sounds severe but the actual defect is not functionally severe.

Common examples:

1. Naming, include, formatting, structure, or metric findings described with generic risk language.
2. Documentation-only findings presented as if they were runtime failures.
3. Portability concerns with no demonstrated effect on the current environment.
4. Findings whose effect text is generic but not tied to the actual code path.

## Common Escalation Cases

Escalate findings when the report severity is too low for the real code impact.

Common examples:

1. Out-of-bounds writes or reads.
2. Uninitialized reads.
3. Concrete unsafe input use that can cause overflow or undefined behavior.
4. Confirmed concurrency defects affecting shared state.
5. Real logic mistakes that clearly change behavior.

## Duplicate Handling

Treat findings as duplicates or near-duplicates when:

1. Multiple rules point to the same underlying line and same defect mechanism.
2. One finding is a specific instance and another is a generic umbrella rule.
3. The report repeats the same impact using different wording.

Preferred behavior:

1. Keep the more specific finding.
2. Downgrade or remove the generic duplicate when it adds no new action.
3. If both are useful, explain the difference explicitly.