# Phase 4 — DOORS upload (optional)

> **When to read this.** You're running `--phase doors`,
> setting up `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`, debugging anchor or
> link-upload failures, or wiring DOORS into a release flow.

After Phase 1 (or after xlsx-import) the operator can push
`FSCS_22.txt` / `FSCS_2E.txt` to DOORS as two per-service
workbooks plus a CS→FS link workbook. **Opt-in only.** DOORS is
one of two explicit branches the operator picks at the
xlsx-import STOP gate (the other being `--phase arxml` +
`--phase implementation`). Phase 1 / xlsx-import end-of-run hints
surface the exact `--phase doors` command.

The DOORS sub-toolkit lives at
[`scripts/fscs/doors/`](../scripts/fscs/doors/) with separate
modules for fetch (`doors_fetch.py`), anchor resolution
(`anchor.py`), per-DID split (`fscs_split.py`), payload
building (`build_doors_payload.py`), MCP transport
(`mcp_transport.py`), upload (`doors_upload_mcp.py`), and link
reconciliation (`doors_links.py`). The `doors_sync.py`
orchestrator wires them together.

---

## 1. The data model

Each DID occupies **2 consecutive rows** in DOORS — the **FS row**
(Functional Spec) and the **CS row** (Coding Spec) — across a
**17-column workbook** aligned to `assets/doors_template.xlsx`:

| Column | FS row (row 1) | CS row (row 2) |
|---|---|---|
| `Number` | "1" | "1" |
| `Destination Object` | anchor address (INSERT only — see §3.5) | anchor address (INSERT only — see §3.5) |
| `isPicture` | `no` (default) | `no` (default) |
| `Absolute Number` | recorded `fs_abs` (UPDATE only — see §3.5) | recorded `cs_abs` (UPDATE only — see §3.5) |
| `Object Heading` | `<HEX> <DidName>` (single-line headline) | (empty) |
| `Object Text` | (empty) | full DID body verbatim, including Behavior |
| `RB_RS_CP_Status` | `Configuration Required` (default) | `Configuration Required` (default) |
| `RB_RS_MS_Status` | `In Process` (default) | `In Process` (default) |
| `RB_Product` | per-DID `product_type` from `fscs.json` (Common ⇒ all mapped products, newline-joined) | same as FS row |
| `RB_Configuration` | `Mainstream` (default) | `Mainstream` (default) |
| `RB_Realizing_SWComponent` | `RBAPLCust_DPB` (or per-product default) | same as FS row |
| `RB_Realizing_SWitem` | **`.arxml` basename only** (e.g. `Dcm_CusDiag_Services_EcucValues_DPB.arxml`) | **`.c` basename only** (e.g. `RBAPLCUST_F189_VersionNumber.c`) |
| `RB_VerificationType` | `Test` (default) | `Inspection` (default) |
| `RB_VerificationCriteria` | (default) | (default) |
| `RB_Analysis_Results` | `Negligible` (default) | `Negligible` (default) |
| `RB_Referenced_Testcase` | `SwT` (FS role default) | `CT` (CS role default) |
| `RB_TestEnvironment` | `Labcar/HIL` (FS role default) | `SIL Simulation` (CS role default) |

`$22` and `$2E` each get **one xlsx**, landing under their
respective service anchors in the same DOORS module. After
content uploads, a re-fetch reconciles each DID's CS row to its
FS row and uploads `doors_upload_links.xlsx`.

Notable contract details:

