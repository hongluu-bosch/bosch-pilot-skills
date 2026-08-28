# Phase 3 — Implementations by Storage Position

> **When to read this.** Anytime Phase 3 emits a `TODO(agent)` stub
> in a generated `RBAPLCUST_RDBI_*.c` (i.e. the DID's
> `storage_pos` is **not** `EEPROM`), this file plus the
> **inline `TODO(agent)` block** at the top of that `.c`
> are the contract you fill the body against — all per-DID
> context is embedded in the `.c` itself, no external playbook
> to download. EEPROM DIDs are fully generated and never produce
> inline TODO blocks — leave them alone.

The DID toolkit's Phase 3 generator (Bosch BSW
`RBAPLCust/src/...` mirror) ships a complete implementation only
for **EEPROM** (NVM-backed) DIDs because they all reduce to one
boilerplate: `DCOM_ReadDataByNVMId` / `DCOM_WriteDataByNVMId`. The
other two storage classes have no single recipe — the right body
depends on the DID's `Behavior` description, the project's available
internal interfaces, and which products the DID applies to. This
document is the agent's playbook for those two classes.

---

## 1. Storage classification

`fscs.json :: dids[].storage_pos` (canonicalised at load — `FLASH`
becomes `ROM`) drives the dispatch:

| `storage_pos` | Class | Generator behaviour | Read this section |
|---|---|---|---|
| `EEPROM` | NVM | **fully generated** — `DCOM_ReadDataByNVMId(...)` body + matching PDM entry + headers. No inline TODO, no stub. | (skip) |
| `ROM` (or `FLASH`) | HardCode | stub + inline `TODO(agent)` block; you fill from the **Customer constants** pattern below. | §2 |
| `RAM` | Internal-Interface | stub + inline `TODO(agent)` block; you fill from **one** of the three RAM patterns below. | §3 |

Anything else (`""` / `INTERNAL` / future literals) currently lands
on the same RAM-class path; treat it as RAM until the schema gains
an explicit literal.

---

## 2. ROM / Flash / HardCode pattern (v2.4.0 — auto-generated)

> **v2.4.0 change.** HardCode DIDs are now **fully auto-generated**
> by Phase 3 when the FSCS `behavior` text contains a valid `HardCode:`
> block. The agent's job is reduced to **review** — no manual body
> filling is required. This section documents the generated output so
> the agent knows what to verify.

**When the generator runs:**

* `.c` body (`src/Common/RBAPLCUST_RDBI_<DidName>.c`) — auto-emitted
  with `Data[i] = C_DID_..._UB;` macro copies.
* `.h` header (`api/RBAPLCUST_RDBI_<DidName>.h`) — auto-emitted with
  the `#define C_DID_<DidName>_Byte<N>_UB 0x<HH>u` ladder parsed
  from the FSCS behavior text.

Both files use **skip-if-exists** — once created, they are never
overwritten, so hand-tuned values are safe across re-runs.

### 2.1 Behavior format (operator-editable)

The `service_22_behavior` field in `fscs_edit.xlsx` must follow the
standard format documented in [`input-format.md`](input-format.md)
("HardCode Behavior Format"):

```text
HardCode:
C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB = 0x42
C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB = 0x6F
...
```

### 2.2 Generated header (`api/RBAPLCUST_RDBI_<DidName>.h`)

```c
#ifndef RBAPLCUST_RDBI_SYSTEMSUPPLIERIDENTIFIERDATAIDENTIFIER_H_
#define RBAPLCUST_RDBI_SYSTEMSUPPLIERIDENTIFIERDATAIDENTIFIER_H_

/* DID F18A — systemSupplierIdentifierDataIdentifier (9 bytes)
 * Auto-generated from FSCS behavior text (HardCode block).
 * Edit the behavior upstream and re-run Phase 3 to regenerate.
 */

#define C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB    0x42u
#define C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB    0x6Fu
/* ... one #define per byte, up to size_bytes-1 ... */

#endif /* RBAPLCUST_RDBI_SYSTEMSUPPLIERIDENTIFIERDATAIDENTIFIER_H_ */
```

