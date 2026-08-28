---
name: 19service-toolkit
version: 0.1.0
description: |
  Generic, project-agnostic AUTOSAR UDS Service 0x19 (Read DTC Information)
  configuration generator for Bosch BSW projects. Currently focused on
  subfunction 0x04 (reportDTCSnapshotRecordByDTCNumber / Freeze Frame).

  Use when the user wants to:
  1. Extract freeze-frame / snapshot requirements from a diagnostic
     questionnaire `.xlsx` and build the authoritative FSCS
     (`Phase 1`).
  2. Generate or update Dem ARXML configuration for freeze-frame classes,
     DID classes and data-element classes (`Phase 2`).
  3. Generate Service 0x19 snapshot read-function C stubs into the Bosch
     project tree (`Phase 3`).
  4. Push the FSCS to IBM DOORS (`Phase 4`).

  **Workspace under `.DCOM_AI/19Service_Toolkit_PRJ/`.**
  Run the toolkit from your project root directory. `--init-project`
  scaffolds the workspace inside `.DCOM_AI/19Service_Toolkit_PRJ/`. The
  skill reads the diagnostic questionnaire from `inputs/` and writes all
  artefacts to `outputs/`; Phase 2 merges ARXML containers into the Bosch
  project tree under `rb/as/<customer>/core/app/dsm/Cubas_DEM/`, and
  Phase 3 writes C stubs under `rb/as/<customer>/core/app/dcom/RBAPLCust/src/`.

  **`--init-project` is a resumable state machine.** Each invocation
  advances the workspace by exactly one step until Phase 1 fires.

  **Pipeline is gated.** No `--phase all`; each phase runs once and exits
  with `[AGENT STOP] End this turn now.` Phase 3 is the one exception —
  it closes with `[AGENT TODO]` so the agent fills inline `TODO(agent)`
  blocks in non-trivial `.c` stubs in the same turn, then emits an
  `[AGENT REVIEW]` summary asking the operator to verify.

  Per-phase contracts, schema details, and version history live in
  `reference/*.md`; this SKILL.md is a dispatcher pointing at them.
---

# 19Service Toolkit

Generic code generator for AUTOSAR UDS Service 0x19 freeze-frame
configuration targeting Bosch BSW projects.

This SKILL.md is a **dispatcher** — it carries cross-phase contracts and
points at the per-phase `reference/*.md` files for details.

## Python environment

The skill is **environment-agnostic**: every command below uses a bare
`python ...` / `pip ...` and assumes a working Python 3.11 or 3.12 on
`PATH`. Use whichever Python name resolves to the right interpreter and
stick with it.

```bash
python -m pip install -r scripts/requirements.txt
python scripts/pipeline.py --version
python scripts/pipeline.py --validate
```

## Quickstart

```bash
# 1. Scaffold workspace. Run repeatedly until Phase 1 fires; each run
#    advances the state machine by exactly one step.
cd /path/to/my-bosch-project
python /path/to/skill/scripts/pipeline.py --init-project --product-types <operator-provided>

# 2. Phase 1 — build FSCS, then STOP for xlsx review.
python scripts/pipeline.py --phase fscs

# 3. Edit outputs/fscs/fscs_edit.xlsx, then re-import.
python scripts/pipeline.py --phase xlsx-import

# 4. Choose one or more branches (independent and idempotent):
python scripts/pipeline.py --phase arxml      # Phase 2
python scripts/pipeline.py --phase c          # Phase 3
python scripts/pipeline.py --phase doors --no-upload --no-fetch  # smoke
python scripts/pipeline.py --phase doors --user-nt <NT>          # real DOORS push
```

> **First-time DOORS push on this machine:** before the `--phase doors`
> upload above, prime the OS keychain so future runs don't prompt for a
> password. Have the **operator** run this in their own terminal
> (never paste a password into the chat):
>
> ```bash
> python scripts/fscs_doors_sync.py \
>     --user-nt <NT> --password <pwd> --save-credentials --no-upload
> ```
>
> Subsequent `--phase doors` runs only need `--user-nt <NT>` — the
> password is read from Windows Credential Manager / macOS Keychain /
> Linux Secret Service automatically. See
> [`reference/phase-4-doors.md`](reference/phase-4-doors.md) for the
> full credential contract.

## The pipeline at a glance

