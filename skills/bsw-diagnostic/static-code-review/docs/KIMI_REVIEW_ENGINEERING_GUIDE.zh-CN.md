# Kimi Review 工程落地指南

本文档定义当前工作区中 Kimi Review 的工程化落地方式。目标不是把 Kimi 当作最终判官，而是把它变成一条可执行、可校验、可归档的辅助评审流水线。

## 目标

这套方案解决以下问题：

1. Bundle 输入过长，模型容易被 workflow 和 guideline 噪声带偏。
2. 报告生成失败时容易留下空文件或半成品。
3. Markdown 与 HTML 的结构不稳定，难以接到 CI 或团队流程里。
4. 外部模型的 finding 结论不应直接成为工程门禁。

## 落地原则

1. Kimi 只负责辅助评审与报告生成。
2. 最终 finding 是否接受，仍由人工或确定性规则决定。
3. 流程只对“生成成功”和“格式完整”做自动校验。
4. 生成失败时不得覆盖已有有效报告。
5. 所有输出都必须可追踪、可复核、可重新执行。

## 工作流

## 推荐模式

现在有两条使用路径：

1. 全自动模式：配置好 Kimi API 后，工程师只需对当前文件执行一次 `Run From Project Skill`。
2. 低手工模式：如果暂时没有 API，就用 `Prepare To Clipboard` 和 `Import From Clipboard`，避免手工保存大段 prompt 和长回复。
3. 无 key 自动模式：使用 `Run Via Kimi Web`，本地脚本自动读取项目 skill、驱动已登录的 Kimi 网页、抓取回复并导入报告。

推荐优先使用全自动模式。

现在统一入口 `run` 也支持自动分流：

1. 如果检测到 `KIMI_API_KEY` 或 `MOONSHOT_API_KEY`，自动走 API 模式。
2. 如果未检测到 key，但 `webAutomation.enabled=true`，自动走 Kimi Web 自动化模式。

### 全自动模式

使用脚本：

`py -3 tools/kimi_review_pipeline.py run --source <source-file>`

它会自动完成：

1. 生成紧凑 bundle。
2. 自动读取项目中的 skill 文件和选定 guideline 文件。
3. 调用 Kimi API。
3. 仅在显式指定输出路径时保存原始响应。
4. 导入 Markdown 与 HTML 代码块，并归一化为正式 HTML 报告。
5. 做结构校验与源码新旧校验。
6. 更新 `.status.json` 和 `.meta.json`。

这里的“自动读取 project skill”指的是本地脚本读取仓库中的 [SKILL.md](skills/static-code-review-workflow/SKILL.md) 和选定 guideline 文件，再通过 API 发给 Kimi；不是 Kimi 客户端自己扫描本地工作区。

前置条件：

1. 设置 `KIMI_API_KEY` 或 `MOONSHOT_API_KEY`。
2. 网络可访问 Kimi 接口。

可选环境变量：

1. `KIMI_BASE_URL` 或 `MOONSHOT_BASE_URL`
2. `KIMI_MODEL` 或 `MOONSHOT_MODEL`

Windows 下也可以直接执行：

`powershell -ExecutionPolicy Bypass -File tools/kimi_review.ps1 -Action Run -Source <source-file>`

### 低手工模式

如果暂时不能直连 API，就使用：

1. `powershell -ExecutionPolicy Bypass -File tools/kimi_review.ps1 -Action PrepareClipboard -Source <source-file>`
2. 把内容粘贴给 Kimi
3. 复制 Kimi 返回结果
4. `powershell -ExecutionPolicy Bypass -File tools/kimi_review.ps1 -Action ImportClipboard -Source <source-file>`

这条路径不再需要人工维护长 prompt 文件，也不需要手工新建 response 文件。

### 无 key 自动模式

使用脚本：

`py -3 tools/kimi_review_pipeline.py run-web --source <source-file>`

它会自动完成：

1. 读取项目中的 [SKILL.md](skills/static-code-review-workflow/SKILL.md) 和选定 guideline 文件。
2. 生成一个给 Kimi 使用的本地 `skill pack` 文件。
3. 打开已登录的 Kimi 网页会话。
4. 自动上传 `skill pack` 和源码文件。
5. 自动发送固定短提示词。
6. 自动抓取 Kimi 最终回复。
7. 自动导入 Markdown 与 HTML 代码块，校验后落盘正式 HTML 报告。
8. 自动执行 gate 校验。

前置条件：

1. 本机可访问 Kimi 网页。
2. 已经在浏览器中登录 Kimi。
3. 已在 `automation/` 目录执行 `npm install` 安装 Playwright 依赖。

这条路径不需要 API key，也不需要剪贴板粘贴长 prompt。

Windows 下也可以直接执行：

`powershell -ExecutionPolicy Bypass -File tools/kimi_review.ps1 -Action RunWeb -Source <source-file>`

### 1. 生成 Bundle

使用脚本：

`py -3 tools/kimi_review_pipeline.py prepare --source <source-file>`

它会生成一个收紧后的 Kimi bundle，默认输出到：

`<source-file>.file-review-to-report.kimi-input.latest.md`

这个 bundle 与此前的手工版本不同：

1. 只保留紧凑评审规则。
2. 明确声明只评审 `Review Input` 里的代码。
3. 默认限制 confirmed findings 的数量。
4. 不再把整套 workflow 和 guideline 正文都塞进评审上下文。

### 2. 发送给 Kimi

把生成的 bundle 内容发送给 Kimi，并获取返回结果。

要求 Kimi 返回：

