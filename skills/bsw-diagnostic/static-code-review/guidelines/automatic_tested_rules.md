# [RB-CharacterSet] Only basic source character set shall be used

- **Severity**: warning
- **Review Severity**: minor
- **Category**: formatting
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB-CharacterSet](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-characterset)

## Description

Only characters from the C Standard (ISO 9899, §5.2.1) basic source character set shall be used in source files. This includes uppercase and lowercase Latin letters, digits, the space character, horizontal tab, vertical tab, form feed, newline, and the following graphic characters: `! " # % & ' ( ) * + , - . / : ; < = > ? [ \ ] ^ _ { | } ~`. Exceptions are allowed for `@`, `$`, and `` ` `` (backtick) when used in Doxygen documentation comments.

## Rationale / Effect if Violated

Non-standard characters may cause compilation issues across different toolchains, corrupt source files when transferred between systems with different encodings, or produce undefined behavior. They also hinder readability and automated processing of source code.

## Bad Example (if applicable)

```c
/* Comment with forbidden character: ä, ö, ü */
uint32 naïve_counter = 0u;
```

## Good Example (if applicable)

```c
/* Comment with only basic source characters */
uint32 naive_counter = 0u;

/** @copyright Robert Bosch GmbH */  /* @ is allowed in doxygen */
```

## Fix Suggestion

Replace all forbidden characters with equivalent characters from the basic source character set. For special characters in comments, use ASCII-safe descriptions or transliterations.

---

# [RB-CHeaderInclude] Do not use C headers directly in C++ files

- **Severity**: warning
- **Review Severity**: minor
- **Category**: includes
- **Analysis**: static
- **Applies to**: cpp
- **Source**: [RB-CHeaderInclude](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-cheaderinclude)

## Description

C++ source files (`.cpp`, `.hpp`) must not directly `#include` C header files (`.h`). Instead, use the corresponding C++ wrapper headers provided by `asw/baselib` or equivalent project-specific wrapper libraries. Direct inclusion of C headers in C++ code can lead to linkage issues, missing `extern "C"` guards, and namespace pollution.

## Rationale / Effect if Violated

C headers do not use C++ linkage conventions. Including them directly may cause symbol resolution errors, unintended name mangling, or subtle runtime bugs. Wrapper headers ensure proper `extern "C"` linkage and may provide type-safe C++ alternatives.

## Bad Example (if applicable)

```cpp
#include "legacy_module.h"   /* direct C header in C++ file — violates rule */
#include <string.h>          /* C standard header in C++ file */
```

## Good Example (if applicable)

```cpp
#include "asw/baselib/legacy_module.hpp"  /* C++ wrapper */
#include <cstring>                        /* C++ version of string.h */
```

## Fix Suggestion

Replace C header includes with their C++ wrapper equivalents from `asw/baselib`. For standard C headers, use the C++ versions (e.g., `<cstring>` instead of `<string.h>`, `<cstdint>` instead of `<stdint.h>`).

---

# [RB CopyrightFinder] Each source file needs a copyright statement

- **Severity**: warning
- **Review Severity**: minor
- **Category**: documentation
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB CopyrightFinder](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-copyrightfinder)

## Description

Every source file (`.c`, `.cpp`, `.h`, `.hpp`) must contain a copyright statement at the top of the file. The required format is:

```c
/** @copyright Robert Bosch GmbH reserves all rights including industrial
 *             property rights. All intellectual property rights, including
 *             copyright, of this computer program are owned by Robert Bosch
 *             GmbH and are protected by law. */
```

## Rationale / Effect if Violated

Missing copyright statements create legal ambiguity regarding intellectual property ownership. This can lead to compliance issues during audits, licensing disputes, or problems when sharing code with partners or third parties.

## Good Example (if applicable)

```c
/** @copyright Robert Bosch GmbH reserves all rights including industrial
 *             property rights. All intellectual property rights, including
 *             copyright, of this computer program are owned by Robert Bosch
 *             GmbH and are protected by law. */

#include "MyModule.h"
```

## Bad Example (if applicable)

```c
/* Missing copyright statement */
#include "MyModule.h"

void MyFunction(void) { }
```

