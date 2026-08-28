# static-code-review

A portable static code review workflow for C/C++ projects using Cline (VS Code) and Kimi.  
基于 Cline + Kimi 的嵌入式 C/C++ 静态代码审查便携工作流。

---

## Quick Start / 快速开始

### 1. Install / 安装

Copy the `static-code-review/` folder to your project root, then run:

将 `static-code-review/` 文件夹复制到项目根目录，然后运行：

```cmd
static-code-review\review-install.cmd
```

Or double-click `review-install.cmd` in File Explorer.

或者在文件资源管理器中直接双击 `review-install.cmd`。

This installs:

安装完成后，项目根目录会自动生成：

- `.clinerules` —— Cline project instruction file / Cline 项目指令文件
- `.vscode/tasks.json` —— VS Code tasks for review workflow / 审查工作流任务

### 2. Review Current File / 审查当前文件

Open a `.c` file in VS Code, then run the task:

在 VS Code 中打开要审查的 `.c` 文件，然后运行任务：

```
Static Code Review Current File
```

### 3. Review Selected Function / 审查选中函数

Select a function in the editor, then run:

在编辑器中选中目标函数，然后运行：

```
Static Code Review Selected Function
```

### 4. Reports / 报告

Formal HTML reports are written to `review-reports/` automatically:

正式 HTML 报告会自动生成到 `review-reports/`：

```
review-reports/static-code-review-report.current-file.<scope>.<timestamp>.html
review-reports/static-code-review-report.current-file.<scope>.<timestamp>.zh-CN.html
```

Previous reports are archived to `review-reports/archive/` before new ones are written.

写入新报告前，旧报告会自动归档到 `review-reports/archive/`。

---

## What This Does / 功能概述

- **Dual-pass review / 双通道审查**
  - Pass A: Rule-based check against project coding guidelines and emits concrete rule hits / 基于项目编码规则的规则审查，输出具体命中项及代码位置
  - Pass B: Independent AI reasoning on behavior impact / AI 独立推理审查
  - Fusion: Merge results and assign final severity. Rule-proven `major`/`critical` findings are locked unless the code satisfies an explicit rule exception. / 融合两轮结果，确定最终严重级别；规则命中的主要/严重问题除非满足规则自身的显式例外条款，否则不得省略或降级

- **Rule Coverage / 规则覆盖声明**
  - Every Markdown report lists the guideline categories applied, which major/critical rules were triggered, and which categories were evaluated but did not trigger. / 每份 Markdown 报告列出应用的规则类别、已触发的 major/critical 规则以及已评估但未触发的主要/严重规则类别

- **Fusion policy / 融合策略**

  | Situation / 情况 | Fusion outcome / 处理 |
  |---|---|
  | A hits major/critical, B confirms / A 命中 major/critical，B 确认 | Keep as confirmed finding / 保留为 confirmed finding |
  | A hits major/critical, B is silent / A 命中 major/critical，B 沉默 | Keep, because the rule already proves it / 保留，因为规则已证明 |
  | A hits major/critical, B argues "not a bug" / A 命中 major/critical，B 辩称“不是 bug” | Downgrade or remove only if B cites an explicit exception clause from the rule and the code satisfies it; otherwise keep / 只有 B 能引用规则的显式例外条款且代码满足该例外时，才能降级或删除；否则保留 |
  | A misses, B finds a behavior defect / A 未命中，B 发现行为缺陷 | Add as supplementary finding, severity from B / 作为补充 finding，按 B 的严重性定级 |
  | A and B point to the same root cause / A 和 B 都指向同一根因 | Merge into one finding / 合并为 1 条，避免扩写 |


- **Auto-generated bilingual reports / 自动生成双语报告**
  - English and Chinese HTML reports in one run / 一次运行同时输出英文和中文 HTML 报告

- **Archive and traceability / 归档与可追溯**
  - Reports are timestamped, archived, and ready for CI gating / 报告带时间戳，支持归档，可对接 CI gate

---

## Directory Structure / 目录结构

```
static-code-review/
├── README.html              # HTML documentation entry point / HTML 文档入口
├── README.md                # This file / 本文件
├── review-install.cmd       # One-click installer / 一键安装脚本
├── .vscode/
│   └── tasks.json           # VS Code tasks (auto-installed to project root) / VS Code 任务（会自动安装到项目根目录）
├── docs/
│   ├── USAGE.zh-CN.html     # Chinese usage guide / 中文使用文档
│   ├── USAGE.en.html        # English usage guide / 英文使用文档
│   ├── DESIGN.zh-CN.html    # Chinese design doc / 中文设计文档
│   ├── DESIGN.en.html       # English design doc / 英文设计文档
│   ├── ROLLOUT_MESSAGE.zh-CN.md  # Rollout announcement / 推广文案
│   ├── DELIVERY.zh-CN.md    # Delivery checklist / 交付清单
│   └── ...
├── skills/
│   └── static-code-review-workflow/
│       ├── SKILL.md                         # Core review workflow skill / 核心审查工作流技能文件
│       ├── guidelines/
│       │   ├── general_coding_rules.md      # General coding rules / 通用编码规则
│       │   ├── arithmetic_coding_rules.md   # Arithmetic rules / 算术规则
│       │   ├── c_coding_rules.md            # C-specific rules / C 语言规则
│       │   └── cpp_coding_rules.md          # C++-specific rules / C++ 语言规则
│       └── references/
│           ├── report-templates.md          # Report templates / 报告模板
│           ├── report-output.md             # Output naming rules / 输出命名规则
│           └── severity-policy.md           # Severity grading policy / 严重级别策略
├── tools/
│   ├── install_cline_integration.ps1   # PowerShell installer / PowerShell 安装脚本
│   ├── archive_review_reports.ps1      # Report archive script / 报告归档脚本
│   ├── kimi_review.ps1                 # PowerShell entry point / PowerShell 入口
│   └── kimi_review_pipeline.py         # Python pipeline engine / Python 流水线引擎
├── templates/
│   └── clinerules.template             # Template for .clinerules / .clinerules 模板
└── automation/
    ├── package.json                    # Playwright dependencies / Playwright 依赖
    └── kimi_web_automation.mjs         # Kimi web automation script / Kimi 网页自动化脚本
```

---

## Trigger Prompts / 触发提示词

Short chat prompts that trigger the review workflow:

以下简短提示词可以在 Cline Chat 中触发审查工作流：

- `Review current file.`
- `Review selected function.`
- `Review current selection.`
- `Review function <function-name>.`
- `Static Code Review Function <function-name>.`

---

## Prerequisites / 前置条件

- Windows OS (PowerShell + Python 3 + Node.js/npm for web automation)
- VS Code with Cline extension installed
- Kimi API key configured in `%USERPROFILE%/.static-code-review/config.json` (for API path)

---

## License / 许可

This is an internal engineering workflow bundle.  
本工程工作流仅供内部使用。
