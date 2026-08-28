# Commands Reference

Detailed CLI / command-schema reference for every entry point the skill exposes. The agent should read this file only when it needs to know full parameter sets, defaults, outputs, or dependencies. The top-level `SKILL.md` carries a one-line summary for each command.

All commands assume a Python 3.11 / 3.12 interpreter is on `PATH` (system Python, `venv`, `conda`, `uv`, ... — the skill makes no assumption beyond that). If the host has a user-level Python-environment skill configured, defer to it for activation; otherwise just run `python ...` directly. Install dependencies once per environment with `python -m pip install -r scripts/requirements.txt`.

## Pipeline overview (gated, no auto-chain)

There is no ``--phase all`` — the pipeline is a chain of
independent phases joined by explicit STOP gates. The operator
runs one ``--phase <name>`` at a time and re-invokes the CLI
after reviewing the intermediate artefacts.

```text
+-------------------+      +---------------------+      +-------------------------+
| --phase fscs      |  →   | (operator edits     |  →   | --phase xlsx-import      |
| Phase 1: builds   | STOP | outputs/fscs/       | STOP | rewrites fscs.json +    |
| fscs.json +       |      | fscs_edit.xlsx:      |      | FSCS_22.txt /           |
| fscs_edit.xlsx     |      | used_flag,          |      | FSCS_2E.txt and prints  |
|                   |      | Product_Type, …)    |      | the used-DID preview    |
+-------------------+      +---------------------+      +-------------------------+
                                                                       |
                                                                       v
                          +----------------------------------------+
                          | Operator chooses ONE OR BOTH branches: |
                          +----------------------------------------+
                            |                                  |
                            v                                  v
                     +-----------------+              +-------------------+
                     | --phase doors   |              | --phase arxml     |
                     | (Phase 4 DOORS) |              | --phase implement.|
                     +-----------------+              +-------------------+
```

Each phase command is documented in detail below.

```yaml
cmd: pipeline_default
command: python scripts/pipeline.py [--input {input}]
description: |
  Equivalent to `--phase fscs` (Phase 1). The default phase is
  `fscs`, so an unflagged `pipeline.py` invocation builds the
  FSCS and stops at the first gate.
```

## Phase 1: FSCS Generation