## Fix Suggestion

Add the standard Bosch copyright comment block at the very top of the file, before any `#include` directives or code.

---

# [RB IncludeGuard] Include files need an include guard

- **Severity**: error
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB IncludeGuard](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-includeguard)

## Description

Every header file (`.h`, `.hpp`) must have an include guard using preprocessor macros. The guard macro name is derived from the filename by converting it to uppercase, replacing dots and dashes with underscores, and appending two trailing underscores. For example, `RBxxx_MyFile.h` becomes `RBXXX_MYFILE_H__`.

## Rationale / Effect if Violated

Without include guards, a header included multiple times (directly or transitively) will cause duplicate definitions, redeclaration errors, and increased compilation time. This is a fundamental requirement for correct C/C++ header design.

## Bad Example (if applicable)

```c
/* RBxxx_MyFile.h — missing include guard */
typedef struct {
    uint32 value;
} MyStruct;
```

## Good Example (if applicable)

```c
/* RBxxx_MyFile.h */
#ifndef RBXXX_MYFILE_H__
#define RBXXX_MYFILE_H__

typedef struct {
    uint32 value;
} MyStruct;

#endif /* RBXXX_MYFILE_H__ */
```

## Fix Suggestion

Add `#ifndef FILENAME_H__` / `#define FILENAME_H__` at the top of the header and `#endif` at the bottom. Derive the macro name from the filename: uppercase, dots and dashes replaced with underscores, two trailing underscores.

---

# [RB IncludeKind] Use "" for user headers and <> for system headers

- **Severity**: warning
- **Review Severity**: minor
- **Category**: includes
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB IncludeKind](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-includekind)

## Description

Use double quotes (`""`) for project/user header includes and angle brackets (`<>`) for system/standard library headers. Double-quoted includes search the directory of the including file first, then fall back to the compiler-configured search paths. Angle-bracket includes search only compiler-configured directories.

System headers that must use `<>` include: `assert.h`, `string.h`, `stddef.h`, `stdint.h`, `stdbool.h`, `limits.h`, and their C++ equivalents.

## Rationale / Effect if Violated

Using the wrong include syntax can cause the compiler to find the wrong file (e.g., a project-local file shadowing a system header), lead to portability issues across different build systems, or fail to find headers entirely in some configurations.

## Bad Example (if applicable)

```c
#include <MyProjectHeader.h>    /* project header with <> — wrong */
#include "stdint.h"             /* system header with "" — wrong */
```

## Good Example (if applicable)

```c
#include "MyProjectHeader.h"    /* project header with "" — correct */
#include <stdint.h>             /* system header with <> — correct */
```

## Fix Suggestion

Use `""` for all project-specific headers and `<>` for standard/system headers (`assert.h`, `string.h`, `stddef.h`, `stdint.h`, `stdbool.h`, `limits.h`, etc.).

---

# [RB MacroDefParentheses] Define macros with parentheses around expression

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB MacroDefParentheses](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-macrodefparentheses)

## Description

When defining an object-like macro whose replacement text is an expression, the entire expression must be enclosed in parentheses. This prevents unexpected operator precedence issues when the macro is used in a larger expression context.

## Rationale / Effect if Violated

Without parentheses, macro expansion in an expression context can produce incorrect results due to operator precedence. For example, `#define RB_TWO 3-1` used as `RB_TWO * 5` expands to `3-1 * 5 = -2` instead of the intended `(3-1) * 5 = 10`. These bugs are subtle and difficult to diagnose.

## Bad Example (if applicable)

```c
#define RB_TWO 3-1
#define OFFSET 10+5

uint32 result = RB_TWO * 5;   /* expands to 3-1*5 = -2, not 10 */
```

## Good Example (if applicable)

```c
#define RB_TWO (3-1)
#define OFFSET (10+5)

uint32 result = RB_TWO * 5;   /* expands to (3-1)*5 = 10, correct */
```

## Fix Suggestion

Wrap the entire macro replacement text in parentheses. For function-like macros, also parenthesize each parameter reference in the replacement text.

---

