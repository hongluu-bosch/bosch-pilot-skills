# Workspace model — multi-project layout

> **When to read this.** You're setting up a new project, switching
> between project workspaces, configuring multiple
> product/customer variants in the same workspace, or debugging
> "wrong project root resolved" issues.

The skill is install-once / use-everywhere. The skill folder
holds **only code** (`scripts/`, `reference/`, `templates/`,
`tests/`); each real project keeps its own **workspace** under
a hidden two-level path —
`.DCOM_AI/DID_Toolkit_PRJ/` — inside the project container,
with its own `config/project.json`, `inputs/`, `outputs/`,
`scripts/`, and `state/`. `.DCOM_AI/` is the generic AI-tooling
umbrella (dot-prefixed so file-tree viewers hide it the way
they hide `.git/`); `DID_Toolkit_PRJ/` is the did-toolkit's
named slot inside it, leaving room for future AI tools as
sibling subdirectories.

### Workspace layout

The workspace lives **inside** the project container (the
directory that hosts the Bosch `rb/as/...` tree), not at the
container's root, so the toolkit's bookkeeping doesn't pollute
the Bosch project's existing layout:

```
my-bosch-project/                              ← project container; paths.base_dir points here
├── Fe_Super/rb/as/<customer>/...              ← Bosch BSW tree (unchanged)
└── .DCOM_AI/                                  ← AI-tooling umbrella (hidden, .git-style)
    └── DID_Toolkit_PRJ/                       ← did-toolkit workspace
        ├── config/project.json                ← the marker file (also: ProjectConfig payload)
        ├── inputs/                            ← drop diagnostic questionnaires here
        ├── outputs/                           ← FSCS + ARXML / impl / DOORS reports
        ├── scripts/                           ← operator-written extract_<customer>.py
        └── state/                             ← doors_upload_state.json + future state
```

