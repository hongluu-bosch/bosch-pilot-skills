# DOORS Upload & Read Workflow Skill

这个 skill 用于标准化 DOORS MCP 相关流程，覆盖四类常用操作：

1. 使用 `scripts/doors_get_tool.py` 读取 DOORS 模块内容。
2. 使用 `scripts/doors_refresh_tool.py` 刷新 DOORS 模块。
3. 使用 `scripts/fix_upload_file.py` 和 `scripts/doors_upload_tool.py` 完成 Excel 修复与上传。
4. 使用 `scripts/doors_update_links_tool.py` 上传 DOORS links Excel。

## 目录结构

- `SKILL.md`：给 Agent 的操作规则与触发说明。
- `scripts/doors_get_tool.py`：调用 MCP 读取模块内容。
- `scripts/doors_refresh_tool.py`：调用 MCP 刷新模块内容。
- `scripts/fix_upload_file.py`：修复上传文件格式。
- `scripts/doors_upload_tool.py`：调用 MCP 上传文件。
- `scripts/doors_update_links_tool.py`：调用 MCP 更新 DOORS links。

## 快速开始

### 运行依赖

推荐使用 Anaconda `MyBaseEnv` 中的 `python.exe` 解释器，例如：

script运行使用python.exe解释器
例如
```powershell
C:\Users\CIZ1CGD4\.conda\envs\MyBaseEnv\python.exe
```

如果当前 shell 中的 `python` 已指向可用环境，也可以直接使用 `python` 调用脚本。

### 1) 读取模块

```powershell
& "C:\...\python.exe" ".\.agents\skills\doors-upload-workflow\scripts\doors_get_tool.py" "<module_uuid>"
```

默认输出：

```text
output/doors_module_<module_uuid>.json
```

### 2) 刷新模块

```powershell
& "C:\...\python.exe" ".\.agents\skills\doors-upload-workflow\scripts\doors_refresh_tool.py" "<module_uuid>"
```

可选保存返回结果：

```powershell
& "C:\...\python.exe" ".\.agents\skills\doors-upload-workflow\scripts\doors_refresh_tool.py" "<module_uuid>" --user-nt CIZ1CGD4 --out "output\refresh_result.json"
```

成功特征：

- 控制台出现 `[SUCCESS] Refresh completed successfully.`
- 返回 `code == 0`

如果返回 `HTTPConnectionPool(...): Read timed out`，表示 MCP 已收到请求，但 DOORS 后端服务超时，通常需要稍后重试或确认服务端状态。

### 3) 修复上传文件（如果文件被手动修改过）

将 `<input.xlsx>` 替换为用户实际要上传的 Excel 文件路径，修复后的文件建议输出为 `*_FIXED.xlsx`。

```powershell
& "C:\...\python.exe" ".\.agents\skills\doors-upload-workflow\scripts\fix_upload_file.py" "<input.xlsx>" "<input_FIXED.xlsx>"
```

### 4) 上传 Excel

优先使用 `--prompt-password`，避免密码进入命令历史：

```powershell
& "C:\...\python.exe" ".\.agents\skills\doors-upload-workflow\scripts\doors_upload_tool.py" "<input_FIXED.xlsx>" "1-3a1288eb3f4712b8-M-3e54f001d7539" "<username>" --prompt-password
```

也可以通过环境变量传入密码：

```powershell
& "C:\...\python.exe" ".\.agents\skills\doors-upload-workflow\scripts\doors_upload_tool.py" "<input_FIXED.xlsx>" "1-3a1288eb3f4712b8-M-3e54f001d7539" "<username>" --password-env DOORS_PASSWORD
```

### 5) 上传 DOORS Links Excel

默认使用 `links-batch` 作为 links 更新批次；如服务端要求指定模块或批次，可追加 `--module-uuid <module_uuid>`。

```powershell
& "C:\...\python.exe" ".\.agents\skills\doors-upload-workflow\scripts\doors_update_links_tool.py" ".\doors_test\links.xlsx" "<username>" --prompt-password
```

## 注意事项

- 不要在日志或截图中暴露明文密码，优先使用 `--prompt-password` 或 `--password-env`。
- 读取和刷新只需要 `module_uuid`；上传 Excel 需要 `module_uuid`、NT 账号和密码；更新 links 需要 links Excel、NT 账号和密码。
- 如果文件是 DOORS 刚导出且未编辑，可尝试直接上传。
- 若报格式错误、解析失败或超时，优先走“修复 -> 上传”链路。

## 备注（手动编辑 Excel 时）

- 如果你在表中手动插入/调整某条记录（例如围绕 ID `541` 的行），需要同步检查以下字段：
  - 首行元数据中的 `sizeRow`（总行数）是否已更新；
  - 数据区 `Absolute Number` 是否与目标记录编号一致（例如应为 `541`）。
- 若这些值未同步，`upload_doors_module` 可能报格式异常或上传后数据错位。
- 不确定时，先执行 `scripts/fix_upload_file.py` 再上传，避免人工修改导致的隐性结构问题。
