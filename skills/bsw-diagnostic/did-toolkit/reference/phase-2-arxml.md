# Phase 2 — ARXML

> **When to read this.** You're running `--phase arxml`,
> debugging the ARXML merge into the Bosch tree, or working
> with the multi-product `product_type` per-DID tag and the
> per-product fan-out it drives.

Phase 2 reads `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json`, computes the per-run
**product work-set** from every `used` DID's `product_type`
cell (see §3 below), and **fans out** — merging one
per-product ARXML into the Bosch tree (resolved via
`paths.base_dir` + `paths.arxml_file`), each with its own
`validation_report_<suffix>.txt` and `arxml_review_report_<suffix>.txt`
under `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/`.

> **Output contract.** The project tree is the sole sink — there is
> no local `outputs/arxml/<PT>/DID_Config.arxml` mirror. The merge
> is skip-on-conflict by `SHORT-NAME` (existing containers always
> win), so nothing is ever overwritten. Reports stay under
> `.DCOM_AI/DID_Toolkit_PRJ/outputs/`. Phase 2 hard-aborts (exit 2) if
> `paths.base_dir` is missing or empty.

> **Build target.** The build target is the *set* of products
> carried by `used` DIDs in `fscs.json`, not a single CLI value;
> Phase 2 iterates the generator once per product. There is no
> `--product-type` / `-t` flag — passing one fails at argparse.

Module map and templating contract:
[`architecture.md`](architecture.md). ARXML container templates:
[`arxml-structure.md`](arxml-structure.md).

---

## 1. Outputs

Per-product fan-out — every artefact below repeats once per
product in the work-set (`<PT>` ∈ `{DPB, ESP, ESPCL, IPB, RBU,
Common}`).

| File | Role |
|---|---|
| `<base_dir>/<paths.arxml_file resolved per product>` | Generated ARXML for product `<PT>` merged into the Bosch tree. One `ECUC-CONTAINER-VALUE` per effective DID targeting this product (or `Common`), plus shared `DcmDspDidInfo` containers. Existing `SHORT-NAME`s are skipped. |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<PT>/validation_report.txt` | Per-DID outcome for this product's iteration: `SUCCESS` / `SKIPPED` / `ERROR` / `OUT_OF_SCOPE` (DIDs targeting a *different* product in the work-set; they appear in their own iteration's ARXML, not this one's). |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<PT>/arxml_review_report.txt` | Auto-runs after generation. Includes the cross-product SCOPE axis when `paths.arxml_file` contains `{product_type}` and sibling product ARXMLs exist on disk. |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<PT>/merge_report.txt` | `[MERGED] N inserted, M skipped` per product file with the list of skipped `SHORT-NAME`s for the operator to reconcile by hand. |

The `Common` slot uses the literal `Common/` directory name and
its ARXML lands at
`Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml` in the Bosch
tree (Bosch convention; see §3 below).

---

## 2. Bosch-tree merge policy

Every direct `ECUC-CONTAINER-VALUE` child of
`DcmDsp/SUB-CONTAINERS` in `DID_Config.arxml` is considered.
Matches against an existing `SHORT-NAME` in the target are
**skipped** (same conservative policy as Phase 3 `.c` files —
hand-tuned definitions win). New containers are spliced in just
before `</SUB-CONTAINERS>`, preserving every byte of the
existing file upstream/downstream of that splice point.

The merge reports `[MERGED] N inserted, M skipped` per file in
`.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<PT>/merge_report.txt`. The merge is
non-destructive — skip-on-conflict means nothing is overwritten,
so there is no rolling backup.

```bash
# Preview the merge for every product in the work-set (no writes).
python scripts/pipeline.py --phase arxml --dry-run