| Phase | Reads | Writes | Deep dive |
|---|---|---|---|
| **1 — FSCS** | `.DCOM_AI/19Service_Toolkit_PRJ/inputs/*.xlsx` | `.DCOM_AI/19Service_Toolkit_PRJ/outputs/fscs/{fscs.json, fscs_edit.xlsx, FSCS_19.txt, reports}` | [`reference/phase-1-fscs.md`](reference/phase-1-fscs.md) |
| **xlsx import** | `outputs/fscs/fscs_edit.xlsx` | `outputs/fscs/fscs.json` + `FSCS_19.txt` | [`reference/phase-1-fscs.md`](reference/phase-1-fscs.md) |
| **2 — ARXML** | `outputs/fscs/fscs.json` | Bosch tree `rb/as/<customer>/core/app/dsm/Cubas_DEM/*.arxml` (skip-on-conflict) | [`reference/phase-2-arxml.md`](reference/phase-2-arxml.md) |
| **3 — C stubs** | `outputs/fscs/fscs.json` | Bosch tree `rb/as/<customer>/core/app/dcom/RBAPLCust/src/<PT>/RBAPLCUST_19Snapshot_*.c` (skip-on-conflict) | [`reference/phase-3-c-generation.md`](reference/phase-3-c-generation.md) |
| **4 — DOORS** *(opt-in)* | `outputs/fscs/FSCS_19.txt` + `inputs/doors_mapping.yaml` | `outputs/doors/doors_upload_19.xlsx` + report | [`reference/phase-4-doors.md`](reference/phase-4-doors.md) |

## Where to read what

| If you're doing... | Read this |
|---|---|
| Setting up a new workspace or switching projects | [`reference/workspace-model.md`](reference/workspace-model.md) |
| Running Phase 1 / handling the xlsx workbook | [`reference/phase-1-fscs.md`](reference/phase-1-fscs.md) |
| Running Phase 2 / debugging ARXML merge | [`reference/phase-2-arxml.md`](reference/phase-2-arxml.md) |
| Running Phase 3 / filling `TODO(agent)` stubs | [`reference/phase-3-c-generation.md`](reference/phase-3-c-generation.md) |
| Running Phase 4 (DOORS upload) | [`reference/phase-4-doors.md`](reference/phase-4-doors.md) |
| Configuring `config/project.json` / DOORS mapping schema | [`reference/configuration.md`](reference/configuration.md) |

## Cross-phase contracts

### A. FSCS governance

`outputs/fscs/fscs.json` is the **single authoritative source**. All
downstream phases read the JSON, never the plaintext.

### B. Product type handling

- `Product_Type` must be supplied **explicitly by the human operator via
  their prompt** at `--init-project` time. The agent must not infer, guess,
  or default product types from filenames, project structure, CAN matrix
  names, diagnostic questionnaires, or any other source.
- Multiple product types may be supplied (comma-separated); Phase 2 and
  Phase 3 fan out to every product in the work-set.
- `Product_Type` can be refined later in `fscs_edit.xlsx`.
- If the operator does not supply `Product_Type` in their prompt, the skill
  stops with `[AGENT STOP]` and asks the operator to provide it. It refuses
  to proceed until product types are explicitly set.

### C. Output safety

Phase 2 and Phase 3 write only into the Bosch project tree. They never
overwrite existing files or containers — every conflict is a skip,
recorded in the per-product `merge_report.txt` or `generation_report.txt`.

### D. Agent turn-stopping contract

The pipeline is **gated**: every phase finishes with
`[AGENT STOP] End this turn now.` The agent must treat each STOP as a
turn boundary. The operator remains in control of advancing through
gates (review xlsx, confirm ARXML target, choose DOORS-vs-ARXML branch,
review generated C stubs).

| Gate | Trigger output | Agent action this turn | Next-turn trigger |
|---|---|---|---|
| **Init** | `[AGENT STOP]` at end of `--init-project` | Surface scaffolded layout + ask for questionnaire / product types / confirmation. Stop. | Operator replies with questionnaire placed or product types provided. |
| **Phase 1** | `[AGENT STOP]` after FSCS built | Surface path to `fscs_edit.xlsx` + review report. Ask operator to edit `used_flag` / `Product_Type` / `impl_notes`. Stop. | Operator replies "done" / "import" / "继续". |
| **xlsx import** | `[AGENT STOP]` after import | Surface used-DID preview + branch menu (ARXML / C / DOORS). Stop. | Operator picks one or more branches. |
| **Phase 2 ARXML** | Phase-specific success banner | Terminal phase — no further STOP. | n/a |
| **Phase 3 C** | `[AGENT TODO] X fill / Y stub` summary | Continuous-flow. The agent immediately expands each *fill* DID's inline `TODO(agent)` block into real code in the same turn, leaving *stub* DIDs in place. | Operator reviews `[AGENT REVIEW]` summary. |
| **Phase 4 DOORS** | Phase-specific success banner | Terminal phase — no further STOP. | n/a |

### E. Password safety

Never ask the operator to paste a DOORS password into the chat. Tell them
to run `scripts/fscs_doors_sync.py --save-credentials` themselves in their
own terminal. Never run `--save-credentials` on the operator's behalf with
a password they typed earlier in the conversation.

## Version

The canonical version lives in two places that must stay in sync:

- `VERSION` (one-line plaintext — source of truth read by scripts).
- `SKILL.md` frontmatter `version:` (what skill hosts pick up).

Run `python scripts/pipeline.py --version` to verify.
