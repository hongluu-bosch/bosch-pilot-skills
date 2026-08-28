# Bosch Pilot Skills

Agent Skills for Bosch Pilot -- AI-assisted development for automotive and embedded software.

## Installing

Clone this repo and copy the skill folders into the Bosch Pilot skills directory:

```bash
git clone https://github.boschdevcloud.com/LOU8HC/bosch-pilot-skills.git
cp -r bosch-pilot-skills/skills/* ~/.bosch-pilot/skills/
```

## Skills

Skills are contextual and auto-loaded based on your conversation. When a skill matches your task, Bosch Pilot reads its `SKILL.md` and loads relevant references.

| Skill | Description |
|-------|-------------|
| **bsw-diagnostic** | Collection of AUTOSAR diagnostic configuration toolkits for Bosch BSW projects -- DID, DiagComm, UDS 0x19/0x31 services, DTC analysis, code review, and ALM/DOORS workflow integration |
| **cline-sdk** | Build AI agents with the Cline SDK -- Agent runtime, ClineCore sessions, custom tools, plugins, events, LLM providers, scheduling, multi-agent teams, and production deployment |
| **create-pull-request** | Create well-structured GitHub pull requests following project conventions -- commit analysis, branch management, PR templates, and `gh` CLI |
| **diagram-design** | Create branded architecture, flowchart, sequence, state machine, ER, timeline, swimlane, Gantt, and 20+ other diagram types as self-contained HTML/SVG/PNG with editorial design system |
| **opentui** | Build terminal user interfaces with OpenTUI -- imperative core API, React reconciler, and Solid reconciler. Components, layout, keyboard handling, animations, and testing |

## Repository Layout

```
skills/
├── bsw_diagnostic/          # AUTOSAR diagnostic toolkits
│   ├── did-toolkit/         #   DID configuration generator
│   ├── diagcomm-toolkit/    #   DiagComm parameter writer
│   ├── 19service-toolkit/   #   UDS 0x19 (Read DTC) config
│   ├── 31service-toolkit/   #   UDS 0x31 (Routine Control) config
│   ├── diagnosisnrcanalysis/ #   Negative Response Code analysis
│   ├── diagnosisroutineanalysis/ # Routine diagnostic analysis
│   ├── dem-pdm-size-sync/   #   DEM/PDM size synchronization
│   ├── ai-ut/               #   Unit test coverage assistant
│   ├── static-code-review/  #   Static code review workflow
│   ├── alm-workitem-read-write/ # ALM workitem read/write
│   └── doors-upload-workflow/   # DOORS upload automation
├── cline-sdk/              # Cline SDK agent development
│   ├── SKILL.md
│   └── references/
├── create-pull-request/    # GitHub PR automation
│   └── SKILL.md
├── diagram-design/         # Visual diagram creation
│   ├── SKILL.md
│   ├── assets/
│   ├── references/
│   └── scripts/
└── opentui/               # Terminal UI development
    ├── SKILL.md
    └── references/
```

## Contributing

Open a PR. New skills must follow the Agent Skills spec: a `SKILL.md` at the skill directory root with frontmatter `name` and `description`, plus any supporting reference files.

## License

Apache 2.0