# Workspace model

The skill is install-once / use-everywhere. The skill folder holds only
code and documentation; each real project keeps its own workspace under
`.DCOM_AI/19Service_Toolkit_PRJ/`.

## Layout

```
my-bosch-project/                              ← project container
├── rb/as/<customer>/...                       ← Bosch BSW tree
└── .DCOM_AI/
    └── 19Service_Toolkit_PRJ/                 ← this skill's workspace
        ├── config/project.json
        ├── inputs/                            ← diagnostic questionnaires
        ├── outputs/                           ← FSCS, ARXML reports, DOORS
        ├── scripts/                           ← optional per-project extractors
        └── state/                             ← DOORS upload state
```

## Project-root resolution

The current working directory (CWD) is the project root. It must contain a
Bosch project tree detected as either `<platform>/rb/as/` or the legacy
`rb/as/` layout. There is no CLI override, no environment-variable override,
and no fallback to the skill install directory.

The resolved path is the **workspace** path (`.DCOM_AI/19Service_Toolkit_PRJ/`);
`paths.base_dir` inside `config/project.json` points at the project
container so ARXML paths resolve against the Bosch tree.

## `--init-project` state machine

1. **FRESH → FOLDERS_ONLY**: from the project root, scaffolds workspace,
   copies templates, exits with `[AGENT STOP]` and asks for a questionnaire in
   `inputs/`.
2. **FOLDERS_ONLY → QUESTIONNAIRE_READY**: detects `.xlsx`, stops and asks
   the operator for `Product_Type` if it was not supplied in the operator
   prompt, scans the Bosch tree, writes `config/project.json`, exits with
   `[AGENT STOP]`.
3. **COMPLETE**: subsequent runs auto-chain into Phase 1.

`--init-project` refuses to overwrite an existing `config/project.json`.