1. `Review Result`
2. `Markdown Report` 代码块
3. `English HTML Report` 代码块
4. `Chinese HTML Report` 代码块

如果你想保留 Kimi 的完整返回结果，可以显式保存为本地 markdown 文件，例如：

`review-reports/kimi-response.current-file.md`

### 3. 导入 Kimi 结果

使用脚本：

`py -3 tools/kimi_review_pipeline.py import --response <kimi-response-file>`

推荐同时传入被评审源码：

`py -3 tools/kimi_review_pipeline.py import --response <kimi-response-file> --source <source-file>`

导入步骤会做这些事情：

1. 提取 `Markdown Report`、`English HTML Report` 和 `Chinese HTML Report` 代码块。
2. 校验 Markdown 是否包含固定 section。
3. 校验 Summary 计数是否与 finding 数量一致。
4. 分别校验英文 HTML 与中文 HTML 是否包含固定 section 和标题元信息。
5. 先把 `review-reports/` 根目录里现有正式报告统一归档到 `archive/`。
6. 原子写入 `.html`、`.zh-CN.html`；旧的 `.md` 正式报告如果存在，也会在归档时一并移动。
7. 只有全部校验通过时才覆盖正式报告。

默认落盘路径：

1. `review-reports/static-code-review-report.current-file.<timestamp>.html`
2. `review-reports/static-code-review-report.current-file.<timestamp>.zh-CN.html`

默认不会在项目内写入运行时临时产物。

只有在显式传入 `--response-output` 或 `--skill-pack-output` 时，才会把原始响应或 skill pack 持久化到你指定的位置。

### 4. 校验已有报告

使用脚本：

`py -3 tools/kimi_review_pipeline.py validate`

如果要避免“代码已经改了但旧报告仍然通过”的情况，推荐带上源码路径：

`py -3 tools/kimi_review_pipeline.py validate --source <source-file>`

它会检查：

1. 正式 HTML 文件存在且非空。
2. 导入阶段已完成 Markdown 结构校验，校验命令会继续检查 HTML 标题、section 和 summary 信息是否完整。
3. 校验结果输出到终端（JSON），不生成额外状态文件。

如果失败，会输出非零退出码。

## VS Code 入口

当前工作区默认提供这些任务：

1. `Static Code Review Setup`
2. `Static Code Review Current File`
3. `Static Code Review Selected Function`
4. `Static Code Review Archive Current Reports`
5. `Static Code Review Current File: Run Web Review`
6. `Static Code Review Current File: Validate Report`
7. `Static Code Review Current File: Gate Report`
8. `Static Code Review Selected Function: Run Web Review`
9. `Static Code Review Selected Function: Validate Report`
10. `Static Code Review Selected Function: Gate Report`

定义见 [.vscode/tasks.json](.vscode/tasks.json)

## 状态输出

脚本会把导入/校验/gate 的状态以 JSON 打印到终端标准输出（失败时写入标准错误），用于本地脚本或 CI 解析。

## 团队使用建议

### 开发阶段

1. 开发者对当前文件运行 `Prepare Bundle`。
2. 将 bundle 发给 Kimi。
3. 将返回结果保存到本地并运行 `Import Response`。
4. 在本地查看正式 HTML 报告。

### 提交前

1. 对变更文件重复执行以上流程。
2. 只把生成成功、格式完整作为通过条件。
3. 不把 Kimi 的 finding 直接当成强制门禁。

### CI 或软门禁阶段

推荐直接执行：

`py -3 tools/kimi_review_pipeline.py gate --report-dir review-reports --report-base static-code-review-report.current-file`

推荐在真实流程中始终带上源码路径：

`py -3 tools/kimi_review_pipeline.py gate --report-dir review-reports --report-base static-code-review-report.current-file --source <source-file>`

在 Windows PowerShell 或常见 Windows CI 环境里，也可以直接执行：

`powershell -ExecutionPolicy Bypass -File tools/kimi_review.ps1 -Action Gate -Source <source-file>`

CI 只做这些检查：

1. `.status.json` 为成功状态。
2. 正式 HTML 报告存在且非空。
3. 报告结构完整。

`gate` 命令会：

1. 重新校验正式 HTML 报告；Markdown 结构检查在导入阶段完成。
2. 如果提供了 `--source`，还会检查源码是否比报告更新。
3. 成功时输出 `gate_passed` 并返回退出码 0。
4. 失败时输出 `gate_failed` 并返回非零退出码。
5. 不根据 finding 数量或级别判断，只根据报告存在性、结构完整性和源码新旧关系判断。

CI 不做这些事情：

1. 不根据 finding 数量直接阻塞合并。
2. 不把 major 或 critical 自动转成硬门禁。
3. 不把 Kimi 输出视为最终真相。

## 仍需遵守的边界

1. 如果代码不能外发到外部模型，这套方案不能直接用于真实业务源码。
2. 如果需要硬门禁，应使用确定性静态分析工具。
3. 如果 Kimi 返回格式不符合约定，导入阶段会失败，不会写入正式报告。

## 相关文件

1. [tools/kimi_review_pipeline.py](tools/kimi_review_pipeline.py)
2. [tools/kimi_review.ps1](tools/kimi_review.ps1)
3. [tools/kimi-review.config.json](tools/kimi-review.config.json)
4. [.vscode/tasks.json](.vscode/tasks.json)
5. [review-reports](review-reports)
6. [../automation/package.json](../automation/package.json)
7. [../automation/kimi_web_automation.mjs](../automation/kimi_web_automation.mjs)