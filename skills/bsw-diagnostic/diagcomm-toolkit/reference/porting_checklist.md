# Porting checklist

Step-by-step for enabling `diagcomm-toolkit` on a new project (or a
new platform variant). Project-invariant — every example below uses
the standard Bosch CusDiag layout templates (`*/rb/as/*/core/app/dcom`,
`RBAPLCust/...`, `Cubas/...`) and the four neutral product-type enums
shipped in the schema (`DPB` / `ESP` / `IPB` / `RBU`); no real project
codename, BSW variant, or DOORS path is hard-coded anywhere in this
checklist.

> **v2.0.0 dual-root reminder.** The skill itself lives once at
> `~/.cursor/skills/diagcomm-toolkit/` (`SKILL_ROOT`). All
> per-project user data lives at
> `<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/` (`WORKSPACE_ROOT`),
> scaffolded by `pipeline.py --init-project`. A single skill clone
> serves every project on the machine. Below, `<skill>` refers to
> the user-level install path; relative paths `inputs/…`,
> `outputs/…`, `state/…`, `.cache/…` are workspace-relative.

## 0. Prerequisites

- Python 3.12+ with the runtime deps installed:
  `python -m pip install -r <skill>/scripts/requirements.txt`
  (covers `lxml` / `PyYAML` / `openpyxl` / `xlsxwriter` /
  `requests` / `keyring`). Older interpreters refuse to run with a
  clear message.
- Read access to a Bosch BSW tree that contains a
  `rb/as/<bsw>/core/app/dcom/` sub-directory, where `<bsw>` is a
  project-specific BSW variant name.
- Write access to every `*.arxml` under that `dcom/` tree (the skill
  rewrites them in place via a surgical byte-level patcher). Rollback
  is delegated to whatever source-control system already tracks that
  tree; the skill does not copy arxml into `outputs/`.
