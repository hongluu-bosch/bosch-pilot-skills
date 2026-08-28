---
name: did-toolkit
version: 2.4.0
description: |
  Generic, project-agnostic AUTOSAR DID configuration generator for
  Bosch BSW projects (DPB / ESP / ESPCL / IPB / RBU / Common). The
  skill is **self-contained** — no customer-specific logic, no
  third-party runtime extractor dependency.

  Use when the user wants to:
  1. Ingest a schema-compliant `.DCOM_AI/DID_Toolkit_PRJ/inputs/*_did.json` into the
     authoritative `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json` (**Phase 1**).
     When the operator only has a questionnaire `.xlsx`, `--init-project`
     auto-triggers an `[AGENT ACTION] auto-extract` signal; the agent
     then writes a one-shot `.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py` that
     reads the workbook and emits the canonical JSON.
  2. Edit and re-import the FSCS CSV (`fscs_edit.xlsx`) to scope DIDs
     via `used_flag` / `Product_Type` (**`--phase xlsx-import`**).
  3. Generate ARXML (**Phase 2**) and C / headers / PDM (**Phase 3**)
     **directly into the Bosch project tree** with per-product
     fan-out and **skip-on-conflict** semantics — existing content
     always wins; reports stay under `.DCOM_AI/DID_Toolkit_PRJ/outputs/`.
  4. Push the FSCS to DOORS (**Phase 4**, opt-in).
  5. Review any generated artefact via the bundled reviewers.

  **Workspace under `.DCOM_AI/DID_Toolkit_PRJ/`.**
  `--init-project <project-root>` scaffolds the workspace inside
  `<project-root>/.DCOM_AI/DID_Toolkit_PRJ/` (`config/`,
  `inputs/`, `outputs/`, `scripts/`, `state/`); `.DCOM_AI/` is the
  generic AI-tooling umbrella and `DID_Toolkit_PRJ/` is this
  skill's namespace inside it, so the same container can later
  host parallel AI tools under sibling subdirectories.
  `paths.base_dir` points at the project container so Phase 2/3
  target the real Bosch tree.

  **`--init-project` is a resumable state machine.** Each invocation
  advances the workspace by exactly one step: (1) **FRESH** →
  scaffold `.DCOM_AI/DID_Toolkit_PRJ/` skeleton + starter templates, stop and ask
  for a `*_did.json`; (2) **FOLDERS_ONLY** → re-prompt; (3)
  **QUESTIONNAIRE_READY** → pick the questionnaire (numbered picker
  / `[Y/n]` / `--input` override), scan the Bosch tree, write
  `project.json`, stop for review; (4) **COMPLETE** → drift warning
  if the live Bosch tree diverged from `paths.pdm_file`, then
  auto-chain into Phase 1. Re-runs are safe by design.

  **Pipeline is gated.** No `--phase all`; each phase runs once and
  exits with `[AGENT STOP] End this turn now.` Phase 1 stops for
  xlsx review; xlsx-import stops with a used-DID preview + DOORS /
  ARXML / impl branch menu. **Phase 3 is the one exception** — it
  closes with `[AGENT TODO]` instead of `[AGENT STOP]` so the agent
  fills inline `TODO(agent)` blocks in non-EEPROM `.c` stubs in the
  same turn, then emits an `[AGENT REVIEW]` summary asking the
  operator to verify.

  Per-phase contracts, schema details, and full version history
  live in `reference/phase-{1,2,3,4}-*.md` + `CHANGELOG.md`; this
  SKILL.md is a dispatcher pointing at them.
---

# DID Toolkit

Generic, project-agnostic code generator for AUTOSAR Diagnostic Identifiers (DIDs) targeting Bosch BSW projects. Three strictly sequential phases plus an optional Phase 4 (DOORS), all anchored on `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json` as the single authoritative data source.