> **Note:** v2.4.0 generates a **per-DID header** (not a family
> header). The old pattern of appending multiple DIDs into a single
> `RBAPLCUST_RDBI_VersionNumber.h`-style family header is no longer
> required — each HardCode DID gets its own clean header file.

### 2.3 Generated C body (`src/Common/RBAPLCUST_RDBI_<DidName>.c`)

```c
#include "RBAPLCUST_RDBI_SystemSupplierIdentifierDataIdentifier.h"
/* ... */

Std_ReturnType RBAPLCUST_F18A_SystemSupplierIdentifierDataIdentifier_ReadData(
    uint8 * Data)
{
    /* Return value initialization */
    Std_ReturnType retVal = E_NOT_OK;
#if(RBFS_DCOM_SystemSupplierIdentifierDataIdentifier ==
    RBFS_DCOM_SystemSupplierIdentifierDataIdentifier_ON)
    /* DID: 0xF18A - systemSupplierIdentifierDataIdentifier
     * Operation: Read data (ROM/Flash storage)
     * Size: 9 bytes
     * Source: C_DID_..._UB macros in matching .h */
    Data[0] = C_DID_SystemSupplierIdentifierDataIdentifier_Byte0_UB;
    Data[1] = C_DID_SystemSupplierIdentifierDataIdentifier_Byte1_UB;
    /* ... up to Data[size_bytes - 1] ... */
    retVal = E_OK;
#endif
    return retVal;
}
```

### 2.4 Agent review checklist

Since the generator does the mechanical work, the agent only needs to
verify:

1. **Hex values match the specification.** Cross-check each `0x<HH>u`
   in the generated `.h` against the customer's DID specification
   (not just the FSCS behavior text, which is operator-edited and may
   contain typos).
2. **Byte count matches `size_bytes`.** The generator emits exactly
   `size_bytes` `#define` lines and `size_bytes` `Data[i] = ...`
   assignments — verify this equals the DID's declared size.
3. **TODO markers on fallback bytes.** If the behavior text was
   incomplete (some bytes missing), the generator emits
   `/* TODO(agent): verify — no HardCode value found */` next to the
   fallback `0x00u`. These must be resolved before release.
4. **Feature Switch macros still in `ConfigElements.h`.** The
   `RBFS_DCOM_<DidName>_ON/OFF` definitions remain in the shared
   `RBAPLCUST_ConfigElements.h` — they are NOT migrated into the
   per-DID header.

### 2.5 Fallback / stub mode

When the FSCS `behavior` text is empty or does not contain a valid
`HardCode:` block, Phase 3 falls back to the **pre-v2.4.0 stub**
posture:

* `.c` file with `TODO(agent)` block (returns `E_NOT_OK`).
* No `.h` file generated.
* Agent must fill the body manually or edit the FSCS behavior upstream
  and re-run Phase 3.

### 2.6 Common pitfalls

* **ASCII vs raw hex.** The parser does NOT convert strings to ASCII
  — the operator must write `0x42` (not `"B"`). Verify the hex values
  are correct for the intended encoding.
* **Size mismatch.** `size_bytes` from FSCS must equal the count of
  `C_DID_..._UB` lines in the behavior text. Mismatches produce
  fallback `0x00u` bytes with TODO markers.
* **Behavior text not saved.** The generator reads from `fscs.json`,
  which is only updated after `--phase xlsx-import`. Always run
  xlsx-import before Phase 3 when behavior text was edited.

---

## 3. RAM / Internal-Interface pattern

RAM-class DIDs read live data from in-RAM signals, internal
getters, or message-bus interfaces. The toolkit can't pick the
right source for you — that is the FSCS `Behavior` field's job.

**Reference implementations** (each demonstrates a different
sub-pattern — read at least the one that matches your DID's
behavior text before writing):