```yaml
cmd: generate_fscs
command: python scripts/pipeline.py [--input {input}] --phase fscs [--reset-used] [--no-review]
description: |
  Ingest the diagnostic questionnaire JSON (`*_did.json` only —
  the skill ships no built-in workbook parser; write a one-shot
  .DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py adapter if you only have
  a workbook), build outputs/fscs/fscs.json, auto-run the FSCS
  content review so fscs_review_report.txt stays in sync with the
  just-written JSON, and export outputs/fscs/fscs_edit.xlsx for
  spreadsheet-based operator edits. Phase 1 does not write
  FSCS_*.txt (those land on xlsx-import).
parameters:
  input:
    type: string
    required: false
    description: |
      Path to the canonical `*_did.json` questionnaire. If
      omitted, auto-detects the single `*_did.json` in
      `.DCOM_AI/DID_Toolkit_PRJ/inputs/`; multiple candidates trigger the multi-
      input contract (`--list-inputs` + interactive selection).
      `.xlsx` is never accepted directly — convert it via a
      one-shot agent-written extractor first. The input path is
      forwarded to the auto-review so the questionnaire-vs-FSCS
      consistency check runs.
  reset_used:
    type: bool
    required: false
    default: false
    description: |
      Discard every preserved `used` flag from the previous fscs.json;
      new build starts with used_22 = used_2e = True for every DID.
      Without this flag, Phase 1 carries the operator's last CSV
      selections forward.
  no_review:
    type: bool
    required: false
    default: false
    description: |
      v1.2: skip the Phase 1 auto-review step. fscs.json + generation
      report and fscs_edit.xlsx still land as usual, but
      fscs_review_report.txt is not refreshed. Equivalent to
      DID_NO_REVIEW=1. The CSV import path always auto-reviews
      regardless of this flag; run `--phase review`
      later to catch up the report without regenerating.
  DID_NO_REVIEW (env):
    type: string
    required: false
    description: |
      v1.2: if set to any non-empty value (accepting 1 / true / yes /
      on, case-insensitive), disables the Phase 1 auto-review.
      Equivalent to --no-review. Intended for CI / headless loops
      that produce fscs.json as an intermediate artefact.
outputs:
  - outputs/fscs/fscs.json                      # authoritative source; carries used_22/used_2e per DID
  - outputs/fscs/fscs_edit.xlsx                  # spreadsheet edit table generated from fscs.json
  - outputs/fscs/fscs_generation_report.txt     # ingestion report: kept / filtered / schema-skipped DIDs
  - outputs/fscs/fscs_review_report.txt         # v1.2 auto-review output (absent if --no-review / DID_NO_REVIEW=1)
# Note: FSCS_22.txt / FSCS_2E.txt are NOT produced by Phase 1 -- they
#       land on `--phase xlsx-import` after the operator edits fscs_edit.xlsx.
per_record_skip: |
  DIDs that fail Pydantic validation are skipped individually and logged
  in fscs_generation_report.txt with their did_hex and the failing
  field(s). Valid siblings still make it into fscs.json.
selection_preservation: |
  Re-running --phase fscs loads the previous outputs/fscs/fscs.json and
  carries each DID's service_22.used / service_2e.used forward. DIDs
  newly introduced by the input default to used=True. Console output
  reports EFFECTIVE counts (supported AND used) so the numbers match
  what the CSV import will render.
auto_review: |
  After fscs.json lands, pipeline.py calls review_fscs.run_review with
  the input JSON attached so all three review checks (business,
  compliance, consistency) run. Failures are logged as WARNING and
  swallowed -- review is advisory and must not reverse a successful
  Phase 1. See reference/review.md for the three review trigger paths.
```

## Phase 1 sibling commands

```yaml
cmd: csv_import
command: python scripts/pipeline.py --phase xlsx-import [--csv {csv_path}] [--input {input}]
description: |
  v1.7: apply the operator-edited spreadsheet table back to the
  authoritative FSCS document. Defaults to outputs/fscs/fscs_edit.xlsx.
  The import rejects added/deleted/duplicate DID rows, validates the
  resulting FSCSDocument, atomically writes fscs.json + FSCS_22.txt +
  FSCS_2E.txt, normalizes the CSV, and refreshes fscs_review_report.txt.
parameters:
  csv_path:
    type: string
    required: false
    default: outputs/fscs/fscs_edit.xlsx
    description: Path to the edited CSV table. Relative paths resolve from the toolkit root.
  input:
    type: string
    required: false
    description: |
      Optional original questionnaire (.xlsx / .xlsm / legacy .json)
      used only for the review consistency check (see review_fscs).
      Defaults to the same auto-discovery rule as Phase 1.
outputs:
  - outputs/fscs/fscs.json
  - outputs/fscs/fscs_edit.xlsx
  - outputs/fscs/FSCS_22.txt
  - outputs/fscs/FSCS_2E.txt
  - outputs/fscs/fscs_review_report.txt
```

```yaml
cmd: run_review
command: python scripts/pipeline.py --phase review [--input {input}]
description: |
  v1.7: ad-hoc re-run of the FSCS content review against the existing
  fscs.json, without regeneration. Use
  after CSV import, tweaking a review rule, or in CI after
  pulling a delivery. Pass --input to additionally run the
  JSON-vs-FSCS consistency check; omit it and the reviewer skips that
  single check (business and compliance still run). Phase 1 and the
  CSV import path already auto-review, so this is the "manual refresh"
  entry point.
outputs:
  - outputs/fscs/fscs_review_report.txt
```

