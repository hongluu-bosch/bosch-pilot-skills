# Finding Validation Reference

Use this reference when a finding comes from model-assisted analysis or a generated report and you need to decide whether it is real, duplicated, overstated, or too vague.

## Goal

Convert generated findings into one of these states:

1. Confirmed.
2. Confirmed but over-classified.
3. Plausible but unproven.
4. Duplicate.
5. Rejected.

## Validation Procedure

Validate each finding in this order:

1. Locate the exact code.
2. Check the rule match.
3. Check the defect mechanism.
4. Check the evidence level.
5. Reassess severity.

## Signs a Finding Is Probably Valid

1. The code clearly matches the reported pattern.
2. The rule and fix suggestion are specific and technically aligned.
3. The impact statement is tied to the actual code path.
4. A deterministic check or manual inspection supports the same conclusion.

## Signs a Finding Needs Downgrade or Clarification

1. The defect exists, but the impact statement uses generic severe wording not proven by the code.
2. The finding cites a broad umbrella rule instead of the more specific issue.
3. The code violates a rule, but runtime or functional impact is unclear.
4. The fix suggestion is generic and not obviously connected to the reported line.

## Signs a Finding Should Be Rejected

1. The code does not contain the reported construct.
2. The cited rule does not apply to the actual code.
3. The finding depends on hidden assumptions with no code evidence.
4. The finding is only a paraphrase of another nearby issue.

## Duplicate Rules

Treat findings as duplicates when:

1. They describe the same code defect using different labels.
2. One finding is specific and another is only a broad restatement.
3. They point to the same line and same defect mechanism.

Preferred handling:

1. Keep the most specific, actionable finding.
2. Merge or drop the generic duplicate.
3. If both are useful, explain how they differ.