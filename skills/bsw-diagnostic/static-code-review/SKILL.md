---
name: static-code-review-workflow
description: 'Use when reviewing code findings, validating auto-generated reports, and running a reusable static code review workflow that classifies issues by functional impact.'
argument-hint: 'Describe the code, findings, or report to review.'
user-invocable: true
disable-model-invocation: false
---

# Static Code Review Workflow

Use this skill when you need a reusable static code review workflow that classifies findings by actual functional impact instead of by guideline wording alone.

This skill is primarily for direct code review. It works best when the input is a focused code snippet, a source file, or a clearly scoped review target. Existing finding lists and exported reports are also supported when you need to validate earlier review output.

This skill is repository-independent. It can be reused across projects to review source code, generated findings, and exported reports.

This standalone skill includes bundled guideline files under [guidelines](./guidelines/). Use them as the default rule source when they are relevant to the input being reviewed.

For a simple visual overview of the workflow, see [simple workflow overview](./assets/simple-workflow-overview.html) or [simple workflow overview (zh-CN)](./assets/simple-workflow-overview.zh-CN.html).

## When to Use

Use this skill when one or more of these are true:

1. You are reviewing a focused code snippet or source file and need to judge whether a specific defect really affects behavior.
2. You need to decide whether a code issue should be `critical`, `major`, `minor`, or `info`.
3. You need to validate findings produced by static analyzers, LLM review, or human review notes.
4. You need to triage an exported report and separate real high-risk findings from noise.
5. You need to downgrade findings that are stylistic, duplicated, or speculative.

When the review scope is a large source file, keep the question focused. Prefer a function, region, or clearly stated review goal over an open-ended request to scan everything.

Typical trigger phrases:

1. review this file
2. validate these findings
3. assess this report
4. classify severity
5. does this affect functionality
6. should this be major or critical

## Core Review Principles

Apply these principles consistently:

1. Only findings with likely functional impact should remain `major` or `critical`.
2. A finding can be high severity only when it has clear evidence of impact on correctness, runtime behavior, memory safety, concurrency, security, or externally visible behavior.
3. Style, naming, formatting, structure, readability, maintainability, portability, and most metric findings should normally be `minor` or `info`.
4. Auto-generated findings must be validated against code context before being treated as confirmed defects.
5. If evidence is weak or impact is uncertain, do not over-classify.
6. When bundled guidelines define a relevant rule, review against that rule before falling back to general judgment.
7. Treat bundled guidelines as a calibration source, not as a checklist that must become findings.
8. For direct source-code review, do not confirm contract-dependent, null-pointer, caller-behavior, boundary-range, wraparound, or portability concerns unless the visible code proves the failing path.
9. Prefer omission over speculative triage noise. A weakly supported concern does not need to appear in the output unless it materially helps reviewer follow-up.
10. Do not treat this skill as a substitute for a deterministic analyzer or an exhaustive whole-codebase scanner.

## Bundled Guideline Library

Use these bundled guideline files as the default rule library for this standalone bundle:

1. [c_coding_rules.md](./guidelines/c_coding_rules.md)
2. [cpp_coding_rules.md](./guidelines/cpp_coding_rules.md)
3. [general_coding_rules.md](./guidelines/general_coding_rules.md)
4. [arithmetic_coding_rules.md](./guidelines/arithmetic_coding_rules.md)
5. [code_metrics.md](./guidelines/code_metrics.md)
6. [automatic_tested_rules.md](./guidelines/automatic_tested_rules.md)

When reviewing code with this skill:

1. Identify which bundled guideline files are relevant to the language and topic.
2. Check whether the reported issue maps to a concrete bundled rule.
3. Cite the matching rule ID or rule title when practical.
4. If no bundled rule applies, continue with the general functional-impact review workflow.

Detailed grading examples and calibration notes are in [severity policy](./references/severity-policy.md).

## Severity Policy

Use this grading policy when reviewing or recalibrating findings:

### Critical

Use `critical` only when the finding has strong evidence of direct high-risk impact, such as:

1. Out-of-bounds access.
2. Uninitialized memory read.
3. Unsafe input handling that can directly trigger memory corruption, overflow, or undefined behavior.
4. Direct security exposure with concrete exploit or data exposure risk.
5. Concurrency defects likely to corrupt shared state or break runtime correctness.

### Major

Use `major` when the finding is not catastrophic but can materially affect behavior, such as:

1. Incorrect logic caused by misuse of language features.
2. Error handling omissions that can propagate bad state or wrong results.
3. Resource lifecycle issues that can cause functional failure or repeated runtime degradation.
4. Domain-validation gaps that can lead to incorrect behavior without clear evidence of catastrophic failure.
5. Numeric conversion or evaluation-order issues that can change program results.

### Minor

Use `minor` for issues that are real but usually not directly blocking functionality, such as:

1. Naming and style violations.
2. Include and header organization issues.
3. Structural and maintainability findings.
4. Complexity and metric findings.
5. Documentation and rationale-comment findings.
6. Portability-only concerns unless they are proven to affect current runtime behavior.

