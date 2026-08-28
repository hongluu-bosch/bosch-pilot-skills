# Phase 3 — Implementation (C / headers / PDM)

> **When to read this.** You're running `--phase implementation`,
> understanding what the generator produces vs. what it leaves for
> the agent, or learning the inline `TODO(agent)` block + the
> continuous fill-in flow.

Phase 3 reads `.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs.json`, computes the
per-run **product work-set** (every product carried by a `used` DID;
see [`phase-2-arxml.md`](phase-2-arxml.md) §3), and **fans out** —
writing PDM entries, header macros, and per-DID
`RBAPLCUST_RDBI_*.c` / `RBAPLCUST_WDBI_*.c` files **directly into the
Bosch project tree** (resolved via `paths.base_dir` + `paths.*`)
once per product. `.c` files use **skip-if-exists at the file level**
(hand-tuned bodies always win); headers / PDM use **entry-level
skip-on-conflict** (existing `#define`s / PDM rows preserved).

Shape of the run:

- **Project tree is the sole source sink.** Reports (validation,
  generation, review) stay under
  `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/`; there is no local source
  mirror to keep in sync.
- **Inline `TODO(agent)` block** on every non-EEPROM stub carries
  DID identity + storage classification + RAM sub-pattern guess +
  FSCS behaviour text + the seven curated context-lookup paths.
- **No `[AGENT STOP]` after framework** — Phase 3 closes with an
  `[AGENT TODO] X fill / Y stub` summary and the agent fills the
  non-empty behaviours in the **same turn**, leaving stubs in
  place for a later round.
- **No `--product-type` CLI flag** — the build target is the *set*
  of products the operator tagged on `used` DIDs in
  `fscs_edit.xlsx::Product_Type` (empty cells collapse to
  `Common`); Phase 3 iterates the generator once per product.

C templates per storage class:
[`c-templates.md`](c-templates.md). Naming contract:
[`naming.md`](naming.md). The agent fill-in playbook for
non-NVM stubs:
[`implementation-storage-positions.md`](implementation-storage-positions.md).

---

## 1. Outputs

Per-product fan-out — every artefact below repeats once per
product in the work-set (`<PT>` ∈ `{DPB, ESP, ESPCL, IPB, RBU,
Common}`).

**Bosch project tree (the actual generated source)** — paths resolved
via `paths.base_dir` + `paths.*` + `{product_type_*}` placeholders:

| Path template | Role |
|---|---|
| `<base_dir>/<c_output_subdir>/RBAPLCUST_RDBI_<Name>.c` | Read-side per-DID source (skip-if-exists) |
| `<base_dir>/<c_output_subdir>/RBAPLCUST_WDBI_<Name>.c` | Write-side per-DID source for `RW` DIDs (skip-if-exists) |
| `<base_dir>/<config_h>` | Merge `#define`s into `RBAPLCUST_Config.h` |
| `<base_dir>/<config_elements_h>` | Merge `#define`s into `RBAPLCUST_ConfigElements.h` |
| `<base_dir>/<config_settings_h>` | Merge `#define`s into per-product `RBDCOM_ConfigSettings.h` |
| `<base_dir>/<pdm_file>` | Append-merge EEPROM PDM entries into `RBAPLCUST_PDM.txt` |

**Local reports (audit trail under `.DCOM_AI/DID_Toolkit_PRJ/outputs/`)**:

| Path | Role |
|---|---|
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/generation_report.txt` | Per-product write / skip / fill / stub breakdown (`agent_fill_targets`, `agent_stub_targets`, `skipped_c_files`) |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/validation_report.txt` | Per-DID outcome for this product's iteration (`SUCCESS` / `SKIPPED` / `ERROR`) |
| `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/impl_review_report.txt` | Auto-runs after generation; advisory only |

---

## 2. Storage-class dispatch

Phase 3 ships a **fully-generated** read/write body **only for
`EEPROM`** (NVM-backed) DIDs because they all reduce to one
boilerplate (`DCOM_ReadDataByNVMId` / `DCOM_WriteDataByNVMId`).
The other two storage classes have no single recipe — the right
body depends on the DID's natural-language `Behavior` text and
the project's available internal interfaces.

