# DOORS mapping — schema reference

Since 1.20.0 the DOORS mapping is split into two halves so the user
only ever has to touch 3 fields:

| Half | Path | Owner | Contains |
|---|---|---|---|
| **Skeleton** (skill-bundled) | `assets/doors_mapping_skeleton.yaml` | skill | All fixed structural fields: `template`, `defaults`, `columns`, `anchor`, `value_maps`, `extract`, `strategy`, `updates`. Read-only. |
| **Overrides** (user input) | `inputs/DiagComm.xlsx::Sheet 'DOORS Upload'` | user | Just `doors.document_uuid`, `mode`, `upload.dry_run`. Edited once per project. |

At runtime, `scripts/excel_loader.py` reads the 3 user fields from
the xlsx, deep-merges them into a copy of the skeleton, and writes
the merged result to `.cache/doors_mapping.yaml` (gitignored). Every
DOORS script (`doors_sync.py`, `build_doors_payload.py`,
`doors_helper.py`) reads the cached file. **You don't run the loader
manually** — it is auto-called at the start of every DOORS command
based on file mtimes.

This document describes the schema of the **merged** result, which
is what every consumer sees. The schema supports two filling models
for the upload Excel:

| Model | Use when | Required blocks |
|---|---|---|
| **A — fixed cells** (`fill:`) | Template has a small, fixed set of named cells to write (one upload row, named cells like `B2`, `B5`). | `doors`, `fill` (+ optional `extract`, `upload`) |
| **B — column-style rows** (`template:` + `defaults:` + `columns:`) | Template has a header row with named columns and N data rows below. Each upload produces one or more data rows. | `doors`, `template`, `defaults`, `columns`, optionally `anchor`, `mode`, `updates`, `strategy` |

Pick whichever matches your DOORS-side template. `diagcomm-toolkit` uses
Model B (one row per arxml file modified). The shipped skeleton is
already in Model B; do not change the model unless the DOORS-side
template changes.

The skeleton is **skill-owned** (`assets/doors_mapping_skeleton.yaml`).
The toolkit never overwrites the user's xlsx and never lets the user
hand-edit the skeleton. To re-pull the skeleton:
`git checkout -- assets/doors_mapping_skeleton.yaml`.

---

## `doors` block

Tells the agent which DOORS document to talk to.

```yaml
doors:
  document_uuid: "550e8400-e29b-41d4-a716-446655440000"  # REQUIRED, fixed per project
  module_path:   "/<DocTree>/Diag/CusDiag"               # optional, human-readable
  module_id:     "12345"                                  # optional, numeric id
  export_format: "json"                                   # only "json" supported today
```

### `document_uuid` (required, **user-input via Excel**)

The canonical, **fixed** identifier of the DOORS document. Each
project / module has a single UUID; once a colleague writes it in,
it never changes. Look it up in DOORS (Properties → URL/UUID, or
whatever the deployment exposes) and paste it verbatim into
`inputs/DiagComm.xlsx::Sheet 'DOORS Upload'::doors.document_uuid`.

The toolkit refuses to proceed if `document_uuid` is missing or
still the placeholder `PUT-DOORS-DOCUMENT-UUID-HERE`.

### Why `module_path` / `module_id` are optional

Different DOORS MCP servers accept different identifiers. Some take only
the UUID; others also accept a path. We keep `module_path` and `module_id`
around so the agent can pick whichever the discovered tool wants — see
[`tool_inventory.md`](./tool_inventory.md). When in doubt, fill in only
`document_uuid`.

### How the agent reads this block

Use the `show-target` subcommand to extract the block deterministically:

```bash
python <skill>/scripts/doors_helper.py show-target \
    --mapping .cache/doors_mapping.yaml
```

(The cache is auto-refreshed from `inputs/DiagComm.xlsx` first.)

stdout is a JSON object with the fields above. The agent feeds the relevant
fields into the `doors__read_module` / `doors__import_excel` MCP tool calls.

| Exit | Meaning |
|---|---|
| 0 | All required fields present and non-placeholder. |
| 1 | Placeholder values still in the file — the agent must stop and ask the user to fill in `document_uuid`. |
| 2 | `doors:` block missing or `document_uuid` absent. |

---

## `extract` block

A nested map of `{name: {json_path, required?}}`. Names may be nested for
grouping; the leaves are the actual queries.

```yaml
extract:
  insertion_object_id:
    json_path: "objects[?title=='DiagComm Parameters'].id"
    required: true                    # default true; mark optional with false
  parent_object_id:
    json_path: "module.parent_id"
    required: false
  module_meta:
    last_modified:
      json_path: "module.last_modified"
      required: false
    revision:
      json_path: "module.revision"
```

