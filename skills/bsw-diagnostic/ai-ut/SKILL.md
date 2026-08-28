---
name: ut-100percent-coverage
description: |
  Use when the user wants C unit tests with Cantata++/GTest targeting 100% statement (C0),
  decision (C1), and MC/DC ("boolean eff."), ISO 26262 ASIL D style. Triggers: "C UT",
  "100% coverage", "MC/DC", "Cantata", "embedded C", "C0/C1", "asil".
  Executor: follow imperatives; expand detail only from references/ut-coverage-handbook.md.
version: "5.3"
---

# C UT — 100% C0/C1/MC/DC (Cantata++ + GTest)

## Stop First If Out Of Workspace

Before running any script, resolve the user-provided `.c` path against the current workspace.

If the resolved `.c` file is outside the current workspace boundary, treat it as a **fatal boundary violation**.

Use this exact user-facing message:

```text
ERROR: The provided .c file is outside the current workspace boundary.
This task has been stopped.
```

Required behavior:

1. Perform this workspace-boundary check **before Phase 0** and **before reading or invoking anything from the target folder**.
2. Output the exact message above to the user.
3. **Stop immediately** after that message.
4. **Do not** inspect that external folder.
5. **Do not** search for, read, or invoke any other skills, scripts, or files from that external folder.
6. **Do not** continue the UT workflow in the same conversation turn.
7. Treat `projectsetup.py` return/output as a **redundant fallback check only**, not the primary detection step.

If `projectsetup.py` later prints `SUT_OUTSIDE_WORKSPACE`, apply the same stop behavior again.

**Goal:** Cantata `ASIL_D_cov.ctr` → entry + statement + decision + **boolean eff.** = **100%** without changing SUT `.c`.

**Agent notes (e.g. Kimi-K2.5):** first check whether the requested `.c` path stays inside the current workspace boundary. If not, output the exact boundary error above and stop immediately. Only if that pre-check passes, execute the rest of this skill as a **checklist**. After each phase, emit a **3-line status**: (1) command run, (2) pass/fail, (3) next action. Use the PowerShell commands below as written; avoid inventing alternative paths. Avoid repeating prose from this file in outputs.

## Hard rules

| Rule | Detail |
|------|--------|
| Boundary | **Before anything else**, verify the requested `.c` file resolves inside the current workspace boundary. If not, output the fixed boundary error and stop the request immediately. |
| Phase 0 | **Only after the boundary check passes**, run `projectsetup.py` on the SUT `.c` before creating/editing tests (see Phase 0 below). Use paths relative to the workspace root or the current component directory exactly as shown. Do not hand-create `test_*` trees. The script's boundary validation is a redundant safety check. |
| Phase 0.5 | Run `align_macros.py` **after** Phase 0. The script decides whether CSV input is needed: if the SUT has no compile-time macros, it injects a safe default block and returns OK; if macros exist, a SwitchSettings CSV is required. Do **not** guess macro values. If the CSV is missing, stop and ask the user. |
| SUT | **Do not** modify the `.c` under test (no logic edits, no "test-only" copies as SUT). No compiler flags to alter semantics for coverage. |
| Scope | **Do not** change files outside the current component/workspace boundary. |
| Stuck | If gap looks like **unreachable / contradictory** SUT logic → **bug report** to user; do not patch SUT. |

## Phase 0 — init (mandatory)

Pre-check:

1. Resolve the requested `.c` path relative to the current workspace.
2. If it is outside the workspace, output the fixed boundary error and stop immediately.
3. Only then run `projectsetup.py`.

Run PowerShell from the workspace root (the directory that contains `.agents`). In this repository, `projectsetup.py` is located at `.agents/skills/ut-100percent-coverage/scripts/projectsetup.py`.

```powershell
Set-Location .\<ComponentFolder>
python ..\.agents\skills\ut-100percent-coverage\scripts\projectsetup.py .\<ComponentName>.c
```

Or, if you prefer to stay in the workspace root:

```powershell
python .\.agents\skills\ut-100percent-coverage\scripts\projectsetup.py .\<ComponentFolder>\<ComponentName>.c
```

**Expected tree:**

```text
<ComponentName>/
├── <ComponentName>.c
└── test_<ComponentName>/
    ├── test_<ComponentName>.h
    ├── test_<ComponentName>.cpp
    └── work/
        ├── cantata_coverage.bat
        ├── input/
        └── output/cantata/   ← ASIL_D_cov.ctr
```

If structure exists, script may skip; still **verify** the generated `test_<ComponentName>/work` path before editing tests.

## Phase 0.5 — compile-time macro alignment (mandatory for Bosch switch-driven SUT)