| `storage_position` | What Phase 3 emits | Inline TODO block written? |
|---|---|---|
| `EEPROM` (alias `NVM`) | Fully-generated read body using `DCOM_ReadDataByNVMId`; matching write body for `RW` DIDs. | No — generator handles in full. |
| `ROM` (alias `FLASH`) | **Auto-generated** `.c` body (`Data[i] = C_DID_..._UB;` copy) + matching `RBAPLCUST_RDBI_<DidName>.h` header with `#define` ladder parsed from FSCS `behavior`. Agent reviews correctness. | No — v2.4.0+ replaces the TODO stub with a complete auto-generated body when the `HardCode:` behavior block is present. If behavior is empty / malformed, a stub with TODO is emitted instead. |
| `RAM` | Same stub posture. Inline TODO block carries a heuristic-picked **RAM sub-pattern** guess (A / B / C / undetermined). | Yes — `RAM` class. |

`FLASH` canonicalises to `ROM` and `NVM` to `EEPROM` at
schema-load time, so downstream code only deals with the three
canonical literals.

---

## 3. The non-NVM stub (inline TODO block)

Non-EEPROM stubs return `E_NOT_OK` (so a half-finished release
fails loudly on the bench, never fake-success), and embed a
multi-line `TODO(agent)` block carrying everything an agent
needs to fill the body:

```c
/* TODO(agent): replace this stub with the real RAM read body.
 *
 * --- Identity ---
 * did_hex     : 3026
 * did_name    : EpbActuatorState
 * data_type   : Unsigned
 * size_bytes  : 2
 * rw_state    : R
 *
 * --- Storage classification ---
 * class       : RAM
 * RAM pattern : B — DefineMESGDef / RcvMESGDef (likely)
 * rationale   : Behavior text mentions 'NMSG_..._ST' / 'DefineMESGDef'.
 *
 * --- Style constraints (mandatory) ---
 * - The function body MUST be MISRA-C compliant
 *   (one statement per line, explicit casts on mixed-
 *   type arithmetic, no fall-through in switch, every
 *   return path explicitly assigned, no unbalanced
 *   braces, no implicit conversions losing precision).
 * - If the body uses any *MESGDef macro family
 *   (sub-pattern B: DefineMESGDef + RcvMESGDef pair,
 *   or sub-pattern C: RBMESG_DefineMESGDef +
 *   RBMESG_RcvMESGDef pair):
 *     * BOTH macros of the pair MUST be present —
 *       a Define without its matching Rcv (or vice
 *       versa) will fail to link.
 *     * They MUST appear as the FIRST two statements
 *       inside the enclosing #if (RBFS_DCOMDomain
 *       == ...) guard, before any read / logic /
 *       assignment statement.
 *
 * --- FSCS Behavior (the implementation prompt) ---
 * Behavior 0x22 (Read):
 *   <verbatim text from fscs_edit.xlsx::behavior_22>
 *
 * --- Agent contract ---
 * Playbook    : reference/implementation-storage-positions.md
 * Action      : Replace this TODO(agent) block with the real body,
 *               then flip retVal = E_NOT_OK -> E_OK. Leave the block
 *               in place if the FSCS behaviour text was empty /
 *               default — edit the FSCS behavior text upstream first,
 *               then re-run Phase 3. */
```

The `TODO(agent)` marker stays loud at runtime (still returns
`E_NOT_OK`); a quick `rg "TODO\(agent\)"` over the Bosch tree
counts unfilled stubs at any time.

> **Style constraints are non-negotiable.** Every agent-filled body
> must satisfy two rules baked into the inline block above:
> (1) MISRA-C compliance — one statement per line, explicit casts
> on mixed-type arithmetic, no `switch` fall-through, every return
> path explicitly assigned, no unbalanced braces, no implicit
> precision loss; and (2) for sub-pattern B / C bodies, both
> `Define*MESGDef` and `Rcv*MESGDef` (or `Xmt*MESGDef` on the
> write side) must appear **paired** and as the **first two
> statements** inside the enclosing `#if (RBFS_DCOMDomain == ...)`
> guard. See [`implementation-storage-positions.md`](implementation-storage-positions.md) §3.2 / §3.3 / §3.6 for worked examples and
> the pitfalls list.

---

## 4. Inline TODO block contract