- *(Optional, for Step 8 only)* DOORS NT account with write access to
  the target module. The Excel import template is bundled with the
  skill; users do not edit it.
  See [§ 8. DOORS upload first-time setup](#8-doors-upload-first-time-setup)
  below.
- *(Optional, for Step 8 only — different network / different DOORS MCP
  host)* set `DIAGCOMM_DOORS_MCP_URL=http://<host>:<port>/mcp` in the
  shell or environment. The three DOORS scripts (`doors_fetch.py`,
  `doors_upload.py`, `doors_sync.py`) read this env var at import time
  and fall back to the bundled team default only when it's unset. Any
  invocation can also pass `--server-url <url>` to override per-run
  (CLI > env var > default).

## 1. Install the skill (machine-level, once per user)

```bash
# Linux / macOS
git clone <repo-url> ~/.cursor/skills/diagcomm-toolkit
python -m pip install -r ~/.cursor/skills/diagcomm-toolkit/scripts/requirements.txt

# Windows (PowerShell)
git clone <repo-url> $env:USERPROFILE\.cursor\skills\diagcomm-toolkit
python -m pip install -r $env:USERPROFILE\.cursor\skills\diagcomm-toolkit\scripts\requirements.txt
```

Then verify:

```bash
python <skill>/scripts/preflight.py
```

Expected: `[skill] OK` and `[workspace] not initialized` (exit 2).
Exit 1 means a bundled asset is missing — re-clone or `git checkout`.

## 2. Bootstrap the per-project workspace (once per project)

A typical layout (default `paths.base_dir = ../..` works zero-config):

```text
<project-root>/                                    ← cd here for every command
├── .DCOM_AI/DiagComm_Toolkit_PRJ/                 ← --init-project creates this
│   ├── inputs/DiagComm.xlsx                       ← the user-edited file
│   ├── .cache/                                    ← gitignored derivatives
│   ├── outputs/                                   ← regenerable reports
│   ├── state/                                     ← DOORS upload state
│   └── .gitignore                                 ← auto-written
└── <PlatformName>/rb/as/<bsw>/core/app/dcom/      ← live arxml tree
```

```bash
cd <project-root>
python <skill>/scripts/pipeline.py --init-project
```

What `--init-project` does:

1. Creates the four workspace subdirs.
2. Copies `<skill>/assets/inputs_template.xlsx` →
   `<workspace>/inputs/DiagComm.xlsx` (blank, with all data-validation).
3. Writes a workspace-local `.gitignore` covering `.cache/`,
   `outputs/`, `state/*.tmp`, and Excel lock files.
4. Refuses to scaffold when the resolved workspace path lives inside
   the skill checkout (catches "I forgot to `cd` to my project root").

Idempotent without `--force`: re-running on an already-scaffolded
workspace skips each existing file and exits 0.

> Any other parent-directory depth between `.DCOM_AI/` and the
> arxml tree works too — just adjust
> `inputs/DiagComm.xlsx::Sheet 'Paths & Options'::paths.base_dir` and
> `paths.dcom_root`. The default value `paths.base_dir = ../..`
> assumes the workspace is exactly two levels deep relative to the
> project root, which is what `--init-project` produces.

## 3. Open `inputs/DiagComm.xlsx`

Since 1.20.0 the only user-edited file is the Excel workbook
`inputs/DiagComm.xlsx`. After `--init-project` it sits at
`<workspace>/inputs/DiagComm.xlsx`, blank but with data-validation
dropdowns / range checks / red-highlighted required cells. Open it in
Excel. Full sheet / column spec: [`excel_format.md`](./excel_format.md).

### Sheet 1 — `Project & Parameters` (every spec change)

9 required cells (red-highlighted) + 16 defaulted cells. The
required ones:

| Field | What to set |
|-----|-------------|
| `project.name` | Human-readable project identifier. Printed by `pipeline.py status` (`project : <name>`) and embedded in every workspace `outputs/FSCS.txt` header / DOORS Object Text. Not written to any arxml — purely a traceability tag. |
| `project.product_type` | Path selector. Pick from dropdown `DPB / ESP / IPB / RBU`. Must match a folder under `RBAPLCust/cfg/`. **NOT** in `parameters` — switching product alone is a project-identity change, not a parameter change (Step 8 calls this `pp_only_changed`). |
| `parameters.CAN_DLC.{rx,tx}_frame_type` (×2) | Pick `ClassicCAN` or `CANFD` from dropdown. |
| `parameters.CAN_DLC.{rx,tx}_dl` (×2) | Pick `8` or `64` from dropdown. |
| `parameters.CAN_{Functional,Physical}_Request_ID`, `parameters.CAN_Response_ID` (×3) | Hex literals (e.g. `0x7DF`); zero-padded width preserved. |

Optional (defaulted) fields:

| Field | What to set |
|-----|-------------|
| `parameters.CAN_Channel` | Path selector. Picks `Can<N>_CusDiag_EcucValues_<PT>.arxml`. Default `0`. Lives in `parameters` (contributes to the param fingerprint). |
| `parameters.*` (other 14 timer / byte / flag fields) | Leave the Value cell blank to use the schema default; otherwise type per the `Allowed/Range` column. Full inventory: [`parameter_types.md`](./parameter_types.md). |

### Sheet 2 — `Paths & Options` (once per project)

| Field | What to set |
|-----|-------------|
| `paths.base_dir` | Path from the workspace root to the project root (parent of the `Fe_*/` tree). Default `../..` is correct when the workspace lives at `<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/` (i.e., the layout `--init-project` produces). |
| `paths.dcom_root` | Path *under* `base_dir` to the `dcom/` folder. Glob wildcards (`*`, `?`, `[...]`) are allowed for segments whose name varies across projects. Structural depth must stay constant; multi-match is resolved with a deterministic first-winner + warning. |
| `paths.{cantp,dcm}_*` | **Usually leave these alone.** They are the standard AUTOSAR layout used by every project so far (`RBAPLCust/cfg/{Common,<PT>}/*.arxml` + `Cubas/cfg/*.arxml`). Only override when a project genuinely relocates a file. |
| `paths.can_pt_file` | Template with `{product_type}` and `{can_channel}` placeholders. Both are filled at run-time from `project.product_type` / `parameters.CAN_Channel`. |
| `options.dry_run_default` | Keep at `TRUE` in interactive use. CI pipelines that want `apply` to default to writing can set `FALSE`. |
| `options.validate_before_apply` | Currently advisory (reserved for a future pre-flight); no harm leaving it `TRUE`. |

### Sheet 3 — `DOORS Upload` (once per project, only if pushing to DOORS)

Only 3 user fields (rest of the DOORS mapping is bundled in
`<skill>/assets/doors_mapping_skeleton.yaml`):

| Field | What to set |
|-----|-------------|
| `doors.document_uuid` | **Replace** the placeholder `PUT-DOORS-DOCUMENT-UUID-HERE` with the project's DOORS module UUID. |
| `mode` | Default `insert`. Almost always leave alone. |
| `upload.dry_run` | Default `FALSE`. Set `TRUE` to build but skip the HTTP upload. |

`<skill>/scripts/excel_loader.py` reads the workspace xlsx at the
start of every pipeline / DOORS run and writes derived JSON / YAML
files into workspace `.cache/` (gitignored). The runtime keeps the
same internal split (`{project, parameters}` + `{paths, options}` +
DOORS mapping) so every existing call site continues to work.

## 4. First health check

```bash
cd <project-root>
python <skill>/scripts/pipeline.py status
```

Expected output is a dashboard ending in `OVERALL: READY`. Common
non-ready states and how to fix them:

| Line | Meaning | Fix |
|------|---------|-----|
| `[diagcomm-toolkit] No workspace found at: ...` | `--init-project` was not run for this project. | `cd <project-root> && python <skill>/scripts/pipeline.py --init-project` |
| `[diagcomm-toolkit] v1.20.x in-skill workspace detected: ...` | Old in-project skill clone still around. | `python <skill>/scripts/migrate_v1_20_to_v2.py --from-skill <project-root>/.agents/skills/diagcomm-toolkit` |
| `[diagcomm-toolkit] Pre-1.20.0 file detected: ...` | Old JSON+YAML inputs still present. | `python <skill>/scripts/pipeline.py --init-project` then `python <skill>/scripts/migrate_v1_19_to_xlsx.py --legacy-from <dir-with-old-json>` |
| `dcom_root : BROKEN` | `paths.dcom_root` glob matched nothing, or resolved to a folder without the `RBAPLCust`/`Cubas` health markers. | Narrow / widen the glob; ensure the folder actually contains the `CusDiag` arxml tree. |
| `arxml files : DEGRADED N/5 present` | One of the alias-mapped arxml files is missing. | Either the project genuinely does not ship that file (rare), or the alias override in `paths` is wrong. Check the listed `MISSING` line. |
| `schema : DRIFT` | `<skill>/assets/DiagComm.txt` was edited but `<skill>/assets/DiagComm_schema.json` is stale. | Run `python <skill>/scripts/pipeline.py gen-schema` (maintainer-only). |
| `landing_report / FSCS : STALE` | Snapshots are older than the newest input arxml. | Regenerate via `landing-report` / `fscs`, or `apply --dry-run` to refresh the diff-driven artifacts. |
| `inputs : NEEDS-FILL inputs/DiagComm.xlsx (N required field(s) not filled)` | The Excel template is present but at least one required Value cell is blank. | Open workspace `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'` and fill the listed cells (red-highlighted). Re-run `status`. |
| `inputs : MISSING inputs/DiagComm.xlsx` | The user template was deleted from the workspace. | `python <skill>/scripts/pipeline.py --init-project --force` to recover the blank template. |

## 5. Verify mapping coverage

```bash
python <skill>/scripts/pipeline.py landing-report
```

- Expected **`unmatched locators: 0`**. A non-zero count means at least
  one PARAM_MAP entry cannot find its node in the current project's
  arxml.
- Each line under `== <param> ==` shows the locator + the SHORT-NAME
  chain of every hit. Use this to sanity-check that a locator is
  landing on the container you expect (e.g. `CusDiagXMT`, not
  `CusDiagXMTFunc`).

If the report flags unmatched locators:

1. **Container renamed**: extend the offending entry in
   `<skill>/scripts/mapping.yaml` with an alternate `ancestor_short_name` /
   `ancestor_short_name_prefix` that matches this project's naming.
   Then run `python <skill>/scripts/pipeline.py export-catalog` to
   refresh `<skill>/reference/landing_spots.md`. (Maintainer-only;
   editing the bundled mapping affects every project on the machine.)
2. **File relocated**: override the matching alias in workspace
   `inputs/DiagComm.xlsx::Sheet 'Paths & Options'::paths.*`.
3. **Genuinely missing from this project**: mark the entry `optional:
   true` in `<skill>/scripts/mapping.yaml` so validate warns instead
   of erring. (Again, maintainer-only.)

## 6. Baseline the existing configuration

```bash
python <skill>/scripts/pipeline.py status        # checks workspace inputs/DiagComm.xlsx + .cache/, lists unfilled REQ cells
python <skill>/scripts/pipeline.py fscs          # render a snapshot

# Want to compare against the live ARXML? (no edits — read-only suggestion):
#   python <skill>/scripts/pipeline.py reseed --from-arxml
#   # → workspace outputs/reseed_suggestion.json — transcribe interesting values into Excel by hand
```

- Workspace `inputs/DiagComm.xlsx` is **user-owned**. The skill never
  writes, deletes, or overwrites it in normal flows. To restore the
  blank template:
  `python <skill>/scripts/pipeline.py --init-project --force` (the
  agent never invokes `--force` on its own).
- `reseed --from-arxml` auto-picks a `project.product_type` suggestion
  by globbing `RBAPLCust/cfg/*/Can*_CusDiag_EcucValues_*.arxml` — if
  exactly one `<PT>/` folder ships the file, that value is suggested.
  Otherwise the schema default (`DPB`) is suggested. The user
  transcribes the right value into Excel. `--product-type DPB|ESP|IPB|RBU`
  overrides the probe.
- Workspace `outputs/FSCS.txt` is a human-readable snapshot of
  whatever is in the cache right now (loaded from
  `inputs/DiagComm.xlsx` at command entry).

## 7. Run the unit + integration tests (skill maintainer)

```bash
cd <skill>
pytest -q tests
```

All tests are self-contained (the integration suite uses a synthetic
fixture at `tests/fixtures/minimal/` plus a `tmp_path`-backed v2
workspace, not any real project's arxml). A green suite means the
split runtime + semantic + mapping layers all import cleanly on this
machine. End users do not need to run pytest.

## 8. Known-good sequence for a first real apply

```bash
cd <project-root>
python <skill>/scripts/pipeline.py validate          # expect errors=0
python <skill>/scripts/pipeline.py apply --dry-run   # review workspace outputs/diff_report.txt
# human eyeballs the diff ...
python <skill>/scripts/pipeline.py apply --apply     # surgical byte-level write
```

If the result is wrong, roll back via the project's source control
(`git checkout -- <arxml>`, `svn revert <arxml>`, etc.). Workspace
`outputs/diff_report.txt` lists every arxml that was touched, so
reverting is just `git checkout --` on that list.

## 9. DOORS upload first-time setup

*Optional — only relevant if this project pushes its FSCS into DOORS.*
`diagcomm-toolkit` is fully self-contained for Step 8: no sibling
skill needed.

### 9.1 Fill in the DOORS module UUID

Open workspace `inputs/DiagComm.xlsx::Sheet 'DOORS Upload'` and
replace the placeholder Value cell of `doors.document_uuid`:

```text
PUT-DOORS-DOCUMENT-UUID-HERE   →   <real DOORS module UUID>
```

The other fields (`anchor.by_heading`, `defaults`, `value_maps`,
`columns`) live in the skill-bundled
`<skill>/assets/doors_mapping_skeleton.yaml` and ship with sensible
defaults for the Bosch / DWA convention; adjust only when a project
genuinely diverges.

### 9.3 Verify the UUID + anchor on a real DOORS dump

```bash
cd <project-root>
python <skill>/scripts/doors_sync.py --no-upload   # auto-refreshes the cache, builds the xlsx; reads inputs only
python <skill>/scripts/doors_helper.py show-target --mapping .cache/doors_mapping.yaml
```

`show-target` exits 0 only when the UUID is real (not the placeholder).
Then run `SKILL.md` Step 7.5d to confirm
`anchor.by_heading` (`"CAN ID and Timing Requirements"`) matches
exactly one row in the live module.

### 9.4 Cache the DOORS password (one-time per machine)

```bash
python <skill>/scripts/doors_sync.py --user-nt <NT> --password <pwd> --save-credentials --no-upload
```

This stores the password ciphertext in the OS keychain (Windows
Credential Manager via DPAPI / macOS Keychain / Linux Secret Service).
Subsequent runs read it back silently — zero prompts, zero env vars,
zero plain-text on disk.

> **Never paste the password into the chat.** Run this command
> yourself in your own terminal. The agent must not run
> `--save-credentials` on your behalf with a password that already
> appeared in chat history (Hard rule 9 in `SKILL.md`).

### 9.5 First real upload

```bash
python <skill>/scripts/doors_sync.py --user-nt <NT>
```

`doors_sync.py` auto-classifies the change (`first_insert` for a fresh
module, then `params_changed` / `pp_only_changed` / `fscs_only_changed`
on later runs), builds the xlsx, uploads, reconciles the real
`AbsoluteNumber`, and persists workspace `state/doors_upload_state.json`.
From here on, every Step 8 invocation is a single `--user-nt <NT>`
line.

### 9.6 Verify (Step 8d)

```bash
python <skill>/scripts/doors_fetch.py <module_uuid> <NT> --refresh \
    --out outputs/doors_verify.json
```

Look up the row by `state.modules[<uuid>].last_success_abs` (NOT the
`SUCCESS:<n>` upload-counter). The Object Text content lives under
`row["DescriptionOfRequirementRB"]` in the fetch JSON — see
[`reference/doors_tool_inventory.md`](doors_tool_inventory.md#get_doors_module).

## 10. Extending the skill for a project-specific field (maintainer)

These steps modify the skill checkout itself, not any workspace.
Every project on the machine sees the change.

1. Add the user-facing parameter name to `<skill>/assets/DiagComm.txt`.
2. Add the corresponding `FIELD_DEFS` entry to `<skill>/scripts/schema.py`
   (type / default / range / PR or PF / `maps_to` note).
3. Run `python <skill>/scripts/pipeline.py gen-schema` to refresh
   `<skill>/assets/DiagComm_schema.json`. Then run
   `python <skill>/scripts/build_inputs_template.py` so
   `<skill>/assets/inputs_template.xlsx` matches.
4. Add one or more entries to `<skill>/scripts/mapping.yaml` pointing
   at the target arxml node(s). If a new transform is needed, add it
   to `<skill>/scripts/mapping.py::TRANSFORMS` *and*
   `REVERSE_TRANSFORMS` (otherwise `reseed`'s reverse walk cannot
   pre-fill the field).
5. Run `python <skill>/scripts/pipeline.py export-catalog` so
   `<skill>/reference/landing_spots.md` stays in sync with the new
   entries.
6. Add a semantic check in `<skill>/scripts/semantic.py` if the field
   has a cross-field or range constraint that the schema type system
   alone cannot express.
7. Add a pytest case in `<skill>/tests/test_semantic.py` and / or
   `<skill>/tests/test_mapping.py` for the transform round-trip.
8. Run `landing-report` and `apply --dry-run` from a real project to
   confirm the new entry reaches the expected node(s).

## 11. Editor / shell compatibility

Every entrypoint is plain Python CLI. Cursor, OpenCode, Aider, Claude
Code, VS Code, or a bare PowerShell / bash shell all invoke the same
`python <skill>/scripts/pipeline.py` (Steps 2–6) and
`python <skill>/scripts/doors_sync.py` (Step 8) sub-commands.

Fresh-project flow: `--init-project` → open workspace
`inputs/DiagComm.xlsx` → fill the 9 REQ cells on Sheet 'Project &
Parameters' → `status` → `validate` → `apply --dry-run` →
`apply --apply` → *(optional)* `doors_sync.py`.

## 12. Checklist summary

Install path (once per machine):

- [ ] `~/.cursor/skills/diagcomm-toolkit/` populated from git
- [ ] `python -m pip install -r <skill>/scripts/requirements.txt` succeeds
- [ ] `python <skill>/scripts/preflight.py` reports `[skill] OK`

Bootstrap path (once per project):

- [ ] `cd <project-root> && python <skill>/scripts/pipeline.py --init-project`
- [ ] `<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/inputs/DiagComm.xlsx` exists

Apply path (Steps 2–7):

- [ ] workspace `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'::project.name` set for this project
- [ ] workspace `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'::project.product_type` matches the deployed `RBAPLCust/cfg/<PT>/` folder
- [ ] workspace `inputs/DiagComm.xlsx::Sheet 'Project & Parameters'::parameters.CAN_Channel` matches the deployed `Can<N>_CusDiag_EcucValues_<PT>.arxml`
- [ ] workspace `inputs/DiagComm.xlsx::Sheet 'Paths & Options'::paths.base_dir` + `paths.dcom_root` resolve to the live `dcom/` tree
- [ ] `pipeline.py status` → `OVERALL: READY`
- [ ] `pipeline.py landing-report` → `unmatched locators: 0`
- [ ] `pipeline.py validate` → `errors: 0`
- [ ] `pipeline.py apply --dry-run` → diff reviewed
- [ ] Rollback path confirmed before `apply --apply` — the target
  project's source control (`git checkout -- <arxml>` /
  `svn revert <arxml>` / equivalent)

DOORS upload path (Step 8, optional):

- [ ] `<skill>/assets/doors_template.xlsx` exists (bundled with the skill; if missing the install is incomplete — restore via `cd <skill> && git checkout -- assets/doors_template.xlsx`)
- [ ] `<skill>/assets/doors_mapping_skeleton.yaml` exists (bundled; same recovery)
- [ ] workspace `inputs/DiagComm.xlsx::Sheet 'DOORS Upload'::doors.document_uuid` replaced with the real UUID (not the `PUT-DOORS-…` placeholder)
- [ ] `doors_helper.py show-target` exits 0
- [ ] Step 7.5d confirms `anchor.by_heading` matches exactly one row
- [ ] DOORS password cached once with `doors_sync.py --user-nt <NT> --password <pwd> --save-credentials --no-upload`
- [ ] `doors_sync.py --user-nt <NT>` exits 0 and workspace `state/doors_upload_state.json` shows the correct `last_success_abs`
- [ ] Step 8d verify against the live module → row at `last_success_abs` carries the expected Object Text under `DescriptionOfRequirementRB`
