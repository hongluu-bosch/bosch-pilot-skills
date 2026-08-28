# [C Coding Rule 1.1] Use only capital letters for the name of a MACRO

- **Severity**: warning
- **Review Severity**: minor
- **Category**: naming
- **Analysis**: static
- **Applies to**: c
- **Source**: [C Coding Rule 1.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#c-coding-rule-1-1)

## Description

No macros shall have lowercase letters in their names. All macro names must use UPPER_SNAKE_CASE exclusively.

## Rationale / Effect if Violated

Macros with lowercase names can be confused with regular variables or functions, reducing readability and increasing the risk of accidental name collisions. Consistent uppercase naming makes macros immediately identifiable in code.

## Good Example

```c
#define MY_MACRO 42
#define MAX_BUFFER_SIZE 1024
```

## Bad Example

```c
#define myMacro 42
#define maxBufferSize 1024
```

## Fix Suggestion

Rename the macro to UPPER_SNAKE_CASE. For example, rename `myMacro` to `MY_MACRO`.

---

# [C Coding Rule 1.2] If possible use functions instead of MACROS

- **Severity**: info
- **Review Severity**: minor
- **Category**: design
- **Analysis**: llm
- **Applies to**: c
- **Source**: [C Coding Rule 1.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#c-coding-rule-1-2)

## Description

Prefer functions over macros wherever possible. Functions are type-safe, easier to debug, and produce clearer error messages. Use `static` functions when the function is only needed within a single compilation unit.

## Rationale / Effect if Violated

Functions are easier to maintain, review, and analyze than macros. Macros bypass type checking, can introduce subtle bugs through multiple evaluation of arguments, and are difficult to step through in a debugger. Using functions improves code safety and maintainability.

## Good Example

```c
static inline int square(int x) {
    return x * x;
}
```

## Bad Example

```c
#define SQUARE(x) ((x) * (x))
```

## Fix Suggestion

Replace the macro with a function. If the macro is only used within a single file, declare the replacement function as `static`. Use `static inline` if performance is a concern.

---

# [C Coding Rule 1.3] Use a function-like MACRO only with all of its arguments

- **Severity**: error
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: c
- **Source**: [C Coding Rule 1.3](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#c-coding-rule-1-3)

## Description

A function-like macro defined with N parameters must always be invoked with exactly N arguments. Calling a macro with fewer or more arguments than it was defined with leads to undefined behavior.

## Rationale / Effect if Violated

Invoking a macro with the wrong number of arguments causes undefined behavior, which may result in compilation errors, silent data corruption, or unpredictable runtime failures.

## Good Example

```c
#define ADD(a, b) ((a) + (b))

int result = ADD(3, 4);
```

## Bad Example

```c
#define ADD(a, b) ((a) + (b))

int result = ADD(3);
```

## Fix Suggestion

Call the macro with the correct number of arguments matching its definition. If the macro is defined with N parameters, always supply exactly N arguments at every call site.

---

# [C Coding Rule 1.4] Do not use preprocessor directives as arguments for MACROS

- **Severity**: error
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: c
- **Source**: [C Coding Rule 1.4](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#c-coding-rule-1-4)

## Description

Do not pass preprocessor directives (such as `#ifdef`, `#define`, `#include`, etc.) as arguments to function-like macros. The behavior of such usage is undefined by the C standard.

## Rationale / Effect if Violated

Passing preprocessor directives as macro arguments results in undefined behavior. The preprocessor does not interpret directives inside macro argument lists, leading to unpredictable compilation results or silent failures.

## Good Example

```c
#define F_OF_X(x) ((x) + 1)

#ifdef FEATURE_ENABLED
int val = F_OF_X(42);
#endif
```

## Bad Example

```c
#define F_OF_X(x, y) ((x) + (y))

F_OF_X(
#ifdef FEATURE_ENABLED,
    something
)
```

## Fix Suggestion

Do not pass preprocessor directives as macro arguments. Move conditional logic outside the macro invocation using `#ifdef`/`#endif` blocks around the entire macro call.

---

# [C Coding Rule 1.5] Be careful with the combination of MACRO parameters and # or ##

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: c
- **Source**: [C Coding Rule 1.5](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#c-coding-rule-1-5)

## Description

When defining macros that use the stringification (`#`) or token-pasting (`##`) operators, ensure that macro parameters used with `#` or `##` are not also used elsewhere in the macro body where they would be subject to macro replacement. Only define macros with multiple `#` or `##` operators if the order of expansion does not affect the result.

## Rationale / Effect if Violated

The `#` and `##` operators prevent macro expansion of their operands, while other uses of the same parameter in the macro body do expand. This inconsistency can produce unexpected results that differ across compilers, leading to subtle and hard-to-diagnose bugs.

## Good Example

```c
#define STRINGIFY(x) #x
#define CONCAT(a, b) a ## b

#define MAKE_LABEL(prefix, id) prefix ## id
```

## Bad Example

```c
#define BAD_MACRO(x) #x + x
/* 'x' is stringified in one place and expanded in another,
   leading to inconsistent behavior */
```

## Fix Suggestion

Ensure that macro parameters used with `#` or `##` are not used elsewhere in the same macro definition. If a parameter must be both stringified/pasted and expanded, use a helper macro to control the expansion order.