```yaml
cmd: doors
command: python scripts/pipeline.py --phase doors [--no-upload] [--user-nt {nt}] [--force-mode insert|update] [--force-no-skip] [--save-credentials | --forget-credentials | --no-keyring]
description: |
  v1.7: build and optionally upload a DOORS-native workbook from
  outputs/fscs/FSCS_22.txt and outputs/fscs/FSCS_2E.txt. The workbook is
  written through the sibling doors-toolkit xlsxwriter path and linted with
  lint-doors-xlsx before upload. Run xlsx-import first so the FSCS text files
  reflect the edited CSV.

  v2.3.0: 4-level password fallback (--password > $DOORS_PWD > OS keychain
  > interactive prompt) plus three admin flags for the OS keychain
  (Windows Credential Manager / macOS Keychain / Linux Secret Service).
  See reference/phase-4-doors.md "Credential cache" for the full contract.
parameters:
  no_upload:
    type: bool
    required: false
    default: false
    description: Build and lint outputs/doors_upload.xlsx without uploading.
  user_nt:
    type: string
    required: false
    description: |
      DOORS NT username. Required for real upload. Falls back to
      $DOORS_USER_NT (since 2.3.0). Omit for --no-upload (build-only)
      or --plan-only.
  password:
    type: string
    required: false
    description: |
      DOORS password. Resolution order: --password > $DOORS_PWD >
      OS keychain (service="did-toolkit:doors", user=<NT>) >
      interactive prompt. Prefer the keychain (--save-credentials) or
      $DOORS_PWD over --password to avoid shell history exposure.
  save_credentials:
    type: bool
    required: false
    default: false
    description: |
      Persist (user_nt, password) in the OS keychain. Combine with
      --no-upload to prime the cache without doing any upload (cold-
      start workflow on a new machine; runs even when mapping yaml /
      FSCS / state don't exist yet).
  forget_credentials:
    type: bool
    required: false
    default: false
    description: |
      Delete the keychain entry for --user-nt and exit. Self-contained
      admin op: does not build, does not upload, does not fetch.
      No-op if no entry exists (returns 0 — benign success).
  no_keyring:
    type: bool
    required: false
    default: false
    description: |
      Bypass the OS keychain entirely (do not read, do not write).
      Useful for CI, debugging, or hosts with no Secret Service backend.
  force_mode:
    type: enum
    values: [insert, update]
    required: false
    description: Override state-based insert/update decision.
outputs:
  - outputs/doors_upload_spec.json
  - outputs/doors_upload.xlsx
  - outputs/doors_payload_report.txt
  - state/doors_upload_state.json   # only after successful upload
```

## Phase 2: ARXML Generation

```yaml
cmd: generate_arxml
command: python scripts/pipeline.py --phase arxml [--dry-run]
description: |
  Generate AUTOSAR ARXML configuration and merge into the Bosch tree
  (skip-on-conflict by SHORT-NAME).

  Phase 2 writes only into the Bosch tree (resolved via paths.base_dir
  + paths.arxml_file); reports stay under .DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/.
  The merge is non-destructive, so there is no rolling backup.
  Phase 2 loads fscs.json, computes the per-run product work-set,
  and iterates the generator once per product. Empty work-set is
  warn-and-skip (Phase 4 / DOORS still runs).
parameters:
  fscs_json:
    type: string
    required: true
    default: .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json
    description: |
      Authoritative FSCS source. Phase 2 is hard-gated on this file: if
      fscs.json is missing, Phase 2 aborts with a remediation hint
      pointing at Phase 1. The Service 22 / Service 2E .txt views are
      human-review artifacts only, never consumed at runtime.
  dry_run:
    type: bool
    required: false
    default: false
    description: |
      Preview every per-product project-tree ARXML write as
      "[DRY-RUN] Would <action>: <path>". No filesystem mutations.
outputs:
  - "<base_dir>/<paths.arxml_file expansion>           # one per product in the work-set"
  - ".DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/validation_report_<suffix>.txt"
  - ".DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/arxml_review_report_<suffix>.txt"
  - ".DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/generation_report.txt"
dependencies:
  - generate_fscs
```

