# Output safety — project tree only, skip-on-conflict

> **When to read this.** You're about to run Phase 2 or Phase 3 on a
> live Bosch tree, or you need to recover from an unexpected skip
> entry in `generation_report.txt`.

Phase 2 and Phase 3 write **only** into the Bosch BSW source tree
(`<paths.base_dir>/<paths.*>`); there is no local source mirror.
`.DCOM_AI/DID_Toolkit_PRJ/outputs/` holds **reports only** (`generation_report.txt`,
`validation_report*.txt`, `arxml_review_report_*.txt`,
`impl_review_report.txt`). Two simplified guards keep the workflow
safe:

1. **Hard-gate on `paths.base_dir`** — Phase 2 / Phase 3 abort early
   (exit 2) when `paths.base_dir` is empty or doesn't resolve to a
   real directory. No tree → no writes.
2. **Skip-on-conflict** — every existing artefact wins. ARXML
   containers are matched by `SHORT-NAME` and skipped; header
   `#define`s skip on macro-name match; PDM entries skip on entry
   key; `.c` files skip wholesale on file existence.

Retired guards (and what replaced them) — kept here as a canary so
an operator who hits a "stale config / flag" error knows what to do:

| Retired | Why | Replacement |
|---|---|---|
| `--output-mode {outputs,project,both}` | The local mirror was duplicate state — every artefact existed in two places at once. | Project tree is the sole sink. Reports stay under `.DCOM_AI/DID_Toolkit_PRJ/outputs/`. |
| `--no-backup` | Skip-on-conflict means we never overwrite anything, so backups are no longer the safety net. | Conflicts are *skipped*, not backed-up-and-overwritten. The pre-existing file is the backup. |
| `outputs/backups/<TS>/...` rolling snapshots | Same. | None — gone. Use `git` on the Bosch tree if you want a snapshot story. |
| `options.output_mode` / `options.backup_before_write` / `options.backup_keep` | Schema-level retirement of the same knobs. | Removed from schema 2.2; load fails loud if a stale config still carries them. |

---

## 1. Guard 1 — Hard-gate on `paths.base_dir`

```text
[ABORT] Phase 2 cannot run — paths.base_dir is empty.
        Edit .DCOM_AI/DID_Toolkit_PRJ/config/project.json and set
        paths.base_dir = <path to project container>, then re-run.
```

Phase 2 / Phase 3 hard-abort with exit code 2 when either:

* `paths.base_dir` is missing / empty in `config/project.json`, or
* the resolved path doesn't exist on disk.

There is no fallback sink, so the only safe failure is to refuse to
run. Fix `paths.base_dir` (typically by re-running `--init-project`
from the project container) and the abort goes away.

Per-(PT, key) skips via `paths.per_product`:

| Skip trigger | Effect |
|---|---|
| `paths.per_product.<PT>.arxml_file = null` | Phase 2 skips the entire `<PT>` iteration. Logged `[SKIP] <PT>: paths.per_product.<PT>.arxml_file = null`. |
| `paths.per_product.<PT>.<key> = null` | Phase 3 skips that one (PT, key) artefact. Logged `[SKIP] paths.per_product.<PT>.<key> = null`. |
| Empty work-set (every `used_flag=FALSE`) | Both phases warn + `return True`; Phase 4 / DOORS still runs. |

---

## 2. Guard 2 — `--dry-run`

```bash
python scripts/pipeline.py --phase arxml --dry-run
# (and again for --phase implementation; there is no auto-chain,
# each phase is one command.)
```

* No filesystem mutations anywhere.
* Every project-tree write is replaced by a log line:
  `[DRY-RUN] Would <action>: <path> (N B)`.
* The `generation_report.txt` is still written under
  `.DCOM_AI/DID_Toolkit_PRJ/outputs/...` (reports are local-only by design).

`--dry-run` is the recommended pre-flight before the first real
Phase 2 / Phase 3 run on a new workspace — it surfaces every path
template resolution so you can confirm the placeholders point at the
right Bosch files.

---

## 3. Phase 2 ARXML merge policy

Every direct `ECUC-CONTAINER-VALUE` child of
`DcmDsp/SUB-CONTAINERS` in `DID_Config.arxml` is considered.
Matches against an existing `SHORT-NAME` in the target are
**skipped** (same conservative policy as Phase 3 `.c` files —
hand-tuned definitions win). New containers are spliced in just
before `</SUB-CONTAINERS>`, preserving every byte of the
existing file upstream / downstream of that splice point. The
target file's container count and skip count land in the
per-product `generation_report.txt`:

```
[MERGED] arxml=<bosch-tree>/.../Dcm_..._EcucValues_DPB.arxml
         inserted=12 skipped=3 (already present by SHORT-NAME)
```

Full Phase 2 details: [`phase-2-arxml.md`](phase-2-arxml.md).

---

## 4. Phase 3 write semantics

| Artefact | Project-tree write semantic |
|---|---|
| `.c` files (`RBAPLCust/src/<PT>/RBAPLCUST_RDBI_<Name>.c` etc.) | **Skip-if-exists at the file level** — once a hand-tuned body lives in the Bosch tree, Phase 3 never overwrites it. Logged in `generation_report.txt` as `skipped_c_files`. |
| Headers (`Config.h`, `ConfigElements.h`, `ConfigSettings.h`) | **Merge** — new `#define`s spliced in just before `#endif`; existing macros preserved. No backup (no overwrite). |
| PDM (`RBAPLCUST_PDM.txt`) | **Append-merge** — new EEPROM PDM entries appended to the existing file; duplicates skipped by key. No backup. |

Full Phase 3 details: [`phase-3-implementation.md`](phase-3-implementation.md).

---

## 5. Invocation cookbook

```bash
# 1. Preview Phase 2 (recommended for first run on a new workspace).
python scripts/pipeline.py --phase arxml --dry-run

# 2. Real Phase 2 — merges directly into the Bosch tree.
python scripts/pipeline.py --phase arxml

# 3. Preview Phase 3.
python scripts/pipeline.py --phase implementation --dry-run

# 4. Real Phase 3 — writes .c / headers / PDM into the Bosch tree.
#    Closes with [AGENT TODO] X fill / Y stub (no [AGENT STOP]) so
#    the agent fills non-empty behaviours in the same turn.
python scripts/pipeline.py --phase implementation
```

The `--output-mode` and `--no-backup` flags are not supported;
passing either is rejected by argparse.

---

## 6. Common pitfalls

| Symptom | Cause / fix |
|---|---|
| `[ABORT] Phase 2 cannot run — paths.base_dir is empty.` | `config/project.json::paths.base_dir` is missing or doesn't exist on disk. Re-run `--init-project` from the project container, or hand-edit `base_dir` to point at the right path. |
| `Phase 2 / 3 skipped: work-set is empty` (warning + `return True`) | Every `used_flag` in `fscs_edit.xlsx` is `FALSE`. Either flip some on (and `--phase xlsx-import` to refresh `fscs.json`), or accept the skip if intentional — Phase 4 / DOORS still has a fully-rendered `fscs.json` to consume. |
| `[SKIP] <PT>: paths.per_product.<PT>.arxml_file = null ...` | The `per_product` block opted that PT out of Phase 2 (e.g. `ESPCL` may be auto-skipped if `cfg/ESPCL/` doesn't exist in the tree). Delete the entry from `paths.per_product` to restore the iteration. See [`configuration.md`](configuration.md). |
| `[SKIP] paths.per_product.<PT>.<key> = null ...` | The per-(PT, key) skip sentinel is set (e.g. `Common.config_settings_h` is auto-disabled when `Common/dcompr/` doesn't exist). Delete the entry to restore the artefact. |
| ARXML `inserted=0 skipped=N` — nothing was added | Either every container already exists in the target (the safe case), or your work-set has zero `used` DIDs for this `<PT>`. Check `generation_report.txt` for the breakdown. |
| `.c` file I just edited was overwritten on re-run | Shouldn't happen — `.c` writes are skip-on-conflict at the file level. If it did, the previous file was a *generated* stub (one-line TODO body) and the new one is closer to your edits; recover via `git`. |

---

## 7. Reports under `.DCOM_AI/DID_Toolkit_PRJ/outputs/`

Even though the source artefacts land in the Bosch tree, the
**reports** stay local so the workspace carries its own audit trail:

| Path | Written by | Contents |
|---|---|---|
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/validation_report_<suffix>.txt` | Phase 2 | per-product DID validation + skip summary |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/arxml_review_report_<suffix>.txt` | Phase 2 review | ARXML coverage / cross-product SCOPE / etc. |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/generation_report.txt` | Phase 3 | per-product write / skip breakdown + fill / stub counts |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/impl_review_report.txt` | Phase 3 review | unfilled `TODO(agent)` count + per-DID status |

Commit those reports? Up to you — they're regenerable, but they're
also useful in code-review for "what did the run actually do".
