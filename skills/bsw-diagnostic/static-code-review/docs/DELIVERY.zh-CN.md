# static-code-review 交付目录说明

这份便携包对外交付时，建议只让工程师关注下面几个入口。

## 工程师真正要看的文件

1. `README.html`

   便携包统一首页。第一次打开时，先从这里进入。

2. `docs/USAGE.zh-CN.html`

   中文使用文档。默认推荐普通工程师先看这个。

3. `docs/USAGE.en.html`

   英文使用文档。给非中文读者使用。

## 维护者需要知道的文件

1. `docs/DESIGN.zh-CN.html`

   中文设计文档，说明整体架构和工作流。

2. `docs/DESIGN.en.html`

   英文设计文档。

3. `docs/KIMI_REVIEW_ENGINEERING_GUIDE.zh-CN.md`

   工程维护说明，面向维护者和集成者。

## 交付时不需要额外解释的目录

1. `.github/`

   内部规则与技能资产目录，不需要普通工程师理解。

2. `automation/`

   网页自动化相关依赖和脚本目录，不是普通使用入口。

3. `tools/`

   核心脚本目录，面向维护者，不面向普通工程师。

4. `templates/`

   模板目录，普通工程师无需关注。

5. `examples/`

   示例目录，普通工程师无需关注。

## 对外说明建议

如果是发给普通工程师，建议只强调下面三点：

1. 先打开 `README.html`。
2. 第一次使用先在 VS Code 中打开 `static-code-review/` 文件夹，再执行 `Static Code Review Setup`。
3. 打开当前 `.c` 文件后，运行任务 `Static Code Review Current File`。

## rollout 前的维护提示

1. `Static Code Review Setup` 现在会先备份已有 `.clinerules` 和 `.vscode/tasks.json`。
2. 对 `.vscode/tasks.json` 会按任务名合并；对 `.clinerules` 会以托管块方式写入，尽量保留项目原有内容。