# Command reference

Per-command reference for `scripts/pipeline.py`. `SKILL.md` gives the
prescriptive playbook; this file is the menu for exact flags, inputs,
outputs, and side-effects.

> **Path conventions (v2.0.0)**: every command runs from the project
> root (`cd <project-root>` first). `<skill>` = the user-level skill
> path (`~/.cursor/skills/diagcomm-toolkit/`). Relative paths
> `inputs/...`, `outputs/...`, `state/...`, `.cache/...` resolve to
> the workspace at `<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/`;
> `assets/...`, `scripts/...` resolve to `<skill>/`. Most commands
> refuse to run when no workspace exists at
> `<cwd>/.DCOM_AI/DiagComm_Toolkit_PRJ` — see [`--init-project`](#--init-project)
> for the bootstrap command.

## Quick index

| Command | When to use |
|---|---|
| [`--init-project`](#--init-project) | One-time bootstrap of a project's workspace. Idempotent; refuses to scaffold inside the skill checkout. **Must run before everything else.** |
| [`status`](#status) | Readiness dashboard. Run first when anything looks off. Refuses to run if no workspace or `inputs/DiagComm.xlsx` missing. |
| [`validate`](#validate) | Sanity-check the user input (loaded from `inputs/DiagComm.xlsx` via `excel_loader.py`) against schema + locators. |
| [`apply --dry-run`](#apply---dry-run) | Preview the VALUE changes that would be written. No disk writes. |
| [`apply --apply`](#apply---apply) | Write the matched ARXML files (surgical byte-level). |
| [`reseed`](#reseed) | Default = no-op deprecation notice. With `--from-arxml`, write a transcribe-by-hand suggestion file from live ARXML. Never edits `inputs/DiagComm.xlsx`. |
| [`landing-report`](#landing-report) | Enumerate live landing spots per project. |
| [`gen-schema`](#gen-schema) | Rebuild `DiagComm_schema.json` after editing `DiagComm.txt`. (Then re-run `python <skill>/scripts/build_inputs_template.py` so `assets/inputs_template.xlsx` matches.) |
| [`export-catalog`](#export-catalog) | Regenerate the catalog table in `reference/landing_spots.md` from `scripts/mapping.yaml`. Maintainer-only. |
| [`fscs`](#fscs) | Render the one-page FSCS snapshot. |

### Workspace-discovery contract (since 2.0.0)

Every workspace-touching command (`status` / `validate` / `apply` /
`fscs` / `landing-report` / `reseed`) goes through one gate at startup:
`runtime._check_workspace_initialized()`. It asserts both
`<cwd>/.DCOM_AI/DiagComm_Toolkit_PRJ/` and its `inputs/` subdir exist.
If either is missing, the process exits with a `SystemExit` whose
message embeds the exact `--init-project` recovery command. This is
how the skill prevents lazy-creating partial workspaces in the wrong
directory.

### Cache-refresh contract (since 1.20.0)

After the workspace gate passes, the same set of commands all share
one invariant: at the start of every run, `runtime.load_user_inputs()`
calls `excel_loader.load_or_refresh()`. If workspace
`inputs/DiagComm.xlsx` is newer than `.cache/DiagComm_values.json`
(or the cache is missing), the loader regenerates the cache from the
xlsx atomically. The cache files are gitignored derived data —
**never edit them**.

If workspace `inputs/DiagComm.xlsx` itself is missing (the workspace
was scaffolded but the user nuked the workbook), every command exits
**2 (BROKEN)** with the recovery hint:
`python <skill>/scripts/pipeline.py --init-project --force`.

If a v1.20.x in-skill workspace is still on disk, `status` exits
**2 (BROKEN)** with the migration command:
`python <skill>/scripts/migrate_v1_20_to_v2.py --from-skill <project-root>/.agents/skills/diagcomm-toolkit`.

If pre-1.20.0 input files (`DiagComm_values.json`,
`DiagComm_config.json`, `doors_mapping.yaml`) are detected, `status`
exits **2 (BROKEN)** with the v1.19 migration command:
`python <skill>/scripts/migrate_v1_19_to_xlsx.py --legacy-from <dir>`.

## --init-project

```bash
cd <project-root>
python <skill>/scripts/pipeline.py --init-project [<project-root>] [--force]
```

One-time per project. Scaffolds
`<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/` with four subdirs
(`inputs`, `outputs`, `state`, `.cache`), copies the bundled
`<skill>/assets/inputs_template.xlsx` into `inputs/DiagComm.xlsx`, and
writes a workspace-local `.gitignore` so derived `.cache/` and
generated `outputs/` stay out of the project's git history.

| Flag | Effect |
|---|---|
| (positional `project_root`) | Defaults to the current working directory. Use this when you want to scaffold a workspace for a different project without `cd`-ing first. |
| `--force` | Overwrite existing files. **Use only after backing up** — this clobbers the user's filled `inputs/DiagComm.xlsx`. The agent never invokes `--force` automatically; it's a user opt-in for "reset to blank template." |

**Idempotent** without `--force`: re-running on an already-scaffolded
workspace reports each existing file as `skipped` and exits 0.

**Safety guard**: refuses to scaffold when the resolved workspace
path lands inside the skill checkout (`SKILL_ROOT`). This catches the
common "I forgot to cd to my project root, so cwd is the skill clone"
mistake. Override is intentionally not supported.

| Exit | Meaning |
|---|---|
| 0 | Workspace scaffolded (or already present). |
| 2 | Refused: target lands inside the skill checkout, or template asset missing. |

*Inputs:* `<skill>/assets/inputs_template.xlsx`.
*Outputs:* `<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/{inputs,outputs,state,.cache,.gitignore}`.

## status

```bash
python <skill>/scripts/pipeline.py status
```

Readiness dashboard. Prints the state of every file the pipeline
depends on (skill assets, workspace config, schema, values, dcom_root,
arxml files, snapshots) plus dependency versions.

| Exit | Meaning |
|---|---|
| 0 | READY — safe to proceed. |
| 1 | DEGRADED — non-fatal (e.g. snapshot STALE, `values : SEEDED`). |
| 2 | BROKEN — missing config/schema/arxml/unresolved `dcom_root`, or workspace not initialised, or legacy layout detected. |

**Workspace gate** (before anything else): if no workspace at
`<cwd>/.DCOM_AI/DiagComm_Toolkit_PRJ/`, exits **2 (BROKEN)** with the
`--init-project` recovery command.

**Cache refresh:** at entry, `excel_loader.load_or_refresh()`
regenerates `.cache/{values,config,doors_mapping}` from workspace
`inputs/DiagComm.xlsx` if any of the source files are newer. If the
xlsx is missing, `status` exits **2 (BROKEN)** with the
`--init-project --force` recovery hint. If a v1.20.x in-skill
workspace or pre-1.20.0 inputs are detected, `status` exits **2
(BROKEN)** with the appropriate migration command. If required cells
on Sheet 'Project & Parameters' are blank, `status` exits **1
(DEGRADED)** with the precise list of unfilled fields.

*Inputs:* skill assets + the workspace's xlsx-driven cache.
*Outputs:* stdout only.

---

## validate

```bash
python <skill>/scripts/pipeline.py validate [--input .cache/DiagComm_values.json]
```

> The `--input` flag is for debug only; the default reads workspace
> `.cache/DiagComm_values.json`, which is auto-derived from the xlsx.
> Pointing it at any other file bypasses the cache-refresh contract.

Schema coverage + semantic rules (CAN ID vs format, STmin cap,
N-timer ordering, …) + locator reachability for every mapped
parameter.

| Exit | Meaning |
|---|---|
| 0 | No errors. Warnings may still be printed. |
| 2 | At least one hard error. Read `outputs/validation_report.txt`. |

*Outputs:* `outputs/validation_report.txt`.

---

## apply --dry-run

```bash
python <skill>/scripts/pipeline.py apply --dry-run
```

Compute the diff for every VALUE node that *would* change, per ARXML
file. **No disk writes.** Use this to review before committing.

*Outputs:* `outputs/diff_report.txt`, `outputs/FSCS.txt`.

---

## apply --apply

```bash
python <skill>/scripts/pipeline.py apply --apply
```

Rewrite the matched ARXML files via a surgical byte-level patcher:
only the inner text of each matched `<VALUE>` element is replaced;
every other byte of the source file is preserved byte-identical.

Rollback is delegated to the target project's VCS (`git checkout --
<arxml>`, `svn revert <arxml>`, …) — the skill keeps no local copies.

*Side effects:* rewrites ARXML under
`<base_dir>/<resolved-dcom_root>/**/cfg/`.
*Outputs:* `outputs/diff_report.txt`, `outputs/FSCS.txt`.

---

## reseed

```bash
python <skill>/scripts/pipeline.py reseed                   # default: no-op deprecation notice
python <skill>/scripts/pipeline.py reseed --from-arxml      # write outputs/reseed_suggestion.json
   [--can-channel N] [--product-type DPB|ESP|IPB|RBU]
```

Since 1.20.0 the user template (workspace `inputs/DiagComm.xlsx`)
ships pre-filled with schema defaults (the workspace is scaffolded
from `<skill>/assets/inputs_template.xlsx` by `--init-project`).
There is no need for the skill to "seed" anything from live ARXML —
the user opens the xlsx and edits.

**Default mode** (`reseed` with no flags) is a **no-op**. It prints
the same "since v2.0.0..." banner that BROKEN status surfaces, and
exits 0. Use it as a reminder of how to recover the blank template
(`python <skill>/scripts/pipeline.py --init-project --force`).

**`--from-arxml` mode** is the diagnostic tool: reverse-transforms
every non-derived mapped parameter (seconds → ms, decimal → hex,
AUTOSAR literals → enum labels) and writes the suggestions to
`outputs/reseed_suggestion.json`. The user manually transcribes any
interesting values into Excel — the skill never overwrites
`inputs/DiagComm.xlsx`.

Path-selector resolution on `--from-arxml`:

- `--can-channel` defaults to the schema default (normally `0`).
  Pass it explicitly if the project uses a non-default per-channel
  `Can<N>_CusDiag` lookup.
- `--product-type` resolution chain: flag value → filesystem probe
  (glob `RBAPLCust/cfg/*/Can*_CusDiag_EcucValues_*.arxml`; picked iff
  exactly one `<PT>/` variant ships) → schema default (`DPB`). If
  the probe is ambiguous or empty, the default is written and you
  must correct it in the suggestion before transcribing.

| Exit | Meaning |
|---|---|
| 0 | No-op printed (default), or suggestion file written (`--from-arxml`). |
| 2 | `--from-arxml`: Config / ARXML unreadable. |

*Outputs:* `outputs/reseed_suggestion.json` (only with `--from-arxml`).

---

## landing-report

```bash
python <skill>/scripts/pipeline.py landing-report [--can-channel N] [--product-type DPB|ESP|IPB|RBU]
```

Enumerate every landing spot in the current project's ARXML: for each
`PARAM_MAP` entry, resolve the target file, run the locator, and list
every matched `PARAM-VALUE` with its SHORT-NAME chain and current
value. Use this to verify the invariant catalog in
[`landing_spots.md`](./landing_spots.md) or to diagnose a locator
miss.

*Outputs:* `outputs/landing_report.txt`.

---

## gen-schema

```bash
python <skill>/scripts/pipeline.py gen-schema            # rewrite the schema file
python <skill>/scripts/pipeline.py gen-schema --check    # drift detector (CI)
```

> Maintainer-only and skill-internal: rewrites `<skill>/assets/DiagComm_schema.json`,
> not anything in the workspace. Run this only when the parameter
> catalog (`<skill>/assets/DiagComm.txt`) changes.

Parse `assets/DiagComm.txt` and emit `assets/DiagComm_schema.json`.
With `--check`, write nothing and exit 1 if the on-disk schema
differs — a unified diff is printed. `status` invokes the same check
silently and reports `schema : DRIFT`.

*Inputs:* `assets/DiagComm.txt`.
*Outputs:* `assets/DiagComm_schema.json` (only on bare `gen-schema`).

---

## export-catalog

```bash
python <skill>/scripts/pipeline.py export-catalog            # rewrite the catalog block
python <skill>/scripts/pipeline.py export-catalog --check    # drift detector (CI)
```

Maintainer-only. Renders the in-code `PARAM_MAP` (loaded from
`scripts/mapping.yaml`) as a markdown table and injects it into
`reference/landing_spots.md` between the
`<!-- auto:catalog-begin -->` / `<!-- auto:catalog-end -->` fences.
Run after editing `mapping.yaml` (e.g. adding a project-specific
locator) to keep the public catalog in sync. With `--check`, write
nothing and exit 1 if the on-disk block differs — a unified diff is
printed.

End users never need this command; it is part of the porting
workflow ([`reference/porting_checklist.md`](./porting_checklist.md)).

| Exit | Meaning |
|---|---|
| 0 | Catalog is already in sync, or was rewritten successfully. |
| 1 | `--check` only: catalog block drifted from `mapping.yaml`. |
| 2 | Target markdown file missing (skill installation broken). |

*Inputs:* `scripts/mapping.yaml` (via `PARAM_MAP`).
*Outputs:* `reference/landing_spots.md` (only on bare `export-catalog` when out of sync).

---

## fscs

```bash
python <skill>/scripts/pipeline.py fscs [--input .cache/DiagComm_values.json]
```

Render a one-page snapshot of the current values file. Follows the
order of `assets/DiagComm.txt` and appends a `# Derived` block for
auto-computed flags such as `CanTpFlexibleDataRateSupport`. Generated
automatically at the end of every `apply` run; use the standalone
command to refresh after a hand-edit of the values file.

*Outputs:* `outputs/FSCS.txt`.