This SKILL.md is a **dispatcher** — it carries cross-phase contracts (governance / DID-selection model / output safety / agent stopping) and points at the per-phase `reference/*.md` files for everything else. Read those on demand when you actually run that phase.

## Python environment

The skill is **environment-agnostic**: every command below uses a bare `python ...` / `pip ...` and assumes a working Python on the operator's `PATH`. Required version is **Python 3.11 or 3.12**.

- Use whatever Python the host already provides (system Python, `venv`, `conda`, `uv`, ...). Don't substitute `py` / `python3` unless that's the only thing on `PATH` — pick whichever name resolves to a 3.11/3.12 interpreter and stick with it.
- If a user-level skill (e.g. `python-environment`) is configured on this machine, defer to it for activation; the did-toolkit itself makes no assumptions beyond "`python` runs the right interpreter".
- Required packages live in [`scripts/requirements.txt`](scripts/requirements.txt). Install once per environment.

```bash
python -m pip install -r scripts/requirements.txt   # one-time setup
python scripts/pipeline.py --version                # prints "did-toolkit X.Y.Z"; non-zero on version drift
python scripts/pipeline.py --validate               # validates config + first inputs/ candidate
```

## Quickstart

```bash
# 1. Scaffold a new workspace. --init-project is the sole entry
#    point — a resumable state machine where each invocation
#    advances the workspace by ONE step. Run it repeatedly until
#    Phase 1 fires.
#
#    Step 1 (FRESH workspace) → scaffolds .DCOM_AI/DID_Toolkit_PRJ/
#       skeleton + starter templates under
#       <project-root>/.DCOM_AI/DID_Toolkit_PRJ/, prints a
#       "drop a *_did.json under .DCOM_AI/DID_Toolkit_PRJ/inputs/" hint and
#       STOPS. No project.json yet.
#    Step 2 (questionnaire dropped) → re-run --init-project. The
#       state machine auto-picks the only *_did.json (or prompts
#       with a numbered picker / [Y/n] confirm), scans the Bosch
#       tree, writes config/project.json, records the chosen
#       basename at paths.input_did_json, and STOPS for review.
#    Step 3 (re-run again) → COMPLETE state auto-chains into
#       Phase 1 against the recorded questionnaire.
#
#    Drift in the Bosch tree between runs triggers a [WARN]
#    + [y/N] overwrite prompt (TTY) or [WARN] + keep (non-TTY).
cd /path/to/my-bosch-project
python /path/to/skill/scripts/pipeline.py --init-project

# After init the layout looks like this — Bosch tree untouched, all
# toolkit artefacts nested under .DCOM_AI/DID_Toolkit_PRJ/ (hidden via
# the .DCOM_AI/ dot-prefix the way .git/ is; DID_Toolkit_PRJ/ is this
# skill's namespace under the generic .DCOM_AI/ umbrella):
#   /path/to/my-bosch-project/
#   ├── Fe_Super/rb/as/...                    ← Bosch BSW tree (Phase 2/3 write here)
#   └── .DCOM_AI/
#       └── DID_Toolkit_PRJ/
#           ├── config/project.json
#           ├── inputs/                ← drop *_did.json here (.xlsx is
#           │                            auto-extracted by --init-project)
#           ├── outputs/               ← FSCS + reviewer / generation reports
#           ├── scripts/               ← operator-written extract_<customer>.py
#           └── state/                 ← doors_upload_state.json + future state

# 2. Phase 1 — build the FSCS, then STOP for xlsx review. A third
#    --init-project re-run on a fully-initialised workspace
#    auto-chains into Phase 1, so this command is optional if you
#    don't mind leaning on the auto-chain.
python scripts/pipeline.py --phase fscs

# 3. Open .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx in Excel/WPS, tweak
#    used_flag / Product_Type / behavior columns, then re-import.
#    xlsx-import rewrites fscs.json + FSCS_22.txt + FSCS_2E.txt and
#    STOPS with a used-DID preview.
python scripts/pipeline.py --phase xlsx-import

# 4. Choose one or both branches (independent and idempotent):
python scripts/pipeline.py --phase doors --no-upload --no-anchor   # smoke
python scripts/pipeline.py --phase doors --user-nt <NT>            # real DOORS push
python scripts/pipeline.py --phase arxml                           # Phase 2
python scripts/pipeline.py --phase implementation                  # Phase 3
```

