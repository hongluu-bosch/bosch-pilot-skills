# [Arithmetic Coding Rule 1.1] Do not use the content of uninitialized variables

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Arithmetic Coding Rule 1.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#aritmetic-coding-rule-1-1)

## Description

Only use variables that have been explicitly initialized before reading their value. Reading from an uninitialized variable leads to undefined behavior in C and C++. Exceptions to this rule include:
- Writing an initial value into the variable (the first access is an assignment).
- Passing a pointer to the variable for call-by-reference (the callee writes the initial value).

## Rationale / Effect if Violated

Reading uninitialized memory yields an indeterminate value and constitutes undefined behavior per the C/C++ standards. This can cause unpredictable program output, crashes, or latent bugs that only manifest under specific memory layouts or optimization levels.

## Bad Example (if applicable)

```c
uint32 value;
if (value > 10u) {  /* ERROR: value is uninitialized */
    DoSomething();
}
```

## Good Example (if applicable)

```c
uint32 value = 0u;
if (value > 10u) {
    DoSomething();
}

/* Also acceptable: call-by-reference initializes the variable */
uint32 result;
GetResult(&result);  /* result is written by the callee */
if (result > 10u) {
    DoSomething();
}
```

## Fix Suggestion

Initialize all variables at the point of declaration before any read access. If the initial value depends on runtime logic, ensure every code path assigns a value before the variable is read.

---

# [Arithmetic Coding Rule 1.2] Consider loss of information when converting int to float

- **Severity**: warning
- **Review Severity**: minor
- **Category**: arithmetic
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Arithmetic Coding Rule 1.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#aritmetic-coding-rule-1-2)

## Description

When converting an integer value to a single-precision floating-point (`float`), be aware that `float` can only represent integers exactly within the range **[-16777216 .. +16777216]** (±2²⁴). Integer values outside this range may lose precision because the 23-bit mantissa of IEEE 754 single-precision cannot represent all integers beyond that magnitude.

## Rationale / Effect if Violated

Silent loss of precision during integer-to-float conversion can lead to incorrect calculations, especially in safety-critical or high-precision contexts. The converted float value may differ from the original integer, producing subtle numerical errors.

## Bad Example (if applicable)

```c
uint32 large_value = 20000000u;
float32 f = (float32)large_value;
/* f may not exactly equal 20000000 due to float precision limits */
```

## Good Example (if applicable)

```c
/* Option 1: Use double when precision beyond ±2^24 is needed */
uint32 large_value = 20000000u;
float64 d = (float64)large_value;  /* double can represent all 32-bit integers exactly */

/* Option 2: Keep values in integer domain when possible */
uint32 large_value = 20000000u;
uint32 result = large_value / 10u;  /* stay in integer arithmetic */
```

## Fix Suggestion

Be aware of the precision limits of single-precision float. If integer values may exceed ±16777216, use `double` (float64) for the conversion, or restructure the computation to remain in the integer domain.

---

# [Arithmetic Coding Rule 1.3] Use services to convert from float to int

