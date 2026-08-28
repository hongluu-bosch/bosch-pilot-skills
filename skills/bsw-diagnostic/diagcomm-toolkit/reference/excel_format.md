# Excel input format — workspace `inputs/DiagComm.xlsx` (1.20.0+)

Since 1.20.0 the **only** user-edited file is `inputs/DiagComm.xlsx`,
a 4-sheet Excel workbook with data-validation dropdowns, range
checks, and red-highlight required cells. This document is the
authoritative spec for that workbook so an LLM (or a human teammate
porting the skill) can answer:

- Which sheets exist, and in what order?
- What does each row mean? Which column does the user edit?
- What validation does Excel enforce on each Value cell?
- How are values typed and coerced when the loader reads the file?
- How is the workbook regenerated from `<skill>/assets/DiagComm_schema.json`?

> **v2.0.0 path note**: the workbook lives at
> `<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/inputs/DiagComm.xlsx`
> (workspace), copied there from
> `<skill>/assets/inputs_template.xlsx` (skill) by `pipeline.py
> --init-project`. `<skill>` = the user-level install, typically
> `~/.cursor/skills/diagcomm-toolkit/`. The skill checkout itself
> never carries a per-project `inputs/DiagComm.xlsx`.

If you change the schema, **also re-run**
`python <skill>/scripts/build_inputs_template.py` so
`<skill>/assets/inputs_template.xlsx` (the master copy of the
workbook) stays in sync. See [Lifecycle](#lifecycle) below.

---

## Workbook layout

| # | Sheet name | Owns | Edit cadence |
|---|---|---|---|
| 1 | `Project & Parameters` | `project.name`, `project.product_type`, all 23 `parameters.*` leaves | Every spec change |
| 2 | `Paths & Options`      | `paths.*` (base_dir, dcom_root, ARXML file templates) + `options.*` | Once per project; standard layout = zero edits |
| 3 | `DOORS Upload`         | `doors.document_uuid`, `mode`, `upload.dry_run` | Once per project (replace placeholder UUID) |
| 4 | `README`               | Static cheat-sheet of field types / ranges / encoding rules | **Read-only** |

The first 3 sheets are *data* sheets; the loader iterates them by
name. The 4th sheet is human documentation only — the loader skips
it. Order matters only for human reading; the loader uses the sheet
names as keys.

---

## Common row format (Sheets 1–3)

Every data row has the same 5 columns:

| Col | Header | Editable? | Purpose |
|---|---|---|---|
| A | `Field` | no | Dotted path into the unified config (e.g. `parameters.CAN_DLC.rx_frame_type`). The loader uses this verbatim as the key when building the cache. |
| B | `Value` | **yes** | The user's input. Required cells start blank with red conditional fill; data validation enforces type + range as the user types. |
| C | `Type` | no | One of `string` / `enum` / `int` / `float` / `hex` / `bool`. Drives both the Excel data-validation rule (column B) and the loader's coercion. |
| D | `Allowed / Range` | no | Either an enum list (`DPB / ESP / IPB / RBU`) or a range (`0..127`) or empty for free-form fields. |
| E | `Description` | no | One-line Chinese description for the user. |

The header row (row 1) is frozen and bolded. Data rows start at row 2.

> **Never edit columns A, C, D, or E.** They are regenerated from
> `<skill>/assets/DiagComm_schema.json` whenever
> `<skill>/scripts/build_inputs_template.py` runs. If you need to
> change one of them, edit `<skill>/assets/DiagComm.txt` (and / or
> `build_inputs_template.py`), regenerate the schema (`pipeline.py
> gen-schema`), then regenerate the template
> (`build_inputs_template.py`). Each project's existing
> `<workspace>/inputs/DiagComm.xlsx` is **not** auto-upgraded — users
> hit `python <skill>/scripts/pipeline.py --init-project --force` to
> opt in (which clobbers their filled values, so back up first).

---

## Sheet 1 — `Project & Parameters`

### Required (red-highlighted) fields

The 9 cells the user **must** fill. Each one carries an Excel data
validation that prevents an invalid value from being typed.

| Field | Type | Validation in Excel |
|---|---|---|
| `project.name` | string | none — free text, but red-fill until non-empty |
| `project.product_type` | enum | dropdown: `DPB / ESP / IPB / RBU` |
| `parameters.CAN_DLC.rx_frame_type` | enum | dropdown: `ClassicCAN / CANFD` |
| `parameters.CAN_DLC.tx_frame_type` | enum | dropdown: `ClassicCAN / CANFD` |
| `parameters.CAN_DLC.rx_dl` | enum | dropdown: `8 / 64` |
| `parameters.CAN_DLC.tx_dl` | enum | dropdown: `8 / 64` |
| `parameters.CAN_Functional_Request_ID` | hex | red-fill until non-empty; `0x` prefix preserved |
| `parameters.CAN_Physical_Request_ID` | hex | red-fill until non-empty; `0x` prefix preserved |
| `parameters.CAN_Response_ID` | hex | red-fill until non-empty; `0x` prefix preserved |

> The "9 required cells" count is also enforced by the runtime
> (`<skill>/scripts/excel_loader.py::validate`) — if Excel doesn't
> trip the user, the pipeline does on the next `status` / `validate`
> call.

### Optional (defaulted) fields

Everything else on Sheet 1 is **optional**. Leaving the Value cell
blank means "use schema default" — the loader fills the gap from
`<skill>/assets/DiagComm_schema.json` at coercion time. Examples:

| Field | Type | Default | Range |
|---|---|---|---|
| `parameters.CAN_Channel` | int | `0` | `0..3` |
| `parameters.CAN_ID_Format` | enum (`11bit / 29bit`) | `11bit` | — |
| `parameters.Addressing_Method` | enum (`Normal / Mixed`) | `Normal` | — |
| `parameters.PaddingByte` | hex | `0x00` | `0x00..0xFF` |
| `parameters.StrictDlcCheck` | bool | `TRUE` | `TRUE / FALSE` |
| `parameters.N_As` … `parameters.N_Cr` | int (ms) | per schema | `1..1000` |
| `parameters.P2_Max` | int (ms) | `50` | `1..1000` |
| `parameters.P2_Star_Max` | int (ms) | `5000` | `1..60000` |
| `parameters.BS` | int | `0` | `0..255` |
| `parameters.STmin` | float (ms) | `0` | `0..127` |
| `parameters.NRC78_Times` | int | `10` | `0..127` |

The full inventory + transforms lives in
[`parameter_types.md`](./parameter_types.md).

---

## Sheet 2 — `Paths & Options`

### Paths (`paths.*`)

| Field | Default | When to change |
|---|---|---|
| `paths.base_dir` | `../..` | The workspace lives at a non-default depth under the project root. The default `../..` is correct when `<workspace>` = `<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/` (i.e., what `--init-project` produces). |
| `paths.dcom_root` | `*/rb/as/*/core/app/dcom` | The project tree is missing or has an extra level between `<project>/` and `<platform>/`. |
| `paths.cantp_common` | `RBAPLCust/cfg/Common/CanTp_CusDiag_EcucValues.arxml` | almost never |
| `paths.cantp_feature_file` | `Cubas/cfg/CanTp_Feature_EcucValues.arxml` | almost never |
| `paths.dcm_common` | `RBAPLCust/cfg/Common/Dcm_CusDiag_Can_EcucValues.arxml` | almost never |
| `paths.dcm_feature_file` | `Cubas/cfg/Dcm_Feature_EcucValues.arxml` | almost never |
| `paths.dcm_services_common` | `RBAPLCust/cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml` | almost never |
| `paths.can_pt_file` | `RBAPLCust/cfg/{product_type}/Can{can_channel}_CusDiag_EcucValues_{product_type}.arxml` | The project uses a custom CAN-PT filename pattern. |

### Options (`options.*`)

| Field | Default | Validation |
|---|---|---|
| `options.dry_run_default` | `TRUE` | dropdown: `TRUE / FALSE` |
| `options.validate_before_apply` | `TRUE` | dropdown: `TRUE / FALSE` |

---

## Sheet 3 — `DOORS Upload`

Only **3 user-set fields** live here; the rest of the DOORS mapping
(column bindings, value_maps, defaults, anchor) is bundled in
`<skill>/assets/doors_mapping_skeleton.yaml` and merged in at runtime
by the loader.

| Field | Type | Default | What the user does |
|---|---|---|---|
| `doors.document_uuid` | string | `PUT-DOORS-DOCUMENT-UUID-HERE` | **Replace** with the project's DOORS module UUID. The downstream `build_doors_payload.py` rejects the placeholder. |
| `mode` | enum | `insert` | dropdown: `insert / update`. Almost always leave at `insert`; `doors_sync.py` decides automatically based on state. |
| `upload.dry_run` | bool | `FALSE` | dropdown: `TRUE / FALSE`. Set `TRUE` to build the xlsx but skip the HTTP upload. |

---

## Type coercion rules (loader side)

`<skill>/scripts/excel_loader.py::_coerce_value` reads each Value
cell and applies these rules in order. Coercion failures raise a
`LoaderError` with the offending sheet + field path.

| Schema type | Excel input | Stored value |
|---|---|---|
| `string` | text | trimmed; placeholder strings (`<fill-me>`, `<set-me>`, `<bootstrap>`) → `None`. The DOORS placeholder `PUT-...` is preserved verbatim so downstream guards still trip. |
| `enum` | text | trimmed; rejected with a `LoaderError` if not in the schema's `allowed` list (Excel data validation should already prevent this). |
| `int` | int / float / numeric text | coerced to `int`. Rejected if outside `min..max`. |
| `float` | int / float / numeric text | coerced to `float`. Rejected if outside `min..max`. |
| `hex` | int / `"0x..."` text | preserved as `"0xNN"` uppercase, **width preserved** (e.g. `0x00` stays `0x00`, not `0x0`). |
| `bool` | bool / `TRUE` / `FALSE` / `1` / `0` / `Y` / `N` (case-insensitive) | Python `True` / `False`. |
| `object` (nested) | — | Walked recursively per the schema's `fields` map. |

> **Why placeholders → None.** The loader treats sentinel strings as
> "the user has not filled this cell yet" so the downstream
> validation message is precise (`<field> is empty -- fill the
> 'Value' cell on Sheet 'X'`). The DOORS UUID placeholder
> (`PUT-DOORS-DOCUMENT-UUID-HERE`) is intentionally exempted from
> this — `build_doors_payload.py` checks `"PUT-" in module_uuid` and
> errors out with a tailored "fill the real UUID" message that beats
> the generic loader complaint.

---

## Cache pipeline

```text
<workspace>/inputs/DiagComm.xlsx                     ← user edits in Excel
  │
  │  <skill>/scripts/excel_loader.py
  │  (auto-called at the start of every pipeline / DOORS command,
  │   regenerates only when xlsx mtime > cache mtime)
  ▼
<workspace>/.cache/DiagComm_values.json   ← {project, parameters} (gitignored)
<workspace>/.cache/DiagComm_config.json   ← {paths, options}      (gitignored)
<workspace>/.cache/doors_mapping.yaml     ← Sheet 'DOORS Upload' merged with
                                            <skill>/assets/doors_mapping_skeleton.yaml
                                            (gitignored)
  │
  ▼
<skill>/scripts/runtime.py::load_user_inputs()   ← every pipeline / DOORS
                                                   command's single entry point
```

CLI for inspecting the cache (run from the project root):

| Command | Purpose |
|---|---|
| `python <skill>/scripts/excel_loader.py --check` | Validate the xlsx; print errors only (exit 1 on any). |
| `python <skill>/scripts/excel_loader.py --show` | Print the resolved `{project, parameters, paths, options, doors}` to stdout. |
| `python <skill>/scripts/excel_loader.py --dump` | Force-regenerate workspace `.cache/` from the xlsx (bypasses mtime check). |
| `python <skill>/scripts/excel_loader.py --dump --force` | Same; `--force` is an alias for clarity. |

---

## Lifecycle

When the schema or the parameter catalog changes (maintainer-only):

1. Edit `<skill>/assets/DiagComm.txt`.
2. Regenerate the schema:
   ```bash
   python <skill>/scripts/pipeline.py gen-schema
   ```
   This rewrites `<skill>/assets/DiagComm_schema.json`.
3. Regenerate the blank xlsx template:
   ```bash
   python <skill>/scripts/build_inputs_template.py
   ```
   This rewrites `<skill>/assets/inputs_template.xlsx`. Each project's
   existing `<workspace>/inputs/DiagComm.xlsx` is **not** auto-upgraded
   — users opt in via
   `python <skill>/scripts/pipeline.py --init-project --force` (which
   clobbers their filled values, so back up first), or by manually
   merging the new template's rows in Excel.
4. Run the test suite to confirm the loader still round-trips:
   ```bash
   cd <skill>
   pytest tests/test_excel_loader.py -v
   ```
5. Bump `<skill>/VERSION` and add a `<skill>/CHANGELOG.md` entry
   noting the new / removed fields.

---

## Migration from older layouts

| You have… | Run this once per project |
|---|---|
| **v1.20.x in-skill workspace** at `<project>/.agents/skills/diagcomm-toolkit/inputs/DiagComm.xlsx` | `cd <project-root> && python <skill>/scripts/migrate_v1_20_to_v2.py --from-skill <project-root>/.agents/skills/diagcomm-toolkit` — atomic-moves xlsx + state + outputs + cache into `<project>/.DCOM_AI/DiagComm_Toolkit_PRJ/`, rewrites `paths.base_dir` from v1 default `"../../.."` to v2 default `"../.."`. |
| **v1.19.x JSON+YAML triplet** | `cd <project-root> && python <skill>/scripts/pipeline.py --init-project` then `python <skill>/scripts/migrate_v1_19_to_xlsx.py --legacy-from <dir-with-old-json-yaml>`. The second tool reads any combination of `DiagComm_values.json`, `DiagComm_config.json`, `doors_mapping.yaml`, fills the new workbook from them, and prints the `rm` commands for the legacy files (it never deletes them itself — that decision belongs to the user). |

`pipeline.py status` itself **refuses to run** with `BROKEN` status
when either legacy layout is still on disk, with the appropriate
migration command printed in the error.

---

## See also

- [`SKILL.md`](../SKILL.md) — agent playbook (read first)
- [`parameter_types.md`](./parameter_types.md) — full parameter inventory + ranges
- [`doors_mapping_format.md`](./doors_mapping_format.md) — schema for the static `<skill>/assets/doors_mapping_skeleton.yaml`
- `<skill>/scripts/excel_loader.py` — the loader itself (~250 lines)
- `<skill>/scripts/build_inputs_template.py` — the template generator (~200 lines)