## Phase 3: Implementation Generation

```yaml
cmd: generate_implementation
command: python scripts/pipeline.py --phase implementation [--dry-run]
description: |
  Generate C code, headers, and PDM entries straight into the Bosch
  tree (skip-on-conflict). Closes with [AGENT TODO] X fill / Y stub.

  Phase 3 writes only into the Bosch tree (paths.c_output_subdir /
  config_h / config_elements_h / config_settings_h / pdm_file); .c
  uses skip-if-exists at the file level, headers/PDM use entry-level
  skip-on-conflict. Nothing is ever overwritten, so there is no
  rolling backup. Reports stay under
  .DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/.
  Every non-EEPROM stub carries an inline TODO(agent) block with
  identity, storage classification, RAM sub-pattern guess, and FSCS
  behaviour text. No [AGENT STOP] after framework — agent fills
  non-empty behaviours in the same turn (continuous flow).
  The per-run work-set is computed from fscs.json (no
  --product-type flag).
parameters:
  config:
    type: string
    default: .DCOM_AI/DID_Toolkit_PRJ/config/project.json
    description: Path to project configuration
  dry_run:
    type: bool
    required: false
    default: false
    description: |
      Preview every project-tree write as "[DRY-RUN] Would <action>: <path>".
      No filesystem mutations. Reports still write under .DCOM_AI/DID_Toolkit_PRJ/outputs/.
outputs:
  - "<base_dir>/<paths.c_output_subdir expansion>/RBAPLCUST_RDBI_*.c    # per product"
  - "<base_dir>/<paths.c_output_subdir expansion>/RBAPLCUST_WDBI_*.c    # per product (RW DIDs)"
  - "<base_dir>/<paths.config_h expansion>"
  - "<base_dir>/<paths.config_elements_h expansion>"
  - "<base_dir>/<paths.config_settings_h expansion>"
  - "<base_dir>/<paths.pdm_file expansion>"
  - .DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/generation_report.txt
  - .DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/validation_report.txt
  - .DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/impl_review_report.txt
dependencies:
  - generate_fscs
```

## Project Setup

