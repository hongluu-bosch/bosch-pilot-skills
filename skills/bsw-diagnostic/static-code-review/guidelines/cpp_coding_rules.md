# [CPP Coding Rule 1.1] Naming Pattern for CPP

- **Severity**: warning
- **Review Severity**: minor
- **Category**: naming
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 1.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-1-1)

## Description

Follow consistent naming conventions for C++ code:
- Functions returning `bool` must be named with prefixes such as `is...`, `has...`, `can...`, or `should...`.
- Class member variables must be prefixed with `m_`.

## Rationale / Effect if Violated

Inconsistent naming makes code harder to read and understand. Boolean-returning functions without intent-revealing prefixes obscure their purpose. Member variables without the `m_` prefix can be confused with local variables or parameters, increasing the risk of bugs and reducing maintainability.

## Good Example

```cpp
class Valve {
public:
    boolean isTargetValveOpen();
    boolean hasPermission();

private:
    TargetValve m_targetValve;
    int m_count;
};
```

## Bad Example

```cpp
class Valve {
public:
    boolean getValveTargetState();
    boolean checkPermission();

private:
    TargetValve targetValve;
    int count;
};
```

## Fix Suggestion

Rename boolean-returning functions to use `is...`, `has...`, `can...`, or `should...` prefixes. Add the `m_` prefix to all class member variables.

---

# [CPP Coding Rule 2.1] Guarantee that library functions do not overflow

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-1)

## Description

Ensure that all calls to library functions are guarded against overflow. Before passing values to library functions, validate that inputs are within the acceptable range to prevent buffer overflows, integer overflows, or other out-of-bounds conditions.

## Rationale / Effect if Violated

Library functions that overflow can cause undefined behavior, memory corruption, security vulnerabilities, or program crashes. Unguarded library calls are a common source of exploitable bugs.

## Good Example

```cpp
#include <cstring>
#include <cstddef>

void safeCopy(char* dest, size_t destSize, const char* src) {
    size_t srcLen = std::strlen(src);
    if (srcLen < destSize) {
        std::memcpy(dest, src, srcLen + 1);
    }
}
```

## Bad Example

```cpp
#include <cstring>

void unsafeCopy(char* dest, const char* src) {
    std::strcpy(dest, src);
}
```

## Fix Suggestion

Add bounds checks before calling library functions. Validate input sizes and use safer alternatives (e.g., `strncpy` instead of `strcpy`, range-checked containers instead of raw arrays).

---

# [CPP Coding Rule 2.2] Do not use an additive operator on an iterator if the result would overflow

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-2)

## Description

Do not apply additive operators (`+`, `-`, `+=`, `-=`) to an iterator if the resulting iterator would point outside the valid range of the underlying container (before `begin()` or past `end()`).

## Rationale / Effect if Violated

Advancing an iterator beyond the bounds of its container results in undefined behavior, which can lead to memory corruption, crashes, or silent data errors.

## Good Example

```cpp
#include <vector>

void processElements(std::vector<int>& vec, size_t offset) {
    if (offset <= vec.size()) {
        auto it = vec.begin() + offset;
    }
}
```

## Bad Example

```cpp
#include <vector>

void processElements(std::vector<int>& vec, size_t offset) {
    auto it = vec.begin() + offset;  // offset could exceed vec.size()
}
```

## Fix Suggestion

Always validate that the result of iterator arithmetic stays within the valid range `[begin(), end()]` before performing the operation. Check container size against the offset before advancing the iterator.

---

# [CPP Coding Rule 2.3] Do not read uninitialized memory

- **Severity**: error
- **Review Severity**: critical
- **Category**: safety
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.3](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-3)

## Description

Never read from uninitialized variables, memory, or object members. All variables and class members must be initialized before their first use. This includes primitive types, pointers, and class member variables that are accessed through member functions.

## Rationale / Effect if Violated

Reading uninitialized memory is undefined behavior. It can produce unpredictable values, cause crashes, or introduce security vulnerabilities. Class members that are not initialized in the constructor can silently contain garbage values.

## Good Example

```cpp
class S {
public:
    S() : m_c(0) {}
    int f(int x) { return x + m_c; }

private:
    int m_c;
};

S s;
int i = s.f(10);
```

## Bad Example

```cpp
class S {
public:
    int f(int x) { return x + m_c; }

private:
    int m_c;  // never initialized
};

S s;
int i = s.f(10);  // reads uninitialized m_c
```

## Fix Suggestion

Initialize all variables at the point of declaration. Ensure all class member variables are initialized in the constructor (preferably via the member initializer list) or with default member initializers.

---

# [CPP Coding Rule 2.4] Do not pass a nonstandard-layout type object across execution boundaries

- **Severity**: warning
- **Review Severity**: major
- **Category**: safety
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.4](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-4)

## Description

Do not pass objects of nonstandard-layout types across execution boundaries (e.g., between different shared libraries, DLLs, or modules compiled with different compilers or compiler settings). Only standard-layout types have a guaranteed memory layout across translation units.

