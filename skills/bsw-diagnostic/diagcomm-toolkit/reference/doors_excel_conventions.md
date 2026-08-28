# Excel conventions for DOORS upload

DOORS imports an `.xlsx` file as a sequence of objects, attribute-by-attribute.
The exact column layout depends on the DOORS-side import template — the
toolkit does **not** invent columns; the caller skill provides the template
and the cell mapping.

This document captures the assumptions that the toolkit's `lint-excel` and
`fill-excel` rely on.

---

## File-level requirements

- Format: **`.xlsx`** (the modern OOXML format). `.xls` is not supported.
- One workbook per upload. Multi-sheet workbooks are allowed; only the
  sheet named in `upload.sheet` (or the active sheet if absent) is written.
- The template **already exists** before the upload. The toolkit fills cells
  but never creates a workbook from scratch.
- Cell references in `fill:` use standard A1 notation (`A1`, `B2`, `AA10`).
- Merged cells: write into the **top-left** cell of the merge; openpyxl
  ignores writes to other cells in the merged range.

---

## What the linter checks

Run via:

```bash
python <skill>/scripts/doors_helper.py lint-excel --excel <path>.xlsx
# stricter DOORS-acceptance check (Application/sharedStrings/meta types):
python <skill>/scripts/doors_helper.py lint-doors-xlsx --excel <path>.xlsx
```

| Check | Pass | Fail action |
|---|---|---|
| File exists | yes / no | exit 2 |
| Extension is `.xlsx` | yes / no | exit 1 (warn) |
| openpyxl can open the workbook | yes / no | exit 2 |
| At least one sheet | yes / no | exit 1 (warn) |
| At least one non-blank cell in first 50 rows | yes / no | exit 1 (warn) |

The linter is intentionally lax: DOORS-specific column rules (e.g. "column A
must be the object ID") are too template-dependent to bake in. Add caller-
specific checks in the caller skill if needed.

---

## Caller-skill checklist

When you build a new caller skill that uploads to DOORS:

1. **Get the DOORS-side template**. Ask the user / a DOORS admin for the
   exact `.xlsx` template DOORS expects. Save it under
   `<your-skill>/assets/doors_template.xlsx`.
2. **Document the cell layout**. Add a short section in your skill's
   reference docs naming each cell that gets filled.
3. **Decide what goes where** in `<your-skill>/assets/doors_mapping_skeleton.yaml` (or wherever your sibling skill's mapping lives).
4. **Smoke-test** by running `build_doors_payload.py` (or the column-style
   builder in your skill) to write `outputs/doors_upload.xlsx`, then run
   `doors_helper.py lint-doors-xlsx --excel outputs/doors_upload.xlsx`
   to confirm DOORS-acceptance before involving the real upload tool.

> **CRITICAL — xlsx generator matters:** DOORS' import endpoint silently
> rejects (or hangs on) xlsx files whose `docProps/app.xml` lists
> `Application` as anything other than `"Microsoft Excel"`. openpyxl
> tags files as `"Openpyxl 3.x"`; **always use xlsxwriter** for the
> file you intend to upload. `lint-doors-xlsx` checks for this.
5. **Then** call the `doors__import_excel` MCP tool.

---

## Common pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Wrote into a merged cell's non-anchor | cell looks empty in Excel | use the top-left cell of the merge |
| Wrote a Python list / dict | Excel cell shows `[1, 2, 3]` | extract to scalar in `extract:` (use `[?...]` filter or `[0]`) |
| Used `.xls` template | `openpyxl` fails to open | save as `.xlsx` first |
| FSCS text contains line breaks | cell shows `\n` literal | enable wrap-text in the template's cell style; openpyxl preserves newlines |
| Numeric DOORS IDs lose leading zeros | `0042` becomes `42` | format the cell as Text in the template, or pass values as strings |
