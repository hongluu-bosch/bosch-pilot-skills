# [Coding Rule 1.1] Keep pairs in the same file

- **Severity**: error
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 1.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-1-1)

## Description

Keep all elements of a control structure in the same file. The closing brace must appear in the same file as the opening brace, `else` must be in the same file as its corresponding `if`, all `case` labels must be in the same file as the `switch`, and `#endif` must be in the same file as the matching `#if` / `#ifdef` / `#ifndef`.

## Rationale / Effect if Violated

Split control structures across files produce confusing, unmaintainable code and can hide logic errors. Readers cannot verify the correctness of a branch or conditional block without locating the matching construct in another file.

## Good Example

```c
#ifdef FEATURE_X
void FeatureX_Init(void) {
    if (config.enabled) {
        StartFeatureX();
    } else {
        StopFeatureX();
    }
}
#endif
```

## Bad Example

```c
/* file1.c */
#ifdef FEATURE_X
void FeatureX_Init(void) {
    if (config.enabled) {
        StartFeatureX();

/* file2.c  -- BAD: else and closing braces belong in file1.c */
    } else {
        StopFeatureX();
    }
}
#endif
```

## Fix Suggestion

Move the matching control structure element (closing brace, `else`, `case`, `#endif`) into the same file as its opening counterpart.

---

# [Coding Rule 1.2] Use a prefix for externally visible identifiers

- **Severity**: warning
- **Review Severity**: minor
- **Category**: naming
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 1.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-1-2)

## Description

Functions, global variables, exported macros, and type names that are visible outside their translation unit shall carry a short prefix indicating the component they belong to. The default prefixes are `RB_` for macros and `rb_` for all other identifiers (functions, variables, types). Do not use the prefixes `RBX_` or `rbx_`, as these are reserved for exchangeable software.

## Rationale / Effect if Violated

Without a component prefix, identifiers risk name collisions across modules, making integration difficult and error-prone. Reserved prefixes (`RBX_` / `rbx_`) may conflict with exchangeable software layers.

## Good Example

```c
#define RB_MAX_CHANNELS  16u

void rb_Init(void);
uint32 rb_channelCount;
typedef struct rb_Config_tag { uint8 id; } rb_Config;
```

## Bad Example

```c
#define MAX_CHANNELS  16u          /* BAD: missing RB_ prefix */
#define RBX_MAX_CHANNELS  16u     /* BAD: RBX_ is reserved */

void Init(void);                   /* BAD: missing rb_ prefix */
uint32 channelCount;               /* BAD: missing rb_ prefix */
```

## Fix Suggestion

Add the appropriate `RB_` prefix (for macros) or `rb_` prefix (for functions, variables, types) to the identifier. Never use `RBX_` or `rbx_`.

---

# [Coding Rule 1.3] Provide include-protection

- **Severity**: error
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: hybrid
- **Applies to**: both
- **Source**: [Coding Rule 1.3](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-1-3)

## Description

Each header file must have include protection (an include guard) to prevent multiple-inclusion errors. Use a unique macro name derived from the file name. The convention is `NAME_H__` for a header named `name.h`. The guard consists of `#ifndef`, `#define`, and `#endif` surrounding the entire header content.

## Rationale / Effect if Violated

Without include guards, headers included multiple times in a translation unit cause duplicate definitions, compilation errors, or increased compile times. Non-unique guard names can silently suppress the contents of a different header.

## Good Example

```c
/* foo.h */
#ifndef FOO_H__
#define FOO_H__

void rb_Foo_Init(void);

#endif /* FOO_H__ */
```

## Bad Example

```c
/* foo.h -- BAD: no include guard */
void rb_Foo_Init(void);
```

## Fix Suggestion

Add `#ifndef FILENAME_H__` / `#define FILENAME_H__` at the top of the header and `#endif /* FILENAME_H__ */` at the bottom.

---

# [Coding Rule 1.4] Provide case identical includes

- **Severity**: warning
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 1.4](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-1-4)

## Description

The casing of the string in an `#include` directive must exactly match the casing of the actual file name on disk. Although some file systems are case-insensitive, builds on case-sensitive systems will fail if the casing differs.

