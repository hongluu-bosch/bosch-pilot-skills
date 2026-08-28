# Changelog

All notable changes to **did-toolkit** are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

- `MAJOR` — breaking changes to pipeline CLI, `fscs.json` schema, review-report contract, or the generated-file layout under `outputs/`.
- `MINOR` — new features, new phases, new reviewer checks, new `storage_pos` aliases, new CLI flags — backward compatible.
- `PATCH` — bug fixes, test additions, documentation clarifications, refactors that do not change observable behavior.

---

## [2.4.0] — 2026-06-05

### HardCode DID auto-generation (per-DID header split)

v2.4.0 introduces **automatic generation** of per-DID constant headers for
`ROM` / `FLASH` (HardCode) storage-class DIDs. The generator parses the
FSCS `service_22_behavior` text for a standard `HardCode:` block and emits:

* **`api/RBAPLCUST_RDBI_<DidName>.h`** — a per-DID header containing the
  `#define C_DID_<DidName>_Byte<N>_UB 0x<HH>u` ladder.
* **`src/Common/RBAPLCUST_RDBI_<DidName>.c`** — a fully-generated read body
  that copies via `Data[i] = C_DID_..._UB;` macros instead of raw hex literals.

Both files use **skip-if-exists** — once created they are never overwritten,
so hand-tuned values are safe across re-runs.

### Added

- `scripts/implementation/hardcode_parser.py` — parses `HardCode:` behavior
  blocks and returns per-byte `(index, hex_value, is_parsed)` tuples.
- `scripts/templates/impl/did_header.j2` — Jinja2 template for the per-DID
  constant header.
- `scripts/implementation/generators.py::generate_did_header()` — renders
  the per-DID header from parsed behavior text.
- `scripts/implementation/orchestrator.py` — auto-derives `api/` path from
  `c_output_dir` (`src/<PT>/` → `api/`) and writes the `.h` file for every
  HardCode DID before the matching `.c`.
- `scripts/templates/impl/read_code.j2` — HardCode DIDs now auto-`#include`
  their matching per-DID header.

### Changed

- `reference/input-format.md` — new §"HardCode Behavior Format (ROM / Flash
  DIDs)" documenting the standard block format, parsing contract, ASCII
  shorthand, and generator output.
- `reference/phase-1-fscs.md` — §4 "HardCode behavior format" now references
  `input-format.md` and explains the auto-generation vs stub fallback.
- `reference/phase-3-implementation.md` — §2 "Storage-class dispatch" updated:
  `ROM` / `FLASH` now reads "Auto-generated .c body + matching .h header
  … Agent reviews correctness." §6 workflow updated to reflect that HardCode
  DIDs are auto-generated and only need agent review.
- `reference/implementation-storage-positions.md` — §2 completely rewritten
  to describe the v2.4.0 auto-generation flow, behavior format, generated
  header / C body examples, agent review checklist, and fallback / stub mode.
- `SKILL.md` — version bumped to `2.4.0`; Phase 3 description updated to
  include HardCode auto-generation.

### Migration notes

Existing `RBAPLCUST_ConfigElements.h` entries that contain HardCode constants
are **not** cleaned up by this release — the generator only writes new per-DID
headers and never touches existing shared headers. Operators who want to
migrate legacy constants should do so manually (copy from `ConfigElements.h`
into the matching `RBAPLCUST_RDBI_<DidName>.h`, then delete the old block).

---

## [2.3.1] — 2026-05-16

### Self-review fixes for the 2.3.0 keychain port

Post-merge review of the 2.3.0 changes turned up two real bugs and
one significant test gap. None of them shipped behavioural regressions
to the legacy `--password` / `$DOORS_PWD` paths, but all three are
worth a clean patch release before more users hit them.

### Fixed

- **`--no-keyring` + `--save-credentials` / `--forget-credentials`
  now reports the actual conflict.** Previously the admin-op short-
  circuit bottomed out in `_keyring_set` / `_keyring_delete`, both of
  which warn `keyring not installed -- run pip install`. That message
  is wrong (and harmful as advice) when the user *deliberately*
  passed `--no-keyring` to disable the backend. Both admin ops now
  detect the flag combo up front and tell the user to drop
  `--no-keyring` instead. Same fix on the build-time `--save-
  credentials` path in the main flow (now prints
  `--no-keyring suppresses --save-credentials; password not cached
  this run` instead).
- **Link upload now runs through the auth-retry helper.** New
  `_update_links_with_pwd_refresh` mirrors `_upload_one_with_pwd_
  refresh` for the `update_doors_links` MCP call. Closes a corner
  case where, if all per-service workbooks classify NOOP
  (`rows_written == 0`), the link upload becomes the FIRST auth-
  bearing call of the run; previously a stale-keychain rejection at
  that one site would surface as a hard `RuntimeError` instead of
  the recoverable one-shot prompt every other DOORS upload gets.
  When the per-service uploads ran first (the common case), the link
  call's first attempt succeeds with the already-validated password,
  so the helper is a thin pass-through and there's no behaviour
  change.

### Internal

- Extracted `_call_doors_with_pwd_refresh(call_fn, ..., on_password_
  change=...)` as the call-agnostic auth-retry core; the per-call-
  site wrappers (`_upload_one_with_pwd_refresh` and the new
  `_update_links_with_pwd_refresh`) are thin shims around it.
  Mirrors the diagcomm-toolkit pattern but generalised so MCP
  endpoints with different signatures (`upload_module` vs
  `update_links`) can share the LDAP-safe one-shot retry contract
  without duplication.

### Tests

- 13 new unit tests (`tests/unit/test_doors_sync_keyring.py`):
  - Nine cover every branch of `_upload_one_with_pwd_refresh`
    (happy path, non-auth-fail propagation, source `prompt` / `cli`
    / no-TTY all skip retry, source `keyring` retry-success +
    keychain-refresh, source `keyring` retry-fail no-keychain-
    touch, empty prompt no-retry, Ctrl+C at prompt no-retry, source
    `env` retry-eligible). The 2.3.0 release shipped this code
    untested -- this release pins the LDAP-attempt budget at 2
    via mocks that IndexError if a refactor introduces a silent
    loop.
  - Two cover the new `_update_links_with_pwd_refresh` (happy path
    + stale-keychain-then-prompt-success).
  - Two cover the `--no-keyring` conflict messaging on both admin
    ops (regression tests for the misleading-message bug above).
- Full suite: **772 passed** (was 759).

### Validation

- `pytest tests/` -> 772 passed.
- Manual smoke (Windows Credential Manager, throwaway NT
  `__did_smoke2__`): full prime → cross-process read-back → forget
  cycle still works after the helper refactor.
- Manual smoke for `--no-keyring` conflict: both
  `--save-credentials --no-keyring` and `--forget-credentials
  --no-keyring` now print the explicit "drop --no-keyring" message
  instead of the misleading "install keyring" one.

---

## [2.3.0] — 2026-05-16

### `--phase doors` now caches the DOORS password in the OS keychain

Phase 4 (DOORS sync) gains a 4-level password fallback and three new
admin-op flags so the operator never has to put the DOORS password on
the CLI, in `$env`, or in any file. The password lives in the
OS-native secret store: Windows Credential Manager (DPAPI), macOS
Keychain, or Linux Secret Service via `gnome-keyring` / KWallet —
ciphertext only, user-bound, machine-bound.

Cross-port from `diagcomm-toolkit` v1.17.0 + v1.19.3, including the
"cold-start short-circuit" lesson from `diagcomm-toolkit` v1.19.3:
the cache-priming command (`--save-credentials --no-upload`) MUST
exit before reading any pipeline input — otherwise it would silently
fail on a brand-new project where FSCS / mapping / state don't exist
yet, and the user would think the password wasn't saved.

### Behavioural changes

- `scripts/fscs/doors/doors_sync.py` password resolution order
  (was: `--password` → `$DOORS_PWD` → interactive prompt; now:
  `--password` → `$DOORS_PWD` → **OS keychain** → interactive prompt).
  Existing CI runs that rely on `$DOORS_PWD` are unaffected; existing
  interactive runs that previously prompted every time will now
  prompt **once** and cache.
- `--user-nt` now accepts `$DOORS_USER_NT` as a fallback (parity with
  `$DOORS_PWD`). The fallback is consulted by every step that needs
  the NT identity (fetch / upload / fresh fetch / link upload /
  admin ops).
- The first content workbook upload runs through a new auth-retry
  helper (`_upload_one_with_pwd_refresh`). On a `401` / `Unauthorized`
  / `Invalid credentials` / `认证失败` / etc. AND the password came
  from cache (env or keychain), the operator gets ONE prompt for a
  refreshed password; on retry success the new password silently
  overwrites the keychain entry. The script never retries more than
  once per run — most enterprise DOORS deployments delegate auth to
  LDAP / AD which lock the NT account after 3-5 wrong attempts.

### Added

- `--save-credentials` (`scripts/fscs/doors/doors_sync.py` +
  `scripts/pipeline.py`) persists `(user_nt, password)` to the OS
  keychain. Combine with `--no-upload` to **prime the cache without
  doing any upload** — this is the recipe the agent generates on a
  brand-new machine.
- `--forget-credentials` (`scripts/fscs/doors/doors_sync.py` +
  `scripts/pipeline.py`) deletes the keychain entry for `--user-nt`
  (or `$DOORS_USER_NT`) and exits. Self-contained admin op: does
  not build, does not upload, does not fetch.
- `--no-keyring` (`scripts/fscs/doors/doors_sync.py` +
  `scripts/pipeline.py`) bypasses the OS keychain entirely (do not
  read, do not write). Useful for CI, debugging, or hosts with no
  Secret Service backend.
- `keyring>=23,<26` added to `scripts/requirements.txt`. It is
  technically optional — `doors_sync.py` degrades gracefully to the
  env-var / interactive-prompt path if the import fails or
  `--no-keyring` is set — but pinned so a fresh install gets the
  zero-prompt UX out of the box.
- 46 new unit tests in `tests/unit/test_doors_sync_keyring.py`
  covering the 4-level fallback ordering, the three keyring helpers
  (with a mock backend), the auth-failure regex (English + Chinese
  tokens), and the cold-start admin-op short-circuits (which must
  exit before reading mapping yaml / FSCS / state).

### Cold-start workflow

```text
# One-time per machine (asks no questions, writes to keychain only):
cd <project-root>
python <skill>/scripts/fscs/doors/doors_sync.py \
    --user-nt <NT> --password <pwd> --save-credentials --no-upload

# Every run after that — zero password prompts, zero env vars:
python <skill>/scripts/pipeline.py --phase doors --user-nt <NT>

# Forget on this machine:
python <skill>/scripts/fscs/doors/doors_sync.py \
    --user-nt <NT> --forget-credentials
```

Keychain entries live at `service="did-toolkit:doors"`,
`username=<NT>` (parallel to `diagcomm-toolkit:doors`).

### Hard rule reminder for the agent

Never ask the user to paste their DOORS password into the chat.
Tell them to run the `--save-credentials --no-upload` command
themselves in their own terminal once. Never run
`--save-credentials` on the agent's behalf with a password the user
typed earlier in the conversation — that path leaks the secret
into chat history.

### Internal

- New helpers in `scripts/fscs/doors/doors_sync.py`:
  `_try_import_keyring`, `_keyring_get`, `_keyring_set`,
  `_keyring_delete`, `_resolve_password` (returns
  `(password, source)`), `_upload_one_with_pwd_refresh`,
  `_looks_like_auth_failure`. Constants:
  `KEYRING_SERVICE = "did-toolkit:doors"`, `_AUTH_FAIL_RE`.
- The admin-op short-circuits (`--forget-credentials` and
  `--save-credentials --no-upload`) live OUTSIDE the main
  `try/except` so their stderr messages and clean rc=0/2 are never
  swallowed by the broad exception handler. This is the lesson
  from `diagcomm-toolkit` v1.19.3 — wrap the lesson into the
  layout, don't reinvent the bug.

### Validation

- `pytest tests/` — **759 passed** (was 713 before; +46 new for the
  keyring path).
- Manual smoke (Windows Credential Manager, throwaway NT
  `__did_toolkit_smoke__`):
  `--save-credentials --no-upload` writes; round-trip
  `keyring.get_password` reads back the exact value;
  `--forget-credentials` deletes; idempotent re-`--forget-credentials`
  is a benign success.

---

## [2.2.0] — 2026-05-15

### Workspace path: `.DCOM_AI/` → `.DCOM_AI/DID_Toolkit_PRJ/`

**The workspace gains a second-level namespace.** The toolkit's
artefacts now live at
`<container>/.DCOM_AI/DID_Toolkit_PRJ/{config,inputs,outputs,scripts,state}/`
instead of the previous single-level
`<container>/.DCOM_AI/{config,inputs,outputs,scripts,state}/`.
`.DCOM_AI/` is now the generic AI-tooling umbrella; the
fixed-name `DID_Toolkit_PRJ/` is this skill's slot inside it. The
two-level shape leaves room for parallel AI tools to coexist
under sibling subdirectories without colliding with the
did-toolkit's directory tree, while preserving the `.git/`-style
dot-prefix so file-tree viewers still hide everything by default.

### Behavioural changes

- `scripts/project_root.py` exports two new constants
  (`DCOM_AI_UMBRELLA_DIR = ".DCOM_AI"`,
  `TOOLKIT_SUBDIR = "DID_Toolkit_PRJ"`); the existing
  `DCOM_AI_WORKSPACE_DIR` is now the composite
  `".DCOM_AI/DID_Toolkit_PRJ"` and `PROJECT_MARKER_PATH` is
  `".DCOM_AI/DID_Toolkit_PRJ/config/project.json"`.
- `--project-root` / `$DID_TOOLKIT_PROJECT_ROOT` now accept any of
  three sensible shapes: the **container path** (resolver hops
  through `.DCOM_AI/DID_Toolkit_PRJ/` automatically), the
  `.DCOM_AI/` umbrella path (one hop into `DID_Toolkit_PRJ/`),
  or the workspace path itself.
- `--init-project` scaffolds the new two-level path; the FRESH
  state now means "no `.DCOM_AI/DID_Toolkit_PRJ/` yet" (the
  `.DCOM_AI/` umbrella may or may not exist — both situations
  fold into FRESH).
- The CWD walker still works from inside the workspace, inside
  the umbrella, inside the Bosch tree, or inside any descendant —
  pathlib's `parents` chain eventually surfaces a container with
  the marker.

### Breaking changes — no backward compatibility window

1. **Workspace layout changes.** Operators on the v2.1.x single-
   level `.DCOM_AI/{config,...}` layout (or even older flat
   layouts) must manually move their sub-folders into
   `.DCOM_AI/DID_Toolkit_PRJ/`. See
   [`reference/workspace-model.md`](reference/workspace-model.md)
   §"Migrating from an older layout" for the recipe; the
   resolver hard-fails to find the workspace otherwise.
2. **No auto-migration.** `--init-project` will not move legacy
   directories for you, and `resolve_project_root` will not match
   a single-level layout. By design — this is a development-version
   bump with no compatibility surface to maintain.

### Migration

```bash
cd /path/to/my-bosch-project
mkdir -p .DCOM_AI/DID_Toolkit_PRJ
# v2.1.x → v2.2.0:
mv .DCOM_AI/config .DCOM_AI/inputs .DCOM_AI/outputs .DCOM_AI/DID_Toolkit_PRJ/
[ -d .DCOM_AI/scripts ] && mv .DCOM_AI/scripts .DCOM_AI/DID_Toolkit_PRJ/
[ -d .DCOM_AI/state   ] && mv .DCOM_AI/state   .DCOM_AI/DID_Toolkit_PRJ/

# Pre-v2.1.x (flat layout) → v2.2.0:
# mv config inputs outputs .DCOM_AI/DID_Toolkit_PRJ/
```

`config/project.json` is unchanged — `paths.base_dir` still
points at the container — so no schema migration is required.
Phase 2 / Phase 3 project-tree write paths are unaffected;
only the location of the toolkit's own bookkeeping moved.

---

## [2.1.0] — 2026-05-15

### Operator-edit UX overhaul: CSV → XLSX

**The operator-edit artefact moves from `fscs_edit.csv` to
`fscs_edit.xlsx`.** Plain CSV gave operators zero feedback when
they typo'd an enum (`TRUE` → `Trie`, `EEPROM` → `eporm`, `RW` →
`R/W`) — every such drift made it all the way to xlsx-import
before failing, costing a round-trip and confusing the
field-level Pydantic error trace. The new workbook ships with:

- **Drop-down (list) validations** on every closed-vocabulary
  column: `used_flag`, `service_22_support`,
  `service_2e_support` → `TRUE` / `FALSE`; `product_type` →
  `Common` / `DPB` / `ESP` / `ESPCL` / `IPB` / `RBU`; `rw_state`
  → `R` / `W` / `RW`; `data_type` → `ASCII` / `Unsigned` /
  `Signed` / `HEX` / `Bytefield` / `Texttable` / `enum` /
  `Linear` / `Identity`; `storage_position` → `EEPROM` / `RAM` /
  `ROM`. Excel / WPS refuse free-text on those cells.
- **Auto-fit column widths** computed from the longest visible
  cell, with extra padding budgeted for CJK so the
  Chinese-name and behavior columns stay readable on the first
  open.
- **Frozen header row** + **autofilter** across the full data
  range — large worksheets no longer scroll their header out of
  view.
- Pydantic schema validation still runs on import, so the
  drop-downs are a UX hint, not the authority. Workbooks edited
  in a tool that strips data validations are still safely
  rejected at the field level.

### Breaking changes — no backward compatibility window

1. **`pipeline.py --phase csv-import` → `pipeline.py --phase
   xlsx-import`.** The old phase name is gone (no alias).
2. **`--csv` flag → `--xlsx`** on `--phase xlsx-import`. Passing
   a `.csv` path produces a clear `[ERROR]` line directing the
   operator to regenerate `fscs_edit.xlsx` with `--phase fscs`.
3. **`scripts/fscs/csv_edit.py` is removed**; replaced by
   `scripts/fscs/xlsx_edit.py` (uses `xlsxwriter` for export and
   `openpyxl` for import). Public package surface
   (`scripts.fscs.__init__`) re-exports `XLSX_COLUMNS`,
   `VALIDATIONS`, `export_fscs_xlsx`, `import_fscs_xlsx` in
   place of the old CSV symbols.
4. **`scripts/requirements.txt` now requires `openpyxl>=3.1,<4`**
   alongside the existing `xlsxwriter>=3.1`.

### Migration

1. Pull `v2.1.0`.
2. `pip install -r scripts/requirements.txt` to pick up
   `openpyxl`.
3. Re-run `python scripts/pipeline.py --phase fscs` against your
   workspace — Phase 1 will regenerate
   `.DCOM_AI/outputs/fscs/fscs_edit.xlsx` from the live
   `fscs.json`, preserving `used_flag` / `product_type` /
   behavior text exactly as they were.
4. Edit the workbook in Excel / WPS as before; the constrained
   columns now refuse invalid entries up front.
5. `python scripts/pipeline.py --phase xlsx-import` to push the
   edits back into `fscs.json` + `FSCS_22.txt` + `FSCS_2E.txt`.

No project-tree write paths, schema fields, or downstream
contracts changed — Phase 2 / Phase 3 / Phase 4 see the same
`fscs.json`.

---

## [2.0.0] — 2026-05-15

**First GitLab public release.** Consolidates the 1.x development
lineage into a stable baseline: `.DCOM_AI/` workspace layout,
resumable `--init-project` state machine, skip-on-conflict
project-tree writes for Phase 2 / Phase 3, agent-driven Phase 3
with inline `TODO(agent)` blocks, MISRA + paired `*MESGDef`
macro constraints, agent contextual-learning paths for RAM/ROM
dependency search, and `Product_Type=Common` default.

No CLI or schema changes vs 1.28.0. The skill is now project-
agnostic top-to-bottom — every customer-specific concern lives
in the target project's `.DCOM_AI/scripts/extract_<customer>.py`
adapter, never in the skill itself.

### Changed

- Documentation pass across `SKILL.md`, `reference/*.md`,
  `scripts/**/*.py`, `tests/**/*.py`, and `.smoke/*.py`:
  removed every historical `v1.X.0 BREAKING` wall, version-
  tagged section header, and retired-feature narration. All
  descriptions now read as current-state contracts.
- `README.md` trimmed to current-state quickstart.

### Removed

- No new removals beyond what 1.27.0 / 1.28.0 already shipped
  (no `--output-mode`, no `--list-briefs`, no `--no-backup`, no
  `--phase all`, no built-in workbook parser, no `_briefs/`
  directory, no rolling backup mechanism).

---

## [1.28.0] — 2026-05-15

**Resumable `--init-project` state machine.** The old "one-shot
scaffold then refuse to ever touch the workspace again" contract
is gone. `--init-project` now classifies the workspace into one of
four states and advances it by **exactly one step** per
invocation. Operators (and LLM agents) can drop a questionnaire
between runs, edit the recorded config, swap the questionnaire,
or let the COMPLETE state auto-chain into Phase 1 — all driven by
re-running the same command. v1.18.0's fail-loud behaviour for
unattended (non-TTY) mode is preserved at the
QUESTIONNAIRE_READY → write-config transition.

### Breaking

- **`--init-project` is no longer one-shot.** Pre-v1.28 callers
  that expected an empty directory to either (a) write
  `project.json` immediately given full `--name` / `--customer-name`
  / `--init-project-root` overrides OR (b) refuse with exit 4 must
  be updated. The new contract: on an empty directory, even with
  full overrides, `--init-project` only scaffolds `.DCOM_AI/` and
  exits 0 with a "drop a `*_did.json` and re-run" hint. The
  config-write step now requires a questionnaire to be present.
- **`refuses-to-overwrite-existing-config` (the v1.26.0 soft
  refusal at exit 1) is gone.** Re-runs on a fully-initialised
  workspace deliberately advance into Phase 1 instead of bailing.
  If the on-disk Bosch tree no longer matches the recorded
  `paths.pdm_file`, the state machine emits a `[WARN]` and (in TTY
  mode) prompts `Overwrite project.json with the detected tree?
  [y/N]`; non-TTY callers default to "keep" + WARN.
- **Schema 2.2 gains `paths.input_did_json`** — the basename of
  the questionnaire chosen during `--init-project`. The field
  defaults to `""` so old configs still load via `extra='forbid'`
  validation, but the COMPLETE-state auto-chain relies on it
  being populated. Hand-edited configs that swap the questionnaire
  filename must update this field.

### Added

- `scripts/init_project.py::_detect_init_state(workspace)` —
  read-only classifier returning one of `INIT_STATE_FRESH`,
  `INIT_STATE_FOLDERS_ONLY`, `INIT_STATE_READY` (questionnaire
  present, no `project.json`), `INIT_STATE_COMPLETE` (everything
  in place).
- `scripts/init_project.py::_pick_questionnaire(questionnaires,
  *, interactive, recorded_choice="", cli_override="")` —
  questionnaire resolver. Resolution order: `cli_override`
  (basename match; tolerates bare-basename or path-like forms),
  `recorded_choice` (basename from `paths.input_did_json`),
  single-candidate auto-pick (or `[Y/n]` confirm in TTY), multi-
  candidate numbered picker (TTY) / `_QuestionnaireAmbiguous`
  (non-TTY).
- `scripts/init_project.py::_detect_bosch_tree_drift(current,
  recorded_paths)` — narrow drift signal comparing the live
  `(project_root, customer)` scan against the segments baked
  into `paths.pdm_file`. Returns `None` when drift is undefined
  (no tree detected, mirror disabled, or matched).
- `scripts/init_project.py::_scaffold_workspace_skeleton(...)` and
  `_print_init_completed_summary(...)` — extracted so the state
  machine's FRESH and QUESTIONNAIRE_READY branches share output
  shape without duplicating logic.
- `--input <basename>` (existing flag) now also drives the
  questionnaire picker during `--init-project`. Useful when
  multiple `*_did.json` files sit under `.DCOM_AI/inputs/` in a
  non-TTY environment.
- `tests/unit/test_init_project.py`: 10 new tests pinning every
  state transition (`_detect_init_state_*`, `_pick_questionnaire_*`,
  `test_complete_state_chains_into_phase_1`,
  `test_complete_state_phase_1_failure_propagates_exit_1`,
  `test_complete_state_drift_non_tty_keeps_existing_config`,
  `test_non_tty_first_run_on_empty_dir_scaffolds_and_exits_0`).
- `.smoke/smoke_init.py` rewritten as a 5-case matrix exercising
  FRESH → FOLDERS_ONLY → QUESTIONNAIRE_READY → COMPLETE end-to-end,
  plus the COMPLETE auto-chain banner check.

### Changed