**Purpose:** SUT `.c` files contain `#if / #ifdef / RB_ASSERT_SWITCH_SETTINGS` blocks whose inclusion depends on **project-generated macro values** (e.g. `RBFS_*`, `FS_*`). The agent must **not** guess these values. This phase cross-references the C file against the **project SwitchSettings CSV** (ground truth) to determine which code paths are actually compiled, then injects the resolved macros into the Cantata build.

> **Note:** `align_macros.py` is the **only** script required for this phase. It performs macro extraction, CSV parsing, and alignment internally.

### When Phase 0.5 runs

- **Always run** `align_macros.py` after Phase 0; it is the only script for this phase.
- The script first extracts compile-time macros from the SUT `.c` file.
  - **No macros found:** it injects a safe default block (neutralises `RB_ASSERT_SWITCH_SETTINGS`) into `test_<ComponentName>.h` and exits **0**. No CSV is required.
  - **Macros found:** a SwitchSettings CSV is **mandatory**. Pass it as the second positional argument.
- If the SUT contains macros but no CSV is provided, or the CSV does not exist, the script exits **2**, prints the detected macros, and asks the user for the CSV path. Do not hallucinate values.

### Single-step alignment & generation

#### SUT without compile-time macros

```powershell
python .\.agents\skills\ut-100percent-coverage\scripts\align_macros.py .\<ComponentFolder>\<ComponentName>.c
```

#### SUT with compile-time macros

```powershell
python .\.agents\skills\ut-100percent-coverage\scripts\align_macros.py .\<ComponentFolder>\<ComponentName>.c .\<ComponentFolder>\SwitchSettings_*.csv --report --output-dir .\<ComponentFolder>\test_<ComponentName>\work\input
```

**What it does:**
1. Scans the `.c` file and extracts all compile-time macros (`#if`, `#ifdef`, `#ifndef`, `RB_ASSERT_SWITCH_SETTINGS`, generic `#if` expressions).
2. Parses the SwitchSettings CSV and builds a ground-truth lookup table.
3. Cross-references every macro found in the `.c` file against the CSV.
4. If a macro is **missing** from the CSV, falls back to the C file's expected value (or leaves it defined-but-empty for `#ifdef` style macros) and emits a **warning**.
5. Injects the resolved macros directly into `test_<ComponentName>.h` inside a marked, auto-managed block. This replaces any previous macro block generated by this script, keeping the test header self-contained.
6. With `--report`, also emits `<Component>_resolved_macros.json` and `<Component>_resolved_macros.txt` in `--output-dir` for audit.

**Stop condition:** If `align_macros.py` exits non-zero, or if **any** macro is flagged MISSING and no fallback value exists, stop and escalate to the user before entering Phase 1.

### Expected outcome for Phase 0.5

- The agent knows **exactly** which `#if` blocks are active for this variant.  
- No code path is assumed; every active branch is backed by CSV data.  
- `test_<ComponentName>.h` contains an auto-generated macro block near the top of the include guard, ready for the Cantata build.

## Phase 1 — analyze & populate (NO BUILD in this phase)

**Goal:** Read and analyse the SUT, then edit `test_<ComponentName>.h` and `test_<ComponentName>.cpp` with the first set of stubs and test cases.

**This phase does NOT run `cantata_coverage.bat`.** The build is intentionally forbidden here to guarantee that analysis and test design are completed before any coverage data is produced.

### Step 1 — read and analyse SUT
Open the SUT `.c` and identify:
- All **public / static functions** to be hit.
- All **external symbols** that must be mocked (e.g. functions, globals, message variables, RBMESG helpers).
- All **branches** (`if` / `else if` / `else`), **switches** (including `default`), and **loops**.
- All **boolean decisions** requiring **MC/DC** pairing.
- If Phase 0.5 was executed, note which `#if / #ifdef` blocks are **active** vs **elided** for the resolved macro set.

### Step 2 — output the SUT analysis summary
Before editing tests, emit a visible analysis summary. It must include at least:
- Public function list.
- Static function list.
- Mock list (external symbol, mock type, reason).
- Branch/decision table with line numbers and MC/DC notes.
- Active/elided `#if` blocks.

This summary is the **gate** that separates Phase 1 from Phase 2. Do not proceed to Phase 2 until it has been produced.

### Step 3 — populate the test artefact
Based on the analysis, edit:
- `test_<ComponentName>.h` — include guard, SUT includes, required macros (Phase 0.5), shared types.
- `test_<ComponentName>.cpp` — GTest fixture with `SetUp` / `TearDown`, gmock stub class, `extern "C"` shims, and the first batch of `TEST_F` cases.

The first batch must cover:
- **C0:** every active statement at least once.
- **C1:** every decision TRUE and FALSE (including `else` and switch `default`).
- **MC/DC:** initial pairwise rows for each boolean condition where independent effect needs to be proven.