## Rationale / Effect if Violated

Nonstandard-layout types may have different memory representations depending on the compiler, compiler version, or compilation flags. Passing such objects across execution boundaries can lead to memory corruption, crashes, or silent data misinterpretation.

## Good Example

```cpp
struct StandardPoint {
    float x;
    float y;
};

extern "C" void sendPoint(StandardPoint p);
```

## Bad Example

```cpp
class NonStandardPoint {
public:
    virtual float getX() { return m_x; }
private:
    float m_x;
    float m_y;
};

extern "C" void sendPoint(NonStandardPoint p);  // virtual table makes this nonstandard-layout
```

## Fix Suggestion

Use only standard-layout types (POD-like structs without virtual functions, without mixed access specifiers for non-static data members, and without base class data members) when passing data across execution boundaries. Serialize complex objects into standard-layout representations for cross-boundary communication.

---

# [CPP Coding Rule 2.5] Enumerations MUST be scoped and have an underlying type

- **Severity**: error
- **Review Severity**: minor
- **Category**: design
- **Analysis**: hybrid
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.5](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-5)

## Description

All enumerations must be declared as scoped enumerations (`enum class`) with an explicit underlying type. Unscoped enumerations (`enum`) and enumerations without a specified underlying type are not permitted.

## Rationale / Effect if Violated

Unscoped enumerations leak their enumerators into the enclosing scope, causing name collisions and implicit conversions to integers. Without an explicit underlying type, the compiler chooses the type, which can vary across platforms and lead to portability issues or unexpected size differences.

## Good Example

```cpp
enum class MyEnum : uint8_t {
    one,
    two,
    three
};
```

## Bad Example

```cpp
enum MyEnum {
    one,
    two,
    three
};
```

## Fix Suggestion

Replace `enum` with `enum class` and specify an explicit underlying type (e.g., `uint8_t`, `uint16_t`, `int32_t`) based on the range of values needed.

---

# [CPP Coding Rule 2.6] Base class destructors SHALL be protected and non-virtual

- **Severity**: warning
- **Review Severity**: major
- **Category**: design
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.6](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-6)

## Description

Base class destructors should be declared as `protected` and non-virtual to prevent deletion of derived objects through base class pointers while still allowing derived classes to clean up properly.

## Rationale / Effect if Violated

A public destructor on a base class allows callers to delete derived objects through a base pointer, which — if the destructor is non-virtual — causes undefined behavior due to incomplete destruction. Making the destructor protected prevents external deletion while preserving the ability of derived classes to invoke it.

## Good Example

```cpp
class BaseClass {
public:
    void doWork();

protected:
    ~BaseClass();
};

class Derived : public BaseClass {
public:
    ~Derived();
};
```

## Bad Example

```cpp
class BaseClass {
public:
    ~BaseClass();  // public non-virtual: allows unsafe deletion via base pointer
};
```

## Fix Suggestion

Move the base class destructor to the `protected` access section and ensure it is non-virtual. If polymorphic deletion via base pointer is required, use a public virtual destructor instead.

---

# [CPP Coding Rule 2.8] Avoid pre-processor directives

- **Severity**: warning
- **Review Severity**: minor
- **Category**: design
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.8](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-8)

## Description

Avoid the use of preprocessor directives in C++ code. Specifically, avoid `#if 0`, `#ifdef`, `#pragma`, and `#define`. Use C++ language features such as `constexpr`, `const`, `inline`, templates, and namespaces instead.

## Rationale / Effect if Violated

Preprocessor directives bypass the C++ type system and are not subject to scoping rules. They make code harder to read, debug, and maintain. `#if 0` blocks become dead code that rots over time. `#define` constants lack type safety. `#ifdef` branching creates hard-to-test code paths.

## Good Example

```cpp
constexpr int MAX_SIZE = 1024;

inline int square(int x) {
    return x * x;
}

template <typename T>
T max(T a, T b) {
    return (a > b) ? a : b;
}
```

## Bad Example

```cpp
#define MAX_SIZE 1024
#define SQUARE(x) ((x) * (x))

#if 0
    // dead code left behind
    void oldFunction() {}
#endif

#ifdef FEATURE_FLAG
    void featureFunction() {}
#endif
```

## Fix Suggestion

Replace `#define` constants with `constexpr` or `const` variables. Replace macro functions with `inline` functions or templates. Replace `#ifdef` conditional compilation with compile-time `if constexpr` or build-system configuration. Remove `#if 0` blocks entirely.

---

# [CPP Coding Rule 2.9] Organize class definitions by access level

- **Severity**: info
- **Review Severity**: minor
- **Category**: design
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.9](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-9)

## Description

Class definitions must be organized with access specifiers in the following order: `public`, then `protected`, then `private`. Omit access sections that contain no members.

## Rationale / Effect if Violated

