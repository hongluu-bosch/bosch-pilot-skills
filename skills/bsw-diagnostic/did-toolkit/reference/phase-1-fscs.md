# Phase 1 — FSCS (questionnaire → `fscs.json` → xlsx edit loop)

> **When to read this.** You're running `--phase fscs`,
> ingesting a new diagnostic questionnaire, debugging the
> multi-input contract, or editing the FSCS via
> `fscs_edit.xlsx`.

Phase 1 turns a customer's diagnostic questionnaire into the
**single authoritative `outputs/fscs/fscs.json`** that every
downstream phase reads. Operator edits go through
`outputs/fscs/fscs_edit.xlsx` and round-trip back via
`--phase xlsx-import`.

---

## 1. Ingestion

Phase 1 accepts schema-compliant `*_did.json` only — drop an `.xlsx`
directly into `.DCOM_AI/DID_Toolkit_PRJ/inputs/` and `--phase fscs` will refuse it. The
skill carries no built-in workbook parser; every questionnaire flows
through an **agent-written one-off extractor** that is automatically
triggered by `--init-project` when it detects workbook(s) with no
matching JSON yet.

| Step | Mechanism |
|---|---|
| **Inspect** | Agent reads the `.xlsx` sheet names + first 5–10 header rows. |
| **Write extractor** | Agent drops a fresh `.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py` that turns the workbook into a canonical `.DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json` matching [`input-format.md`](input-format.md). |
| **Ingest** | `--phase fscs` reads the JSON and builds `fscs.json`. |

**Auto-extraction gate.** `--init-project` inspects `inputs/` and prints
an `[AGENT ACTION] auto-extract` signal when workbook(s) are present
but no `*_did.json` exists. The agent then writes the extractor,
runs it, and re-invokes `--init-project` to advance the workspace.
If extraction fails, the agent reports the error and **stops** — the
operator must inspect the workbook / headers and intervene; do not
auto-retry.

When multiple workbooks exist, the agent lists all candidates and
asks the operator to pick one. When a JSON already exists alongside
a workbook, `--init-project` prints an `[AGENT NOTICE]` reminding the
operator that a newer workbook may warrant re-extraction.

The extractor is **throwaway** (one workbook, one extractor) by
design — it keeps the skill itself generic and prevents
customer-specific column heuristics from leaking into future
projects. Full extractor recipe + canonical primitives:
[`excel-ingestion.md`](excel-ingestion.md). Canonical record
schema: [`input-format.md`](input-format.md).

> **Self-containment.** The extractor never reaches into the
> `did_extract` skill or any other external tool. The "read
> Excel and produce JSON" capability lives entirely inside
> the workspace's `.DCOM_AI/DID_Toolkit_PRJ/scripts/`.

---

## 2. Input modalities and auto-extraction

The `--init-project` state machine handles three input scenarios:

### 2a. Workbook(s) only, no JSON

`--init-project` detects `.xlsx`/`.xlsm` files but no `*_did.json`
and emits an `[AGENT ACTION] auto-extract` signal. The agent then:

1. Lists all workbooks (multiple → asks operator to pick one).
2. Writes a one-shot `extract_<customer>.py` in the workspace.
3. Runs it to emit the canonical `*_did.json`.
4. Re-invokes `--init-project` to advance the workspace.

This entire flow is **agent-driven** — the operator only needs to
place the workbook; no manual extractor writing is required.

If extraction fails (bad header, missing column, etc.), the agent
reports the error and **stops** — it does not auto-retry. The
operator must inspect the workbook and intervene.

### 2b. JSON + workbook coexistence

When `*_did.json` already exists alongside one or more workbooks,
`--init-project` prints an `[AGENT NOTICE]` reminding the operator
that the workbook may be newer or corrected. The agent then prompts
whether to re-extract; the existing JSON remains authoritative
unless the operator explicitly asks for a refresh.

---

## 3. Multi-questionnaire selection

When `.DCOM_AI/DID_Toolkit_PRJ/inputs/` holds more than one `*_did.json`,
`pipeline.py` does not auto-pick the alphabetically-first file.
The selection contract has TWO layers:

### 2a. `--init-project` records a choice