> **First-time DOORS push on this machine:** before the `--phase doors`
> upload above, prime the OS keychain so future runs don't prompt for
> a password. Have the **operator** run this in their own terminal
> (never paste a password into the chat):
>
> ```bash
> python scripts/fscs/doors/doors_sync.py \
>     --user-nt <NT> --password <pwd> --save-credentials --no-upload
> ```
>
> Subsequent `--phase doors` runs only need `--user-nt <NT>` (or
> `$DOORS_USER_NT`) — the password is read from Windows Credential
> Manager / macOS Keychain / Linux Secret Service automatically. See
> [`reference/phase-4-doors.md`](reference/phase-4-doors.md) for the
> full credential-cache contract (4-level fallback, auth-failure
> auto-retry, `--forget-credentials`, `--no-keyring`).

After Phase 3, the controller prints an `[AGENT TODO]` summary listing `X fill / Y stub` targets. The agent must expand each *fill* DID's inline `TODO(agent)` block into real code in the **same turn**; *stub* DIDs (empty / default FSCS behaviour) keep their TODO block as a placeholder. See [§ Phase 3 fill-in](#phase-3-non-nvm-agent-fill-in) for the contract.

## The pipeline at a glance

| Phase | Script | Reads | Writes | Deep dive |
|---|---|---|---|---|
| **1 — FSCS** | (agent-written `extract_<customer>.py` if needed) → `scripts/generate_fscs.py` → `scripts/fscs/xlsx_edit.py` | `.DCOM_AI/DID_Toolkit_PRJ/inputs/*_did.json` + previous `fscs.json` (used-flag carry-forward) | `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/{fscs.json, fscs_edit.xlsx, fscs_review_report.txt, fscs_generation_report.txt}` | [`reference/phase-1-fscs.md`](reference/phase-1-fscs.md) |
| **xlsx edit** | `--phase xlsx-import` | `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx` (operator-edited) | `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/{fscs.json, FSCS_22.txt, FSCS_2E.txt}` (atomic rewrite) + refreshed review | [`reference/phase-1-fscs.md`](reference/phase-1-fscs.md) §4 |
| **2 — ARXML** | `scripts/generate_arxml.py` (driven by `pipeline.py::run_phase2` fan-out loop) | `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json` (work-set computed via `scripts/fscs/product_workset.py`) | **Bosch project tree** — `<paths.base_dir>/<paths.arxml_file>` merged per product (skip-on-conflict by `SHORT-NAME`). Reports under `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/`. Folder collapses ESPCL → ESP via the path alias; filename suffix tags Common→`SingleCANID`, others→`<PT>`. | [`reference/phase-2-arxml.md`](reference/phase-2-arxml.md) |
| **3 — Implementation** | `scripts/implementation/orchestrator.py` (driven by `pipeline.py::run_phase3` fan-out loop) | `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json` (same work-set as Phase 2) | **Bosch project tree** — `.c` / headers / PDM via `paths.c_output_subdir` / `paths.config_h` / `paths.config_settings_h` / `paths.config_elements_h` / `paths.pdm_file` (skip-on-conflict). Reports + `generation_report.txt` under `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/`. | [`reference/phase-3-implementation.md`](reference/phase-3-implementation.md) |
| **4 — DOORS** *(opt-in)* | `scripts/fscs/doors/doors_sync.py` | `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/{FSCS_22, FSCS_2E}.txt` (built by xlsx-import) + `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml` | `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_upload_{22, 2E, links}.xlsx` + state | [`reference/phase-4-doors.md`](reference/phase-4-doors.md) |