- **`run_init_project` is now a state machine** rather than a
  linear scaffolder. Every invocation calls `_detect_init_state`
  first and branches accordingly. The function still accepts the
  same kwargs (`name` / `customer_name` / `project_root` /
  `base_dir` / `interactive`), plus a new `input_choice` kwarg
  forwarded from `--input`.
- `paths.input_did_json` is now written by `--init-project` and
  read by the COMPLETE-state branch to skip the picker prompt on
  re-runs. Hand-editing the field in `project.json` is the
  recommended way to switch questionnaires without re-running
  the full init flow.

### Fixed

- `_detect_bosch_tree_drift` no longer raises `TypeError` when the
  live scan returns `None` (the "no tree visible" posture, which
  is common in non-mirror workspaces). It now returns `None` so
  the state machine treats absent-tree as "drift undefined" rather
  than a fatal error.

### Migration notes (v1.27.x → v1.28.0)

Most operators won't notice the change because the new contract
is strictly more forgiving:

1. **Existing fully-initialised workspaces keep working.**
   Re-running `--init-project` on a workspace that already has
   `project.json` + `*_did.json` simply chains into Phase 1.
2. **CI / unattended init must seed a questionnaire first.**
   The pattern is now:

   ```bash
   mkdir -p <project>/.DCOM_AI/inputs
   cp my_did.json <project>/.DCOM_AI/inputs/
   python scripts/pipeline.py --init-project <project> \
       --non-interactive --name MyProj \
       --customer-name rbcn --init-project-root Fe_Super
   ```

   The first command will then auto-detect QUESTIONNAIRE_READY and
   write `project.json` in one invocation. Without the
   `cp`, the empty workspace just gets scaffolded and exits 0.
3. **The exit-1 "refuses to clobber" guard is gone.** If you
   relied on it as a write-protection, lock the config file at
   the OS level instead. The state machine deliberately allows
   re-runs because the drift WARN + `[y/N]` prompt is the new
   safety net.

### Versioning rationale

This is `MINOR` rather than `MAJOR` because the changes are
additive on the schema side (one new field with a default) and
the CLI surface is unchanged — only the *behaviour* of
`--init-project` on a partially-initialised workspace is new.
However, the v1.26.0 "refuse to clobber" promise was broken and
the contract for non-TTY first-run was reshaped, so callers that
codified the old exit codes need to be updated; the migration
notes above cover the two real-world patterns.

---

## [1.27.1] — 2026-05-15

**Skill-repo cleanup, no behavioural change.** Removes the stale
pre-v1.26 workspace directories that lingered at the skill root
after the v1.26.0 layout migration, and moves the DOORS mapping
config from a tracked file into a scaffolded template.

### Removed

- `outputs/`, `inputs/`, `state/` at the skill root. These were
  pre-v1.26 workspace artefacts; v1.26.0 moved the workspace to
  `<project-container>/.DCOM_AI/`, so any reappearance at the skill
  root is now an accident (and the leftover `inputs/Olympus_*.xlsx`
  / `inputs/GAC*.xlsx` workbooks definitely shouldn't have been
  checked in).
- `.pytest_cache/`, `.pytest_cache_local/`, `pytest_out.txt` —
  runtime cruft from local test invocations.

### Moved

- `inputs/doors_mapping.yaml` →
  `scripts/templates/doors_mapping.yaml.template`. The file is
  per-project operator config, not a skill-shipped tracked input,
  so it now travels as a template that `--init-project` scaffolds
  into `.DCOM_AI/inputs/doors_mapping.yaml.template`. Operators
  rename it to drop the `.template` suffix before the first
  `--phase doors` run. Path references throughout the codebase
  (`scripts/fscs/doors/*.py`, `reference/phase-4-doors.md`,
  `reference/troubleshooting.md`, `README.md`) were updated to
  point at the new `.DCOM_AI/inputs/` location. The
  `SKILL_ROOT / "inputs" / "doors_mapping.yaml"` argparse fallbacks
  in `build_doors_payload.py` are kept (commented as stale
  fallbacks) so the standalone CLI keeps its shape, but the
  orchestrator never exercises them.

### Added

- `scripts/init_project.py::_scaffold_template_into` — generic
  helper that backs both the existing extractor-template scaffold
  and the new DOORS-mapping-template scaffold. Idempotent;
  re-running `--init-project` never clobbers a hand-edited file.
- `.smoke/smoke_init.py` case 2 now asserts
  `.DCOM_AI/inputs/doors_mapping.yaml.template` exists post-init.

### Updated

- `.gitignore`: drops the obsolete `outputs/backups/` rule and the
  comment that called `outputs/` "regeneratable from `inputs/`"
  (both pre-v1.26 references). Adds `inputs/` / `state/` /
  `.pytest_cache_local/` / `pytest_out.txt` defensively so the
  retired directories can't sneak back into a commit.

### Migration

If a v1.27.0 checkout is updated in place, no operator action is
needed. If the operator was relying on a hand-edited
`<skill>/inputs/doors_mapping.yaml`, copy it into the project's
`.DCOM_AI/inputs/doors_mapping.yaml` before re-running
`--phase doors`.

---

## [1.27.0] — 2026-05-15

**BREAKING — three structural cuts in one release:** the built-in
Excel extractor is gone, the `outputs/<artefact>/<PT>/` local mirror
for Phase 2 / Phase 3 is gone, and per-DID Markdown briefs are gone.
Operator feedback motivated each cut:

1. **GAC / Olympus parser noise crept into unrelated projects.** The
   built-in extractor under `scripts/excel_extract/` carried
   customer-specific column maps + heuristics. When the skill was
   pointed at a fresh project, it confidently miscategorised columns
   and emitted nonsense FSCS rows. The fix is to make Phase 1 strictly
   reject `.xlsx` / `.xlsm` input — agents must write a one-shot
   `extract_<customer>.py` adapter under `.DCOM_AI/scripts/` instead.
2. **`outputs/<artefact>/<PT>/` mirrored generated source.** Phase 2/3
   used to write `.arxml` / `.c` / `.h` / `.pdm` into both
   `.DCOM_AI/outputs/...` AND the Bosch tree. Two copies meant two
   chances to drift, two diffs to review, and confusion about which
   was authoritative. Phase 2/3 now write **only** into the Bosch
   tree (skip-on-conflict); reports stay under `.DCOM_AI/outputs/`.
3. **`_briefs/<HEX>_<svc>.md` had no readers.** The v1.15.0 briefs
   were meant to be an intermediate hand-off for the agent. In
   practice they introduced a round-trip (read brief → switch back
   to `.c` → fill in body) that broke the agent's context. Briefs
   are now inlined as a `TODO(agent)` comment block inside each
   generated `.c`, with the full DID identity / storage classification
   / FSCS behaviour text baked in. Phase 3 framework-and-fill happens
   in one continuous agent turn.

### BREAKING — what changed at the CLI / config / on-disk surface

* `--phase fscs -i <questionnaire>.xlsx` now exits with an error
  pointing at `reference/excel-ingestion.md`. Phase 1 accepts
  schema-compliant `*_did.json` only. The same JSON-only rule
  applies to `--list-inputs` auto-discovery.
* `--output-mode {outputs,project,both}`, `--no-backup`,
  `--list-briefs` were retired (argparse no longer recognises them).
  Calls passing those flags fail loudly rather than being silently
  ignored.
* `config/project.json` schema bumped to **2.2**. The `options` block
  is now empty by design (`output_mode`, `backup_before_write`,
  `backup_keep` all retired). The class is kept with
  `extra='forbid'` so stale knobs in hand-edited configs fail loud
  at load — re-run `--init-project` to refresh.
* `scripts/excel_extract/` was deleted in its entirety. Every test
  / smoke harness that imported it was deleted or rewritten.
* `scripts/implementation/briefs.py` was deleted. The
  `BackupManager` class in `scripts/implementation/safety.py` was
  removed; only `guarded_project_write` remains.
* `.DCOM_AI/outputs/implementation/<PT>/` and
  `.DCOM_AI/outputs/arxml/<folder>/` now hold **reports only**
  (`generation_report.txt`, `validation_report*.txt`,
  `arxml_review_report_*.txt`). Generated source / config files
  land in the Bosch tree exclusively.
* The Phase 2 ARXML merge and the Phase 3 header / PDM merges
  preserve existing content unconditionally (skip-on-conflict at
  the container / `#define` / entry level). The rolling backup
  mechanism under `outputs/backups/<ts>/` was removed because the
  new semantics never overwrite anything.
* `[AGENT STOP]` no longer fires after Phase 3 framework
  generation. Phase 3 closes with an `[AGENT TODO]` summary
  enumerating *X fill targets* (DIDs with non-empty FSCS
  behaviour text — agent expands the inline TODO block this same
  turn) and *Y stub targets* (behaviour empty / default — leave
  the TODO block in place for a future round).

### Migration (v1.26 → v1.27)

```bash
# 1. Refresh the workspace config (options block shape changed).
cd /path/to/my-bosch-project
python /path/to/skill/scripts/pipeline.py --init-project .

# 2. If the questionnaire is an .xlsx, write an extractor under
#    .DCOM_AI/scripts/extract_<customer>.py that reads the workbook
#    and emits .DCOM_AI/inputs/<customer>_did.json. See
#    reference/excel-ingestion.md for the JSON schema.

# 3. Re-run Phase 1 → CSV review → CSV import as usual.
#    Phase 2 + Phase 3 now write straight into the Bosch tree.
```

### Files

* **`SKILL.md`**, **`README.md`**, **`reference/workspace-model.md`**,
  **`reference/configuration.md`**, **`reference/excel-ingestion.md`**:
  rewritten for v1.27.0.
* **`scripts/pipeline.py`**: drop `--output-mode`, `--no-backup`,
  `--list-briefs`; `run_phase2` / `run_phase3` resolve the project-
  tree target via `resolve_mirror_path` + `paths.base_dir` and
  hard-abort when the tree is missing.
* **`scripts/generate_arxml.py`**: `generate(...)` signature changed
  (`output_mode` / `no_backup` kwargs removed, new `report_dir`
  kwarg points at `.DCOM_AI/outputs/arxml/<folder>/`). The
  `BackupManager` instance is gone.
* **`scripts/implementation/orchestrator.py`**: rewritten for the
  project-tree-only sink. Hard-aborts on missing `paths.base_dir`,
  tracks `skipped_c_files` / `agent_fill_targets` /
  `agent_stub_targets` in the returned stats, writes
  `generation_report.txt` with the filled-vs-stub breakdown.
* **`scripts/implementation/generators.py`**: new `classify_storage`
  + `_build_inline_todo_block` helpers; `_build_read_func_body` /
  `_build_write_func_body` emit the inline TODO block instead of
  pointing at an external brief.
* **`scripts/implementation/models.py`**: `DIDImplementationInfo`
  gained `did_name_zh`, `product_type`, `behavior_22`, `behavior_2e`
  so the inline TODO block has everything it needs at render time.
* **`scripts/implementation/safety.py`**: dropped `BackupManager`.
* **`scripts/implementation/briefs.py`**: deleted.
* **`scripts/excel_extract/`**: deleted.
* **`scripts/config/schema.py`**: `SCHEMA_VERSION = "2.2"`,
  `ProjectOptions` body cleared.
* **`scripts/init_project.py`**: starter `options` is `{}`.
* **`tests/integration/test_phase_all.py`**: deleted (phase-all
  auto-chain was retired in v1.25.0; this test was last vestige).
* **`tests/integration/test_arxml_project_mirror.py`**, **`test_per_product_skip.py`**: rewritten for the project-tree-only sink.
* **`tests/unit/test_config_schema.py`**, **`test_init_project.py`**,
  **`test_pipeline_argparse.py`**, **`test_collision.py`**,
  **`test_phase3_stub_for_non_nvm.py`**, **`test_code_generators.py`**:
  updated for the new contract.
* **`tests/unit/test_excel_extract_*.py`**, **`test_implementation_briefs.py`**, **`test_backup.py`**, **`tests/integration/test_backup_rolling.py`**, **`tests/integration/test_output_modes.py`**: deleted.

---

## [1.26.0] — 2026-05-14