At the QUESTIONNAIRE_READY transition of the `--init-project`
state machine, `_pick_questionnaire` resolves which file to use
and the chosen basename gets persisted at
`paths.input_did_json` in `config/project.json`. Resolution order
inside `--init-project`:

1. `--input <basename>` flag (basename match; tolerates
   path-like forms).
2. Single candidate present → auto-pick (or `[Y/n]` confirm in TTY).
3. Multiple candidates + TTY → numbered picker built into
   `_pick_questionnaire`.
4. Multiple candidates + non-TTY → `_QuestionnaireAmbiguous` →
   `--init-project` exits 3 with a candidates listing.

The COMPLETE-state auto-chain into Phase 1 then uses the
recorded basename directly, so the picker never re-prompts
unless the operator passes a fresh `--input` override.

### 2b. Direct `--phase fscs` selection (legacy path, still supported)

If you skip `--init-project` and invoke `--phase fscs`
explicitly, the historical agent contract applies:

1. Run `python scripts/pipeline.py --list-inputs`. It prints
   one absolute POSIX path per line — every `*_did.json` under
   `.DCOM_AI/DID_Toolkit_PRJ/inputs/` — and exits 0 even when the directory is
   missing or empty (use empty stdout as the empty-set signal).
   `.xlsx` files are never listed; only schema-compliant JSON.

2. **Exactly one line** → just run `--phase fscs` (it
   auto-detects the same file).

3. **Two or more lines** → render a numbered list of the
   candidates **directly in the assistant message** and stop the
   turn so the operator can reply with the index (or filename)
   of their choice. **Do not** use the `AskQuestion` tool — the
   operator wants a plain conversational prompt. After the
   operator replies, invoke
   `python scripts/pipeline.py --input <chosen path> --phase fscs`
   in the next turn.

4. A direct `--phase fscs` with no `--input`
   and a multi-candidate inputs directory will **exit 3** with a
   hard ERROR pointing at this contract — the agent should never
   see that error if step 1 was done first. Human operators at
   a TTY get an interactive numbered menu instead of the error.

Example assistant turn for step 3:

```
.DCOM_AI/DID_Toolkit_PRJ/inputs/ 下检测到 3 份 *_did.json，请选择本次 Phase 1 用哪一份（回复编号或文件名即可）：
  [1] <customerA>_<variant1>_did.json
  [2] <customerB>_<variant1>_did.json
  [3] <customerB>_<variant2>_did.json
```

---

### 2c. JSON + workbook coexistence priority

When `inputs/` holds **both** `*_did.json` and `.xlsx`/`.xlsm`:

1. **JSON selection takes priority.** `_pick_questionnaire` resolves
   which JSON to use via the rules in §3a, completely independent of
   any workbooks present.
2. **Re-extraction is secondary.** After JSON selection, the agent
   sees the `[AGENT NOTICE]` and asks the operator: "A workbook
   coexists with the selected JSON. Re-extract?" The default answer
   is **no** — the existing JSON remains authoritative. The operator
   must explicitly confirm (e.g. "yes" / "重新提取" / "用 xlsx") for
   the agent to overwrite the JSON.

This prevents accidental data loss: a stale workbook left in `inputs/`
cannot silently override a freshly-edited JSON.

---

## 3. Phase 1 outputs

| File | Role |
|---|---|
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json` | **Single authoritative source.** Every downstream consumer reads this. Operator `used` selections from previous runs are carried forward unless `--reset-used` is passed. |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx` | **Operator edit table** — only editable artefact in the FSCS layer. |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_review_report.txt` | Auto-runs at end of Phase 1; advisory, never blocks. Skip with `--no-review` / `DID_NO_REVIEW=1` for CI. |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_generation_report.txt` | *Ingestion gate* report: `.DCOM_AI/DID_Toolkit_PRJ/inputs/*_did.json` records failing Pydantic validation are **skipped individually** (not aborting the build) and listed here with `did_hex` + failing field(s). |

`FSCS_22.txt` and `FSCS_2E.txt` are **NOT written by Phase 1** —
they're built later by `--phase xlsx-import`. This is intentional:
the xlsx workbook is the only operator-editable surface.

### `used` flag carry-forward