## Rationale / Effect if Violated

Mismatched casing in `#include` paths causes build failures on case-sensitive file systems (e.g., Linux), even though the same code may compile on case-insensitive systems (e.g., Windows). This leads to portability issues.

## Good Example

```c
#include "Rte_Type.h"   /* matches actual file name Rte_Type.h */
#include "rb_config.h"  /* matches actual file name rb_config.h */
```

## Bad Example

```c
#include "rte_type.h"   /* BAD: actual file is Rte_Type.h */
#include "RB_Config.h"  /* BAD: actual file is rb_config.h */
```

## Fix Suggestion

Correct the casing of the `#include` path to exactly match the actual file name on disk.

---

# [Coding Rule 2.2] Use //-comments with caution

- **Severity**: warning
- **Review Severity**: major
- **Category**: comments
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 2.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-2-2)

## Description

Use C-style comments (`/* */`) for SPECIAL_COMMENTS such as `MEASUREMENT` and `NO_TOOL_SCAN`. Do not use nested comments. Do not place a backslash (`\`) at the end of a `//` comment, as this extends the comment to the next line and silently hides code.

## Rationale / Effect if Violated

A backslash at the end of a `//` comment causes the next source line to be treated as part of the comment, silently hiding executable code. Nested comments can lead to unexpected comment boundaries. Using `//` for special comments may cause tools to fail to recognize them.

## Good Example

```c
/* MEASUREMENT */
uint32 rb_measValue;

/* This is a safe multi-line comment
   spanning two lines */
if (condition) {
    DoWork();
}
```

## Bad Example

```c
// MEASUREMENT               /* BAD: special comment must use C-style */
uint32 rb_measValue;

// toggle feature flag \     /* BAD: backslash extends comment */
rb_featureEnabled = TRUE;    /* this line is silently commented out! */
```

## Fix Suggestion

Replace `//` comments with `/* */` for special comments (`MEASUREMENT`, `NO_TOOL_SCAN`). Remove trailing backslashes from `//` comments.

---

# [Coding Rule 3.1] Do not use the implicit conversion of function to pointer

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 3.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-3-1)

## Description

When referring to the address of a function, explicitly use the address-of operator (`&f`) rather than the bare function name (`f`). Without parentheses, a bare function name decays to a pointer, which can be confused with a function call. In particular, `if(f)` always evaluates to true for a valid function, which is almost certainly a bug.

## Rationale / Effect if Violated

Using a bare function name where a call was intended silently compiles but produces incorrect behavior. For example, `if(f)` is always true and never actually calls `f`. This leads to hard-to-find logic errors.

## Good Example

```c
if (f()) {           /* correct: calls the function */
    DoWork();
}

callback = &f;       /* correct: explicitly takes address */
```

## Bad Example

```c
if (f) {             /* BAD: always true, does not call f */
    DoWork();
}

callback = f;        /* BAD: implicit conversion to pointer */
```

## Fix Suggestion

Use `&f` when taking a function's address, or `f()` when calling the function.

---

# [Coding Rule 3.2] Do not shift variables further than its bit size

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 3.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-3-2)

## Description

A variable shall not be shifted by an amount equal to or greater than its bit width. For example, a `uint8` (8 bits) may only be shifted by 0 through 7. Shifting by a negative value is also undefined behavior. When the shift amount is a variable, its range must be verified at runtime.

## Rationale / Effect if Violated

Shifting a value beyond its bit size or by a negative amount is undefined behavior per the C/C++ standards. The result is unpredictable and may vary across compilers, optimization levels, and target architectures.

## Good Example

```c
uint8 value = 1u;
uint8 result = value << 7u;   /* OK: shift within [0, 7] for uint8 */

uint32 mask = 1u;
uint32 shifted = mask << 31u; /* OK: shift within [0, 31] for uint32 */
```

## Bad Example

```c
uint8 value = 1u;
uint8 result = value << 8u;   /* BAD: shift equals bit size of uint8 */

uint32 mask = 1u;
uint32 shifted = mask << 32u; /* BAD: shift equals bit size of uint32 */

int8 x = 1;
int8 y = x << -1;            /* BAD: negative shift amount */
```

