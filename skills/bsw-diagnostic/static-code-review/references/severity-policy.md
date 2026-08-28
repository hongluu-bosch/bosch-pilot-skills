# Severity Policy Reference

This reference file provides concrete calibration examples for functional-impact code review.

Use it when a finding sits near the boundary between `critical`, `major`, and `minor`.

## Guiding Rule

Only findings with clear functional impact should remain `major` or `critical`.

If a finding is mainly about readability, consistency, structure, portability, or maintainability, it should usually be `minor` or `info`.

## Typical Critical Findings

These usually justify `critical` when the code evidence is concrete:

1. Array out-of-bounds access.
2. Uninitialized memory read.
3. Input used in a way that can directly cause overflow, memory corruption, or undefined behavior.
4. Direct security exposure with concrete exploit or data exposure consequences.
5. Concurrency defects likely to corrupt shared state or break execution correctness.
6. Invalid address or pointer usage that can dereference unmapped or unsafe memory.

## Typical Major Findings

These usually justify `major` when they can materially affect behavior, but the risk is below the `critical` threshold:

1. Error returns ignored in a way that can propagate wrong state.
2. Language-feature misuse that changes logic.
3. Resource lifecycle misuse that can break behavior or cause repeated runtime degradation.
4. Numeric conversion issues that can change program results.
5. Evaluation-order and side-effect issues that can produce incorrect results.
6. Library-domain or recursion misuse when it can realistically affect runtime behavior.
7. Cross-boundary type-layout issues with likely runtime or integration impact.

## Typical Minor Findings

These should usually stay `minor` unless code evidence shows direct impact:

1. Naming and formatting violations.
2. Include style and header organization issues.
3. Complexity and metric findings.
4. Documentation and comment-rationale findings.
5. Global-state design concerns without demonstrated runtime breakage.
6. Enum-range and portability-only concerns.
7. Macro-style and parenthesization findings unless they are shown to break behavior in the current code.

## Downgrade Rules

Downgrade a finding when one or more of these are true:

1. It violates a rule but there is no clear effect on actual behavior.
2. The issue is plausible but not demonstrated in the current code path.
3. The reported impact is speculative or only indirectly related to correctness.
4. The issue is primarily about maintainability, portability, or consistency.

## Escalation Rules

Escalate a finding only when the code evidence supports it:

1. The defect can change program output or control flow.
2. The defect can corrupt memory or access invalid memory.
3. The defect can break safety, security, or concurrency guarantees.
4. The defect can cause externally visible functional failure.