> **Why analyse before compiling:** Pre-analysis of functions, mocks, branches, switches and MC/DC targets lets the agent write correct stubs and test signatures before the first Cantata run, reducing avoidable compile-fix iterations.

## Phase 2 — first coverage run

**Prerequisite:** Phase 1 SUT analysis summary must be visible in the conversation and `test_<ComponentName>.cpp` must contain SUT-specific tests (not just the auto-generated placeholder).

Change to the work directory, clean the output folder, and run Cantata:

```powershell
Set-Location .\test_<ComponentName>\work
Remove-Item -Path .\output -Recurse -Force -ErrorAction SilentlyContinue
.\cantata_coverage.bat
```

Or from the workspace root:

```powershell
Set-Location .\<ComponentFolder>\test_<ComponentName>\work
Remove-Item -Path .\output -Recurse -Force -ErrorAction SilentlyContinue
.\cantata_coverage.bat
```

> **Why clean `output` first:** Cantata sometimes merges new results with stale files in `output/cantata/`. Deleting the folder before each run guarantees `ASIL_D_cov.ctr` reflects only the current test execution.

## Phase 3 — design + implement (coverage loop)

After the first Cantata run (Phase 2), use the coverage report to close gaps:

- **C0:** every statement at least once.  
- **C1:** every decision TRUE and FALSE (incl. loop enter/skip, switch default).  
- **MC/DC:** for each condition in a decision, prove **independent** effect on outcome (pairwise rows; watch short-circuit).

Add minimal `TEST_F` cases to `test_<Component>.cpp` and update mocks/macros in `test_<Component>.h` as needed. Naming: see handbook §2.

## Phase 4 — MC/DC

Use truth-table method in **`references/ut-coverage-handbook.md` §4** (do not duplicate long tables in chat).

## Phase 5 — close the loop

Repeat until done or stop condition:

1. Analyse the current SUT state and planned gap fix before building.  
2. Clean `work/output` (`Remove-Item -Path .\output -Recurse -Force -ErrorAction SilentlyContinue`)  
3. Build + run `cantata_coverage.bat`  
4. Open `work/output/cantata/ASIL_D_cov.ctr`  
5. If not 100%: map lines with handbook **§1** → add minimal tests → goto 1  

**Stop and escalate if:** `projectsetup.py` cannot create tree; Cantata/Cook-san missing; SUT file missing; `SUT_OUTSIDE_WORKSPACE`; SwitchSettings CSV missing when `align_macros.py` has detected compile-time macros; `align_macros.py` exits non-zero; **3** consecutive compile-fix failures; **10** coverage iterations without progress; user says stop.

## Verification

From report directory:

- Summary lines show **100.0%** for all four types.  
- In PowerShell, `Select-String` for un-executed / NOT effective / NOT exercised should return **no matches** (unless user accepted infeasible with documentation).

## Deep reference (single file)

- **Patterns, report search, MC/DC tables, mock cheatsheet, bug signals:** `references/ut-coverage-handbook.md`

## Script — `.agents/skills/ut-100percent-coverage/scripts/projectsetup.py`

- Resolves the SUT path, rejects anything outside the workspace root, and checks for existing `test_<stem>/` + key files.  
- The script's `SUT_OUTSIDE_WORKSPACE` result is a redundant safety net; the skill should normally stop earlier during the pre-check.  
- If the test project does not already exist: runs Cook-san `setup_project.bat` (default cook path in script; override `--cook-san-path` if needed).  
- Existing `test_<stem>/` directories are protected by default. Re-init requires **both** `--force` and `--allow-existing-test-project-reinit`, and the script writes a sibling JSON audit log of the before/after tree snapshot.  
- Cook-san setup is launched via an argument array instead of a shell-built command string.  
- Exit **0** when tree OK; **1** on missing/out-of-workspace SUT, missing `setup_project.bat`, protected existing tree, or failed setup.

### `.agents/skills/ut-100percent-coverage/scripts/align_macros.py`

- **Phase 0.5 orchestrator.** Runs extraction and parsing in-memory, then cross-references C-side macro expectations against the CSV ground truth.  
- Accepts an optional CSV path. If the SUT has no compile-time macros, the CSV is not required and the script injects a safe default block.
- If compile-time macros are found and the CSV is missing or not found, exits **2** and prints the detected macros so the user can supply the CSV path.
- Produces the auto-managed macro block inside `test_<ComponentName>.h` (the only required artefact). Optional audit reports (`_resolved_macros.json` / `.txt`) are generated only when `--report` is passed.  
- Exit **0** when alignment succeeds or when no macros are found (even with conflicts, as long as a resolved value exists).  
- Exit **2** when unresolved MISSING macros block progress or when a CSV is required but missing; the skill must stop and ask the user.