## Fix Suggestion

Ensure the shift amount is within `[0, bit_size - 1]` for the variable's type. Add runtime checks or assertions when the shift amount is a variable.

---

# [Coding Rule 3.3] Do not access an array outside of its bound

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 3.3](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-3-3)

## Description

Every array access must be within the declared bounds of the array. When the index is computed at runtime (from input, calculation, or loop variable), implement a range check or assertion before the access to guarantee the index is valid.

## Rationale / Effect if Violated

Out-of-bounds array access is undefined behavior. It can corrupt adjacent memory, cause crashes, introduce security vulnerabilities, or produce silently wrong results that are extremely difficult to debug.

## Good Example

```c
uint8 buffer[10];
uint8 index = GetIndex();

if (index < 10u) {
    buffer[index] = 0xFFu;  /* OK: bounds checked */
}
```

## Bad Example

```c
uint8 buffer[10];
uint8 index = GetIndex();

buffer[index] = 0xFFu;  /* BAD: index could be >= 10 */
```

## Fix Suggestion

Add a bounds check before every array access where the index is not provably within range. Use assertions during development and defensive checks in production code.

---

# [Coding Rule 3.4] Use memcpy, memmove and memcmp only with pointers of compatible types

- **Severity**: warning
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 3.4](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-3-4)

## Description

`memcpy` copies raw bytes including padding, so it may only be used between objects of the same type within the same program. For data that crosses boundaries (e.g., NvM callbacks), use `RB_Serialize()` / `RB_Deserialize()` instead. `memcmp` shall not be used because padding bytes have indeterminate values and produce unreliable comparisons.

## Rationale / Effect if Violated

Using `memcpy` between incompatible types or across program boundaries copies padding bytes, producing corrupt or misaligned data. `memcmp` on structs with padding yields false negatives because padding content is indeterminate.

## Good Example

```c
rb_Config srcConfig;
rb_Config dstConfig;
(void)memcpy((void*)&dstConfig, (const void*)&srcConfig, sizeof(rb_Config));

/* For NvM callbacks, use serialization */
RB_Serialize(&nvmBuffer, &srcConfig, sizeof(rb_Config));
RB_Deserialize(&dstConfig, &nvmBuffer, sizeof(rb_Config));
```

## Bad Example

```c
rb_Config config;
uint8 rawBuffer[sizeof(rb_Config)];

/* BAD: memcpy between incompatible types across boundary */
(void)memcpy(rawBuffer, &config, sizeof(rb_Config));

/* BAD: memcmp on structs with potential padding */
if (memcmp(&config1, &config2, sizeof(rb_Config)) == 0) {
    /* unreliable comparison */
}
```

## Fix Suggestion

Use `RB_Serialize()` / `RB_Deserialize()` for NvM callbacks and cross-boundary data transfers. Do not use `memcmp` on structs. Cast pointers to `void*` for MISRA compliance when using `memcpy` with compatible types.

---

# [Coding Rule 3.5] Make sure that the integer value cast to void* is a valid address

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 3.5](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-3-5)

## Description

When casting an integer (e.g., `uint32`) to a pointer (`void*`) for direct hardware register access, ensure that the target address physically exists on the hardware, is accessible to the software (not protected or restricted), and is reserved for the intended use case.

## Rationale / Effect if Violated

Casting an arbitrary integer to a pointer and dereferencing it accesses potentially unmapped, protected, or unrelated memory. This can cause bus faults, corrupt hardware state, or introduce security vulnerabilities.

## Good Example

```c
/* Address 0xFFFF0000 is documented in the hardware manual
   as the control register for peripheral X, reserved for this driver */
#define RB_PERIPH_X_CTRL_REG  ((volatile uint32*)0xFFFF0000u)

uint32 regValue = *RB_PERIPH_X_CTRL_REG;
```

## Bad Example

```c
/* BAD: arbitrary address with no verification */
uint32 addr = GetAddressFromConfig();
uint32 value = *((volatile uint32*)addr);  /* may not be a valid HW register */
```

## Fix Suggestion