## Where to read what

A decision matrix for the agent — load the matching reference file only when actually working on that area.

| If you're doing... | Read this |
|---|---|
| Setting up a new workspace, switching projects, or wiring multi-product configs | [`reference/workspace-model.md`](reference/workspace-model.md) |
| Running Phase 1 / handling multi-input ambiguity / editing the xlsx workbook | [`reference/phase-1-fscs.md`](reference/phase-1-fscs.md) |
| Writing a one-off `extract_<customer>.py` to normalise a questionnaire `.xlsx` into the canonical `*_did.json` | [`reference/excel-ingestion.md`](reference/excel-ingestion.md) |
| Confirming the canonical input JSON schema | [`reference/input-format.md`](reference/input-format.md) |
| Running Phase 2 / debugging ARXML merge / using `product_type` filter | [`reference/phase-2-arxml.md`](reference/phase-2-arxml.md) |
| Running Phase 3 / understanding what's auto-generated vs what's left for the agent | [`reference/phase-3-implementation.md`](reference/phase-3-implementation.md) |
| **Filling in a `TODO(agent)` stub for a ROM/RAM DID** | [`reference/implementation-storage-positions.md`](reference/implementation-storage-positions.md) (the agent playbook) |
| Running Phase 4 (DOORS upload) | [`reference/phase-4-doors.md`](reference/phase-4-doors.md) |
| Understanding the Phase 2/3 project-tree write contract (skip-on-conflict, no backups) | [`reference/output-safety.md`](reference/output-safety.md) |
| Hitting an error or unexpected behaviour | [`reference/troubleshooting.md`](reference/troubleshooting.md) |
| Running any reviewer (`review_fscs.py` / `review_arxml.py` / `review_impl.py`) | [`reference/review.md`](reference/review.md) |
| Verifying a generated function / file / macro name | [`reference/naming.md`](reference/naming.md) |
| Looking up a CLI flag, default, or stand-alone CLI | [`reference/commands.md`](reference/commands.md) |
| Configuring `config/project.json` / DOORS mapping schema / path placeholders | [`reference/configuration.md`](reference/configuration.md) |
| Inspecting the data flow, module map, or Jinja2 templating contract | [`reference/architecture.md`](reference/architecture.md) |
| Working on the test suite or golden-file workflow | [`reference/testing.md`](reference/testing.md) |
| ARXML container / `DcmDspDidInfo` shared-container layout | [`reference/arxml-structure.md`](reference/arxml-structure.md) |
| C code template selection (RDBI/WDBI × RAM/EEPROM matrix) | [`reference/c-templates.md`](reference/c-templates.md) |

## Cross-phase contracts

These three contracts apply across every phase and are too important to defer to a reference file.

### A. FSCS data-source governance

`outputs/fscs/fscs.json` is the **single authoritative FSCS source**. Every downstream consumer reads the JSON — never the plaintext:

| Consumer | Module | Reads |
|---|---|---|
| Phase 2 ARXML | `scripts/generate_arxml.py` | `fscs.json` (via `scripts/fscs/adapter.py`) |
| Phase 3 Implementation | `scripts/implementation/orchestrator.py` | `fscs.json` (via adapter) |
| FSCS Review | `scripts/review_fscs.py` | `fscs.json` (via adapter) |
| ARXML Review | `scripts/review_arxml.py` | `fscs.json` (via `adapter.to_review_dicts`) |
| Implementation Review | `scripts/review_impl.py` | `fscs.json` (via `adapter.to_review_dicts`) |
| XLSX Export / Import | `scripts/fscs/xlsx_edit.py` | `fscs.json` directly (Pydantic `FSCSDocument`) |
| DOORS Payload | `scripts/fscs/doors/doors_sync.py` | `FSCS_22.txt` + `FSCS_2E.txt` (built by xlsx-import), split per-DID via `fscs_split.py` |