The inline block lives **inside the generated `.c` stub** — no
external playbook to download, no separate brief to find.
Everything is in front of the agent when they read the `.c`. The
block is anchored by the literal `TODO(agent):` marker so
`--phase implementation` re-runs can detect "still a stub" vs
"agent-filled" purely by substring match.

Inline TODO blocks are emitted for:
* `RAM` DIDs.
* `ROM` / `FLASH` DIDs **only when** the FSCS `behavior` text is empty or does not contain a valid `HardCode:` block (v2.4.0+ auto-generates the body when the HardCode block is present).

They are **skipped** (no TODO block, fully-generated body) for:
* `EEPROM` / `NVM` DIDs (the generator emits the
  `DCOM_ReadDataByNVMId` / `DCOM_WriteDataByNVMId` boilerplate
  with the right `NVM_ID_DCOM_<NAME>` literal).
* `ROM` / `FLASH` DIDs whose `behavior` contains a valid `HardCode:`
  block (v2.4.0+ — the generator auto-emits the `#define` ladder
  header + macro-based `.c` body).
* DIDs whose `service_22.effective == False` (deselected — Phase
  3 doesn't generate a `.c` for them either).

If the FSCS `behavior` text is empty (or the default
placeholder), the inline block still goes out but the DID lands
in the **stub-target** bucket of the Phase 3 footer — the agent
is told not to expand it this round (no behaviour to expand
*from*). Edit `fscs_edit.xlsx::behavior_*` upstream, re-run
`--phase xlsx-import` + `--phase implementation`, then the same
DID flips to a **fill-target** in the next round.

---

## 5. RAM sub-patterns

The heuristic in
`scripts.implementation.generators.classify_storage` matches against
the joined `behavior_22 + behavior_2e` text:

| Sub-pattern | Trigger keywords | Pattern |
|---|---|---|
| **A — direct getter** | `RBEcuSupply` / `ComScl_RawSignal` / "battery" / "voltage" / "filtered" / "raw signal" / `get*(` | Call documented project getter, convert units, fill `Data[i]`. Example: `RBAPLCUST_RDBI_BatteryVoltage.c`. |
| **B — `DefineMESGDef` + `RcvMESGDef`** | `NMSG_..._ST` / `DefineMESGDef` / `RcvMESGDef` | ESP/DPB struct messages; check `.Qualifier_N == <Message>_Normal` else fall back to `0x7Fu` sentinel. Example: `RBAPLCUST_RDBI_BLS.c` ESP/DPB branches. |
| **C — `RBMESG_DefineMESGDef` + `RBMESG_RcvMESGDef`** | `RBMESG_` / `RBBSM_` | IPB-style scalar / enum signals; copy through or switch-map enum to byte. Example: `RBAPLCUST_RDBI_EPB.c`. |

Heuristic priority: **C > B > A** (more specific keywords win).
When no keyword matches, the inline TODO block records
`undetermined — no behavior keyword matched` and points the
agent at all three reference files for manual selection.

Full pattern decoding, file placement conventions
(`Common/` vs `<Product>/`), house-style cheatsheet (function
signature, tabs vs spaces, header guard format, license header),
and common pitfalls: **read
[`implementation-storage-positions.md`](implementation-storage-positions.md)
in full before filling any non-EEPROM stub.**

---

## 6. Agent fill-in workflow (continuous flow)

> **Three contracts you cannot skip while filling:**
> 1. **Curated search first.** Look up signal / typedef / RBFS_*
>    context inside the seven paths in
>    [`implementation-storage-positions.md`](implementation-storage-positions.md)
>    §5.1 before scanning the wider tree. They cover ~95% of the
>    symbols a non-EEPROM body needs and are dramatically faster
>    than a full repo grep.
> 2. **Confirm before touching anything beyond the generated `.c`.**
>    Edits to `.bcfg` / customer `.h` / `RBFS_*` switches follow
>    the §5.2 edit + operator-confirmation contract — quote the
>    file + diff and `[AGENT STOP]` for any change that crosses
>    an existing operator-set value, a customer-shipped header,
>    or an unrelated DID's enablement.
> 3. **Close with a review summary.** When the round is done,
>    emit the §5.3 `[AGENT REVIEW]` block (filled / stub / extra
>    edits / operator decisions) and stop, asking the operator
>    to verify.

```bash
# 1. Run Phase 3. Generator writes the framework directly into the
#    Bosch tree (skip-on-conflict per product) and prints an
#    [AGENT TODO] summary listing fill / stub targets.
python scripts/pipeline.py --phase implementation
# Footer (example):
#   [AGENT TODO] Phase 3 framework done. 12 fill / 3 stub.
#     Fill targets (expand inline TODO this turn):
#       - <bosch-tree>/.../src/DPB/RBAPLCUST_RDBI_VinRead.c   (EEPROM, $22)
#       - <bosch-tree>/.../src/DPB/RBAPLCUST_RDBI_OdoRead.c   (RAM    , $22)
#       ...
#     Stub targets (behaviour empty — leave TODO in place):
#       - <bosch-tree>/.../src/DPB/RBAPLCUST_RDBI_TBD1.c
#       ...

# 2. There is no separate [AGENT STOP] after framework generation —
#    the agent continues in the SAME turn:
#    a) Read the inline TODO(agent) block in each fill-target .c.
#       It already carries DID identity, storage classification,
#       RAM sub-pattern guess, and the FSCS behaviour text.
#    b) Cross-reference the matching section in
#       implementation-storage-positions.md (§3 RAM only; §2 HardCode
#       is now auto-generated from the FSCS behavior block).
#    c) **Search the curated context paths first** (§5.1 of
#       implementation-storage-positions.md) for signal
#       definitions, aswif getter prototypes, RBMESG names, and
#       RBFS_* switches — these seven paths cover ~95% of the
#       symbols a non-EEPROM body needs. Fall back to a wider
#       grep only when none of §5.1 yield a hit.
#    d) Read at least one cited reference .c file in full so the
#       indentation, comment style, and macro spelling match the
#       project's house style.
#    e) Replace the TODO(agent) block in the .c with the real body.
#       For HardCode DIDs, the generator auto-emits the .h header
#       and the macro-based .c body — the agent only reviews.
#    f) Project-tree edits beyond the generated .c
#       (.bcfg / .h / RBFS_* switches) follow the §5.2 edit +
#       operator-confirmation contract:
#         * Stop and ask when the change touches an existing
#           operator-set value, a customer-shipped header, or an
#           unrelated DID's enablement.
#         * Quote the exact path + line range, show a one-line
#           diff, and end the turn with [AGENT STOP].
#
#    For stub targets (empty FSCS behaviour), leave the TODO block
#    in place — edit fscs_edit.xlsx::behavior_* upstream first, then
#    re-run --phase xlsx-import + --phase implementation.

# 3. Emit the closing summary (§5.3) once every fill target has
#    been addressed:
#      [AGENT REVIEW] Phase 3 fill-in complete.
#        Filled (N):   <hex> <name>  ->  <relative path>
#        Left as stub (M, FSCS Behavior empty): ...
#        Project-tree edits beyond the generated .c (K): ...
#        Operator decisions captured this round (J): ...
#      Please review the listed files; reply "done" / "looks good"
#      / "继续" once verified, or call out anything to revise.
#    Then stop the turn.

# 4. Counts: `rg "TODO\(agent\)" <bosch-tree>` always reflects the
#    remaining work across the project tree.
```

The Phase 3 footer is the source of truth for the fill / stub set;
the per-product `generation_report.txt` carries the same lists for
audit / CI integration.

---

## 7. File-name collision handling

Two DIDs whose cleaned names collide (e.g. both clean down to
`VersionNumber`) would otherwise overwrite each other's `.c`.
Phase 3 detects this pre-scan and falls back to a
hex-disambiguated stem (`<HEX>_<CleanedName>.c`) for the
colliding subset. `did_hex` is guaranteed unique upstream so the
fallback always resolves.

The collision is logged: `[COLLISION] N cleaned DID name(s)
collide ... falling back to hex-disambiguated filenames: [...]`.

---

## 8. Bosch-tree write semantics

The project tree is the sole sink for Phase 3 source artefacts.
There is no `outputs/implementation/<PT>/c_code/` local mirror
anymore.

| Artefact | Write policy in project tree |
|---|---|
| `.c` files | **Skip-if-exists at the file level** — once a `.c` exists in `<base_dir>/<c_output_subdir>/`, Phase 3 never overwrites it. Logged in `generation_report.txt` as `skipped_c_files`. |
| Headers (`Config.h`, `ConfigElements.h`, `ConfigSettings.h`) | **Entry-level merge** — new `#define`s spliced in just before `#endif`; existing macros preserved (skip-on-conflict by macro name). No backup file (no overwrite). |
| PDM (`RBAPLCUST_PDM.txt`) | **Entry-level append-merge** — new EEPROM PDM entries appended; existing entries with the same key skipped. No backup file. |

Full project-tree write contract and dry-run usage:
[`output-safety.md`](output-safety.md).

### Per-(PT, key) skip / override

Real Bosch trees have artefact-level asymmetries on top of the
PT-level ones Phase 2 handles — e.g. `Common/dcompr/cfg/` doesn't
exist on any shipped tree (so the `Common` slot has no
`RBDCOM_ConfigSettings.h` target), and `IPB`'s ConfigSettings file
ships only as variant-suffixed copies (`RBDCOM_ConfigSettings_IPB.h`
/ `..._IPB4HAD.h` / `..._RoPPSub.h`, no plain `RBDCOM_ConfigSettings.h`).

The `paths.per_product` block (see
[`configuration.md`](configuration.md#pathsper_product)) lets each
(PT, key) pair independently opt out or override. Unlike Phase 2's
all-or-nothing semantics, Phase 3's overrides are **per artefact** —
other artefacts for the same product still flow.

| `paths.per_product.<PT>.<key>` | Phase 3 behaviour for that (PT, key) |
|---|---|
| `null` | The artefact is **dropped from the Bosch tree** for that one product (no `<base_dir>/<artefact>` write). Pipeline logs `[SKIP] paths.per_product.<PT>.<key> = null`. Other artefacts for the same product (e.g. `pdm_file`, `c_output_subdir`) still write normally. |
| `"<path>"` | The Bosch write lands at the literal override path (`<base_dir>/<override>`) instead of expanding the template. |
| absent | Default behaviour — template + placeholder expansion. |

`--init-project` auto-seeds two common cases when the live tree
scan confirms them:

| Auto-seeded entry | Reason | Tag |
|---|---|---|
| `per_product.Common.config_settings_h = null` | `Common/dcompr/` directory missing in the tree — there's no `RBDCOM_ConfigSettings.h` for the cross-product slot. | `[INFO]` |
| `per_product.IPB.config_settings_h = "<...>RBDCOM_ConfigSettings_IPB.h"` | IPB ships variant-suffixed `..._IPB.h` / `..._IPB4HAD.h` / `..._RoPPSub.h`. Default is the `_IPB.h` variant; alternates are listed for the operator to confirm or hand-swap. | `[CONFIRM]` |

`--init-project` also surfaces `[FYI]` lines for `src/` subdirs
not covered by the standard template (typically `src/IPB11/` and
`src/XPB/`). These do **not** auto-populate `per_product`; if
you want to mirror C code into one of those instead, hand-edit
`paths.per_product.<PT>.c_output_subdir` to the literal path.

### Common-DID broadcast

There is one piece of Phase 3 behaviour that surprises everyone
the first time they look at the per-PT outputs, so it is pinned
here:

**Phase 3 does not filter DIDs by `product_type`. Every per-PT
iteration sees the full DID set from `fscs.json`.**

Mechanism:

* `scripts/implementation/models.py::DIDImplementationInfo`
  (the data model Phase 3 consumes) **has no `product_type`
  field**. It carries `did_hex`, `did_name`, `nvm_item`,
  `storage_position`, sub-fields, and behaviour text — but not
  the per-DID PT tag.
* `scripts/fscs/adapter.py::to_did_implementation_infos(document)`
  filters out `DESELECTED` and write-only DIDs but **does not
  filter by `product_type`**. Every Phase-3-eligible DID flows
  into every PT's iteration.
* `scripts/implementation/orchestrator.py::ImplementationGenerator
  .generate_from_dids(dids, ..., product_type=<PT>)` writes the
  same `dids` list into every PT's Bosch tree (no local source
  mirror).

The practical effect:

* `Common`-tagged DIDs' ConfigSettings / Config / ConfigElements
  / PDM entries / `.c` stubs **already appear in every per-PT
  mirror file** — `dpb/dcompr/cfg/RBDCOM_ConfigSettings.h` /
  `esp10/dcompr/cfg/...` / `ipb/dcompr/cfg/...` /
  `rbu/dcompr/cfg/...` all contain the Common DID rows.
* The `paths.per_product.Common.config_settings_h = null` entry
  the `--init-project` detector seeds **only suppresses Common's
  own iteration attempting to write into the non-existent
  `Common/dcompr/cfg/`**. It does **not** drop Common's
  settings — they have already been broadcast into every other
  PT's mirror file by every other PT's iteration.
* DPB-tagged DIDs likewise appear in ESP / IPB / RBU /
  Common's outputs (and vice versa). Phase 3 is not making a
  PT-aware split.

This is the codified semantic: it satisfies the "Common DIDs
visible everywhere" requirement *and* keeps Phase 3 a single
fan-out loop over the workset rather than a PT-aware filter
ladder. Any future change that adds true PT-filtering to Phase 3
is a deliberate code change that must preserve the
Common-broadcast exception (otherwise Common DIDs would suddenly
disappear from every other PT's ConfigSettings — a silent
regression).

If you need a PT to **really** drop Common's contribution, the
only knob today is `paths.per_product.<PT>.config_settings_h
= null` (skip both local artefact and Bosch mirror for that one
(PT, key)). The detector will not seed this for you; hand-edit
only when you know what you're doing.

> **ESPCL note (cross-reference to Phase 2):** the Phase-2 alias
> `ESPCL → ESP` is **Phase-2 only**. Phase 3 still iterates
> ESPCL as a distinct PT and produces its own
> `outputs/implementation/ESPCL/`, its own `src/ESPCL/` mirror,
> and its own `esp10cl/dcompr/cfg/RBDCOM_ConfigSettings.h` entry
> (subject to the broadcast described above).

---

## 9. Common pitfalls

| Symptom | Cause / fix |
|---|---|
| Phase 3 footer says `[AGENT TODO] X fill / Y stub` | Expected when any DID has `storage_position` ∈ `{ROM, FLASH, RAM}`. Expand each fill target's inline `TODO(agent)` block in the same turn; leave stub targets in place. See §6. |
| Want to count remaining TODOs | `rg "TODO\(agent\)" <bosch-tree>` (or `grep -r "TODO(agent)"` outside PowerShell). |
| Agent looked for `_briefs/` files | There is no external `_briefs/` directory — the inline `TODO(agent)` block inside each non-EEPROM `.c` carries the same context (identity + storage classification + FSCS behaviour text + curated context paths). |
| `.c` file in Bosch tree wasn't refreshed after a re-run | Skip-if-exists policy — Phase 3 never overwrites an existing `.c`. Move/rename the file then re-run. |
| Two DIDs producing the same `.c` filename | Expected when both clean down to the same identifier. Phase 3 falls back to `<HEX>_<Name>.c`; check the `[COLLISION]` log line for which DIDs were renamed |
| EEPROM DID's read body is a stub instead of a real `DCOM_ReadDataByNVMId` call | `nvm_item` field is empty in `fscs.json`. Fix it in `fscs_edit.xlsx` then `--phase xlsx-import` |
| `[SKIP] paths.per_product.<PT>.<key> = null` and the matching Bosch artefact is missing | Per-(PT, key) skip sentinel is set in `project.json` (e.g. `Common.config_settings_h` is auto-disabled because `Common/dcompr/` doesn't exist). Delete the entry from `paths.per_product.<PT>` to restore the artefact. |
| Bosch ConfigSettings header for IPB lands at an unexpected path | `paths.per_product.IPB.config_settings_h` carries a string override (auto-seeded to `RBDCOM_ConfigSettings_IPB.h` by `--init-project`). Check `project.json` and either keep / change to `_IPB4HAD.h` etc. / remove the override. |
| Tree has `src/IPB11/` and `src/XPB/` but Phase 3 doesn't write there | These are `[FYI]` extras `--init-project` only mentions; they don't auto-populate `per_product`. Add `paths.per_product.IPB.c_output_subdir` (or analogous) by hand if you want to route C code into one of those. |