# Real merge — writes one ARXML per product into the Bosch tree.
# Skip-on-conflict by SHORT-NAME; merge_report.txt lists every skip.
python scripts/pipeline.py --phase arxml
```

---

## 3. Multi-product filter — `product_type`

Per-DID multi-product tag. Stored in `fscs.json` as the per-DID
`product_type` field, surfaced in `fscs_edit.xlsx` as the
`Product_Type` column (positioned right after `used_flag` so the
operator's review eye flows from "is this DID in scope?" to "which
product does it apply to?"). Defaults to the wildcard
``Common``; the schema migrator and field validator collapse
``None`` / blank / missing values to ``Common`` at load time so the
on-disk JSON and the CSV cell always carry an explicit tag.

> **Fan-out driver.** Every distinct value carried by a `used` DID
> becomes its own product in the work-set, and Phase
> 2 / Phase 3 iterate the generator once per product. The
> `OUT_OF_SCOPE` bucket survives but with re-defined semantics
> (see "Validation report buckets" below).

Freshly-built DIDs land with the wildcard default `Common` (the
schema migrator + field validator collapse missing / `None` /
blank values to `Common` at load time, so the on-disk JSON and
the CSV cell always carry an explicit tag). Operators narrow
specific DIDs to `DPB` / `ESP` / `ESPCL` / `IPB` / `RBU` in
`fscs_edit.xlsx` for product-specific routing.

### Build target — derived from fscs.json

There is no "build target" CLI flag. The work-set is computed at
the start of every Phase 2 / Phase 3 invocation by
`scripts/fscs/product_workset.py::compute_workset(document)`:

1. Iterate `fscs.json::dids[]`; skip any DID where both
   `service_22.used` and `service_2e.used` are `False`.
2. Strip + canonicalise the `product_type` cell (case-insensitive
   match against `{DPB, ESP, ESPCL, IPB, RBU, Common}`).
3. Empty / `None` collapses to `Common` (defence-in-depth — the
   schema validator should already have done this at load).
4. Unrecognised values raise `UnknownProductTypeError` and Phase
   2 / Phase 3 abort with a hint at the offending DID hex and the
   legal whitelist (case-insensitive whitelist; typo
   `DPC` → hard error, fix in `fscs_edit.xlsx`).
5. Returned work-set is a deterministic tuple in display order
   (production products alphabetical, `Common` last).

Empty work-set (e.g. all DIDs have `used_flag=FALSE`) is a
warn-and-skip — Phase 2 / 3 print a stderr warning and return
`True` so Phase 4 / DOORS can still run on the same `fscs.json`.

### Operator overrides

| Cell value | Effect on Phase 2 |
|---|---|
| `<empty>` / `<None>` | Collapses to the `Common` slot. The DID is emitted in the `Common/` ARXML. |
| `DPB` / `ESP` / `IPB` / `RBU` (case-insensitive) | The DID joins that product's iteration. Other products' iterations mark it `OUT_OF_SCOPE` and exclude it from their ARXML — but every iteration runs, so the DID still ships in *exactly one* product's ARXML in the Bosch tree. |
| `ESPCL` (case-insensitive) | **Path alias to `ESP`** — ESPCL iterates with its own ESPCL+Common DID set (single-target filter, same as every other PT) but its output lands in the Bosch tree as `cfg/ESP/Dcm_..._ESPCL.arxml` — *next to* ESP's own `Dcm_..._ESP.arxml`, not folded into it. The folder collapse is purely a path rewrite via the `{product_type_arxml_folder}` placeholder; the per-PT filename suffix (`_ESPCL` vs `_ESP`) keeps the two iterations separable. See *Phase-2 product path alias* below. |
| `Common` (case-insensitive) | Owns its own dedicated iteration. The DID lands at `cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml` in the Bosch tree. The cross-product SCOPE reviewer suppresses overlap warnings against `Common`. |

### Validation report buckets

Each per-product iteration writes its own
`.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/validation_report_<suffix>.txt`.
The `<folder>` segment may collapse two PTs into one shared
directory under the path alias, so the `_<suffix>` filename tag
is what disambiguates the per-iteration report. The
`OUT_OF_SCOPE` bucket now reads as "DID belongs to a *different*
iteration of this run" — not "DID is excluded altogether".

```
[SCOPE] 0xF180 ECUSerialNumber - product_type=ESP, this iteration targets product_type=DPB
        (the DID will appear in the 'ESP' iteration's ARXML instead)
...
SCOPE summary: 12 OUT_OF_SCOPE / 145 emitted / 157 considered
```

To trace where a specific DID landed, search for its hex in the
per-product `validation_report.txt` files — exactly one will show
`SUCCESS`, the others (if any) will show `OUT_OF_SCOPE`.

### Cross-product SCOPE reviewer

When `paths.arxml_file` contains `{product_type}` and you have
sibling product ARXMLs in the Bosch tree, the reviewer also
runs a **cross-product SCOPE axis**: any DID `SHORT-NAME`
appearing in more than one product's ARXML (without being tagged
`Common`) raises a `SCOPE` issue in `arxml_review_report.txt`.

Typical cause: a DID was created without setting
`product_type`, leaked into a sibling product's release.
Fix in `fscs_edit.xlsx` (`Product_Type=DPB` to pin, or
`Product_Type=Common` to legitimise the overlap), then re-run
`--phase xlsx-import` and Phase 2.

### ARXML folder + filename convention

The ARXML path splits into two independent placeholder slots.
Both default to canonical Bosch naming; the *folder* slot is
alias-aware (`{product_type_arxml_folder}`), the *filename* slot
is not (`{product_type_suffix}`).

| Slot | Placeholder | Real PTs (`DPB` / `ESP` / `IPB` / `RBU`) | `ESPCL` (alias source) | `Common` |
|---|---|---|---|---|
| **Folder** | `{product_type_arxml_folder}` | upper-case short name (`DPB` / `ESP` / `IPB` / `RBU`) | **`ESP`** (collapses to alias target) | `Common` (title-case literal) |
| **Filename** | `{product_type_suffix}` | upper-case short name (`DPB` / `ESP` / `IPB` / `RBU`) | `ESPCL` (own short name) | `SingleCANID` (Bosch ARXML convention) |

Resulting Bosch paths under the default template
(`cfg/{product_type_arxml_folder}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml`):

| PT | Bosch path |
|---|---|
| `DPB` | `cfg/DPB/Dcm_CusDiag_Services_EcucValues_DPB.arxml` |
| `ESP` | `cfg/ESP/Dcm_CusDiag_Services_EcucValues_ESP.arxml` |
| `ESPCL` | `cfg/ESP/Dcm_CusDiag_Services_EcucValues_ESPCL.arxml` *(co-tenant of ESP)* |
| `IPB` | `cfg/IPB/Dcm_CusDiag_Services_EcucValues_IPB.arxml` |
| `RBU` | `cfg/RBU/Dcm_CusDiag_Services_EcucValues_RBU.arxml` |
| `Common` | `cfg/Common/Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml` |

The local `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/` directory only
carries the per-iteration reports (`validation_report_<suffix>.txt`,
`arxml_review_report_<suffix>.txt`, `merge_report.txt`); no local
copy of the generated ARXML is kept.

`init_project.py` writes the canonical alias-aware template by
default. Hand-edited configs that still carry `{product_type_upper}`
in the folder slot lose the alias; ESPCL writes to `cfg/ESPCL/...`
instead of `cfg/ESP/...`. Two ways to fix:

1. Re-run `python scripts/pipeline.py --init-project` (overwrites
   `paths.arxml_file` with the canonical template).
2. Hand-edit `config/project.json::paths.arxml_file` and swap
   `{product_type_upper}` → `{product_type_arxml_folder}` in the
   folder slot only. Leave the `{product_type_suffix}` filename
   slot alone.

### Phase-2 product path alias: `ESPCL → ESP`

`ESPCL` is conceptually a variant of `ESP` and the Bosch tree has
no `cfg/ESPCL/` directory; ESPCL's diagnostics ARXML is supposed
to live in `cfg/ESP/` next to ESP's own. Phase 2 captures this
with a **path** alias: ESPCL iterates with its own DID set
(single-target filter, ESPCL+Common DIDs only), runs the
classifier and validation reporter independently, and writes its
own ARXML — but the *output paths* are alias-rewritten to ESP's
folder. ESPCL and ESP produce two separate ARXMLs that happen to
live in the same folder.

The alias table is hard-coded in
`scripts/fscs/product_workset.py`:

```python
_PHASE2_PRODUCT_ALIASES: dict[str, str] = {
    "ESPCL": "ESP",
}
```

Adding a new alias is a deliberate code change here, not a config
edit (matches the `_DEFAULT_PRODUCT_TYPE_MAP` / `RECOGNISED_PRODUCTS`
convention).

**What Phase 2 does when `ESPCL` is in the work-set:**

1. `pipeline.run_phase2` logs once per alias source PT in the
   workset:
   `[ALIAS] ESPCL → ESP (Phase 2 path alias): ESPCL's ARXML lands
   in cfg/ESP/ with _ESPCL filename suffix; reports go under
   .DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/ESP/.`
2. ESPCL iterates with its own DID set (`product_type=ESPCL`
   single-target filter). The classifier accepts ESPCL- and
   Common-tagged DIDs only; ESP-tagged DIDs are
   `OUT_OF_SCOPE` (they land in ESP's iteration).
3. The output paths are computed via:
   * `folder = product_type_arxml_folder("ESPCL")` → `"ESP"`
     (used for the `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/` report layout
     and the Bosch mirror folder).
   * `suffix = product_type_suffix("ESPCL")` → `"ESPCL"`
     (used for the per-iteration filename tag).
   * Bosch path = `{product_type_arxml_folder}` placeholder in
     `paths.arxml_file` → `cfg/ESP/Dcm_..._ESPCL.arxml`.
4. ARXML merges into the Bosch tree at
   `cfg/ESP/Dcm_CusDiag_Services_EcucValues_ESPCL.arxml` (skip-on-
   conflict by `SHORT-NAME`). Reports under
   `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/ESP/`:
   `validation_report_ESPCL.txt`,
   `arxml_review_report_ESPCL.txt`,
   `merge_report_ESPCL.txt`.
5. ESP's own iteration runs identically with `suffix="ESP"`,
   producing `Dcm_..._ESP.arxml` next to ESPCL's in `cfg/ESP/`.
   The two iterations cannot overwrite each other because every
   output filename carries the `_<suffix>` tag.

**Phase 3 ignores the alias.** ESPCL still iterates as a distinct
PT in Phase 3, writing into the Bosch tree under `src/ESPCL/` and
`esp10cl/dcompr/cfg/RBDCOM_ConfigSettings.h`. The path alias is
exactly what its name says: Phase 2 only.

`--init-project` emits `[INFO] Phase 2 path alias active: ESPCL → ESP`
unconditionally (regardless of whether `cfg/ESPCL/` happens to
exist) and never seeds `paths.per_product.ESPCL.arxml_file = null`.
Operators who ship a custom Bosch tree that does carry
`cfg/ESPCL/` and want a separate folder for ESPCL must remove
`ESPCL` from `_PHASE2_PRODUCT_ALIASES` (deliberate code change).

### Per-product skip / override

Real Bosch trees aren't fully template-symmetric. `paths.per_product`
(see [`configuration.md`](configuration.md#pathsper_product)) lets
the operator declare per-PT gaps and overrides once.

For Phase 2's only mirror key (`arxml_file`), the semantics are
**all-or-nothing per product**:

| `paths.per_product.<PT>.arxml_file` | Phase 2 behaviour for that PT |
|---|---|
| `null` | The product is **dropped from the run-time work-set entirely**. No Bosch ARXML is touched and the per-product report directory is not created. Pipeline logs `[SKIP] <PT>: paths.per_product.<PT>.arxml_file = null — no Bosch ARXML target for this product, skipping entire Phase 2 iteration`. The product still appears in any `validation_report_<suffix>.txt` `OUT_OF_SCOPE` lines from sibling iterations (so DIDs targeting it stay traceable). |
| `"<path>"` | The Bosch merge writes to the literal override path (`<base_dir>/<override>`) instead of expanding the template. Reports still land under `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<folder>/`. |
| absent | Template + placeholder expansion (alias-aware via `{product_type_arxml_folder}`). |

> **Init-time note:** `--init-project` emits an unconditional
> `[INFO] Phase 2 path alias active: ESPCL → ESP` line on every
> tree (even when `cfg/ESPCL/` is present, since the alias still
> reroutes the output) and never auto-seeds `ESPCL.arxml_file =
> null`. The skip-via-`null` semantics still apply if you
> hand-write `per_product.ESPCL.arxml_file = null`, but doing so
> *cancels* the path alias for ESPCL — the iteration runs SKIP and
> nothing lands in `cfg/ESP/Dcm_..._ESPCL.arxml`. You'd typically
> only do that if you also remove ESPCL from
> `_PHASE2_PRODUCT_ALIASES`.

`--init-project` also surfaces `[FYI]` lines for **extra ARXMLs**
the live tree carries that aren't covered by the standard template
(e.g. `Common/Dcm_..._EcucValues.arxml` no-suffix sibling, or
`IPB/Dcm_..._IPB11.arxml`). These do **not** auto-populate
`per_product`; if you want to mirror into one of those instead,
hand-edit `paths.per_product.<PT>.arxml_file` to the literal path.

---

## 4. Hard gate on `fscs.json`

Phase 2 aborts at the entry point if
`.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json` is missing — no silent fallback
to a stale `FSCS_22.txt`. The remediation hint points at
`--phase fscs` to regenerate.

The drift advisory (Phase 1 §5) runs as a non-blocking pre-run
warning and prints to stderr if `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/*.txt` are
out of sync with the JSON.

Phase 2 also hard-aborts (exit 2) if `paths.base_dir` is missing
or empty — there is no local fallback, the Bosch tree is the sole
sink.

---

## 5. Common pitfalls

| Symptom | Cause / fix |
|---|---|
| `[ERROR] .DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json missing` | Phase 1 was skipped. Run `--phase fscs` first |
| `[ERROR] paths.base_dir missing or empty — Phase 2 hard-aborts` | Re-run `python scripts/pipeline.py --init-project` so the toolkit autodetects the Bosch tree, or hand-edit `.DCOM_AI/DID_Toolkit_PRJ/config/project.json::paths.base_dir`. There is no local fallback |
| Bosch-tree ARXML wasn't touched even after a successful run | Skip-on-conflict by `SHORT-NAME`: every container already existed. Check `.DCOM_AI/DID_Toolkit_PRJ/outputs/arxml/<PT>/merge_report.txt` — every container should be listed under `M skipped` with its `SHORT-NAME` |
| Phase 2 emits a DID we didn't expect for this product | `Product_Type` cell collapses to `Common` when empty/None. Pin it in `fscs_edit.xlsx` then `--phase xlsx-import` |
| Cross-product SCOPE reviewer flags a DID that should be shared | Set `Product_Type=Common` in `fscs_edit.xlsx` to legitimise the overlap |
| Phase 2 / Phase 3 errors out with `unrecognized arguments: --product-type` | The flag is gone; the work-set is computed from `fscs.json`. Drop the flag entirely |
| Phase 2 / Phase 3 errors out with `unrecognized arguments: --output-mode` or `--no-backup` | Neither flag is supported. Drop them; the Bosch tree is the sole sink and skip-on-conflict replaces backup |
| Phase 2 / Phase 3 abort with `unrecognised product_type 'DPC'` | A `Product_Type` cell in `fscs_edit.xlsx` doesn't match the case-insensitive whitelist `{DPB, ESP, ESPCL, IPB, RBU, Common}`. Fix the typo, re-run `--phase xlsx-import`, then re-run Phase 2 |
| Phase 2 prints `work-set is empty` and skips | Every `used_flag` is `FALSE` in `fscs_edit.xlsx`. Either flip some on, or this is intentional (Phase 4 / DOORS still runs) |
| `[MERGED] 0 inserted, N skipped` | Every container in the generated ARXML already exists in the target. Merge is a no-op — this is the expected steady-state when nothing changed |
| `Common` slot ARXML mirrored as `_Common.arxml` instead of `_SingleCANID.arxml` | `paths.arxml_file` still uses the legacy `{product_type_upper}` for the filename suffix. Swap it for `{product_type_suffix}` (or delete `.DCOM_AI/DID_Toolkit_PRJ/config/project.json` and re-run `--init-project`) |
| `[SKIP] <PT>: paths.per_product.<PT>.arxml_file = null` and no Bosch ARXML was touched | The per-product override block opted that PT out (a hand-edited `null`). Delete the `per_product.<PT>.arxml_file` line from `project.json` to restore the iteration |
| Bosch ARXML for one PT was written to a path that doesn't match `paths.arxml_file` | `paths.per_product.<PT>.arxml_file` carries a string override that supersedes the template. Inspect `project.json` and either keep / change / remove the override |
| Need to roll back a merge | Use the source-control of the Bosch tree (git/SVN). There is no rolling backup — skip-on-conflict never overwrites |
