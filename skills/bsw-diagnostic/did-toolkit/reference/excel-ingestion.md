# Excel Ingestion — Agent-Driven Phase 1 Input

> **Self-containment + genericity.** `did-toolkit` is a stand-alone,
> **project-agnostic** skill. It has **no runtime dependency** on
> `did_extract` or any other external skill, **and no built-in
> template parser for any specific customer**. The only thing fixed
> by `did-toolkit` is the Phase 1 **input record schema** — the JSON
> that `scripts/fscs/builder.py` consumes. *How* you get from a
> customer's diagnostic-questionnaire `.xlsx` to that JSON is up to
> the agent on every new questionnaire; only the output shape is a
> contract.

Phase 1 accepts schema-compliant `*_did.json` only — drop an `.xlsx`
directly into `.DCOM_AI/DID_Toolkit_PRJ/inputs/` and Phase 1 will refuse it. The
agent-driven extractor is the **sole** ingestion path, and it is
**automatically triggered** by `--init-project` when workbooks are
detected without a corresponding JSON.

This document is the canonical guide for ingesting a new questionnaire.
Read it whenever Phase 1 needs a workbook (any workbook) converted to
the canonical `*_did.json`.

---

## 1. The one-tier model

`did-toolkit` ships exactly one ingestion path. The agent reads the
workbook, infers the structure, writes a one-off Python script (or
notebook), and produces a `.json` matching §2. Phase 2 / Phase 3 /
the reviewers / DOORS upload all see the same JSON regardless of how
it was produced.

| Step | Owner | Output |
|---|---|---|
| Detect workbooks | `--init-project` | `[AGENT ACTION] auto-extract` signal when no JSON exists |
| Open the `.xlsx`, inventory sheets / header rows / language | Agent | A short read-out shared with the operator |
| Write `.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py` (one-off; not reusable) | Agent | A Python script committed alongside the workspace |
| Run the extractor | Agent (in the same turn) | `.DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json` |
| Re-run `--init-project` | Agent | Advances workspace to QUESTIONNAIRE_READY |
| Validate via `python pipeline.py --validate --input .DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json` | Operator | Pydantic-level pass / fail report |
| Run Phase 1 | Operator | `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json` + `fscs_edit.xlsx` |

**Multi-workbook flow.** When `inputs/` holds more than one `.xlsx`,
the agent lists every candidate and asks the operator to pick which
one to process. The chosen workbook gets an extractor; the rest are
left in place for future runs.

**Coexistence notice.** When a `*_did.json` already exists alongside
one or more workbooks, `--init-project` prints an `[AGENT NOTICE]`
reminding the operator that the workbook may be newer. The agent
prompts whether to re-extract; the existing JSON remains
authoritative unless the operator explicitly asks for a refresh.

**Failure handling.** If the extractor fails (bad header, missing
column, unreadable sheet, etc.), the agent reports the error and
**stops** — it does not silently retry, auto-delete the workbook, or
generate a partial JSON. The operator must inspect the workbook and
intervene. This is intentional: a failed extraction usually means
the questionnaire structure is novel or corrupted, and the agent
needs operator guidance before proceeding.

There is no "auto-detected template" shortcut anymore — even if the
new workbook looks identical to a previous customer's. The extractor
adapter is one-off by design: it lives in the workspace, gets
reviewed alongside the project's other artefacts, and is regenerated
when the questionnaire structure changes. The skill itself stays
clean of customer-specific column maps.

---

## 2. The fixed JSON contract (the only thing that is not negotiable)

Phase 1's `scripts/fscs/builder.py` accepts a `list[dict]` where each
dict describes one DID. The full per-field specification, validators,
and `sub_fields` schema live in [`input-format.md`](input-format.md);
**read that file first** before writing any extraction logic.

Minimal mental model — one DID record:

```python
{
    "did_hex":          "0x5001",          # uppercase 4-hex, "0x"-prefixed
    "did_name_en":      "Vehicle mode",    # free English, spaces ok
    "did_name_zh":      "车辆模式",         # optional CJK
    "cvt":              "U",               # U / C / T (CVT class)
    "supported_by_ecu": "Y",               # Y / N — gate at builder
    "rw_state":         "R",               # R / W / RW
    "size_bytes":       "1",               # digit string; "TBD" if unknown
    "data_type":        "Hex",             # see SubFieldDataType (input-format.md §sub_fields.data_type)
    "storage_pos":      "RAM",             # RAM / EEPROM / ROM (NVM == EEPROM)
    "access": {
        "service_22": {
            "application": {"default": "Y", "programming": "N", "extended": "Y"},
            "boot":        {"default": "N", "programming": "N", "extended": "N"},
            "security":    {"level0": "Y", "level1": "Y", "level_fbl": "N"},
        },
        "service_2e": { ...same shape... },
    },
    "sub_fields": [
        {
            "byte":              "0",
            "bit":               "0~3",
            "name_en":           "Vehicle mode status",
            "name_zh":           "车辆模式状态",
            "range_min_phy":     "0",
            "range_max_phy":     "15",
            "unit":              "",
            "method_en":         "0x00=Normal Mode\n0x01=Manufacture Mode\n...",
            "method_zh":         "0x00=正常模式\n0x01=制造模式\n...",
            "default_value_phy": "0x01",
            "data_type":         "Numeric",     # optional, schema 1.3+
            "encoding":          "Unsigned",    # optional, schema 1.3+
        },
    ],
}
```