Verify the address against hardware documentation. Ensure the address exists, is accessible at the current privilege level, and is reserved for the intended use case. Prefer named macros for hardware register addresses.

---

# [Coding Rule 3.6] Use large enough integers to hold array subscripts

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 3.6](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-3-6)

## Description

Use integer types large enough to represent all valid index values for a given array, especially when array sizes are configurable or large. Be cautious with unsigned integer subtraction, which wraps around to a large positive value rather than becoming negative.

## Rationale / Effect if Violated

An undersized index type can overflow or truncate, producing incorrect array accesses. Unsigned subtraction wrapping is a common source of out-of-bounds bugs when an index is decremented past zero.

## Good Example

```c
uint32 rb_largeArray[65536];
uint32 idx;  /* large enough for all valid indices */

for (idx = 0u; idx < 65536u; idx++) {
    rb_largeArray[idx] = 0u;
}
```

## Bad Example

```c
uint32 rb_largeArray[65536];
uint8 idx;  /* BAD: uint8 max is 255, cannot index beyond 255 */

for (idx = 0u; idx < 65536u; idx++) {  /* idx wraps at 256 */
    rb_largeArray[idx] = 0u;
}
```

## Fix Suggestion

Use `size_t` or an appropriately sized unsigned integer type for array subscripts. Audit all index variables when array sizes change. Guard unsigned subtraction to avoid wraparound.

---

# [Coding Rule 4.1] Consider concurrency

- **Severity**: error
- **Review Severity**: critical
- **Category**: concurrency
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-1)

## Description

Embedded code runs concurrently through interrupt service routines, preemptive tasks, and multi-core execution. All shared resources — global variables, shared buffers, messages, hardware registers — must be accessed in a thread-safe manner using appropriate locking mechanisms (critical sections, mutexes, atomic operations).

## Rationale / Effect if Violated

Unsynchronized access to shared resources causes data races, torn reads/writes, lost updates, and other concurrency bugs that are intermittent, timing-dependent, and extremely difficult to reproduce and diagnose.

## Good Example

```c
static uint32 rb_sharedCounter;

void rb_IncrementCounter(void) {
    EnterCriticalSection();
    rb_sharedCounter++;
    LeaveCriticalSection();
}

uint32 rb_GetCounter(void) {
    uint32 localCopy;
    EnterCriticalSection();
    localCopy = rb_sharedCounter;
    LeaveCriticalSection();
    return localCopy;
}
```

## Bad Example

```c
static uint32 rb_sharedCounter;

/* BAD: no protection — can be interrupted mid-update */
void rb_IncrementCounter(void) {
    rb_sharedCounter++;
}

/* BAD: read may see a partially updated value */
uint32 rb_GetCounter(void) {
    return rb_sharedCounter;
}
```

## Fix Suggestion

Protect shared resources with appropriate locking mechanisms (critical sections, mutexes, spinlocks, or atomic operations) depending on the execution context.

---

# [Coding Rule 4.2] Check the validity of values received from external sources

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-2)

## Description

Data received from external sources (communication buses, sensors, configuration files, other software components) must be validated before use. Specifically check: array indices against bounds, loop iteration counts, divisors for zero, memory allocation sizes, and pointer validity.

## Rationale / Effect if Violated

Unvalidated external data can cause out-of-bounds access, infinite loops, division by zero, buffer overflows, and other undefined behaviors. Attackers or faulty components can exploit missing validation to compromise system safety.

## Good Example

```c
void rb_ProcessMessage(const rb_Message* msg) {
    if (msg == NULL) {
        return;
    }
    if (msg->index >= RB_MAX_ENTRIES) {
        rb_ReportError(RB_ERR_INVALID_INDEX);
        return;
    }
    rb_entries[msg->index] = msg->value;
}
```

## Bad Example

```c
void rb_ProcessMessage(const rb_Message* msg) {
    /* BAD: no NULL check, no bounds check */
    rb_entries[msg->index] = msg->value;
}
```

## Fix Suggestion

Add validation checks for all data received from external sources before use: NULL-check pointers, range-check indices, verify divisors are non-zero, and validate sizes.

---

# [Coding Rule 4.3] Do not hard code sensitive information

