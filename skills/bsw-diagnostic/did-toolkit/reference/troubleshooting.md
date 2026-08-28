# Troubleshooting

> **When to read this.** A pipeline run failed, behaved
> unexpectedly, or produced a confusing log line.

Symptoms grouped by subsystem. Each row also points at the
deeper-detail reference doc when the fix needs more context.

---

## 1. Environment

| Symptom | Cause / fix |
|---|---|
| Wrong Python picked up / `import` errors on Pydantic | Confirm `python --version` reports 3.11 or 3.12 and `python -m pip show pydantic` resolves. Reinstall deps with `python -m pip install -r scripts/requirements.txt`. If the host has a user-level Python-environment skill configured, activate it first. |
| Permission denied on output files | `chmod -R 755 outputs/` (Windows: take ownership of the workspace tree) |
| `python scripts/pipeline.py --version` exits non-zero | `SKILL.md` frontmatter / `VERSION` / `CHANGELOG.md` top entry disagree — pick one canonical version and align all three |

---

## 2. Workspace resolution

| Symptom | Cause / fix |
|---|---|
| Phases write to the wrong `outputs/` | CWD walk landed on a different ancestor's `config/project.json`. Use `--project-root <path>` or `$DID_TOOLKIT_PROJECT_ROOT` to force the right one |
| `--init-project` re-runs unexpectedly chain into Phase 1 | Intentional: once the workspace is COMPLETE (skeleton + questionnaire + `project.json`), the state machine auto-advances. To re-issue from scratch, delete `.DCOM_AI/DID_Toolkit_PRJ/config/project.json` (and optionally the questionnaire) before re-running |
| `--init-project` reports `[WARN] detected Bosch tree at … but project.json's paths.pdm_file is anchored elsewhere` | Drift detection: live `(project_root, customer)` scan no longer matches the segments baked into `paths.pdm_file`. In TTY answer `y` to the `[y/N] overwrite` prompt; in non-TTY the existing config is kept by design — hand-edit `paths.*` or re-run interactively |
| `--init-project` in non-TTY mode exits 3 with `*_did.json files in .DCOM_AI/DID_Toolkit_PRJ/inputs/; non-TTY mode can't prompt` | Picker tripped: multiple questionnaires staged. Pass `--input <basename>` (bare name or relative path, both work) to disambiguate |
| `--init-project --non-interactive` on an empty workspace exits 0 with no `project.json` | Expected: FRESH state only scaffolds the skeleton. Drop a `*_did.json` under `.DCOM_AI/DID_Toolkit_PRJ/inputs/` and re-run; the second invocation will write the config |
| `extra='forbid'` raises `ValidationError` on a typo | The schema is strict by design. Fix the typo or check [`configuration.md`](configuration.md) for the canonical key name |
| Multi-config workspace, agent runs `--phase X` and gets exit 4 | Agent contract — call `--list-configs`, present the candidates to the operator, then re-invoke with `--config <chosen>` |
| `setup.py` says "multiple Bosch tree candidates" | Workspace contains more than one `<X>/rb/as/.../RBAPLCust`. Pass `--project-root <NAME>` to pick the intended one |

Deeper detail: [`workspace-model.md`](workspace-model.md).

---

## 3. Phase 1 — FSCS

| Symptom | Cause / fix |
|---|---|
| Phase 1 succeeded but no `FSCS_22.txt` / `FSCS_2E.txt` | Expected — the text views are emitted by `--phase xlsx-import` after the operator confirms the work-set. Edit `fscs_edit.xlsx`, then `python scripts/pipeline.py --phase xlsx-import` |
| `--phase fscs` exits 3 with multi-input error | Multiple `inputs/` candidates — call `python scripts/pipeline.py --list-inputs` first, then re-invoke with `--input <chosen path>` |
| Operator `used` selections lost after re-running Phase 1 | Don't pass `--reset-used` unless you mean it. Phase 1 auto-carries-forward by default |
| `inputs/<customer>_did.json` records keep getting `SKIPPED` in `fscs_generation_report.txt` | Pydantic validation failed — open the report to see which `did_hex` + which field. Fix the source `.json` (or the agent extractor that produced it) |

| **xlsx edit** | |
| CSV import says a DID row is missing or unexpected | Keep exactly one row per DID from the exported CSV. Use `used_flag=FALSE` to exclude DIDs, never delete rows |
| CSV import fails because columns are missing | Regenerate the CSV with `--phase fscs` and edit only the exported columns. Complex `value_range` / `sub_fields` / `free_text` data is intentionally hidden in `fscs.json` |
| Behavior text I edited isn't showing up in `FSCS_22.txt` | Re-run `--phase xlsx-import` after editing the CSV |