- `Object Text` carries the **full Behavior section**, multi-line
  preserved (the renderer has a regression pin so future changes
  can't silently truncate it).
- `RB_Realizing_SWitem` is **filename only** (no path); FS row is
  `.arxml`, CS row is `.c`. Path-shaped templates from legacy
  mappings are reduced to their basename automatically.
- `RB_Product` is sourced **per-DID from
  `fscs.json::dids[].product_type`**, NOT from
  `config/project.json` (there is no global `project.product_type`
  fall-back).

---

## 2. `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml` — minimum required

Before the first upload, fill in the following keys. The shipped
template carries production keyword text already, so the typical
edit is just the two UUIDs and the value map.

`--init-project` scaffolds the template at
`.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml.template` (sourced from
`scripts/templates/doors_mapping.yaml.template` in the skill). Rename
it to drop the `.template` suffix before the first `--phase doors`
run; the orchestrator only reads `doors_mapping.yaml`, not the
`.template` copy.

### 2.1 Two UUIDs (mandatory)

```yaml
doors:
  document_uuid: "<DOORS 内容模块的 UUID>"     # required: where FSCS content goes

links:
  enabled: true
  link_type: "Realisation"                   # default; tweak per project
  link_module_uuid: "<DOORS Link 模块的 UUID>" # required: where CS→FS links live
  direction: "cs_to_fs"                      # default (CS links to FS)
```

The smoke-test mode (`--no-anchor --no-upload`) skips both UUIDs
so you can verify local workbook generation with placeholders.

### 2.2 `RB_Product` value map

```yaml
value_maps:
  RB_Product:
    DPB:    "DPB"
    ESP:    "ESP 10"
    ESPCL:  "ESP 10"
    IPB:    "IPB 2.0"
    RBU:    "RBU"
```

The cell value is sourced **per-DID** from
`.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json::dids[].product_type` (the same
field the operator edits via the `Product_Type` column in
`.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx`).

Per-DID YAML overrides take the highest precedence — useful for
patching one DID without touching the FSCS data:

```yaml
rb_product_overrides:
  "0x0101": "Common"      # 0x0101 applies to all products even though it's tagged DPB
  "0xF190": "DPB"
```

Resolution order: `rb_product_overrides[hex]` (yaml) >
`dids[].product_type` (fscs.json) > empty cell.

`Common` (case-insensitive, both in `fscs.json` and in the
overrides block) expands to all mapped products (newline-joined)
— it is the same wildcard semantic as `Product_Type=Common` in
the ARXML filter (Phase 2).

### 2.3 `role_values` — per-row defaults (FS vs CS)

Some columns differ between the FS row and the CS row. A
declarative override block lets the operator pin the defaults
without editing Python:

```yaml
role_values:
  FS:
    RB_Referenced_Testcase: "SwT"
    RB_TestEnvironment: "Labcar/HIL"
  CS:
    RB_Referenced_Testcase: "CT"
    RB_TestEnvironment: "SIL Simulation"
```

The shipped values match `assets/doors_template.xlsx`. Add more
keys to either role to override any other column on a per-row
basis.

### 2.4 `realizing_paths` — FS=.arxml / CS=.c basenames

```yaml
realizing_paths:
  fs_template: "Dcm_CusDiag_Services_EcucValues_{product_type}.arxml"
  cs_template: "RBAPLCUST_{did_hex_bare}_{did_name}.c"
  customer_default: "rbcn"
```

Both templates are rendered to a basename (the workbook never
contains a path prefix). Available substitution tokens:
`{product_type}`, `{customer}`, `{did_hex_bare}`, `{did_name}`,
`{did_hex_lower}`. The legacy single `templates: [...]` list is
still accepted but each entry is reduced to its basename.

### 2.5 Service anchor keywords

```yaml
anchors:
  service_22:
    text: "The ReadDataByIdentifier service ..."   # production keyword (pre-filled)
    # by_absolute_number: 215                      # alternative: hard-pin to row N
  service_2e:
    text: "This service allows the Diagnosis tool to write ..."
```

If DOORS later renames the service heading text, edit
`anchors.service_XX.text` to match, or use `by_absolute_number`
to pin to a specific row regardless of text.

Full schema reference + every overridable knob:
[`configuration.md`](configuration.md).

---

## 3. Three-tier run modes

| Mode | Command | What it does |
|---|---|---|
| **Smoke test** | `--phase doors --no-upload --no-anchor` | Cheapest: build both per-service workbooks under `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/` without touching DOORS. Safe with placeholder `document_uuid`. |
| **Plan only** | `--phase doors --plan-only` | Compute the INSERT / UPDATE / NOOP / STALE plan against the recorded state and exit; no xlsx written, no MCP calls. Cheapest "what would change?" preview. Implies `--no-fetch --no-upload --no-links --no-anchor`. |
| **Anchor verify** | `--phase doors --no-upload --user-nt <NT>` | Additionally fetch the DOORS export and resolve anchors (verifies keyword text still matches the live module). |
| **Full sync** | `--phase doors --user-nt <NT>` | fetch → anchor → build (state-aware) → upload `doors_upload_22.xlsx` → upload `doors_upload_2E.xlsx` → re-fetch → reconcile FS/CS pairs → upload `doors_upload_links.xlsx` → write back per-DID landings into `state/doors_upload_state.json` |
| **Content only** | `--phase doors --user-nt <NT> --no-links` | Same as full sync but stop after the two content uploads (skip link reconciliation). Useful when the link module isn't ready yet. NB: INSERT landings can't be recorded without `--no-links` off (no `reconcile_did_rows` -> no fresh AbsoluteNumbers); UPDATE / NOOP are still recorded correctly. |
| **Reuse last fetch** | `--phase doors --user-nt <NT> --no-fetch` | Skip the `get_doors_module` round-trip and use the local `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_export.json`. Useful for quick re-runs after a payload tweak. |
| **Force fresh fetch** | `--phase doors --user-nt <NT> --refresh` | Force the MCP server to re-fetch even when its cache says no change. Use when DOORS-side edits aren't reflected in the cached export. |
| **Force re-INSERT** | `--phase doors --user-nt <NT> --force-reinsert` | Wipe the per-module landings before the diff so every effective DID classifies as INSERT. Use after a DOORS-side teardown or module re-pointing. |

### Password resolution (4-level fallback, since 2.3.0)

1. `--password <pwd>` — explicit CLI flag (highest precedence; never auto-retried on auth failure)
2. `$DOORS_PWD` — environment variable (CI / scripted runs)
3. **OS keychain** — `keyring` library brokers Windows Credential Manager (DPAPI) / macOS Keychain Access / Linux Secret Service. Entry lives at `service="did-toolkit:doors"`, `username=<NT>`. Prime it once with `--save-credentials` (see below).
4. Interactive prompt (TTY only; never returned from a non-TTY shell — those should set `$DOORS_PWD` or pass `--password`).

`--user-nt` itself accepts `$DOORS_USER_NT` as a fallback (parity with `$DOORS_PWD`), so a properly seeded shell can run the full Phase 4 with **zero CLI credentials** and **zero prompts**.

### Credential cache: prime, use, refresh, forget

```bash
# 1. PRIME (one-time per machine; the operator runs this in their own
#    terminal — never via the agent, since the password would land in
#    chat history). Cold-start short-circuit: works on a brand-new
#    project where mapping.yaml / FSCS / state don't exist yet.
python <skill>/scripts/fscs/doors/doors_sync.py \
    --user-nt <NT> --password <pwd> --save-credentials --no-upload

# 2. USE (every subsequent run — zero prompts, zero env vars):
python <skill>/scripts/pipeline.py --phase doors --user-nt <NT>

# 3. REFRESH (after a DOORS-side password change — overwrite the
#    cached entry):
python <skill>/scripts/fscs/doors/doors_sync.py \
    --user-nt <NT> --password <new-pwd> --save-credentials --no-upload
# (Or do nothing — the next --phase doors run will get an
# Unauthorized response, ONE prompt for the new password, retry,
# and silently refresh the keychain on success. See below.)

# 4. FORGET (delete the keychain entry; idempotent — a second
#    run is a benign no-op):
python <skill>/scripts/fscs/doors/doors_sync.py \
    --user-nt <NT> --forget-credentials
```

`--no-keyring` bypasses the OS keychain entirely (do not read, do not write). Useful for CI, debugging, or hosts with no Secret Service backend. `keyring` itself is a regular `pip install` (pinned in `scripts/requirements.txt` as `keyring>=23,<26`) — the script degrades gracefully to the env-var / interactive-prompt path if the import fails.

### Auth-failure auto-retry (one-shot per run)

If the upload responds with anything matching `_AUTH_FAIL_RE` (`401`, `403`, `Unauthorized`, `Invalid credentials`, `authentication failed`, `login failed`, `wrong password`, `用户名或密码错误`, `认证失败`, `密码错误`) **and** the password came from cache (`source ∈ {env, keyring}`) **and** stdin is a TTY, `_upload_one_with_pwd_refresh` prompts ONCE for a refreshed password and retries. On retry success the new password silently overwrites the keychain entry; on retry failure the keychain is **not** modified.

The script never retries more than once per run. Most enterprise DOORS deployments delegate auth to LDAP / AD which lock the NT account after 3-5 wrong passwords, so two attempts (cached + one prompt) is the safe upper bound. If both fail with auth errors, the operator must fix the underlying cause (typo'd NT, locked account, DOORS-side replication lag right after a password reset) before another run — log into the DOORS Web UI once to confirm and unlock if needed.

`source == "prompt"` and `source == "cli"` are explicitly NOT retried: in the prompt case the user just typed it, so another prompt won't help and risks NT lock-out; in the CLI case the user passed an explicit value, so we respect their choice and surface the failure.

The auth-retry runs only on the **first** content workbook upload. Once that succeeds (with the original or refreshed password), the second content upload and the link upload reuse the validated password directly — if either of those then fails with auth, the LDAP/AD account state changed mid-run (extremely rare) and the script surfaces the error rather than risk burning more attempts.

---

## 3.5. State machine

Phase 4 maintains a **per-workspace, per-DOORS-module** ledger of
what landed where with what content fingerprint. Every
`--phase doors` run consults this ledger to decide, for each
DID×service pair, which of four buckets to drop the row into.

### Anchor address vs `Absolute Number` — read this once

Two different concepts share the same DOORS-side number space and
operators kept conflating them. The internal code-level rename
makes the role explicit at every read site:

| Concept | Code field | Workbook column | Role |
|---|---|---|---|
| **Anchor address** | `AnchorMatch.anchor_address` (read from the export's `AbsoluteNumber` field of the anchor row) | `Destination Object` | Where to **append after** for INSERTs. One value per service, set at the top of the run from `anchors.service_XX.text` / `by_absolute_number`. |
| Recorded landing | `ServiceLanding.fs_abs` / `cs_abs` | `Absolute Number` | Where this DID **already lives** in DOORS (recorded by post-upload writeback). Used by UPDATEs to overwrite in place. |

So an INSERT row pair carries `anchor_address` in `Destination
Object` (DOORS: "drop me below row N"), and an UPDATE row pair
carries the recorded `fs_abs` / `cs_abs` in `Absolute Number`
(DOORS: "overwrite row M and row M+1"). The two columns are
**mutually exclusive per row** — exactly one is non-empty.

The DOORS-side field is still called `AbsoluteNumber` (we
`row.get("AbsoluteNumber")` in `anchor.py` / `doors_links.py` —
that's a DOORS API constraint), and the upload xlsx column header
is still `Absolute Number` (template constraint). Only the
in-memory anchor field was renamed.

### Buckets

| Bucket | Meaning | Workbook effect |
|---|---|---|
| **INSERT** | DID is not recorded for this module / service. | Row pair lands with `Destination Object = anchor.anchor_address` and `Absolute Number` blank → DOORS appends after the anchor. |
| **UPDATE** | DID is recorded but the rendered content hash drifted. | Row pair lands with `Destination Object` blank and `Absolute Number = <recorded fs_abs/cs_abs>` → DOORS overwrites in place. |
| **NOOP** | DID is recorded and the hash matches. | Row pair is **omitted from the workbook entirely** — the cheapest possible MCP call. |
| **STALE** | DID is recorded but is no longer effective in the current FSCS for that service. | WARN-only on stderr; record kept in state until the v1.18.x `--prune-stale` flag lands. |

### Content hash — what counts as "changed"

The hash is a SHA-256 over the **15 DOORS cells that actually
carry payload** (every cell except `Destination Object` and
`Absolute Number`, which the state machine itself controls).
Anything that changes the rendered content of those 15 cells —
including FSCS edits to fields like `NVM_ID` or any other field
that bubbles into `Object Text`'s Behavior section — flips the
DID into UPDATE on the next run. Pure cosmetic changes that don't
reach the workbook (e.g. an internal-only `revision` bump on a
DID's JSON record) are correctly classified as NOOP.

The hash is **insensitive** to dict-key order and trailing
whitespace, but **sensitive** to leading whitespace and any
unicode rewrite. See
[`scripts/fscs/doors/content_hash.py`](../scripts/fscs/doors/content_hash.py)
for the canonicaliser.

### State file — `state/doors_upload_state.json` (schema 3.0)

```jsonc
{
  "schema_version": "3.0",
  "modules": {
    "<DOORS module UUID>": {
      "last_uploaded_at": "2026-05-13T14:00:00+00:00",
      "dids": {
        "0xF190": {
          "service_22": {
            "fs_abs": "401",
            "cs_abs": "402",
            "content_hash": "sha256:abcd...",
            "last_uploaded_at": "2026-05-13T14:00:00+00:00"
          },
          "service_2e": {
            "fs_abs": null, "cs_abs": null,
            "content_hash": null, "last_uploaded_at": null
          }
        }
      }
    }
  }
}
```

* **Per-workspace.** The file lives under
  `.DCOM_AI/DID_Toolkit_PRJ/state/doors_upload_state.json` and is threaded by
  `pipeline.py::run_doors_sync`. Multi-project workspaces never
  cross-contaminate.
* **Per-module.** Each `modules.<uuid>` substate is consulted
  independently. An operator can target two DOORS modules from
  the same workspace (different `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml`
  configs) and their landings stay separate.
* **Atomic writes.** `save_state` writes to a sibling `.tmp`
  file then renames; a Ctrl+C mid-write can never leave the
  state file half-populated.
* **Migration.** Legacy `schema_version: 2` state files read as
  an empty :class:`State` with a stderr advisory; the next
  successful upload rewrites the file at the current schema with
  the freshly-recorded landings. No manual migration step needed.

### Module-UUID drift — what happens

If the operator re-points `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml::doors.document_uuid`
to a different DOORS module mid-flight, the state machine
self-resolves: the new UUID has no per-DID memory, so every DID
classifies as INSERT against the new module. The old module's
recorded landings stay in the file under the old UUID — they're
still correct for that module if the operator ever points back.

If you genuinely deleted the DOORS-side rows by hand and want a
clean slate, pass `--force-reinsert` (it wipes the per-module
substate via `reset_module(state, module_uuid)`, persists the
wipe immediately, then runs the build).

### Post-upload state writeback

After a successful upload + link reconciliation,
`doors_sync._writeback_state_post_upload` folds the freshly-fetched
FS/CS AbsoluteNumbers (from `reconcile_did_rows`) into the typed
state for INSERTs, refreshes the recorded `content_hash` +
timestamp for UPDATEs, leaves NOOPs untouched (the recorded
timestamp is genuinely the "last time this DID changed"), and
warns on STALE.

### DIDs in both services — per-service landings

A DID effective in both `service_22.effective` and
`service_2e.effective` lands at TWO physically distinct row
pairs in DOORS (one under each anchor). The state machine
records both landings independently:

* The orchestrator re-resolves the two service anchors against
  the *fresh* post-upload export, converts each anchor's
  `AbsoluteNumber` into a row index, and carves the row list
  into per-service `[start, end)` slices.
* `reconcile_did_rows(service_ranges=...)` then walks the rows
  ONCE and emits one `LinkEntry` per matched DID×service
  with the per-anchor `(fs_abs, cs_abs)` correctly attached.
* `_writeback_state_post_upload` keys its lookup by
  `(service, did_hex)` so each service slot in the per-DID
  state file gets its OWN landing (e.g. `0x0101.service_22`
  records the 22-block AbsoluteNumbers, `0x0101.service_2e`
  records the 2E-block AbsoluteNumbers).

Result: a subsequent UPDATE for that DID under either service
points at the correct row in the correct service block — no
cross-contamination, no DOORS-side row clobber.

If the per-service anchor resolution fails on the fresh export
(rare; usually means the anchor keyword text drifted between
the upload and the re-fetch), the orchestrator falls back to
the hex-only path and prints a stderr WARN. That fallback can
mis-record when a DID is in both services; the remediation is to
fix the anchor text in `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml` and
re-run `--phase doors --refresh`.

### `RowCtx.mode`

Operator-facing yaml mappings can read `row.mode` (one of
`"insert"` / `"update"`) if they want mode-conditional cell
content. The shipped `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml` ignores it;
the field is documented here so custom mappings can branch on
it without surprise.

---

## 4. Outputs

| File | Role |
|---|---|
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_upload_22.xlsx` | $22 service content upload xlsx (two rows per DID) |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_upload_2E.xlsx` | $2E service content upload xlsx |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_upload_links.xlsx` | CS → FS link upload xlsx (one link per DID per service) |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_export.json` | Most recent `get_doors_module` raw response |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_link_entries.json` | Reconciled `[{did_hex, fs_abs, cs_abs, service}]` list |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/doors/doors_payload_report.txt` | Human-readable build summary (per service: each DID + RB_Product + anchor row) |
| `.DCOM_AI/DID_Toolkit_PRJ/state/doors_upload_state.json` | Per-DID landing ledger. Per-workspace, per-DOORS-module. Drives the INSERT / UPDATE / NOOP / STALE state machine described in §3.5. |

---

## 5. Common pitfalls

| Symptom | Cause / fix |
|---|---|
| `.DCOM_AI/DID_Toolkit_PRJ/inputs/doors_mapping.yaml needs a real doors.document_uuid` | Replace `PUT-DOORS-DOCUMENT-UUID-HERE` with the real UUID. Smoke test bypass: add `--no-anchor --no-upload` |
| `Anchor for service $22 not found` | Keyword string drifted in DOORS. Edit `anchors.service_22.text` or use `by_absolute_number: <N>` fallback. Pass `--refresh` to bypass MCP cache |
| `WARN: links.link_module_uuid is blank; skipping link upload` | Content uploads succeeded but link upload was skipped. Fill the link module UUID in yaml then re-run with `--no-fetch` (avoids re-fetching the module just to upload links) |
| `WARN: zero FS/CS pairs reconciled` | DOORS-side cache hasn't refreshed, or the Object Heading text was modified after the FS upload. Wait a moment, then re-run with `--refresh` |
| `RB_Product` column empty in the workbook | The DID's per-DID `product_type` cell is empty in `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx`, or `value_maps.RB_Product` doesn't have a mapping for that product. Pin the DID's `Product_Type` in the CSV (then `--phase xlsx-import`), or add the product to `value_maps.RB_Product`. There is no global `project.product_type` fall-back |
| `Object Text` truncated mid-Behavior | Renderer regression — `test_build_payload_object_text_carries_full_behavior` exists exactly to catch this. Re-run the test suite; if it still passes the truncation is happening downstream of the workbook (DOORS-side cell-length cap) |
| `RB_Realizing_SWitem` shows a path instead of a basename | Mapping uses the legacy `realizing_paths.templates: [...]` block — the renderer still reduces it to a basename automatically. If you see a path, check that no operator override is forcing a value via the `columns:` block |
| Upload looks identical to the previous run but takes ages | The MCP server may be re-fetching the full module. Use `--no-fetch` for incremental re-runs after a payload tweak |
| Authentication failure | Resolution order is `--password` > `$DOORS_PWD` > **OS keychain** > interactive prompt (since 2.3.0). Cached keychain stale? `doors_sync.py` auto-prompts ONCE for a fresh password and silently refreshes the keychain on retry success. Two attempts both fail → log into the DOORS Web UI to confirm the password and unlock the NT account if needed (LDAP/AD typically locks after 3-5 wrong attempts), then refresh the cache with `python <skill>/scripts/fscs/doors/doors_sync.py --user-nt <NT> --password <new-pwd> --save-credentials --no-upload` |
| `[doors_sync] WARN: keyring write failed` / `keyring lookup failed` | OS keychain backend hiccup. `doors_sync.py` falls through to env-var / interactive-prompt path; pass `--no-keyring` to bypass the cache permanently for this run |
| Cold-start `--save-credentials --no-upload` looks like it did nothing | did-toolkit ≥ 2.3.0 short-circuits this command BEFORE reading mapping yaml / FSCS / state — must work on a brand-new project. If it doesn't print `credential cache primed`, you're on a stale build (`python scripts/pipeline.py --version` to confirm) |