### Info

Use `info` for low-risk advisory items where the finding is mainly informational and not actionable as a concrete defect.

## Review Procedure

Follow this order:

1. Identify the review scope.
2. Determine the evidence source.
3. Confirm the code context.
4. Check the bundled guideline library for relevant rules.
5. Decide the input mode: direct code review, existing findings, or exported report.
6. Remove duplicates and near-duplicates before final classification.
7. Collapse multiple symptoms that share one defect mechanism into one finding.
8. Assess functional impact first.
9. Assess non-functional impact second.
10. Apply the severity policy.
11. For direct source-code review, keep confirmed findings selective and prefer one strong code-proven item over multiple speculative or contract-dependent items.
12. Separate confirmed findings from open questions and unconfirmed suspicions, but omit low-value follow-up noise when it does not help the reviewer.
13. Produce a structured result.

When the input is an auto-generated report, also follow the [report triage guide](./references/report-triage.md).

## Input Mode Guidance

Apply the workflow differently depending on the input:

1. Direct code review: treat this as the default mode. Review the code against the bundled guidelines, confirm defect mechanisms from the code itself, and keep uncertain risks out of confirmed findings.
2. Existing finding list: validate each item, deduplicate overlapping items, and keep only the most specific actionable finding for each underlying defect.
3. Exported report: treat this as report triage. Reassess severity, remove duplicates, and move weakly supported items out of confirmed findings.

When multiple findings point to the same underlying mechanism, keep the most specific and actionable one. Generic umbrella findings should usually be removed or folded into the more specific item.

When contract context, caller guarantees, or boundary conditions are missing, do not present the issue as a confirmed defect unless the code itself already proves the failure.

When reviewing a single source file or function without external contract context:

1. Do not manufacture open questions for every unseen precondition.
2. Do not emit null-pointer or wraparound concerns just because a parameter or arithmetic operation exists.
3. Only keep an open question when resolving it would materially change whether a high-impact finding is real.
4. Unless the user explicitly asks for exhaustive coverage, keep at most 3 confirmed findings for a source file and prefer fewer when one issue dominates the behavioral risk.

## Output Expectations

When using this skill, structure the review output like this:

1. Confirmed Findings
2. Open Questions
3. Suspected But Unconfirmed Issues
4. Risk Summary
5. Suggested Next Actions

For each finding, explain:

1. What the issue is.
2. Whether it affects functionality.
3. Why the chosen severity is justified.
4. Why it was not classified higher if downgraded.

If no open questions or unconfirmed issues survive filtering, output `None.` for those sections instead of adding advisory noise.

By default, this skill should return review conclusions in chat. Report file generation belongs to the dedicated report-generation prompt.

Only generate Markdown and HTML report content from this skill when the user explicitly asks for report output and no dedicated report-generation prompt is being used.

Use the [report templates](./references/report-templates.md) as the default structure.
Use the [report output guide](./references/report-output.md) for naming and placement.

When report generation is delegated to project tasks or a bundled review pipeline, do not invent extra archive shell commands. Treat report archiving as pipeline-managed unless the user explicitly asks for a standalone archive step.

## Reviewer Guidance

When reviewing generated findings:

1. Prefer direct code evidence over generic risk language.
2. Trust deterministic findings more than unsupported model claims.
3. Downgrade any finding that is rule-only but not behavior-impacting.
4. Escalate only when the reasoning is concrete and code-backed.
5. Validate suspicious model-only findings using the [finding validation guide](./references/finding-validation.md).
6. Prefer bundled guideline rules over ad hoc wording when a matching rule exists.
7. If a possible issue depends on missing contracts or unseen call paths, present it as an open question or unconfirmed issue instead of a confirmed defect.

## Boundaries

This skill should guide review behavior, but it should not:

1. Replace static analyzers or test results.
2. Claim release readiness on its own.
3. Promote speculative findings to high severity without code evidence.
4. Treat every rule violation as a functionally significant defect.
5. Serve as the only first-pass scanner for large codebases.

## Resources

1. [severity policy](./references/severity-policy.md)
2. [report triage](./references/report-triage.md)
3. [finding validation](./references/finding-validation.md)
4. [review examples](./references/examples.md)
5. [regression case: deduplicate to one major](./references/regression-case-dedup-major.md)
6. [regression case: downgrade to minor](./references/regression-case-downgrade-minor.md)
7. [regression case: escalate to critical](./references/regression-case-escalate-critical.md)
8. [report templates](./references/report-templates.md)
9. [report output](./references/report-output.md)
10. [simple workflow overview](./assets/simple-workflow-overview.html)
11. [sample Markdown report](./assets/sample-static-code-review-report.md)
12. [sample HTML report](./assets/sample-static-code-review-report.html)
13. [bundled c rules](./guidelines/c_coding_rules.md)
14. [bundled cpp rules](./guidelines/cpp_coding_rules.md)
15. [bundled general rules](./guidelines/general_coding_rules.md)