`fscs_edit.xlsx` is the **operator edit table** generated from `fscs.json` — drop-down validations on constrained columns, auto-fit widths, frozen header. `FSCS_22.txt` / `FSCS_2E.txt` are **read-only artefacts generated by xlsx-import** (not by Phase 1) and carry an explicit `# Generated from outputs/fscs/fscs.json -- do not edit this file by hand.` banner.

**Sequencing is mandatory.** Phase 2 / Phase 3 / standalone reviewers all hard-gate on `outputs/fscs/fscs.json` — missing → abort with remediation hint. No silent fallback to a stale `FSCS_22.txt`.

### B. DID selection (two-gate model)

Each DID in `fscs.json` carries **two independent per-service gates**. A DID is emitted to `FSCS_22.txt` / `FSCS_2E.txt` / ARXML / C only when both are `True` for that service; the JSON itself always keeps the full input set.

| Gate | Field (per service) | Owner | Meaning |
|---|---|---|---|
| **Support** | `service_XX.supported` | Derived from `rw_state` in Phase 1, then operator-editable via `service_XX_support` | Does the DID offer this UDS service? |
| **Selection** | `service_XX.used` *(default `True`)* | Operator, via `fscs_edit.xlsx` `used_flag` | Is this DID in scope for the current release? Flip to `FALSE` to exclude from `.txt` / ARXML / C without deleting it from `fscs.json`. |

Effective = `supported AND used`. Downstream consumers all call `FSCSServiceAccess.effective`. Generation validation reports may still mark deselected DIDs as `status: DESELECTED` for traceability.

For the multi-product `product_type` filter — Phase 2 / Phase 3 build for *every* product carried by a `used` DID, not for a single CLI-supplied target — see [`reference/phase-2-arxml.md`](reference/phase-2-arxml.md).

### C. Output safety (project tree only, skip-on-conflict)

Phase 2 / Phase 3 write **only** into the Bosch project tree (resolved via `paths.base_dir` + `paths.*` placeholders). The skill never overwrites existing content — every conflict is a skip, recorded in the per-phase `generation_report.txt`.

| Guard | What it does |
|---|---|
| **Hard-gate on `paths.base_dir`** | Phase 2 / Phase 3 abort early (exit 2) if `paths.base_dir` is missing, empty, or doesn't resolve to a real directory. No tree → nothing to write into → nothing to do. |
| **Skip-on-conflict** | ARXML merge skips already-present `SHORT-NAME` containers; header merge skips already-defined `#define`s; PDM merge skips already-listed entries; `.c` files are skipped wholesale if a same-named file exists. The pre-existing tree always wins. |
| **`--dry-run`** | Preview every project-tree write as `[DRY-RUN] Would <action>: <path>`. No filesystem mutations. Useful for "is the path template right?" checks before committing. |
| **Reports under `.DCOM_AI/DID_Toolkit_PRJ/outputs/`** | `arxml/<folder>/{validation_report,arxml_review_report}_*.txt`, `implementation/<PT>/{generation_report,review_report}.txt` — the audit trail for what was emitted / skipped / flagged for review. |

Full contract and merge details: [`reference/output-safety.md`](reference/output-safety.md).

### D. Agent turn-stopping contract

The pipeline is **gated**: every phase finishes by writing artefacts and emitting an `[AGENT STOP] End this turn now.` directive line. The agent driving the skill (Claude / Cursor / GPT / other host) **MUST treat each STOP as a turn boundary** — not as advisory narration.

The gates exist to surface operator-facing decisions (CSV scope, DOORS-vs-ARXML branch, per-product detection correctness, auto-extraction confirmation) that an auto-chain would otherwise hide. The agent must not paper over them by issuing the next `pipeline.py` invocation on the operator's behalf.