# [RB FunctionIdentifier] A function identifier shall only be used with a preceding &

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB FunctionIdentifier](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-functionidentifier)

## Description

A function identifier must always be used in one of two ways: called with `()` to invoke it, or preceded by `&` to take its address. A bare function identifier (without `()` or `&`) shall never appear in expressions. In C, a function name without `()` decays to a pointer implicitly, which can mask bugs where a function call was intended but forgotten.

## Rationale / Effect if Violated

Using a bare function identifier (e.g., `if (f)`) always evaluates to true (since function pointers are non-null for defined functions), which is almost certainly a bug — the programmer likely intended `if (f())`. This creates silent logic errors that are difficult to detect during testing.

## Bad Example (if applicable)

```c
if (IsReady) {          /* BUG: always true, should be IsReady() */
    StartProcess();
}

callback = MyFunction;  /* implicit address-of — unclear intent */
```

## Good Example (if applicable)

```c
if (IsReady()) {        /* correct: function is called */
    StartProcess();
}

callback = &MyFunction; /* explicit address-of — intent is clear */
```

## Fix Suggestion

If the intent is to call the function, add `()` with appropriate arguments. If the intent is to take the function's address, add the `&` operator explicitly.

---

# [RB NamingConvention] Source code identifiers shall follow RB Naming Convention

- **Severity**: warning
- **Review Severity**: minor
- **Category**: naming
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB NamingConvention](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-namingconvention)

## Description

All source code identifiers shall follow the Robert Bosch Naming Convention. The general pattern is:

```
[Namespace_Prefix]<IdentifierName>[_TypeIndication]
```

Key rules:
- **Global and static variables**: Must use the `RB_` prefix (or project-specific namespace prefix such as `RBXXX_`).
- **Local variables**: Must use the `l_` prefix.
- **Function names**: Must use the project namespace prefix (e.g., `RBxxx_FunctionName`).
- **Type indication suffixes** are used to indicate the type (e.g., `_u8`, `_s16`, `_f32`, `_b`).
- **Macros and constants**: All uppercase with underscores (e.g., `RBXXX_MAX_VALUE`).

## Rationale / Effect if Violated

Inconsistent naming makes code harder to read, understand, and maintain. The naming convention provides immediate visual cues about scope, type, and ownership of identifiers, which is critical in large embedded codebases with many contributors.

## Bad Example (if applicable)

```c
uint8 counter;                  /* global missing RB_ prefix */
void doSomething(void);         /* function missing namespace prefix */

void RBxxx_Process(void) {
    uint16 temp;                /* local missing l_ prefix */
}
```

## Good Example (if applicable)

```c
uint8 RBxxx_counter_u8;        /* global with prefix and type suffix */
void RBxxx_DoSomething(void);  /* function with namespace prefix */

void RBxxx_Process(void) {
    uint16 l_temp_u16;          /* local with l_ prefix and type suffix */
}
```

## Fix Suggestion

Apply the correct prefix (`RB_`, `RBXXX_`, `l_`, `rb_`) based on identifier scope and add type indication suffixes where required by convention.

---

# [RB NoExternInImpl] Do not use extern in implementation files

- **Severity**: warning
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB NoExternInImpl](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-noexterninimpl)

## Description

The `extern` keyword for variable or function declarations must not appear in implementation files (`.c`, `.cpp`). All `extern` declarations belong in header files (`.h`, `.hpp`), which are then included by the implementation files that need them. This ensures a single point of declaration and avoids mismatches between declaration and definition.

## Rationale / Effect if Violated

Placing `extern` declarations in implementation files bypasses the header-based interface contract. If the declaration in the `.c` file does not match the actual definition (e.g., wrong type or signature), the compiler cannot detect the mismatch, leading to undefined behavior at link time or runtime.

## Bad Example (if applicable)

```c
/* MyModule.c */
extern uint32 g_SharedCounter;     /* extern in .c file — violates rule */
extern void OtherModule_Init(void); /* extern in .c file — violates rule */
```

## Good Example (if applicable)

```c
/* MyModule.c */
#include "OtherModule.h"  /* declarations come from the header */
```

## Fix Suggestion