```yaml
cmd: setup_project
command: python scripts/pipeline.py --init-project [--name {name}] [--customer-name {customer}] [--init-project-root {root}] [--input {basename}]
description: |
  `--init-project` is a RESUMABLE STATE MACHINE. Each invocation
  classifies the workspace and advances it by exactly ONE step.
  Call the same command repeatedly until Phase 1 fires.

  States and per-state behaviour:

  * FRESH (no .DCOM_AI/DID_Toolkit_PRJ/ at all): scaffolds the workspace skeleton
    (config/ inputs/ outputs/ scripts/ state/) + copies starter
    templates (extract_customer.py.template, doors_mapping.yaml.template)
    into the workspace, prints "drop a *_did.json under .DCOM_AI/DID_Toolkit_PRJ/inputs/"
    hint, exits 0 with [AGENT STOP]. No project.json is written.
  * FOLDERS_ONLY (skeleton present, no *_did.json yet): same
    hint as FRESH (idempotent). Exits 0 with [AGENT STOP].
  * QUESTIONNAIRE_READY (at least one *_did.json present, no
    project.json yet): resolves WHICH questionnaire to use
    (resolution order: --input <basename>, then
    paths.input_did_json from a leftover config if any, then
    auto-pick when only one candidate, then [Y/n] confirm in TTY,
    then numbered picker for multi-candidate TTY,
    _QuestionnaireAmbiguous in non-TTY). Scans the Bosch tree
    once, builds the paths.* literals + paths.per_product
    overrides, and writes config/project.json with
    paths.input_did_json set to the chosen basename. Exits 0 with
    [AGENT STOP] asking the operator whether to advance into
    Phase 1.
  * COMPLETE (everything in place): runs an OPTIONAL drift check
    by comparing the live (project_root, customer) scan against
    the segments baked into the recorded paths.pdm_file. If drift
    is detected: TTY prompts "Overwrite project.json with the
    detected tree? [y/N]" and rewrites on `y`; non-TTY emits a
    [WARN] line and keeps the existing config. Then unconditionally
    chains into PipelineController.run_phase1(<recorded questionnaire>),
    returning 0 on success or 1 on Phase 1 failure.

  Bosch-tree auto-detection (still applies at the
  QUESTIONNAIRE_READY transition): matches
  <base_dir>/<X>/rb/as/<Y>/core/app/dcom/RBAPLCust and demands a
  unique hit; pass --init-project-root / --customer-name to pin
  them when the workspace holds multiple trees or customers.

  `--init-project` auto-populates `paths.per_product` by walking
  the live Bosch tree to detect known asymmetries:
  emits [INFO] lines when a path is missing and was auto-skipped
  with `null` (typical: ESPCL.arxml_file, Common.config_settings_h),
  [CONFIRM] lines when a variant-suffixed file was auto-defaulted
  (typical: IPB.config_settings_h → "..._IPB.h" with alternates
  listed), and [FYI] lines for tree extras not covered by the
  standard template (Common/Dcm_..._EcucValues.arxml no-suffix,
  IPB/...IPB11.arxml, src/IPB11/, src/XPB/). Hand-edit
  config/project.json::paths.per_product to override.
parameters:
  name:
    type: string
    required: true
    description: Project name
  base_dir:
    type: string
    default: <workspace root (five parents above setup.py)>
    description: |
      Workspace root to scan for the Bosch tree. Defaults to the directory
      that contains the skill checkout, e.g. C:/SharCC/CNMS/CNMS_<name>.
  project_root:
    type: string
    required: false
    description: |
      Top-level Bosch tree directory name (often "Fe_Super", but project-
      specific). Skip to auto-detect; required if >1 candidate under base_dir.
  customer_name:
    type: string
    required: false
    description: |
      BSW customer segment (e.g. "rbcn"). Skip to auto-detect; required if
      the resolved <project_root>/rb/as/ contains >1 customer.
  input:
    type: string
    required: false
    description: |
      Pre-select a questionnaire under .DCOM_AI/DID_Toolkit_PRJ/inputs/ when
      multiple *_did.json are present. Accepts either the bare
      basename ("foo_did.json") or a path-like form
      ("inputs/foo_did.json", ".DCOM_AI/DID_Toolkit_PRJ/inputs/foo_did.json"); the
      state machine matches on the basename either way. Required
      in non-TTY mode when more than one questionnaire is staged
      (otherwise --init-project exits 3 with a candidates listing).
outputs:
  - .DCOM_AI/DID_Toolkit_PRJ/config/project.json (written at the QUESTIONNAIRE_READY transition)
  - .DCOM_AI/DID_Toolkit_PRJ/scripts/extract_customer.py.template (starter; FRESH/FOLDERS_ONLY)
  - .DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml.template (starter; FRESH/FOLDERS_ONLY)
  - .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/* (only at the COMPLETE auto-chain into Phase 1)
exit_codes:
  - "0: state advanced (or no-op for FOLDERS_ONLY re-runs)"
  - "1: --init-project / --phase mutually exclusive, OR Phase 1 returned False from the COMPLETE auto-chain"
  - "2: interactive abort (EOFError / Ctrl-D), questionnaire picker FileNotFoundError, or unreadable project.json"
  - "3: QUESTIONNAIRE_READY/COMPLETE picker found multiple *_did.json in non-TTY mode without --input"
  - "4: QUESTIONNAIRE_READY needs --name and no Bosch tree was detected (fail-loud guard)"
```

## Validate Configuration