| Gate | Trigger output | Agent action this turn | Next-turn trigger |
|---|---|---|---|
| **Init — auto-extraction** | `[AGENT ACTION] auto-extract` when `inputs/` has workbook(s) but no JSON | The agent lists the workbook(s), writes a one-shot `extract_<customer>.py`, runs it to emit the canonical `*_did.json`, then re-invokes `--init-project`. **Stop the turn.** | Operator reviews the extractor or the JSON; re-runs `--init-project` to advance. |
| **Init — standard** | `[AGENT STOP]` at the end of `--init-project` | Surface the `[OK]` / `[CONFIRM]` / `[FYI]` block + the scaffolded layout in plain text. Ask the operator to (a) drop a questionnaire into `inputs/` if the pre-flight noted it was empty, and (b) confirm any `[CONFIRM]` auto-defaults (e.g. `IPB.config_settings_h` variant pick) are correct. **Stop the turn.** | Operator replies with the questionnaire placed / a `[CONFIRM]` override hand-edit / "go" / "继续" / similar. |
| **Phase 1 (`--phase fscs`)** | `[AGENT STOP]` after the `[STOP] Phase 1 complete` banner | Surface the absolute path to `outputs/fscs/fscs_edit.xlsx` + a short summary of the auto-review report (`fscs_review_report.txt`) and ASK the operator to edit `used_flag`, `Product_Type`, `behavior`, etc. Optionally point at the columns the review flagged. **Stop the turn.** | Operator replies "done" / "import" / "继续" / similar (or asks for clarification — answer it, **still** without auto-chaining). |
| **CSV import (`--phase xlsx-import`)** | `[AGENT STOP]` after the per-product work-set preview + the Option A / Option B menu | Surface the per-product DID counts and the two branch options (Phase 4 DOORS vs Phase 2 ARXML + Phase 3 impl). **Stop the turn.** | Operator picks one or both options ("doors only" / "arxml" / "都跑" / etc.). |
| **Phase 4 DOORS / Phase 2 ARXML** | Phase-specific success banner | Terminal phases — no further STOP. | n/a |
| **Phase 3 impl** | `[AGENT TODO] X fill / Y stub` summary | Phase 3 is **continuous-flow**. The controller emits an `[AGENT TODO]` (not `[AGENT STOP]`); the agent immediately expands each *fill* DID's inline `TODO(agent)` block into real code in the **same turn**, leaving *stub* DIDs in place. See [§ Phase 3 fill-in](#phase-3-non-nvm-agent-fill-in). | n/a |

**Rules the agent must follow at every STOP:**

1. **Plain-text presentation, not `AskQuestion`.** Mirror the existing multi-questionnaire / multi-config contracts ([`reference/troubleshooting.md`](reference/troubleshooting.md)) — list the choices conversationally so the operator can reply naturally; the formal-question tool would over-constrain decisions that are deliberately open (e.g. "Option A and Option B" — the operator might pick both).
2. **One phase per agent turn.** Even when the operator says "do all of it", run the *next* phase only and stop again at its `[AGENT STOP]`. The gates are how the operator catches their own mistakes; collapsing them defeats the design.
3. **Never silently retry past a STOP.** If a phase fails (non-zero exit) the agent should surface the error and ask — never auto-rerun.
4. **Quote the `[STOP]` block verbatim.** The footer carries the actionable file paths and command snippets the operator needs; don't paraphrase or shorten them.
5. **Operator override is always honoured.** If the operator says "just run everything end-to-end, no questions", run each phase in sequence in **separate turns** with brief acknowledgements between them. The CLI hard-gates each phase independently, so the operator stays in control regardless of how aggressive the agent wants to be.

`[AGENT STOP]` is the only marker the agent is required to recognise; the human-facing `[STOP]` banner above it is for the operator. If both are present, the agent's contract is keyed on `[AGENT STOP]`.

## Phase 3 non-NVM agent fill-in

Pulled to the top because it requires unique agent action that can't happen inside the generator. Full detail in [`reference/phase-3-implementation.md`](reference/phase-3-implementation.md) and the playbook in [`reference/implementation-storage-positions.md`](reference/implementation-storage-positions.md).