| Sub-pattern | When to use it | Reference file |
|---|---|---|
| **A. Direct internal getter** | Behavior says "read battery voltage" / "read raw signal X" / "call function Y" | `RBAPLCUST_RDBI_BatteryVoltage.c` |
| **B. `DefineMESGDef` / `RcvMESGDef`** (no `RBMESG_` prefix) | Behavior names a struct-typed network message (`NMSG_<...>_ST` ending in `_ST`); typically ESP/DPB | `RBAPLCUST_RDBI_BLS.c` (ESP/DPB branches) |
| **C. `RBMESG_DefineMESGDef` / `RBMESG_RcvMESGDef`** | Behavior names a scalar / enum RBMESG signal (no `_ST` suffix); typically IPB / IPB2 / RBU branches | `RBAPLCUST_RDBI_BLS.c` (IPB2 branch) and `RBAPLCUST_RDBI_EPB.c` |

A real DID often combines these per product domain — see
`RBAPLCUST_RDBI_BLS.c` which uses sub-pattern B for ESP/DPB and
sub-pattern C for IPB.

### 3.1 Sub-pattern A — direct internal getter

```c
FUNC(Std_ReturnType, DCM_APPL_CODE) RBAPLCUST_<DidName>_ReadData(
    P2VAR(uint8, AUTOMATIC, DCM_INTERN_DATA) Data)
{
    VAR(Std_ReturnType, AUTOMATIC) retVal = E_NOT_OK;

    /* Pull the live value via the documented internal interface. */
    uint16 l_<measurement> = <Module>_<Get...>();

    /* Convert HSW units to DCOM units per the DID's behavior text.
     * Example below: HSW = 1/256 V per bit, DCOM = 8/100 V per bit. */
    Data[0] = (uint8)(((l_<measurement> * 100) / 256) >> 3);

    retVal = E_OK;
    return retVal;
}
```