**Hard rules** (the builder rejects any record that violates these):

* `did_hex` must normalise to `0xXXXX` (4 uppercase hex chars). Lowercase,
  trailing `h`, raw integer, `0X` prefix — all accepted on input but the
  output **must** be the canonical form.
* `rw_state` must be one of `R` / `W` / `RW`. Never hard-code; derive
  from the Excel column / sheet that actually says so.
* `access.service_{22,2e}` must always exist with the **full nested
  shape** (application / boot / security blocks, all leaves Y/N). For a
  service the DID does not support, fill every leaf with `"N"`.
* If the same DID appears in both a `$22` and a `$2E` source (or a
  read-side and write-side sheet), **OR-merge** the access blocks
  (`Y` wins over `N`); promote `rw_state` to `RW`.
* Security inclusion rule: if `level0 == "Y"` then `level1` must also be
  `"Y"` (high level implies low level). The reviewer will flag a
  violation; pre-correct in the extractor.

Anything not in the contract above (`num`, hardcoded comments,
extraction provenance, …) is allowed as extra keys — the builder
ignores unknown top-level fields.

---

## 3. Agent-driven workflow

Every workbook — there is no built-in parser, regardless of
customer:

### Step 1 — Inspect the workbook

```python
import openpyxl
wb = openpyxl.load_workbook(
    ".DCOM_AI/DID_Toolkit_PRJ/inputs/<file>.xlsx",
    data_only=True,
    read_only=True,
)
print(wb.sheetnames)
for name in wb.sheetnames:
    ws = wb[name]
    print(name, ws.max_row, ws.max_column)
    # peek at the first ~10 header rows
    for row in ws.iter_rows(min_row=1, max_row=10, values_only=True):
        print(row)
```

Identify:

1. **Which sheet(s) hold DID data.** (Skip cover pages, change logs,
   reference tables, summary dashboards.)
2. **Header row(s).** Some templates use a 1-row header, some have a 2-
   or 3-row composite header with merged cells. Pick the row whose
   cells uniquely name the columns you need.
3. **Service partitioning.** Are read DIDs and write DIDs on separate
   sheets? Mixed in one sheet with an `R/W State` column? Or some
   third arrangement?
4. **Sub-field rows.** Are sub-fields on separate rows beneath the DID
   header row? Inline as a multi-line cell? Listed in a side-table?
5. **End-of-data sentinel.** Some templates use an explicit
   `#EndOfData` marker; many just run out of rows. Decide a stop
   condition before writing the loop.

### Step 2 — Write a one-off extractor

Drop the script into the workspace, run it, dump JSON. The
extractor's home is **`<project-root>/.DCOM_AI/DID_Toolkit_PRJ/scripts/`** —
NOT the skill's own `scripts/` folder. Putting it in the
workspace keeps the skill install pristine and lets the operator
commit the extractor next to the questionnaire it parses.

```
<project-root>/.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py    # one-off; per-workspace, not in the skill
<project-root>/.DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json       # result; pipeline auto-discovers it
```

`--init-project` creates an empty `.DCOM_AI/DID_Toolkit_PRJ/scripts/` slot for
you so the location is unambiguous.

Skeleton:

```python
#!/usr/bin/env python3
"""Extract DIDs from <customer> questionnaire <file>.xlsx -> inputs/<customer>_did.json.

One-off agent-written extractor. NOT a reusable parser.
"""
import json
import sys
from pathlib import Path

import openpyxl

# The skill ships no shared workbook-parsing helpers — each
# extractor is fully self-contained. Write small private helpers
# right here for hex normalisation, Y/N coercion, etc. Keeping the
# helpers local to the extractor is intentional: the skill stays
# generic.

# Launch this script from the project root (the typical workflow —
# operator ``cd``s into the container and runs
# ``python .DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py``). Inputs and
# outputs both live under .DCOM_AI/DID_Toolkit_PRJ/inputs/.
SOURCE = Path(__file__).resolve().parent.parent / "inputs" / "<file>.xlsx"
OUT    = Path(__file__).resolve().parent.parent / "inputs" / "<customer>_did.json"

def extract():
    wb = openpyxl.load_workbook(SOURCE, data_only=True, read_only=True)
    records = []
    # ... walk the sheet(s), build one dict per DID, populate access ...
    # ... OR-merge across services if the same DID appears in both ...
    # ... attach sub_fields ...
    return records

def main():
    records = extract()
    for i, rec in enumerate(records, start=1):
        rec["num"] = i
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(records)} records to {OUT}")

if __name__ == "__main__":
    main()
```