Phase 3 ships a fully-generated body **only for `EEPROM`** (NVM-backed) DIDs and **auto-generated bodies for `ROM`/`FLASH`** (HardCode) DIDs whose FSCS `behavior` contains a valid `HardCode:` block (v2.4.0+). `RAM` (internal-interface) DIDs land a `.c` stub returning `E_NOT_OK` plus an **inline `TODO(agent)` block** carrying the DID identity, storage classification verdict, RAM sub-pattern guess, and the FSCS behaviour text for both services.

```bash
# 1. Run Phase 3. Generator writes the framework into the Bosch tree
#    (skip-on-conflict per product) and lists every fill / stub
#    target. Phase 3 closes with [AGENT TODO] — the agent continues
#    filling non-empty behaviours in the same turn.
python scripts/pipeline.py --phase implementation
# Footer example:
#   [AGENT TODO] Phase 3 framework done. 12 fill / 3 stub.
#     Fill targets (expand inline TODO this turn):
#       - DPB/c_code/RBAPLCUST_RDBI_VinRead.c   (EEPROM, $22)
#       - DPB/c_code/RBAPLCUST_RDBI_OdoRead.c   (RAM    , $22)
#       ...
#     Stub targets (behaviour empty — leave TODO in place):
#       - DPB/c_code/RBAPLCUST_RDBI_TBD1.c
#       ...

# 2. The agent reads each fill target's TODO(agent) block (it carries
#    DID identity, storage class, RAM sub-pattern guess, FSCS
#    behaviour text, AND the seven curated context-lookup paths) plus
#    the playbook section in
#    reference/implementation-storage-positions.md, then replaces
#    the TODO block with the real body in the same turn — everything
#    the agent needs is inline.
#
#    Three non-skippable contracts while filling:
#      a) Curated search first — look up signal / typedef / RBFS_*
#         context inside the seven paths in playbook §5.1 before
#         widening the grep. Order: cnms_core/core → customer/core →
#         <customer>/<product>/{aswif,dcompr,cswpr} → <customer>/csw.
#      b) Stop & ASK before any project-tree edit beyond the
#         generated .c (.bcfg / customer .h / RBFS_* switches) when
#         the change touches an existing operator-set value, a
#         customer-shipped header, or an unrelated DID's enablement
#         (playbook §5.2). Quote path + line range + one-line diff
#         and [AGENT STOP].
#      c) Close with the [AGENT REVIEW] summary (filled / stub /
#         project-tree edits / operator decisions captured), then
#         stop and ask the operator to verify (playbook §5.3).

# 3. The operator re-runs Phase 3 only if FSCS behaviour text was
#    updated upstream; skip-on-conflict keeps every agent-filled .c
#    untouched, so re-runs are idempotent.
```

Stub targets stay loud at runtime (still `E_NOT_OK`) so a half-finished release lights up on the bench. The TODO block carries everything the next agent / reviewer needs — never delete it without filling the body.

## Common commands

The most-used five. For the full table (every flag, every default, every stand-alone reviewer CLI), see [`reference/commands.md`](reference/commands.md).