`#include` the header that exposes the getter (e.g.
`#include "RBEcuSupply_Voltages.h"` for battery voltage). The
inline `TODO(agent)` block lists candidate headers from the FSCS
behavior text where possible; when it can't infer, the agent
searches the curated `aswif` path (§5.1 #4) and the project's
`api/` folder to find the matching declaration.

### 3.2 Sub-pattern B — `DefineMESGDef` / `RcvMESGDef` (struct-typed message)

```c
Std_ReturnType RBAPLCUST_<DidName>_ReadData(uint8 * Data)
{
#if (RBFS_DCOMDomain == RBFS_DCOMDomain_ESP)
    DefineMESGDef(NMSG_<MessageName>_ST);
    RcvMESGDef (NMSG_<MessageName>_ST);

    if (l_NMSG_<MessageName>_ST.Qualifier_N == <MessageName>_Normal)
    {
        Data[0] = (uint8)(l_NMSG_<MessageName>_ST.<field>_B ? 1u : 0u);
    }
    else
    {
        Data[0] = 0x7Fu;            /* invalid-data sentinel */
    }
#elif (RBFS_DCOMDomain == RBFS_DCOMDomain_DPB)
    /* Same structure, different message name (XMT vs RCV side). */
    DefineMESGDef(NMSG_<MessageName>_XMT_ST);
    RcvMESGDef (NMSG_<MessageName>_XMT_ST);
    /* ... */
#endif
    return E_OK;
}
```

Key idioms:

* `DefineMESGDef` and `RcvMESGDef` are a **mandatory pair** — one
  without the other will not link. They MUST be the **first two
  statements** inside the enclosing `#if (RBFS_DCOMDomain == ...)`
  guard, before any read / logic / assignment statement. The
  agent that fills in the body must respect this placement.
* The macros expand to a local variable named `l_<MESSAGE>`. Don't
  declare it manually.
* Always check `.Qualifier_N == <Message>_Normal` (or the
  message-specific `Normal` enum) before trusting the payload —
  otherwise emit the agreed sentinel (`0x7F`, `0xFF`, ...).
* Network messages often differ between RX (ESP listens) and TX
  (DPB transmits) sides; the inline `TODO(agent)` block tags which
  message names are available per product. When the listed names
  don't match, search the curated `cswpr` path (§5.1 #6) for the
  full `NMSG_..._ST` definition set.

### 3.3 Sub-pattern C — `RBMESG_DefineMESGDef` / `RBMESG_RcvMESGDef` (scalar / enum)

```c
#if ((RBFS_DCOMDomain == RBFS_DCOMDomain_IPB2) || \
     (RBFS_DCOMDomain == RBFS_DCOMDomain_IPB2ForHAD))
    RBMESG_DefineMESGDef(<RBMESG_Name>);
    RBMESG_RcvMESGDef(<RBMESG_Name>);

    Data[0] = l_<RBMESG_Name>;            /* scalar: just copy through */
#endif
```

Key idioms (same shape as sub-pattern B):

* `RBMESG_DefineMESGDef` and `RBMESG_RcvMESGDef` are a **mandatory
  pair** — one without the other will not link. They MUST be the
  **first two statements** inside the enclosing `#if
  (RBFS_DCOMDomain == ...)` guard, before any read / logic /
  assignment statement.
* For enum-typed RBMESG signals, switch-map them to the customer's
  output byte values (see `RBAPLCUST_RDBI_EPB.c` for the
  `PbcActuatorState_*_N` -> `0x00..0x07` mapping). The inline
  `TODO(agent)` block calls out enum DIDs explicitly when the
  FSCS describes one; the curated `cswpr` path (§5.1 #6) carries
  the canonical enum definitions when an additional symbol is
  needed.

### 3.4 Where to write

| Artefact | Path (relative to project root) |
|---|---|
| `.c`, product-agnostic (`#if`-guarded) | `rb/as/jac/core/app/dcom/RBAPLCust/src/Common/RBAPLCUST_RDBI_<DidName>.c` |
| `.c`, single-product only | `rb/as/jac/core/app/dcom/RBAPLCust/src/<Product>/RBAPLCUST_RDBI_<DidName>.c` |

`Common/` is the strong default — even a single-product DID
benefits from the per-domain `#if` ladder so you can swap
products later without moving the file. Only put a file under
`<Product>/` (e.g. `DPB/`, `ESP/`, `IPB/`, `IPB11/`, `RBU/`)
when the implementation cannot be made common (different
function signature, conflicting headers, etc.).

### 3.5 What to read from the inline `TODO(agent)` block

* `behavior_22` / `behavior_2e` — the FSCS description, often
  references a specific RBMESG / NMSG signal name. Use that as
  the `<MessageName>` in the macros.
* Heuristic line — "ends in `_ST`" → sub-pattern B;
  "scalar enum" → sub-pattern C; otherwise sub-pattern A.
* `size_bytes` — how many `Data[i]` writes you emit.
* `product_type` — used for the outer `#if` guards.
* When a value is enum-coded, `value_range` lists the FSCS enum
  symbols; the agent maps them to the destination byte values
  per the behavior text.

### 3.6 Common pitfalls

* **Wrong macro family.** `DefineMESGDef` (without prefix) is
  used for `NMSG_..._ST` struct messages; `RBMESG_DefineMESGDef`
  is used for `RBMESG_...` scalar / enum signals. Mixing them
  causes link-time misery.
* **Unpaired `*MESGDef` macros.** Both `Define*MESGDef` and the
  matching `Rcv*MESGDef` (or `Xmt*MESGDef` on the write side)
  must appear together — a Define without its matching Rcv (or
  vice versa) will fail to link.
* **`*MESGDef` macros not at the top of the body.** They MUST be
  the first two statements inside the enclosing
  `#if (RBFS_DCOMDomain == ...)` guard, before any read / logic
  / assignment statement. Tucking them after a comment block or
  an early `Data[i] = ...` write produces both a MISRA finding
  and unreliable code-generator output.
* **MISRA-C violations.** Every agent-filled body must be MISRA-C
  compliant: one statement per line, explicit casts on mixed-type
  arithmetic, no fall-through in `switch`, every return path
  explicitly assigned, no unbalanced braces, no implicit
  conversions losing precision.
* **Missing `Qualifier_N` check.** Sub-pattern B without the
  qualifier guard reports stale data when the network is down.
* **Hard-coded product assumption.** Even a "DPB-only" DID needs
  the `#if (RBFS_DCOMDomain == ...)` guard so the file builds
  cleanly when the same source tree is compiled for sibling
  products.
* **Forgetting the `_GeneralFunctions` includes.** RAM-pattern
  files almost always need `#include "RBAPLCUST_Global.h"` (and
  often `RBAPLCUST_GeneralFunctions.h`). The inline `TODO(agent)`
  block lists the minimum include set.

---

## 4. Write side (WDBI) for non-EEPROM DIDs

The reference code base does not write back to ROM (it's
read-only by definition) and writes to RAM only via dedicated
`WDBI_*.c` files that mirror the read-side macros (e.g.
`RBAPLCUST_WDBI_RemoteActuationMode.c`,
`RBAPLCUST_WDBI_APBSystemSwitching.c`).

When `rw_state == "RW"` and `storage_pos != "EEPROM"`:

* **ROM:** This is a configuration error — ROM is read-only.
  Phase 3 still emits a `WDBI` stub but the inline `TODO(agent)`
  block flags it as `storage_pos=ROM with rw_state=RW` and asks
  the operator to either drop the write side or reclassify the
  DID to RAM / EEPROM. Don't fill the stub until that's resolved.
* **RAM:** Mirror the read-side macro family (sub-pattern B or C),
  but use `XmtMESGDef` / `RBMESG_XmtMESGDef` for the transmit
  side. Reference: `RBAPLCUST_WDBI_RemoteActuationMode.c`.

The inline `TODO(agent)` block on the WDBI stub carries the same
per-service `behavior_2e` text, so the agent can plan write-side
translation symmetrically with read.

---

## 5. Context-lookup paths (agent search hints)

Some RAM / ROM DID bodies need context from elsewhere in the
Bosch project tree — the matching signal definition, a typedef,
an `aswif` getter prototype, an existing `bcfg` slot, a Freestyle
Switch (`RBFS_*`) macro — before the agent can write a correct
body. **Scanning the entire tree is slow and noisy.** Search the
curated paths below first; only fall back to a wider grep when
none of them match.

The customer segment (e.g. `rbcn` / `jac` / `acme`) is baked into
`paths.base_dir` at `--init-project` time — the literal value
already shipped with the workspace replaces `<customer>` below.
`{product_type_lower}` resolves to the per-iteration product
slug exactly the same way `paths.config_settings_h` does (see
[`configuration.md`](configuration.md) for the placeholder map).

### 5.1 Curated paths (search in this order)

| # | Path (relative to `paths.base_dir`) | Why look here |
|---|---|---|
| 1 | `Fe_Super/rb/as/cnms_core/app/dcom` | Cross-customer DCOM core: shared service-22/2E definitions, common DID enum maps. Start here for anything that smells "framework-wide". |
| 2 | `Fe_Super/rb/as/core/app/dcom` | Customer-agnostic DCOM layer below `cnms_core` — generic Std_ReturnType helpers, NvM block descriptors. |
| 3 | `Fe_Super/rb/as/<customer>/core/app/dcom` | Customer-specific DCOM overlay — customer-tuned DID handlers, RBAPLCust glue. |
| 4 | `Fe_Super/rb/as/<customer>/{product_type_lower}/app/asw/aswif` | Per-product ASW interface — getter / setter prototypes and the include path the `.c` body needs to reach internal signals (battery voltage, raw sensor outputs, etc.). Primary target for **sub-pattern A** (direct getter) bodies. |
| 5 | `Fe_Super/rb/as/<customer>/{product_type_lower}/dcompr` | Per-product DCOM project config — `.bcfg` files defining the DID slot, FS macro switches (`RBFS_DCOM_<Name>_ON/_OFF`), session / security mappings. Look here when the body needs to gate on a `RBFS_*` switch. |
| 6 | `Fe_Super/rb/as/<customer>/{product_type_lower}/cswpr` | Per-product CSW project — communication stack wiring, RBMESG / NMSG signal name lookups. Primary target for **sub-pattern B / C** (`*MESGDef`) bodies. |
| 7 | `Fe_Super/rb/as/<customer>/csw/project` | Customer-level CSW project bundle — top-of-funnel `.cswpr` / `.bcfg` indices, often the fastest way to discover which `.cswpr` carries a given signal. |

Search hits should always be cross-checked by reading the file's
surrounding context — a typedef name alone isn't enough; the
agent needs to see the field shape, the `#define` family, and
the `#if` guards around the symbol before pasting it into the
DID body.

### 5.2 Edit + operator-confirmation contract

While drafting the body the agent may need to touch supporting
artefacts beyond the generated `.c`. The contract:

| Change kind | Agent is allowed to | Operator confirmation required when |
|---|---|---|
| **Inside the generated `.c`** (replace the `TODO(agent)` block with the real body, fix includes, add `static` helpers within the same file) | Always — that is the Phase 3 fill-in contract. | Never — agent owns the body. |
| **`.bcfg`** entry edit / addition (a new DID slot, a tweaked session set) | Apply small, well-scoped edits when the FSCS Behavior text + a curated-path search clearly point at the change. | The edit changes existing operator-set values (session mask, security level, RBFS gating) or introduces a new ECUC container the operator didn't ask for. **Stop and ask.** |
| **`.h`** edit (add a `#define` block, a new typedef, extend an enum) | Append to the matching header inside the project's `api/` folder when the body needs a symbol that doesn't exist yet. | The edit modifies a customer-shipped header (anything not under the per-product `api/` folder), or introduces an enum value that conflicts with an existing one. **Stop and ask.** |
| **`RBFS_*` Freestyle Switch macros (`#FS`)** — flip ON/OFF, add a new switch | Flip a switch the FSCS Behavior text explicitly cites, or add a new `RBFS_DCOM_<DidName>_ON` definition next to its peers when the curated paths show the existing pattern. | The flip changes an *unrelated* DID's enablement, or the new switch crosses customer / product boundaries (e.g. defining the same `RBFS_*` for both DPB and ESP via a single file). **Stop and ask.** |

When the agent stops to ask, it should:
1. Quote the exact path + line range the edit would touch,
2. Show a one-line diff of the proposed change,
3. End the turn with `[AGENT STOP]` so the operator can reply.

### 5.3 Closing summary (after the round completes)

When every fill-target for the current Phase 3 run has been
addressed (replaced with a real body OR explicitly left as a stub
because the FSCS Behavior was empty), the agent emits a single
summary block before stopping:

```
[AGENT REVIEW] Phase 3 fill-in complete.
  Filled (N):   <DID_hex> <DID_name>  →  <relative path>
                ...
  Left as stub (M, FSCS Behavior empty):
                <DID_hex> <DID_name>  →  <relative path>
                ...
  Project-tree edits beyond the generated .c (K):
                <relative path>  →  <one-line description>
                ...
  Operator decisions captured this round (J):
                <short note + decision>
                ...
Please review the listed files; reply "done" / "looks good" /
"继续" once verified, or call out anything to revise.
```

This summary doubles as a CI checkpoint and as the operator's
review queue — the per-product
`.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/generation_report.txt` carries
the framework-generation side of the same data, but the summary
above is the **agent's** record of what was filled / skipped /
edited in this turn.

---

## 6. End-to-end agent workflow

1. **Run Phase 3 normally.** The pipeline writes the `.c`
   framework into the Bosch tree (skip-on-conflict) and embeds
   an inline `TODO(agent)` block at the top of every non-EEPROM
   `.c`.
2. **Enumerate fill targets from the Phase 3 footer:**

   ```text
   [AGENT TODO] Phase 3 framework done. 12 fill / 3 stub.
     Fill targets (expand inline TODO this turn): ...
     Stub targets (behaviour empty — leave TODO in place): ...
   ```

   The per-product `.DCOM_AI/DID_Toolkit_PRJ/outputs/implementation/<PT>/generation_report.txt`
   carries the same lists for audit / CI integration.

3. **For each fill target (RAM / Internal-Interface DIDs only):**
   * Read the inline `TODO(agent)` block at the top of the
     generated `.c` — it carries DID identity, storage
     classification, RAM sub-pattern guess, and the FSCS
     behaviour text.
   * Read this file's matching section (§3 for `RAM`).
   * **Search the curated context paths (§5.1) first** to locate
     signal definitions, getter prototypes, RBMESG names, and
     `RBFS_*` switches the body needs to reference. Only fall
     back to a wider grep when none of §5.1 yield a hit.
   * Read at least one of the listed reference files in full so
     the indentation, comment style, and macro spelling match
     the project's house style.
   * Replace the `TODO(agent)` block in the generated
     `RBAPLCUST_RDBI_<Name>.c` with the real implementation.
   * For any project-tree edit beyond the generated `.c`
     (`.bcfg` / `.h` / `RBFS_*`), apply the §5.2
     edit + operator-confirmation contract: stop and ask when
     the change crosses an existing operator-set value, a
     customer-shipped header, or an unrelated DID's enablement.

   **HardCode DIDs (v2.4.0+):** These are fully auto-generated and do
   not contain a `TODO(agent)` block.  Skip the replace step above;
   instead perform the review checklist in §2.4 (verify hex values,
   byte count, and TODO markers on fallback bytes).
4. **Emit the closing summary (§5.3)** once all fill targets
   have been addressed — list filled DIDs, stubs left in place,
   project-tree edits, and any operator decisions captured this
   round, then stop and ask the operator to review.
5. **Re-run Phase 3** if the FSCS `behavior` text changes
   upstream. The generator detects unfilled stubs by scanning
   for the `TODO(agent)` marker and reports a count in
   `validation_report.txt`. A clean release has zero unfilled
   stubs.

If the FSCS `behavior` text is wrong, **edit
`fscs_edit.xlsx::behavior_*` upstream and re-run
`--phase xlsx-import` + `--phase implementation`** rather than
trying to compensate in the `.c`. The behaviour text is the
source of truth.

---

## 7. House style cheatsheet

* **Function signature.** Read functions for ESP/DPB use the
  AUTOSAR macros: `FUNC(Std_ReturnType, DCM_APPL_CODE) ...
  (P2VAR(uint8, AUTOMATIC, DCM_INTERN_DATA) Data)`. Read
  functions for IPB/RBU sometimes use the simpler
  `Std_ReturnType ... (uint8 * Data)`. **Match the surrounding
  files in the same directory** — don't mix styles within one
  product folder.
* **Tabs, not spaces** in `RBAPLCust/src/...` (the existing
  files all use tabs; preserve that).
* **Comment block at the top** mirrors the reference files:
  `FUNCTION_NAME` / `FUNCTION_DESCRIPTION` / `FUNCTION_PARAMETER`
  / `FUNCTION_RETURN` block. The inline `TODO(agent)` block at
  the head of every generated `.c` carries a pre-filled template
  you can paste verbatim.
* **Header guard format.**
  `RBAPLCUST_RDBI_<UPPER_NAME>_H__` (note the trailing double
  underscore — see existing `RBAPLCUST_RDBI_VersionNumber.h`).
* **License header** at the top of every new file — copy verbatim
  from any existing `RBAPLCust/src/Common/*.c`.

---

## 8. References on disk

Skill source (this doc + framework / inline-TODO generator):

```
<skill>/reference/implementation-storage-positions.md   ← you are here
<skill>/scripts/implementation/generators.py            ← stub + inline TODO emitter
<skill>/scripts/implementation/orchestrator.py          ← per-product fan-out
```

Curated project-tree paths to search first (see §5.1 for the
full table and what each one carries):

```
Fe_Super/rb/as/cnms_core/app/dcom                                ← framework-wide DCOM
Fe_Super/rb/as/core/app/dcom                                     ← customer-agnostic core
Fe_Super/rb/as/<customer>/core/app/dcom                          ← customer-specific overlay
Fe_Super/rb/as/<customer>/{product_type_lower}/app/asw/aswif     ← ASW getter prototypes
Fe_Super/rb/as/<customer>/{product_type_lower}/dcompr            ← DCOM .bcfg + RBFS_* switches
Fe_Super/rb/as/<customer>/{product_type_lower}/cswpr             ← CSW signal / RBMESG defs
Fe_Super/rb/as/<customer>/csw/project                            ← top-of-funnel CSW index
```

When in doubt, read at least one neighbour `.c` file in the same
project directory before writing — the local convention always
wins over this document.