Run with:

```bash
python <skill>/scripts/doors_helper.py extract-many \
    --json-file <export.json> \
    --mapping <doors_mapping.yaml> \
    --out <extracted.json>
```

Output is a JSON object with the *flat dotted* names, e.g.:

```json
{
  "insertion_object_id": "OBJ-9123",
  "module_meta.last_modified": "2026-04-27T12:00:00Z",
  "module_meta.revision": "v3.2"
}
```

### `json_path` mini-syntax

Subset of JSONPath, sufficient for the DOORS dumps we handle:

| Syntax | Meaning |
|---|---|
| `a.b.c` | nested keys |
| `a.b[0]` / `a.b[-1]` | integer index |
| `a.b[*]` | every element of a list / every value of a dict |
| `a.b[?key=='value']` | filter list-of-dicts by exact equality (single quotes) |

Multiple matches collapse into a list. Single match returns the scalar.

---

## `fill` block

A list of `{cell, source}` entries describing what to write into the Excel
template.

```yaml
fill:
  - cell: "B2"
    source: "extract.insertion_object_id"
  - cell: "B3"
    source: "extract.module_meta.last_modified"
    optional: true                    # don't fail if source missing
  - cell: "B5"
    source: "extras.fscs_text"        # injected via --extras fscs_text="..."
  - cell: "B6"
    source: "literal:DiagComm baseline"
```

### `source` prefixes

| Prefix | Resolves to |
|---|---|
| `extract.<dotted>` | a key in the JSON produced by `extract-many` |
| `extras.<key>` | a `key=value` pair passed via `--extras` |
| `literal:<text>` | the text after `literal:`, used verbatim |

### Excel cell references

Standard A1 notation only (`A1`, `B2`, `AA10`). Range writes (`A1:B2`) are
not supported — split into multiple entries.

---

## `upload` block (optional)

```yaml
upload:
  sheet: "Sheet1"                       # which sheet to fill (default = active sheet)
  target_module: "/<DocTree>/..."       # passed verbatim to the import tool;
                                        # defaults to doors.module_path if absent
  dry_run: false                        # advisory; agents should also gate on user "yes"
```

---

## Validation rules

`build_doors_payload.py` and `doors_helper.py` validate the mapping at
runtime. They will exit 2 if:

- `fill` references an unresolved `extract.*` and the entry isn't `optional: true`.
- `extras.<key>` is referenced but not provided via `--extras`.
- `cell:` is missing or not a valid A1 reference.
- `extract:` has a leaf without `json_path`.

---

# Model B — column-style row uploads

Use this when the DOORS-side import template looks like:

```
row 1   sizeRow | <n> | sizeColumn | <m>     (meta header)
row 2   ColumnA | ColumnB | ColumnC | ...    (column-name row)
row 3+  data row 1
        data row 2
        ...
```

Caller skills (e.g. `diagcomm-toolkit`) own the row generation — they
build a list of `{column_name: value}` dicts and feed them into their
own per-skill builder script (e.g. `build_doors_payload.py`). The
yaml's job is to pin down (a) where the rows go, (b) what the static
columns hold, and (c) how dynamic columns get their values.

## `template` block (required)

```yaml
template:
  path:        "assets/doors_template.xlsx"   # caller-relative
  sheet:       "CS Data"
  header_row:  2          # 1-based row index of the column-name row
  data_start:  3          # 1-based row index of the first data row
  size_row:    1          # 1-based row index of the meta header
                          # ('sizeRow' / 'sizeColumn' cells are auto-refreshed)
```

## `strategy` (required)

| Value | Meaning |
|---|---|
| `per_arxml` | one data row per arxml file the caller modified |
| `single_row` | a single data row; per-row dynamic columns get aggregated |

Caller skills define which strategies they support. `diagcomm-toolkit`
supports both, with `per_arxml` as default.

## `anchor` block (insert mode only)

Tells the caller's builder which DOORS row to attach new content
*after*. The lookup happens at run time against the JSON dump
downloaded by the agent — so no per-project hand-picking of identifiers.

```yaml
anchor:
  by_heading:    "CAN ID and Timing Requirements"   # primary rule
  heading_field: "DescriptionOfRequirementRB"        # which JSON field carries the heading text

  # optional fallbacks, tried in this order if the primary rule misses:
  # by_identifier:      "<DOC>_SWFS_<SECTION>_NNN"   # exact row identifier
  # by_absolute_number: 400                          # row's DOORS AbsoluteNumber
```

