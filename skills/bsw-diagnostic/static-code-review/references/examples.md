# Review Examples

Use these examples to calibrate severity decisions when reviewing findings.

For stable regression checks of the standalone review workflow, also use these packaged regression cases:

1. [regression-case-dedup-major.md](./regression-case-dedup-major.md)
2. [regression-case-downgrade-minor.md](./regression-case-downgrade-minor.md)
3. [regression-case-escalate-critical.md](./regression-case-escalate-critical.md)

## Critical Examples

### Example 1: Out-of-bounds array access

Code pattern:

```c
uint8 buffer[8];
buffer[index] = value;
```

Expected classification:

1. `critical`

Reason:

1. If `index` is not proven in range, memory outside the array may be overwritten.

### Example 2: Uninitialized read

Code pattern:

```c
uint32 value;
if (value > 0u) {
    DoWork();
}
```

Expected classification:

1. `critical`

Reason:

1. The program reads indeterminate memory and behavior is unstable.

## Major Examples

### Example 1: Ignored error return

Code pattern:

```c
Std_ReturnType result = Sensor_Read(&value);
(void)result;
ProcessValue(value);
```

Expected classification:

1. `major`

Reason:

1. Failure handling is bypassed and wrong state can propagate.

### Example 2: Order-of-evaluation bug

Code pattern:

```c
result = compute(a++) + compute(a++);
```

Expected classification:

1. `major`

Reason:

1. Behavior depends on unspecified evaluation order and can change results.

## Minor Examples

### Example 1: Naming convention violation

Code pattern:

```c
uint32 counter;
```

Expected classification:

1. `minor`

Reason:

1. Readability and consistency are affected, but not correctness.

### Example 2: Include style issue

Code pattern:

```c
#include "string.h"
```

Expected classification:

1. `minor`

Reason:

1. This is mainly a portability or consistency issue unless concrete behavioral impact is shown.

## Downgrade Examples

### Example 1: Metric finding with generic risk wording

Finding text:

1. Function nesting depth exceeds the recommended limit and may increase defect risk.

Expected classification:

1. `minor`

Reason:

1. The issue affects maintainability, not directly functional behavior.

## Escalation Examples

### Example 1: External input copied into fixed buffer without bounds checking

Code pattern:

```c
strcpy(dest, packet);
```

Expected classification:

1. `critical`

Reason:

1. External input can overflow a fixed-size buffer with direct runtime consequences.