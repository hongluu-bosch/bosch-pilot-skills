# Phase 2 — ARXML

Phase 2 reads `outputs/fscs/fscs.json` and merges freeze-frame
configuration into the Bosch project tree.

## Target files

The generator scans `rb/as/<customer>/core/app/dsm/Cubas_DEM/` for
ARXML files matching the pattern:

```
DemEnvData_RBAPLCUST_EcucValues[.<suffix>].arxml
```

Suffix matching (configurable in `config/project.json`):

| Product type | Preferred suffix | Fallback |
|---|---|---|
| `Common` | `_Common` | no suffix |
| `RBU` | `_RBU` | no suffix |
| `IPB` | `_IPB` | no suffix |
| `ESP` | `_ESP` | no suffix |
| `DPB` | `_DPB` | no suffix |
| `ESPCL` | `_ESPCL` | no suffix |
| `<custom>` | `_<custom>` | no suffix |

The skill first tries to resolve a target automatically. If multiple
candidates match, or no candidate matches, it lists the candidates and
asks the operator to pick one.

## Generated containers

For each effective DID in the work-set:

1. `DemFreezeFrameClass_<class>` — updated with `DemDidClassRef` list.
2. `DemDidClass_<did>` — `DemDidIdentifier` + `DemDidDataElementClassRef`.
3. `DemDataElementClass_<did>` — `DemExternalCSDataElementClass` with:
   - `DemDataElementReadFnc`
   - `DemDataElementUsePort = false`
   - `DemDataElementProvideMonitorData = false`
   - `DemDataElementArraySize`

`DemFreezeFrameRecNumClass_<class>` is **not** created automatically.
Only projects that need more than one snapshot record layout need this
container; create it manually in the ARXML before running Phase 2 if
required.

## Merge policy

### Skip-on-conflict by `DemDidIdentifier`

A DID is identified by its numeric `DemDidIdentifier` value, not by the
`SHORT-NAME` of its container.  If the target ARXML already contains a
`DemDidClass_*` with the same identifier — regardless of whether it uses a
plain name (`DemDidClass_0x1100`) or a descriptive suffix
(`DemDidClass_0x1100_WheelSpeed`) — Phase 2 **reuses the existing container**
and does not create a second DID class.

The same reuse logic is applied to `DemDataElementClass_*`: Phase 2 follows
the existing `DemDidClass -> DemDidDataElementClassRef` to find the data
element container that is already in use and reuses it.  This prevents
duplicate data element containers when the existing file uses descriptive
suffixes such as `DemDataElementClass_0x1100_WheelSpeed`.

### Descriptive suffixes for new DIDs

For DIDs that are not yet present in the ARXML, Phase 2 derives a
descriptive `SHORT-NAME` suffix from `did_name_en`.  Common stop words such
as `at`, `last`, `fault`, `code`, `set`, `and`, etc. are removed and the
remaining words are concatenated in CamelCase.

Examples:

| DID name (EN) | Generated suffix |
|---|---|
| `Wheel Speed and vehicle speed at Last Fault Code Set` | `WheelSpeedVehicleSpeed` |
| `ESP system general status at Last Fault Code Set` | `ESPSystemGeneralStatus` |
| `TestStatus` | `TestStatus` |
| `AVH status` | `AVHStatus` |

The resulting containers look like:

- `DemDidClass_0x2131_TestStatus`
- `DemDataElementClass_0x2131_TestStatus`
- `DemExternalCSDataElementClass_0x2131_TestStatus`

If the generated descriptive `SHORT-NAME` is already taken by an unrelated
container, Phase 2 falls back to the plain name (`DemDidClass_0x2131`) and
appends a numeric disambiguator if necessary.  The merge report lists every
reuse, skip, and fallback.

## Structural safety

Phase 2 uses `lxml` to parse and modify the ARXML tree. After writing,
a verification pass ensures that no existing `ECUC-CONTAINER-VALUE`
`SHORT-NAME` was removed. Whitespace/indentation may be normalized by the
serializer, but all semantic content and container structure is preserved.
