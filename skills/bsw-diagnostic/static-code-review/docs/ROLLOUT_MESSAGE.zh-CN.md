# static-code-review rollout 文案

各位工程师，`static-code-review/` 便携包已经可用，直接放到项目根目录即可。

首次使用：

1. 先在 VS Code 中打开**项目根目录**（`static-code-review/` 所在的上一层文件夹）
2. 打开 `static-code-review` 文件夹，双击运行 `review-install.cmd`

日常使用：

1. 打开当前要审查的 `.c` 文件
2. 当前文件 review：运行 VS Code 任务 `Static Code Review Current File`
3. 函数级 review：先选中目标函数，再运行 VS Code 任务 `Static Code Review Selected Function`

报告会自动生成到 `review-reports/`。

默认流程会自动归档上一轮正式报告，不需要手动清理旧报告；当前文件、单函数、选中函数共用这一行为。

中文说明看 `static-code-review/docs/USAGE.zh-CN.html`，英文说明看 `static-code-review/docs/USAGE.en.html`。
