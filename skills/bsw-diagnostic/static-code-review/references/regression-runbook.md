# Regression Runbook

Use this runbook to manually regression-check the standalone Static Code Review workflow after changes to the skill, prompts, or usage guidance.

## Goal

Confirm that the packaged regression cases still produce the expected review behavior after prompt or workflow changes.

This runbook is intentionally manual. It is designed for reviewer verification of output quality, not for automated pass or fail execution.

## Regression Cases

Run these cases as a stable baseline:

1. [regression-case-dedup-major.md](./regression-case-dedup-major.md)
2. [regression-case-downgrade-minor.md](./regression-case-downgrade-minor.md)
3. [regression-case-escalate-critical.md](./regression-case-escalate-critical.md)

## When To Run

Run this manual regression after changes to any of these assets:

1. `/skills/static-code-review-workflow/SKILL.md`
2. `/.github/prompts/static-code-review.prompt.md`
3. `/.github/prompts/static-code-review-generate-report.prompt.md`
4. Usage guides or overview documents that change the expected operating mode.
5. Severity, triage, or finding-validation references.

## Setup

1. Open the repository root in VS Code.
2. Open Copilot Chat.
3. Make sure the standalone assets are visible in the current workspace.
4. Decide whether you are validating the review prompt or the report-generation prompt.
5. Use the same prompt entry point for all three cases in a single regression pass.

## Standard Procedure

For each regression case:

1. Open the case file.
2. Copy the scenario, code, and candidate findings into Copilot Chat, or summarize them faithfully in one prompt.
3. Use `Static Code Review` when validating triage behavior.
4. Use `Static Code Review Generate Report` only when you also want to confirm report-generation behavior.
5. Compare the response against the expected outcome section in the case file.
6. Record whether the case passed, partially passed, or failed.

## Pass Criteria By Case

### Case 1: Deduplicate To One Major

Expected pass behavior:

1. Exactly one confirmed `major` finding is kept for the signed/unsigned comparison defect.
2. Duplicate null-pointer items are not both kept as confirmed findings.
3. Contract-dependent null-pointer concerns move to open questions rather than confirmed findings.
4. Non-functional items such as copyright or cast-comment findings do not remain as major or critical defects.

Fail examples:

1. Multiple duplicate findings remain in confirmed findings.
2. The signed/unsigned defect disappears or is downgraded below `major` without new evidence.
3. Contract-dependent null-pointer concerns are promoted to confirmed defects without code proof.

### Case 2: Downgrade To Minor

Expected pass behavior:

1. Naming, include-style, macro-style, and prefix issues stay at `minor` when no concrete runtime impact is shown.
2. The workflow does not escalate convention-only findings to `major` or `critical`.

Fail examples:

1. Style-only issues remain `major` or `critical` with generic risk wording only.
2. The workflow treats convention violations as confirmed runtime defects without code-backed impact.

### Case 3: Escalate To Critical

Expected pass behavior:

1. Fixed-buffer overflow risk from unchecked external input remains `critical`.
2. The reasoning explicitly ties the issue to direct memory corruption or undefined behavior.

Fail examples:

1. The overflow case is downgraded to `major` or `minor` without a code-based justification.
2. The reasoning becomes generic and stops connecting the defect to direct high-risk runtime impact.

## Suggested Recording Template

Use a short checklist for each run:

1. Case name.
2. Prompt entry point used.
3. Pass, partial pass, or fail.
4. What changed from the expected output.
5. Whether the change is acceptable, a regression, or an intentional policy update.

## Interpreting Results

1. If all three cases pass, the core triage behavior is stable for this change set.
2. If the downgrade case fails, the workflow may be over-classifying noise.
3. If the dedup case fails, the workflow may be drifting toward scanner-like behavior.
4. If the critical-escalation case fails, the workflow may be too conservative and may miss high-risk defects.

## Notes

1. Exact wording does not need to match previous runs.
2. Severity, confirmation status, and duplicate-handling behavior do need to match the expected outcome unless the policy changed intentionally.
3. If policy changes intentionally, update the regression case files together with this runbook.