Move all `extern` declarations to the appropriate header file and include that header in the implementation file.

---

# [RB NoFunctionDefinitionInHeader] Do not define functions in header files

- **Severity**: warning
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB NoFunctionDefinitionInHeader](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-nofunctiondefinitioninheader)

## Description

Function definitions (i.e., functions with a body) must not appear in header files (`.h`, `.hpp`). Headers should contain only declarations (prototypes). The function body must be placed in the corresponding implementation file (`.c`, `.cpp`). The only exception is `static inline` functions, which must be defined in the header to allow the compiler to inline them across translation units.

## Rationale / Effect if Violated

Defining non-inline functions in headers causes multiple-definition linker errors when the header is included in more than one translation unit. Even if guarded by include guards, each translation unit gets its own copy of the function, violating the One Definition Rule (ODR).

## Bad Example (if applicable)

```c
/* MyModule.h */
#ifndef MYMODULE_H__
#define MYMODULE_H__

void MyModule_Init(void) {    /* function definition in header — violates rule */
    counter = 0u;
}

#endif
```

## Good Example (if applicable)

```c
/* MyModule.h */
#ifndef MYMODULE_H__
#define MYMODULE_H__

void MyModule_Init(void);     /* declaration only */

static inline uint32 MyModule_GetMax(uint32 a, uint32 b) {
    return (a > b) ? a : b;   /* static inline is allowed */
}

#endif

/* MyModule.c */
#include "MyModule.h"

void MyModule_Init(void) {    /* definition in .c file — correct */
    counter = 0u;
}
```

## Fix Suggestion

Move the function definition (body) to the corresponding `.c` or `.cpp` implementation file. Keep only the function prototype (declaration) in the header.

---

# [RB NoVariableDefinitionInHeader] Do not define variables in header files

- **Severity**: warning
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB NoVariableDefinitionInHeader](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-novariabledefinitioninheader)

## Description

Variable definitions (i.e., variables that allocate storage) must not appear in header files (`.h`, `.hpp`). Headers may only contain `extern` declarations of variables. The actual variable definition must be in the corresponding implementation file (`.c`, `.cpp`).

## Rationale / Effect if Violated

Defining a variable in a header causes each translation unit that includes the header to create its own copy of the variable. This leads to multiple-definition linker errors or, worse, each module silently operating on its own independent copy when the intent was a shared variable.

## Bad Example (if applicable)

```c
/* MyModule.h */
uint32 g_Counter = 0u;       /* variable definition in header — violates rule */
```

## Good Example (if applicable)

```c
/* MyModule.h */
extern uint32 g_Counter;     /* declaration only */

/* MyModule.c */
uint32 g_Counter = 0u;       /* definition in .c file — correct */
```

## Fix Suggestion

Move the variable definition to the corresponding `.c` or `.cpp` file. In the header, use an `extern` declaration only.

---

# [RB NoWhitespaceMemberSelection] No whitespace in member selection

- **Severity**: info
- **Review Severity**: minor
- **Category**: formatting
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB NoWhitespaceMemberSelection](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-nowhitespacememberselection)

## Description

There must be no whitespace around the member selection operators `.` (dot) and `->` (arrow). The operator must be immediately adjacent to both the object/pointer and the member name.

## Rationale / Effect if Violated

Whitespace around member selection operators reduces readability and deviates from universally accepted C/C++ style. It can also cause confusion about operator precedence in complex expressions.

## Bad Example (if applicable)

```c
value = foo . bar;
result = ptr -> member;
data = obj .field1 -> field2;
```

## Good Example (if applicable)

```c
value = foo.bar;
result = ptr->member;
data = obj.field1->field2;
```

## Fix Suggestion

Remove all whitespace immediately before and after `.` and `->` operators.

---

# [RB NoWhitespaceUnaryOperator] No whitespace after unary operator

- **Severity**: info
- **Review Severity**: minor
- **Category**: formatting
- **Analysis**: static
- **Applies to**: both
- **Source**: [RB NoWhitespaceUnaryOperator](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-nowhitespaceunaryoperator)

## Description

