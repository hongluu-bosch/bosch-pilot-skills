# UT / Cantata++ / ASIL D — compact handbook

Use this file **on demand**: MC/DC pairing, report lines, mocks, bug triage, workflow phase details. The skill file (`SKILL.md`) owns workflow and red lines.

## 0. Workflow phase map

| Phase | Purpose | Build allowed? | Key exit artifact |
|-------|---------|----------------|-------------------|
| Phase 0 | Init test tree with `projectsetup.py` | No | `test_<Comp>/work/cantata_coverage.bat` exists |
| Phase 0.5 | Resolve compile-time macros with `align_macros.py` | No | Resolved macro block in `test_<Comp>.h` |
| **Phase 1** | **Analyze SUT and populate `test_<Comp>.h` / `.cpp`** | **NO** | **SUT analysis summary + initial tests** |
| Phase 2 | First coverage run | Yes | `ASIL_D_cov.ctr` from `cantata_coverage.bat` |
| Phase 3 | Coverage-loop: close C0/C1 gaps | Yes | Updated `test_<Comp>.cpp` |
| Phase 4 | MC/DC truth-table work | Yes | MC/DC pairs exercised |
| Phase 5 | Close the loop until 100% | Yes | Final `ASIL_D_cov.ctr` |

**Critical rule:** Phase 1 never invokes `cantata_coverage.bat`. Running the build before analysis and initial test population is a workflow violation.

## 1. Coverage report (`ASIL_D_cov.ctr`)

**Summary targets:** entry point, statement, decision, **boolean eff.** → all **100.0%**, INFEASIBLES acceptable only if formally justified (default: zero).

| Line pattern | Metric | Meaning |
|--------------|--------|---------|
| `stmnt N (...) 0` | C0 | Statement never executed |
| `decn N (...) branch TRUE 0` / `FALSE 0` | C1 | Branch never taken |
| `decn N (switch) default 0` | C1 | Default never taken |
| `expr N <cond> NOT effective` | MC/DC | Condition never independently flipped outcome |
| `expr N <cond> NOT exercised` | MC/DC | Short-circuit: condition never evaluated |

**Quick grep (from `test_<Comp>/work/output/cantata/`):**

```bash
grep "100.0%" ASIL_D_cov.ctr
grep -iE "un-executed|NOT EXECUTED" ASIL_D_cov.ctr   # expect empty at goal
grep -i "not effective" ASIL_D_cov.ctr
grep -i "not exercised" ASIL_D_cov.ctr
```

**Fix priority:** entry 0% → C0 gaps → C1 → MC/DC → boundaries / errors.

## 2. Test naming

- C0: `<Function>_C0_Line<line>`
- C1: `<Function>_C1_<Decision>_<side>` (e.g. `_IfGuard_True`)
- MC/DC: `<Function>_MCDC_L<line>_<Condition>_Effective` (+ `_Baseline` where useful)

## 3. Test shape (GTest)

- **AAA** in every test: Arrange → Act → Assert.
- **SetUp**: reset globals, volatile message vars, mock state; **TearDown**: `Mock::VerifyAndClearExpectations` where mocks used.
- **EXPECT_CALL** with `WillOnce` / `WillRepeatedly`; avoid silent uninteresting calls.

Minimal skeleton:

```cpp
TEST_F(ComponentTest, Fn_C0_Line42) {
    // Arrange
    // Act: result = Fn(...);
    // Assert
}
```

## 4. MC/DC — truth tables (pair = two rows, one condition flips, outcome flips)

**`A && B`** — 3 tests: baseline (T,T)→T; (F,T)→F proves A; (T,F)→F proves B.

**`A || B`** — 3 tests: baseline (F,F)→F; (T,F)→T proves A; (F,T)→T proves B.

**`A && B && C`** — 4 tests: (T,T,T); flip each of A,B,C alone → F.

**`A || B || C`** — 4 tests: (F,F,F); flip each alone → T.

**`A && (B || C)`** — need **two** TRUE baselines ((T,T,F) and (T,F,T)) plus flips for A and for B/C independence; often **5** rows total. Watch **short-circuit**: force A=T before expecting B/C to be evaluated.

**`!A`**: cover both values of A; treat `!A` as one boolean operand in larger expr.

**Common mistakes:** flipping multiple conditions at once; paired rows with **same** decision outcome; forgetting to disable short-circuit for inner condition.

## 5. Mocks (C + gmock)

- **Pattern:** `MockDeps` singleton `s_instance` + `extern "C"` wrappers forwarding to `MOCK_METHODn`.
- **Returns / errors:** `EXPECT_CALL(mock, F(_)).WillOnce(Return(E_OK));`
- **Out pointers:** `DoAll(SetArgPointee<0>(v), Return(E_OK))`.
- **RBMESG / volatile globals:** `extern volatile` in header; assign **0** in SetUp.

