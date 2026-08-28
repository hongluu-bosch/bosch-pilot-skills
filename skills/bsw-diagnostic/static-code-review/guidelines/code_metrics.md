# [Metric-RB-CC-BBM.GOTO] Do not use goto statements

- **Severity**: error
- **Review Severity**: minor
- **Category**: metrics
- **Analysis**: static
- **Applies to**: both
- **Source**: [Metric-RB-CC-BBM.GOTO](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#metric-rb-cc-bbmgoto)

## Description

goto statements shall not be used. They lead to unstructured code that is difficult to read, maintain, and verify. The use of goto bypasses normal control flow constructs and makes reasoning about program behavior error-prone.

## Rationale / Effect if Violated

Using goto creates spaghetti code with unpredictable control flow. It undermines structured programming principles, making static analysis harder and increasing the risk of resource leaks, skipped initializations, and unreachable code.

## Fix Suggestion

Replace goto with structured control flow constructs such as loops (`for`, `while`), conditionals (`if`/`else`), `break`, `continue`, or early `return` statements. If goto is used for cleanup, use RAII (C++) or a dedicated cleanup function (C).

---

# [Metric-RB-CC-BBM.LEVEL] Maximum nesting level

- **Severity**: warning
- **Review Severity**: minor
- **Category**: metrics
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Metric-RB-CC-BBM.LEVEL](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#metric-rb-cc-bbmlevel)

## Description

Functions shall not have excessive nesting levels. Deep nesting makes code hard to understand and maintain. Recommended maximum nesting depth is **5 levels**.

## Rationale / Effect if Violated

Deeply nested code is difficult to read, test, and modify. Each additional nesting level increases cognitive load and makes it harder to trace execution paths, raising the likelihood of logic errors and reducing maintainability.

## Fix Suggestion

Reduce nesting by extracting nested logic into helper functions, using early returns, or applying guard clauses to handle edge cases at the top of the function. Inverting conditions to exit early is often the simplest improvement.

---

# [Metric-RB-CC-BBM.PARAM] Maximum number of function parameters

- **Severity**: warning
- **Review Severity**: minor
- **Category**: metrics
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Metric-RB-CC-BBM.PARAM](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#metric-rb-cc-bbmparam)

## Description

Functions shall not have too many parameters. Recommended maximum is **7 parameters**. A high parameter count indicates that a function may be doing too much or that related data should be grouped.

## Rationale / Effect if Violated

Functions with many parameters are harder to call correctly, increasing the risk of argument-order mistakes and making the API difficult to use and maintain. Long parameter lists also hinder readability and complicate testing.

## Fix Suggestion

Group related parameters into structs or classes. Consider using a configuration or context struct to bundle options. Evaluate whether the function has too many responsibilities and should be split.

---

# [Metric-RB-CC-BBM.PATH] Maximum number of execution paths

- **Severity**: warning
- **Review Severity**: minor
- **Category**: metrics
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Metric-RB-CC-BBM.PATH](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#metric-rb-cc-bbmpath)

## Description

Functions shall not have too many execution paths. A high path count indicates overly complex logic that is difficult to test exhaustively and reason about correctly.

## Rationale / Effect if Violated

An excessive number of execution paths makes it impractical to achieve full test coverage. It increases the probability of untested edge cases harboring defects and makes code reviews less effective.

## Fix Suggestion

Simplify the function by extracting sub-functions, reducing conditional branches, or using lookup tables and dispatch maps instead of long if/else or switch chains.

---

# [Metric-RB-CC-BBM.STMT] Maximum number of statements

- **Severity**: warning
- **Review Severity**: minor
- **Category**: metrics
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Metric-RB-CC-BBM.STMT](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#metric-rb-cc-bbmstmt)

## Description

Functions shall not have too many statements. Recommended maximum is **50–80 statements**. Excessively long functions are a sign that the function is handling multiple responsibilities.

## Rationale / Effect if Violated

Long functions are harder to understand, test, and maintain. They tend to accumulate unrelated logic over time, violating the single-responsibility principle and increasing the risk of regressions when changes are made.

## Fix Suggestion

Refactor long functions into smaller, focused helper functions. Identify logically distinct sections and extract them, giving each a descriptive name that documents its purpose.

---

# [Metric-RB-CC-BBM.VG] Cyclomatic complexity (McCabe)

- **Severity**: warning
- **Review Severity**: minor
- **Category**: metrics
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Metric-RB-CC-BBM.VG](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#metric-rb-cc-bbmvg)

## Description

Functions shall have limited cyclomatic complexity. Recommended maximum VG is **15**. Cyclomatic complexity (VG) counts the number of independent paths through a function, with each decision point (if, while, for, case, &&, ||) adding to the count.

## Rationale / Effect if Violated

High cyclomatic complexity correlates with increased defect density and reduced testability. Functions with VG above the threshold require a disproportionate number of test cases for adequate coverage and are more prone to subtle logic errors.

## Fix Suggestion

Reduce complexity by extracting sub-functions, simplifying boolean conditions, consolidating duplicate branches, or using polymorphism (C++) to replace conditional dispatch.