Re-running `--phase fscs` after an input change reloads the
previous `fscs.json`, carries `used_22` / `used_2e` and
per-service `behavior` text forward for DIDs that still exist,
and defaults `used=True` plus storage-derived behavior templates
for newly-introduced DIDs. Console output reports *effective*
counts so they match what actually lands in `.txt` / ARXML / C.

`--phase fscs --reset-used` resets all operator `used` flags
back to `True` — useful when starting a fresh release cycle.

---

## 4. xlsx edit loop

After Phase 1 writes `fscs.json`, `pipeline.py` exports
`.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx`. This is the **only**
spreadsheet the operator edits.

```
Phase 1 ─▶ fscs.json (auth) ─▶ fscs_edit.xlsx ─[operator edits in Excel/WPS]─▶
        ◀─ FSCS_22.txt + FSCS_2E.txt + fscs.json (rewritten) ◀─ xlsx-import ◀─
```

### Round trip

1. `python scripts/pipeline.py --phase fscs`
2. Edit `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_edit.xlsx`. Keep `did_hex`
   stable; keep exactly one row per DID. Reordering rows is
   allowed; **adding/removing rows is rejected** on import.
3. `python scripts/pipeline.py --phase xlsx-import` — validates
   the workbook, atomically rewrites
   `fscs.json` + `FSCS_22.txt` + `FSCS_2E.txt`, normalises the
   workbook, refreshes `fscs_review_report.txt`. (Or
   `--phase xlsx-import --xlsx <PATH>` for a non-default file.)
4. Re-run Phase 2 / Phase 3 to propagate the selection into
   ARXML and generated C.

### Editable columns

`used_flag`, `product_type`, `did_hex`, `did_name`, `did_name_zh`,
`rw_state`, `service_22_support`, `service_2e_support`,
`data_type`, `storage_position`, `size_bytes`, `nvm_item`,
`service_22_behavior`, `service_22_sessions`,
`service_22_security_levels`, `service_2e_behavior`,
`service_2e_sessions`, `service_2e_security_levels`.

`product_type` is positioned right after `used_flag` so the
operator's review eye flows from "is this DID in scope?" to
"which product does it apply to?" before the identity columns.

DID values are exported as `0x0101` and normalised back to bare
uppercase hex in `fscs.json`. Complex `value_range`,
`sub_fields`, and `free_text` data stay hidden in `fscs.json`
and are preserved by xlsx-import.

### HardCode behavior format (ROM / Flash DIDs)

For DIDs with `storage_position = ROM` (or `Flash`), the
`service_22_behavior` column drives the **auto-generation** of the
per-byte constant header in Phase 3. The standard format is:

```text
HardCode:
C_DID_<DidName>_Byte0_UB = 0xXX
C_DID_<DidName>_Byte1_UB = 0xXX
...
```

* `<DidName>` — PascalCase DID name (spaces removed), matching `did_name_en`.
* `Byte<N>_UB` — zero-based index, contiguous from `0` to `size_bytes-1`.
* `0x<HH>` — two-digit hex with `0x` prefix.

See [`input-format.md`](input-format.md) §"HardCode Behavior Format" for the
full specification, parsing contract, and worked examples.

> **Tip:** When a ROM DID's behavior is empty or does not start with
> `HardCode:`, Phase 3 still emits a `.c` stub with a `TODO(agent)`
> block, but the auto-generated header is **not** produced — the agent
> must fill the body manually. Always populate the HardCode block before
> running Phase 3 to get the fully-automated path.

### Drop-down validations & layout

The exported workbook is the single source of UX guarantees for
the operator — never re-encode these as a plain `.csv`:

- **Drop-down (list) validations** are attached to every column
  whose schema constraint is closed:
  `used_flag`, `service_22_support`, `service_2e_support`
  → `TRUE` / `FALSE`;
  `product_type` → `Common` / `DPB` / `ESP` / `ESPCL` / `IPB` /
  `RBU`;
  `rw_state` → `R` / `W` / `RW`;
  `data_type` → `ASCII` / `Unsigned` / `Signed` / `HEX` /
  `Bytefield` / `Texttable` / `enum` / `Linear` / `Identity`;
  `storage_position` → `EEPROM` / `RAM` / `ROM`.
  Excel / WPS refuse free-text input on these cells so the
  operator cannot accidentally drift the schema.
