# Changelog

All notable changes to this skill are captured here. Dates are the
release date; versions follow [Semantic Versioning](https://semver.org/).

## [2.0.3] - 2026-05-16  -- portability scrub: drop project-codename leaks, env-var the DOORS MCP URL

Pure cleanup. No code paths, no schema, no flags, no migration. Goal:
make the skill cleaner for users on other machines / other projects /
other Bosch sub-organisations. The v2.0.0 split moved the skill out of
``<project>/.agents/...`` into a single user-level checkout, which means
the same files are now read by every project on the machine -- so any
project-codename or DOORS-row identifier baked into the source-of-record
docs leaks one team's vocabulary into every other team's workspace. This
pass strips those leaks and makes the one remaining environment-specific
default (the DOORS MCP server URL) override-able without editing the
source.

Fixed
~~~~~
- ``reference/porting_checklist.md``: the "nothing here references X
  directly" sentence used to list four real project / platform codenames
  (``Fe_Super`` / ``rbcn`` / ``DPB`` / ``CNMS_Ferrum``). Of those, only
  ``DPB`` is actually neutral (it is one of the four product-type enums
  defined in the schema; ``DPB`` / ``ESP`` / ``IPB`` / ``RBU``). The
  other three were leaks from one specific Bosch sub-project. Rewrote
  the sentence to call out the neutral primitives only (standard layout
  templates ``*/rb/as/*/core/app/dcom``, ``RBAPLCust/...``,
  ``Cubas/...``, plus the four product-type enums).
- ``reference/doors_mapping_format.md``: replaced two ``"/CNMS/..."``
  example DOORS module paths with the generic placeholder
  ``"/<DocTree>/..."``. These were YAML examples, not anything any code
  parses -- but a new operator reading the file would naturally copy
  them verbatim into their own ``doors_mapping.yaml``, then waste a
  Step 8 round-trip discovering the path doesn't exist in their tree.
- The hard-coded example row identifier ``503571_SWFS_SWCS_DCOM_400``
  (a real row from one Bosch project's DOORS module) was used as the
  "expected output" / "for example" sample in four places. Replaced
  everywhere with the shape-only placeholder
  ``<DOC>_SWFS_<SECTION>_NNN`` -- enough for the reader to recognise
  the pattern, no real value leaked:
    - ``SKILL.md`` Step 7.5d "Expected: exactly one identifier" hint.
    - ``reference/doors_mapping_format.md`` ``anchor.by_identifier``
      fallback example.
    - ``assets/doors_mapping_skeleton.yaml`` ``anchor.by_identifier``
      fallback example AND the long comment in the ``columns``
      section that warns DOORS rejects the full identifier prefix.
    - ``scripts/build_doors_payload.py`` module docstring's
      ``insert / update`` mode explanation.
- The internal-team DOORS MCP server URL ``http://10.54.7.36:8000/mcp``
  is now read from the ``DIAGCOMM_DOORS_MCP_URL`` environment variable
  at import time, with the same bundled value as the fallback. Affects
  ``scripts/doors_fetch.py`` (gained ``import os``),
  ``scripts/doors_upload.py``, ``scripts/doors_sync.py``. The
  ``--server-url`` CLI flag on every one of them still wins over both
  (resolution order: CLI > env var > bundled default), so existing
  invocations behave identically. Operators on a different VPN / a
  different DOORS MCP host can now ``export
  DIAGCOMM_DOORS_MCP_URL=http://<host>:<port>/mcp`` once and forget.
- ``SKILL.md`` Troubleshooting table: the row for ``connection refused
  10.54.7.36`` now refers to ``<doors-mcp-host>`` generically and points
  the operator at the new ``DIAGCOMM_DOORS_MCP_URL`` env var as the fix
  for "the default URL doesn't match your environment". The off-VPN /
  server-down advice is unchanged.
- ``reference/porting_checklist.md`` Prerequisites: added one optional
  bullet documenting ``DIAGCOMM_DOORS_MCP_URL`` for first-time setup on
  a host with a non-default DOORS MCP server.

Not changed
~~~~~~~~~~~
- No code paths, no schemas, no flags, no test changes. 137/137 tests
  still pass.
- Bundled team default ``http://10.54.7.36:8000/mcp`` is preserved as
  the fallback -- everyone already on the internal network keeps working
  with zero configuration. The env var only matters for off-network
  installs.
- ``assets/inputs_template.xlsx`` is already neutral: ``project.name``
  blank, ``project.product_type`` blank, ``doors.document_uuid``
  =``PUT-DOORS-DOCUMENT-UUID-HERE``, all path defaults are layout
  templates (e.g. ``RBAPLCust/cfg/Common/...``). Verified during this
  pass -- no change needed.
- Bosch CusDiag stack vocabulary that is *part of the skill's contract*
  (``CusDiag`` itself, the four product-type enums, the
  ``rb/as/<bsw>/core/app/dcom/`` layout template, the
  ``RBAPLCust/`` / ``Cubas/`` directory names) is kept verbatim -- the
  skill explicitly targets that stack and these names are the literal
  on-disk paths every consumer sees, not project-private codenames.
- Historical CHANGELOG entries (1.5.x .. 2.0.2) are left intact, even
  though they still mention ``503571_SWFS_...`` /
  ``http://10.54.7.36:...`` -- those entries describe what happened
  in past releases and rewriting them would falsify history.

## [2.0.2] - 2026-05-16  -- v2.0.1 follow-up: finish the path cleanup

Second cleanup pass on top of v2.0.1. No code paths, no schema, no
flags, no migration. Same goal as v2.0.1 -- every runtime-printed hint
should be a literal command the user can copy-paste from any cwd -- but
v2.0.1 missed a batch of ``ImportError`` -> ``SystemExit`` guards that
still pointed at the v1 relative ``scripts/requirements.txt`` form, and
one of them in ``build_doors_payload.py`` still pointed at the dead
v1 sibling skill ``../doors-toolkit/scripts/requirements.txt``. v2.0.0
explicitly cut that dependency ("Step 8 is fully self-contained inside
``diagcomm-toolkit``"); the leftover hint would send the user at a path
that does not exist on a user-level v2 install.

Fixed
~~~~~
- ``build_doors_payload.py::_load_yaml`` no longer references the v1
  sibling skill ``../doors-toolkit/scripts/requirements.txt``. It (and
  ``write_workbook`` / ``_read_template_columns``) now print
  ``<SKILL_ROOT>/scripts/requirements.txt`` resolved against the bundled
  ``HERE`` constant.
- ``doors_sync.py``: PyYAML-missing guard + keyring-missing warning
  now print the resolved ``SKILL_ROOT`` path.
- ``doors_upload.py`` and ``doors_fetch.py`` gained a module-level
  ``SKILL_ROOT`` constant (consistent with the rest of the scripts/)
  and their ``requests``-missing guards print the resolved path.
- ``doors_helper.py``: PyYAML-missing guard prints the resolved
  ``HERE.parent / scripts / requirements.txt`` instead of a relative
  hint. Module docstring rewritten to drop the stale "replacement for
  doors-toolkit/scripts/pipeline.py" line; v2.0.0 cut that link.
- ``pipeline.py::cmd_status``:
  - The ``BROKEN`` deps row now prints the resolved
    ``<skill>/scripts/requirements.txt`` (was the bare relative form).
  - Added a ``workspace root`` line right under ``skill root`` so the
    Step 2 dashboard matches the dual-root contract ``context.py`` /
    ``preflight.py`` already follow. Tagged ``(NOT INITIALIZED)`` when
    the workspace does not exist yet.
- ``mapping.py``: import-time PyYAML guard prints the resolved
  ``scripts/requirements.txt`` path.
- ``excel_io.py``: openpyxl guard prints the resolved path AND drops
  the stale ``"doors-toolkit:"`` branding prefix (correct prefix is
  now ``"diagcomm-toolkit:"``).
- ``preflight.py``:
  - ``_check_module`` FAIL row + ``_check_user_xlsx`` openpyxl WARN
    row now print the resolved ``SKILL_ROOT/scripts/requirements.txt``.
  - The workspace-missing FAIL detail and the final "Status: READY.
    Next:" hint no longer print the literal ``<skill>`` placeholder;
    both now print the resolved ``SKILL_ROOT/scripts/pipeline.py``
    path the user can copy verbatim. The earlier in-function paths
    were already resolved -- this pass fixes the remaining two lines
    v2.0.1 missed.
- ``json_query.py``: module docstring rewritten to say
  ``diagcomm-toolkit (Step 7.5 / 8 helpers)`` instead of the stale
  ``"for the doors-toolkit"`` first line. (The file has been part of
  this skill since well before the v2.0.0 split.)
- ``arxml_patcher.py``: import-time lxml guard prints the resolved
  ``<SKILL_ROOT>/scripts/requirements.txt`` instead of the bare
  relative form.
- ``pipeline.py --init-project`` now runs a one-shot localization
  pass on the freshly-copied ``inputs/DiagComm.xlsx``: every
  ``<skill>`` placeholder on the README sheet (Trouble-shooting
  recipes) is rewritten to the resolved ``SKILL_ROOT`` path so the
  user can copy commands out of Excel without manual substitution.
  Best-effort and silent on openpyxl-missing / read-only-fs; a new
  ``[patch ]`` summary line is printed when the rewrite actually
  ran. ``assets/inputs_template.xlsx`` itself keeps the ``<skill>``
  placeholder because the template is shared across every install.
- ``SKILL.md`` "Deep-dive docs" list: removed the dead
  ``[../doors-toolkit/SKILL.md]`` cross-link. The user-level install
  has no sibling at ``~/.cursor/skills/doors-toolkit/``, and v2.0.0
  already noted "this skill no longer depends on it" -- the link only
  invited confusion.

Not changed
~~~~~~~~~~~
- No code paths, no schemas, no flags, no test changes. 137/137 tests
  still pass.
- Historical CHANGELOG entries (1.5.x .. 2.0.1) are left intact.

## [2.0.1] - 2026-05-16  -- v2.0.0 follow-up: docs / hint cleanup

Pure cleanup release. No code-path or schema change, no new flags, no
migration. Fixes the v2.0.0 docs and runtime hints that still pointed
at the v1 ``python scripts/...`` invocation form (only valid when the
skill checkout was the workspace) instead of the v2 ``python
<skill>/scripts/...`` form (run from the project root).

Fixed
~~~~~
- ``SKILL.md``:
  - All Step 2-8 command examples (~17 places), Hard rules 4 / 7 / 8 /
    9 / 10, the Edge-case recipes table, and the Troubleshooting table
    rewritten from ``python scripts/...`` to
    ``python <skill>/scripts/...``.
  - The ``state/doors_upload_state.json`` section described the v1
    in-skill location ("sibling of inputs/ and outputs/" + "ships with
    .gitkeep and a README.md") -- rewritten to point at
    ``<workspace>/state/`` and to note the skill checkout no longer
    ships ``state/`` at all.
  - Dead cross-link ``[state/README.md](state/README.md)`` -- now
    ``[reference/state_recovery.md]`` (the file was ``git mv``'d in
    v2.0.0).
  - Pre-flight checklist's ``cp assets/inputs_template.xlsx ...``
    recovery hint -- replaced with the v2 reset path
    ``python <skill>/scripts/pipeline.py --init-project --force`` and
    clarified it is destructive + must be user-driven.
  - The path-conventions paragraph claimed commands were "written as
    ``python scripts/...`` for brevity" -- no longer true after the
    rewrite; paragraph rewritten to match the corpus.
- Runtime-printed hints (stderr / report files) now print actual
  resolved filesystem paths via ``HERE / "..."`` /
  ``SKILL_ROOT / "..."`` instead of the literal ``python scripts/...``
  string, so the user can copy them verbatim regardless of where the
  skill is installed:
  - ``preflight.py``: schema-drift hint
  - ``doors_sync.py``: cache-refresh fallback hint + reconcile-failure
    recovery hint
  - ``build_doors_payload.py``: "run apply --apply first" error hints
    (x2) + "next step: doors_upload" hint
  - ``reports.py``: ``<skill>/scripts/...`` banner injected into
    ``reference/landing_spots.md``
- Module docstrings (``--help`` output) and one YAML comment header
  switched to the ``<skill>/scripts/...`` placeholder with a one-line
  note explaining ``<skill>``: ``excel_loader.py``, ``doors_sync.py``,
  ``doors_upload.py``, ``doors_fetch.py``, ``build_inputs_template.py``,
  ``migrate_v1_19_to_xlsx.py``, ``runtime.py``, ``mapping.yaml``.
- ``assets/inputs_template.xlsx`` -- regenerated. Its in-workbook
  README sheet had stale ``cp assets/inputs_template.xlsx
  inputs/DiagComm.xlsx`` and ``python scripts/migrate_v1_19_to_xlsx.py``
  recovery hints; both now describe the v2 ``--init-project --force``
  / ``--legacy-from`` flow.

Not changed
~~~~~~~~~~~
- ``CHANGELOG.md`` historical entries (1.5.x .. 1.20.x) are left
  intact -- those ``python scripts/...`` references describe what
  those versions actually shipped and shouldn't be retroactively
  edited.
- No code paths, no schemas, no flags, no test changes. 137/137 tests
  still pass.

## [2.0.0] - 2026-05-15  -- BREAKING: user-level skill + per-project workspace

The skill becomes a **user-level installation** mirroring how
`did-toolkit` works. The single checkout at
`~/.cursor/skills/diagcomm-toolkit/` carries only immutable assets
(scripts / templates / docs / tests); each project the operator works
on gets its own per-project workspace under
`<project>/.DCOM_AI/DiagComm_Toolkit_PRJ/` that owns the user-edited
Excel, the `.cache/` derivative files, generation `outputs/`, and DOORS
upload `state/`. One skill clone, many projects.

```text
~/.cursor/skills/diagcomm-toolkit/        # bundled (one copy, git-tracked)
  scripts/  assets/  reference/  tests/

<project-root>/.DCOM_AI/DiagComm_Toolkit_PRJ/   # per-project workspace
  inputs/DiagComm.xlsx                          # the only user-editable file
  .cache/                                       # auto-derived from xlsx
  outputs/                                      # generation reports
  state/doors_upload_state.json                 # DOORS sync state
```

### Migration (one-shot, per project)

```bash
cd <project-root>                                # the dir owning your AUTOSAR tree
python ~/.cursor/skills/diagcomm-toolkit/scripts/migrate_v1_20_to_v2.py \
    --from-skill <project-root>/.agents/skills/diagcomm-toolkit
```

`migrate_v1_20_to_v2.py` lifts `inputs/DiagComm.xlsx` + `state/` (+
optionally `outputs/` and `.cache/`) out of the old in-skill location
into the new workspace, atomic-moves each file, rewrites the v1
default `paths.base_dir = "../../.."` -> v2 default `"../.."`, and
prints the `rm -rf <old skill checkout>` cleanup command for the user
to run after verifying `pipeline.py status` reports READY.

For users still on **v1.19.x**, run `migrate_v1_19_to_xlsx.py` first
(now workspace-aware via `--legacy-from <dir>`), then `migrate_v1_20_to_v2.py`.

### Bootstrap workflow (fresh projects)

```bash
cd <project-root>
python ~/.cursor/skills/diagcomm-toolkit/scripts/pipeline.py --init-project
# scaffolds .DCOM_AI/DiagComm_Toolkit_PRJ/{inputs,outputs,state,.cache}
# copies assets/inputs_template.xlsx -> inputs/DiagComm.xlsx
# drops a workspace-local .gitignore so .cache/ + outputs/ stay untracked

# fill the red-highlighted required cells in inputs/DiagComm.xlsx, then:
python ~/.cursor/skills/diagcomm-toolkit/scripts/pipeline.py status
```

### BREAKING

- **Removed**: in-skill `inputs/`, `outputs/`, `state/`, `.cache/`
  directories. The skill checkout now carries scripts + assets + docs
  + tests only. Per-project user data has moved to the workspace.
- **Changed**: `paths.base_dir` is anchored on `WORKSPACE_ROOT` (the
  per-project `.DCOM_AI/DiagComm_Toolkit_PRJ/`), not `SKILL_ROOT`. The
  default value flips from `"../../.."` (three levels up from a v1
  in-project skill clone) to `"../.."` (two levels up from the v2
  workspace, landing on the project root). The migration tool
  rewrites this automatically.
- **Changed**: every pipeline subcommand (`status` / `validate` /
  `apply` / `fscs` / `landing-report` / `reseed`) refuses to run
  when no workspace exists at `<cwd>/.DCOM_AI/DiagComm_Toolkit_PRJ/`,
  printing the `--init-project` recovery command.
- **Changed**: every pipeline subcommand also refuses when an old
  in-skill 1.20.x layout is detected (so users can't accidentally
  half-migrate). `_check_legacy_layout` now surfaces both the v1.19.x
  JSON-trio and the v1.20.x in-skill xlsx as separate, named errors
  with their respective migration commands.

### Added

- **`pipeline.py --init-project [<project-root>]`** -- single-step
  workspace bootstrap. Idempotent (skips existing files); `--force`
  overwrites the user's filled Excel with the blank template baseline
  (use only after backing up). Refuses to scaffold when the target
  workspace would land inside the skill checkout (catches the "forgot
  to cd to my project root" case).
- **`scripts/migrate_v1_20_to_v2.py`** -- one-shot migration from
  v1.20.x in-skill layout to v2 workspace layout. Validates the source
  is a real skill checkout, atomic-moves user data, rewrites
  `paths.base_dir`, prints cleanup steps; never deletes the old
  checkout itself.
- **Two-stage `preflight.py`** -- skill stage (deps + bundled assets)
  always runs; workspace stage (xlsx + base_dir) runs only when a
  workspace exists. Exit code 2 means "skill OK but workspace not yet
  initialised" (vs 1 = skill broken).
- **`runtime._check_workspace_initialized()`** -- single gate that
  every workspace-touching command goes through, with one consistent
  error message pointing at `--init-project`.
- **Workspace-local `.gitignore`** -- written by `--init-project` so
  the user's project repo doesn't accidentally commit `.cache/` or
  `outputs/`.
- **`context.py` reports both roots** -- `skill root` (where assets
  live) and `workspace root` (where user data lives), with a
  `(NOT INITIALIZED)` tag on workspace when the directory doesn't
  exist yet.

### Internals

- New module-level constants in `runtime.py` /  `excel_loader.py` /
  `context.py` / `pipeline.py` / `doors_sync.py` /
  `build_doors_payload.py` / `migrate_v1_19_to_xlsx.py`:
  `WORKSPACE_NAME`, `DCOM_AI_DIRNAME`, `WORKSPACE_ROOT`. All
  user-data paths (`INPUTS_DIR`, `OUTPUTS_DIR`, `STATE_DIR`,
  `CACHE_DIR`, `XLSX_PATH`, `VALUES_PATH`, `CONFIG_PATH`,
  `DOORS_MAPPING_PATH`) now derive from `WORKSPACE_ROOT`. Asset paths
  (`TEMPLATE_PATH`, `DOORS_SKELETON_PATH`, `SCHEMA_PATH`,
  `ASSETS_DIR`) still derive from `SKILL_ROOT`.
- `runtime._rel_to_skill` is now an alias for `_rel_to_cwd`. v2
  workspace + project-tree paths are too far from the skill clone for
  skill-relative rendering to be useful; cwd (the project root) is
  the only consistent anchor.
- `tests/conftest.py` `fixture_project` now synthesises a fake
  `<tmp>/project/.DCOM_AI/DiagComm_Toolkit_PRJ/` workspace and
  rebinds `WORKSPACE_ROOT` (+ all derived constants) per-module via
  `monkeypatch`. The fixture rewrites `paths.base_dir` to an absolute
  path so the v2 anchor change is invisible to fixture-driven tests.
- `runtime._pretty_path` -- unified pretty-printer for user-facing
  error messages: anchored on cwd first, falls back to absolute. All
  `Path.relative_to(SKILL_ROOT)` call sites in `pipeline.py` /
  `excel_loader.py` were converted; they failed loudly under fixture
  monkey-patches because workspace-tmp paths sit outside SKILL_ROOT.
- `tests/test_init_project.py` (new) -- 6 cases covering scaffold,
  idempotency, `--force` overwrite, explicit project-root argument,
  the "refuse inside skill" guard, and the `main()` short-circuit
  dispatch for both `--init-project` and `init-project`.

## [1.20.0] - 2026-05-15  -- BREAKING: Excel-driven inputs

The user-input surface is now **a single Excel workbook with
data-validation dropdowns**: `inputs/DiagComm.xlsx`. The legacy
trio (`inputs/DiagComm_values.json`, `inputs/DiagComm_config.json`,
`inputs/doors_mapping.yaml`) is gone; their equivalent is generated
on demand under `.cache/` (gitignored). This drop reduces what the
agent has to discover by ~70%: a fresh project clone now has exactly
**one** file the user opens, and that file uses Excel's native
data-validation features so even an offline reviewer (or another
LLM with no skill knowledge) can see at a glance which 9 cells are
required, what the legal enums are, and what unit each integer is in.

### Migration (one-shot)

```bash
python scripts/migrate_v1_19_to_xlsx.py
```

The tool reads any of the three legacy files that are still on disk,
populates `inputs/DiagComm.xlsx` from them, and prints the exact
`rm` commands for the legacy files (it never deletes them — the
user decides). `pipeline.py status` refuses to run with `BROKEN`
status until the legacy files are removed, with the migration
command embedded in the error.

### BREAKING

- **Removed**: `inputs/DiagComm_values.json`, `inputs/DiagComm_config.json`,
  `inputs/doors_mapping.yaml`. Replaced by `inputs/DiagComm.xlsx`.
- **Removed**: `pipeline.py reseed` default behaviour ("write a blank
  values JSON if missing"). Default is now a **no-op** that prints
  the recovery hint (`cp assets/inputs_template.xlsx inputs/DiagComm.xlsx`).
- **Changed**: `pipeline.py reseed --from-arxml` writes a *suggestion*
  file (`outputs/reseed_suggestion.json`) for the user to transcribe
  into Excel by hand — it no longer overwrites `inputs/`.
- **Changed**: every command (`status` / `validate` / `apply` / `fscs`
  / `landing-report`) now exits **2 (BROKEN)** when `inputs/DiagComm.xlsx`
  is missing, instead of lazy-seeding a JSON skeleton. Recovery hint
  printed.
- **Changed**: `pipeline.py status` exits **2 (BROKEN)** with a
  migration command when any pre-1.20.0 input file is detected.

### Added

- `inputs/DiagComm.xlsx` — git-tracked Excel workbook with 4 sheets:
  `Project & Parameters` (every spec change), `Paths & Options`
  (once per project; standard layout = zero edits), `DOORS Upload`
  (once per project), `README` (read-only cheat sheet). Required
  cells are red-highlighted via conditional formatting; enums are
  dropdowns; integers/floats have range validation; the workbook is
  programmatically generated from `assets/DiagComm_schema.json` so
  schema drift is impossible.
- `assets/inputs_template.xlsx` — blank master copy of the user
  workbook. Recovery: `cp assets/inputs_template.xlsx inputs/DiagComm.xlsx`.
- `assets/doors_mapping_skeleton.yaml` — DOORS mapping invariants
  (column bindings, value_maps, defaults, anchor). The skill bundles
  this; the user only sets 3 fields via the xlsx
  (`doors.document_uuid`, `mode`, `upload.dry_run`), which the
  loader merges with the skeleton.
- `scripts/excel_loader.py` — reads the xlsx, validates (required
  cells / enum membership / integer + float ranges / hex syntax),
  coerces types, and writes the cache atomically. Auto-called at
  the start of every pipeline / DOORS command (mtime-based, so it
  no-ops when nothing has changed). CLI: `--check` / `--show` /
  `--dump`.
- `scripts/build_inputs_template.py` — dev tool that regenerates
  `assets/inputs_template.xlsx` from `assets/DiagComm_schema.json`.
  Run after every `pipeline.py gen-schema`.
- `scripts/migrate_v1_19_to_xlsx.py` — one-shot migration from the
  1.19.x JSON+YAML inputs to `inputs/DiagComm.xlsx`. `--dry-run`
  shows the migration plan; `--force` overwrites an existing xlsx.
- `tests/test_excel_loader.py` — round-trip + validation tests for
  the loader (uses an in-memory xlsx fixture built from the live
  schema).
- `reference/excel_format.md` — sheet / column / data-validation /
  coercion / lifecycle spec.

### Changed

- `scripts/runtime.py` — new public entry `load_user_inputs()` is
  now the sole loader for every command body. It refreshes the
  cache from the xlsx, then returns the merged
  `{project, parameters, paths, options}` dict. Old
  `runtime.load_unified()` is preserved as a thin wrapper for
  backward compat. Path constants (`VALUES_PATH`, `CONFIG_PATH`,
  `DOORS_MAPPING_PATH`) now point under `.cache/`. New constants
  (`XLSX_PATH`, `TEMPLATE_PATH`, `DOORS_SKELETON_PATH`,
  `CACHE_DIR`).
- `scripts/pipeline.py` — fillness reports now reference `inputs/DiagComm.xlsx`
  + the offending sheet / row instead of a JSON path. `cmd_status` /
  `cmd_validate` / `cmd_apply` / `cmd_fscs` / `cmd_landing_report`
  surface the new error messages. `_bootstrap_unified` delegates to
  `runtime.load_user_inputs()`.
- `scripts/doors_sync.py` + `scripts/build_doors_payload.py` —
  `DEFAULT_VALUES` and `DEFAULT_MAPPING` repointed to `.cache/`;
  conditional cache refresh at the start of `main()` so default
  paths "just work".
- `scripts/preflight.py` — adds `inputs/DiagComm.xlsx` existence +
  sheet-completeness check (3 required data sheets present, openpyxl
  can parse the workbook).
- `scripts/context.py` — separate `inputs` / `cache` / `assets`
  blocks in the dashboard; refreshes the cache (best-effort) before
  reporting.
- `tests/conftest.py` — fixtures monkey-patch the new path constants
  + neutralize legacy-file detection + skip the cache refresh (so
  fixtures continue to ship pre-cooked v2 JSON instead of a real xlsx).
- `tests/test_context.py` + `tests/test_integration.py` — updated
  for the new BROKEN-when-xlsx-missing semantics and the rewritten
  `cmd_reseed` behaviour.
- `.gitignore` — adds `.cache/`, `~$*.xlsx`, `inputs/.~lock.*`,
  `inputs/~$*` (Excel lock files).
- `README.md`, `SKILL.md`, `reference/{excel_format,parameter_types,doors_mapping_format,commands,porting_checklist,landing_spots,transforms,internals,doors_excel_conventions}.md`
  — all user-facing docs rewritten around the Excel input.

### Notes

- The internal four-block shape (`project` / `parameters` / `paths` /
  `options`) is preserved; downstream call sites in `semantic.py`,
  `mapping.py`, `arxml_patcher.py`, `reports.py` are unchanged.
- Cache files (`.cache/DiagComm_values.json`,
  `.cache/DiagComm_config.json`, `.cache/doors_mapping.yaml`) are
  byte-identical in shape to the legacy `inputs/*` files, so any
  ad-hoc tooling that consumed the old JSON / YAML will continue to
  work if pointed at the new location.
- DOORS placeholder string `PUT-DOORS-DOCUMENT-UUID-HERE` is
  preserved verbatim through the loader (intentionally not stripped
  to `None`) so `build_doors_payload`'s `"PUT-" in module_uuid`
  guard still trips.

## [1.19.4] - 2026-05-15

### Fixed (data-leak in baseline)

- `inputs/doors_mapping.yaml::doors.document_uuid` was committed with
  a real production DOORS module UUID ever since DOORS Step 8
  shipped in 1.17. New users cloning the skill would inherit that
  pointer and, if they ran `doors_sync` without first editing the
  mapping, push their data into a stranger's DOORS module. The field
  is now reset to the documented placeholder
  `PUT-DOORS-DOCUMENT-UUID-HERE`, which `doors_sync` /
  `build_doors_payload` already gate on (`"PUT-" in module_uuid` →
  hard stop with "doors_mapping.yaml still has the placeholder UUID").

### Changed (doc / example sanitization)

Stripped the source-project name and that same real UUID
out of every place a *new* user reads as a current example, while
leaving them in the historical narrative (CHANGELOG entries,
"this-bit-us-in-1.7.1"-style code comments) for traceability:

- `README.md`: the `inputs/DiagComm_values.json` schema example now
  uses `"name": "MyProject"`; the `inputs/doors_mapping.yaml`
  example now shows `document_uuid: "PUT-DOORS-DOCUMENT-UUID-HERE"`.
- `SKILL.md`: the Step 8 decision-banner example and the user-facing
  bullet template both use `MyProject` + a synthetic
  `1-aaaaaaaaaaaaaaaa-M-bbbbbbbbbbbbb` UUID.
- `state/README.md`: the v3 state-file layout example uses
  `MyProject` and the same synthetic UUID.
- `scripts/doors_state.py` module docstring: same.
- `scripts/build_doors_payload.py` row-union docstring: uses
  `MyProject` (was the real source project name).
- `scripts/pipeline.py` fillness-report hint: now
  `项目名（自由文本，例如 'MyProject'）` (was the real source project name).

### Notes

- No code paths changed -- this is a content-only release. The git
  history retains the leaked UUID for reference; rotating the actual
  DOORS module UUID is out of scope for the skill (DOORS-side
  concern).
- Users who *want* to push to that real UUID can still do so by
  pasting it back into their local
  `inputs/doors_mapping.yaml`; the file is in `inputs/` precisely
  because it is per-project user input and the skill ships only the
  blank template.

## [1.19.3] - 2026-05-15

### Fixed

- `python scripts/doors_sync.py --user-nt <NT> --password <PWD>
  --save-credentials --no-upload` (the cache-priming recipe the agent
  generates on a brand-new machine) used to silent-exit after the
  Step 8 decision banner. Root cause: build_doors_payload tried to
  read FSCS / diff / DOORS export which a brand-new checkout does not
  have, then `_bail` only wrote the error to
  `outputs/doors_payload_report.txt` (no stderr), and doors_sync
  propagated `rc=2` without a message. From the user's terminal it
  looked like the command did nothing -- the password did NOT get
  cached, and subsequent uploads had to interactively prompt /
  silently fail.

### Changed

- `doors_sync.py`: `--save-credentials --no-upload` is now a
  self-contained admin op (sibling of `--forget-credentials`).
  Short-circuited right after `keyring_mod` is initialised, before
  any pipeline IO. Requires `--user-nt` + `--password` (or the
  matching env vars). Writes to the OS keychain and exits cleanly
  with `[doors_sync] credential cache primed; ...`. No FSCS / diff /
  export needed -- this is now the canonical first-run setup
  command.
- `build_doors_payload._bail()`: every bail message is now mirrored
  to stderr (prefixed `[build_doors_payload] `) in addition to the
  on-disk report. Previously only the report file got the message,
  so any caller (doors_sync, ad-hoc shell use, future automations)
  that didn't open the report saw silent rc=2.
- `doors_sync.py`: when `build_doors_payload.build_payload` returns
  `rc=2`, we now also print
  `[doors_sync] build_doors_payload failed (rc=2). Details written
  to: <report path>` so users know where the explanation lives.

### Tests

- 121/121 pytest still passing.
- Manual: `--save-credentials --no-upload` with a throwaway user
  (`__test_cold_start__`) saved + verified + forgot the entry; no
  pipeline IO touched.

## [1.19.2] - 2026-05-15

### Changed

- Default `dcm_services_common` arxml path bumped from
  `Dcm_CusDiag_Services_EcucValues.arxml` to
  `Dcm_CusDiag_Services_EcucValues_SingleCANID.arxml`. The
  `_SingleCANID` variant is the standard Bosch CusDiag drop for
  single-CAN-ID projects and is the canonical landing spot for P2 /
  P2* timer writes. Updated everywhere the path is hard-coded:
  - `inputs/DiagComm_config.json` (bundled blank template)
  - `scripts/runtime.py::DEFAULT_PATHS` (was already on the new name;
    docs / examples now agree)
  - `scripts/context.py` (status table)
  - `scripts/schema.py` parameter descriptions for `P2_Max` /
    `P2_Star_Max`; regenerated `assets/DiagComm_schema.json`.
  - `scripts/mapping.yaml` and `scripts/mapping.py` header comments
  - `reference/landing_spots.md` (alias table)
  - `tests/fixtures/minimal/config.json` and the renamed fixture
    arxml under
    `tests/fixtures/minimal/dcom/RBAPLCust/cfg/Common/`
  - `tests/test_integration.py` landing-report assertion

### Tests

- 121/121 pytest still passing after the rename + schema regeneration.

## [1.19.1] - 2026-05-11

**Blank template now lists every parameter, not just the
prompt-required ones.** 1.19.0 only listed the 9 fields the user
absolutely had to set, leaving the other 12 (timer / flag fields)
hidden behind "schema defaults". For real projects the schema
defaults are often wrong (e.g. real projects often need `N_As=70` not 25,
`PaddingByte=0xAA` not `0x00`, `StrictDlcCheck=true`...), and a
silent "use default" makes those parameters easy to miss during spec
review.

### Changed

- `inputs/DiagComm_values.json` now lists all 21 parameters:
  - `prompt_required` fields stay `null` / `<fill-me>` (fillness
    check still hard-refuses).
  - Other 17 fields are pre-filled with their schema default value
    as a visible placeholder. Non-blocking, but the `_README` and
    the fillness report's tail message both flag them as
    "review-against-spec-before-apply".
- `_build_blank_parameters_template()` rewritten to derive the
  template shape from `assets/DiagComm_schema.json` (recursive walk).
  When `gen-schema` adds a new parameter it shows up automatically in
  the next `reseed` / lazy-bootstrap output, no hand edit needed.
- `_print_fillness_report()` tail message updated: was
  "non-required fields auto-fill from schema default"; now reads
  "已先填好 schema 默认值占位... apply 前请对照项目 spec 逐项 review".

### Why

User feedback: "新模板里少了很多原来应该有的字段". On a project
where the spec timer / padding values diverge from DiagComm.txt
defaults, hiding those fields behind an implicit "default" rule
risks shipping wrong values. Listing them explicitly forces a review
step but keeps the fast happy path (filling defaults works for any
project that already matches DiagComm.txt).

### Tests

- 121/121 still passing. No assertion changes needed because the
  fillness check covers exactly the same set of fields.

## [1.19.0] - 2026-05-11

**Skill startup is now near-instant: the first run no longer
reverse-walks 4-6 ARXML files to seed the user input. Instead the
two `inputs/` files ship as committed BLANK TEMPLATES with explicit
placeholders for the 9 prompt-required fields.**

### Added

- `pipeline.py::_check_template_fillness()` — surfaces every still
  unfilled prompt-required field (`<fill-me>` / `null` / empty) with
  a precise hint (type, allowed values, unit). Wired into the entry
  of `cmd_validate`, `cmd_apply`, `cmd_fscs` (hard refuse with rc=2),
  and `cmd_status` (soft `NEEDS-FILL` row).
- `runtime.strip_doc_keys()` — drops `_README` style underscore-prefix
  keys from loaded JSON so the bundled templates can carry inline
  Chinese instructions without contaminating the structured loader.
- `pipeline.py reseed --from-arxml` — opt-in flag that restores the
  legacy "reverse-walk live arxml and pre-fill every parameter"
  behaviour for power users who want a snapshot of the current
  project state.
- `context.py` now lists every unfilled required field in a dedicated
  section, and updates `next_step` to point the agent at the right
  fill action.

### Changed

- `inputs/DiagComm_values.json` and `inputs/DiagComm_config.json` are
  now COMMITTED BLANK TEMPLATES. The .gitignore entries are gone.
  Each project's filled-in copy lives only in its own working tree;
  pulls of the upstream skill never overwrite project data because
  the tracked baseline is the placeholder template.
- `_bootstrap_unified()` (lazy-seed path triggered when the file is
  missing) now writes the bundled blank template — no ARXML reverse
  walk, no schema lookups beyond what's needed to print the next-step
  banner. Time on a fresh project drops from "scan whole arxml tree"
  to "two writes".
- `pipeline.py reseed` (without `--from-arxml`) writes the blank
  template too. The original arxml-reverse-walk behaviour now lives
  behind `--from-arxml`.
- Project-identity placeholders unified to a single `<fill-me>`
  string (was `<set-me-on-first-launch>`).

### Tests

- `test_status_seeds_values_when_missing`,
  `test_validate_seeds_and_returns_1_on_fresh_project`,
  `test_apply_seeds_and_returns_1_on_fresh_project` updated for the
  new blank-template bootstrap (asserts `<fill-me>` placeholders +
  `NEEDS-FILL` status row).
- `test_context_lists_unfilled_required_fields` (new) covers the
  schema-walking fillness logic in `context.py`, including
  `_README` strip, nested object recursion, and "non-required is
  not flagged" semantics.
- All 121 tests passing.

## [1.18.0] - 2026-05-09

**Two-pronged orientation overhaul so that weaker LLM clients stop
wasting tokens on filesystem discovery: (1) a script-driven Step 0
orientation; (2) a hard split between user-edited files and
skill-bundled assets.**

### Added

- `scripts/context.py` — a stdlib-only, read-only Step 0 orientation
  script. It prints the skill root, inferred `base_dir`, matching
  `dcom_root` directories, status of every user-edited input AND every
  skill-bundled asset, current `project.name` / `product_type` /
  `CAN_Channel`, resolved target ARXML files, and the next exact
  command to run. `--json` emits the same data for scripted consumers.
- `tests/test_context.py` — regression coverage for path inference,
  user-input seeding hints, and broken-install detection (missing
  `assets/`).
- `assets/` folder — skill-bundled, read-only artefacts that travel
  with the skill via git: `assets/DiagComm.txt` (parameter catalog),
  `assets/DiagComm_schema.json` (regenerated via `pipeline.py
  gen-schema`), and `assets/doors_template.xlsx` (bundled DOORS Excel
  template). Adopts the standard Anthropic skill anatomy
  (`scripts/` + `references/` + `assets/`).

### Changed

- `inputs/` is now reserved exclusively for user-edited files:
  `DiagComm_values.json`, `DiagComm_config.json`, `doors_mapping.yaml`.
  Anything the user never edits has moved to `assets/`. The agent
  still never writes existing files in `inputs/`; the new `assets/`
  is read-only at runtime.
- `SKILL.md` now makes `python scripts/context.py` the mandatory first
  workflow step and explicitly tells agents not to scan the repository
  when context output already explains the missing path or input. The
  file map and ownership table reflect the `inputs/` vs `assets/`
  split.
- `README.md` documents `context.py` in quick start, the new repo
  layout (with `assets/`), and updates the troubleshooting table.
- `scripts/preflight.py` now treats `scripts/context.py` and every
  `assets/*` file as required so incomplete installs fail early.
- `scripts/runtime.py`, `scripts/schema.py`,
  `scripts/build_doors_payload.py`, `scripts/pipeline.py`, and
  `scripts/context.py` all read schema/catalog/template from `assets/`
  instead of `inputs/`.
- `inputs/doors_mapping.yaml::template.path` default points to
  `assets/doors_template.xlsx`.
- `tests/conftest.py` provisions the temp project with the new
  `inputs/` + `assets/` layout and re-wires `ASSETS_DIR` alongside
  `INPUTS_DIR`.

### Migration

- After upgrading to 1.18.0, `git pull` will move
  `inputs/DiagComm.txt`, `inputs/DiagComm_schema.json`, and
  `inputs/doors_template.xlsx` into `assets/`. No user action is
  required as long as `inputs/DiagComm_values.json` /
  `inputs/DiagComm_config.json` / `inputs/doors_mapping.yaml` are
  still in place.

### Removed

- `inputs/test_upload.xlsx` is no longer shipped or referenced — the
  bundled `assets/doors_template.xlsx` is the single source of truth
  for the DOORS sheet layout.

## [1.17.0] - 2026-05-07

**Step 8 credentials: OS keychain fallback + auto-refresh on auth
failure. No more `$env:DOORS_PWD` everywhere, no more password in chat
history, no more retyping after every reboot.**

User-facing motivation, verbatim:

> 关于 step 8 需要输用户名密码的问题，有没有什么好的解决方案，可以
> 不用明文保存密码且不用每次都输入

The new flow: cache the password once with `--save-credentials`,
then never type / env-var it again. The cipher-text lives in the OS
keychain (Windows Credential Manager via DPAPI / macOS Keychain /
Linux Secret Service), user-bound and machine-bound. The skill never
writes the password under `inputs/` / `outputs/` / `state/`, never
echoes it back into chat, and never requires the user to set up an
env var in `$PROFILE` (which would be plain-text on disk).

### Added

- `scripts/doors_sync.py` — 4-level password resolution chain:

      1. `--password <pwd>`           (CLI explicit; one-off / debug)
      2. `$DOORS_PWD`                 (CI / scripted runs)
      3. OS keychain                  (default for interactive use)
      4. interactive `getpass` prompt (TTY only)

  The first non-empty source wins; sources below it are not consulted.
  CI / non-TTY shells stop at source 2 and never block on a prompt.

- New CLI flags on `scripts/doors_sync.py`:

  - `--save-credentials` — after a successful resolution, persist
    `(user_nt, password)` in the OS keychain under service
    `diagcomm-toolkit:doors`. Re-running with this flag and a different
    password OVERWRITES the existing entry — this is how a user
    refreshes the cache after a DOORS-side password change. Honoured
    even on `--no-upload` runs so users can cache without doing a real
    upload.
  - `--forget-credentials` — delete the keychain entry for `--user-nt`
    and exit. No build, no upload. Idempotent: a missing entry is a
    benign exit 0 (we probe with `get_password` first to avoid relying
    on per-backend `delete_password` error messages, which differ
    wildly between Windows / macOS / Linux Secret Service).
  - `--no-keyring` — bypass the OS keychain entirely (do not read,
    do not write). Useful for CI, debugging, or hosts without a
    Secret Service backend.

- `scripts/doors_sync.py::_upload_with_pwd_refresh` — auth-failure
  auto-refresh:

  - When the upload subprocess fails AND `_looks_like_auth_failure`
    matches (`401`, `unauthorized`, `invalid credentials`,
    `authentication failed`, `bad/wrong password`, plus the DWA
    Chinese variants `密码错误` / `用户名或密码错误` / `认证失败`)
    AND the password came from a cache (env var or keychain), the
    script prompts ONCE for a new password via `getpass` and retries
    the upload.
  - On retry success the new password silently overwrites the
    keychain entry; the next run goes back to zero-prompt. On retry
    failure the keychain is NOT modified, so a wrong typed password
    can never replace the previously cached one.
  - **Hard cap: 1 retry per run.** Most enterprise DOORS deployments
    delegate auth to LDAP / AD which lock the NT account after 3-5
    failed attempts; we deliberately spend at most 2 attempts per
    invocation (the cached one + the typed one). Users / agents must
    NOT loop the script after a double auth failure — the next run
    risks tripping the lockout counter.
  - Auto-refresh is suppressed when `pwd_source == "cli"` (user
    passed `--password` explicitly; respect that), `pwd_source ==
    "prompt"` (the password just typed was already wrong), or stdin
    is not a TTY (CI mode).

- `scripts/requirements.txt` — added `keyring>=24` (optional;
  `doors_sync.py` degrades cleanly to env var / CLI / prompt if
  `keyring` is not importable).

### Changed

- `scripts/doors_sync.py::_run_upload` — return signature widened to
  `(rc, abs_n, captured)` where `captured = stdout + "\n" + stderr`.
  The captured text is what `_looks_like_auth_failure` greps for the
  auth-fail tokens; existing callers that only used the first two
  elements are unaffected.

- `scripts/doors_sync.py` — `--user-nt` is now resolved independently
  from `--password` (was previously gated on both being present at
  once). On `--no-upload` the script still honours `--save-credentials`
  if both NT and password are available, so users can pre-cache
  credentials before any real upload.

- `scripts/doors_sync.py` — `--user-nt` help text now mentions
  `$DOORS_USER_NT` as an env-var fallback (already worked, was just
  undocumented).

### Documentation

- `SKILL.md`:
  - User input contract: rewrote the credentials paragraph from a
    single-line `--user-nt <NT> --password $env:DOORS_PWD` recipe
    into a description of the 4-level fallback chain + a forward
    pointer to the new Step 8b credentials section.
  - Step 8 (entry point): replaced the default command with a
    one-time `--save-credentials` + zero-prompt-thereafter pair.
  - **New**: Step 8b — credentials (keyring fallback) section. Lays
    out the 4-source resolution table, the management commands
    table, the auto-refresh behaviour, and a prominent NT lock-out
    warning (LDAP / AD typically locks after 3-5 attempts; the
    script caps at 2 per run — agents must stop after a double
    auth failure rather than loop).
  - Hard rule 9: extended to forbid two new misuses — (1) asking the
    user to paste their DOORS password into the chat, (2) running
    `--save-credentials` on the agent's behalf with a password the
    user already typed in the conversation (would leak the secret
    into chat history). The user must run the cache command
    themselves in their own terminal.
  - Step 8 troubleshooting: replaced the obsolete `auth → wrong NT
    password` row with five new rows covering the keychain reject /
    auto-retry success / auto-retry failure / no-password / keyring-
    backend-broken cases. Each row tells the agent exactly what to
    say to the user (and crucially, what NOT to do — paste the
    password, loop the script).
  - Security callout updated: the supported persistence is now the
    OS keychain explicitly (instead of "always re-prompt").

- `README.md`:
  - Badge bumped to 1.17.0.
  - TL;DR contract: the credentials bullet now describes the 4-level
    fallback + first-time `--save-credentials` workflow.
  - Quick start step 4: replaced the `$env:DOORS_PWD` recipe with a
    two-command sequence (cache once with `--save-credentials
    --no-upload`, then bare `--user-nt <NT>` thereafter), plus a
    "password rotated?" recipe pair (active refresh vs. passive
    auto-prompt) and the `--no-keyring` / `--forget-credentials`
    escape hatches.
  - Recipes table: added 4 rows covering first-time cache, password
    rotation, forget, and CI bypass.
  - Troubleshooting table: added 4 rows mirroring the new SKILL.md
    Step 8b error messages, including the NT lock-out warning.

### Compatibility

- Existing callers that pass `--password` (CLI flag) or `$DOORS_PWD`
  (env var) keep working unchanged. The keychain is consulted only
  when both are empty.
- `keyring` is a soft dependency: if it can't be imported (e.g. the
  user hasn't `pip install -r scripts/requirements.txt`-ed since the
  bump), `_try_import_keyring` returns `None` and the script falls
  back to env var / prompt with no functional regression. Trying to
  `--save-credentials` without `keyring` emits a single WARN and
  proceeds with the upload anyway.
- State schema unchanged (still v3). No migrations needed.
- No changes to `build_doors_payload.py` / `doors_upload.py` —
  the credential plumbing is entirely inside `doors_sync.py`.

### Verified (smoke)

- `python scripts/doors_sync.py --help` — all three new flags
  (`--save-credentials`, `--forget-credentials`, `--no-keyring`)
  surface with intelligible help text.
- `--forget-credentials` without `--user-nt` exits 2 with a clear
  error.
- `--forget-credentials --user-nt <unknown>` exits 0 (idempotent;
  validated against Windows Credential Manager).
- Keyring round-trip (write → read → overwrite → delete →
  delete-again-idempotent) all PASS on Windows DPAPI backend.
- `_looks_like_auth_failure` regex matches all five canonical
  English DOORS auth-error strings (`401 Unauthorized`, `Invalid
  credentials`, `Authentication failed`, `bad nt password`, `Login
  failed: wrong password`) and rejects six common non-auth errors
  (HTTP 500, connection refused, module locked, missing template,
  missing anchor, empty string).

## [1.16.1] - 2026-05-07

**FSCS / Object Text header: project and product on independent lines,
DOORS Object Text accumulates both as ` / `-joined unions.**

Reviewer follow-up to 1.16.0. The user request, verbatim:

> 再微调一下：项目名称和产品类型分两行，如果后续更改 pp 而没改 parameter
> 就在后面加，用 / 隔开就行了

The header now always has *four* lines (toolkit tag / project / product /
timestamp) instead of folding project + product into one line. Splitting
those two facts onto their own lines makes them independently
extensible: when a DOORS row picks up a second product without
parameter changes (`pp_only_changed`), only the product line widens
(`# ESP / IPB`) — no flow-around-a-combined-string gymnastics needed.

Only the DOORS Object Text cell carries the union view; `FSCS.txt`
itself remains a single-project / single-product snapshot of the
current apply (it's an artefact of the *current* run, not the row's
history).

### Changed

- `scripts/reports.py::_render_fscs`
  - Header is now four lines:
    `# DiagComm FSCS`, `# <project>`, `# <product>`,
    `# <timestamp>[  [<mode>]]`. The `[<mode>]` tag still rides on
    the timestamp line and is suppressed for `SNAPSHOT`.
  - Body / parameter grid layout is unchanged from 1.16.0.
- `scripts/build_doors_payload.py` — new `_rewrite_object_text_header`
  - Rewrites the four-line `#` header of the FSCS text passed to the
    Object Text composer so the project and product lines reflect the
    accumulated `state.covered_projects` / `state.covered_products`
    unions (joined with ` / ` in insertion order).
  - Falls back gracefully (returns the input unchanged) when fed an
    older header shape — e.g. a 1.16.0 three-line snapshot or a
    1.15.0 one-liner — so cells continue to render *something* during
    a partial upgrade rather than a malformed header.
- `scripts/build_doors_payload.py::build_payload`
  - Calls `_rewrite_object_text_header(full_fscs_text,
    final_projects, final_products)` and feeds the result into
    `_build_object_text_for_kind` as `full_fscs`. For `first_insert`
    and `params_and_pp_changed` the unions collapse to the single
    current value, so the rewrite is a no-op; for the REPLACE kinds
    (`pp_only_changed`, `fscs_only_changed`) the cell now reflects
    every (project, product) the row has ever covered, not just the
    most recent run.
  - `extras.fscs_full_text` and `extras.fscs_hybrid_text` continue to
    bind to the **original** (pre-rewrite) FSCS text — only `Object
    Text` (via `row.object_text`) sees the union view.

### Compatibility

- `parse_fscs` accepts the new four-line header transparently (it
  already skipped any line starting with `#`); all 23 fields still
  round-trip with the same values.
- `state.modules[<uuid>].last_object_text` written under 1.16.0 (with
  a three-line header) keeps round-tripping through `_join_with_blank_line`
  — the next REPLACE-class run rewrites it to the new four-line
  header anyway, and the next APPEND-class (`params_changed`) run
  preserves the old header on top of the new delta block.
- `RB_Product` / `RB_Realizing_SWitem` cells are unchanged: still
  newline-joined unions of `state.covered_*`.

### Fixed (regressions surfaced by the first 1.16.1 `pp_only_changed` upload)

- `scripts/doors_sync.py::_rebuild_state_inputs`
  - Now mirrors `build_doors_payload.build_payload` and applies
    `_rewrite_object_text_header(...)` before calling
    `_build_object_text_for_kind`. Previously the rewrite only ran on
    the path that produced the xlsx; the path that produced
    `state.last_object_text` reused the raw single-project /
    single-product FSCS, so state silently diverged from what was
    actually uploaded. The next `params_changed` run would then
    APPEND its delta block on top of stale (un-unioned) header text,
    erasing accumulated coverage information from the cell history.
  - Implementation: read `covered_projects` / `covered_products` out
    of the state entry, union them with the current run's
    (project, product), and feed the rewritten FSCS text in.
- `scripts/doors_sync.py` final state-update banner
  - The `last_success_abs=...` line used to print `success_abs` (the
    opaque upload-server counter) verbatim, which made update runs
    look as though `1598` had just been overwritten with e.g. `628`.
    Now it reads the persisted value back out of state after
    `record_update` / `record_insert` and prints **that**, with an
    inline note showing the upload counter when it differs from the
    persisted abs in update mode. Behaviour-only, no on-disk schema
    change.

---

## [1.16.0] - 2026-05-07

**FSCS / Object Text layout polish: three-line header + grid-aligned
parameter table.**

Reviewer feedback on the v7 Object Text cell asked for two visual
adjustments. The user request, verbatim:

> 导 doors 这一步中，需要调整一下 object_text 的格式，项目名称/产品类型
> /时间可以分三行 ... 下面 parameters 的内容也不够对齐，需要调整一下

Both `outputs/FSCS.txt` and the DOORS Object Text cell now render as:

```
# DiagComm FSCS
# MyProject / ESP
# 2026-05-07 11:23:19

CAN_Channel               :       0
CAN_ID_Format             :   11bit
Addressing_Method         :  Normal
...
N_Bs                      :  150 ms
P2_Star_Max               : 5000 ms
PaddingByte               :    0xAA
StrictDlcCheck            :    true
NRC78_Times               :      10
```

### Changed

- `scripts/reports.py::_render_fscs`
  - Header split from a single line
    `# DiagComm FSCS  -  <project> / <product>  -  <timestamp>` into
    three independent `#` lines (project header, project / product,
    timestamp). Each datum now sits on its own row, which scans more
    cleanly both in `FSCS.txt` and in the DOORS Object Text cell.
    The optional `[<mode>]` tag continues to ride on the timestamp
    line and is still suppressed for `SNAPSHOT`.
  - Parameter block is now sized to the actual run: label column is
    left-aligned to the longest leaf name, value column is
    right-aligned to the longest rendered value. Result: same-unit
    values stack at the suffix (`70 ms` / `150 ms` / `5000 ms` flush
    at `ms`), hex IDs stack at the low-order digit, and there are no
    pointless trailing spaces around shorter labels. Separator went
    from `: ` to ` : ` to match the new tighter widths.
- `scripts/reports.py::_fscs_line`
  - Now accepts optional `label_width` / `value_width` keyword args
    so callers can pass run-specific widths. The legacy
    `value_width=0` path keeps the old left-aligned-value behaviour
    for any downstream caller that only knows the label width.
  - `FSCS_LABEL_WIDTH` is now a *fallback* default (26 — exactly fits
    `CAN_Functional_Request_ID` plus one space), used only when the
    body is empty. Live FSCS rendering always derives the width from
    the data.
- `scripts/build_doors_payload.py::_build_delta_text`
  - Header banner is now two lines (`# Update <ts>` then
    `# parameters changed  (<project> / <product>)`) so the cell's
    update markers and FSCS body share the same one-fact-per-line
    rhythm.
  - Label column inside the delta block is sized to the params that
    actually changed in this run; falls back to 26 (the new
    `_DELTA_LABEL_FALLBACK`) when no params are parsable. Separator
    matches FSCS body (` : `).

### Compatibility

- `parse_fscs` (in `build_doors_payload.py`) was already tolerant of
  arbitrary whitespace around the `:` separator, so no regex changes
  were needed. Re-parsing an existing v7-format `FSCS.txt` produced
  by 1.15.0 still works; re-parsing a 1.16.0-format file produces
  the same 23 fields with the same values.
- The DOORS Object Text composition rules (v7) are unchanged — only
  the rendered text is denser. Existing rows in DOORS that were
  populated under 1.15.0 will see the new layout the next time
  `change_kind ∈ {first_insert, params_and_pp_changed, pp_only_changed,
  fscs_only_changed}` runs (REPLACE), or when a `params_changed` run
  appends the new-style delta block on top of the previous cell.
- `state.modules[<uuid>].last_object_text` continues to round-trip
  byte-for-byte through `doors_state.record_*`; the next
  `params_changed` run will append the new-style delta block on top
  of the previously stored cell text.

---

## [1.15.0] - 2026-05-06

**Object Text trim: replace-on-unchanged + delta-only on params change.**

Reviewers complained the `Object Text` cell in DOORS was redundant and
poorly aligned: every update appended a fresh banner block plus the
*entire* FSCS body again, even when only the FSCS rendering changed
or only the (project, product) mapping was extended. Two consecutive
runs typically doubled the cell length while the actual semantic
delta was a single line.

The user request, verbatim:

> Object Text 中文本的内容太过冗余，且不够对齐，精简内容，parameters
> 没变的话不用新起追加内容，直接在原本的内容中改

Implemented as the v7 Object Text composition rules.

### Object Text rules (v7)

| `change_kind`                         | Operation | Cell content after run                                       |
| ------------------------------------- | --------- | ------------------------------------------------------------ |
| `first_insert`, `params_and_pp_changed` | seed      | current FSCS verbatim                                        |
| `params_changed`                      | APPEND    | prev cell + thin separator + delta-only block (no FSCS replay) |
| `pp_only_changed`                     | REPLACE   | current FSCS verbatim                                        |
| `fscs_only_changed`                   | REPLACE   | current FSCS verbatim                                        |
| `no_change` (`--force-no-skip`)       | APPEND    | prev cell + single-line marker                               |

`RB_Product` / `RB_Realizing_SWitem` are **unchanged**: they remain
growing unions across runs, so multi-mapping coverage is still
discoverable from the row even when Object Text gets replaced.

### Changed

- `scripts/reports.py::_render_fscs`
  - Header collapsed from four lines (`# FSCS -- ...`, `# project`,
    `# generated`, `# mode`) to one:
    `# DiagComm FSCS  -  <project> / <product>  -  <timestamp>`. The
    `[<mode>]` tag is appended only when mode != `SNAPSHOT`, so DOORS
    uploads stay clean.
  - `product_type` is no longer rendered as a body line — it lives
    in the header (and `RB_Product` already carries it on the DOORS
    side).
- `scripts/build_doors_payload.py::_build_delta_text`
  - Heavy `===` 62-char banners replaced by a thin `---` rule of the
    same width, so the appended block reads as a continuation of the
    FSCS rather than a brand-new section.
  - Per-arxml `Changed files:` and `Changed parameters:` sub-headings
    removed; the param-by-param `<param>: <old> -> <new>` lines are
    now aligned to `FSCS_LABEL_WIDTH` (28) so they stack visually
    with the FSCS body sitting above them in the same cell.
- `scripts/build_doors_payload.py::_build_object_text_for_kind`
  - `pp_only_changed` / `fscs_only_changed` → REPLACE (return
    current FSCS, ignore `prev_object_text`).
  - `params_changed` → APPEND `delta_block` only, no full-FSCS
    replay (`_build_params_changed_block` removed).
  - `no_change` marker is now a single line: `# Update <ts>  -
    re-uploaded (no semantic change)`.
- `scripts/build_doors_payload.py::build_payload`
  - Report now prints `Object Text op : REPLACE | APPEND` next to
    the lengths so it's obvious what just happened to the cell.
- Module docstring rewritten to document the v7 rules; v6's "always
  append" model is called out as superseded.

### Removed

- `_BANNER`, `_build_pp_only_block`, `_build_fscs_only_block`, and
  `_build_params_changed_block` from
  `scripts/build_doors_payload.py`. They were the v6 append-block
  templates and have no callers under the v7 rules.

### Migration / behavioural notes

- Existing rows in DOORS that already have the v6-style cumulative
  Object Text (FSCS + multiple `[Update]` banners + repeated FSCS
  blocks) will start shrinking on the **next** update:
  - A `params_changed` run appends one thin delta block on top of
    whatever prev_object_text holds, leaving the historical banners
    in place but not adding new ones.
  - A `pp_only_changed` or `fscs_only_changed` run replaces the
    entire cell with the current FSCS, dropping all v6 history.
- If you want to preserve the v6 history before the first replace,
  read `state/doors_upload_state.json::modules[<uuid>].history`
  (this skill's own history log, never overwritten).
- The state field `last_object_text` continues to mean "what's
  authoritative in the cell after this run". On REPLACE runs that
  equals the current FSCS; on APPEND runs it equals the new full
  cell text.

## [1.14.0] - 2026-05-06

**Bug fix: post-insert AbsoluteNumber reconciliation.**

`upload_doors_module`'s response payload (`Data: SUCCESS:<n>`) was
being trusted as the AbsoluteNumber DOORS allocates to a freshly
inserted row, and persisted that way into
`state.modules[<uuid>].last_success_abs`. Empirical verification
(diffing pre- and post-upload module exports against the actual row
in DOORS) showed the counter is **opaque**: in three consecutive
inserts/updates we observed 614 → 615 → 616, while the actual
AbsoluteNumber DOORS allocated to the new row was 1598. The next
update therefore always failed with
`FAILURE:<m>:Cannot find required Object with Absolute Number <n>`.

### Added

- `scripts/doors_fetch.py`
  - One-shot `get_doors_module` (and optional `refresh_doors_module`)
    over plain HTTP/SSE with explicit timeouts, mirroring the same
    transport `doors_upload.py` already uses. CLI entry point persists
    the result to `outputs/doors_export_fresh.json` (or `--out`).
  - New importable `fetch_module(...)` function shared with
    `doors_sync.py` so the session/timeout machinery lives in one
    place.
- `scripts/doors_sync.py`
  - `_reconcile_abs_after_insert(...)` — fetches the module fresh
    after a successful insert, diffs the AbsoluteNumber set against
    `outputs/doors_export.json` (the snapshot used for the anchor
    lookup), and returns the single new AbsoluteNumber. Falls back
    to a content-prefix match when concurrent edits introduce
    multiple new rows; bounded retry loop when cache lag returns
    zero new rows.
  - On successful reconcile, the freshly fetched module also
    overwrites `outputs/doors_export.json` so the next run's anchor
    lookup and decision logic see a current snapshot.
  - New CLI flags: `--no-reconcile`, `--reconcile-attempts N`,
    `--reconcile-sleep N`, `--reconcile-fetch-timeout N`,
    `--reconcile-refresh-timeout N`.

### Changed

- `scripts/doors_sync.py::main()`
  - Insert path now goes through `_reconcile_abs_after_insert(...)`
    before `record_insert(...)`. The opaque upload counter is
    replaced by the real AbsoluteNumber whenever reconcile succeeds.
  - On reconcile failure (persistent cache lag, fetch error,
    multi-new ambiguity), the run still completes but emits a loud
    WARN that names the exact manual recovery steps:
    `doors_fetch.py --refresh`, then patch
    `state.modules[<uuid>].last_success_abs` and the matching
    history entry's `abs_n`.
  - Update path is unchanged: `record_update(...)` already preserves
    the existing `last_success_abs` (it never trusts the upload
    counter), so the bug never affected updates.
- Module-level docstring of `doors_sync.py` rewritten to document
  the reconcile step explicitly between the upload and the state
  write.

### Behavioural notes

- The upstream DOORS server's `refresh_doors_module` has a server-
  side read timeout of ~60 s connecting to the live DOORS instance.
  When that times out, the cached read is still served and reconcile
  proceeds with whatever the cache has; the retry loop covers the
  short window between insert and replication.
- `prev_export` for diff is `outputs/doors_export.json`. If the
  export is missing on first-ever run, reconcile falls back to pure
  content-prefix matching against the entire fresh export.
- `--no-reconcile` exists for tests / debug only; using it in
  production guarantees the next update fails until you patch state.

## [1.13.0] - 2026-05-06

**Breaking input schema change.** Splits user input into two files
that mirror the conceptual model introduced in 1.12.0 (parameters
unique per upload, project / product the variable axis), AND
separates the rarely-touched plumbing (paths / options) from the
spec-change knobs (project / parameters) on disk.

### v2 schema (split into two files)

`inputs/DiagComm_values.json` — edited every spec change:

```json
{
  "$schema": "diagcomm-toolkit/v2",
  "project":    { "name": "<project>", "product_type": "DPB|ESP|IPB|RBU" },
  "parameters": { "CAN_Channel": 0, "CAN_ID_Format": "11bit", "...": "..." }
}
```

`inputs/DiagComm_config.json` — set once per project, rarely touched:

```json
{
  "$schema": "diagcomm-toolkit/v2",
  "paths":   { "base_dir": "...", "dcom_root": "...", "...": "..." },
  "options": { "dry_run_default": true, "validate_before_apply": true }
}
```

The runtime merges both files into one in-memory dict so every
existing call site (`split_unified` and friends) still sees the
four-block shape (`project` / `paths` / `options` / `parameters`).

What moved:

| 1.12.0 (v1) | 1.13.0 (v2) | File | Why |
|---|---|---|---|
| `project_name` (top-level) | `project.name` | values | Co-locate with `product_type`; both are project identity. |
| `values.product_type` | `project.product_type` | values | `product_type` is identity, not a parameter. The fingerprint no longer needs to special-case it. |
| `values.<rest>` | `parameters.<rest>` | values | Naming follows the mental model: this block is "the unique parameter set". |
| `values.CAN_Channel` | `parameters.CAN_Channel` | values | `CAN_Channel` is a real parameter — emphasised by the rename. |
| `paths` (top-level)   | `paths` (top-level) | **config** | Moved out of the values file so the things you edit every spec change aren't crowded by templates you set once. |
| `options` (top-level) | `options` (top-level) | **config** | Same reason as `paths`. |

### Changed

- `scripts/runtime.py`
  - `split_unified()` now reads v2 (`project.{name,product_type}`,
    `parameters`). `_migrate_v1_to_v2_in_memory()` is a defensive
    in-memory fallback so legacy fixtures keep working in tests; the
    primary failure path is the loud `_check_legacy_layout()` error
    pointing the user at the new shape.
  - `_inject_runtime_options()` no longer needs to push
    `product_type` into config — it already arrives via
    `split_unified` — and only copies `parameters.CAN_Channel` →
    `config.options.can_channel`.
  - `CONFIG_PATH` (= `inputs/DiagComm_config.json`) and
    `CONFIG_FILENAME` are new constants; `merge_values_with_config()`
    + `_read_config_for()` glue the two halves into the existing
    in-memory shape. `load_unified()` reads both files and merges.
  - `_check_legacy_layout()` now also rejects the **pre-split
    single-file v2** layout (paths/options still inline in
    DiagComm_values.json) with a concrete migration message.
- `scripts/pipeline.py`
  - New `_build_initial_values()` and `_build_initial_config()`
    return the values-half and config-half respectively; new
    `_write_v2_input_pair()` writes both files atomically-ish. The
    legacy `_build_initial_skeleton()` and `_write_unified_file()`
    are kept as wrappers so fixtures don't break.
  - Bootstrap / reseed write the **pair** (values + config) and the
    banner names both files. Reseed refuses if **either** file
    already exists, with a `rm <values> <config>` hint.
  - `_read_input_file()` accepts the v2 split (merges sibling
    `DiagComm_config.json`, falling back to the canonical
    `inputs/DiagComm_config.json`, then to defaults), the legacy
    single-file v2 (used as-is), and v1 / flat fixtures.
  - `_seed_values_from_arxml()` no longer stuffs `product_type` into
    the seed dict (it's project identity, not a parameter).
  - `_values_block_from_file` → `_parameters_block_from_file`,
    `_resolve_product_type()` reads `project.product_type` first
    (with v1 `values.product_type` fallback for stray fixtures).
- `scripts/build_doors_payload.py` and `scripts/doors_sync.py`
  - Both read v2 (`project.name`, `project.product_type`,
    `parameters.CAN_Channel`). `doors_sync.py` factors the read into
    one `_read_v2_identity()` helper with v1 fallback so a stray
    legacy fixture never blocks Step 8.
  - New `_load_values_with_config()` in `build_doors_payload.py`
    merges the sibling `DiagComm_config.json` so `paths` is
    available for `_collect_realizing_arxmls`. `doors_sync.py`
    routes its values read through the same helper.
- `scripts/doors_state.py::compute_param_fingerprint()` now hashes
  the `parameters` block directly. The product_type-exclusion filter
  stays as a defensive safety net for v1-shaped legacy data.
- `scripts/schema.py`, `inputs/doors_mapping.yaml`, `SKILL.md`,
  `state/README.md` — all references to `values.product_type` /
  `values.<x>` rewritten to `project.product_type` /
  `parameters.<x>`, and `paths` / `options` references now point at
  `DiagComm_config.json`. `SKILL.md` Step 1 gained an explicit "v2
  schema" block describing the two-file layout.
- `inputs/DiagComm_values.json` — regenerated as v2 (project +
  parameters only). Parameters are reordered into functional groups
  (channel/frame → addressing → CanTp timing → Dcm/UDS).
- `inputs/DiagComm_config.json` — **new file** (paths + options).
  Carries the standard Bosch CusDiag layout defaults.

### Migration

Skill is unreleased outside the working repo, so the migration policy
is **delete and re-seed** (no auto-rewrite):

1. Stop any in-flight Step 8 run.
2. Easiest: delete both files and re-seed.

   ```
   rm inputs/DiagComm_values.json inputs/DiagComm_config.json
   python scripts/pipeline.py reseed
   ```

   The bootstrap writes both halves directly in the v2 split shape.
3. Hand-edit alternative: split your existing v1 file into two:

   * `DiagComm_values.json` keeps `{$schema, project, parameters}`
   * `DiagComm_config.json` gets `{$schema, paths, options}`

   The example blocks above are the canonical templates.
4. The state file (`state/doors_upload_state.json`) is untouched by
   this change — it tracks DOORS-side identity (`module_uuid` +
   project/product/fingerprints). Any prior v3 entries keep working.

If a hand-edited file still has the v1 layout — or the pre-split
single-file v2 — on the next run, `_check_legacy_layout()` raises a
`SystemExit` pointing at this changelog entry; nothing silently
corrupts data.

### Notes

- `CAN_Channel` is kept inside `parameters` per the user's spec.
  Even though it reads like a path selector, it changes which CAN
  Pdu chain the project ships and therefore *is* a real parameter
  contributing to the fingerprint.
- The fingerprint output is **stable** across this change for any
  file whose `values` block already lacked `product_type` — but
  product_type is removed from `parameters` in v2 by definition, so
  for files that had it inside `values`, the new fingerprint may
  differ. That's intentional: previously the value was filtered out
  before hashing; now it's never in the dict to begin with. State
  files written in 1.12.0 may therefore re-classify as
  `params_changed` on the first 1.13.0 run for the same data.

## [1.12.0] - 2026-05-06

Reframes the DOORS row as a **living record** rather than a snapshot.
The conceptual model that drove this rework:

- The parameter set (`DiagComm_values.json::values` minus
  `product_type`) is unique per upload — at any moment in time the
  values file describes one parameter configuration.
- The `(project_name, product_type)` pair is **not** unique — one
  parameter set may serve multiple projects/products over its
  lifetime.

Therefore, the DOORS row tracked under each `module_uuid` accumulates
information across runs instead of being overwritten:

- `RB_Product` is the union of every product that ever shared the
  row (each item translated through `value_maps.RB_Product`).
- `RB_Realizing_SWitem` is the union of every arxml that ever
  appeared under the row.
- `Object Text` is the union of every prior FSCS / delta block — each
  update appends; nothing is replaced. The append template depends on
  the `change_kind` (params changed / project-or-product only /
  FSCS-only / no-change).

### Changed

- **`scripts/doors_state.py`** — schema bumped from v2 to **v3**.
  - Each `modules.<uuid>` entry now carries
    `covered_projects[]`, `covered_products[]`,
    `covered_arxml_paths[]`, `last_object_text`, and an append-only
    `history[]` log alongside the existing `last_success_abs`,
    `last_upload_at`, and `current_*` fields.
  - New `classify_change()` returns one of `first_insert`,
    `params_and_pp_changed`, `params_changed`, `pp_only_changed`,
    `fscs_only_changed`, `no_change`.
  - New `record_insert()` (replaces the entry; resets `covered_*`
    lists) and `record_update()` (preserves `last_success_abs`; grows
    `covered_*`; refreshes `last_object_text`; appends to history).
  - `decide_mode()` keeps the v1.11.0 truth table (insert only on
    `first_insert` / `params_and_pp_changed`); `decide_mode_from_kind`
    is the new low-level form taking a pre-classified kind.
  - New `union_preserve_order()` helper.
  - Added `get_module_entry()` for read-only state access from
    `doors_sync.py` and `build_doors_payload.py`.
  - Auto-migrates v1 → v2 → v3 on first read.

- **`scripts/build_doors_payload.py`** — v6 header.
  - `build_payload()` accepts new optional kwargs `existing_state`,
    `change_kind`, `cli_target_abs`. The orchestrator passes them in;
    hand-driven CLI runs default to `first_insert` / `params_changed`
    plus a new `--state-file` discovery path for parity.
  - New `_build_object_text_for_kind()` driver and four append-block
    templates (`_build_pp_only_block`, `_build_fscs_only_block`,
    `_build_params_changed_block`, `_build_no_change_block`) plus
    `_join_with_blank_line()` glue. The deprecated `_build_hybrid_text`
    stays for backward compat behind `extras.fscs_hybrid_text`.
  - New `_apply_rb_product_map()` to translate a *list* of products
    via `value_maps.RB_Product` (the legacy `map:` source only ever
    handled scalars).
  - New extras: `extras.rb_product_value`, `extras.rb_realizing_value`,
    `extras.appended_block`, `extras.change_kind`.
  - Empty `diff_report.txt` is now allowed in `update + single_row`
    mode when `change_kind ∈ {pp_only_changed, no_change}` — the
    appended Object Text block carries the change description.
  - Update mode validation accepts `cli_target_abs` as the
    AbsoluteNumber when no per-arxml `updates` are needed.
  - Payload report now lists `change_kind`, prior `covered_*` sizes,
    final union'd cell content, and Object Text length deltas.

- **`scripts/doors_sync.py`** —
  - Calls `classify_change()` first, then routes through
    `decide_mode_from_kind()` (or `--force-mode` overrides).
  - Threads the `change_kind`, the existing state entry, and the
    `cli_target_abs` into `build_doors_payload.build_payload()`.
  - On success calls `record_insert(...)` (insert mode) or
    `record_update(...)` (update mode) — the latter accumulates
    `covered_*` lists and appends to history.
  - New `_rebuild_state_inputs()` helper recomputes the freshly
    written `Object Text` and union'd realizing-paths from the same
    deterministic inputs the builder used, so the persisted state
    snapshot matches what DOORS now holds.
  - Decision banner includes `change_kind` and a one-line summary of
    the carried-over `covered_*` sizes; insert mode now prints an
    explicit "this orphans the previous row in DOORS" warning.

- **`inputs/doors_mapping.yaml`** — v5 header notes.
  - `RB_Product` rebound from `map:RB_Product:extras.product_type` to
    `extras.rb_product_value` (cell-ready, mapped + joined union).
  - `RB_Realizing_SWitem` rebound from `extras.realizing_arxmls` to
    `extras.rb_realizing_value` (cell-ready joined union).
  - `Object Text` still binds to `row.object_text` (the value is now
    built by the new `_build_object_text_for_kind` driver).
  - Long source-prefix doc table updated to reflect the new extras
    and the deprecation of `extras.fscs_hybrid_text`.

- **`SKILL.md` Step 8** — full rewrite of the auto-decision table,
  cell content rules (insert vs update), state file description, and
  the post-upload verification checklist. Banner example updated.

- **`state/README.md`** — full v3 documentation: schema with the
  three field groups (`current_*`, `covered_*`, history), decision
  table by `change_kind`, migration policy (v1→v2→v3), and recovery
  procedures including the new "shrink covered_products" instruction.

- **`VERSION`** — `1.11.0` → `1.12.0`.

### Behaviour change worth calling out

In `1.11.0`, swapping product (e.g. `ESP` → `IPB`) on the same
parameter set did `update`, but the row was *replaced* —
`RB_Product = "IPB 2.0"` and the previous "ESP 10" was lost. In
`1.12.0` the same action still does `update`, but now `RB_Product`
becomes `"ESP 10\nIPB 2.0"` (insertion order, dedup), and a compact
"new mapping" note is appended to `Object Text`. Same for
`RB_Realizing_SWitem` (paths grow). If you specifically want the row
to forget the previous product, pass `--force-mode insert` (which
carves a brand-new row and abandons the old one).

## [1.11.0] - 2026-05-06

Refines the auto insert/update decision to track **one DOORS row per
`module_uuid`**, not one row per `(module_uuid, project, product)`.
The new rule: **insert only when the parameters AND the project/product
context have both genuinely changed** — every other case (parameters
unchanged, or only the project/product changed, or only the parameters
changed) is `update` against the row recorded in state.

### Changed

- **`scripts/doors_state.py`** — schema bumped from v1 to **v2**.
  - `entries["<uuid>|<project>|<product>"]` is replaced with
    `modules["<uuid>"]` (one entry per `module_uuid`).
  - `decide_mode()` now takes
    `(module_uuid, project_name=, product_type=, param_fingerprint=)`
    and implements the new truth table:
    | params changed? | proj/prod changed? | state has entry? | mode |
    | --- | --- | --- | --- |
    | — | — | no | **insert** |
    | no | no | yes | (`is_no_change` → skip) |
    | no | yes | yes | **update** (refresh project/product cells) |
    | yes | no | yes | **update** |
    | yes | yes | yes | **insert** |
  - `compute_param_fingerprint()` now **excludes `product_type`** from
    the SHA-256 input, so swapping product alone doesn't flip the
    fingerprint (it's a "project/product" change, not a "parameter"
    change). `project_name` was always excluded (it's a top-level
    field, not part of `values`).
  - New `get_last_abs(state, module_uuid)` convenience helper used by
    `--force-mode update`.
  - Auto-migrates v1 state files: per `module_uuid`, the entry with
    the most recent `last_upload_at` survives; older per-product
    entries are dropped (with a one-line stderr note).
  - `record_success()` and `is_no_change()` keyed by `module_uuid`
    only.
- **`scripts/doors_sync.py`** —
  - Drops `make_key()`; passes `module_uuid` + project + product +
    fingerprint into `decide_mode` directly.
  - Decision banner no longer prints `state key`; just
    `module_uuid` + `decided mode` + `reason`. Reasons are now
    descriptive ("params unchanged; refreshing cells for product
    'ESP' -> 'IPB'", "params changed but project+product unchanged",
    etc.).
  - `--force-mode update` validates against the module's
    `last_success_abs` directly (no triple key required).
- **`SKILL.md` Step 8** — auto-decision rule rewritten to the new
  truth table; `state/` description rewritten to explain the v2
  schema and migration; banner example updated.
- **`state/README.md`** — full v2 documentation: schema, decision
  rule, migration policy, and recovery procedures (per-module
  removal, full wipe, etc.).
- **`VERSION`** — `1.10.0` → `1.11.0`.

### Behaviour change worth calling out

In `1.10.0`, swapping `product_type` (e.g. `ESP` → `IPB`) was an
**insert** — a brand-new DOORS row got created. In `1.11.0` the same
action is an **update**: the existing row is rewritten in place with
the new `RB_Product`, the new `RB_Realizing_SWitem` paths, etc. If
you genuinely want a new row (e.g. you're authoring a second product
in the same DOORS module), pass `--force-mode insert`.

## [1.10.0] - 2026-05-06

Step 8 (DOORS upload) now **auto-decides** between `insert` and
`update` — no more "ask the user every time". Decision is driven by a
new agent-owned state file that records the `AbsoluteNumber` DOORS
returned on the previous successful upload, keyed by
`(module_uuid, project_name, product_type)`. `update` mode now also
ships a richer Object Text payload (full FSCS + a delta block).

### Added

- **`scripts/doors_sync.py`** — single Step 8 entry point. Reads
  `inputs/DiagComm_values.json` + `inputs/doors_mapping.yaml` +
  `state/doors_upload_state.json`, decides mode automatically, calls
  `build_doors_payload.build_payload(...)` in-process, then runs
  `doors_upload.py` as a subprocess, parses `Data: SUCCESS:<n>`, and
  persists the new state. Supports `--force-mode insert|update`,
  `--force-no-skip`, `--no-upload`, and `--user-nt` / `--password`
  (the latter falls back to `$DOORS_USER_NT` / `$DOORS_PWD`).
- **`scripts/doors_state.py`** — pure module: `load_state`,
  `save_state` (atomic), `make_key`, `compute_param_fingerprint`,
  `compute_file_sha256`, `decide_mode`, `record_success`,
  `is_no_change`. Imported by `doors_sync.py`; not a CLI.
- **`state/`** folder — agent-owned. Ships with `.gitkeep` and
  `README.md`. `state/doors_upload_state.json` is created on the first
  successful upload and committed alongside the skill so a teammate's
  checkout already knows which DOORS row each `(project, product)`
  maps to.
- **Hybrid `Object Text` for update mode** — `build_doors_payload.py`
  now exposes `extras.fscs_delta_text`, `extras.fscs_hybrid_text`, and
  per-row `row.object_text`. `inputs/doors_mapping.yaml` binds
  `Object Text` to `row.object_text`, which equals:
  - **insert**: full `outputs/FSCS.txt` verbatim (unchanged).
  - **update**: full `outputs/FSCS.txt` + separator + a delta block
    (timestamp, project, product, changed files, changed parameters
    rendered as `'<old>' -> '<new>'`, parsed from
    `outputs/diff_report.txt`).
- **`--force-no-skip`**: when `param_fingerprint` AND `fscs_sha256`
  both match the recorded last upload, `doors_sync.py` exits 1 with a
  "no semantic changes, skipping" notice. Pass `--force-no-skip` to
  upload anyway.

### Changed

- **`build_doors_payload.py`**:
  - `single_row + update` no longer requires exactly one entry in
    `updates:`. It now requires all entries to point at the **same**
    AbsoluteNumber (because single_row merges every arxml into one
    row). This unblocks `doors_sync.py`'s default behaviour of mapping
    every diff arxml onto the same recorded `last_success_abs`.
  - Header docstring bumped to v5.
- **`inputs/doors_mapping.yaml`**:
  - `Object Text` now binds to `row.object_text` (was
    `extras.fscs_full_text`). Behaviour for insert mode is unchanged;
    update mode picks up the hybrid text automatically.
  - Header comment expanded with v4 notes (mapping behaviour, mode is
    now a default — `doors_sync.py` decides automatically).
- **`SKILL.md` Step 8**: rewritten around `doors_sync.py`. Removed the
  "ask the user insert/update + collect AbsoluteNumber per arxml"
  prompt. Added: decision rule table, the no-change short-circuit,
  the state file location/recovery, and a direct vs hand-driven
  invocation table.
- **`.gitignore`**: adds `state/*.tmp` (atomic-write side-effects).
- **Hard rules (§7, §9)**: §7 lists `doors_sync.py` as the canonical
  Step 8 entry point; §9 forbids hand-typing AbsoluteNumbers for
  `--force-mode update` (always source from state).

### Migration

- Existing users with no state file: first run after upgrade will
  decide `insert` for every (project, product), upload, then create
  state. This is correct (no row was ever inserted by this skill
  before). If you have an existing DOORS row from a *manual* prior
  upload that this skill should now own, either:
  - run once with `--force-mode insert` and accept a duplicate row,
    then delete the old row in DOORS, or
  - hand-edit `state/doors_upload_state.json` to seed
    `last_success_abs = "<existing_abs>"` for the relevant key
    (rare; see `state/README.md`).
- Existing users with stale `inputs/doors_mapping.yaml` overrides:
  if `Object Text` is hand-bound to `extras.fscs_full_text`, leave it
  for insert-only behaviour, or switch to `row.object_text` to pick
  up the hybrid update text.

## [1.9.0] - 2026-04-28

The skill is now **fully self-contained** for DOORS round-trips. It no
longer reaches into the sibling `doors-toolkit` skill at runtime — every
helper it needs is bundled under `scripts/` and `reference/`. The
sibling skill still exists (for *other* future skills to reuse) but
`diagcomm-toolkit` is now installable as a single folder.

### Added

- **`scripts/doors_helper.py`** — local CLI replacing the subprocess
  calls into `../doors-toolkit/scripts/pipeline.py`. Subcommands:
  `show-target`, `inspect`, `extract`, `extract-many`, `lint-excel`,
  and a new **`lint-doors-xlsx`** that checks the 3 known DOORS-rejection
  modes (Application string, sharedStrings, numeric meta cells).
- **`scripts/excel_io.py`** / **`scripts/json_query.py`** / **`scripts/_log.py`**
  — vendored from `doors-toolkit/scripts/` (same source). `excel_io`
  is the canonical openpyxl + lint helper.
- **`reference/doors_*.md`** — vendored copies of `doors-toolkit/reference/*.md`
  with paths rewritten to local (`scripts/doors_helper.py` instead of
  `../doors-toolkit/scripts/pipeline.py`). The xlsx-format lesson
  (xlsxwriter vs openpyxl) is now documented in
  `reference/doors_excel_conventions.md`.

### Changed

- **`scripts/build_doors_payload.py`** no longer spawns subprocesses
  to `doors-toolkit`. It imports `doors_helper.cmd_show_target` and
  `excel_io.lint_workbook` directly and runs them in-process. Faster
  startup, no PYTHONPATH gymnastics, and `doors-toolkit` is no longer a
  required sibling on disk.
- **`SKILL.md`** — every `../doors-toolkit/...` path replaced with
  the local equivalent; troubleshooting / file-map / "Where to read
  next" sections updated. The "Step 8 — upload FSCS to DOORS"
  section now describes the 3 local helpers (`doors_helper.py`,
  `build_doors_payload.py`, `doors_upload.py`) and explicitly says no
  sibling skill is needed.
- The Step 7.5c JSON path example fixed to `data.rows[?...]` (Bosch
  DWA exports root the rows under `data.rows`, not `rows`).

### Removed

- Runtime dependency on `../doors-toolkit/scripts/pipeline.py`.
  `doors-toolkit` is now mentioned only as a sibling reference, not a dep.

### Migration

Nothing for end-users to do. If you have a working v1.8.x install,
`git pull` will bring the new files; the next Step 7.5 / 8 run picks
them up automatically. If you'd previously cloned `doors-toolkit`
specifically for this skill, you can now drop it (but feel free to
keep it — its v2.0.0 release ships the same lessons-learned in a
form usable by other future skills).

## [1.8.0] - 2026-04-28

DOORS upload made self-contained and reliable. Two structural fixes
that together eliminate the "upload hangs for 13–17 minutes then
times out" failure mode that hit a real project after 1.7.1:

### Changed (breaking for the upload step only — no data-format change)

- **`build_doors_payload.py` now writes the xlsx with `xlsxwriter`**
  instead of openpyxl. DOORS' import service silently rejects (or
  hangs on) xlsx files whose `docProps/app.xml` lists `Application` as
  anything other than "Microsoft Excel" — openpyxl tags the file
  `Openpyxl 3.1.5`, which was the root cause of the post-upload hang.
  `inputs/doors_template.xlsx` is still consulted for the canonical
  column ORDER, but is no longer copied / saved-back. Since 1.18.0 this
  file is bundled with the skill and hidden from normal user workflow.
  Output now has `Application=Microsoft Excel`, ships a
  `xl/sharedStrings.xml` part, and writes `sizeRow` / `sizeColumn` as
  *strings* — exactly matching `references/test_upload.xlsx`.
- **No more separate "fix" step.** Any external xlsx-fix script
  (e.g. `fix_upload_file.py`) is now redundant. SKILL.md hard rule
  §10 forbids running one before the upload.

### Added

- **`scripts/doors_upload.py`** — local upload helper that calls the
  `upload_doors_module` MCP tool over plain HTTP/SSE with a hard
  180 s upload timeout (default), instead of going through
  Cursor's `CallMcpTool` (which has no per-call timeout knob and
  was the actual reason the IDE appeared to "hang" — the server was
  slow, not us).
  Usage: `python scripts/doors_upload.py <xlsx> <module_uuid> <user_nt> <password>`
  with optional `--server-url` / `--upload-timeout`.
- **`scripts/requirements.txt`** now also pins `xlsxwriter>=3.2`,
  `openpyxl>=3.1`, and `requests>=2.31`.

### Documentation

- Step 8c rewritten: instead of constructing a `CallMcpTool`
  invocation inline, the agent now runs the local
  `python scripts/doors_upload.py` (positional args + env-var
  password) and reports the printed `[SUCCESS] Upload completed` /
  `Data: SUCCESS:<n>` line back to the user.
- Step 8d (verify) now keys verification off the `<n>` returned by
  `Data: SUCCESS:<n>` (the new row's AbsoluteNumber).
- Hard rule §10 added: never run an external xlsx-fix step
  before upload — `build_doors_payload.py` already produces
  DOORS-native xlsx.
- Troubleshooting table updated for the new failure modes
  (`doors_upload.py` exits 1, hits its 180 s timeout, etc.).

### Smoke test

End-to-end run on a real project (ESP product type) /
module `1-aaaaaaaaaaaaaaaa-M-bbbbbbbbbbbbb`:

```text
build_doors_payload.py    -> outputs/doors_upload.xlsx (12.9 KB, xlsxwriter)
doors_upload.py            -> [SUCCESS] Upload completed successfully.
                              Data: SUCCESS:574    (60 s end-to-end)
```

## [1.7.1] - 2026-04-28

Live-upload calibration after first end-to-end DOORS round-trip with
a real project (ESP product type). The DOORS server rejected the previously-shipped xlsx
shape; three concrete corrections to match the actual contract.

### Changed

- **`Destination Object` (col B) now carries the anchor's bare
  `AbsoluteNumber`** (e.g. `400`), not the full identifier
  `503571_SWFS_SWCS_DCOM_400`. The full identifier was rejected by
  the DOORS upload endpoint. `build_doors_payload.py` now sources
  `row.destination` from the anchor's `AbsoluteNumber` field.
- **`Object Heading` (col E) now empty**. The previous
  `"DiagComm baseline @ <timestamp>"` literal was
  rejected upstream. `inputs/doors_mapping.yaml::columns` uses the
  new `literal:` (empty) source to write a blank cell.
- **`Object Text` (col F) now carries the full `outputs/FSCS.txt`**
  verbatim instead of the per-arxml subset. The full FSCS is the
  "what was delivered" document; the per-arxml subset (which
  parameters changed in this run) lives in `diff_report.txt` and is
  not what DOORS wants to ingest. `inputs/doors_mapping.yaml::columns`
  switched from `row.fscs_chunk` to `extras.fscs_full_text`.
- **`strategy:` default flipped from `per_arxml` to `single_row`**.
  Now that every row would carry identical `Object Text`, per-arxml
  rows would only differ in `RB_Realizing_SWitem`; the `single_row`
  strategy aggregates the arxml basenames into one cell (newline
  separated) and emits a single FSCS row. `per_arxml` is still
  supported for callers that want it.

## [1.7.0] - 2026-04-28

Step 8 made project-portable. The hand-curated per-arxml
`destinations` map (identifiers like `503571_SWFS_SWCS_DCOM_400`) was
replaced by a **dynamic anchor lookup** against `outputs/doors_export.json`,
plus an explicit insert-vs-update mode selection at upload time.

### Changed

- **`inputs/doors_mapping.yaml`** — schema v3:
    - Removed `destinations:` and `unknown_destination_policy:` blocks
      (no more hand-picked per-arxml IDs in the mapping yaml).
    - Added `anchor:` block with `by_heading` (default `"CAN ID and
      Timing Requirements"`) + `heading_field` (default
      `DescriptionOfRequirementRB`) + optional `by_identifier` /
      `by_absolute_number` fallbacks.
    - Added `mode:` field (`insert` default, or `update`) and an
      `updates:` block for update-mode AbsoluteNumbers.
    - Added the `Absolute Number` column to `columns:` so
      update-mode flows can fill column D dynamically.
- **`scripts/build_doors_payload.py`** — rewritten to v3:
    - In `insert` mode: reads `outputs/doors_export.json`, walks rows
      to find the anchor (by id / heading / abs-number), writes its
      `identifier` into column B of every data row, leaves column D
      blank. DOORS lays the rows down sequentially in the order they
      appear in the xlsx.
    - In `update` mode: writes the per-arxml AbsoluteNumber into
      column D of each row, leaves column B blank. AbsoluteNumbers
      come from `updates:` in the yaml or the new
      `--mode update --update-abs <arxml>=<n>` CLI flags.
    - Surfaces the matched anchor (rule + identifier + AbsoluteNumber)
      in `outputs/doors_payload_report.txt`.
    - Clear, actionable error messages for "anchor not found" and
      "update mode missing an arxml".
- **`SKILL.md`**:
    - Step 7.5 reframed: now confirms the anchor heading text actually
      matches a row (instead of validating an `extract.*.json_path`).
    - Step 8b reframed: the agent first asks the user
      *"insert (default) or update?"* and, if `update`, collects the
      AbsoluteNumber for each arxml in the diff, then invokes the
      builder with the corresponding flags.
    - Hard rule 9 updated: anchor identifiers are *always* derived
      dynamically; never type one in by hand.
- **`doors-toolkit/reference/mapping_format.md`** — Model B section
  reflects the new `anchor` / `mode` / `updates` blocks.
- **DOORS `RB_Product` column is now derived per-row from
  `inputs/DiagComm_values.json::values.product_type`** via a new
  `value_maps:` block in `inputs/doors_mapping.yaml`. The DOORS-side
  vocabulary is `DPB / "ESP 10" / "IPB 2.0" / RBU` (probed from the
  live module: 13 distinct combos across 652 rows), the DiagComm-side
  enum is `DPB / ESP / IPB / RBU`. The shipped map covers all four.
  Resolution uses a new `map:<map_name>:<inner_source>` prefix in
  `columns:` (e.g. `"map:RB_Product:extras.product_type"`), so the
  feature is generic — any other column that needs enum translation
  can use the same mechanism by adding to `value_maps:`.
- **`scripts/build_doors_payload.py`** — `_resolve_source` now
  understands the `map:` prefix and produces an actionable error
  message listing the known map keys when the lookup misses.

### Why

Different projects' DOORS modules have different object identifiers.
Hard-coding `503571_SWFS_SWCS_DCOM_…` per arxml in a checked-in yaml
means every project would have to rewrite that section. The new design
keeps the rule (insert after the "CAN ID and Timing Requirements"
heading) project-stable, and the live JSON dump is the single source
of truth for the actual identifier.

## [1.6.1] - 2026-04-28

Step 8 redesigned around the actual DOORS upload contract discovered
via `get_doors_module` (module
`503571_SWFS_0216_DCOM_SWCS_DiagnosisCommunication`, 1026 rows, 155
fields per row, no heading/title field). The DOORS-side import xlsx
is column-style (header row + data rows), so the cell-level mapping
from 1.6.0 was wrong.

### Changed

- **`inputs/doors_mapping.yaml`** — schema replaced. New blocks:
    - `template` (sheet / header_row / data_start / size_row),
    - `strategy: per_arxml | single_row`,
    - `destinations` (per-arxml DOORS object identifier),
    - `unknown_destination_policy` (fail | skip | append),
    - `defaults` (static RB_* column values),
    - `columns` (dynamic overrides via `row.*` / `extras.*` /
      `literal:` sources).
  Old `extract` / `fill` blocks dropped — they were single-row
  cell-fill semantics that don't fit the DOORS template.
- **`inputs/doors_template.xlsx`** — provisioned by copying the user's
  pre-existing `inputs/test_upload.xlsx` (sheet "CS Data", 15 columns:
  `Number`, `Destination Object`, `isPicture`, `Absolute Number`,
  `Object Heading`, `Object Text`, plus `RB_*` columns).
- **`scripts/build_doors_payload.py`** — rewritten end-to-end:
    - Parses `outputs/diff_report.txt` and groups the changes by
      arxml basename.
    - Emits one data row per arxml (or one aggregated row when
      `strategy: single_row`).
    - Writes `outputs/doors_upload.xlsx` and refreshes the meta
      header's `sizeRow` / `sizeColumn` automatically.
    - Refuses to run when any arxml in the diff has no
      `destinations` entry or still holds a `PUT-…` placeholder
      (under `unknown_destination_policy: fail`).
- **`SKILL.md` Step 8b/8c** — rewritten to match the per-arxml row
  model and the actual `upload_doors_module` MCP tool args
  (`module_uuid`, `user_nt`, `password`, `file_name`, `file_base64`).
  Step 8c now explicitly prompts for NT credentials at upload time
  and never persists them.
- **Hard rule 9** — already covered in 1.6.0; refined wording in the
  Step 8 troubleshooting table.

### Added (in `doors-toolkit`)

- **`reference/tool_inventory.md`** — populated with the four tools
  the live server exposes: `get_doors_module`,
  `refresh_doors_module`, `upload_doors_module`,
  `update_doors_links`. The canonical UUID arg is `module_uuid`.
- **`reference/mapping_format.md`** — adds Model B (column-style row
  uploads) alongside the original Model A.
- **`scripts/pipeline.py show-target`** — gates on placeholder UUID
  values (already in 1.6.0, retained).

## [1.6.0] - 2026-04-28

DOORS upload workflow. After Step 7 (apply + report) the skill can now
optionally push FSCS into a DOORS document via the new `doors-toolkit`
common skill (which itself talks to the `doors` MCP server at
`http://10.54.7.36:8000/mcp`).

### Added

- **`scripts/build_doors_payload.py`** — Step 8 helper. Reads
  `outputs/FSCS.txt` + `outputs/doors_export.json` (downloaded by the
  agent) + `inputs/doors_template.xlsx` + `inputs/doors_mapping.yaml`,
  delegates UUID-resolution / extraction / cell-fill / lint to
  `doors-toolkit`, and writes `outputs/doors_upload.xlsx` ready for the
  agent to import via the doors MCP `import_excel` tool. Never calls
  MCP itself. Refuses to run if the mapping yaml still has the
  placeholder `document_uuid`.
- **`inputs/doors_mapping.yaml`** — user-owned map. The required
  `doors.document_uuid` field carries the fixed UUID of the target
  DOORS document; `module_path` / `module_id` are optional fallbacks.
  `extract:` and `fill:` blocks unchanged. Schema documented at
  `../doors-toolkit/reference/mapping_format.md`.
- **`SKILL.md` Step 7.5** — one-time-per-project DOORS exploration
  loop: confirm UUID, pull the JSON dump, inspect its shape, refine
  `extract.insertion_object_id.json_path`. Writes nothing back to
  DOORS; can be re-run freely.
- **`SKILL.md` Step 8** — full upload-to-DOORS playbook: pre-flight
  checklist, `show-target` + MCP read-module call, `build_doors_payload.py`,
  agent-side confirm prompt, MCP import-excel call, post-upload verify.
  Skipped unless the user asks.
- **Hard rule 9** — never invoke `doors__*` MCP tools without explicit
  user "yes"; never invent module paths, object IDs or document UUIDs.

### Notes

- Step 7.5 / Step 8 are opt-in; Steps 1–7 behave identically to 1.5.1.
- The user must paste the real DOORS document UUID into
  `inputs/doors_mapping.yaml` before either step proceeds.
- Historical note: at this version the user had to drop the DOORS import
  template at `inputs/doors_template.xlsx` before Step 8b. Since 1.18.0
  the template is bundled with the skill and users do not edit it.
- The agent must run the one-time tool-discovery procedure in
  `../doors-toolkit/reference/tool_discovery.md` and update
  `tool_inventory.md` with the actual tool names + the UUID-arg name
  exposed by the server.

## [1.5.1] - 2026-04-27

Solo-dev / clone-and-use UX polish. No behaviour change.

### Added

- **`scripts/preflight.py`** — one-shot environment self-check. Run
  once after cloning to verify Python ≥ 3.12, `lxml` / `PyYAML` / (opt)
  `pytest`, skill files intact, default `base_dir = ../../..` actually
  resolves to a CusDiag tree (uses the same `*/rb/as/*/core/app/dcom`
  glob as `runtime.DEFAULT_PATHS`), and schema is in sync with
  `DiagComm.txt`. Pure stdlib, makes no network calls, installs nothing.

### Changed

- **`README.md`** — Quick start rewritten to lead with
  `git clone ... && pip install ... && preflight` for first-time
  colleagues; canonical install path
  `<your-project>/.agents/skills/diagcomm-toolkit/` now explicit.
  Recipes table gained a "validate clone / env" row.

### Removed

- **`.gitlab-ci.yml`** — the only check we could still run under the
  network policy was schema drift; the same check now runs as part of
  `preflight.py` (and locally before push). One less moving part for a
  single-developer repo.
- **`.gitattributes`** — solo-dev on Windows, no cross-OS contributions
  expected, so no LF-normalisation needed. Drop to reduce surface area.
- **GitLab pipeline badge** in `README.md` — no CI to report.

## [1.5.0] - 2026-04-26

**Breaking.** Retires `config/project.json` entirely. From this release
on, **every user-editable knob lives in a single unified file:**
`inputs/DiagComm_values.json`. Project identity, path templates,
behaviour flags, and the 23 DiagComm parameters are now nested under
one JSON document.

### Changed (breaking)

- **`config/project.json` deleted.** Its three former blocks moved into
  `inputs/DiagComm_values.json` as a top-level skeleton:
  - `project.name` → `project_name` (string at the top level).
  - `paths.*` → `paths.*` (same key set, same templates).
  - `options.*` → `options.*` (same keys: `dry_run_default`,
    `validate_before_apply`).
  - The 23 DiagComm parameters that were already in
    `inputs/DiagComm_values.json` (incl. 1.4.0's `product_type`) move
    one level deeper, under a new `values` block.
- **New top-level shape** (verbatim):
  ```jsonc
  {
    "$schema": "diagcomm-toolkit/v1",
    "project_name": "...",
    "paths":   { "base_dir": "...", "dcom_root": "...", ... },
    "options": { "dry_run_default": true, ... },
    "values":  { "product_type": "DPB", "CAN_Channel": 0, ... }
  }
  ```
- **Lazy-seed writes the full skeleton.** First-run bootstrap (and
  `pipeline.py reseed`) now produce the unified document, not a flat
  values dict. The reverse-walk still populates `values.*` from live
  ARXML; `paths` / `options` come from `runtime.DEFAULT_PATHS` /
  `DEFAULT_OPTIONS`; `project_name` is seeded as
  `<set-me-on-first-launch>` for the user to fill in.
- **Migration guard added.** If `config/project.json` still exists at
  runtime, the pipeline now refuses to start and prints explicit
  step-by-step instructions for hoisting your settings into
  `inputs/DiagComm_values.json` (and deleting the legacy file).

### Added

- **`runtime.load_unified()` / `split_unified()` / `load_diagcomm()`.**
  New loader API: `load_unified` returns the raw nested dict;
  `split_unified` returns the legacy `(config_view, values)` tuple so
  internal code that still expects the pre-1.5.0 split can keep
  working unchanged. `load_diagcomm` is the convenience wrapper.
- **`runtime.DEFAULT_PATHS` / `DEFAULT_OPTIONS` constants.** Source of
  truth for the standard AUTOSAR layout used during lazy-seed
  bootstrap; also a single monkeypatch point for the test fixture.
- **Unified test fixture.** `tests/fixtures/minimal/values.json` is now
  the single fixture file (the old `project.json` is gone). `conftest`
  patches `DEFAULT_PATHS` / `DEFAULT_OPTIONS` from the fixture so the
  lazy-seed path stays exercised end-to-end.

### Migration (existing projects)

1. Open `config/project.json`. Note the values of `project.name`,
   every entry under `paths.*`, and every entry under `options.*`.
2. Open `inputs/DiagComm_values.json`. Wrap its current contents
   under a new `"values"` key, then add three sibling top-level keys:
   ```jsonc
   {
     "$schema": "diagcomm-toolkit/v1",
     "project_name": "<paste project.name here>",
     "paths":   { /* paste paths block here */ },
     "options": { /* paste options block here */ },
     "values":  { /* the old flat contents of values.json */ }
   }
   ```
3. Delete the old file: `rm config/project.json` (and remove the now
   empty `config/` directory if you like).
4. Run `python scripts/pipeline.py status` -- expect
   `OVERALL: READY`. If you see the migration guard error instead,
   you missed step 3.

If you'd rather start fresh: `rm inputs/DiagComm_values.json
config/project.json` then `python scripts/pipeline.py reseed`. The
new unified skeleton is rebuilt from live ARXML in one shot.

## [1.4.0] - 2026-04-25

**Breaking.** Consolidates the two user-editable path selectors into
a single file so every "what the user changes" knob lives in
`inputs/DiagComm_values.json`. `config/project.json` shrinks to pure
project identity + static path wiring.

### Changed (breaking)

- **`product_type` moved to `inputs/DiagComm_values.json`.** Was in
  `config/project.json::project.product_type`; now a top-level
  `product_type` field in the values file, typed as an `enum` of
  `DPB | ESP | IPB | RBU` via `DiagComm_schema.json`. Runtime copies
  it back into `config.project.product_type` via
  `_inject_runtime_options` -- completely symmetric with the
  `CAN_Channel` → `config.options.can_channel` bridge introduced in
  1.2.1.
- **`config/project.json` trimmed.** Removed three fields that were
  either duplicated elsewhere or dead weight:
  - `project.product_type` -- moved to values file (see above).
  - `project.description` -- was declared but never read by any
    script; removed.
  - `product_type_allowed` -- was a stated "allow-list" but zero code
    enforced it; enum validation now lives in the schema (the only
    place that can actually reject an invalid value).
- **`reseed --force` flag is gone** -- already removed in 1.3.0, but
  1.4.0 locks the new "strict ownership" policy into the command
  surface: `reseed` *only* writes when `inputs/DiagComm_values.json`
  is missing. Nothing else.

### Added

- **`Product Type` field in `DiagComm.txt` + `FIELD_DEFS`.**
  `pipeline.py gen-schema` now produces a `product_type` entry at
  the top of `DiagComm_schema.json`, typed `enum
  [DPB, ESP, IPB, RBU]` with `prompt_required: true` and a
  description that flags it as a path selector, not arxml payload.
- **Filesystem-probe seeding for `product_type`.**
  `_resolve_product_type` now globs
  `RBAPLCust/cfg/*/Can*_CusDiag_EcucValues_*.arxml` under the
  resolved `dcom_root` and, if exactly one `<PT>/` folder ships the
  matching arxml, auto-picks that variant on first seed. Ambiguous
  or empty → falls through to the schema default (`DPB`) and the
  user edits by hand. This makes `reseed` effectively zero-arg on
  projects that only deploy one product variant.
- **`--product-type {DPB,ESP,IPB,RBU}` CLI flag on `reseed` and
  `landing-report`.** Overrides the probe + schema default for
  one-off seeds / reports against a non-primary variant.
- **Symmetric injection in `_inject_runtime_options`.** Now handles
  both `CAN_Channel` and `product_type` in one pass; empty strings
  and non-string `product_type` values are silently skipped (same
  failure model as `CAN_Channel`).

### Test coverage

- Four new `test_inject_runtime_options_*` cases for
  `product_type`: happy path, missing key, empty-string skip,
  non-string skip, and a "both fields together" smoke test.
- Existing 115 tests updated for the new values fixture layout
  (fixture values.json now carries `product_type: "DPB"`).

### Migration (existing projects)

1. Open `config/project.json`. Copy the value of
   `project.product_type` (if you had one).
2. Remove `project.product_type`, `project.description`, and
   `product_type_allowed` from `config/project.json`.
3. Open `inputs/DiagComm_values.json`. Add `"product_type": "<value
   you copied>"` as a top-level key (typical location: right above
   `CAN_Channel`).
4. Run `python scripts/pipeline.py status` -- should print
   `OVERALL: READY`. If you see `arxml files : DEGRADED`, the
   product_type you picked does not match a deployed
   `RBAPLCust/cfg/<PT>/` folder; fix it in the values file.

## [1.3.1] - 2026-04-25

Documentation-only release. Restructures `SKILL.md` and the
`reference/` files for better compatibility with weaker LLM models:
sequential step numbering, flat decision tables (no sub-lists inside
table cells), imperative tone throughout, one rule per bullet, and
aggressive pruning of redundant prose. No behavioural change to any
command or test.

### Changed (docs only)

- **`SKILL.md` rewritten.**
  - Steps are now `1..7` in order (was `0, 2, 3, 4, 6`), matching
    the seven-line workflow at the top one-to-one.
  - Each step section is ≤ 20 lines, table-first, imperative:
    one row per exit code, one action per row.
  - **Hard rules** collapsed to seven single-line items; the prose
    rationale for rule 4 (the `inputs/` ownership contract) moves
    to `reference/commands.md` and `reference/internals.md`.
  - **Troubleshooting** table gains one row per failure mode
    (7 rows total, one-sentence remedy each) — previously prose
    bullets.
  - Clarified the "Step 5 confirmation" script: explicit literal
    question the agent must ask, explicit list of acceptable
    affirmatives.
- **`reference/commands.md` tightened.**
  - Lazy-seed callout reduced from 13 lines to 5.
  - `reseed` description compressed from ~35 lines to ~15.
  - Duplicate rollback section at bottom removed (lives in
    `SKILL.md` Step 7 + `reference/internals.md`).
  - Per-command YAML blocks flattened into markdown headers +
    tight prose + side-effects bullets.
  - Each command anchor renamed to its bare command name
    (`#status`, `#validate`, etc.) — stable, grep-friendly.
- **`reference/parameter_types.md` legend compressed** to two
  bullets plus a one-line note about the "delete-first" re-sync
  path. Summary matrix reduced to two columns.
- **`reference/transforms.md` "add a new transform" recipe** reduced
  to five lines.
- **`reference/internals.md` intro** reduced from 9 to 3 lines.
- **`reference/landing_spots.md` intro** reduced by one paragraph.
- **`reference/porting_checklist.md`** tightened §5 (baseline) and
  §9 (editor/shell compatibility).

### Not changed

- Zero code changes. `pytest -q tests` still reports 114/114 green.
- No CLI surface changes.
- `VERSION` bumped `1.3.0 → 1.3.1` (patch: docs only).

## [1.3.0] - 2026-04-25

Tighten the ownership contract on `inputs/`: `reseed` no longer
accepts `--force`, and the skill never overwrites any file under
`inputs/` (lazy-seeding a *missing* `DiagComm_values.json` is the
sole exception). Users re-sync by deleting the file themselves.
Breaking CLI change — callers of `reseed --force` must now `rm` the
file first.

## [1.2.1] - 2026-04-25

Collapse `CAN_Channel` to a single source of truth in
`inputs/DiagComm_values.json` (removed `options.can_channel` from
`config/project.json`). Wire `project.name` into every `outputs/FSCS.txt`
header and the `pipeline.py status` output. Dependency errors for
`lxml` / `PyYAML` are now symmetric, with a pre-flight probe in
`status` that reports the exact `pip install` command before any
later command would fail mid-flight.

## [1.2.0] - 2026-04-25

Remove skill-local backups and `pipeline.py restore`; rollback is
delegated to the target project's own VCS
(`git checkout -- <arxml>` / `svn revert <arxml>` / …), with
`outputs/diff_report.txt` naming every touched file. The `outputs/`
tree is now strictly regenerable reports.

## [1.1.0] - 2026-04-24

Architecture reset to the standard *SKILL.md + `scripts/pipeline.py`*
shape. Added lazy-seed of `inputs/DiagComm_values.json` on the first
pipeline command and an explicit `pipeline.py reseed` for on-demand
re-sync from live arxml. Removed the WebUI wizard, the desktop
launchers, the intermediate `outputs/project_defaults.json` artefact,
and the contributor toolchain (CI config, pre-commit, ruff config,
dev scripts, build-release script).

## [1.0.0] - 2026-04-24

First public release. Shipped the byte-level surgical ARXML patcher
(`scripts/arxml_patcher.py`), the declarative parameter → locator
mapping (`scripts/mapping.yaml` + `mapping.py`), the semantic
validation layer (`scripts/semantic.py`), and an initial 5-step
WebUI wizard. The wizard and its surrounding toolchain were removed
in 1.1.0; the patcher / mapping / validation core is what the
current skill still builds on.