- **Severity**: error
- **Review Severity**: critical
- **Category**: security
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.3](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-3)

## Description

Do not embed sensitive information in source code, including cryptographic keys, passwords, secret tokens, and their sizes. Sensitive data must be stored in secure, non-source-code configuration mechanisms.

## Rationale / Effect if Violated

Hard-coded secrets are visible to anyone with access to the source code, binary, or version control history. They cannot be rotated without rebuilding the software and violate security best practices and compliance requirements.

## Good Example

```c
/* Key is provisioned at runtime from secure storage */
uint8 rb_cryptoKey[RB_KEY_LENGTH];

void rb_LoadKey(void) {
    RB_SecureStorage_Read(RB_KEY_SLOT_ID, rb_cryptoKey, RB_KEY_LENGTH);
}
```

## Bad Example

```c
/* BAD: secret key hard-coded in source */
static const uint8 rb_cryptoKey[] = { 0x2B, 0x7E, 0x15, 0x16,
    0x28, 0xAE, 0xD2, 0xA6, 0xAB, 0xF7, 0x15, 0x88, 0x09, 0xCF, 0x4F, 0x3C };

/* BAD: password hard-coded */
static const char* rb_password = "admin123";
```

## Fix Suggestion

Store sensitive data in secure configuration (secure storage, HSM, key management service). Load it at runtime through secure APIs. Never commit secrets to version control.

---

# [Coding Rule 4.4] Do not use recursions

- **Severity**: error
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.4](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-4)

## Description

Neither direct recursion (a function calling itself) nor indirect recursion (a cycle of function calls, e.g., A calls B calls A) is permitted. The call graph must be acyclic.

## Rationale / Effect if Violated

Recursion consumes stack space proportional to the recursion depth, which is often unpredictable. In embedded systems with limited stack, this can cause stack overflow, memory corruption, and system crashes. Static analysis tools cannot determine worst-case stack usage for recursive code.

## Good Example

```c
/* Iterative factorial */
uint32 rb_Factorial(uint32 n) {
    uint32 result = 1u;
    uint32 i;
    for (i = 2u; i <= n; i++) {
        result *= i;
    }
    return result;
}
```

## Bad Example

```c
/* BAD: direct recursion */
uint32 rb_Factorial(uint32 n) {
    if (n <= 1u) {
        return 1u;
    }
    return n * rb_Factorial(n - 1u);  /* recursive call */
}
```

## Fix Suggestion

Replace recursive algorithms with iterative equivalents using explicit loops and, if needed, a manually managed stack or work queue.

---

# [Coding Rule 4.5] Pay special attention to constructs predestinated for runtime errors

- **Severity**: warning
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.5](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-5)

## Description

Exercise special care with constructs that are prone to runtime errors:
- **Arithmetic errors**: integer overflow, underflow, division by zero, loss of precision in type conversions.
- **Pointer arithmetic**: results must remain within the bounds of the originating array (or one past the end).
- **Pointer dereferencing**: always verify that a pointer is not NULL before dereferencing.

## Rationale / Effect if Violated

These constructs are the most common sources of undefined behavior and runtime faults in C/C++ programs. Failures are often intermittent and dependent on input data, making them difficult to detect during testing.

## Good Example

```c
uint32 rb_SafeDivide(uint32 dividend, uint32 divisor) {
    if (divisor == 0u) {
        rb_ReportError(RB_ERR_DIV_ZERO);
        return 0u;
    }
    return dividend / divisor;
}

void rb_ProcessData(const uint8* data) {
    if (data != NULL) {
        /* safe to dereference */
        rb_HandleByte(*data);
    }
}
```

## Bad Example

```c
/* BAD: no check for division by zero */
uint32 rb_Divide(uint32 dividend, uint32 divisor) {
    return dividend / divisor;
}

/* BAD: no NULL check before dereference */
void rb_ProcessData(const uint8* data) {
    rb_HandleByte(*data);
}
```

## Fix Suggestion

Add runtime checks for arithmetic operations (especially division), validate pointer bounds before arithmetic, and check for NULL before every pointer dereference.

---

# [Coding Rule 4.6] If a function returns error information, test it

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: project-specific