Stub when no call verification is needed.

## 6. Source defect signals (do **not** edit SUT — report)

| Signal | Likely cause |
|--------|----------------|
| Block after `return` / dead after unconditional branch | Dead code |
| `if` body never runs after assignment making condition constant | Logic bug |
| MC/DC impossible with sane types (e.g. redundant `uint8 >= 0`) | Redundant condition |
| Branch/decision structurally unreachable | Design / enum exhaustiveness |

**Bug report (minimal):** file + line + function + type (unreachable / logic / MC/DC impossible) + 5-line snippet + current coverage % + suggested fix **for user to apply**.

## 7. Files you may edit

- `test_<Component>.h`, `test_<Component>.cpp`, stubs under test tree only.
- **Never** SUT `.c` logic, compiler flags to "fake" behavior, or paths outside the component workspace.

## 8. Conditional compilation & macro-driven code paths

After **Phase 0.5** the agent has a definitive `*_resolved_macros.json` (produced by `align_macros.py --report`). Use it to determine which `#if / #ifdef / #else` blocks are **active** for the current variant and which are **elided** by the preprocessor.

### Coverage scope rule

- **Only** code that survives the preprocessor for the resolved macro set is in scope for 100% coverage.  
- Elided (`#if 0`) blocks are **not** counted as gaps. Do not write tests for them.  
- If Cantata still reports uncovered lines inside an elided block, verify that the resolved macros are actually being picked up by the build; the instrumentation may be using a different macro set than the resolved one.

### Quick mapping

From `*_resolved_macros.json`:

| `match_type` | Typical resolved value | Code path rule |
|--------------|------------------------|----------------|
| `if_eq` (e.g. `#if (MACRO == VALUE)`) | `MACRO = VALUE` | The `#if` body is **active**; `#else` (if any) is **elided**. |
| `if_eq` | `MACRO = OTHER` | The `#if` body is **elided**; `#else` is **active**. |
| `ifdef` | defined (value present in CSV) | Body is **active**. |
| `ifdef` | undefined (missing from CSV) | Body is **elided**. |
| `assert_switch` | first expected value = resolved value | Body is **active**. |
| `generic_if` | depends on expression evaluation | Treat like `if_eq` -- the resolved value must make the expression evaluate to true for the body to be active. |

### Agent checklist before Phase 1

1. Open `*_resolved_macros.json`.
2. For each macro entry, note the `status` (MATCH / CONFLICT / MISSING) and `resolved_value`.
3. Walk through the `.c` file line-by-line for every `#if` / `#ifdef` / `#else` / `#endif`.
4. Mark each block as **ACTIVE** or **ELIDED** based on the resolved value.
5. Only design tests for **ACTIVE** blocks.
6. If a CONFLICT or MISSING macro affects a block that Cantata later marks as uncovered, flag it in the coverage-gap triage (see §6) rather than forcing a test for unreachable code.

### Where the resolved macros live

`align_macros.py` injects the macro block directly into `test_<Component>.h`, inside a marked region near the top of the include guard. Because the test header is typically parsed before the SUT during Cantata instrumentation, the macros are defined early enough for the preprocessor to expand `#if / #ifdef` correctly.

Do **not** modify the SUT `.c` to add `#include` or `#define` lines.

### Cantata instrumentation pitfalls

- **Pitfall:** Cantata sometimes instruments the entire file before macro expansion if the resolved macros are not visible early enough.  
- **Fix:** Keep the generated macro block at the top of `test_<Component>.h`, before any `#include` of the SUT or its dependencies. If the block is accidentally moved lower, re-run `align_macros.py` to restore it.
- **Verification:** After the first `cantata_coverage.bat` run, grep the `.ctr` for lines inside known-elided blocks. If they appear as "un-executed", the macro block is not being applied early enough.

## 9. Phase 1 — detailed analysis template

Use this template to produce the **SUT analysis summary** required before entering Phase 2.

### 9.1 Function inventory

| Function | Scope | Return type | Key parameters | Notes |
|----------|-------|-------------|----------------|-------|
| | | | | |

### 9.2 Mock inventory

| Symbol | Type | SUT line | Mock strategy | Header/source to add |
|--------|------|----------|---------------|----------------------|
| | | | | |

### 9.3 Branch / decision table

| Line | Decision | TRUE test inputs | FALSE test inputs | MC/DC conditions |
|------|----------|------------------|-------------------|------------------|
| | | | | |

### 9.4 Active vs elided `#if` blocks

| Block start line | Macro / expression | Resolved state | Active? | Notes |
|------------------|--------------------|----------------|---------|-------|
| | | | | |

### 9.5 Initial test plan

| Test name | Target | Inputs | Expected return / side effects |
|-----------|--------|--------|--------------------------------|
| | | | |