| Command | Purpose |
|---|---|
| `python scripts/pipeline.py --phase fscs` | **Phase 1 (default)** — regen `fscs.json`, preserve `used` flags, auto-review, export `fscs_edit.xlsx`; STOPS for operator xlsx review |
| `python scripts/pipeline.py --phase xlsx-import` | Validate `fscs_edit.xlsx`, atomically rewrite `fscs.json` + `FSCS_*.txt`, refresh review; STOPS with a used-DID preview + branch menu |
| `python scripts/pipeline.py --phase arxml` | Phase 2 only — per-product ARXML fan-out from `fscs.json` (v1.21+) |
| `python scripts/pipeline.py --phase implementation` | Phase 3 only — per-product C / headers / PDM fan-out; continuous-flow `[AGENT TODO]` after framework |
| `python scripts/pipeline.py --phase doors` | Phase 4 (opt-in) — build / upload DOORS workbook from `FSCS_*.txt` |
| `python scripts/pipeline.py --list-inputs` / `--list-configs` | Two agent-enumeration entry points (sorted, exit 0 on empty). See [`reference/troubleshooting.md`](reference/troubleshooting.md) for the multi-* selection contracts |
| `python scripts/pipeline.py --version` | Print `did-toolkit X.Y.Z` and exit non-zero if the three version files disagree |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Invalid arguments / `--init-project` collision |
| 2 | Missing configuration |
| 3 | Invalid input file / multi-input ambiguity (no `--input`) |
| 4 | Generation error / multi-config ambiguity (no `--config`, non-TTY) |
| 5 | File I/O error |

## Best practices

1. **Version control** — commit `.DCOM_AI/DID_Toolkit_PRJ/inputs/*_did.json`, `.DCOM_AI/DID_Toolkit_PRJ/config/project.json`, and (if you wrote one) `.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py`. The questionnaire `.xlsx` lives outside the workspace as the operator's source of truth; the extractor adapter is what gets reviewed. Do **not** commit `.DCOM_AI/DID_Toolkit_PRJ/outputs/` — fully regenerable.
2. **Input management** — keep the questionnaire `.xlsx` as the single source of truth outside the workspace; the extractor script + `*_did.json` it produces are regenerable. Never edit `outputs/fscs/fscs.json` or `inputs/<customer>_did.json` by hand. Use meaningful English DID names; Chinese names are reference-only. Validate with `--validate` before generation.
3. **Dry-run before merging** — Phase 2 / Phase 3 write directly into the Bosch tree. Run with `--dry-run` first to confirm the path templates resolve to the right files; the actual merge then proceeds with skip-on-conflict so existing content can't be clobbered.
4. **Multi-project setup** — use `--init-project` per project; keep `.DCOM_AI/DID_Toolkit_PRJ/config/project.json` version-controlled per workspace.
5. **Phase 3 fill-in discipline** — expand the inline `TODO(agent)` block in the same turn Phase 3 emits `[AGENT TODO]`. Edit the FSCS `behavior` text upstream and re-run if the source description is wrong; skip-on-conflict keeps agent-filled `.c` files intact across re-runs. Don't bypass the `TODO(agent)` markers — they're how the next reviewer / CI counts unfinished work.
6. **DOORS credentials (Phase 4) — never via chat.** Never ask the operator to paste the DOORS password into the chat. Tell them to run `python scripts/fscs/doors/doors_sync.py --user-nt <NT> --password <pwd> --save-credentials --no-upload` themselves in their terminal once; from then on `--phase doors` reads the password from the OS keychain (Windows Credential Manager / macOS Keychain / Linux Secret Service) and runs prompt-free. Never run `--save-credentials` on the operator's behalf with a password they typed earlier in the conversation — that path leaks the secret into chat history. If the upload fails with `Unauthorized` / `认证失败` / `401`, `doors_sync.py` does ONE auto-retry (prompts for a fresh password and refreshes the keychain on success); never loop or burn more attempts — most enterprise DOORS instances delegate auth to LDAP / AD which lock the NT account after 3-5 wrong tries.

## Version

The canonical version lives in three places that must stay in sync:

- `VERSION` (one-line plaintext — source of truth read by scripts / CI).
- `SKILL.md` frontmatter `version:` (what skill hosts pick up).
- Top entry of [`CHANGELOG.md`](CHANGELOG.md) (`## [X.Y.Z]` header).

Run `python scripts/pipeline.py --version` before any release — it prints `did-toolkit X.Y.Z` and exits non-zero if the three files disagree. Full feature history and `MAJOR` / `MINOR` / `PATCH` policy: [`CHANGELOG.md`](CHANGELOG.md).