```yaml
cmd: validate
command: python scripts/pipeline.py --validate
description: Validate project configuration and input files
outputs:
  - Console validation report
```

## FSCS CSV Edit Table

Phase 1 exports this table by default. It is the only operator editing surface in v1.7.

```yaml
cmd: csv-edit
command: python scripts/pipeline.py --phase fscs
description: >
  Exports outputs/fscs/fscs_edit.xlsx from the authoritative fscs.json.
  Operators edit the CSV in Excel/WPS, then run --phase xlsx-import.
  Use used_flag to control downstream DID participation and
  service_22_support / service_2e_support to describe supported services.
  Edit service_22_behavior / service_2e_behavior to control the Behavior
  block rendered after Value Range in FSCS_22.txt / FSCS_2E.txt.
  Keep one row per DID; added/deleted/duplicate rows are rejected.
inputs:
  - outputs/fscs/fscs.json
outputs:
  - outputs/fscs/fscs_edit.xlsx
notes:
  - `service_22_support` / `service_2e_support` are editable final service-support flags.
  - `service_22_behavior` / `service_2e_behavior` are editable side-specific
    FSCS Behavior text fields. Multiline CSV cells are preserved.
  - Complex value-range, sub-field, and free-text data are hidden from CSV and preserved in fscs.json.
  - Re-run Phase 2 / Phase 3 after xlsx-import to propagate the new selection
    into ARXML and generated C. DIDs fully deselected (used=False on both
    services) show up as status=DESELECTED in validation_report.txt and
    are omitted from the generated ARXML / C.
```

## Independent Review Runs

When Phase 1/2/3 have already produced their artefacts, each reviewer can be re-run standalone:

```bash
# FSCS Review — reads authoritative fscs.json, compares against the
# customer-provided *_did.json the JSON was generated from.
python scripts/review_fscs.py \
    --fscs-json .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json \
    --input-json .DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json \
    --output .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_review_report.txt

# ARXML Review — reads fscs.json + the generated ARXML in the Bosch tree.
# There is no local outputs/arxml/<PT>/DID_Config.arxml mirror;
# point --arxml at the actual Bosch path resolved from paths.arxml_file.
python scripts/review_arxml.py \
    --arxml <base_dir>/cfg/DPB/Dcm_CusDiag_Services_EcucValues_DPB.arxml \
    --fscs-json .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json \
    --output .DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/DPB/arxml_review_report_DPB.txt

# Implementation Review — reads fscs.json + the generated sources in the
# Bosch tree. There is no local outputs/implementation/<PT>/ source
# mirror; --impl-dir points at the actual project tree location.
python scripts/review_impl.py \
    --impl-dir <base_dir>/<paths.c_output_subdir>/DPB \
    --fscs-json .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json \
    --output .DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/DPB/impl_review_report.txt
```

All three reviewers hard-fail if `--fscs-json` does not exist and print a remediation hint pointing at Phase 1.

## Console Encoding (CJK Output)

Every CLI entry point calls `scripts/io_encoding.reconfigure_stdio_utf8()` at import time, which flips `sys.stdout` / `sys.stderr` to UTF-8 with `errors='replace'`. This is what makes `did_name_zh` ("车辆配置码", "工厂模式", …) and the Chinese review messages ("业务不合规", "注: 问题不影响后续Phase执行") render as proper glyphs instead of `\u8f66\u8f86...` escape noise on Windows PowerShell / cmd.exe / captured-output CI runners.

* **Do not remove the `reconfigure_stdio_utf8()` calls** from `pipeline.py`, the `generate_*.py`, `review_*.py`, or `fscs_import.py`. The call is idempotent and fail-soft, so re-running via `pipeline.py` (which re-imports child generators) pays at most two cheap no-op reconfigures.
* **File writes are not affected.** `fscs.json`, `FSCS_*.txt`, ARXML, generated C, PDM, and all review reports are written with explicit `encoding='utf-8'`, so their on-disk content was always correct -- only terminal display was broken.