Deeper detail: [`phase-1-fscs.md`](phase-1-fscs.md). Multi-input
contract: [`phase-1-fscs.md#2-multi-questionnaire-selection`](phase-1-fscs.md#2-multi-questionnaire-selection).

---

## 4. Phase 2 — ARXML

| Symptom | Cause / fix |
|---|---|
| Phase 2 reports `outputs/fscs/fscs.json missing` | Phase 1 was skipped. Run `python scripts/pipeline.py --phase fscs` first |
| `WARN [fscs.drift]` on Phase 2 startup | `outputs/fscs/*.txt` are out of sync with `fscs.json` — usually because someone hand-edited the text. Re-run `--phase xlsx-import` to regenerate |
| Phase 2 emits a DID we didn't expect for this product | `product_type` is the wildcard `Common` (the default — applies to all products). Pin it to a specific product in `fscs_edit.xlsx::Product_Type` then `--phase xlsx-import` |
| Cross-product reviewer flags a DID that should be shared | Set `Product_Type=Common` in `fscs_edit.xlsx` to legitimise the overlap |
| `[MERGED] 0 inserted, N skipped` | Every container in `DID_Config.arxml` already exists in the target. Merge is a no-op — this is the expected steady-state when nothing changed |
| Bosch-tree ARXML wasn't touched | Phase 2 hard-aborts when `paths.base_dir` is missing/empty. Check exit code 2; fix `paths.base_dir` (or re-run `--init-project` from the project container). If the work-set was empty (`[WARNING] work-set is empty`), no PT had any `used` DIDs to emit. |
| `Phase 2 / 3 skipped: work-set is empty` (warning, exit 0) | Every `used_flag=FALSE` in `fscs_edit.xlsx`. Either flip some on (then `--phase xlsx-import`), or accept the skip — Phase 4 / DOORS still runs |
| `Phase 2 / 3 abort with unrecognised product_type 'DPC'` | A `Product_Type` cell doesn't match the case-insensitive whitelist `{DPB, ESP, ESPCL, IPB, RBU, Common}`. Fix the typo in `fscs_edit.xlsx` then `--phase xlsx-import` |
| `unrecognized arguments: --product-type` at argparse | The flag is not supported. Drop it from your command — Phase 2 / 3 fan out across every product carried by a `used` DID in `fscs.json` |
| `[SKIP] <PT>: paths.per_product.<PT>.arxml_file = null ...` and `outputs/arxml/<PT>/` is missing | The `per_product` block opted that PT out of Phase 2 (e.g. `ESPCL` is auto-skipped because `cfg/ESPCL/` doesn't exist in the tree). Delete the entry from `paths.per_product` to restore the iteration. See [`configuration.md`](configuration.md#pathsper_product) |
| `Pydantic ValidationError: per_product.<x>.<y>` at config load | The `per_product` block has an unknown PT (must be one of `DPB` / `ESP` / `ESPCL` / `IPB` / `RBU` / `Common`, case-sensitive), an unknown inner key (must be one of the 6 mirror keys), or an empty-string value (use `null` for skip). Fix `config/project.json` and re-run |

Deeper detail: [`phase-2-arxml.md`](phase-2-arxml.md). Output
modes: [`output-safety.md`](output-safety.md).

---

## 5. Phase 3 — Implementation

| Symptom | Cause / fix |
|---|---|
| Phase 3 footer says `[AGENT TODO] X fill / Y stub` | Expected when any DID has `storage_position` ∈ `{ROM, FLASH, RAM}`. Expand each fill-target's inline `TODO(agent)` block in the same turn; leave stub-targets in place. There is no external playbook — the inline block carries everything. |
| Want to count remaining TODOs | `rg "TODO\(agent\)" <bosch-tree>` |
| Agent looked for `_briefs/` files | There is no external `_briefs/` directory — the inline `TODO(agent)` block inside each non-EEPROM `.c` carries the same context. |
| `.c` file in Bosch tree wasn't refreshed after a re-run | Skip-if-exists policy — Phase 3 never overwrites an existing `.c`. Move/rename the existing file then re-run. |
| Two DIDs producing the same `.c` filename | Expected when both clean down to the same identifier. Phase 3 falls back to `<HEX>_<Name>.c`; check the `[COLLISION]` log line |
| EEPROM DID's read body is a stub instead of `DCOM_ReadDataByNVMId` | `nvm_item` field is empty in `fscs.json`. Fix it in `fscs_edit.xlsx` then `--phase xlsx-import` |
| RAM sub-pattern guess in the inline TODO block is "undetermined" | Behavior text doesn't match any keyword heuristic. Read [`implementation-storage-positions.md`](implementation-storage-positions.md) §3 in full and pick A/B/C by hand |
| `[SKIP] paths.per_product.<PT>.<key> = null — skipping local artefact and Bosch mirror ...` and a Phase 3 artefact is missing | The per-(PT, key) skip sentinel is set in `project.json` (e.g. `Common.config_settings_h` is auto-disabled because `Common/dcompr/` doesn't exist; or `IPB.<x>` was hand-disabled). Delete the entry from `paths.per_product.<PT>` to restore the artefact |
| Bosch ConfigSettings header for IPB landed at an unexpected path | `paths.per_product.IPB.config_settings_h` carries an override (auto-seeded to `RBDCOM_ConfigSettings_IPB.h`). Inspect `project.json` and either keep / change to `_IPB4HAD.h` etc. / remove the override |

Deeper detail: [`phase-3-implementation.md`](phase-3-implementation.md).
Agent fill-in playbook:
[`implementation-storage-positions.md`](implementation-storage-positions.md).

---

## 6. Phase 4 — DOORS

| Symptom | Cause / fix |
|---|---|
| `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml needs a real doors.document_uuid` | Replace `PUT-DOORS-DOCUMENT-UUID-HERE` with the real UUID. Smoke test bypass: `--phase doors --no-anchor --no-upload` |
| `Anchor for service $22 not found` | Keyword string drifted in DOORS — edit `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml::anchors.service_22.text` or use `by_absolute_number: <N>` fallback. Pass `--refresh` to bypass MCP cache |
| `WARN: links.link_module_uuid is blank; skipping link upload` | Content uploads succeeded but link upload skipped. Fill the link module UUID in yaml then re-run with `--no-fetch` (avoids re-fetching just to upload links) |
| `WARN: zero FS/CS pairs reconciled` | DOORS-side cache hasn't refreshed, or the Object Heading text was modified after the FS upload. Wait a moment, then re-run with `--refresh` |
| `RB_Product` column empty in the workbook | The DID's per-DID `Product_Type` cell is blank in `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx` (rare — the loader normalises to `Common`), or `value_maps.RB_Product` in `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml` doesn't have a mapping for that product. Pin the CSV cell to a recognised product (then `--phase xlsx-import`), or extend the yaml mapping |
| Upload looks identical to previous run but takes ages | The MCP server may be re-fetching the full module. Use `--no-fetch` for incremental re-runs after a payload tweak |
| Authentication failure | Resolution order is `--password` > `$DOORS_PWD` > **OS keychain** > interactive prompt (since 2.3.0). If the cached keychain entry is stale (DOORS-side password was changed), `doors_sync.py` auto-prompts ONCE for a fresh password and silently refreshes the keychain on retry success. If both attempts fail with auth errors, log into the DOORS Web UI to confirm the password and unlock the NT account if needed (LDAP/AD typically locks after 3-5 wrong attempts). Refresh the cache manually with `python scripts/fscs/doors/doors_sync.py --user-nt <NT> --password <new-pwd> --save-credentials --no-upload`. |
| `[doors_sync] WARN: keyring write failed` / `keyring lookup failed` | OS keychain backend hiccup (Windows Credential Manager locked, macOS Keychain prompted-and-cancelled, Linux Secret Service not running). The script falls through to the env-var / interactive-prompt path automatically — set `$DOORS_PWD` for one run, or pass `--no-keyring` to bypass the cache permanently. |
| `[doors_sync] WARN: \`keyring\` not installed` after `--save-credentials` | Run `python -m pip install -r scripts/requirements.txt` (since 2.3.0 the file pins `keyring>=23,<26`). The script still runs without `keyring`, just without the OS-keychain layer of the password fallback. |
| Cold-start `--save-credentials --no-upload` looks like it did nothing | Pre-2.3.0 bug from sister skill `diagcomm-toolkit` (fixed there in v1.19.3, ported here in 2.3.0). did-toolkit 2.3.0+ short-circuits this command BEFORE reading mapping yaml / FSCS / state, so it must work on a brand-new project. If it doesn't print `credential cache primed`, you're on a stale build — confirm `python scripts/pipeline.py --version` shows ≥ 2.3.0. |

Deeper detail: [`phase-4-doors.md`](phase-4-doors.md).

---

## 7. Output safety

| Symptom | Cause / fix |
|---|---|
| `[ABORT] Phase 2 cannot run — paths.base_dir is empty` | Hard-gate: fix `paths.base_dir` (or re-run `--init-project` from the project container). See [`output-safety.md`](output-safety.md) §1. |
| Bosch tree wasn't touched but I expected it to be | The project tree is the sole sink — there's no other place Phase 2/3 could have written. Run with `--dry-run` to see the resolved write paths; if the dry-run says "Would create" but the real run didn't touch the file, check per-(PT, key) skip sentinels (`paths.per_product.*` = `null`). |
| Looking for `outputs/backups/` rolling snapshots | Not part of the skill. Skip-on-conflict never overwrites, so the snapshot story is delegated to `git` on the Bosch tree. |
| `--output-mode` / `--no-backup` flag rejected | Neither flag is supported. The project tree is the sole sink, skip-on-conflict is the safety net. Update your scripts. |

---

## 8. Exit codes (quick reference)

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Invalid arguments / `--init-project` collision |
| 2 | Missing configuration |
| 3 | Invalid input file / multi-input ambiguity (no `--input`) |
| 4 | Generation error / multi-config ambiguity (no `--config`, non-TTY) |
| 5 | File I/O error |

---

## 9. Logging

`DEBUG` (detail) · `INFO` (normal) · `WARNING` (non-critical)
· `ERROR` (critical) · `FATAL` (unrecoverable). Use `--verbose`
for `DEBUG` output.