There must be no whitespace between a unary operator and its operand. This applies to unary operators such as `!`, `~`, `++`, `--`, unary `-`, unary `+`, `*` (dereference), and `&` (address-of).

## Rationale / Effect if Violated

Whitespace between a unary operator and its operand reduces readability and can cause confusion about the intended operation, especially in complex expressions where it may be misread as a binary operator.

## Bad Example (if applicable)

```c
if (! flag) { }
++ i;
value = - x;
ptr = & variable;
```

## Good Example (if applicable)

```c
if (!flag) { }
++i;
value = -x;
ptr = &variable;
```

## Fix Suggestion

Remove the whitespace between the unary operator and its operand.

---

# [RB ExplicitCast] Comment the reason of an explicit cast

- **Severity**: warning
- **Review Severity**: minor
- **Category**: documentation
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB ExplicitCast](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-explicitcast)

## Description

Every explicit type cast in the code must be accompanied by a comment that includes the keyword **"cast"** and explains the reason why the cast is necessary. This applies to all C-style casts and C++ cast operators (`static_cast`, `reinterpret_cast`, `const_cast`, `dynamic_cast`).

## Rationale / Effect if Violated

Explicit casts override the type system and suppress compiler warnings. Without a documented reason, future maintainers cannot determine whether the cast is intentional and correct, or whether it masks a design flaw or type mismatch. Requiring a comment forces the author to justify the cast.

## Bad Example (if applicable)

```c
uint16 value = (uint16)raw_data;           /* no comment explaining the cast */
float32 ratio = (float32)count / total;    /* no comment explaining the cast */
```

## Good Example (if applicable)

```c
/* cast: raw_data is guaranteed to be within uint16 range by protocol spec */
uint16 value = (uint16)raw_data;

/* cast: integer-to-float conversion needed for ratio calculation */
float32 ratio = (float32)count / (float32)total;
```

## Fix Suggestion

Add a comment before or on the same line as each explicit cast. The comment must contain the word "cast" and explain why the cast is necessary and safe.

---

# [RB-ForbiddenMacros] Use of forbidden macro

- **Severity**: error
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB-ForbiddenMacros](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-forbiddenmacros)

## Description

Do not use the generic `MIN`, `MAX`, `A_MIN_AB`, or `A_MAX_AB` macros. These macros are not type-safe and can cause double-evaluation side effects. Instead, use the type-safe inline functions provided in `RB_MathHelpers.h`:

| Forbidden Macro | Replacement Function (examples) |
|---|---|
| `MIN(a, b)` | `RB_Min_u8(a, b)`, `RB_Min_s16(a, b)`, `RB_Min_f32(a, b)` |
| `MAX(a, b)` | `RB_Max_u8(a, b)`, `RB_Max_s16(a, b)`, `RB_Max_f32(a, b)` |
| `A_MIN_AB(a, b)` | `RB_Clamp_*` functions |
| `A_MAX_AB(a, b)` | `RB_Clamp_*` functions |

## Rationale / Effect if Violated

Generic MIN/MAX macros evaluate their arguments multiple times, which causes bugs when arguments have side effects (e.g., `MIN(x++, y)` increments `x` twice). They also provide no type checking, leading to silent implicit conversions and potential overflow.

## Bad Example (if applicable)

```c
uint8 smaller = MIN(sensorA, sensorB);
sint16 clamped = A_MIN_AB(value, upper_limit);
```

## Good Example (if applicable)

```c
uint8 smaller = RB_Min_u8(sensorA, sensorB);
sint16 clamped = RB_Min_s16(value, upper_limit);
```

## Fix Suggestion

Replace `MIN`/`MAX`/`A_MIN_AB`/`A_MAX_AB` macros with the corresponding type-safe `RB_Min_*`, `RB_Max_*`, or `RB_Clamp_*` functions from `RB_MathHelpers.h`, matching the operand types.

---

# [Generic-NoGlobalVariable] Global variables shall not be used