- **Auto-fit column widths** are computed from the longest visible
  cell, with extra padding budgeted for CJK characters so that
  the Chinese-name and behavior columns stay readable.
- **Header row is frozen** and an **autofilter** is attached to
  the full data range to keep navigation comfortable on long
  worksheets.

Pydantic schema validation still runs on import — drop-downs are
a UX hint, not the authority. If somebody opens the workbook in
a tool that strips data validations, xlsx-import will still
reject malformed cells with a clear field-level error.

> **`product_type` semantics.** Single source of truth for both
> the Phase 2 / Phase 3 fan-out work-set (every distinct value
> on a `used` DID becomes its own per-product build iteration,
> see [`phase-2-arxml.md`](phase-2-arxml.md) §3) and the Phase 4
> DOORS `RB_Product` cell. The default value is the wildcard
> `Common` (the schema migrator + field validator collapse
> missing / `None` / blank values to `Common` at load time, so
> the on-disk JSON and the CSV cell always carry an explicit
> tag). `Common` (case-insensitive) owns its own per-product
> iteration (reports under
> `.DCOM_AI/DID_Toolkit_PRJ/outputs/{arxml,implementation}/Common/`, Bosch tree
> write at `cfg/Common/Dcm_..._SingleCANID.arxml` and the
> matching Phase 3 sources), is never flagged by the
> cross-product SCOPE reviewer, and is expanded to a
> newline-joined list of every mapped product in DOORS. A
> non-empty non-Common token (`DPB`, `ESP`, `ESPCL`, `IPB`,
> `RBU`, …) restricts the DID to that product's iteration.
> Operators narrow them in `fscs_edit.xlsx` if they want
> product-specific routing.

Field-by-field semantics: [`configuration.md`](configuration.md).

---

## 5. Drift advisory

`scripts/fscs/drift.py` compares the on-disk
`.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/*.txt` against `fscs.json`. If they diverge
(typically because someone hand-edited the text), it emits
`WARN [fscs.drift] ...` on stderr but **never blocks the
pipeline**. The check is wired into Phase 2 as an advisory pre-run.

Run standalone:

```bash
python -m scripts.fscs.drift --outputs .DCOM_AI/DID_Toolkit_PRJ/outputs
```

Remediation: re-run `--phase xlsx-import` to regenerate
`FSCS_22.txt` / `FSCS_2E.txt` from the authoritative JSON.

---

## 6. Legacy import (one-shot migration)

For projects that previously used a TXT-only workflow:

```bash
python scripts/fscs_import.py \
    .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/FSCS_22.txt \
    .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/FSCS_2E.txt \
    -o .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json
```

Builds the canonical `fscs.json` from the legacy text pair.
Run once per project, then commit `fscs.json` and the
extractor-produced `*_did.json`; never the TXT files.

---

## 7. Common pitfalls

| Symptom | Cause / fix |
|---|---|
| Phase 1 succeeded but no `FSCS_22.txt` / `FSCS_2E.txt` | Expected (v1.7+). Edit `fscs_edit.xlsx`, then `--phase xlsx-import` |
| `--phase fscs` exits 3 with multi-input error | Multiple `.DCOM_AI/DID_Toolkit_PRJ/inputs/*_did.json` candidates — call `--list-inputs` first, then `--input <chosen>` (see §2) |
| `--phase fscs` exits with `inputs/ contains *.xlsx` | The skill ships no built-in workbook ingester. Run a one-shot `.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py` to convert the workbook to `*_did.json`, drop the JSON into `.DCOM_AI/DID_Toolkit_PRJ/inputs/`, then re-run Phase 1 |
| xlsx-import says a DID row is missing or unexpected | Keep exactly one row per DID from the exported workbook. Use `used_flag=FALSE` to exclude DIDs, never delete rows |
| xlsx-import fails because columns are missing | Regenerate the workbook with `--phase fscs` and edit only the exported columns |
| `WARN [fscs.drift]` on Phase 2 | Someone hand-edited the TXT. Re-run `--phase xlsx-import` to regenerate from JSON |
| Operator `used` selections lost after re-running Phase 1 | Don't pass `--reset-used` unless you mean it. Phase 1 auto-carries-forward by default |