**BREAKING — workspace artefacts moved under `.DCOM_AI/`; pre-v1.26
flat workspaces no longer resolve.** Operator feedback: in v1.25
and earlier, `--init-project <project-root>` scaffolded
`config/`, `inputs/`, `outputs/` (and v1.17.0's `state/`)
**directly under the Bosch project's container directory**,
polluting the project root with toolkit-specific folders that
Bosch tooling / file-tree viewers had to learn to ignore.
Customer teams also asked for a per-workspace `scripts/` slot
so the operator-written `extract_<customer>.py` adapter could
live next to its workspace rather than inside the skill
installation (where it polluted the skill folder instead).

v1.26.0 nests the entire workspace under
`<project-root>/.DCOM_AI/` — `.git/`-style hidden directory —
and adds `scripts/` + `state/` slots in the standard scaffold.
The pre-v1.26 flat layout is **no longer recognised** by
`scripts/project_root.py`; existing v1.25 workspaces must
migrate (one `mkdir` + four `mv` commands, see below) before
this version's resolver or scaffolder will see them.

### Why the change

Three pieces of operator feedback converged:

1. **Toolkit folders pollute the project tree.** Bosch projects
   already have a strong layout convention (`rb/as/<customer>/`,
   `core/app/`, etc.). Dropping a flat `config/inputs/outputs/`
   triplet at the project root made the toolkit's bookkeeping
   visible to every tool that scans the tree — IDE explorers,
   build scripts, Bosch's own diff tooling — and pushed
   operators to add ad-hoc `.gitignore` rules per project.
2. **`scripts/extract_<customer>.py` polluted the skill.** The
   v1.11.0+ excel-ingestion contract told operators to write
   one-off adapters under the **skill's** `scripts/` folder.
   This meant `did-toolkit/scripts/extract_gac.py` /
   `extract_olympus.py` / `extract_<every-customer>.py` all
   accumulated in the install directory, with no per-project
   isolation. Multi-workspace operators routinely ran a wrong
   extractor against the wrong workspace.
3. **State files had no obvious home.** v1.17.0's DOORS upload
   state machine landed `state/doors_upload_state.json` at the
   workspace root but never made it visible in the `--init-project`
   footer; new operators had to discover the dir empirically
   after the first `--phase doors` run.

`.DCOM_AI/` solves all three at once by giving the toolkit a
single, well-known, hidden home under the project container.

### BREAKING — flat workspace shape no longer recognised

`scripts/project_root.py` (the four-tier resolver) recognises
**only** the `.DCOM_AI/` marker. The pre-v1.26
`<container>/config/project.json` shape — sole layout from
v1.14.0 through v1.25.x — is gone:

| Container path | Marker file | Workspace path returned |
|---|---|---|
| `<dir>` (v1.26.0+) | `<dir>/.DCOM_AI/config/project.json` | `<dir>/.DCOM_AI/` |
| `<dir>` (pre-v1.26 flat) | `<dir>/config/project.json` | **not recognised** |

`--project-root <container>` and `$DID_TOOLKIT_PROJECT_ROOT`
accept either the **container path** or the `.DCOM_AI/`
workspace path directly — the validator follows the
`.DCOM_AI/` hop transparently when the operator points at the
container. From inside a Bosch-tree subdir, the CWD walker
climbs ancestors until it finds the `.DCOM_AI/` marker and then
returns the workspace (with the hop already applied), so all
phase code keeps using `self.base_dir` unchanged.

### Migration recipe (v1.25 → v1.26)

```bash
cd /path/to/my-bosch-project          # the project container
mkdir .DCOM_AI
mv config inputs outputs .DCOM_AI/
# optional, only if Phase 4 / DOORS was used:
[ -d state ] && mv state .DCOM_AI/
```

That's the entire migration. `config/project.json` is
unchanged on disk (schema still 2.1; `paths.base_dir` still
points at the container). Re-running `--init-project` after
the move is **not** needed — the pipeline auto-discovers the
new workspace location on the next invocation, and the
scaffolder would refuse (exit 1) because a workspace already
exists in the right place.

### Implementation

* **`scripts/project_root.py`**:
  - New constant `DCOM_AI_WORKSPACE_DIR = ".DCOM_AI"`.
  - `PROJECT_MARKER_PATH` changed semantics — now a relative
    path from the **container** (`".DCOM_AI/config/project.json"`)
    rather than from the workspace (`"config/project.json"`).
  - `is_project_root(dir)` now returns True only for
    `<dir>/.DCOM_AI/config/project.json`. The flat-marker
    branch was removed.
  - New helper `workspace_for(container) -> Path`: maps a
    container to `<container>/.DCOM_AI`, the path the pipeline
    treats as `self.base_dir`.
  - `find_project_root_upward(start)` returns
    `<container>/.DCOM_AI/` (the workspace) when the marker is
    found, so `controller.base_dir` consumers see `inputs/` /
    `outputs/` / `state/` / `scripts/` relative to the
    workspace transparently.
  - `_validate_explicit(path)` (the `--project-root` /
    `$DID_TOOLKIT_PROJECT_ROOT` validator) follows the
    `.DCOM_AI/` hop when the operator points at the container,
    and returns the workspace as-is when they point at it
    directly.

* **`scripts/init_project.py`**:
  - `--init-project <target>` scaffolds the workspace under
    `<target>/.DCOM_AI/` rather than directly at `<target>`.
  - Workspace contents: `config/`, `inputs/`, `outputs/`,
    plus two new slots `scripts/` (for operator-written
    one-off `extract_<customer>.py`) and `state/` (for
    `doors_upload_state.json` + future resumable bookkeeping).
  - `paths.base_dir` still resolves to `str(target)` (the
    project **container**, where the Bosch tree lives) — every
    `paths.*` mirror template therefore resolves against the
    same anchor it did pre-v1.26. Phase 2/3 mirrors require
    **no** code changes.
  - Bosch-tree scan still runs from the container (not from
    `.DCOM_AI/`) so the BSW tree is discovered correctly.
  - Collision check refuses (exit 1) when
    `<target>/.DCOM_AI/config/project.json` already exists.
    Check runs **before** any `mkdir` so a refusal leaves no
    half-scaffolded `.DCOM_AI/` stub.
  - "Next steps" / `[OK]` footer prints workspace-relative
    paths so the operator sees the actual on-disk layout
    (`.DCOM_AI/inputs/...` etc.).

* **`tests/unit/test_init_project.py`**: every assertion that
  reads `target/config/project.json` was updated to read from
  `_ws(target) / "config" / "project.json"` (the new helper
  centralises the `.DCOM_AI/` hop).

* **`tests/unit/test_project_root.py`**: rewritten end-to-end
  for the `.DCOM_AI/`-only resolver — `_scaffold_workspace`
  now creates the `.DCOM_AI/config/project.json` marker, every
  resolver test (predicate, walker, CLI tier, env tier, CWD
  walk tier, fallback) asserts the resolver returns the
  workspace (with `.DCOM_AI/` hop applied). New regression
  pin `test_is_project_root_false_for_flat_config` catches a
  silent re-introduction of pre-v1.26 backward compatibility.
  Container / workspace symmetry pinned for both CLI and env
  tiers.

* **`.smoke/smoke_init.py`**: rewritten to assert the
  v1.26 layout (`<target>/.DCOM_AI/` workspace, four required
  subdirs). Also fixed a pre-existing v1.24 mismatch —
  `arxml_file` is checked for `{product_type_arxml_folder}` +
  `{product_type_suffix}` now (was checking the dead
  `{product_type_upper}`).

* **Documentation**: `SKILL.md` (frontmatter + body intro +
  Quickstart + best-practices + version table),
  `README.md` (intro + scaffolding paragraph + extractor
  placement + version highlights), and
  `reference/workspace-model.md` (new "Workspace layout" +
  "Migrating from the v1.25 flat layout" sections +
  scaffolder steps + multi-config layout + pitfalls table)
  describe the new layout exclusively — every mention of the
  flat layout is framed as "not recognised, migrate".
  `reference/excel-ingestion.md` updates the
  `extract_<customer>.py` placement to live under the
  workspace (`.DCOM_AI/scripts/`) instead of the skill folder.
  `reference/configuration.md` clarifies that
  `paths.base_dir` points at the **container**, not the
  workspace.

### No schema bump

`schema_version` stays at `"2.1"` — `project.json`'s on-disk
shape didn't change, only where the file lives.
`paths.base_dir` continues to be the project container
(unchanged); the v1.26 workspace dir is implicit one level
deeper at `.DCOM_AI/`.

### Files touched

`scripts/project_root.py`, `scripts/init_project.py`,
`SKILL.md`, `README.md`, `VERSION`, `CHANGELOG.md`,
`reference/workspace-model.md`,
`reference/excel-ingestion.md`,
`reference/configuration.md`,
`tests/unit/test_init_project.py`,
`tests/unit/test_project_root.py`, `.smoke/smoke_init.py`.

---

## [1.25.0] — 2026-05-14

**Pipeline gated by default + `--init-project` questionnaire
pre-flight (BREAKING — `--phase all` removed; SKILL.md description
shrunk).** Operator-feedback batch: the auto-chained
`--phase all` was hiding mistakes (wrong used-flag scope, wrong
Product_Type tagging) until Phase 3 had already burned through
ARXML and C generation; `--init-project` was doing a heavy Bosch
tree scan before the operator had even placed the questionnaire;
the SKILL.md frontmatter description had grown to ~600 words
covering every BREAKING change back to v1.21.0, blowing past the
conservative context budgets some LLM hosts use to size the
description-injection slot. This release fixes all three.

### Why the change

Three pieces of independent operator feedback converged:

1. **Auto-chain hides mistakes.** Operators who ran
   `--phase all` would routinely realise *after* Phase 3
   finished that they wanted to flip `used_flag` on a handful of
   DIDs, or that they had forgotten to tag `Product_Type` —
   forcing a full re-run. The auto-chain saved typing but
   compressed three independent decisions (CSV scope, DOORS-vs-
   ARXML branch, output-mode) into one impulsive command.
2. **Init is slow on big trees.** Customer Bosch trees can hit
   5-10k files under `RBAPLCust/`. The two top-level
   `workspace.iterdir()` walks in `_detect_bosch_tree` +
   `_detect_per_product_overrides` added up to multi-second init
   times on slow / networked filesystems. Worse: init would
   complete *without* the operator placing a questionnaire,
   leaving the workspace in a "config OK but next command fails
   with 'no questionnaire in inputs/'" half-state.
3. **SKILL.md description ballooned.** Each BREAKING change
   v1.16 → v1.24 had added its own paragraph to the frontmatter
   `description:` field so an LLM picking up the skill cold
   would see the latest contract. The field grew past 600
   words; some hosts truncate at ~400 and the agent would lose
   the "self-contained" / "no `did_extract` dep" framing.

v1.25.0 addresses all three with explicit STOP gates, a
one-pass Bosch tree scan + questionnaire pre-flight, and a
~200-word description that points at `reference/*.md` +
`CHANGELOG.md` for the deep details.

### BREAKING — `--phase all` is gone

* The CLI choice list dropped `'all'`. Running
  `pipeline.py --phase all` (or no `--phase` at all under the
  pre-v1.25 default) now triggers an argparse error
  (`invalid choice: 'all'`).
* The default `--phase` is now **`fscs`** (was `all`). Running
  `pipeline.py` with no flag = `pipeline.py --phase fscs`.
* CI / automation scripts that relied on the auto-chain must
  spell out each phase. The recommended sequence is:
  ```bash
  python scripts/pipeline.py --phase fscs
  python scripts/pipeline.py --phase csv-import
  python scripts/pipeline.py --phase arxml
  python scripts/pipeline.py --phase implementation
  ```
  Phase 4 (`--phase doors`) and Phase 2/3 are independent
  branches — pick one or both as required.

### New behaviour — STOP gates + agent turn-stopping contract

Phase 1 (`--phase fscs`) now ends with an unmistakable
`[STOP] Phase 1 complete — review before continuing.` footer
that spells out: (a) which file to open
(`outputs/fscs/fscs_edit.csv`), (b) what to check
(`used_flag` scopes the build; `Product_Type` picks fan-out
target), (c) the exact follow-up command
(`--phase csv-import`).

CSV-import (`--phase csv-import`) ends with a
`[STOP] CSV import complete — review the used-DID scope below.`
footer carrying:

* Total DID count + effective counts per UDS service
  (0x22 / 0x2E).
* **Per-product work-set preview** — one line per
  `Product_Type` actually carried by an effective DID, with
  the DID count. This is the exact set Phase 2/3 would fan out
  over if invoked next.
* Empty-work-set warning if no DID is currently effective
  (most likely cause: every `used_flag=FALSE`).
* Explicit two-branch menu (DOORS vs ARXML/impl) with the
  full copy-paste commands.

The preview is *advisory* — failures while computing it are
swallowed and replaced with a minimal "summary unavailable"
fallback so the import itself is never gated on summary
success.

**Agent turn-stopping contract.** Each of the three gates
(init, Phase 1, CSV-import) also emits an `[AGENT STOP] End
this turn now.` directive line *after* the human-facing
`[STOP]` banner. SKILL.md ships a new "Cross-phase contract
D — Agent turn-stopping contract" section pinning what the
LLM driving the skill must do at every gate:

* Plain-text presentation of the [STOP] block + decisions
  (no `AskQuestion` — same posture as the existing
  multi-questionnaire / multi-config contracts).
* One phase per agent turn — even when the operator says
  "do everything", the agent runs the *next* phase only
  and stops again at its `[AGENT STOP]`.
* Never silently retry past a STOP — surface failures and
  ask.
* Quote the `[STOP]` block verbatim (paths + commands are
  what the operator needs).
* Operator can override aggressively ("just run all of it")
  but the gates stay one-per-turn so the operator still
  sees every decision.

This contract closes the loophole where some LLM hosts read
the v1.25.0 "[STOP]" narrative as advisory and just kept
firing tool calls — exactly the auto-chain behaviour the
release set out to remove. `[AGENT STOP]` is the only marker
the agent is required to recognise; the human-facing `[STOP]`
banner above it is for the operator.

### New behaviour — `--init-project` questionnaire pre-flight

`pipeline.py --init-project` now scaffolds `inputs/` *first*,
then checks for any `*.xlsx` / `*.xlsm` / `*_did.json` (same
tier rules as the runtime Phase 1 auto-discovery). Three
branches:

* **Already present.** Prints
  `[OK] N diagnostic questionnaire(s) detected in inputs/`
  with the first 5 filenames; continues without prompt.
* **Empty `inputs/` in TTY mode.** Prints a clear
  ```
  [!] No diagnostic questionnaire detected yet.
      Drop one (*.xlsx / *.xlsm / *_did.json) into:
        <absolute path to inputs/>
  ```
  and blocks on `Press Enter when ready (or Ctrl-C to
  abort)...`. After Enter, re-scans and either confirms the
  drop or prints a `[warn]` and continues anyway (the operator
  can place the file later — Phase 1 re-checks).
* **Empty `inputs/` in non-TTY mode (CI / agent shell).**
  Prints a single `[warn]` and continues. CI has nobody to
  wait for; blocking would deadlock the pipeline.

`Ctrl-C` during the prompt returns exit code 2 (irrecoverable
abort) so a calling script can distinguish "operator aborted"
from "questionnaire still missing post-prompt".

### Perf — one-pass Bosch-tree scan

`_detect_bosch_tree` + `_detect_per_product_overrides` used to
walk `workspace.iterdir()` twice. v1.25.0 adds
`_scan_bosch_workspace_once` which does the top-level scan
once and returns both `(project_root, customer)` and the full
`all_candidates` list (kept for future
"ambiguous tree → suggest `--project-root <name>`"
diagnostics). The deeper per-product walk under
`<workspace>/<project_root>/rb/as/<customer>/.../RBAPLCust/`
still runs once on the resolved customer — that walk is
unavoidable (it's the per-PT skip-sentinel detector).

Expected speedup: ~30-50% on slow / networked filesystems for
the common single-customer-tree case; no measurable effect on
the no-tree-detected fast path.

### Docs

* `SKILL.md` frontmatter `description:` rewritten from ~600
  words to ~200, focused on **what** + **when** (the trigger
  surface for LLM skill selection); breaking-change history
  delegated to this CHANGELOG entry.
* `SKILL.md` body Quickstart rewritten as a 4-step gated
  sequence; "Common commands" table re-shaped around the
  per-phase CLIs (Phase 1 / csv-import / arxml /
  implementation / doors) — no more `--phase all` row.
* `README.md` "想一键全跑" section retitled to "流水线总览
  （v1.25.0：分阶段、有停顿，不再一口气跑完）" with a flow
  diagram of the two STOP gates.
* `reference/commands.md`: `cmd: run_all` block replaced by a
  flow diagram + a `cmd: pipeline_default` stub.
* `reference/output-safety.md`: examples rewritten as separate
  `--phase arxml` / `--phase implementation` invocations.
* `reference/phase-4-doors.md`, `reference/phase-1-fscs.md`,
  `reference/testing.md`, `reference/review.md` updated to
  drop stale `--phase all` references.

### Test impact

`tests/integration/test_phase_all.py` already drives the
controller via direct `run_phase1` / `run_phase2` / `run_phase3`
method calls (not via the CLI), so the test continues to pass
on v1.25.0. The test filename is left as-is for historical
continuity; its docstring now notes "Phase 1+2+3 via controller
method calls (v1.25.0 no longer via `--phase all`)".

### Migration notes

* **CI scripts.** Replace `pipeline.py --phase all` with the
  four-command sequence shown above. There is no shorter form;
  the auto-chain was a deliberate removal.
* **Personal aliases.** If you had a shell alias around
  `--phase all`, retarget it at `--phase fscs` (the most
  common interactive starting point) and let the gating
  footers guide you to the next command.
* **Agent prompts / runbooks.** Search for `--phase all` and
  replace with `--phase fscs` + a note that the operator
  picks the next command from the printed STOP footer.

---

## [1.24.0] — 2026-05-14

**Phase-2 ESPCL → ESP path alias (BREAKING `paths.arxml_file`
template) + symmetric `_<suffix>` ARXML naming.** Replaces v1.23.0's
DID fold-in approach with a path-only alias: ESPCL still iterates
Phase 2 with its own DID set, but its outputs are routed into ESP's
folder so the two products share a Bosch directory without sharing
a filename.

### Why the change

v1.23.0 folded ESPCL DIDs into ESP's Phase 2 ARXML so a single
`cfg/ESP/Dcm_..._ESP.arxml` covered both. Field operators flagged
two pain points:

1. The combined ARXML didn't match Bosch's diagnostics-tooling
   convention: every PT slot in `cfg/<PT>/` is supposed to be a
   *single-product* configuration, even when two PTs share a
   directory.
2. The fold-in moved ESPCL DIDs into ESP's iteration but never
   produced an `_ESPCL.arxml` artefact, making "what does the
   diagnostic stack actually look like for ESPCL?" impossible to
   answer from the generated outputs alone.

v1.24.0 keeps the per-PT iteration model that the rest of Phase 2 /
Phase 3 already uses, and instead aliases the *paths* — ESPCL
gets its own `Dcm_..._ESPCL.arxml` file, but it lands inside
`cfg/ESP/` next to ESP's own `Dcm_..._ESP.arxml`.

### Concrete output layout

`outputs/arxml/` (and the matching Bosch `cfg/` mirror) for a
work-set carrying both ESP and ESPCL:

```
outputs/arxml/ESP/
├── DID_Config_ESP.arxml         ← ESP iteration, ESP+Common DIDs
├── DID_Config_ESPCL.arxml       ← ESPCL iteration, ESPCL+Common DIDs
├── validation_report_ESP.txt
├── validation_report_ESPCL.txt
├── arxml_review_report_ESP.txt
└── arxml_review_report_ESPCL.txt
```

Bosch mirror under `Fe_Super/rb/as/<customer>/core/app/dcom/RBAPLCust/cfg/`:

```
cfg/ESP/
├── Dcm_CusDiag_Services_EcucValues_ESP.arxml
└── Dcm_CusDiag_Services_EcucValues_ESPCL.arxml
```

Every ARXML / report filename now carries a `_<suffix>` tag
(`_DPB`, `_ESP`, `_ESPCL`, `_IPB`, `_RBU`, or `_SingleCANID` for
Common) so two PTs sharing a folder don't overwrite each other.

### Mechanism

* **New `{product_type_arxml_folder}` placeholder** in
  `paths.arxml_file`. Behaves like `{product_type_upper}` for
  every PT *except* alias source PTs (currently `ESPCL`), which
  collapse to the alias target's folder name (`ESP`). Phase 3
  templates (`paths.c_output_subdir` / `paths.config_settings_h`)
  intentionally keep `{product_type_upper}` / `{product_type_lower}`
  — Phase 3 ignores the alias.
* **Default `paths.arxml_file` template changed** from
  `cfg/{product_type_upper}/Dcm_..._EcucValues_{product_type_suffix}.arxml`
  to
  `cfg/{product_type_arxml_folder}/Dcm_..._EcucValues_{product_type_suffix}.arxml`.
  `--init-project` writes the new template; pre-v1.24.0 hand-edited
  configs that still carry `{product_type_upper}` in the folder
  slot lose the alias and ESPCL writes to `cfg/ESPCL/...` instead.
* **`pipeline.run_phase2`** computes
  `folder = product_type_arxml_folder(product)` and
  `suffix = product_type_suffix(product)` per iteration; output
  paths become `outputs/arxml/<folder>/DID_Config_<suffix>.arxml`,
  with two `..._<suffix>.txt` reports beside it. Both helpers
  live in :mod:`scripts.implementation.paths` (next to their
  sibling `product_type_lower` / `product_type_upper` /
  `product_type_suffix` placeholders).
* **`generate_arxml.generate(validation_report_path=...)`** lets
  the orchestrator pin a per-iteration report path so ESP and
  ESPCL co-tenants in `outputs/arxml/ESP/` don't share
  `validation_report.txt`.
* **Detector emits unconditional alias message.**
  `--init-project`'s detector now logs
  `[INFO] Phase 2 path alias active: ESPCL → ESP` regardless of
  whether `cfg/ESPCL/` happens to exist — the alias is in effect
  on every fully-populated tree as well. Never seeds
  `paths.per_product.ESPCL.arxml_file = null` (would cancel the
  alias).

### Removed

* `phase2_accepted_scopes_for(target)` — the v1.23.0 scope-set
  helper for the DID fold-in.
* `phase2_scheduled_workset(workset)` — partitioned the workset
  into `(scheduled, aliased_away)` for the fold-in.
* `accepted_scopes` parameter on `ARXMLGenerator.generate()` /
  `ARXMLGenerator._document_to_dids()` /
  `ARXMLGenerator.load_dids()` /
  `review_arxml.run_review()` /
  `review_arxml.ARXMLReviewer.load_from_fscs_json()`.
  Single-target `product_type` filtering is back; ESPCL's
  iteration sees ESPCL+Common DIDs only, never ESP's.

### Migration

Pre-v1.24.0 configs that carry `{product_type_upper}` in the
folder slot of `paths.arxml_file` lose the alias. Two ways to
fix:

1. Re-run `python scripts/pipeline.py --init-project` (overwrites
   `paths.arxml_file` with the new template; preserves the rest).
2. Hand-edit `config/project.json::paths.arxml_file` and swap
   `{product_type_upper}` → `{product_type_arxml_folder}` in the
   folder slot (leave the `{product_type_suffix}` filename slot
   alone).

`paths.per_product.ESPCL.arxml_file = null` entries left over
from v1.22.0 / pre-1.23 detector runs continue to work as a SKIP
sentinel (Phase 2 will refuse to produce ESPCL outputs even with
the alias active). Operators who want the alias to take effect
must remove those entries.

No `schema_version` bump (still `2.1`).

### Added

* `product_type_arxml_folder(pt)` in
  `scripts/implementation/paths.py` (lazy-imports
  `phase2_alias_target_for` from `scripts.fscs.product_workset`
  to avoid an import cycle). Single source of truth for both
  the `{product_type_arxml_folder}` placeholder expansion and
  the local `outputs/arxml/<folder>/` layout in
  `pipeline.run_phase2`.
* `{product_type_arxml_folder}` placeholder support in
  `resolve_path`.
* `validation_report_path` parameter on
  `ARXMLGenerator.generate()` and `report_path` parameter on
  `ARXMLGenerator.generate_validation_report()`.
* `TestProductTypeArxmlFolder` (unit) covers the placeholder
  helper end-to-end.

### Changed

* `pipeline.run_phase2` — fan-out output layout now uses
  `outputs/arxml/<folder>/DID_Config_<suffix>.arxml` and
  per-suffix validation / review reports.
* `init_project._build_paths_block` default `arxml_file` template
  swaps `{product_type_upper}` for `{product_type_arxml_folder}`.
* `init_project._detect_per_product_overrides` ESPCL branch:
  emits unconditional `[INFO] Phase 2 path alias active`,
  optional `[FYI] Phase 2 alias target missing` if `cfg/ESP/`
  is also absent. No `per_product.ESPCL.arxml_file = null`
  auto-seed.
* `tests/integration/test_phase_all.py` golden expectations
  renamed to `_SingleCANID` suffix; matching golden files moved
  in `tests/golden/phase_all/arxml/Common/`.
* `tests/integration/test_per_product_skip.py` — Phase-2 SKIP
  assertions updated for the new `outputs/arxml/<folder>/`
  layout (an `ESPCL.arxml_file=null` skip in a workset without
  ESP DIDs now cancels the entire `outputs/arxml/ESP/` directory).

### Removed

* `phase2_accepted_scopes_for` / `phase2_scheduled_workset` from
  `scripts/fscs/product_workset.py` and `fscs/__init__.py`.
* `accepted_scopes` parameter on `ARXMLGenerator` /
  `review_arxml` public surface.
* `Iterable` import from `scripts/pipeline.py` /
  `scripts/review_arxml.py` (no longer needed).

---

## [1.23.0] — 2026-05-14

**Phase-2 product alias mechanism (ESPCL → ESP) + Phase-3 broadcast
clarification.** Two follow-ups to v1.22.0 that change how a
specific class of "product without a dedicated Bosch slot" is
routed:

1. **Phase 2 ESPCL → ESP fold-in.** ESPCL is conceptually a variant
   of ESP, and the Bosch tree has no `cfg/ESPCL/` directory to
   mirror an ESPCL ARXML into. v1.22.0 handled this by auto-nulling
   `paths.per_product.ESPCL.arxml_file`, which suppressed both the
   local `outputs/arxml/ESPCL/` and the Bosch mirror — but it also
   silently dropped every ESPCL-tagged DID (they never made it into
   ESP's ARXML either). v1.23.0 routes ESPCL DIDs into ESP's Phase 2
   iteration: ESPCL-tagged DIDs land in ESP's `DID_Config.arxml`
   (and its Bosch `cfg/ESP/Dcm_..._ESP.arxml` mirror) alongside
   ESP-tagged DIDs. The alias is **Phase-2-only**; Phase 3 still
   iterates ESPCL as a distinct PT (writing into `src/ESPCL/` and
   the per-PT ConfigSettings as before).

2. **Phase 3 Common-broadcast pinned + documented.** Phase 3's
   `to_did_implementation_infos` does not filter DIDs by
   `product_type`, so every per-PT iteration processes the **same
   complete DID set** — including all `Common`-tagged entries.
   The practical effect is that Common DIDs' ConfigSettings /
   Config / ConfigElements / PDM entries / `.c` stubs already
   appear in every per-PT mirror file (`dpb/dcompr/cfg/RBDCOM_ConfigSettings.h`,
   `esp10/dcompr/cfg/...`, `ipb/dcompr/cfg/...`, etc.). The
   v1.22.0 `paths.per_product.Common.config_settings_h = null`
   detector entry only suppresses Common's *own* iteration
   attempting to write into a non-existent `Common/dcompr/cfg/`;
   it does **not** drop Common's settings — they're broadcast into
   every other PT's mirror. v1.23.0 codifies this in
   `reference/phase-3-implementation.md` and pins it via tests so
   a future "fix" that adds a real per-PT filter to Phase 3 is a
   deliberate code change with the broadcast-restoring exception
   spelled out.

No CLI surface changed; the `paths.per_product` schema is
unchanged from v1.22.0. The detector seed for ESPCL.arxml_file is
the only behavioural change to `--init-project` — operators who
re-run init against a tree without `cfg/ESPCL/` now see an
`[INFO] Phase 2 alias active: ESPCL → ESP` line instead of the
v1.22.0 `[INFO] paths.per_product.ESPCL.arxml_file = null` line,
and no `per_product.ESPCL` entry is written.

### Added

- **`scripts/fscs/product_workset.py::_PHASE2_PRODUCT_ALIASES`**
  — hard-coded `{"ESPCL": "ESP"}` map declaring Phase-2-only
  product aliases. Future variants of this kind would be
  deliberate code changes here (mirroring the
  `_DEFAULT_PRODUCT_TYPE_MAP` / `RECOGNISED_PRODUCTS` convention),
  not config edits.
- **`phase2_alias_target_for(source)`** /
  **`phase2_alias_source_for(target)`** /
  **`phase2_accepted_scopes_for(target)`** /
  **`phase2_scheduled_workset(workset)`** — public helpers in
  `scripts.fscs` exposing the alias table for Phase 2's scheduling
  loop and the per-iteration filter set. Comparisons are
  case-insensitive; returned spellings stay canonical so callers
  can round-trip them through `resolve_path`.
- **`ARXMLGenerator._document_to_dids(..., accepted_scopes=...)`**
  + `load_dids(..., accepted_scopes=...)` + `generate(...,
  accepted_scopes=...)` — optional keyword that REPLACES the
  legacy single-target `product_type` filter with set-membership
  comparison. `"common"` is always added to the set so the
  wildcard semantics survive. `accepted_scopes=None` keeps the
  legacy `{product_type, "common"}` behaviour exactly as before.
- **`review_arxml.run_review(..., accepted_scopes=...)`** + the
  underlying `ARXMLReviewer.load_from_fscs_json` parameter so the
  reviewer's `emitted` set agrees with the alias-merged ARXML on
  disk (e.g. ESP's ARXML legitimately carrying ESPCL DIDs).
- **`tests/unit/test_product_workset.py`** — 14 new tests in
  three classes (`TestPhase2AliasLookups`,
  `TestPhase2AcceptedScopes`, `TestPhase2ScheduledWorkset`)
  pinning the alias helpers' contracts.
- **`tests/unit/test_product_scope.py::TestAcceptedScopesAlias`**
  — 4 new tests pinning the multi-scope filter behaviour
  (alias-source inclusion, Common always in scope, scope-set
  REPLACES single-target, default behaviour preserved when
  `accepted_scopes=None`).

### Changed

- **`scripts/pipeline.py::run_phase2`** now (a) partitions the
  workset via `phase2_scheduled_workset` so alias source PTs
  (`ESPCL`) drop out of iteration when their target (`ESP`) is
  also present, (b) computes per-iteration accepted-scope sets
  via `phase2_accepted_scopes_for`, and (c) forwards both the
  scope set and the alias provenance to `ARXMLGenerator.generate`
  + `_run_arxml_review`. Console output gains an `[ALIAS] ESPCL → ESP`
  line and a `(also accepting alias-source DIDs: ESPCL)` annotation
  on the affected build.
- **`scripts/init_project.py::_detect_per_product_overrides`** no
  longer seeds `paths.per_product.<PT>.arxml_file = null` for PTs
  that are Phase-2 alias sources. Instead it emits an
  `[INFO] Phase 2 alias active: <PT> → <target>` line. Other
  detector branches (Common ConfigSettings auto-null, IPB variant
  CONFIRM, `[FYI]` extras) are unchanged.
- **`tests/unit/test_init_project.py`**:
  `test_detector_skips_espcl_arxml_when_cfg_dir_missing` →
  `test_detector_reports_phase2_alias_when_espcl_cfg_dir_missing`,
  asserting the ALIAS-active `[INFO]` line and the absence of the
  per_product entry. `test_init_project_writes_detected_per_product_to_config`
  updated to expect ESPCL **not** in `per_product` (alias replaces
  the entry).

### Bumped

- `VERSION` and the runtime `--version` banner from `1.22.0` to
  `1.23.0` (additive minor bump — no schema change, no CLI
  break).

---

## [1.22.0] — 2026-05-14

**BREAKING — Per-product Bosch-mirror overrides + skip sentinel
(schema 2.0 → 2.1, no migrator).** Real Bosch trees aren't fully
template-symmetric — `cfg/ESPCL/` is missing on every shipped
tree we've inspected, `Common/dcompr/cfg/` is absent (so
`RBDCOM_ConfigSettings.h` has no Common variant), and `IPB`'s
ConfigSettings header is variant-suffixed
(`RBDCOM_ConfigSettings_IPB.h` / `..._IPB4HAD.h` / `..._RoPPSub.h`)
rather than carrying the canonical name. v1.21.0 papered over
these by silently producing `outputs/{arxml,implementation}/<PT>/`
artefacts that had no Bosch home; v1.22.0 introduces
`paths.per_product` so the operator (or `--init-project`'s new
auto-detect) can pin per-PT overrides and skips precisely.

Pre-release skill, so the schema bump ships **without a migrator**:
the Pydantic `schema_version` validator only accepts the current
string (`"2.1"`). Every prior shape (`"2.0"`, `"1.1"`, `"1.0"`)
hard-fails at load with a `ValidationError` pointing at
`--init-project`. No CLI surface changed from v1.21.0; this is a
config-shape feature rather than a pipeline rework.

### Added

- **`paths.per_product` block (schema 2.1).** Optional dict
  keyed by canonical product short name (`DPB` / `ESP` / `ESPCL`
  / `IPB` / `RBU` / `Common`); inner keys are a subset of the
  six existing mirror-path fields (`pdm_file`, `config_h`,
  `config_elements_h`, `config_settings_h`, `c_output_subdir`,
  `arxml_file`). Inner values are either `null` (skip both
  local artefact and Bosch mirror for that (PT, key)) or a
  non-empty string (literal override path used in place of
  template + placeholder expansion). Outer-key whitelist and
  inner-key whitelist are both validated at load time so typos
  fail loud.
- **`scripts/implementation/paths.py::resolve_mirror_path(...)`**
  + `MirrorResolution` enum (`OVERRIDE` / `TEMPLATE` / `SKIP` /
  `UNSET`). Single source of truth for "where does this (PT, key)
  artefact land?" — Phase 2 and Phase 3 both route through it
  so the per-product semantics are uniform across phases.
- **`scripts/init_project.py::_detect_per_product_overrides(...)`**
  walks the live Bosch tree and synthesises `per_product`:
  - Missing `cfg/<PT>/` → `per_product.<PT>.arxml_file = null`
    + `[INFO]` line (canonical case: `ESPCL`).
  - Missing `<pt_lower>/dcompr/cfg/` → `per_product.<PT>.config_settings_h
    = null` + `[INFO]` line (canonical case: `Common`).
  - Plain `RBDCOM_ConfigSettings.h` absent but variant-suffixed
    files present → defaults to the `_<PT>.h` variant +
    `[CONFIRM]` line listing alternatives so the operator can
    verify or hand-edit.
  - ARXML files in `cfg/<PT>/` not covered by the standard
    template (e.g. `Common/Dcm_..._EcucValues.arxml` no suffix,
    `IPB/...IPB11.arxml`) → `[FYI]` lines with hand-edit
    pointers.
  - `src/` subdirs not in the recognised PT whitelist (e.g.
    `IPB11`, `XPB`) → `[FYI]` line with `c_output_subdir`
    hand-edit pointer.
- **`tests/unit/test_path_resolution.py`** — 12 new tests for
  the override / SKIP / UNSET / TEMPLATE verdicts and PT
  canonicalisation; `tests/unit/test_config_schema.py` — 9 new
  tests for the schema 2.1 whitelist + round-trip; `tests/unit
  /test_init_project.py` — 8 new tests for the detector
  branches; `tests/integration/test_per_product_skip.py` — 8
  new end-to-end tests for the Phase 2 / Phase 3 skip semantics
  (ESPCL.arxml_file and Common.config_settings_h cases).

### Changed

- **`pipeline.py::run_phase2`** pre-filters the work-set against
  `paths.per_product.<PT>.arxml_file == null` so a SKIPped
  product is removed from the build entirely (no
  `outputs/arxml/<PT>/` directory is produced). Logs a `[SKIP]`
  line per skipped product so the silent-degradation surface is
  always observable.
- **`scripts/implementation/orchestrator.py::generate_from_dids`**
  consults `resolve_mirror_path` per (PT, key); a `SKIP` verdict
  drops both the local artefact under `outputs/implementation
  /<PT>/...` and the Bosch mirror, and an `OVERRIDE` verdict
  redirects only the Bosch mirror destination (local outputs
  remain at the conventional path). C-source generation also
  honours `c_output_subdir` SKIP so a fully-disabled product
  produces no `RBAPLCUST_*.c` stubs but still emits per-DID
  briefs (briefs are local-only).
- **`scripts/init_project.py::_build_paths_block`** now writes
  `per_product` into the emitted `paths` block (empty `{}` is
  the no-overrides default; the auto-detect synthesised entries
  flow through here).
- **`scripts/init_project.py::run_init_project`** prints the
  detector's `[INFO]` / `[CONFIRM]` / `[FYI]` lines after the
  `[OK]` block, in that order — actionability ascends from
  "review only" through "MUST verify" to "optional opt-in".
- **`scripts/config/schema.py`** bumped to schema 2.1. Pre-release
  skill — no migration shim: the validator hard-rejects every
  prior `schema_version` (`"2.0"` and earlier).
- **`scripts/config/loader.py`** simplified: no in-memory version
  normalisation. The loader either returns a 2.1 instance or
  raises `ValidationError` with a pointer at `--init-project`.

### Migration

Pre-release skill, no automatic migration. Operators on a v1.19.0
- v1.21.0 (`schema_version: "2.0"`) `project.json` regenerate
from scratch:

```bash
# 1. Note any custom paths.* values you need to preserve
cat config/project.json
# 2. Delete the old file
rm config/project.json
# 3. Re-scaffold (auto-detects Bosch tree + populates per_product)
python scripts/pipeline.py --init-project
# 4. Hand-copy any custom paths.* values across; review the
#    detector's [INFO] / [CONFIRM] / [FYI] lines and adjust
#    paths.per_product as needed.
```

---

## [1.21.0] — 2026-05-14

**BREAKING — Phase 2 / Phase 3 fan-out across the per-DID work-set.**
v1.16.0 had already moved the build-target product from
`config.product_type` onto a per-DID `Product_Type` cell. v1.21.0
finishes the migration: instead of running the pipeline once per
product with `--product-type DPB`, then once with `--product-type ESP`,
etc., the pipeline now scans `outputs/fscs/fscs.json` for every
`Product_Type` value carried by a `used` DID and *fans out* — a
single Phase 2 / Phase 3 invocation generates artefacts for every
product in one shot. Outputs land side-by-side under
`outputs/{arxml,implementation}/<PT>/`, mirror-writes flow through
the existing `output_mode='project'` plumbing, and the `Common`
wildcard slot gets its own canonical path naming
(`Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml`).

### Removed

- **`pipeline.py --product-type / -t` CLI flag.** The five-product
  enum (`DPB|ESP|ESPCL|IPB|RBU`) is gone from argparse. Phase 2 / 3
  no longer take a single build target — the work-set is computed
  per run from `fscs.json` (see Added below). Pre-v1.21 invocations
  fail at argparse with `unrecognized arguments: --product-type`;
  the fix is to drop the flag entirely.
- **`PipelineController.run_phase2(product_type=...)` /
  `run_phase3(product_type=...)` keyword arguments.** Removed in
  lockstep with the CLI flag. Programmatic callers should drop the
  kwarg and let the work-set resolve itself; pass an explicit
  `output_mode=` if needed.

### Added

- **`scripts/fscs/product_workset.py`** — single-source-of-truth
  module that turns an `FSCSDocument` into the run's product
  work-set. Filters DIDs by `used_flag`, canonicalises
  `Product_Type` cells (`dpb` → `DPB`, empty/None → `Common`),
  hard-fails on unrecognised values via `UnknownProductTypeError`,
  and returns a deterministic display order (production products
  alphabetical, `Common` last).
- **`scripts/implementation/paths.py::product_type_suffix(...)`**
  + the matching `{product_type_suffix}` placeholder. The helper
  maps the five real products to their upper-case names (`DPB`,
  `ESP`, …) and the `Common` wildcard to the literal
  `SingleCANID` so the ARXML filename for the cross-product slot
  matches the Bosch-side convention
  (`Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml`) instead of
  the nonsensical `_Common.arxml` that the old
  `{product_type_upper}` substitution produced.
- **`scripts/implementation/paths.py::product_type_upper(...)`**
  helper, lifted out of `resolve_path` so the `Common` ↔ title-
  case quirk lives in exactly one place.
- **Per-product `outputs/` layout.** `outputs/arxml/<PT>/` (with
  `DID_Config.arxml`, `arxml_review_report.txt`,
  `validation_report.txt` per-product) and
  `outputs/implementation/<PT>/` (with `pdms/`, `headers/`,
  `c_code/`, `validation_report.txt`, `impl_review_report.txt`).
  `outputs/fscs/` stays product-agnostic at the root.
- **`tests/unit/test_product_workset.py`** — exhaustive coverage
  for the new module: `used_flag` filtering, `None`/empty/blank
  cells collapsing to `Common`, case-insensitive whitelist matching,
  display-order stability, multi-product worksets, and
  `UnknownProductTypeError` shaping.

### Changed

- **`pipeline.py::run_phase2` and `run_phase3`** rewritten to load
  `fscs.json`, call `compute_workset(document)`, and iterate the
  generator once per product. Each iteration's outputs land in
  `outputs/{arxml,implementation}/<PT>/`. Empty work-set is a
  warn-and-skip (`logger.warning` + `return True`) so downstream
  Phase 4 / DOORS still has a fully-rendered `fscs.json` to
  consume — the empty work-set is a "nothing to build" signal,
  not a hard failure.
- **`pipeline.py::_run_arxml_review`** now accepts an explicit
  `report_path=` parameter so each per-product fan-out iteration
  writes its own review report beside its ARXML
  (`outputs/arxml/<PT>/arxml_review_report.txt`) rather than
  serially overwriting a single shared file.
- **`pipeline.py --list-briefs`** walks every
  `outputs/implementation/<PT>/c_code/_briefs/` subdirectory and
  concatenates the brief enumeration. The relative-path column
  surfaces the product so the agent reader can route fixes
  correctly.
- **`scripts/generate_arxml.py`** backup-root computation walks
  one extra parent (`outputs/arxml/<PT>/DID_Config.arxml.parent
  .parent.parent` → `outputs/`) to keep `outputs/backups/` shared
  across products and across phases.
- **`scripts/implementation/orchestrator.py`** mirror-side backup
  root walks one extra parent for the same reason.
- **`scripts/implementation/paths.py::resolve_path`** now also
  expands the new `{product_type_suffix}` placeholder; existing
  three placeholders unchanged.
- **`scripts/init_project.py`** ARXML template emits
  `cfg/{product_type_upper}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml`,
  which fixes the historical bug where the `Common` slot wrote
  to a non-existent `_Common.arxml` filename. Operators can still
  hand-edit `paths.arxml_file` in `config/project.json` if their
  Bosch tree uses different conventions.
- **`tests/fixtures/tiny_project.json`** ARXML-file template
  switched to the new `{product_type_suffix}` placeholder so the
  integration tests reflect the canonical post-`init-project`
  shape.
- **`tests/golden/phase_all/`** regenerated under the per-product
  layout (`arxml/Common/`, `implementation/Common/`).
- **`tests/integration/test_arxml_project_mirror.py` /
  `test_backup_rolling.py` / `test_output_modes.py` /
  `test_phase_all.py`** updated for the new layout (`Common`
  slot, `SingleCANID` ARXML filename) and for the dropped
  `product_type=` kwarg.
- **`tests/unit/test_pipeline_argparse.py`** seeds a real
  one-DID `fscs.json` so the `run_phase3` work-set picks `DPB`
  and the mocked generator is invoked exactly once.
- **`tests/unit/test_review_arxml.py` /
  `test_review_impl.py`** golden paths point at
  `phase_all/arxml/Common/DID_Config.arxml` and
  `phase_all/implementation/Common/`.

### Migration guide (v1.20 → v1.21)

| Pre-v1.21                                                    | v1.21.0 replacement                                           |
| ------------------------------------------------------------ | ------------------------------------------------------------- |
| `python scripts/pipeline.py -p all -t DPB`                   | `python scripts/pipeline.py -p all` (work-set fans out)        |
| `python scripts/pipeline.py -p arxml -t DPB`                 | `python scripts/pipeline.py -p arxml`                          |
| `controller.run_phase2(product_type="DPB")`                  | `controller.run_phase2()`                                     |
| `controller.run_phase3(product_type="DPB", output_mode=...)` | `controller.run_phase3(output_mode=...)`                      |
| `outputs/arxml/DID_Config.arxml`                             | `outputs/arxml/<PT>/DID_Config.arxml`                         |
| `outputs/implementation/c_code/`                             | `outputs/implementation/<PT>/c_code/`                         |
| `paths.arxml_file: cfg/{product_type_upper}/Dcm_CusDiag_Services_EcucValues_{product_type_upper}.arxml` | `paths.arxml_file: cfg/{product_type_upper}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml` |

If your `outputs/fscs/fscs_edit.csv` has DIDs with empty
`Product_Type` cells, they collapse to the `Common` wildcard slot
on the next `pipeline.py --phase csv-import`. Tag specific products
in the CSV (`Product_Type=DPB`, `Product_Type=ESP`, …) to fan out
across multiple products.

If your `paths.arxml_file` was last regenerated with `init_project`
on v1.20 or earlier and still uses `{product_type_upper}` for the
filename suffix, the `Common` work-set iteration will now write to
`Dcm_CusDiag_Services_EcucValues_Common.arxml` instead of the
canonical `_SingleCANID.arxml`. Update the template (or delete
`config/project.json` and re-run `--init-project`) to pick up the
new placeholder.

---

## [1.20.0] — 2026-05-13

**BREAKING — Entry-point and documentation cull.** Audit on top of
the v1.19.0 schema cull surfaced two more sources of confusion:
duplicate Phase 2/3 CLI surfaces that hadn't been used by the
controller since the phase-7 split, and a `reference/configuration.md`
that still documented the v1.1 schema in full. v1.20.0 finishes the
cleanup.

### Removed

- **`scripts/setup.py` (~16 KB).** Physically deleted. v1.18.0
  merged its responsibilities into `pipeline.py --init-project`
  but kept the file as a "compat entry point"; the audit found
  zero runtime callers (the v1.18.0 `init_project.py` duplicated
  the Bosch-tree detection inline rather than importing it). The
  two unit-test files (`tests/unit/test_setup_py.py`,
  `tests/unit/test_setup_discovery.py`) were deleted in lockstep —
  Bosch-tree discovery is now exercised end-to-end through
  `tests/unit/test_init_project.py`. `--init-project` is the
  sole workspace-init entry point.
- **`scripts/generate_arxml.py::main()` + argparse + standalone
  CLI (~95 LoC).** The Phase 2 entry point is now solely
  `pipeline.py --phase arxml`, which imports `ARXMLGenerator`
  directly. The standalone CLI carried its own argparse (a
  duplicate maintenance surface in lockstep with `pipeline.py`)
  plus a v1.16.0-stale read of `config['project']['product_type']`
  that v1.19.0 schema 2.0 forbids; the file survives as an
  importable module so `from generate_arxml import ARXMLGenerator`
  keeps working unchanged.
- **`scripts/generate_implementation.py::main()` + argparse +
  standalone CLI (~90 LoC).** Same treatment for Phase 3. The
  file is now a pure import shim re-exporting the public surface
  of `scripts/implementation/`.
- **`scripts/run_pipeline.bat`.** A one-liner wrapper that
  hardcoded `--product-type DPB`; useful only on a single
  user's machine.
- **`pytest_out.txt`** (root). Stale 417-test snapshot from
  pre-v1.16.0 that drifted vs the current 800+ suite — clearly
  an accidental commit.
- **`reference/archive/REFACTOR_BRIEF.md` (~60 KB) and the
  `reference/archive/` directory.** Six-part refactoring archive
  from the phase-1 → phase-7 codebase split. Carried zero
  operational value but was still being dispatched-to from
  `SKILL.md` line 204; the link is gone too. Git history retains
  the file for anyone hunting historical context.

### Changed

- **`reference/configuration.md` rewritten end-to-end** for v1.19.0
  schema 2.0. The v1.1 example carrying all 10 culled fields is
  gone; the new file documents the surviving 7 `paths.*` keys + 3
  `options.*` keys, the `{product_type_*}` placeholder substitution
  rules, and an explicit "removed in v1.19.0 (do not re-introduce)"
  table so an operator hitting an `extra_forbidden` validation
  error can identify which legacy field to drop.
- **`reference/workspace-model.md`** — schema example refreshed to
  v1.19.0 shape; the entire "section 5 backward compatibility" and
  "setup.py auto-detect" subsections deleted (the latter pointed at
  a script that no longer exists). New "non-TTY happy path" sub-
  section consolidates the `--name` / `--customer-name` /
  `--project-root` / `--non-interactive` flag reference; the
  v1.18.0 fail-loud (exit 4) behaviour is documented inline.
- **Six other reference files trimmed** for v1.19.0/v1.20.0
  consistency: `architecture.md` (paths.py placeholder list),
  `commands.md` (output-mode help text dropped paths.project_root
  ref), `output-safety.md` (rollback recipe wording),
  `troubleshooting.md` (`product_scope` → `product_type` rename in
  symptom column; DOORS RB_Product fix points at fscs_edit.csv
  instead of removed config knob), `phase-3-implementation.md`
  (brief content list), `implementation-storage-positions.md`
  (HardCode `#define` guard guidance now points operators at
  sibling `.h` files for the `RBFS_ProjectName_*` macro since
  `project.name` is gone).
- **`SKILL.md`** — five v1.16.0 version-string residues fixed
  (Quickstart `--version` echo, Quickstart §2 setup.py call,
  §Version banner ×2, version table headline). Version table
  gained three rows (1.17.x / 1.18.0 / 1.19.0). Quickstart §2
  was rewritten as a single `--init-project` block with a
  reference to the non-TTY contract. Frontmatter description
  tail extended with the v1.20.0 entry-point cull summary.
- **`README.md`** — v1.19.0 long-form section trimmed to a 3-line
  "最近三个 BREAKING" summary (1.18.0 → 1.19.0 → 1.20.0).
- **`pipeline.py`**: `_load_json` `INFO` hint and `--init-project`
  argparse `help` text both updated; the latter explicitly
  documents v1.20.0's "sole entry point" status.
- **`scripts/init_project.py`**: module docstring trimmed (no
  longer references the v1.18.0 setup.py merge); the inline
  Bosch-tree-discovery comment dropped its
  "subsumes scripts/setup.py" pointer.

### Migration

- If a CI script invokes `python scripts/setup.py ...`, replace
  with `python scripts/pipeline.py --init-project --name <NAME>`
  (plus `--customer-name` / `--project-root` when no Bosch tree is
  detected). The `setup.py` CLI flags map 1:1 to `--init-project`
  flags except `--project-name` is now `--name`.
- If a CI script invokes `python scripts/generate_arxml.py ...`
  or `python scripts/generate_implementation.py ...`, switch to
  `python scripts/pipeline.py --phase arxml --product-type <PT>`
  / `--phase implementation --product-type <PT>`. `pipeline.py`
  has been the canonical entry point since v1.0; the standalone
  scripts were never the recommended path.
- `from generate_arxml import ...` / `from generate_implementation
  import ...` continue to work unchanged.

### Stats

- 9 files deleted (~190 KB), 12 files edited.
- ~280 LoC removed from scripts/ (setup.py + two main()s + dead
  code) net of the new SKILL.md / CHANGELOG entries.
- 800+ unit + integration tests still green (-25 setup_*.py tests,
  no replacements needed; init-project coverage already
  comprehensive).

---

## [1.19.0] — 2026-05-13

**BREAKING — `project.json` schema 1.1 → 2.0: aggressive cull.**
Audit found 10 fields with zero runtime consumers; all gone in
one shot. Top-level shrinks to `schema_version` / `paths` /
`options`. Pre-release status — no migration shim, no advisory
warning — older configs hard-fail with a pointer at the cull
list and the `pipeline.py --init-project` regeneration command.

### Removed

- **`project` block (5 fields)**: `name`, `customer_name`,
  `project_root`, `created_date`, `last_modified`. The two
  identity strings (`name` / `customer_name`) were never read by
  any phase; `project_root` duplicated `paths.project_root`;
  the two timestamps were write-only telemetry. `--init-project`
  / `setup.py` still accept `--name` / `--customer-name` /
  `--project-root` (used at build time to materialise `paths.*`
  literal segments and to gate the non-TTY fail-loud check) but
  do NOT echo them back into the config.
- **`product_type_mapping` block.** The five-product mapping
  (`ESP→esp10`, `DPB→dpb`, `ESPCL→esp10cl`, `IPB→ipb`,
  `RBU→rbu`) lives in `implementation/paths.py::_DEFAULT_PRODUCT_TYPE_MAP`
  and has been stable for the lifetime of the toolkit. A sixth
  product is now a deliberate code edit — config-level overrides
  were a footgun for "ESP→esp11" typos that silently misrouted
  every Phase 3 write. The runtime fallback in
  `paths.product_type_lower(config, ...)` no longer reads
  `config['product_type_mapping']`; the `config` parameter is
  kept in the signature for call-site compatibility.
- **`paths.project_root`**. Duplicated `project.project_root`,
  both unread. The literal segment still survives baked into
  `paths.{pdm_file, config_h, config_elements_h, config_settings_h,
  c_output_subdir, arxml_file}`, which is the only place
  Phase 2 / Phase 3 ever looked for it.
- **`options.{overwrite_existing, generate_comments,
  validate_before_generate}`**. v1.12.x compat flags inherited from
  the original v1.0 `setup.py`; never wired to any actual code
  path. `output_mode` / `backup_before_write` / `backup_keep`
  remain.
- **`{customer_name}` placeholder support in
  `implementation.paths::resolve_path`.** Customer is baked
  literally into `paths.*` strings by `init_project` / `setup`;
  no template ever referenced the placeholder. A stale template
  carrying `{customer_name}` now survives verbatim into the
  resolved path so the breakage is visible instead of silently
  resolving to `""`.

### Changed

- **`scripts/config/schema.py`**: `SCHEMA_VERSION = "2.0"`.
  `ProjectIdentity` class deleted entirely. `ProjectPaths` /
  `ProjectOptions` shrunk to the surviving 7 / 3 fields.
  `ProjectConfig` reduced to three top-level fields. The
  `_migrate_legacy` model validator was removed (no migration);
  `_validate_schema_version` rejects any value other than
  `"2.0"` with a message pointing at the module docstring's full
  removal list and the `--init-project` regeneration command.
  The five-field `DEFAULT_PRODUCT_TYPE_MAPPING` constant
  alias is gone from the public `config` package.
- **`scripts/init_project.py`**: `_build_starter_config` now
  emits the schema-2.0 dict (no `project` block, no
  `product_type_mapping`, no dead options); `name` is accepted
  for caller compatibility but silently dropped. `_build_paths_block`
  no longer carries `project_root` in its return dict (it's still
  consumed as a build-time input to materialise the literal path
  segments). The post-init log line that printed the captured
  customer / project-root pair was rewritten to print
  `pdm_file` instead.
- **`scripts/setup.py`**: same cull — `create_project_config`
  emits schema 2.0; `name` and `product_type` parameters survive
  for back-compat but the values disappear at build time. The
  output summary surfaces `(NOT persisted; v1.19.0 cull)` next
  to the captured project name as a one-shot operator hint.
- **`scripts/review_arxml.py::_audit_other_product_arxmls`**:
  the cross-product ARXML scan no longer reads
  `config.product_type_mapping`; it imports
  `implementation/paths.py::_DEFAULT_PRODUCT_TYPE_MAP` directly.

### Tests

- Rewrote `tests/unit/test_config_schema.py`: removed the
  v1.12.x compat fixture / migration-stderr assertions; added
  per-removed-field "must hard-fail" assertions and a
  schema-2.0 round-trip fixture.
- Rewrote `tests/unit/test_init_project.py`: dropped all
  assertions on `cfg.project.*` and `cfg.product_type_mapping`;
  added v1.19.0 cull pins (top-level keys are exactly three,
  `options` carries exactly three fields, removed legacy fields
  do NOT reappear in the freshly-emitted JSON).
- Rewrote `tests/unit/test_setup_py.py`: same cull pins;
  added `test_name_arg_is_accepted_but_not_persisted` so a
  future "let's resurrect project.name for user-friendly
  bookkeeping" PR fails this test before it merges.
- Updated `tests/unit/test_setup_discovery.py` and
  `tests/unit/test_product_scope.py` for the schema 2.0 shape
  (no `project` block, no `paths.project_root`).
- Rewrote `tests/unit/test_path_resolution.py`: removed the
  `{customer_name}` substitution test; added a
  `test_customer_name_placeholder_no_longer_substituted` pin so
  re-introducing the placeholder is visible. Added a
  `test_config_supplied_mapping_no_longer_overrides` pin for
  the runtime-mapping cull.
- Replaced `tests/fixtures/tiny_project.json` with the
  schema-2.0 shape so any test that loads it via
  `load_project_config` continues to pass cleanly.

### Migration

There is no migration. Pre-release status — regenerate
`config/project.json` via `python scripts/pipeline.py
--init-project` and copy any custom values from the surviving 7
`paths.*` keys + 3 `options.*` keys across by hand. Anything
under `project` / `product_type_mapping` / `paths.project_root` /
the three dead options didn't matter even before this release.

### Stats

- 13 files touched (3 scripts + 1 schema + 5 unit tests + 1
  fixture + 3 docs).
- ~150 LoC removed net (schema cull + dead options outweighs
  the larger `_validate_schema_version` error message).
- 827 / 827 unit + integration tests green; smoke
  `init-project` three scenarios pending (next).

---

## [1.18.0] — 2026-05-13

**One-shot workspace init: `pipeline.py --init-project` now subsumes
`scripts/setup.py`, dropping the ambiguous "do I run init or setup?
both? in what order?" question that operators kept asking.** A single
invocation creates the workspace, structurally detects an adjacent
Bosch BSW tree, and pre-populates `paths.*` with product-type-templated
values. Non-TTY mode is fail-loud (exit 4) instead of silently shipping
`Fe_Super` / `rbcn` placeholder configs into CI pipelines.

### Changed

- **`scripts/init_project.py` is now the single workspace-init
  entry point.** It absorbs the v1.13.x structural Bosch-tree
  discovery from `setup.py::find_project_root_and_customer` (kept
  inline as `_detect_bosch_tree` so init is self-contained), and
  when discovery succeeds it pre-populates the six mirror paths
  (`pdm_file` / `config_h` / `config_elements_h` /
  `config_settings_h` / `c_output_subdir` / `arxml_file`) the same
  way `setup.py::create_project_config` used to. When no tree is
  reachable, `paths.*` stays empty and the workspace runs in the
  safe outputs-only posture.
- **Interactive prompt count: 4 → 3.** The
  `paths.base_dir` prompt is gone — it's always set to the resolved
  target directory automatically. The remaining three (`name` /
  `customer_name` / `project_root`) get their defaults from the
  Bosch-tree scan when a tree was detected, so the happy path is
  "press Enter three times".
- **`paths.{c_output_subdir, config_settings_h, arxml_file}` carry
  `{product_type_upper}` / `{product_type_lower}` placeholders
  instead of baking a specific product into the file at setup
  time.** Phase 2 (`generate_arxml.py`) and Phase 3
  (`implementation/orchestrator.py`) already feed every path
  through `scripts.implementation.paths.resolve_path` with the
  per-run `--product-type`, so a single `project.json` works for
  every product the workspace targets. Operators no longer need to
  re-run setup when switching `--product-type` for Phase 2/3
  mirroring. The downstream resolver and `ProjectConfig` schema
  already supported these placeholders since v1.13.0; v1.18.0
  finally puts the producer in line with the consumer.
- **`scripts/setup.py::create_project_config` matches the same
  placeholder shape** (instead of baking products) and accepts
  `product_type=` for backward-compat with a stderr WARNING that
  the value is ignored. The `--product-type` CLI argument on
  `setup.py` is now optional (no longer `required=True`); passing
  it just emits the deprecation WARN.

### Added

- **CLI flags `--name` / `--customer-name` / `--init-project-root`
  / `--base-dir` on `pipeline.py --init-project`** so an agent (or
  any non-TTY caller) can fully specify identity fields without
  ever entering the prompt loop. `--init-project-root` is named
  distinctly from the existing `--project-root` (which selects the
  workspace for any other phase) to avoid CLI-flag shadowing.
- **Bosch-tree auto-detection at init time.** The new
  `_detect_bosch_tree` walks the workspace and returns
  `(project_root, customer)` when the structural match is unique;
  when ambiguous (multiple roots or multiple customers under one
  root), returns `None` and the operator must disambiguate via the
  CLI flags above. Hidden directories (`.agents`, `.git`,
  `.jazz5`, etc.) are skipped during the scan.
- **Bosch-tree validation against operator hints** before mirror
  pre-population. If `--project-root Fe_Typo` doesn't structurally
  validate, `paths.*` stays empty (safe posture) instead of
  shipping a config that points at a non-existent tree.

### Removed

- **Non-TTY silent-default placeholder behaviour** (`init-project`
  used to write `customer_name=rbcn` / `project_root=Fe_Super`
  with a stderr WARN when neither flag was supplied and stdin
  wasn't a TTY). Too many CI pipelines were quietly shipping
  these placeholders into real workspaces. Replacement: exit code
  4 with a stderr explanation listing exactly which CLI flags are
  needed for the current environment.
- **`paths.base_dir` interactive prompt** (was confusing operators
  who didn't know what `base_dir` meant). It's set to the resolved
  target directory automatically.

### Tests

- **9 new tests in `tests/unit/test_init_project.py`** covering
  Bosch-tree detection (5 cases: no-tree / unique-tree / multiple
  roots / multiple customers / hidden-dirs-skipped), mirror-enabled
  vs disabled paths block (`{product_type_*}` placeholders present
  / absent), and end-to-end pin that `--init-project` on a
  Bosch-tree workspace writes placeholders rather than baked
  products.
- **8 existing tests in `tests/unit/test_init_project.py` updated**
  for the new fail-loud non-TTY behaviour, the dropped `base_dir`
  prompt, and the three-question interactive flow.
- **3 tests in `tests/unit/test_setup_py.py` updated and 1 added**
  to assert `paths.{c_output_subdir, arxml_file, config_settings_h}`
  now carry `{product_type_upper}` / `{product_type_lower}`
  placeholders, plus a back-compat pin that passing
  `product_type=` produces a config identical to the no-arg call
  (just with a stderr WARN we don't pin verbatim).
- **2 tests in `tests/unit/test_setup_discovery.py`** dropped the
  `product_type=` parameter from `create_project_config` calls
  (no longer required since v1.18.0).
- Full pytest sweep: 811 → 822 passing (11 new, no regressions
  from the refactor). One Windows-specific `os.replace`
  `PermissionError` in `test_fscs_dual_write.py` is environmental
  flake unrelated to this change (passes on retry).

### Migration

**Operators upgrading from v1.17.x:**

- Existing `config/project.json` files keep working unchanged.
  Schema is still 1.1; the `paths.*` field shapes the operator
  hand-edited (or `setup.py` produced) load cleanly.
- To benefit from cross-product mirror without re-setup, operators
  can swap baked products in their existing
  `paths.{c_output_subdir, config_settings_h, arxml_file}` for
  `{product_type_upper}` / `{product_type_lower}` placeholders.
  No automated migration tool — the swap is mechanical and
  one-time.
- New workspaces created via v1.18.0 `--init-project` always carry
  the placeholder form.

**Operators still calling `scripts/setup.py` directly:**

- The script still works. `--product-type` is no longer required
  (passing it emits a stderr WARN that the value is ignored).
- The recommended path is `pipeline.py --init-project`, which now
  does both jobs in one command.

---

## [1.17.2] — 2026-05-13

**Rename internal `AnchorMatch.absolute_number` → `anchor_address`
to stop confusing it with the workbook's `Absolute Number` column.**
Operators kept asking "wait, which `AbsoluteNumber` is this?" when
reading state-machine reports, doors logs, or `doors_sync` source
— because the same DOORS-side number appears in three roles
(anchor row id, INSERT `Destination Object` payload, UPDATE
`Absolute Number` payload) and using the same name everywhere
made the role invisible at read time.

### Changed

- **`AnchorMatch.absolute_number` → `AnchorMatch.anchor_address`**
  (`scripts/fscs/doors/anchor.py`). Docstring rewritten to spell
  out the role and the v1.17.2 rename rationale. Same dataclass
  shape (positional slot unchanged), so the in-file `AnchorMatch(
  service, str(...), "by_text", row)` constructions in `anchor.py`
  itself didn't move.
- **All call sites updated**:
  - `scripts/fscs/doors/build_doors_payload.py` — 6 reads
    (`RowCtx.destination` for FS / CS contexts, INSERT-mode
    `Destination Object` write, dry-run anchor placeholder, report
    line, JSON summary key `anchor_abs` → `anchor_address`).
  - `scripts/fscs/doors/doors_sync.py` — 2 reads (CLI summary
    print, `abs_to_idx` lookup for `service_ranges` carving).
- **Doc references updated**:
  - `reference/phase-4-doors.md` — §1 column table now reads
    "anchor address (INSERT only)" / "recorded `fs_abs` (UPDATE
    only)" instead of conflating both into "anchor `AbsoluteNumber`",
    and a new §3.5 lead-in subsection **"Anchor address vs
    `Absolute Number` — read this once"** lays out the
    code-field-vs-workbook-column-vs-DOORS-API-name distinction
    in one table.
  - `scripts/fscs/doors/diff.py` and `doors_state.py` module
    docstrings refer to `anchor.anchor_address` in the INSERT
    bucket description.

### Not changed (intentionally)

- **DOORS-side field name stays `AbsoluteNumber`.** Every
  `row.get("AbsoluteNumber")` in `anchor.py` / `doors_links.py` is
  reading the DOORS export schema — that's a DOORS API contract,
  not ours.
- **Upload xlsx column header stays `Absolute Number`.** Operator
  template constraint (`assets/doors_template.xlsx`).
- **`ServiceLanding.fs_abs` / `cs_abs` stay.** Those are the
  recorded landings, not the anchor; the rename was scoped to the
  anchor concept only (per operator decision in the rename
  question).
- **YAML config key stays `by_absolute_number`.** Operator-facing
  config — renaming would silently break every existing
  `inputs/doors_mapping.yaml` in the wild.

### Tests

- 6 attribute-access updates in `tests/unit/test_doors_payload.py`
  (4 anchor-resolution assertions + 2 `BuildResult.services[s].
  anchor.<attr>` reads). YAML config keys (`by_absolute_number`)
  and the test name `test_anchor_by_absolute_number_overrides_text_lookup`
  intentionally untouched — those are config, not code.
- Full pytest sweep: 811 → 811 passing, no behaviour delta (pure
  rename + docstring + report-line cosmetic fix).

### Migration

Zero operator action required. State files (`state/doors_upload_
state.json`) keep the same shape (`fs_abs` / `cs_abs` were never
called `absolute_number` in the schema). YAML config keeps the
same shape. Only in-process code reading `AnchorMatch` needs the
new attribute name — and there are no public consumers outside
`scripts/fscs/doors/`.

---

## [1.17.1] — 2026-05-13

**Fix: a DID present in BOTH `service_22` and `service_2e`
recorded only one landing for two services.** The 22 and 2E
anchors live in different parts of the DOORS module, so the
same DID lands at TWO physically distinct row pairs (different
`(fs_abs, cs_abs)` per service). v1.17.0's
`_writeback_state_post_upload` keyed its lookup on `did_hex`
alone, so the second `LinkEntry` overwrote the first in the
landings dict and both `service_22` / `service_2e` slots ended
up pointing at the same physical row. The next UPDATE under one
service would clobber the wrong row in DOORS.

### Fixed

- **`reconcile_did_rows` is now per-service-aware.** A new
  optional `service_ranges` parameter
  (`{"22": (start, end), "2E": (start, end)}`) carves the row
  list into per-anchor slices; every matched DID×service emits
  its OWN `LinkEntry` with the correct service tag and the
  per-anchor `(fs_abs, cs_abs)`. Without `service_ranges` the
  function preserves v1.16.0 behaviour (one entry per match,
  `service=""`) so legacy callers keep working.
- **`doors_sync.py` re-resolves anchors against the fresh
  post-upload export** to build `service_ranges` from the
  resolved anchor row indices, then threads it into
  `reconcile_did_rows`. Falls back gracefully to the v1.16.0
  hex-only path with a stderr WARN if anchor resolution fails
  on the fresh export.
- **`_writeback_state_post_upload` keys its landings lookup by
  `(service, did_hex)`** instead of `did_hex` alone. Each
  service slot in the per-DID state record now gets the correct
  per-anchor `(fs_abs, cs_abs)` independently. The hex-only
  fallback survives for legacy entry sources but emits a WARN
  pointing operators at the v1.17.1 orchestrator.
- **`_annotate_service` no longer overwrites authoritative
  service tags.** When `reconcile_did_rows` already stamped
  `"22"` / `"2E"` from `service_ranges`, the annotator passes
  the entry through unchanged; only entries with empty
  `service` get the v1.16.0 union-tagging fallback.

### Tests

- 3 new tests pin the fix:
  - `test_reconcile_with_service_ranges_tags_each_match_per_service`
    (unit) — fixture has 0x0101 in both services with disjoint
    AbsoluteNumber blocks (200s vs 400s); asserts two separate
    `LinkEntry` instances with correct `service` tags.
  - `test_reconcile_without_service_ranges_keeps_v1_16_unannotated_form`
    (unit) — back-compat pin.
  - `test_did_in_both_services_records_distinct_landings_per_service`
    (integration) — round-trip on disk: writeback → save_state
    → load_state → assert `0x0101.service_22.fs_abs.startswith("22-")`
    and `0x0101.service_2e.fs_abs.startswith("2E-")`; subsequent
    UPDATE in BOTH services pins that the workbook addresses
    the service-correct landings.
- Full pytest sweep: 808 → 811 passing (3 new, no regressions).

### Migration

Operators upgrading from v1.17.0 don't need to do anything
manually: the next successful `--phase doors` run automatically
re-records the per-service landings into the typed state file.
DIDs that were previously mis-recorded in v1.17.0 will UPDATE
once at the wrong row and then converge to the correct landings;
in practice we recommend a one-shot
`--phase doors --force-reinsert` after the upgrade to skip the
intermediate UPDATE-at-wrong-row step entirely.

---

## [1.17.0] — 2026-05-13

**DOORS Phase 4 becomes stateful: per-DID INSERT / UPDATE / NOOP /
STALE state machine.** v1.16.0 made every `--phase doors` run a
full re-INSERT of every effective DID. That worked for the first
push but burned MCP bandwidth and clobbered DOORS-side
AbsoluteNumbers on every subsequent run. v1.17.0 keeps a typed,
per-DID×service ledger of what landed where with what content
hash, then lets the diff engine decide on each run whether to
INSERT (new), UPDATE (drifted), NOOP (unchanged, skip the row
entirely), or warn STALE (recorded but no longer in FSCS).

The state file (`<workspace>/state/doors_upload_state.json`,
schema 3.0) is per-workspace AND per-DOORS-module: an operator
can target two modules from the same workspace without their
state cross-contaminating. Module-UUID drift (e.g. operator
re-pointed `inputs/doors_mapping.yaml::doors.document_uuid`)
self-resolves: the new module starts with no recorded landings,
so every DID classifies as INSERT — which is the correct semantic.
A new `--force-reinsert` CLI explicitly wipes the per-module
substate when the operator did teardown DOORS-side and wants a
clean slate; `--plan-only` prints the plan without touching disk
or DOORS for cheap "what would change?" inspection.

### Added

- **`scripts/fscs/doors/doors_state.py`** — typed schema 3.0 state
  module: `State` / `ModuleState` / `DIDState` / `ServiceLanding`
  dataclasses with atomic `save_state` / `load_state` round-trip
  semantics (write-tmp-then-rename) and silent migration from
  v1.10.x schema 2 (records the migration on stderr; treats
  the file as empty so the next run rebuilds the per-DID memory
  on its first successful upload).
- **`scripts/fscs/doors/content_hash.py`** — deterministic SHA-256
  fingerprint of the 15 DOORS cells that actually carry content
  (excludes `Destination Object` and `Absolute Number`, which
  the state machine itself controls). The hash is what the diff
  engine compares against the recorded landing's `content_hash`
  to decide UPDATE vs NOOP. Insensitive to dict-key order and
  trailing whitespace; sensitive to leading whitespace and any
  unicode rewrite.
- **`scripts/fscs/doors/diff.py`** — pure `compute_action_plan`
  function. Takes a typed `State` plus the freshly computed
  per-DID×service hashes and returns an `ActionPlan` with one
  `DIDAction(action ∈ {INSERT, UPDATE, NOOP, STALE})` per pair.
  Workbook layout follows the FSCS-file iteration order;
  `format_plan_table` re-imposes a bucketed view for human
  reports. Per-module isolation is automatic — the engine only
  consults `state.modules[module_uuid]`, so different modules
  never share landings.
- **Two new orchestrator CLI flags** on `scripts/pipeline.py`
  and `scripts/fscs/doors/doors_sync.py`:
  - `--plan-only` → load state, build hashes, compute plan,
    print `format_plan_table`, exit 0. No xlsx hits disk; no
    fetch / upload / link operations attempted. Implies
    `--no-fetch --no-upload --no-links --no-anchor`.
  - `--force-reinsert` → wipe the per-module substate
    (`reset_module(state, module_uuid)`), persist the wipe
    immediately, then run the build with everything classifying
    as INSERT. Recovery posture for a DOORS-side teardown.
- **Post-upload reconcile** in `doors_sync.py`. After a successful
  upload + link reconciliation, the helper
  `_writeback_state_post_upload` folds the freshly-fetched FS/CS
  AbsoluteNumbers (from `reconcile_did_rows`) back into the typed
  state for INSERTs, refreshes the recorded `content_hash` +
  timestamp for UPDATEs, leaves NOOPs untouched, and warns on
  STALE (delete deferred to v1.18.x `--prune-stale`).

### Changed

- **`build_doors_payload.py::build_payload` is now two-pass.**
  Pass 1 always computes the per-DID×service `content_hash` so
  the diff engine has accurate inputs; Pass 2 walks the action
  plan and writes ONLY INSERT and UPDATE rows. NOOPs are skipped
  from the workbook entirely — that's the cheapest possible MCP
  call. Empty workbooks (every DID NOOP) are still written to
  disk so the orchestrator's path-reporting and filesystem
  invariants stay intact.
- **`RowCtx.mode`** field added (`"insert"` / `"update"`).
  Operator-facing yaml mappings can now read `row.mode` if they
  want to render mode-conditional cell content; the shipped
  yaml ignores it, but the field is documented in
  `reference/phase-4-doors.md §3.5`.
- **`BuildResult`** now carries `action_plan: ActionPlan` and
  `did_pair_hashes: Dict[(service, did_hex), str]` so the
  orchestrator can do post-upload reconcile + state writeback
  without re-rendering anything.
- **`scripts/fscs/doors/doors_sync.py`** swapped its legacy
  aggregate state writeback (`fscs_sha256` + counts) for the
  per-DID writeback through the new state machine. The old
  state file (`schema_version: 2`) is read once, logged as
  superseded, and rewritten as schema 3.0 on the next
  successful upload.

### Compatibility

- **Existing v1.16.0 workspaces upgrade silently.** The first
  `--phase doors` run after the upgrade reads the legacy schema 2
  state file, logs the migration on stderr, and treats every
  effective DID as INSERT (correct semantic — no per-DID memory
  yet). After the upload succeeds the state file is rewritten
  in schema 3.0 with the freshly-recorded landings.
- **`build_payload` keeps the v1.16.0 calling convention.** When
  `state` and `module_uuid` are not passed (the unit-test
  fixtures, the build-only smoke), every effective DID classifies
  as INSERT exactly as before — no test regressions.
- `BuildResult.services` is empty under `--plan-only`; the
  orchestrator detects this and skips its "built ${service}"
  prints. Other consumers reading `result.services` should
  branch on `args.plan_only` if they care.

### Tests

- 89 DOORS-related unit tests (`test_doors_payload.py`,
  `test_doors_state.py`, `test_doors_content_hash.py`,
  `test_doors_diff.py`) cover state round-trip, content hash
  determinism / sensitivity, four-bucket diff classification
  with per-module isolation, and the four workbook scenarios
  (pure INSERT, pure UPDATE, mixed, all-NOOP empty workbook).
- `tests/integration/test_doors_state_machine_rounds.py` exercises
  the full INSERT → NOOP → UPDATE round-trip on disk through
  `save_state` / `load_state` plus `_writeback_state_post_upload`,
  with synthetic `LinkEntry` instances simulating DOORS reconcile.
- Full pytest sweep: 808 → 808 passing (1 new integration
  test net-new, no regressions).

---

## [1.16.0] — 2026-05-13

**DOORS export realigned to the operator-supplied template, and
`product_type` becomes a per-DID field.** v1.13.0 introduced
`product_scope` as a per-DID tag for the Phase 2 cross-product
filter and v1.13.x added a parallel `project.product_type` config
knob for the build target. The two overlapped: there was no good
reason to keep both. v1.16.0 collapses them.

The DOORS export side was also overdue for a refresh: the v1.15.x
14-column workbook didn't line up with the operator-supplied
`assets/doors_template.xlsx`. The CS row's `Object Text` was
truncated, `RB_Realizing_SWitem` carried full paths, `RB_Product`
was empty, and three template columns were missing entirely.
v1.16.0 fixes all of that in one pass.

### Breaking

- **FSCS schema 1.4 → 1.5.** Per-DID `product_scope` is renamed to
  `product_type`. The FSCS document's `project.product_type`
  field is removed; the build-target product is now supplied per
  call via the `--product-type` CLI flag. **Legacy v1.4 documents
  upgrade silently** — the schema-bump migrator renames the
  per-DID key and strips the project-level key with a one-line
  stderr advisory the first time it sees one.
- **Project-config schema 1.0 → 1.1.** `config/project.json`
  drops `project.product_type`. Existing v1.0 configs migrate
  silently with a stderr advisory; the operator should run
  `--init-project` or hand-edit to remove the legacy key.
- **`scripts/pipeline.py --phase arxml` and `--phase implementation`
  now require `--product-type`.** The previous fall-back to
  `project.product_type` is gone — Phase 2/3 abort with a
  diagnostic if the flag is missing rather than risking a silent
  miscompile against the wrong product flavour.
- **DOORS workbook layout went 14 → 17 columns** in the order
  pinned by `assets/doors_template.xlsx` (added `Number`,
  `RB_Referenced_Testcase`, `RB_TestEnvironment`; reordered the
  rest to match the template). Existing operator overrides in
  `inputs/doors_mapping.yaml::columns` need to be re-aligned
  one-time; the shipped YAML is already correct.

### Added

- **Per-DID `product_type` is the single source of truth** for
  both the Phase 2 build-target filter (`OUT_OF_SCOPE` rows in
  the validation report) and the Phase 4 DOORS `RB_Product` cell
  (one row pair per DID). A new `Product_Type` column ships in
  `outputs/fscs/fscs_edit.csv` so operators can edit the value
  per DID in Excel/WPS without touching JSON.
- **`--product-type` flag on Phase 1.** Single-product workflows
  pass it once on the command line and every freshly-built DID
  whose source record carries no per-DID value gets auto-stamped
  with the active flag. Operator-tagged values (including the
  `Common` wildcard) are never overwritten.
- **`role_values` block in `inputs/doors_mapping.yaml`.**
  Declarative overrides for the FS-row vs CS-row content
  divergence (`RB_Referenced_Testcase` / `RB_TestEnvironment`
  shipped values match `assets/doors_template.xlsx` defaults of
  `SwT` / `Labcar/HIL` and `CT` / `SIL Simulation`).
- **Per-role realizing basenames.** `realizing_paths.fs_template`
  / `cs_template` replaces the v1.15.x `templates: [...]` list.
  The DOORS row gets the `.arxml` basename on the FS row and the
  `.c` basename on the CS row, matching the
  `assets/doors_template.xlsx` layout. Path-shaped templates are
  silently reduced to their basename so legacy mappings keep
  working.

### Changed

- **`Object Text` carries the full Behavior section** verbatim,
  multi-line preserved. (The previous build already passed
  `DIDBlock.body` through, but it was never explicitly tested;
  v1.16.0 adds a regression pin so a future renderer change can't
  silently truncate the operator's diag spec.)
- **`build_doors_payload.py`** rewritten end-to-end for the
  17-column layout. Reads per-DID `product_type` from
  `outputs/fscs/fscs.json`. The `RowCtx` dataclass gained
  `referenced_testcase`, `test_environment`, and per-row
  `realizing` fields.
- **`scripts/init_project.py`** dropped the product-type prompt
  (interactive mode now asks four questions instead of five) and
  no longer writes `project.product_type` into the starter
  config. The five-product `product_type_mapping` seed survives.
- **`scripts/setup.py`** still consumes `--product-type` to derive
  product-flavoured paths but no longer echoes the value into
  `project.product_type`.
- **`apply_product_scope_defaults`** is renamed to
  `apply_product_type_defaults` (with the legacy alias kept
  exported for v1.15.x callers). The signature now takes
  `default_product_type=` explicitly instead of reading from
  `document.project`.

### Fixed (latent v1.14.0 regression surfaced by smoke testing)

- **`scripts/pipeline.py --phase doors` now writes to the active
  workspace.** Previously it shelled out to
  `scripts/fscs/doors/doors_sync.py` with skill-root defaults for
  every path (`--mapping`, `--out-dir`, `--report`, etc.), so
  any operator running the DOORS phase from a v1.14.0
  multi-project workspace would read `inputs/doors_mapping.yaml`
  out of the **skill folder** and write
  `outputs/doors/doors_upload_*.xlsx` back into the **skill
  folder** as well, never touching the workspace's own tree.
  v1.16.0 threads `self.base_dir` (workspace) into all nine
  workspace-rooted CLI flags. The bug is older than v1.16.0 but
  was masked because most operators ran the toolkit from the
  skill root before v1.14.0; the new per-DID `product_type`
  source (`fscs.json`) makes it impossible to ignore because the
  RB_Product cell would otherwise come out empty in every
  workspace except the skill itself.
- **`scripts/fscs/doors/doors_sync.py`** gained `--txt-22`,
  `--txt-2e`, and `--fscs-json` CLI flags (skill-root defaults
  preserved for standalone runs from the skill folder).
  `pipeline.py` uses them to redirect the read side of the
  pipeline at the workspace's `outputs/fscs/` tree.

### Migration tips

- **Operator with an existing `outputs/fscs/fscs.json`:** the file
  loads cleanly on first read; `Phase 1 --phase fscs` will
  rewrite it in schema 1.5 shape. No manual edits needed.
- **Operator with an existing `config/project.json` carrying
  `project.product_type`:** the loader strips the key with a
  stderr warning. To silence the warning, either run
  `--init-project --force` (rewrites the file in schema 1.1
  shape) or hand-delete the line.
- **Operator with hand-rolled `--phase arxml` invocations:** add
  `--product-type DPB` (or whichever target). The skill no longer
  fills it in for you.
- **Operator with custom `inputs/doors_mapping.yaml`:** open
  `assets/doors_template.xlsx` and align the `columns:` block
  cell-for-cell. The shipped YAML is the canonical example.

---

## [1.15.0] — 2026-05-13

**Phase 3 closes the non-NVM gap.** Up through v1.14.x, only
EEPROM (NVM-backed) DIDs got a fully-generated read/write body —
ROM/Flash (HardCode) and RAM (internal-interface) DIDs left
empty `TODO` stubs the operator had to fill from scratch with no
guidance. v1.15.0 keeps the stub-on-non-NVM posture (no
guess-and-pray code generation) but adds the missing scaffolding
so an agent can fill them with high confidence.

### Added

- **`reference/implementation-storage-positions.md`** — the
  agent's playbook for filling non-NVM stubs. Decoded patterns
  for all three storage classes (EEPROM / HardCode / RAM), with
  RAM split into three sub-patterns:
  * **A.** direct internal getter (e.g. `RBEcuSupply_GetEcuSupply_Filtered()`),
  * **B.** `DefineMESGDef`+`RcvMESGDef` for `NMSG_..._ST` struct
    messages (typical ESP/DPB),
  * **C.** `RBMESG_DefineMESGDef`+`RBMESG_RcvMESGDef` for scalar /
    enum signals (typical IPB / RBU).
  Each section cites JAC reference files
  (`RBAPLCUST_RDBI_VersionNumber.c/h`, `RBAPLCUST_RDBI_BLS.c`,
  `RBAPLCUST_RDBI_BatteryVoltage.c`, `RBAPLCUST_RDBI_EPB.c`),
  pre-decoded skeletons, file-placement conventions
  (`Common/` vs `<Product>/`), and FSCS `behavior`-text
  consumption guidance.
- **`scripts/implementation/briefs.py`** — per-DID brief writer.
  Pure functions: `classify_storage(DIDFscsEntry)` returns
  `StorageClassification` (class + RAM sub-pattern guess +
  rationale); `render_brief(...)` builds the Markdown payload;
  `write_briefs_for_document(FSCSDocument, briefs_dir)` loops
  the document and writes briefs for every non-EEPROM DID with
  `service_22.effective == True`. Each brief carries DID
  identity, both services' raw `behavior` text, the storage-
  class verdict, suggested project paths, and a paste-ready
  `#define` skeleton (HardCode) or macro hint (RAM).
- **`pipeline.py --list-briefs`** — agent enumeration entry
  point. Prints `HEX<TAB>STORAGE_CLASS<TAB>RELATIVE-PATH` per
  brief (sorted, exit 0 on empty workspace). Mirrors the
  `--list-inputs` / `--list-configs` contract so an agent driver
  uses identical vocabulary across all three discovery surfaces.
- **`PipelineController` Phase 3 footer** — when at least one
  brief was written, prints
  `[AGENT TODO] N non-EEPROM DID(s) need manual fill-in. Briefs in: <path>`
  so an operator running Phase 3 interactively can't miss the
  follow-up step.

### Changed

- **`scripts/implementation/generators._build_read_func_body`**
  and **`_build_write_func_body`** — non-EEPROM stubs now
  embed a structured `TODO(agent):` block carrying the brief
  filename (`outputs/implementation/c_code/_briefs/<hex>_<svc>.md`)
  and the playbook path (`reference/implementation-storage-positions.md`)
  so the agent has a one-hop link from the C source to the
  generation contract. Function still returns `E_NOT_OK` (no
  fake-success on the bench). EEPROM path is unchanged — zero
  regression for the existing NVM workflow.
- **`ImplementationGenerator.generate(...)`** — after writing
  the C stubs, also calls `write_briefs_for_document` and adds
  `briefs_written` to the returned stats dict. Failures are
  warned-and-continued (briefs are an additive convenience,
  never block the build).
- **`SKILL.md`** — new "Phase 3 — Agent fill-in for non-NVM
  DIDs" section documenting the brief + stub + playbook
  workflow.
- **`README.md`** — new "🟨 Phase 3 — 非 NVM DID 的 agent
  补完" section before the optional DOORS step.

### Tests

- `tests/unit/test_implementation_briefs.py` (31) — storage
  classification (every literal lands in the right class; RAM
  sub-pattern A/B/C heuristic order is deterministic;
  RBMESG-vs-NMSG priority is pinned), brief content (identity
  block, both-services behavior, RW vs read-only section split,
  HardCode `#define` ladder, RAM macro hint, reference-file
  pointers per class), filesystem behaviour
  (`<HEX>_<svc>.md` filename, EEPROM/deselected DIDs skipped,
  sorted output), discovery + `--list-briefs` formatter
  (HEX<TAB>CLASS<TAB>PATH).
- `tests/unit/test_phase3_stub_for_non_nvm.py` (6) — pin EEPROM
  read body still has zero TODO leak; non-EEPROM read/write
  stubs carry `TODO(agent)` + brief filename + playbook path
  + `E_NOT_OK`; RW DIDs use the `_rw.md` brief filename for
  both services.

### Compatibility

- **EEPROM workflow is unchanged.** Existing tests pass without
  modification; an EEPROM-only release produces zero briefs and
  no `[AGENT TODO]` footer.

---

## [1.14.0] — 2026-05-12

**Global skill, per-project state.** The skill is now install-once /
use-everywhere: a single skill folder serves any number of project
workspaces, each with its own `config/` + `inputs/` + `outputs/`.
Project root is resolved via a four-tier policy and a fresh
workspace can be scaffolded interactively. All additive — v1.13.x
single-workspace installs keep working unchanged.

### Added

- **`scripts/project_root.py`** — `resolve_project_root()` with the
  four-tier policy: `--project-root <path>` CLI > `$DID_TOOLKIT_PROJECT_ROOT`
  env var > CWD-walk for `config/project.json` (the marker file IS
  the v1.13.x config, no separate marker required) > skill-folder
  fallback. Helpers `is_project_root(path)` and
  `find_project_root_upward(start)` exposed for downstream tooling.
- **`PipelineController.skill_root` / `.project_root`** — the
  historical `base_dir` attribute now aliases `project_root` so
  every v1.13.x call site (`self.base_dir / 'inputs'`, etc.) keeps
  working without churn. `skill_root` stays anchored at the install
  dir so `tests/` and `reference/` references remain stable.
- **`pipeline.py --project-root <path>`** — explicit override flag.
  Validated at parse time; bad path raises `FileNotFoundError`
  with a remediation hint that names the source (`--project-root`
  vs `$DID_TOOLKIT_PROJECT_ROOT`).
- **`pipeline.py --init-project [PATH]`** — new verb that scaffolds
  a fresh workspace at `PATH` (defaults to CWD). TTY mode prompts
  interactively for `name` / `product_type` / `customer_name` /
  `project_root` / `paths.base_dir` with smart defaults; non-TTY
  writes a starter template + WARNING. Refuses to overwrite an
  existing `config/project.json` (exit code 1).
- **`scripts/init_project.py`** — implementation module with
  `run_init_project(target_path, *, interactive=None)`. Round-
  trips the starter payload through `ProjectConfig.model_validate`
  so any drift between template and schema fails loud at init time
  rather than at first phase invocation.
- **`pipeline.py --config <path>`** — global flag to select among
  sibling `config/project*.json` files. Resolves workspace-
  relative, bare-filename (auto-prefixed with `config/`), or
  absolute paths.
- **`pipeline.py --list-configs`** — enumerate every
  `config/project*.json` in the workspace as `TAG<TAB>RELATIVE-PATH`
  (sorted, exit 0 on empty). Mirrors `--list-inputs`.
- **`scripts/config_selector.py`** — multi-config selection policy.
  Single match auto-selects; multiple + TTY = numbered menu; multiple
  + non-TTY = exit code 4 + stderr ambiguity error listing every
  candidate. Identical contract to v1.12.1 multi-input.

### Changed

- **`pipeline._load_json('config/project.json')`** transparently
  redirects to the active multi-config selector path so legacy
  callers honour `--config <path>` without needing rewrites.
- **`PipelineController.load_project_config()`** honours
  `self.active_config_path` set by the selector.
- **`SKILL.md`** — new "Multi-project workspaces" section
  documenting project-root resolution, `--init-project`, and
  multi-config selection.
- **`README.md`** — new "🌐 全局 skill / 多项目工作区" section at
  the top covering the new workflow; "三步必做清单" notes
  `--init-project` as the recommended bootstrap.

### Compatibility

- **Single-workspace install (v1.13.x style) is the tier-4
  fallback**, so operators who haven't migrated to per-project
  workspaces see no behaviour change. Existing tests pass without
  modification.

### Tests

- `tests/unit/test_project_root.py` (14) — every tier of the
  resolver, plus marker-detection edge cases (directory vs file,
  empty env var treated as unset).
- `tests/unit/test_init_project.py` (8) — headless happy path,
  Pydantic round-trip, refuse-to-clobber, TTY interactive flow
  with patched `input`, bad-product-type re-prompt loop, EOF
  abort.
- `tests/unit/test_config_selector.py` (15) — discovery sort
  order, explicit-path resolution (workspace-relative, bare,
  absolute), single-config auto-select, empty workspace, multi-
  config TTY menu (index + tag), reprompt-then-accept, EOF, non-
  TTY ambiguity exit code.

---

## [1.13.0] — 2026-05-12

**Three platform-borrowed Phase 2 / Phase 3 upgrades land together
behind one MINOR bump:** Pydantic-validated `config/project.json`,
ARXML-reviewer false-positive purge (differential B), per-DID
`product_scope` filter + cross-product SCOPE auditor (differentials
A + C). FSCS schema bumps `1.3 → 1.4` (additive only — every legacy
document upgrades silently).

### Added

- **`scripts/config/`** — new package providing strongly-typed
  `ProjectConfig` Pydantic models for `config/project.json`. Four
  sub-models (`ProjectIdentity` / `ProjectPaths` / `ProjectOptions`
  + the top-level `ProjectConfig`), all `extra='forbid'` so a typo
  in a hand-edited config raises at load time instead of silently
  flipping a feature off. `schema_version` defaults to `"1.0"` and
  is the migration hook for future shape changes. `load_project_config(path)`
  returns the validated model; missing / empty file yields safe
  defaults; bad JSON / unknown keys raise loudly. Co-existing dict
  access via `pipeline._load_json('config/project.json')` keeps
  unmigrated call sites working during the transition.
- **`PipelineController.load_project_config()`** — typed accessor
  used by Phase 2's cross-product SCOPE auditor; new code should
  prefer it over the legacy dict.
- **FSCS schema 1.4: `DIDFscsEntry.product_scope: Optional[str]`**
  for per-DID multi-product filtering. `None` (default) keeps the
  v1.3 "applies-to-all" semantics; a non-empty value (e.g. `"DPB"`,
  `"ESP"`, `"Common"`) restricts emission. The literal `"Common"`
  token (case-insensitive) is the wildcard exemption that mirrors
  the DOORS-export convention. `_upgrade_legacy_schema` now treats
  `1.3` as a legacy version and silently bumps it to `1.4`.
- **`fscs.apply_product_scope_defaults(document)`** — Phase 1
  builder helper. After build, walks the document and stamps
  `product_scope = project.product_type` onto every untagged
  (`None`) DID when `project.product_type` is set. Single-product
  workflows stay zero-operator: an operator who never touches the
  CSV's `product_scope` column still gets the right filter.
- **CSV editor: new `product_scope` column** (between `rw_state`
  and `service_22_support`). Empty cell maps back to `None`; the
  operator can promote a DID to `Common` (wildcard) or pin it to
  one product without leaving the spreadsheet.
- **Phase 2 `OUT_OF_SCOPE` validation status** — DIDs whose
  `product_scope` doesn't match the active `--product-type` are
  excluded from `DID_Config.arxml` and surface as `[SCOPE]` rows
  in `validation_report.txt` with an `OUT_OF_SCOPE: <count>`
  summary line. Distinct from `ERROR` / `SKIPPED` so multi-product
  workspaces can audit "intentionally absent" vs "accidentally
  missing".
- **Differential C — cross-product SCOPE auditor**
  (`ARXMLReviewer.review_cross_product_scope(config,
  current_product_type)`). When the active `paths.arxml_file`
  template contains `{product_type}` and the project tree has
  ARXMLs for sibling products (e.g. `.../DPB/DID_Config.arxml`
  alongside `.../ESP/DID_Config.arxml`), the reviewer flags every
  `DcmDspDid` SHORT-NAME that appears in more than one product's
  ARXML — *unless* the corresponding entry's `product_scope` is
  `"Common"`. New `SCOPE` issue type joins the existing
  `STRUCTURE` / `COVERAGE` / `IDENTIFIER` / `SIZE` / `INFOREF` /
  `FUNCTION` axes.
- **Tests:** `tests/unit/test_config_schema.py` (18 tests covering
  schema defaults, typo rejection, schema_version pin, round-trip
  fidelity, Unicode survival, behaviour matrix); 
  `tests/unit/test_review_arxml_emitted_set.py` (5 tests pinning
  differential B); `tests/unit/test_product_scope.py` (15 tests
  pinning differentials A + C end-to-end including
  `apply_product_scope_defaults`, OUT_OF_SCOPE filter, ARXML
  exclusion, validation report summary, cross-product overlap
  flagging, Common opt-out, single-product short-circuit).

### Changed

- **Differential B — `review_arxml.py` data source switched to the
  generator's emitted set.** v1.12.x's `_effective_dids()` filtered
  by `supported_by_ecu`, which produced false `COVERAGE` /
  `IDENTIFIER` / `SIZE` / `INFOREF` / `FUNCTION` issues against
  every `DESELECTED` / write-only `ERROR` / RW-compliance `SKIPPED`
  DID — i.e. the reviewer expected DIDs the generator deliberately
  dropped. v1.13.0 reuses `ARXMLGenerator._document_to_dids(verbose=False)`
  to compute the SUCCESS subset and drives every per-axis check off
  it. The `_effective_dids` method is preserved (legacy-fallback
  shim activates when `dids_json` is injected directly without
  `load_from_fscs_json`, keeping older test fixtures passing).
- **`ARXMLGenerator._document_to_dids(verbose=True, product_type=None)`**
  — added two keyword arguments. `verbose=False` silences the
  per-DID OK/SKIP prints (the reviewer needs that to avoid
  duplicating generator output). `product_type=<str>` activates
  the v1.13.0 product-scope filter.
- **`load_dids` / `generate` thread `product_type` through**, and
  `pipeline.run_phase2 → _run_arxml_review` now passes both the
  product type and the typed `ProjectConfig` to
  `review_arxml.run_review` so the reviewer's `emitted` set agrees
  with the generator's filter and the cross-product SCOPE axis
  fires when the layout supports it.
- **`review_arxml.run_review(product_type=None, config=None)`** —
  new keyword parameters. Both default to `None`, preserving the
  v1.12.x single-tree-no-filter posture for callers that haven't
  migrated.
- **`SCHEMA_VERSION = "1.4"`** in `fscs/schema.py`; assertions in
  `test_schema_v1_3.py`, `test_pipeline_argparse.py`,
  `test_fscs_import_cli.py`, and `test_fscs_dual_write.py` updated
  accordingly. `tests/golden/phase_all/fscs/fscs.json` regenerated
  with `--update-goldens` (now carries `product_scope: "DPB"` per
  DID, matching the auto-fill behaviour).

### Internal / Migration notes

- `config/project.json` migration path is purely additive: a v1.12.x
  file with no `schema_version` field loads as `1.0` and validates
  cleanly. No operator action required.
- FSCS migration path is also additive: a v1.3 `fscs.json` (no
  `product_scope` keys) loads as v1.4 with `product_scope=None`
  on every DID, matching the v1.12.x "no filtering" behaviour.
- New `OUT_OF_SCOPE` status is the first non-error / non-success
  validation row that affects ARXML output. Tooling that grep'd
  `[OK]` / `[SKIP]` / `[ERR]` / `[DESEL]` should add `[SCOPE]`
  to its allowlist.
- Cross-product SCOPE auditing is opt-in by configuration: a
  workspace whose `paths.arxml_file` lacks `{product_type}` (single-
  product layout) gets the v1.12.x reviewer behaviour for free.
  No new CLI flag is needed.

---

## [1.12.1] — 2026-05-12

**Multi-questionnaire selection contract (v1.12.0) tweaked: the agent
must ask the operator in plain text and stop the turn — do NOT use
the `AskQuestion` tool. CLI behaviour is unchanged (still `exit 3`
on non-TTY multi-candidate, still interactive menu on TTY).**

### Changed

- **`SKILL.md`** — *Multiple questionnaires in `inputs/`* sub-section
  step 3 rewritten: render a numbered list of candidates **directly
  in the assistant message and stop the turn** so the operator can
  reply conversationally. Explicit "Do not use the `AskQuestion`
  tool" instruction added. Worked example block included.
  Frontmatter `description` and *Commands (Quick Reference)* row for
  `--list-inputs` updated to match.
- **`README.md`** — Step 2 lead paragraph: "通过 `AskQuestion` 让你选" →
  "直接在回复里把候选编号列出来停住等你回复（不用任何弹窗工具）".
- **`scripts/pipeline.py`** — non-TTY error message and `--list-inputs`
  argparse help reworded the same way; `_select_input_or_exit` and
  `discover_input_candidates` docstrings updated. No code-path
  changes.

### Test status

624 / 624 pytest tests still passing (no test changes — the
contract change is purely in the agent-facing documentation and
operator-facing log strings).

### Rationale

The operator preferred a single conversational thread without
modal popups for the multi-candidate prompt. Plain text in the
assistant reply also keeps the full chat history searchable
(the picked file, plus the timestamp the question was asked) in
one place, which `AskQuestion` answers don't always preserve.

---

## [1.12.0] — 2026-05-12

**Multi-questionnaire selection contract: when `inputs/` has more than
one candidate, the agent must enumerate via `--list-inputs` and ask
the operator (Cursor `AskQuestion`) before invoking Phase 1; humans
at a TTY get an interactive numbered menu. The previous WARN +
silent alphabetical auto-pick is gone — non-interactive invocations
without `--input` exit `3` with an actionable error.**

### Added

- **`scripts/pipeline.py --list-inputs`** — new side-effect-free CLI
  flag. Enumerates every Phase-1 candidate under `inputs/` (one
  absolute POSIX path per line, `.xlsx` / `.xlsm` tier first then
  `*_did.json` tier), exits 0 even on a missing or empty `inputs/`
  (use empty stdout as the empty-set signal). Designed for the
  agent's pre-flight `AskQuestion` flow.
- **`PipelineController.discover_input_candidates()`** — public
  helper returning `{"xlsx": [Path, ...], "json": [Path, ...]}`,
  alphabetically sorted, Excel temp files (`~$*`) excluded, missing
  `inputs/` returns empty lists. Reused by both `--list-inputs` and
  the auto-detect branch in `main()`.
- **`scripts/pipeline.py::_select_input_or_exit()`** — module-level
  function that branches on `sys.stdin.isatty() and sys.stdout.isatty()`:
    - **TTY** — prints a numbered menu to stderr, reads operator's
      choice via `input()`, accepts `q` / `Ctrl-C` to abort, retries
      up to 3 times on invalid input.
    - **Non-TTY** — prints a hard ERROR listing every candidate plus
      the two remediation paths (`--input <path>` for one-shot use, or
      the `--list-inputs` + `AskQuestion` flow for the agent), then
      `sys.exit(3)`.
- **`tests/unit/test_pipeline_input_discovery.py`** — 9 new unit
  tests pinning:
    - `discover_input_candidates()` tiering, sorting, `~$` exclusion,
      `.xlsm` support, `*_did.json` decoy filtering, and missing-dir
      tolerance.
    - `--list-inputs` exit-0 contract and side-effect freedom.
    - `_select_input_or_exit()` non-TTY exit 3, TTY happy path
      returning the chosen path, TTY abort on `q`.

### Changed

- **`scripts/pipeline.py::main()`** — auto-detect branch refactored.
  Single-candidate behaviour is unchanged; multi-candidate branch
  now delegates to `_select_input_or_exit()` instead of warning +
  silently picking the alphabetically-first file. The previous
  behaviour (since v1.7) caused operators to not notice a wrong-
  file selection until downstream artefacts were already committed.
- **`SKILL.md`** — frontmatter `description` mentions the new
  selection contract; *Editing workflows* item 1 gains a *Multiple
  questionnaires in `inputs/` (v1.12.0)* sub-section spelling out
  the four-step contract; *Commands (Quick Reference)* table adds a
  row for `--list-inputs`.
- **`README.md`** — Step 2 lead paragraph rewritten: "多份共存也行"
  with the new `--list-inputs` + `AskQuestion` story spelled out.

### Behaviour change (non-breaking for the single-candidate case)

| `inputs/` has ... | `--input` passed? | TTY? | Pre-1.12.0 | 1.12.0 |
|---|---|---|---|---|
| 0 candidates | — | — | exit 1 | exit 1 (unchanged) |
| 1 candidate | no | — | auto-pick | auto-pick (unchanged) |
| 2+ candidates | yes | — | use `--input` | use `--input` (unchanged) |
| 2+ candidates | no | yes | WARN + alphabetical auto-pick | interactive menu |
| 2+ candidates | no | no | WARN + alphabetical auto-pick | **ERROR exit 3** |

The non-TTY 2+-candidate change is the only one that flips an
exit code (0 → 3); CI / agent shells previously got a silent (and
likely wrong) auto-pick. Operators who relied on that behaviour
should pass `--input <path>` explicitly.

### Test status

624 / 624 pytest tests passing locally (was 615 / 615 in 1.11.0;
9 additions are the new `test_pipeline_input_discovery.py` cases).

---

## [1.11.0] — 2026-05-12

**Public helper API for agent-written one-off Phase 1 extractors.**
Promotes the per-cell normalisers and access-block utilities that were
previously package-private (underscore prefix inside
`scripts/excel_extract/extractor.py`) to a stable public surface on
the `excel_extract` package root. Direct consequence of the v1.10.2
self-containment statement: agents writing
`scripts/extract_<customer>.py` for a novel questionnaire layout no
longer have to import private symbols.

### Added

- **`scripts/excel_extract/helpers.py`** — new module hosting the
  canonical implementations of the per-cell helpers. Public names
  (without underscores), with full docstrings tied back to
  `reference/excel-ingestion.md` and the schema invariants in
  `reference/input-format.md`:
    - `normalize_did_hex(raw) -> Optional[str]` — canonical `"0xXXXX"`
      uppercase 4-hex form, or `None` for invalid / sentinel input.
    - `coerce_size(raw) -> str` — digit string or `"TBD"`; tolerates
      `"10 bytes"`, `1.0`, blanks.
    - `normalize_yn(raw, default="N") -> str` — Y/N variants
      (`yes` / `true` / `1` / `x` / `✓` / blank / `-` / `—` / `/` /
      `✗`) → `"Y"` / `"N"`.
    - `normalize_rw(raw, default="R") -> str` — `R` / `W` / `R/W` /
      `RW` / `RWX` → `"R"` / `"W"` / `"RW"`.
    - `empty_access()` / `empty_access_block()` — fresh default
      access skeletons (full nested shape, every leaf `"N"`) so the
      schema's hard rule about always-present `service_22 / service_2e`
      blocks can be satisfied without thinking.
    - `merge_access_block(target, source) -> None` — **in-place**
      OR-merge; any `"Y"` wins. Use when a DID appears on multiple
      sheets.
    - `collapse_method_lines(*cells)` / `join_lines_compact(value)` —
      multi-line cell joiners that drop the usual placeholders
      (`"/" / "-" / "—"`).
    - `END_SENTINEL = "#endofdata"` — lower-case stop marker shared
      with the Olympus template; compare via
      `text.lower().startswith(END_SENTINEL)`.
- **`scripts/excel_extract/__init__.py`** — rewritten to re-export
  the new public helpers plus the schema-1.3 sub-field normalisers
  (`SubFieldDataType`, `SubFieldEncoding`,
  `normalize_sub_field_data_type`, `normalize_sub_field_encoding`),
  so a one-off extractor can do everything from a single
  `from excel_extract import ...` line. `__all__` updated; `dir()`
  / IDE autocompletion reflect the new surface.
- **`tests/unit/test_excel_extract_public_api.py`** — 15 new tests
  pinning:
    - All 20 documented public names are exported on the package
      root.
    - `__all__` matches the documented list (no drift).
    - The 10 public helper objects are **the same objects** as the
      underscore aliases the GAC / Olympus parsers in `extractor.py`
      already import — guarantees zero behavioural drift between
      paths.
    - Smoke checks for the documented contract (canonical `0xXXXX`
      from `normalize_did_hex`, lower-case `END_SENTINEL`, full
      nested shape from `empty_access`, fresh dict per call, in-place
      OR-merge from `merge_access_block`, R/W canonicalisation, Size
      coercion, Y/N variants, multi-line joiners).
    - Schema-1.3 normalisers re-exported are the same callables as
      `fscs.schema.normalize_sub_field_data_type` / `_encoding`.

### Changed

- **`scripts/excel_extract/extractor.py`** — internal helper
  implementations moved to `helpers.py`; the file now keeps only the
  template parsers (GAC / Olympus) and re-imports the helpers under
  their original underscore names so every existing call site
  (`_normalize_did_hex` / `_yn` / `_normalise_rw` / `_empty_access` /
  `_merge_access_block` / `_END_SENTINEL` / `_coerce_size` /
  `_collapse_method_lines` / `_join_lines_compact`) stays
  byte-identical. Net diff: -126 / +14 LoC, no behavioural change.
- **`reference/excel-ingestion.md`** — §3 worked starter example
  now uses public names (`from excel_extract import normalize_did_hex,
  ...`) instead of underscore imports. §4 helper inventory rewritten
  for the public surface, lists every helper with its public name +
  signature + one-line description, and adds a backward-compatibility
  note pointing at the surviving underscore aliases.
- **`README.md`** — top banner now opens with a 🔒-marked
  *自含 skill* statement and explicitly names the public import
  surface so first-time readers see "the agent path" without diving
  into reference docs.
- **`SKILL.md`** — frontmatter `description` mentions the public
  helper API; version bumped to 1.11.0 in three places (frontmatter,
  H1, version-section line).

### Removed

- Nothing user-visible. The underscore aliases in
  `scripts/excel_extract/extractor.py` are still in place for
  pre-1.11.0 callers and will be marked deprecated (not removed) in a
  future MINOR.

### Test status

615 / 615 pytest tests passing locally (was 600 / 600 in 1.10.x; 15
additions are the new `test_excel_extract_public_api.py` cases).

---

## [1.10.2] — 2026-05-12

**Phase 1 ingestion model rewritten in the docs as agent-driven by
default. `did-toolkit` is now formally self-contained — no runtime
dependency on `did_extract` or any other extraction skill. The shipped
`scripts/excel_extract/` GAC + Olympus parsers are reframed as
"convenience captures of two known templates", not as the canonical
input path.**

This release is documentation + frontmatter only. Code, schema, CLI,
and observable behaviour are byte-identical to 1.10.1; the change is
about how operators (and future agents) think about Phase 1 input.

### Added

- **`reference/excel-ingestion.md`** — new authoritative guide for the
  Phase 1 input boundary. Covers:
    - The two-tier model (convenience parsers vs. agent-driven
      extraction) with the explicit rule that agent-driven is the
      primary path going forward.
    - The fixed JSON contract — recap of `input-format.md` plus the
      hard rules (canonical `0xXXXX`, never hard-code `rw_state`,
      always emit the full `access` skeleton, OR-merge across
      services, security inclusion).
    - Step-by-step agent workflow: inspect workbook → write one-off
      `scripts/extract_<customer>.py` → produce `inputs/<customer>_did.json`
      → `--validate` → `--phase fscs`.
    - Helper inventory in `scripts/excel_extract/extractor.py`
      (`_normalize_did_hex`, `_coerce_size`, `_yn`, `_normalise_rw`,
      `_empty_access`, `_merge_access_block`, `_END_SENTINEL`) plus
      schema-1.3 normalizers (`normalize_sub_field_data_type`,
      `normalize_sub_field_encoding`).
    - "When (not) to extend `excel_extract/`" rule of thumb (only
      after two or more structurally-identical questionnaires from
      the same template family).
    - Self-containment statement: never call `did_extract`, never
      copy `did_extract/references/*` into `scripts/extract_*.py`,
      never hand-edit `inputs/<customer>_did.json`.

### Changed

- **`SKILL.md`** — frontmatter `description` and the lead paragraph now
  describe Phase 1 input as dual-path (agent-driven primary,
  convenience parsers for GAC / Olympus only) and add an explicit
  *"Self-containment"* callout. The Three-Phase Pipeline table row 1
  reflects the dual path. Editing-workflows item 1 split into a
  known-template branch and an agent-driven branch with full command
  sequence. *Best Practices* "Input management" entry rewritten to
  mandate the agent-driven path for unfamiliar templates and
  explicitly forbid reaching into `did_extract`. *Additional
  Resources* table gains a row for `excel-ingestion.md`.
- **`README.md`** — Step 2 retitled *"投放诊断问卷（双路径）"* with a
  table comparing the two paths, an explicit pointer to
  `reference/excel-ingestion.md`, and the self-containment statement.
- **`reference/input-format.md`** — top-of-file callout retitled
  *"This file is the only fixed contract for Phase 1 input"* and now
  references both extraction paths instead of the legacy "questionnaire
  is single source of truth + .json is fall-back" framing.

### Unchanged

- All Python code (`scripts/excel_extract/`, `scripts/fscs/`,
  `scripts/pipeline.py`, `scripts/generate_fscs.py`, the DOORS sub-
  package) is byte-identical to 1.10.1. No CLI flags added or
  removed; no schema changes; no test-fixture changes.
- `inputs/<customer>_did.json` legacy auto-discovery still works
  exactly the same way; this release simply re-frames it from
  *"transitional fall-back"* to *"first-class agent-driven output
  format"*.

---

## [1.10.1] — 2026-05-12

**DOORS upload re-positioned as the optional Phase 4. Operator-facing
prompts at the end of every Phase 1 / CSV-import / `--phase all` run
now surface the exact `--phase doors` commands so the upload path is
discoverable from the console instead of from the docs.**

The entire DOORS subsystem was already opt-in (gated on
`--phase doors`), but the post-Phase-1 console output never mentioned
it, leaving operators to grep `SKILL.md` for the command. This release
makes the optional step explicit at the three decision points where
the operator naturally pauses:

### Added

- **`scripts/pipeline.py::run_phase1`** — final "Next steps" block now
  has a dedicated *"Optional — DOORS upload"* sub-section with three
  command variants (smoke / verify-anchors / full-upload) and a one-
  line reminder of the two `inputs/doors_mapping.yaml` UUIDs that
  must be filled before the full upload.
- **`scripts/pipeline.py::run_csv_import`** — previously logged only
  the four "Updated:" lines and returned silently. Now prints a
  matching "Next steps" block (Phase 2 / Phase 3 + the same DOORS
  optional sub-section) so the obvious follow-up after editing the
  CSV is visible without re-reading the docs.
- **`scripts/pipeline.py::main` (`--phase all` summary)** — when all
  three phases succeed, appends *"Optional next step — push the FSCS
  to DOORS"* with the smoke-test and full-upload commands.

### Changed

- **`SKILL.md`** — three-phase pipeline table extended with a
  *"4 (optional)"* row pointing at `scripts/fscs/doors/doors_sync.py`,
  with explicit "opt-in only — `--phase all` never runs this" note.
  Editing-workflow item 5 retitled to *"DOORS prep / upload (optional
  Phase 4)"* and references the new console hints.
- **`README.md`** — second-paragraph headline retitled
  "首次使用 / 新项目落地" (DOORS removed from the must-do list); the
  former *"DOORS 上传 — 上传前必填项"* H2 is now
  *"🟦 可选第 4 步 ─ DOORS 上传"* with sub-sections renumbered
  4.1 / 4.2 / 4.3 / 4.4. New callout under Step 3 tells the operator
  that the console will print the optional DOORS hint at the end of
  Phase 1 / CSV-import / `--phase all`.

### Unchanged

- DOORS upload behaviour itself (CLI flags, MCP transport, anchor
  resolution, per-DID two-row layout, FS↔CS link reconciliation) is
  byte-identical to 1.10.0.
- `--phase all` is still strictly Phase 1 → Phase 2 → Phase 3 (no
  auto-DOORS); chaining DOORS into `all` would require credential
  prompts and a real `document_uuid`, which `--phase all` cannot
  validate.
- `fscs.json` schema stays at `1.3`; no test fixtures or golden files
  changed.

---

## [1.10.0] — 2026-05-12

**DOORS upload pipeline rewritten: per-DID two-row, two workbooks,
per-service anchors, automatic FS↔CS link generation.**

The Phase-doors output stops being a single aggregate `Object Text`
cell and becomes a faithful per-DID layout: every DID lands as two
adjacent DOORS rows (FS = Object Heading, CS = Object Text), one
workbook per service ($22 / $2E), each anchored under the matching
service-introduction paragraph in the live DOORS module. After the
two content uploads succeed, the orchestrator re-fetches the module,
pairs each FS row with the row that follows it (the freshly-inserted
CS row) by Object-Heading text match, and uploads a links workbook
that wires every CS → FS via MCP `update_doors_links`.

### Added

- **`scripts/fscs/doors/fscs_split.py`** — parses the rendered
  `FSCS_22.txt` / `FSCS_2E.txt` into per-DID `DIDBlock` records
  (`did_hex`, `did_name`, first-line `heading`, body). The renderer
  banner is stripped so it never leaks into a DOORS row.
- **`scripts/fscs/doors/anchor.py`** — locates a per-service anchor
  AbsoluteNumber from a DOORS export JSON (`outputs/doors/doors_export.json`)
  by matching the user-supplied keyword text against
  `DescriptionOfRequirementRB`. Three resolution rules in order:
  `by_absolute_number` override → exact text match → whitespace-
  normalised text match. Loads both `data.rows` and top-level `rows`
  shapes.
- **`scripts/fscs/doors/mcp_transport.py`** — minimal HTTP/SSE
  transport for the DOORS MCP server with explicit per-call timeouts
  (port of the `diagcomm-toolkit` `doors_fetch.py` transport, kept
  byte-for-byte compatible).
- **`scripts/fscs/doors/doors_fetch.py`** — `python … doors_fetch.py
  <module_uuid> <user_nt> [--refresh]` calls `get_doors_module`
  (optionally preceded by `refresh_doors_module`) and persists the
  payload to `outputs/doors/doors_export.json`.
- **`scripts/fscs/doors/doors_upload_mcp.py`** — wraps both
  `upload_doors_module` and `update_doors_links` behind a single
  `upload | links` CLI; reads `--password` or `$DOORS_PWD`, never logs
  the password.
- **`scripts/fscs/doors/doors_links.py`** — `LinkEntry` dataclass plus
  `reconcile_did_rows` (pairs each FS row with the row that follows
  it in a fresh export) and `build_link_xlsx` (DOORS-native xlsx
  with `Source Module / Source AbsoluteNumber / Target Module /
  Target AbsoluteNumber / Link Type / Link Module` columns). Default
  direction is `cs_to_fs` per the user's spec.
- **`inputs/doors_mapping.yaml` v2 schema**:
  - `anchors.service_22.text` + `anchors.service_2e.text` — verbatim
    multiline keyword strings with optional `by_absolute_number`
    override.
  - `value_maps.RB_Product` is consulted per DID; the special token
    `Common` (project-level or per-DID via
    `rb_product_overrides[did_hex]`) fans the cell out to every
    mapped product joined by newline.
  - `realizing_paths.templates` renders per-DID strings with
    `{did_hex} / {did_hex_bare} / {did_name} / {product_type} /
    {customer}` placeholders for the `RB_Realizing_SWitem` cell.
  - `links.{enabled, link_type, link_module_uuid, direction}` — the
    link-Excel knobs; the link upload no-ops with a warning when
    `link_module_uuid` is blank.
  - `columns:` source bindings mirror diagcomm-toolkit
    (`row.<key> | extras.<key> | literal:<text>`).
- **`scripts/pipeline.py` --phase doors** new flags:
  `--no-fetch` (reuse the on-disk export), `--no-links` (skip the
  link upload), `--no-anchor` (cheapest smoke test; no MCP traffic;
  the `Destination Object` cell stays blank), `--refresh` (force
  `refresh_doors_module` on fetch). The legacy `--force-mode` /
  `--force-no-skip` flags are removed (every run rebuilds the full
  per-service workbook set, so insert/update is no longer a thing).
- **16 new unit tests** in `tests/unit/test_doors_payload.py`
  covering `fscs_split` parsing/banner-strip/hex padding,
  `anchor.resolve_anchors` exact + normalised + by_absolute_number,
  per-DID two-row build with `RB_Product` resolution (single product,
  `Common` fan-out, per-DID override), anchor injection from a real
  export, FS↔CS reconciliation, and link xlsx column layout (both
  directions). Full suite: **600/600 passing**.

### Changed

- **`scripts/fscs/doors/build_doors_payload.py`** completely rewritten.
  The single-row strategy is gone; every service now emits one xlsx
  under `outputs/doors/` (`doors_upload_22.xlsx`,
  `doors_upload_2E.xlsx`) with two rows per DID (FS heading row + CS
  text row) plus the configured `RB_*` defaults on every row.
  Workbooks are written directly with `xlsxwriter` (DOORS-native:
  `Application=Microsoft Excel`, sharedStrings, string-typed
  `sizeRow / sizeColumn`); the `doors-toolkit` subprocess hop is
  retired.
- **`scripts/fscs/doors/doors_sync.py`** rewritten as the end-to-end
  orchestrator: fetch (or reuse) the DOORS export, resolve anchors,
  build both workbooks, upload them via MCP `upload_doors_module`,
  re-fetch the module, reconcile FS/CS pairs by Object-Heading text
  match, build the link xlsx, upload it via MCP
  `update_doors_links`, and persist the run summary under
  `state/doors_upload_state.json`.
- **Output paths** — every DOORS artefact now lives under
  `outputs/doors/`: `doors_export.json`, `doors_upload_22.xlsx`,
  `doors_upload_2E.xlsx`, `doors_upload_links.xlsx`,
  `doors_link_entries.json`, `doors_payload_report.txt`.

### Removed

- Single-row aggregated-cell DOORS strategy (`strategy: single_row`
  / `strategy: per_service` knob in the old mapping yaml). Every
  upload is now per-DID two-row.
- The `force-mode` / `force-no-skip` insert-vs-update CLI surface in
  `--phase doors`. DOORS' anchor-driven insert handles the equivalent
  semantics on every run.
- The `doors-toolkit` subprocess hop in
  `build_doors_payload.py` (the workbook is produced in-process).

### Migration Notes

- Re-fill `inputs/doors_mapping.yaml` from the new template — the v1
  schema (`anchor:` singular, `strategy:`, `mode:`) is no longer
  recognised. The new template is shipped at the same path; the
  smallest required edit is `doors.document_uuid` and
  `links.link_module_uuid`.
- Existing `state/doors_upload_state.json` v1 entries are silently
  ignored; the new orchestrator writes a v2 entry on its first run
  per module (kept lightweight: no insert/update history because
  every run is a full per-DID rebuild).

---

## [1.9.0] — 2026-05-12

**Schema 1.3: standardised per-sub-field `data_type` and `encoding`.**
The questionnaire's per-byte business semantic and bit-level encoding
are now lifted into the Pydantic schema as proper Literal enums, with
case-insensitive aliasing so the operator's familiar spellings still
work. Bonus: two long-standing GAC column-mapping bugs that this work
exposed are also fixed.

### Added

- **`SubFieldDataType`** Literal: ``Numeric / Enum / BitField / Hex /
  ASCII / BCD / Composite``. The per-sub-field business semantic.
- **`SubFieldEncoding`** Literal: ``Unsigned / Signed / Float32 /
  Float64 / ASCIIString / RawBytes``. The bit-level decoding hint.
- **`FSCSSubField.data_type`** and **`FSCSSubField.encoding`** --
  optional fields populated from the questionnaire by Phase 1 (or
  left at ``None`` when the source cell is blank / unrecognised).
- **`normalize_sub_field_data_type` / `normalize_sub_field_encoding`**
  helpers exposed on the ``fscs`` package surface so other tooling
  can reuse the same alias tables. Aliases include legacy
  DataType literals (``Identity`` / ``Linear`` ⇒ ``Numeric``,
  ``Bytefield`` ⇒ ``Hex``, ``Texttable`` ⇒ ``Enum``) plus common
  Bosch DCOM type spellings (``uint8``/``u16``/``s32``/``sint16``).
- **Extractor inference helper** `_infer_encoding_from_data_type`:
  fills in obvious encodings (``ASCII⇒ASCIIString``, ``Hex⇒RawBytes``,
  ``BCD⇒RawBytes``, ``BitField⇒Unsigned``) when the questionnaire
  only declares the business semantic. Numeric / Enum / Composite
  intentionally stay silent so the existing renderer heuristic still
  drives the Signed-vs-Unsigned choice from the physical range.
- **94 new unit tests** covering the alias tables, the
  ``FSCSSubField`` validator round-trip, the v1.0/v1.1/v1.2 ⇒ v1.3
  schema upgrade, and the extractor's normalisation helpers; plus a
  parametrised live-extract test that pins the canonical-only
  invariant across all three checked-in questionnaires.

### Changed

- **`FSCSDocument.schema_version`** bumped to ``"1.3"``. Documents
  written by v1.0/v1.1/v1.2 are silently upgraded on load (the new
  fields default to ``None``).
- **GAC ``method_en`` / ``method_zh`` synonyms** now match the
  ``Conversion(E)`` / ``Conversion(C)`` headers the GAC questionnaire
  actually uses. Pre-v1.9 the rich enum-mapping column was being lost
  on extract, which meant the renderer's ``Byte N [bit X-Y] -> 0x00:
  Foo`` block was usually empty for GAC inputs even when the
  questionnaire was fully filled in. Now it renders as expected.
- **GAC ``default_value_phy`` synonyms** drop the bare ``"default"``
  word (which was cross-claiming the APP / BOOT access ``Default``
  column) and add the questionnaire's actual header spelling
  ``"Deault"`` (sic) so the real default-value column is captured.
- **Builder** passes ``data_type`` and ``encoding`` through to
  ``FSCSSubField``; legacy records that don't carry the keys still
  build cleanly.

### Migration

- Re-run `python scripts/pipeline.py --phase fscs` to refresh
  ``outputs/fscs/fscs.json`` with the new metadata. No CSV / DOORS
  changes are required; the existing ``fscs_edit.csv`` columns stay
  the same. Existing v1.2 ``fscs.json`` files load and are upgraded
  on the next save.
- If you previously hand-edited ``data_type`` cells with values like
  ``Identity`` or ``Linear`` you don't need to rename them -- the
  schema's alias table normalises both to ``Numeric`` automatically.

---

## [1.8.0] — 2026-05-12

**The diagnostic-questionnaire .xlsx is now Phase 1's single source of
truth.** Phase 1 reads the questionnaire directly: there is no longer a
hand-curated `inputs/*_did.json` step in front of `fscs.json`, and the
extractor is wired into `pipeline.py` / `generate_fscs.py` / the
validator so the operator workflow is unchanged on the surface.

### Added

- **`scripts/excel_extract/`** package -- diagnostic-questionnaire
  `.xlsx` reader. Auto-detects the **GAC** template (`$22` / `$2E`
  sheets, OR-merged access permissions, `rw_state` derived from the
  source sheet) and the **Olympus** template (`03.{1,2,3,4}.* DID`
  sheets, 3-row composite header, `#EndOfData` sentinel,
  `IOcontrol`/`Routines` mirror sheets skipped). Outputs the
  `list[dict]` shape `scripts/fscs/builder.py` already consumes, so the
  rest of the pipeline did not change.
- **`scripts/excel_extract/cli.py`** standalone CLI for dry-running the
  extractor against a workbook, printing the detected template, the
  picked sheets, the column-mapping warnings, and the first N DIDs --
  handy for triaging a fresh questionnaire variant before re-running
  Phase 1.
- **`extract_records_with_report` warnings on the console** -- Phase 1
  now prints the questionnaire template, sheets used, and per-row
  extraction warnings without aborting the build. Fundamental issues
  (file not openable, no recognisable DID sheet) still raise.
- 106 new unit + integration tests covering the column-map matcher
  (exact/token/substring passes, the original "byte ↔ Length (Bytes)"
  bug), the value-coercion helpers (`_normalize_did_hex`, `_coerce_size`,
  `_yn`, `_normalise_rw`, the access-block factory + OR-merge),
  template detection, the Olympus sheet picker, and synthetic + live
  end-to-end extraction against the three checked-in questionnaires.

### Changed

- **`pipeline.py` and `scripts/generate_fscs.py` accept `.xlsx` /
  `.xlsm` directly** in addition to the legacy `.json`. Auto-discovery
  prioritises `.xlsx` over `*_did.json` so the typical operator
  workflow needs no `--input` flag. `--validate` performs the same
  Excel parse + per-row warning collection that Phase 1 does.
- **`scripts/review_fscs.py::parse_input_source`** now dispatches on the
  input suffix so the on-demand reviewer can read either an Excel
  questionnaire or a legacy JSON without per-call configuration.
- **`column_map.build_column_map`** uses a three-pass matcher (exact ⇒
  token-aware ⇒ substring) so `Byte` and `Length (Bytes)` do not steal
  each other's column. The original substring-only matcher was the
  root cause of the GAC `0x0101 Variant Coding` first-sub-field
  `byte=16` regression; that case is now pinned by both a synthetic
  and a live integration test.
- **`SKILL.md`** updated to describe the Excel-as-source-of-truth flow,
  the GAC + Olympus template detection rules, the
  `scripts/excel_extract/cli.py` dry-run command, and the legacy-JSON
  fallback.

### Migration

- Drop the diagnostic questionnaire `.xlsx` into `inputs/` and remove
  any hand-curated `inputs/*_did.json` once you've re-run
  `python scripts/pipeline.py --phase fscs` and confirmed the
  resulting `outputs/fscs/fscs.json` matches your expectations
  (`fscs_generation_report.txt` summarises kept/filtered/skipped DIDs).
- Existing `inputs/*_did.json` continues to work unchanged for one
  release as a transitional fall-back -- new column-map synonyms or
  schema additions will land first in the Excel path.
- No `outputs/` migration is required; `fscs.json` schema stays at
  v1.2 in this release. Schema 1.3 (`data_type` / `encoding` lifted
  out of `sub_fields` raw extras into proper enums) lands in v1.9.

---

## [1.7.0] — 2026-05-12

**FSCS TXT rendering now uses structured byte metadata.** Phase 1 stores
byte index/span plus numeric conversion metadata in `fscs.json`, and
CSV import renders byte-accurate request/response tables with per-byte
aggregated value ranges that smart-align across both header rows and
sub-field rows.

### Added

- `sub_fields[].byte_idx`, `sub_fields[].byte_span`,
  `sub_fields[].resolution`, and `sub_fields[].offset` in
  `outputs/fscs/fscs.json`, with legacy `schema_version=1.1` load
  compatibility.

### Changed

- `FSCS_22.txt` no longer emits the redundant `Data Record` summary row.
- `FSCS_2E.txt` shows write data fields in the request block while keeping
  the positive response as the UDS `$6E` acknowledgement.
- Request/response byte tables share **one dynamic column width per DID**:
  `Byte 1`, `Byte 2-3`, and the sub-field rows (including
  `Byte N [bit X-Y]` annotations) all line up against the same column
  edge. The width is computed from the longest byte label so short
  labels never gap-out.
- Per-sub-field `Range:` aux line carries the **logical (raw register)
  HEX range** derived from `(physical - offset) / resolution`, rounded
  half-up to the nearest integer code. Already-hex inputs are passed
  through verbatim.
- Footer `Value Range:` uses a **two-line layout**: each byte group
  emits `Byte[i]:` (or `Byte[i-j]:`) on its own line and the value
  content on the next line indented four extra spaces, so the byte
  column and value column scan independently:
  ```
  Value Range:
              Byte[0]:
                  Physical range: 0 ~ 20.4 V (Resolution: 0.08, Offset: 0)
              Byte[1]:
                  0x00~0x03, 0x05~0x07
  ```
- Footer `Value Range:` is **aggregated by byte** (no bit splitting),
  with two complementary classification rules:
  - **Enum bytes win over numeric bytes.** When a byte group hosts at
    least one enum sub-field, only the merged enum keys are rendered;
    sibling numeric `Physical range:` lines are dropped from that byte
    so enum and numeric views never collide on the same row.
  - Numeric (non-enum) byte groups render `Physical range: <min> ~
    <max> [unit] (Resolution: <r>, Offset: <o>)` on the indented
    second line.
- Enum keys are **interval-merged** before rendering: consecutive keys
  collapse into `0x**~0x**` form (e.g. `0x00, 0x01, 0x02, 0x03,
  0x05-0x07` becomes `0x00~0x03, 0x05~0x07`). Already-merged ranges in
  the input are parsed back into intervals so they can chain with
  neighbouring singletons.
- Long enum interval lists wrap at 80 chars; continuation lines keep
  the same content-column indent so the byte label remains scannable.
- Importer-generated documents (no `sub_fields`) gracefully fall back
  to rendering the summary `did.value_range` with the same two-line
  layout so round-tripping a `.txt` stays lossless on screen.
- **Signed raw fields** now render correctly in the per-sub-field
  ``Range:`` aux line: negative raw values use signed-magnitude hex
  (``-0x003F``) padded to the field's byte width, e.g. a signed int16
  ``-63 ~ 1300`` reads as ``Range: -0x003F ~ 0x0514`` instead of
  falling back to the raw decimal string.
- The footer ``Physical range: ...`` line now appends an inferred
  ``Encoded: Signed/Unsigned`` annotation. The classifier computes
  ``raw_min = (physical_min - offset) / resolution``: ``raw_min < 0``
  is two's-complement signed, otherwise the field is unsigned (with
  any negative physical bias captured by ``offset``). When the inputs
  cannot be parsed (e.g. raw range already in hex literal form) the
  annotation is omitted rather than guessed.

---

## [1.6.0] — 2026-05-11

**FSCS behavior text is now part of the CSV edit loop.** Phase 1 seeds
side-specific behavior templates into `fscs.json`; operators edit them in
`fscs_edit.csv`; CSV import renders the text after `Value Range` in
`FSCS_22.txt` and `FSCS_2E.txt`.

### Added

- `service_22.behavior` and `service_2e.behavior` in `outputs/fscs/fscs.json`
  with legacy `schema_version=1.0` load compatibility.
- `service_22_behavior` and `service_2e_behavior` columns in
  `outputs/fscs/fscs_edit.csv`.
- Storage-derived behavior templates inspired by `did-toolkit-platform`:
  EEPROM uses NVM read/write text, RAM uses `interface: `, and ROM read
  paths use one `HardCode:` header followed by per-byte constant placeholders.

### Changed

- Phase 1 preserves per-service behavior text from the existing `fscs.json`
  for DIDs that still exist, alongside the existing selection preservation.
- `FSCS_22.txt` and `FSCS_2E.txt` now render a side-specific `Behavior:`
  block immediately after `Value Range:`.

---

## [1.5.0] — 2026-05-11

**CSV is now the only operator editing surface, and DID FSCS can be
prepared for DOORS upload.** The CSV round trip exposes only spreadsheet-
friendly DID/service fields; complex JSON/free-text fields stay preserved
inside `fscs.json`. `csv-import` still renders the legacy-style
`FSCS_22.txt` / `FSCS_2E.txt` views via the existing renderer.

### Added

- **`scripts/fscs/doors/build_doors_payload.py`** to build a DOORS-native upload
  workbook from `FSCS_22.txt` and `FSCS_2E.txt` using the sibling
  `doors-toolkit` xlsxwriter path.
- **`scripts/fscs/doors/doors_sync.py`** as the DID DOORS entry point. It decides
  insert/update from local state, builds + lints `outputs/doors_upload.xlsx`,
  and can upload via the doors-toolkit hard-timeout uploader.
- **`inputs/doors_mapping.yaml`** as the user-owned DOORS target and column
  mapping file, plus `state/` for upload state.
- Unit coverage for CSV-only export/import and DOORS xlsx build + lint.

### Changed

- **`fscs_edit.csv` now contains only operator-facing columns**:
  `used_flag`, DID identity/name/type/storage/service support, sessions, and
  security levels. `value_range_json`, `sub_fields_json`, and `free_text_*`
  are intentionally hidden and preserved from `fscs.json`.
- **Phase 1 and CSV import report locked CSV files clearly** instead of
  producing stale/preview edit tables when Excel/WPS has the file open.
- **Versioned docs** now describe CSV-only editing and the DID DOORS upload
  flow.

### Migration

- Regenerate the edit table with `python scripts/pipeline.py --phase fscs`
  after closing any open `outputs/fscs/fscs_edit.csv` handle. The regenerated
  CSV no longer contains JSON/free-text columns.
- Fill `inputs/doors_mapping.yaml::doors.document_uuid` before using
  `python scripts/pipeline.py --phase doors --no-upload`.

---

## [1.4.0] — 2026-05-11

**Phase 1 editing moved from the deleted browser UI to CSV.** Phase 1 now exports a
spreadsheet-friendly `outputs/fscs/fscs_edit.csv` after generating the
authoritative `fscs.json`. Operators edit that CSV in Excel/WPS and run
`python scripts/pipeline.py --phase csv-import` to validate the edits,
rewrite `fscs.json`, emit `FSCS_22.txt` / `FSCS_2E.txt`, and refresh the
FSCS review report.

### Added

- **`scripts/fscs/csv_edit.py`** for deterministic FSCS CSV export/import.
  The import path rejects missing, duplicate, or newly-added DID rows so
  spreadsheet mistakes do not silently change scope.
- **`python scripts/pipeline.py --phase csv-import`** with optional
  `--csv <path>` for importing a non-default edit table.
- **`outputs/fscs/fscs_edit.csv`** as the operator edit artefact. The CSV
  starts with `used_flag`, emits DID values as `0x####`, keeps only
  per-service support flags (`service_22_support`, `service_2e_support`),
  and includes editable DID metadata plus advanced JSON columns for value
  ranges and sub-fields.

### Changed

- **The Streamlit editor stack was removed.** `scripts/ui/`,
  `scripts/requirements-ui.txt`, `--phase ui`, `--phase stop-ui`,
  `--open-ui`, and `--no-open-ui` are no longer shipped.
- **Phase 1 writes `fscs.json`, auto-runs review unless suppressed, and
  exports `fscs_edit.csv`.**
- **`FSCS_22.txt` / `FSCS_2E.txt` are now written by CSV import**, not by
  Phase 1 and not by the normal operator UI path.
- **Documentation updated** in `SKILL.md`, `reference/commands.md`,
  `reference/architecture.md`, and `reference/review.md` to describe the
  CSV round trip as the normal workflow.

### Migration

- Existing `fscs.json` files remain compatible. Run:
  ```bash
  python scripts/pipeline.py --phase fscs
  # edit outputs/fscs/fscs_edit.csv
  python scripts/pipeline.py --phase csv-import
  ```
- Remove any local automation that calls `--phase ui`, `--phase stop-ui`,
  `--open-ui`, or `--no-open-ui`; use the CSV round trip instead.

---

## [1.3.0] — 2026-04-24

**UI lifecycle now matches operator expectations — closing the browser
ends the server.** Through v1.2 the Streamlit editor was a detached
daemon: once spawned, it outlived everything short of `--phase stop-ui`
or a reboot, and a Phase 1 auto-launch from yesterday could still be
holding port 8501 + `streamlit.log` today. v1.3 adds a background
watchdog that mirrors Streamlit's own `SessionManager.num_active_sessions`
signal and exits the process once every browser disconnects.

### Added

- **`fscs-idle-shutdown` watchdog thread** in
  `scripts/ui/fscs_editor.py`. Polls
  `streamlit.runtime.get_instance()._session_mgr.num_active_sessions()`
  every 2 s. Once the editor has served at least one browser (the
  "ever_seen_client" arm), if every session disconnects and nothing
  reconnects within a 20 s grace window, the watchdog calls
  `_terminate_streamlit()` (the existing `os._exit(0)` path used by
  the Exit modal). Page refreshes and brief WiFi hiccups are absorbed
  by the grace window; true tab-close → server down.
- **`DID_UI_IDLE_SHUTDOWN` env var** — set to `0` / `false` / `no` /
  `off` to disable the watchdog entirely. For CI / demo setups that
  need a sticky server across multiple browser sessions. Default:
  enabled.
- **`DID_UI_IDLE_GRACE_S` env var** — override the no-session grace
  period in seconds. Unparseable or non-positive values fall back to
  the 20 s default rather than raising — a typo in an env var should
  not brick the UI lifecycle.
- **`tests/unit/test_fscs_ui_watchdog.py`** covering every branch of
  the pure `_idle_shutdown_decision`, env-var parsing (default, falsy
  spellings, whitespace, unparseable, non-positive), idempotent
  watchdog start, opt-out short-circuit, and the RuntimeError
  degradation path when Streamlit runtime is unimportable (36 cases).

### Changed

- **`pipeline.py::stop_ui` docstring re-framed as a backstop.** The
  common "close the tab and walk away" case is now handled by the
  watchdog; stop-ui remains the CLI for zombies only
  (`DID_UI_IDLE_SHUTDOWN=0`, UI crashed mid-render, or a future
  Streamlit whose `SessionManager` API doesn't match).
- **`SKILL.md` "Streamlit UI & Auto-Launch" section** documents the
  watchdog contract and the two env-var knobs, plus the browser
  `beforeunload` prompt flow for dirty documents.
- **`reference/architecture.md`** system diagram now shows the
  idle-shutdown hook under UI, with a footnote explaining the 20 s
  grace window and the two opt-out env vars.
- **`reference/commands.md`** — `open_ui` entry documents the v1.3
  lifecycle; new `stop_ui` entry explicitly labelled as the backstop.
- **`fscs_editor.py` top-level title** now reads `FSCS editor (v1.3)`.

### Migration

- No breaking changes. Opt-out preserves v1.2 behaviour exactly:
  ```bash
  # headless / CI / sticky dashboard
  $env:DID_UI_IDLE_SHUTDOWN = "0"
  python scripts/pipeline.py --phase ui
  ```
- Operators who relied on `--phase stop-ui` as the *primary* shutdown
  path can continue to do so; the CLI is unchanged. v1.3 just makes
  it unnecessary for the common case.
- The watchdog requires Streamlit 1.20+ (has
  `SessionManager.num_active_sessions`). Older Streamlits degrade
  gracefully — the probe raises `RuntimeError`, the loop counts
  probe failures, and after ~2 minutes of failures the watchdog
  exits the thread silently, equivalent to opting out.

---

## [1.2.0] — 2026-04-24

**Auto-review restored — Review becomes an independent artefact that
tracks the authoritative `fscs.json`.** v1.1.x treated business review
as strictly operator-triggered (UI button + `--phase review`), which
turned out to push stale-report problems onto the operator: generate,
forget to press review, hand off `fscs.json` with a review from three
changes ago. v1.2 puts review back on the critical path -- **not as a
gate**, but as an advisory artefact that is refreshed every time the
source changes.

### Changed

- **Phase 1 auto-runs the FSCS content review after generation.**
  `pipeline.py::run_phase1` now calls `_run_fscs_review(input_path,
  fscs.json)` at the end of the generation block, before the UI
  auto-launch. Failures remain advisory -- the review hook still
  swallows exceptions and logs a WARNING; Phase 1's return value and
  the pipeline's exit code are unaffected. The input JSON is passed
  through so the consistency check runs (same behaviour as
  `--phase review --input ...`).
- **UI Save auto-refreshes the review report.** Every Save path in
  `scripts/ui/fscs_editor.py` (sidebar, bottom bar, modal `Save &
  Exit`, fallback `Save & Exit`) now calls the new
  `_auto_review_after_save` helper after the atomic triple-write
  lands. Input JSON is not in scope in the UI, so review runs
  without the consistency check (business + compliance only). Save
  success toasts now include the review summary counts
  (`Saved ... Auto-review: N issue(s) (business=X, compliance=Y,
  consistency=Z).`).
- **UI "Run business review" button removed.** With Save now being
  the canonical trigger there is no second action worth exposing;
  the single code path avoids the "button ran but you forgot to
  Save" foot-gun. The sidebar's `Last review` pane stays and is
  populated by every auto-review run. CLI users who need to
  re-review without opening the UI still have `python
  scripts/pipeline.py --phase review`.
- **`fscs_generation_report.txt` vs `fscs_review_report.txt`
  semantics clarified in docstrings.** The former is the **ingestion
  gate** artefact (kept / filtered / schema-skipped records). The
  latter is the **content audit** artefact (business / compliance /
  consistency issues against the kept set). Both are advisory and
  live next to each other in `outputs/fscs/`.
- **SKILL.md / reference/review.md / reference/architecture.md /
  reference/commands.md** rewritten to describe the three Review
  trigger paths: Phase 1 end, UI Save, `--phase review`. The "v1.1
  variant" language about "operator-controlled from the UI" is gone.

### Added

- **`--no-review` CLI flag (Phase 1 only).** Skip the Phase 1
  auto-review step. Mirrors the shape of `--no-open-ui`. Intended
  for CI that produces `fscs.json` as an intermediate artefact and
  doesn't need the report in that lane.
- **`DID_NO_REVIEW=1` environment variable.** Same effect as
  `--no-review`, set it once per shell / CI job. Parsed in the
  same case-insensitive `{1,true,yes,on}` style as
  `DID_NO_OPEN_UI`.
- **`_auto_review_after_save(paths)` helper in `fscs_editor.py`.**
  Replaces the old `_run_business_review`. Silent by design -- on
  failure it logs to the child's stderr (redirected to
  `streamlit.log`) rather than painting a red sidebar error, so a
  broken review install doesn't mask the just-successful Save.
  Returns the result dict so the Save success toast can embed the
  counts.
- **`_format_save_toast(review)` helper.** One call site (toast
  wording) shared by all four Save paths; single place to tune the
  message format.

### Fixed

- **"Save, then forget to review" drift.** Previously the on-disk
  `fscs_review_report.txt` could lag the `fscs.json` by an
  arbitrary number of UI edits. v1.2 ties the two together: every
  state change to the authoritative source also refreshes the
  report.
- **Exit-with-unsaved-changes branches now refresh review too.**
  The `Save & Exit` flow (both modal and fallback) used to save
  but not review, leaving a stale report right before the server
  died. v1.2 threads the auto-review in before `_terminate_streamlit`,
  and `run_review`'s typical <200 ms runtime comfortably fits
  inside the existing 0.5 s delayed exit window.

### Migration Notes (v1.1.x → v1.2.0)

- **No CLI breakage.** Every v1.1 command line keeps working
  unchanged; the new behaviour is additive. Operators who want the
  v1.1 silence can add `--no-review` (or export
  `DID_NO_REVIEW=1`).
- **UI muscle memory.** The "Run business review" button is gone.
  Press Save -- review now runs automatically. The `Last review`
  sidebar pane shows the same counts as before.
- **Test fixtures.** `tests/integration/test_phase_all.py` adds
  `fscs/fscs_review_report.txt` to `EXPECTED_EXISTS_ONLY`. If you
  have a fork pinning the v1.1 expected outputs, update the list.

---

## [1.1.1] — 2026-04-20

**Robustness patch for Phase 1 auto-launch.**
Same API and schema as 1.1.0; every change closes a real "pipeline
claims success but UI is dead" failure mode seen in v1.1.0 field use.

### Added

- **Post-spawn health check in `launch_fscs_ui`.** After `Popen`
  returns, the pipeline pauses ~1.2s, polls `proc.poll()`, and — if the
  child already exited — scrapes the last 40 lines of
  `outputs/fscs/streamlit.log` for a known failure signature
  (`ModuleNotFoundError`, port already bound, broken import chain) and
  surfaces a concrete remediation hint instead of the previous cheerful
  "🪄 Launched FSCS editor".
- **Port-listening confirmation.** After the health check, polls
  `127.0.0.1:8501` for up to ~4s to confirm Streamlit is actually
  serving before printing the "open in a browser" message. If the
  deadline expires while the child is still alive, the message switches
  to "still binding port 8501 — check streamlit.log if browser doesn't
  load within 10s".
- **`python scripts/pipeline.py --phase stop-ui`.** Probes port 8501,
  resolves the owner PID (via `psutil` when available, else `netstat
  -ano` on Windows / `lsof` on POSIX), verifies the owner's cmdline
  mentions `streamlit` or `fscs_editor` (refuses to kill anything
  else), terminates it, and clears `streamlit.log`. Fixes the
  recurring "previous Streamlit still holds streamlit.log, new Phase 1
  can't clean up" deadlock.
- **Pinned UI extras in `scripts/requirements-ui.txt`.** Explicit
  floor+ceiling on `click`, `blinker`, and `tornado` so environments
  where Streamlit upgraded in place without bringing its transitive
  deps along no longer ship a dead UI.
- **SKILL.md → FSCS editor troubleshooting section.** Lists the four
  common failure modes (blank browser, stale Streamlit, health-check
  failure, port slow to bind) and the exact command for each.

### Changed

- **`_clean_phase1_outputs` gives a targeted hint when `streamlit.log`
  is locked.** Before: generic `WinError 32` WARNING. After: points
  the operator at `--phase stop-ui` or `--no-open-ui` specifically.

### Fixed

- **Phase 1 auto-launch no longer reports success on a dead child.**
  The v1.1.0 rollout hit this with a missing `click` transitive dep:
  Streamlit exited within ~200ms of start, the pipeline logged
  "Launched FSCS editor", and the operator saw a blank browser.
  Surfaces as a concrete failure with an install hint now.

### Tests

- **New:** `tests/unit/test_pipeline_stop_ui.py` covering the four
  branches of `stop_ui` (port free / owner unknown / owner not
  Streamlit / owner is Streamlit).
- **New:** `tests/unit/test_pipeline_launch_ui.py::TestPostSpawnHealthCheck`
  covering the health check path — dead child returns False, the
  `ModuleNotFoundError: 'click'` log signature produces the install
  hint, and a slow port-binding child still returns True with a
  neutral warning.
- **Updated:** existing launch-UI tests rig the Popen mock with a
  `poll() -> None` child and sequence the port-probe to return False
  pre-spawn / True post-spawn so the new grace period doesn't trip
  them.

---

## [1.1.0] — 2026-04-20

**Phase 1 split + UI as the source of truth for operator decisions.**
Backward-compatible for operators (same CLI, same `fscs.json` schema),
but scripts that depended on Phase 1 auto-writing `FSCS_*.txt` or
auto-running business review need to opt in explicitly.

### Added

- **`--phase review`** — on-demand business review against the existing
  `fscs.json` without re-running Phase 1. Pass `--input` to include the
  JSON-vs-FSCS consistency check; omit it for business + compliance
  checks only.
- **`--phase ui`** — re-opens the Streamlit editor against the existing
  `fscs.json` without regenerating anything. The canonical way to
  resume an editing session.
- **`--reset-used`** — Phase 1 flag that discards preserved `used`
  selections from any pre-existing `fscs.json`. Without the flag,
  Phase 1 carries operator selections forward as before.
- **`outputs/fscs/fscs_generation_report.txt`** — new Phase 1 artefact
  summarising kept / filtered (`supported_by_ecu != Y`) / skipped
  (Pydantic validation errors) records, with per-skipped-DID diagnostics.
- **Port probe** on `127.0.0.1:8501` before spawning Streamlit. If a
  previous session is still answering, the pipeline reuses it instead
  of starting a second server.
- **UI `Run business review` button** — mirrors `--phase review` inside
  the editor; results (counts + report path) surface in the sidebar.
- **UI `Edit mode` toggle** (sidebar, default **OFF**) — locks every
  per-DID field to read-only until the operator explicitly unlocks
  editing. DID selection checkboxes stay live regardless.
- **UI bottom action bar** — primary `Save` and `Exit` buttons. Exit
  with unsaved changes opens a modal `[Save & Exit / Discard & Exit /
  Cancel]`; the browser `beforeunload` hook also warns on tab close.

### Changed (breaking for scripts, not for operators)

- **Phase 1 no longer writes `FSCS_22.txt` / `FSCS_2E.txt`.** Those two
  files are now produced by the UI's atomic triple-write on Save.
  Running `--phase fscs` plus `--phase ui` with a Save in between
  reproduces the v1.0 artefact set.
- **Phase 1 no longer auto-runs business review.** The review step is
  now operator-controlled via the UI button, the standalone
  `scripts/review_fscs.py`, or `--phase review`.
- **Per-record validation in `generate_fscs`.** DIDs that fail Pydantic
  validation are skipped (with a report entry) instead of aborting the
  entire build. Valid siblings still land in `fscs.json`.
- **`--input` auto-detection** now warns and picks the alphabetically
  first JSON when `inputs/` contains multiple files, instead of erroring
  out. Zero files still aborts.
- **`run_review(input_json=None)`** is now accepted; callers that omit
  the raw input get business + compliance checks but skip the
  JSON-vs-FSCS consistency check.
- **Phase 1 rerun cleans stale outputs** under `outputs/fscs/`
  (`fscs.json`, `FSCS_*.txt`, `fscs_review_report.txt`,
  `fscs_generation_report.txt`, `streamlit.log`) before generating so
  no stale files survive across runs.

### Fixed

- Streamlit UI no longer crashes on a fresh checkout where `FSCS_*.txt`
  don't exist yet: the editor now loads from `fscs.json` only (legacy
  TXT fallback removed).

### Tests

- New: `tests/unit/test_fscs_generation_report.py` covering the kept /
  filtered / skipped matrix and report diagnostics.
- New: `tests/unit/test_pipeline_launch_ui.py::TestPortProbeShortCircuit`
  covering the 8501 reuse behaviour.
- Updated: `test_fscs_generator.py`, `test_pipeline_argparse.py`,
  `test_pipeline_launch_ui.py`, `test_fscs_ui_editor.py`,
  `test_phase_all.py`, `test_fscs_dual_write.py` to reflect the Phase
  1 / UI Save split.

---

## [1.0.0] — 2026-04-20

**First public release.** End-to-end AUTOSAR DID configuration generator targeting Bosch BSW projects (ESP / DPB / ESPCL / IPB / RBU). Three strictly sequential phases with `outputs/fscs/fscs.json` as the single authoritative data source.

### Core pipeline

- **Phase 1 — FSCS Generation** (`scripts/generate_fscs.py`)
  - Input: `inputs/*.json` (DID definitions with sessions, security levels, access, storage, sub-fields, ranges).
  - Output: authoritative `outputs/fscs/fscs.json` (Pydantic-validated) + human review renderings `FSCS_22.txt` / `FSCS_2E.txt` + review report.
  - Supports streamlit editor auto-launch via `--open-ui` / `--no-open-ui` / `DID_NO_OPEN_UI` env var.
- **Phase 2 — ARXML Generation** (`scripts/generate_arxml.py`)
  - Reads `fscs.json` exclusively. Produces `outputs/arxml/DID_Config.arxml` plus `validation_report.txt`.
  - Optional mirror into the real Bosch project tree (merged deduplicated by SHORT-NAME) when `output_mode=project` / `both`. Mirror target resolves from `paths.project_root` (auto-detected by `setup.py`, e.g. `Fe_Super`).
- **Phase 3 — Implementation Generation** (`scripts/generate_implementation.py`)
  - Reads `fscs.json` exclusively. Emits `RBAPLCUST_RDBI_*.c` / `RBAPLCUST_WDBI_*.c`, four header text fragments, and `pdm_entries.txt`.
  - Optional project-tree mirror with rolling backups (configurable retention, default 5).

### FSCS data source governance

- `outputs/fscs/fscs.json` is the **single authoritative source** for every downstream consumer (ARXML, Implementation, all three reviewers, Streamlit UI).
- Hard sequential gating: Phase 2 / Phase 3 / reviewers fail fast with a remediation hint pointing at Phase 1 if `fscs.json` is missing. No silent TXT fallback.
- Text artefacts `FSCS_22.txt` / `FSCS_2E.txt` are derived views — always regenerated from the same in-memory `FSCSDocument` so the `.json` and `.txt` twins stay in lock-step.

### DID Selection — Two-Gate Model

- New `used: bool = True` flag per service (`service_22.used`, `service_2e.used`) alongside the existing `supported`.
- A DID is "effective" (= included in FSCS text, ARXML, generated C, validation reports) only when **`supported AND used`**.
- Fully deselected DIDs (`used=False` on both services) surface in validation reports with status `DESELECTED`.
- `used` flags persist across Phase 1 regenerations when a prior `fscs.json` exists.

### Streamlit Editor & Auto-Launch (`scripts/ui/fscs_editor.py`)

- Phase 1 auto-launches the editor (unless `--no-open-ui`) as a background process in its own Windows `CREATE_NEW_PROCESS_GROUP` (or POSIX `start_new_session`); survives parent console closing without propagating CTRL+C.
- Child stdio is redirected to `outputs/fscs/streamlit.log` so operators can debug silent crashes; `--server.headless=true` is set to skip Streamlit's first-run interactive email prompt (which would otherwise block on stdin and terminate the child).
- "DID Selection" panel with per-service checkboxes and Select all / Clear all buttons.
- Per-DID edit forms for sessions, security levels, data_type, storage, size, rw_state, NVM item, value range, sub-fields.
- Atomic triple-write on save: `fscs.json` + `FSCS_22.txt` + `FSCS_2E.txt` (temp-file + `os.replace`).

### Storage-Position Canonicalization

Three canonical storage kinds + two input aliases, case-insensitive:

| Input | Canonical | NVM item | PDM entry | Phase 3 C skeleton |
|---|---|---|---|---|
| `EEPROM` / `NVM` | `EEPROM` | yes | yes | full NvM-backed read/write body |
| `RAM` | `RAM` | no | no | TODO skeleton tagged `(RAM storage)` |
| `ROM` / `Flash` | `ROM` | no | no | TODO skeleton tagged `(ROM/Flash storage)`, read-only (no write skeleton ever emitted) |

Unknown values fail validation with a clear Pydantic error pointing at the offending record.

### Reviewers

- **FSCS Review** (`scripts/review_fscs.py`) — business / configuration / consistency checks against the input JSON.
- **ARXML Review** (`scripts/review_arxml.py`) — container coverage, identifier mapping, data size, DidInfo ref, AR-Package layout, function hooks.
- **Implementation Review** (`scripts/review_impl.py`) — coverage, PDM consistency, feature-switch headers, range macros.
- All three reviewers read `fscs.json` and are identically affected by the `effective` gate (`DESELECTED` status is not an error).

### Tooling & developer experience

- `scripts/pipeline.py` — three-phase orchestrator with `--phase fscs|arxml|implementation|all`, `--validate`, `--output-mode`, `--dry-run`.
- `scripts/setup.py` — one-shot `config/project.json` bootstrap. Purely structural project-root / customer discovery: scans `<base_dir>/*` for the unique subdirectory containing `rb/as/<customer>/core/app/dcom/RBAPLCust` and inlines the discovered names into every `paths.*` template. Previously hard-coded the project-root as `Fe_Super`; now parametrised via `paths.project_root` + `--project-root` / `--customer-name` CLI hints, so deliveries that rename the top-level Bosch directory per release work without patching the script.
- `scripts/fscs_import.py` — legacy `FSCS_*.txt` → `fscs.json` migration CLI for pre-1.0 projects.
- `scripts/io_encoding.py` — shared `reconfigure_stdio_utf8()` helper wired into every CLI entry point so CJK (`did_name_zh`, review messages) renders correctly on Windows consoles / captured pipes.
- `run_pipeline.bat` — one-click Windows launcher (activates `Python31211` conda env, runs full pipeline).

### Test suite

- **355 tests**, split into `tests/unit/` (schema, builder, renderer, adapter, drift, UI model / editor / save, generators, reviewers, templating, naming, path resolution, package split, collision, guarded write, merge, CLI argparse) and `tests/integration/` (phase_all, output modes, backup rolling, ARXML project mirror, FSCS dual-write).
- Golden-file regression under `tests/golden/phase_all/` covers FSCS + ARXML + implementation artefacts.
- `--update-goldens` workflow for intentional output-format changes.

### Documentation

- `SKILL.md` — 293-line concise entry point with YAML frontmatter.
- `reference/` — nine focused documents (`architecture`, `arxml-structure`, `c-templates`, `commands`, `configuration`, `input-format`, `naming`, `review`, `testing`) loaded on demand.
- `reference/archive/REFACTOR_BRIEF.md` — archived historical refactoring brief.

### Release-hygiene

- `outputs/`, `.pytest_cache/`, `__pycache__/` gitignored and auto-regenerated.
- `config/project.json` **not** shipped — regenerated via `scripts/setup.py`; pipeline logs one-line INFO hint if absent, no spurious warnings.
- Sample input `inputs/GAC_DPT_EBB_did.json` retained so the pipeline works out-of-the-box.

---

## Conventions for future entries

Each new release adds a section at the top in this format:

```
## [X.Y.Z] — YYYY-MM-DD
### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security
```

Only include sections that apply; omit empty ones. Link the version to a git tag when the skill moves under version control.