## Description

If a struct is later sent, published, stored, committed, or written back as a whole object, the code shall not update only a subset of its members unless one of these is true in the same path:

1. The current complete struct state has already been restored or received.
2. All members of the struct are fully initialized before the whole-object output.

This rule applies to message structs, buffers, payload structs, and other aggregate objects whose full contents are emitted by a later API or macro call.

## Rationale / Effect if Violated

Partial updates on an aggregate that is later emitted as a whole can silently propagate stale, unintended, or undefined values in members that were not refreshed in the current path. This produces a direct functional defect: the outward-facing message or stored object no longer represents the intended state of the current logic.

## Good Example

```c
rb_MessageType message;

/* OK: restore the full current state first, then change only the intended member */
RB_MessageReceive(&message);
message.qualifier = RB_QUALIFIER_INVALID;
RB_MessageSend(&message);
```

```c
rb_MessageType message;

/* OK: initialize every member before whole-object output */
message.value = 0u;
message.qualifier = RB_QUALIFIER_INVALID;
message.timestamp = 0u;
RB_MessageSend(&message);
```

## Bad Example

```c
rb_MessageType message;

/* BAD: only one member is updated before the whole struct is sent */
message.qualifier = RB_QUALIFIER_INVALID;
RB_MessageSend(&message);
```

```c
rb_PayloadType payload;

/* BAD: unchanged members may carry stale or unintended values */
payload.status = RB_STATUS_TIMEOUT;
RB_StorePayload(&payload);
```

## Trigger Template for Reviewers

Flag this rule when the following pattern appears in the same control-flow path:

1. A local struct of type `<AggregateType>` is updated by assigning only one or a few of its members.
2. The same aggregate is then emitted as a whole via a send/store/publish macro or function (for example: `SendMESGDef(<Struct>)`, `RBMESG_SendMESGDef(<Struct>)`, `RB_StorePayload(&<Struct>)`, or similar whole-object APIs).
3. The code does not show either: `(a)` a preceding `RcvMESGDef` / `RB_MessageReceive` / restore of the full struct state, or `(b)` explicit initialization of every member before the output call.

Required fields in the finding:

- **Function**: function where the partial update occurs.
- **Location**: line numbers of the partial assignment and the whole-object output call.
- **Evidence**: list the member(s) that were assigned and the output call; note which members were not refreshed in the current path.
- **Functional Impact**: explain that stale or indeterminate values in unrefreshed members will be sent/stored as part of the whole object.
- **Reasoning**: cite this rule and specify whether exception (1) or (2) applies; if neither applies, the rule is triggered at major severity.
- **Suggested Action**: either restore the full struct state before the partial update, initialize every member explicitly, or document the applicable exception with a code comment.

## Fix Suggestion

Before partially updating a struct that will be emitted as a whole, either:

1. Restore or receive the full current struct state first.
2. Fully initialize every member in the same path before the output call.

Do not rely on untouched members retaining correct values unless the code in the same path proves that the full aggregate state is valid.

---

# [Coding Rule 4.6] If a function returns error information, test it

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.6](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-6)

## Description

When a function returns error information (via return value or output parameter), the caller must test and handle it. If the return value is intentionally ignored, explicitly cast to `(void)` with a comment explaining why. This rule also applies to error status returned by reference through pointer parameters.

## Rationale / Effect if Violated

Ignoring error returns allows failures to propagate silently, leading to corrupted state, incorrect results, or system malfunction. Unhandled errors are a frequent root cause of field failures.

## Good Example

```c
Std_ReturnType result = rb_ReadSensor(&sensorValue);
if (result != E_OK) {
    rb_ReportError(RB_ERR_SENSOR_READ);
    return;
}

/* Intentionally ignoring return value — logging is best-effort */
(void)rb_LogEvent(RB_EVT_STARTUP);
```

## Bad Example

```c
/* BAD: return value ignored without (void) cast */
rb_ReadSensor(&sensorValue);

/* BAD: error status output parameter not checked */
rb_GetConfig(&config, &errorStatus);
/* errorStatus never tested */
```

## Fix Suggestion

