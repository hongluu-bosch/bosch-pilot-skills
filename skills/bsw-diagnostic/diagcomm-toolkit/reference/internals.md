# diagcomm-toolkit internals

Deep technical notes. The day-to-day protocol lives in
[`../SKILL.md`](../SKILL.md); read this file only when the user asks
about safety, validation rules, or the apply pipeline.

## Safety guarantees

1. **Surgical byte-level writes.** Only the inner text of each matched
   `<VALUE>…</VALUE>` node is rewritten. XML declaration, namespaces,
   CRLF/LF line endings, comments, and every byte outside the matched
   VALUE range stay byte-identical. `git diff` of a patched arxml
   shows only the VALUE nodes the user intended to change.
2. **Dry-run by default** (`options.dry_run_default=true`). `--apply`
   is required to write.
3. **No-match → no-write.** Unresolved locators emit `WARN` and are
   skipped; the file is left alone. The patcher never blindly writes
   a value.
4. **Rollback via VCS.** The skill keeps **no local backups**. Every
   supported project ships inside a source-control tree (git / SVN /
   Jazz / …) which is the single source of truth for rolling an apply
   back (`git checkout -- <arxml>`, `svn revert <arxml>`, …). The
   `outputs/diff_report.txt` from the failing run is the authoritative
   list of files that need reverting.
5. **Semantic pre-checks.** `validate` and `apply` refuse to run
   (exit 2) unless:
   - `CAN_Functional_Request_ID` / `CAN_Physical_Request_ID` /
     `CAN_Response_ID` fit `CAN_ID_Format` (11-bit → `0x7FF`,
     29-bit → `0x1FFFFFFF`)
   - `STmin` ∈ `0..127` ms (AUTOSAR / ISO 15765-2 cap)
   - `PaddingByte` ∈ `0..0xFF` (hex or decimal)
   - `NRC78_Times` ∈ `0..255`
   - `ClassicCAN` frame type forces `dl=8`
6. **Paper trail.** `outputs/diff_report.txt` and
   `outputs/validation_report.txt` persist across runs.

## Unit and convention notes

- **Timers in milliseconds.** `N_*`, `P2_Max`, `P2_Star_Max`, `STmin`
  are all entered in ms. The pipeline divides by 1000 when writing
  ARXML — do not pre-divide.
- **Asymmetric RX/TX.** The four `CAN_DLC.*` sub-fields (RX/TX ×
  request/response) are collected independently so RX and TX can
  differ. `CanTpFlexibleDataRateSupport` is **derived** at apply-time
  (true iff either direction uses CANFD) and never asked of the user.

## Parameter → arxml mapping

- **Locator catalogue** — file alias + DEFINITION-REF suffix + ancestor
  SHORT-NAME + transform + expected hit count →
  [`landing_spots.md`](./landing_spots.md).
- **Type / range / default / PR-flag tables** →
  [`parameter_types.md`](./parameter_types.md).
- **Value transforms** (user units ↔ AUTOSAR literals) →
  [`transforms.md`](./transforms.md).
- **Machine-readable source** — `scripts/mapping.py::PARAM_MAP` +
  `scripts/mapping.yaml`.

### Verifying project alignment

```bash
python <skill>/scripts/pipeline.py landing-report
```

Writes `outputs/landing_report.txt` listing every resolved target node
with its current VALUE. Unmatched locators print `(0 hit(s))`; fix by
extending `PARAM_MAP` (for a genuinely different container name) or
the matching alias under `inputs/DiagComm.xlsx::Sheet 'Paths & Options'::paths.*` (for a
relocated file).