A consistent ordering of access levels makes classes easier to read and understand. Users of a class care most about the public interface, so it should appear first. Inconsistent ordering across a codebase slows down code reviews and increases cognitive load.

## Good Example

```cpp
class MyClass {
public:
    MyClass();
    void doSomething();

protected:
    void helperMethod();

private:
    int m_data;
};
```

## Bad Example

```cpp
class MyClass {
private:
    int m_data;

public:
    MyClass();
    void doSomething();

protected:
    void helperMethod();
};
```

## Fix Suggestion

Reorder the class definition so that `public` members appear first, followed by `protected`, then `private`. Remove empty access sections.

---

# [CPP Coding Rule 2.10] Guidelines for the inline keyword

- **Severity**: info
- **Review Severity**: minor
- **Category**: design
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 2.10](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-2-10)

## Description

Follow these guidelines for the `inline` keyword:
- Use the `--max_inlining` compiler option to control inlining behavior at the build level.
- Member functions defined inside the class body are implicitly `inline`; do not redundantly add the keyword.
- `constexpr` functions are implicitly `inline`; do not redundantly add the keyword.
- Use `inline` explicitly only for functions defined in header files outside a class body.

## Rationale / Effect if Violated

Redundant `inline` specifiers add noise to the code without changing behavior. Misunderstanding implicit inlining can lead to either unnecessary annotation or missing `inline` on functions that require it (e.g., header-defined free functions), causing linker errors from ODR violations.

## Good Example

```cpp
class Calculator {
public:
    int add(int a, int b) { return a + b; }  // implicitly inline

    constexpr int multiply(int a, int b) { return a * b; }  // implicitly inline
};

inline int helperFunction(int x) {  // explicitly inline: defined in header, outside class
    return x * 2;
}
```

## Bad Example

```cpp
class Calculator {
public:
    inline int add(int a, int b) { return a + b; }  // redundant inline

    inline constexpr int multiply(int a, int b) { return a * b; }  // redundant inline
};
```

## Fix Suggestion

Remove redundant `inline` from member functions defined inside the class body and from `constexpr` functions. Add `inline` to functions defined in headers outside of class bodies. Use compiler options like `--max_inlining` to manage inlining strategy.

---

# [CPP Coding Rule 3.1] Use lower-case with componentname_ as prefix for file and directory names

- **Severity**: warning
- **Review Severity**: minor
- **Category**: naming
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 3.1](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-3-1)

## Description

All file and directory names must be lowercase and prefixed with the component name followed by an underscore. This convention applies to all source files (`.cpp`, `.hpp`, `.h`) and directories.

## Rationale / Effect if Violated

Mixed-case file names cause portability issues between case-sensitive (Linux) and case-insensitive (Windows, macOS) file systems. Without a component prefix, file name collisions become likely in large projects with many components.

## Good Example

```
rbc_abc_runnable.hpp
rbc_abc_runnable.cpp
rbc_abc_types.hpp
```

## Bad Example

```
RbcAbcRunnable.hpp
AbcRunnable.cpp
Types.hpp
```

## Fix Suggestion

Rename files and directories to use lowercase letters only, with the component name as a prefix separated by an underscore. For example, rename `RbcAbcRunnable.hpp` to `rbc_abc_runnable.hpp`.

---

# [CPP Coding Rule 3.2] Layout of include directives

- **Severity**: warning
- **Review Severity**: minor
- **Category**: structure
- **Analysis**: llm
- **Applies to**: cpp
- **Source**: [CPP Coding Rule 3.2](https://abtv2014.de.bosch.com/userContent/BauhausDoc/processDoc/Coding_rules_document.html#cpp-coding-rule-3-2)

## Description

Include directives must be organized in the following order, with each section separated by an empty line:
1. Main module header (using `""` quotes)
2. Local component headers (using `""` quotes)
3. Project headers (using `<>` angle brackets)
4. STL and system headers (using `<>` angle brackets)

Within each section, headers must be sorted alphabetically.

## Rationale / Effect if Violated

A consistent include order ensures that the main module header is self-contained (it will fail to compile if it has missing dependencies). Grouping and sorting includes improves readability, makes merge conflicts less likely, and helps identify unnecessary dependencies.

## Good Example

```cpp
#include "rbc_abc_runnable.hpp"

#include "rbc_abc_config.hpp"
#include "rbc_abc_types.hpp"

#include <project/core/logger.hpp>
#include <project/utils/string_utils.hpp>

#include <algorithm>
#include <string>
#include <vector>
```

## Bad Example

```cpp
#include <vector>
#include "rbc_abc_types.hpp"
#include <algorithm>
#include "rbc_abc_runnable.hpp"
#include <project/core/logger.hpp>
#include <string>
#include "rbc_abc_config.hpp"
```

## Fix Suggestion

Reorder include directives into the four sections: main module header first, then local component headers, then project headers, then STL/system headers. Sort alphabetically within each section and separate sections with an empty line.