This is the **only** supported workspace shape. Earlier layouts
(flat `config/` / `inputs/` / `outputs/` under the container, or
a single-level `.DCOM_AI/{config,...}` without the
`DID_Toolkit_PRJ/` namespace) are not recognised and not auto-
migrated — see [§ Migrating from an older layout](#migrating-from-an-older-layout)
below for the manual upgrade recipe.

---

## 1. Project-root resolution (four-tier)

Every run resolves a single project root using the policy in
[`scripts/project_root.py`](../scripts/project_root.py):

| Priority | Source | When it fires |
|---|---|---|
| 1 | `--project-root <path>` | Explicit CLI flag — highest priority. Use in scripts / CI / agent automation when the workspace path is known. Accepts any of three shapes: the **container path** (resolver hops through `.DCOM_AI/DID_Toolkit_PRJ/` automatically), the `.DCOM_AI/` umbrella path (one hop into `DID_Toolkit_PRJ/`), or the `.DCOM_AI/DID_Toolkit_PRJ/` workspace path directly. |
| 2 | `$DID_TOOLKIT_PROJECT_ROOT` | Environment variable — set once per shell, every subsequent invocation picks it up. Same container/umbrella/workspace symmetry as the CLI flag. |
| 3 | **CWD walk** | Toolkit looks at the current directory and every ancestor for one that contains `.DCOM_AI/DID_Toolkit_PRJ/config/project.json`. First hit wins; identical UX to `git`. The walker returns the **workspace** path (with the two-level hop already applied), so phases see `self.base_dir` transparently. |
| 4 | **Skill-folder fallback** | When nothing else matches, defaults to the skill install dir — single-workspace fallback where the skill folder *is* the project folder. |

The resolved path becomes `controller.project_root`; both
`controller.project_root` and the legacy alias
`controller.base_dir` point at the same location — the
`.DCOM_AI/DID_Toolkit_PRJ/` workspace under the container.

### Migrating from an older layout

If a project still keeps `config/` / `inputs/` / `outputs/`
directly under the container, or under a single-level
`.DCOM_AI/` (the layout used before the
`DID_Toolkit_PRJ/` namespace landed), the resolver won't find
them. One-off migration steps:

```bash
cd /path/to/my-bosch-project          # the project container
mkdir -p .DCOM_AI/DID_Toolkit_PRJ
# old flat layout — move from the container root:
mv config inputs outputs .DCOM_AI/DID_Toolkit_PRJ/
[ -d state ] && mv state .DCOM_AI/DID_Toolkit_PRJ/
# OR old single-level layout — move from .DCOM_AI/ instead:
# mv .DCOM_AI/config .DCOM_AI/inputs .DCOM_AI/outputs .DCOM_AI/DID_Toolkit_PRJ/
# [ -d .DCOM_AI/state ] && mv .DCOM_AI/state .DCOM_AI/DID_Toolkit_PRJ/
```

That's the entire migration. `config/project.json` is unchanged
(`paths.base_dir` still points at the container). The pipeline
auto-discovers the new workspace location on the next invocation.
**Do not** re-run `--init-project` — that would refuse (exit 1)
because a workspace already exists in the right place after the
move.

### Skill root vs project root

* `controller.skill_root` — where this skill is installed
  (immutable code: `scripts/`, `reference/`, `templates/`).
* `controller.project_root` — the resolved workspace (mutable
  data: `config/`, `inputs/`, `outputs/`).

Phase modules `import` from `skill_root / 'scripts'` so the
imports are stable regardless of which workspace is active. All
file I/O resolves under `project_root`.

---

## 2. Scaffolder — `--init-project` (sole entry point)

Spin up a new workspace with the unified scaffolder.
`--init-project` is the **only** way to materialise
`config/project.json` (there is no separate `setup.py`).

```bash
# inside the directory that should become your project workspace
cd /path/to/my-bosch-project
python /path/to/skill/scripts/pipeline.py --init-project
```

`--init-project` is a **resumable state machine**. Each
invocation advances the workspace by exactly one step (call the
same command repeatedly until Phase 1 fires):

1. **FRESH → FOLDERS_ONLY** *(no `.DCOM_AI/DID_Toolkit_PRJ/` yet)*. Scaffolds
   `.DCOM_AI/DID_Toolkit_PRJ/{config,inputs,outputs,scripts,state}/` under the
   container, copies the starter templates
   (`scripts/extract_customer.py.template`,
   `inputs/doors_mapping.yaml.template`), prints a clear "drop a
   `*_did.json` under `.DCOM_AI/DID_Toolkit_PRJ/inputs/`" hint, exits 0 with
   `[AGENT STOP]`. **No `project.json` is written yet** — that
   waits for the questionnaire.
2. **FOLDERS_ONLY → FOLDERS_ONLY** *(skeleton present, no
   questionnaire yet)*. Idempotent: re-prints the questionnaire
   hint, exits 0. Designed for "operator re-runs the command
   before placing the file" — no destructive side effects.
3. **FOLDERS_ONLY → QUESTIONNAIRE_READY → COMPLETE** *(at least
   one `*_did.json` present, `project.json` still missing)*.
   Resolves WHICH questionnaire to use via
   `_pick_questionnaire` (single → auto-pick / `[Y/n]` confirm in
   TTY; multiple → numbered picker in TTY; non-TTY requires
   `--input <basename>` or fails with `_QuestionnaireAmbiguous`
   → exit 3). Auto-detects the adjacent Bosch BSW tree by
   walking the container for `<X>/rb/as/<Y>/core/app/dcom/RBAPLCust`
   (unique hit seeds `paths.*` with `{product_type_*}`
   placeholders; zero hits leaves them empty; multi-hit asks
   the operator). Runs the per-product scan in the same pass to
   seed `paths.per_product` overrides
   (`[INFO]`/`[CONFIRM]`/`[FYI]` log lines explained in
   [`configuration.md`](configuration.md#pathsper_product)).
   Writes `.DCOM_AI/DID_Toolkit_PRJ/config/project.json` (recorded questionnaire
   basename lands at `paths.input_did_json`), stops with an
   `[AGENT STOP]` and asks whether to advance into Phase 1.
4. **COMPLETE → Phase 1 auto-chain** *(everything in place on a
   subsequent run)*. Detects optional Bosch-tree drift via
   `_detect_bosch_tree_drift` — when the live
   `(project_root, customer)` scan no longer matches segments
   baked into `paths.pdm_file`, prints a `[WARN]` and (in TTY)
   prompts `Overwrite project.json with the detected tree?
   [y/N]`; non-TTY callers default to "keep" + WARN.
   Unconditionally invokes `PipelineController.run_phase1` with
   the recorded questionnaire and propagates Phase 1's exit
   code (0 on success, 1 on failure). To run Phase 1 with a
   different questionnaire, pass `--input <basename>` on the
   COMPLETE-state re-run.

`paths.base_dir` is set to the container (`<target>`), **not**
to `.DCOM_AI/DID_Toolkit_PRJ/` itself — that keeps every
`paths.*` mirror template resolving against the same anchor it
would in the flat layout (`<base_dir>/<project_root>/rb/as/...`).

### Two run modes

| Mode | Behaviour |
|---|---|
| **TTY (real terminal)** | Prompts for `name` / `customer_name` / `project_root`. Detected Bosch-tree pair pre-fills the last two — Enter to accept. |
| **Non-TTY (agent / CI)** | **Exits 4** if `--name` is missing, or if `--customer-name` / `--project-root` are missing AND no Bosch tree was detected. There is no silent-placeholder fallback — CI pipelines must supply the values explicitly so they never ship `Fe_Super` / `rbcn` literals into real workspaces. |

```bash
# Non-TTY happy path with a Bosch tree present
python scripts/pipeline.py --init-project /path/to/ws --name MyProj

# Non-TTY happy path without a Bosch tree (full overrides required)
python scripts/pipeline.py --init-project /path/to/ws \
    --name MyProj --customer-name rbcn --project-root Fe_Super

# Force non-interactive even on a TTY (CI on Windows where
# isatty() can mis-report subprocess.DEVNULL stdin)
python scripts/pipeline.py --init-project /path/to/ws --non-interactive --name MyProj
```

`--name` / `--customer-name` / `--project-root` are consumed at
build time to materialise `paths.*` literal segments; they are
**not** persisted as standalone fields in `project.json` (see the
rejected-legacy-fields list in
[`configuration.md`](configuration.md)).

**Refuses to overwrite** an existing
`.DCOM_AI/DID_Toolkit_PRJ/config/project.json` (exit code 1) so
a re-run can never clobber operator edits. Operators on an older
layout must follow the
[migration recipe above](#migrating-from-an-older-layout)
instead of re-running `--init-project`.

After init, just `cd` into the workspace and run any phase — no
flags needed; the controller auto-discovers the workspace via
the CWD walk.

```bash
cd /path/to/my-bosch-project
python /path/to/skill/scripts/pipeline.py --phase fscs
```

---

## 3. Multiple configs per workspace — `--config` / `--list-configs`

A single workspace may host several sibling configs for
multi-product / multi-customer flows:

```
my-bosch-project/                              ← project container
└── .DCOM_AI/                                  ← AI-tooling umbrella
    └── DID_Toolkit_PRJ/                       ← workspace
        ├── config/
        │   ├── project.json                   ← default
        │   ├── project.dpb.json               ← DPB-specific overrides
        │   └── project.esp.json               ← ESP-specific overrides
        ├── inputs/
        ├── outputs/
        ├── scripts/
        └── state/
```

Selection follows the standard multi-input contract:

| Situation | Behaviour |
|---|---|
| `--config <path>` (workspace-relative / bare filename / absolute) | Explicit win. `--config project.dpb.json` and `--config config/project.dpb.json` and `--config /abs/path/...` all resolve to the same file. |
| Single config in `config/` | Auto-selects silently. |
| Multiple configs **+ TTY** | Interactive numbered menu. Pick by index or by tag (`dpb` / `esp`). |
| Multiple configs **+ non-TTY (agent)** | **Exits 4**, writes TAG-and-PATH list to stderr. Agent contract: enumerate via `--list-configs`, render plain-text menu, stop the turn for operator's pick, re-invoke with `--config <chosen>`. Identical contract to `--list-inputs`. |

`--list-configs` prints one `TAG<TAB>RELATIVE-PATH` line per
discovered config (sorted), exit 0 on empty workspace.

**Tag derivation.** The tag is the segment between `project.`
and `.json` in the filename: `project.dpb.json` → `dpb`;
`project.json` → empty tag (default).

---

## 4. `config/project.json` schema

Validated by `scripts/config/schema.py` (Pydantic v2). Strict —
unknown keys raise `extra='forbid'` for early typo detection, and
the `schema_version` validator only accepts the current string.
Operators on a prior shape regenerate via `--init-project`.

```jsonc
{
  "schema_version": "2.2",

  "paths": {
    "base_dir":          "/abs/path/to/my-bosch-project",

    // Phase 3 mirror targets (left "" when no Bosch tree was
    // detected at --init-project time; mirror disabled silently).
    "pdm_file":          "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/RBDCOM_Customer.pdm",
    "config_h":          "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/api/RBAPLCUST_Config.h",
    "config_elements_h": "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/api/RBAPLCUST_ConfigElements.h",
    "config_settings_h": "Fe_Super/rb/as/rbcn/{product_type_lower}/dcompr/cfg/RBDCOM_ConfigSettings.h",
    "c_output_subdir":   "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/src/{product_type_upper}",

    // Phase 2 mirror target (same gating).
    "arxml_file":        "Fe_Super/rb/as/rbcn/core/app/dcom/RBAPLCust/cfg/{product_type_upper}/Dcm_CusDiag_Services_EcucValues_{product_type_suffix}.arxml",

    // Basename of the questionnaire chosen at the
    // QUESTIONNAIRE_READY transition of --init-project. Empty
    // string means "no questionnaire recorded yet" (workspace
    // never advanced past FOLDERS_ONLY). The COMPLETE-state
    // auto-chain feeds this filename to Phase 1.
    "input_did_json":    "acme_did.json",

    // Per-product override + skip block (auto-populated by
    // --init-project from a live tree scan; safe to hand-edit).
    "per_product": {
      "ESPCL":  { "arxml_file":        null },                                 // tree never has cfg/ESPCL/
      "Common": { "config_settings_h": null },                                 // tree never has Common/dcompr/
      "IPB":    { "config_settings_h": "Fe_Super/rb/as/rbcn/ipb/dcompr/cfg/RBDCOM_ConfigSettings_IPB.h" }
    }
  },

  // options block is empty by design. The class is kept with
  // extra='forbid' so stale knobs (output_mode, backup_*, etc.)
  // fail loud at load.
  "options": {}
}
```

Path placeholders `{product_type_upper}` /
`{product_type_lower}` / `{product_type}` /
`{product_type_suffix}` are substituted at resolve-time, **once
per product in the work-set** that Phase 2 / Phase 3 derive from
`fscs.json`. One `project.json` therefore drives every product
the operator tagged in `fscs_edit.xlsx::Product_Type` —
`--init-project` is run once, adding new products is an xlsx edit,
not a config change. `paths.per_product` overrides each
individual (PT, key) on top of the templates above (`null` skips
that artefact, a non-empty string overrides the template path).
Full field-level reference, placeholder semantics (including the
`Common`-special-case for `{product_type_suffix}`), the
`per_product` three-value semantics table, and the rejected
legacy fields list: [`configuration.md`](configuration.md).

---

## 5. Common pitfalls

| Symptom | Cause / fix |
|---|---|
| Phases write to the wrong `outputs/` | CWD walk landed on a different ancestor's `.DCOM_AI/DID_Toolkit_PRJ/config/project.json`. Use `--project-root` or `$DID_TOOLKIT_PROJECT_ROOT` to force the right one. |
| Pipeline can't find the workspace on an older layout | Flat / single-level layouts are not recognised; follow the [migration recipe](#migrating-from-an-older-layout) (mkdir `.DCOM_AI/DID_Toolkit_PRJ/`, move `config/` / `inputs/` / `outputs/` / `state/` into it). |
| `--init-project` exits 1 with "refusing to overwrite" | A `.DCOM_AI/DID_Toolkit_PRJ/config/project.json` already exists at the target. Move/delete it explicitly if you really want to start over — the scaffolder will never silently destroy operator edits. |
| `--init-project` exits 4 in non-TTY | Missing `--name`, or missing `--customer-name` / `--project-root` when no Bosch tree is detected. Fail-loud by design; supply the flags or run interactively. |
| `extra_forbidden` `ValidationError` on legacy fields | The config carries one of the rejected legacy fields (any of `project.*`, `product_type_mapping`, `paths.project_root`, legacy `options.*`). No migration shim — regenerate via `--init-project` and hand-copy custom `paths.*` values. |
| `--init-project` reports "multiple Bosch tree candidates" | Workspace contains more than one `<X>/rb/as/.../RBAPLCust`. Pass `--project-root <NAME>` and `--customer-name <NAME>` (or both) to disambiguate. |
| Multiple configs but `--phase X` runs without `--config` and exits 4 | Agent contract — call `--list-configs`, present the candidates to the operator, re-invoke with `--config <chosen>`. |
