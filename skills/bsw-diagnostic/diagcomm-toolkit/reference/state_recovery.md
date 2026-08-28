# Workspace `state/` — agent-owned state for Step 8 (DOORS upload)

Contents of the workspace `state/` folder are written by
`<skill>/scripts/doors_sync.py` after a successful DOORS upload. Users
are not expected to edit these files. The folder lives at
`<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/state/` since v2.0.0
(prior to v2 it lived in the in-skill checkout; the
`migrate_v1_20_to_v2.py` tool relocates it).

| File | Owner | Purpose |
|---|---|---|
| `doors_upload_state.json` | `doors_sync.py` | Per-`module_uuid` record of the last DOORS row this skill maintained, including the **accumulated history** (covered projects/products/arxml paths and the previous `Object Text` snapshot) that drives the append-style update behaviour. |

The four workspace folders divide ownership cleanly:

- `inputs/`  is **user-owned**     (workspace `inputs/DiagComm.xlsx`, the only file the user actually edits)
- `outputs/` is **regenerable**    (workspace `outputs/{FSCS,diff_report,doors_upload}.txt|xlsx`, …)
- `state/`   is **agent-owned**    (Step 8 memory across runs — this folder)
- `.cache/`  is **auto-derived**   (workspace `.cache/{values,config,doors_mapping}.json|yaml`, regenerated from the xlsx)
- `<skill>/assets/` is **skill-bundled** (`DiagComm.txt`, `DiagComm_schema.json`, `doors_template.xlsx`, `inputs_template.xlsx`, `doors_mapping_skeleton.yaml` — read-only at runtime, lives in the user-level skill checkout)

## File format (`doors_upload_state.json`, schema v3)

```jsonc
{
  "version": 3,
  "modules": {
    "1-aaaaaaaaaaaaaaaa-M-bbbbbbbbbbbbb": {
      "last_success_abs":            "576",
      "last_upload_at":              "2026-05-06T10:21:33",

      // identity of the LATEST upload (drives classify_change)
      "current_project_name":        "MyProject",
      "current_product_type":        "IPB",
      "current_param_fingerprint":   "sha256:…",
      "current_fscs_sha256":         "sha256:…",

      // accumulated history -- grow monotonically across runs
      "covered_projects":            ["MyProject"],
      "covered_products":            ["ESP", "IPB"],
      "covered_arxml_paths":         [
        "CanTp_CusDiag_EcucValues.arxml",
        "CanTp_Feature_EcucValues.arxml",
        "Dcm_CusDiag_Can_EcucValues.arxml",
        "Dcm_Feature_EcucValues.arxml",
        "Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml",
        "Can0_CusDiag_EcucValues_ESP.arxml",
        "Can0_CusDiag_EcucValues_IPB.arxml"
      ],
      "last_object_text": "…(full Object Text content as written to DOORS)…",

      // append-only audit log
      "history": [
        {"ts": "2026-05-06T09:00:00",
         "project": "MyProject", "product": "ESP",
         "param_fingerprint": "sha256:…", "fscs_sha256": "sha256:…",
         "change_kind": "first_insert", "abs_n": "576"},
        {"ts": "2026-05-06T10:21:33",
         "project": "MyProject", "product": "IPB",
         "param_fingerprint": "sha256:…", "fscs_sha256": "sha256:…",
         "change_kind": "pp_only_changed", "abs_n": "576"}
      ]
    }
  }
}
```

**One entry per `module_uuid`.** The entry tracks the **single active
DOORS row** that this skill is currently maintaining inside that
module — but the *content* of that row grows over time. The fields
fall into three groups:

- **`last_success_abs` / `last_upload_at`** — what we wrote and when.
- **`current_*`** — exactly what was uploaded last time. Used by
  `classify_change()` to decide what changed since.
- **`covered_*` / `last_object_text` / `history`** — the running
  *content* of the DOORS row. The next update unions in any new
  values and appends a new block to `last_object_text`.

## Decision rule (mirrors `SKILL.md` Step 8)

| `change_kind` | Mode | Effect on the row |
|---|---|---|
| `first_insert`         | **insert** | Brand-new DOORS row, fresh state entry. |
| `params_and_pp_changed`| **insert** | Brand-new DOORS row; previous state entry is **replaced** (the orphan row is no longer tracked). |
| `params_changed`       | **update** | Same row. Object Text appends a "(parameters changed)" block. |
| `pp_only_changed`      | **update** | Same row. Object Text appends a "new mapping" note; `covered_projects` / `covered_products` grow. |
| `fscs_only_changed`    | **update** | Same row. Object Text appends a "(FSCS regenerated)" block. |
| `no_change`            | **skip** (exit 1) | Pass `--force-no-skip` to upload anyway with a "no semantic change" stamp. |

## Schema migration

| From | Behaviour on first read |
|---|---|
| v1 (legacy `entries["<uuid>\|<project>\|<product>"]`) | Auto-collapsed to v2 (one entry per `module_uuid`, newest `last_upload_at` wins), then to v3. Stderr emits one note per migration. |
| v2 (one entry per `module_uuid`, no accumulation lists) | Auto-promoted to v3: `covered_projects`, `covered_products` are seeded with the single recorded value; `covered_arxml_paths = []`; `last_object_text = null`; `history` gets one synthesised `first_insert` entry tagged with `_migrated_from: "v2"`. The next update will append on top of an empty prior `Object Text`. |
| v3 | Used as-is. |

## Recovery procedures

| Goal | Action |
|---|---|
| Force a fresh DOORS row even though state remembers one | `python <skill>/scripts/doors_sync.py --force-mode insert …`. State entry for this module is **replaced** on success — `covered_*` lists reset, history starts a new chain. |
| Force update against a state entry that exists | `python <skill>/scripts/doors_sync.py --force-mode update …`. Fails fast if the module has no `last_success_abs`. The classified `change_kind` still drives the Object Text append template. |
| Forget about a module entirely (wipe its entry, e.g. the row was deleted in DOORS) | Open workspace `state/doors_upload_state.json`, remove the offending key under `modules`, save. Next Step 8 run for that module goes to `first_insert`. |
| Wipe all state and start over | Delete workspace `state/doors_upload_state.json` (the folder stays — `--init-project` recreates it). Use with care — every previously-tracked module falls back to `first_insert` and you may end up with duplicate DOORS rows. |
| "I want this product gone from RB_Product" | Edit the relevant entry's `covered_products` list and remove the value, then run an update. (We do not provide an automatic shrink path because the spec is grow-only.) |

## What does *not* go here

- User-edited inputs. Workspace `inputs/DiagComm.xlsx` is the single
  user-edited file (and its `.cache/` derivatives auto-regen from it).
- Regenerable artefacts (FSCS, diff report, the xlsx, payload report).
  Those live in workspace `outputs/` and are git-ignored by the
  workspace's auto-written `.gitignore`.
- Secrets. Never. The DOORS password lives only in the OS keychain
  (Windows Credential Manager / macOS Keychain / Linux Secret Service)
  via `keyring`, or transiently in `$DOORS_PWD` for CI; see
  [`SKILL.md` Step 8b — credentials](../SKILL.md#step-8b--credentials-keyring-fallback).
  Never paste it into chat, never write it under workspace `inputs/` /
  `outputs/` / `state/`.