- **Severity**: warning
- **Review Severity**: minor
- **Category**: design
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Generic-NoGlobalVariable](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#generic-noglobalvariable)

## Description

Global variables (variables with external linkage defined at file scope) shall not be used. Global mutable state creates hidden dependencies between modules, makes code harder to test, and introduces risks for concurrency issues. Instead, use encapsulation patterns such as static file-scope variables with accessor functions.

## Rationale / Effect if Violated

Global variables create tight coupling between modules, make it difficult to reason about program state, and hinder unit testing because global state must be set up and torn down for each test. In concurrent or interrupt-driven systems, unprotected global variables are a source of race conditions.

## Bad Example (if applicable)

```c
/* MyModule.c */
uint32 g_SystemState = 0u;  /* globally visible — any module can modify */
```

## Good Example (if applicable)

```c
/* MyModule.c */
static uint32 s_SystemState = 0u;  /* file-scope, not visible externally */

uint32 MyModule_GetState(void) {
    return s_SystemState;
}

void MyModule_SetState(uint32 newState) {
    s_SystemState = newState;
}
```

## Fix Suggestion

Encapsulate the global variable as a `static` file-scope variable and provide accessor functions (`Get`/`Set`) for controlled access from other modules.

---

# [RB-EnumCheck] Enum values shall be in non-negative 32-bit range

- **Severity**: error
- **Review Severity**: minor
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB-EnumCheck](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-enumcheck)

## Description

All enumerator values in an `enum` must be within the non-negative 32-bit integer range **[0 .. 2147483647]** (i.e., `[0 .. INT32_MAX]`). Negative enumerator values are forbidden. Enum values must not be assigned values outside the representable range. Error states or invalid sentinel values should be placed at the end of the enumeration without an explicit assigned value, relying on the natural increment.

## Rationale / Effect if Violated

The C standard allows the underlying type of an `enum` to be implementation-defined. Negative values or values exceeding `INT32_MAX` can cause portability issues, unexpected sign extension, or undefined behavior when stored in unsigned integer types. Consistent non-negative ranges ensure predictable behavior across compilers and platforms.

## Bad Example (if applicable)

```c
typedef enum {
    RBXXX_State_Init = 0,
    RBXXX_State_Running = 1,
    RBXXX_State_Error = -1       /* negative value — violates rule */
} RBXXX_State_t;
```

## Good Example (if applicable)

```c
typedef enum {
    RBXXX_State_Init = 0,
    RBXXX_State_Running,
    RBXXX_State_Stopped,
    RBXXX_State_Error            /* placed at end, no explicit negative value */
} RBXXX_State_t;
```

## Fix Suggestion

Remove negative enumerator values. Place error or sentinel states at the end of the enumeration without assigning explicit negative values.

---

# [RB MissingReason] Cast to void and volatile usage shall be commented

- **Severity**: warning
- **Review Severity**: minor
- **Category**: documentation
- **Analysis**: llm
- **Applies to**: both
- **Source**: [RB MissingReason](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#rb-missingreason)

## Description

Two constructs require mandatory comments:

1. **Cast to `(void)`**: When a function's return value is intentionally ignored by casting to `(void)`, a comment containing the phrase **"return value"** must explain why the return value is not needed.

2. **`volatile` qualifier**: Every use of the `volatile` qualifier on a variable must be accompanied by a comment explaining why `volatile` is necessary (e.g., hardware register access, shared memory with ISR, etc.).

## Rationale / Effect if Violated

Casting to `(void)` suppresses compiler warnings about unused return values. Without a comment, reviewers cannot determine whether the ignored return value is intentional or an oversight. Similarly, `volatile` disables important compiler optimizations; unjustified use wastes performance, while missing `volatile` on truly volatile data causes incorrect optimization.

## Bad Example (if applicable)

```c
(void)RB_ClearByReadXXX();              /* missing comment with "return value" */

volatile uint32 sensor_reg;             /* missing comment explaining volatile */
```

## Good Example (if applicable)

```c
/* return value not required, register is cleared by read access */
(void)RB_ClearByReadXXX();

/* volatile: hardware register mapped to memory, value may change externally */
volatile uint32 sensor_reg;
```

## Fix Suggestion

For `(void)` casts, add a comment containing "return value" that explains why the return value is intentionally discarded. For `volatile` qualifiers, add a comment explaining why the variable must be declared volatile.