Check every function return value for errors. If intentionally ignoring a return value, cast to `(void)` and add a brief comment explaining why it is safe to ignore.

---

# [Coding Rule 4.7] Only pass valid values to libraries

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.7](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-7)

## Description

Before calling a library function with a restricted input domain, validate that the arguments are within the valid range. This applies to mathematical functions (`sqrt`, `log`, `asin`, `fmod`), character classification functions (`toupper`, `isalpha`), and others (`abs` with `INT_MIN`).

## Rationale / Effect if Violated

Passing out-of-domain values to library functions causes undefined behavior, implementation-defined results, or runtime exceptions. For example, `sqrt(-1.0)` is undefined, and `abs(INT_MIN)` overflows on two's complement systems.

## Good Example

```c
float64 rb_SafeSqrt(float64 x) {
    if (x < 0.0) {
        rb_ReportError(RB_ERR_MATH_DOMAIN);
        return 0.0;
    }
    return sqrt(x);
}

char rb_SafeToUpper(char c) {
    if ((c >= 'a') && (c <= 'z')) {
        return (char)toupper((unsigned char)c);
    }
    return c;
}
```

## Bad Example

```c
/* BAD: no domain check — x could be negative */
float64 result = sqrt(x);

/* BAD: toupper with potentially negative char value */
char upper = toupper(c);
```

## Fix Suggestion

Add pre-condition checks that validate arguments against the documented domain of the library function before calling it.

---

# [Coding Rule 4.8] Call functions in appropriate sequence

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.8](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-8)

## Description

Functions that operate on resources must be called in the correct lifecycle order: allocate (open/init), use (read/write/process), deallocate (close/deinit). A resource must not be used before it is allocated or after it is deallocated, and every allocation must have a corresponding deallocation.

## Rationale / Effect if Violated

Using a resource before initialization or after deinitialization causes undefined behavior, data corruption, or system crashes. Missing deallocation leads to resource leaks that degrade system performance over time.

## Good Example

```c
void rb_ProcessFile(const char* filename) {
    FILE* fp = fopen(filename, "r");
    if (fp != NULL) {
        /* use the resource */
        rb_ReadData(fp);
        /* deallocate the resource */
        (void)fclose(fp);
    }
}
```

## Bad Example

```c
void rb_ProcessFile(const char* filename) {
    FILE* fp;
    /* BAD: using resource before opening */
    rb_ReadData(fp);

    fp = fopen(filename, "r");
    (void)fclose(fp);

    /* BAD: using resource after closing */
    rb_ReadData(fp);
}
```

## Fix Suggestion

Ensure every resource follows the allocate-use-deallocate sequence. Do not use a resource before allocation or after deallocation. Verify that every allocation path has a corresponding deallocation.

---

# [Coding Rule 4.9] Do not rely on order of evaluation and side-effects

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Coding Rule 4.9](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#coding-rule-4-9)

## Description

The order in which sub-expressions are evaluated within a single expression is largely unspecified in C/C++. If multiple sub-expressions have side-effects and correctness depends on their execution order, split them into separate statements. Note that `&&` and `||` operators guarantee left-to-right evaluation with short-circuit semantics.

## Rationale / Effect if Violated

Relying on unspecified evaluation order produces code whose behavior varies across compilers and optimization levels. The same expression may yield different results on different platforms, causing intermittent, hard-to-reproduce bugs.

## Good Example

```c
/* Side-effects in separate statements — order is explicit */
uint32 a = rb_GetNext();
uint32 b = rb_GetNext();
uint32 sum = a + b;

/* Short-circuit is well-defined and safe to rely on */
if ((ptr != NULL) && (ptr->value > 0u)) {
    DoWork(ptr);
}
```

## Bad Example

```c
/* BAD: two calls with side-effects in one expression —
   evaluation order of arguments is unspecified */
uint32 sum = rb_GetNext() + rb_GetNext();

/* BAD: order of evaluation of function arguments is unspecified */
rb_Process(rb_PopQueue(), rb_PopQueue());
```

## Fix Suggestion

Split expressions that contain multiple sub-expressions with side-effects into separate statements so the execution order is explicit and deterministic.