- **Severity**: error
- **Review Severity**: major
- **Category**: arithmetic
- **Analysis**: llm
- **Applies to**: both
- **Source**: [Arithmetic Coding Rule 1.3](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#aritmetic-coding-rule-1-3)

## Description

Do not convert floating-point values to integer types using explicit or implicit C casts. Instead, use the dedicated conversion functions provided in `RB_FloatConversion.h`. These functions handle rounding, clamping, and overflow protection in a safe and standardized way.

Available conversion functions include:
- `RB_FloatToIntLimiter_f32_u32`
- `RB_FloatToInt_f32_s16`
- `RB_FloatToInt_f32_u16`
- `RB_FloatToInt_f32_s32`
- `RB_FloatToInt_f32_u32`
- And other type-specific variants.

## Rationale / Effect if Violated

Direct float-to-integer casts in C/C++ truncate toward zero and produce undefined behavior if the float value is outside the representable range of the target integer type. The conversion service functions provide well-defined rounding and saturation, preventing overflow and ensuring deterministic results.

## Bad Example (if applicable)

```c
float32 some_float = 1234.56f;
uint32 x = (uint32)some_float;        /* explicit cast — violates rule */
sint16 y = some_float;                 /* implicit cast — also violates rule */
```

## Good Example (if applicable)

```c
float32 some_float = 1234.56f;
uint32 x = RB_FloatToInt_f32_u32(some_float);
sint16 y = RB_FloatToInt_f32_s16(some_float);
```

## Fix Suggestion

Replace every explicit or implicit float-to-integer cast with the appropriate `RB_FloatToInt*` or `RB_FloatToIntLimiter*` function from `RB_FloatConversion.h`, matching the source float type and target integer type.

---

# [Floating Point Arithmetic Coding Rule 1.1] Use only single precision

- **Severity**: warning
- **Review Severity**: minor
- **Category**: arithmetic
- **Analysis**: hybrid
- **Applies to**: both
- **Source**: [Floating Point Arithmetic Coding Rule 1.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#floating-point-aritmetic-coding-rule-1-1)

## Description

Use only single-precision floating-point (`float` / `float32`) for all runtime floating-point operations. Do not use `double` (`float64`) unless explicitly justified and approved. All floating-point literals must use the `f` suffix (e.g., `3.14f`) to ensure they are treated as single-precision constants by the compiler. Unsuffixed literals like `3.14` default to `double`, which may cause implicit promotions and unnecessary double-precision operations.

## Rationale / Effect if Violated

On many embedded targets, double-precision operations are significantly slower (often emulated in software) and consume more memory. Using `double` where `float` suffices degrades runtime performance and increases code size. Unsuffixed literals silently promote expressions to double precision, potentially causing mixed-precision arithmetic.

## Bad Example (if applicable)

```c
double x = 3.14;
double result = x * 2.0;
```

## Good Example (if applicable)

```c
float32 x = 3.14f;
float32 result = x * 2.0f;
```

## Fix Suggestion

Replace all `double` declarations with `float` (or `float32`). Add the `f` suffix to every floating-point literal (e.g., `0.0f`, `1.5f`, `3.14159f`).

---

# [Floating Point Arithmetic Coding Rule 1.2] Do not use equal comparison on floats

- **Severity**: error
- **Review Severity**: major
- **Category**: arithmetic
- **Analysis**: hybrid
- **Applies to**: both
- **Source**: [Floating Point Arithmetic Coding Rule 1.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#floating-point-aritmetic-coding-rule-1-2)

## Description

Do not compare floating-point values for exact equality using `==` or `!=`. Due to the nature of IEEE 754 floating-point representation and rounding during arithmetic operations, two values that are mathematically equal may differ at the bit level. This rule also applies to comparisons against `0.0f`.

## Rationale / Effect if Violated

Floating-point arithmetic accumulates rounding errors. An equality check that is mathematically correct may fail at runtime because the computed result differs from the expected value by a tiny amount. This leads to unreliable control flow, missed branches, and bugs that are difficult to reproduce and diagnose.

## Bad Example (if applicable)

```c
float32 a = ComputeValue();
float32 b = ComputeOtherValue();

if (a == b) {           /* unreliable — may fail due to rounding */
    DoSomething();
}

if (x == 0.0f) {        /* also unreliable */
    HandleZero();
}
```

## Good Example (if applicable)

```c
float32 a = ComputeValue();
float32 b = ComputeOtherValue();

if (fabsf(a - b) < EPSILON) {
    DoSomething();
}

if (fabsf(x) < EPSILON) {
    HandleZero();
}
```

## Fix Suggestion

Replace direct equality comparisons (`==`, `!=`) on floating-point values with a tolerance-based comparison using `fabsf(a - b) < EPSILON`, where `EPSILON` is a suitable small positive constant for the application domain.