Resolution order: `by_identifier` → `by_heading` → `by_absolute_number`.
The first rule that hits wins; the resolved row's `identifier` lands
in column B of every data row; the resolved row's `AbsoluteNumber` is
also surfaced in the report (informational only, never written into
the upload xlsx in insert mode).

If **no** rule matches, the builder exits 2 with a
`anchor not found in doors_export.json` error.

## `mode` (required for column-style)

| Value | Column B (Destination Object) | Column D (AbsoluteNumber) | Notes |
|---|---|---|---|
| `insert` (default) | resolved anchor identifier | blank | DOORS lays rows down sequentially after the anchor in xlsx order |
| `update` | blank | per-arxml AbsoluteNumber from `updates` (or `--update-abs`) | DOORS overwrites the existing rows in place |

The CLI flag `--mode insert|update` overrides the yaml.

## `updates` block (update mode only)

Per-arxml AbsoluteNumber to overwrite. Equivalently, callers can
omit this block and pass `--update-abs <arxml>=<n>` flags at the CLI
(one flag per arxml that appears in the diff).

```yaml
updates:
  CanTp_CusDiag_EcucValues.arxml:    405
  Can0_CusDiag_EcucValues_ESP.arxml: 410
```

Update mode requires every arxml in the diff to have an entry; the
builder exits 2 with an explicit list if any are missing.

## `defaults` block

Static values written into every data row. The keys are the **column
header names** (verbatim, from row 2 of the template).

```yaml
defaults:
  isPicture:                "no"
  RB_RS_CP_Status:          "accepted"
  RB_Product:               "DPB"
  RB_Configuration:         "DCOM_ReferenceDiagnosis_CUST"
  RB_Realizing_SWComponent: "CUBAS"
  …
```

## `columns` block (dynamic overrides)

Per-cell sources, keyed by column header name. Resolution rules:

| Prefix | Resolves to |
|---|---|
| `extras.<key>` | a key in the per-run extras dict (caller-supplied) |
| `row.<key>` | a per-row context value (`row.arxml`, `row.destination`, `row.absolute_no`, `row.fscs_chunk`, `row.diff_chunk`, `row.param_count` — caller-defined) |
| `literal:<text>` | the text after `literal:`, with `extras.foo` / `row.foo` substrings expanded inline |
| `map:<map_name>:<inner>` | first resolve `<inner>` (any other prefix), then translate it through `value_maps.<map_name>` (see below). Fails clearly if the resolved value is not a key in the map. |

Example:

```yaml
columns:
  "Destination Object":   "row.destination"
  "Absolute Number":      "row.absolute_no"
  "Object Heading":       "literal:DiagComm baseline @ extras.generated_at"
  "Object Text":          "row.fscs_chunk"
  "RB_Realizing_SWitem":  "row.arxml"
  "RB_Product":           "map:RB_Product:extras.product_type"
```

In insert mode `row.absolute_no` is the empty string and `row.destination`
holds the anchor identifier; in update mode the roles flip.

## `value_maps` block (optional, for `map:` sources)

Lookup tables keyed by map name. Used when the caller-side enum and
the DOORS-side cell vocabulary don't match exactly.

```yaml
value_maps:
  RB_Product:
    DPB: "DPB"
    ESP: "ESP 10"
    IPB: "IPB 2.0"
    RBU: "RBU"
```

Resolution: a `columns:` source like
`"map:RB_Product:extras.product_type"` first resolves
`extras.product_type` (e.g. `"ESP"`), then looks it up in
`value_maps.RB_Product` and writes `"ESP 10"` into the cell.

If the resolved value is not in the map, the builder exits 2 with a
message that lists the known keys, e.g.

> `value_maps.RB_Product has no entry for 'BWA' (known keys:
>  ['DPB', 'ESP', 'IPB', 'RBU']); add it to assets/doors_mapping_skeleton.yaml`

## Model-B validation rules

The caller's builder script validates at runtime and exits 2 when:

- `template.path` does not exist.
- `template.sheet` is not in the workbook.
- `header_row` has no non-empty cells.
- A `columns` source references an unknown `extras.*` / `row.*` key.
- `mode: insert` and the `anchor` block does not match any row of
  `outputs/doors_export.json`.
- `mode: update` and at least one arxml in the diff has neither an entry
  in `updates:` nor a matching `--update-abs` flag.
- A `columns:` source uses `map:<name>:<inner>` but `value_maps.<name>`
  is missing, or the resolved `<inner>` value is not a key in the map.
