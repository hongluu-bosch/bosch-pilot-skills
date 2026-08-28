# DiagComm transforms (forward + reverse)

Every parameter travels between **user-input space** and **arxml literal
space** via a named transform. Forward transforms are applied by
`apply`; reverse transforms are applied by the lazy-seed / `reseed`
reverse walk that produces `outputs/reseed_suggestion.json` from live arxml (run via `pipeline.py reseed --from-arxml`; the user transcribes the suggestions into `inputs/DiagComm.xlsx` by hand)
values. Both registries live in `scripts/mapping.py`.

- `TRANSFORMS[name]` — forward: user input → arxml literal (string)
- `REVERSE_TRANSFORMS[name]` — reverse: arxml literal → user value

Forward and reverse are inverses up to the input's normalisation (case,
whitespace, `0x`/decimal form).

---

| Name | Forward (user → arxml) | Reverse (arxml → user) | Used by |
|---|---|---|---|
| `hex_to_decimal` | `"0x7DF"` / `2015` / `"2015"` → `"2015"` (decimal literal) | `"170"` → `"0xAA"` (2-digit-padded hex) | CAN IDs, `PaddingByte` |
| `ms_to_seconds` | `25` (ms) → `"0.025"` | `"0.025"` → `25` (ms, int when whole) | All timers: `N_*`, `P2_Max`, `P2_Star_Max`, `STmin` |
| `float_seconds` | seconds literal passthrough (formatted) | `"0.05"` → `0.05` | *(legacy, no active mappings)* |
| `int_str` | `8` → `"8"` | `"8"` → `8` | `BS`, `CAN_DLC.TX_DL` |
| `bool_str` | `True` / `"true"` / `"yes"` / `1` / `"on"` → `"true"`; falsy variants → `"false"` | `"true"` → `True`, otherwise `False` | `StrictDlcCheck` |
| `can_id_type` | `"11bit"` → `"STANDARD"`, `"29bit"` → `"EXTENDED"` | `"STANDARD"` → `"11bit"`, `"EXTENDED"` → `"29bit"` | `CAN_ID_Format` |
| `addressing_format` | `"Normal"` → `"CANTP_STANDARD"`; `"NormalFixed"` → `"CANTP_NORMALFIXED"`; `"Extended"` → `"CANTP_EXTENDED"` | `"CANTP_STANDARD"` → `"Normal"`, etc. | `Addressing_Method` |
| `canfd_support` | `"CANFD"` → `"true"`, `"ClassicCAN"` → `"false"` | *(PR — no reverse needed)* | `CAN_DLC.frame_type` (FD flag in `cantp_feature_file`) |
| `canfd_pdu_id_type` | `"ClassicCAN"` → `"STANDARD_CAN"`, `"CANFD"` → `"STANDARD_FD_CAN"` | *(PR — no reverse needed)* | `CAN_DLC.frame_type` (`CanIf*PduCanIdType` in `can_pt_file`) |
| `identity` | `str(v)` passthrough | `str(v)` passthrough | *(unused fallback)* |

---

## Notes per transform

- **`hex_to_decimal`** — the forward transform auto-detects hex by
  looking at `0x` prefix OR presence of `[a-f]` digits (so a bare
  `"AA"` is also treated as hex). The reverse emits at least two hex
  digits, always with `0x` prefix, so `PaddingByte` round-trips as
  `0x00 .. 0xFF`. CAN IDs round-trip with whatever natural width the
  hex digits produce (e.g. `"1857"` ↔ `"0x741"`).

- **`ms_to_seconds`** — uses Python's `format(f, "g")` for compact
  literals (`0.025`, not `0.0250000`). The reverse emits an `int` when
  the millisecond result is whole (e.g. `25`, not `25.0`) to keep
  `DiagComm_values.json` tidy.

- **`bool_str`** — accepts `"true"/"1"/"yes"/"y"/"on"` and their
  negative counterparts, case-insensitive. Unknown strings raise
  `ValueError` (surfaced by `apply` as a per-entry warning).

- **`canfd_support` / `canfd_pdu_id_type`** — both drive the same
  `CAN_DLC.frame_type` user field but target different files. They are
  marked PR, so the lazy-seed reverse walk deliberately does NOT
  provide a reverse (the user must re-choose the frame type each
  session).

---

## Adding a new transform

1. Define forward `_my_xform` and reverse `_rev_my_xform` in
   `scripts/mapping.py`.
2. Register: `TRANSFORMS["my_xform"] = _my_xform`,
   `REVERSE_TRANSFORMS["my_xform"] = _rev_my_xform`.
3. Add a row to the table above.
4. Reference the transform name in the relevant `PARAM_MAP` entries.
5. Smoke-test round-trip:

   ```bash
   python <skill>/scripts/pipeline.py reseed --from-arxml   # exercise reverse walk; result in workspace outputs/reseed_suggestion.json
   python <skill>/scripts/pipeline.py reseed
   python <skill>/scripts/pipeline.py validate # exercise forward transform load
   ```