### Step 3 — Validate before running Phase 1

```bash
# Run from the project container; --input is workspace-relative.
python <skill>/scripts/pipeline.py --validate --input .DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json
```

`--validate` exercises the full Pydantic schema (the same one Phase 1
uses) without writing any output. Any field-level violation is reported
with the offending `did_hex` + path. Fix in the extractor, re-run, until
clean.

### Step 4 — Run Phase 1 as usual

```bash
python <skill>/scripts/pipeline.py --phase fscs --input .DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json
# or, if it's the only candidate in .DCOM_AI/DID_Toolkit_PRJ/inputs/:
python scripts/pipeline.py --phase fscs
```

Pipeline auto-discovery picks up `*_did.json` files in
`.DCOM_AI/DID_Toolkit_PRJ/inputs/`. `.xlsx` files are never auto-discovered —
workbooks must be converted to JSON via your extractor before
Phase 1 will accept them.

### Step 5 — Iterate

The console output of Phase 1 calls out:

* `Total records: N` — sanity-check vs. the questionnaire's declared
  DID count.
* `Kept / Filtered / Skipped` — `Skipped` means schema validation
  failed for a record; the per-DID detail is in
  `outputs/fscs/fscs_generation_report.txt`.
* `Service 22 / Service 2E supported / effective` counts — verify the
  access merge semantics are doing what you expect.

If any of these look wrong, edit the extractor (not the JSON) and
re-run Phase 1. Treat the extractor script as the source of truth, not
the JSON it produces.

---

## 4. Helper primitives (write them locally; do not share)

The skill ships no shared workbook-parsing helper module — every
extractor is fully self-contained. Below is the canonical set of
cell-normalisation primitives. Copy what you need into the
extractor file directly.

```python
def _normalize_did_hex(raw):
    """Raw cell -> '0xXXXX' (upper, zero-padded) or None."""
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s.startswith("#endofdata"):
        return None
    if s.endswith("h"):
        s = s[:-1]
    if s.startswith("0x"):
        s = s[2:]
    try:
        v = int(s, 16)
    except ValueError:
        try:
            v = int(float(s))
        except (TypeError, ValueError):
            return None
    return f"0x{v:04X}"

def _coerce_size(raw):
    """Raw cell -> digit string ('1', '16') or 'TBD'."""
    if raw is None or str(raw).strip() == "":
        return "TBD"
    s = str(raw).strip().lower().replace("bytes", "").replace("byte", "").strip()
    try:
        return str(int(float(s)))
    except (TypeError, ValueError):
        return "TBD"

def _normalize_yn(raw, default="N"):
    """Tolerant Y/N coercion. 'Y'/'yes'/'true'/'1'/'x'/'✓' all -> 'Y'."""
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if s in ("y", "yes", "true", "1", "x", "✓", "support", "supported"):
        return "Y"
    if s in ("n", "no", "false", "0", "", "-", "/", "—"):
        return "N"
    return default

def _normalize_rw(raw, default="R"):
    """'R/W' / 'RW' / 'RWX' -> 'RW'; 'R' / 'read' -> 'R'; 'W' / 'write' -> 'W'."""
    if raw is None:
        return default
    s = str(raw).strip().lower().replace("/", "").replace(" ", "")
    if "r" in s and "w" in s:
        return "RW"
    if "w" in s:
        return "W"
    if "r" in s:
        return "R"
    return default
```

The default-access skeleton and OR-merge helper are boilerplate
every extractor writes out by hand — see
[`input-format.md`](input-format.md) for the canonical shape of
`access[svc][sess][sec]`.

---

## 6. What does **not** belong in this skill

* **External skill calls.** `did-toolkit` must not invoke `did_extract`,
  `did-extract`, MCP servers other than DOORS, or any other extraction
  tool. The agent does the dynamic Excel reading directly inside
  `did-toolkit`'s working directory.
* **Sample reference projects from other skills.** If you need
  inspiration for a new template, write a fresh one-off and discard it.
  Don't import or vendor extractors from unrelated tooling — they
  target slightly different schemas and drift quickly.
* **Hand-edited `inputs/<customer>_did.json`.** The JSON is the contract,
  but the extractor script is the source of truth. Re-running the
  extractor must reproduce the JSON byte-for-byte (modulo `num`
  renumbering); hand edits are forbidden because they desync the source
  of truth.

---

## 7. See also

* [`input-format.md`](input-format.md) — the full per-DID record schema
  the extractor must produce. **Authoritative reference.**
* [`architecture.md`](architecture.md) — how Phase 1 wires the records
  list into `FSCSDocument`, the CSV exporter, and Phase 2 / 3.
* [`commands.md`](commands.md) — every `pipeline.py` flag, including
  `--validate`, `--input`, `--reset-used`.
