---
name: doors-upload-workflow
description: 使用 DOORS MCP 脚本读取、刷新、修复、上传 DOORS 模块和更新 DOORS links。用户提到 DOORS 上传/读取/刷新、读 DOORS module UUID、更新 links、`upload_doors_module`、`get_doors_module`、`refresh_doors_module`、`update_doors_links`、`doors_upload_tool.py`、`doors_get_tool.py`、`doors_refresh_tool.py`、`doors_update_links_tool.py`、`fix_upload_file.py`、DOORS Excel 格式损坏、WPS/Excel 保存后无法上传、"上传失败"、"格式问题"、"先修复再上传"时，必须使用本技能。
---

# DOORS Upload & Read Workflow

本 skill 负责通过 DOORS MCP（`http://10.54.7.36:8000/mcp`）完成四类工作：

1. 读取一个 DOORS 模块（`get_doors_module`）—— 把模块属性 + 行内容拉到本地 JSON。
2. 刷新一个 DOORS 模块（`refresh_doors_module`）—— 触发 DOORS 端重新刷新模块数据。
3. 把 Excel 上传/更新到一个 DOORS 模块（`upload_doors_module`）——
   - 必要时先用 `fix_upload_file.py` 修复被 Excel/WPS 重新保存后破坏的底层格式。
   - 再用 `doors_upload_tool.py` 调用 `upload_doors_module` 完成上传。
4. 上传 DOORS links Excel（`update_doors_links`）—— 调用 MCP 更新 link 关系。

本 skill 已内置可复用脚本（团队共享）：

- `scripts/doors_get_tool.py` —— 读取 DOORS 模块
- `scripts/doors_refresh_tool.py` —— 刷新 DOORS 模块
- `scripts/fix_upload_file.py` —— 修复 Excel
- `scripts/doors_upload_tool.py` —— 上传 Excel 到 DOORS
- `scripts/doors_update_links_tool.py` —— 上传 DOORS links Excel

## 适用场景

- 用户要把 `.xlsx` 上传/更新到一个 DOORS 模块。
- 用户要上传/更新 DOORS links Excel，或提到 `update_doors_links` / `doors_update_links_tool.py`。
- 用户要按 `module_uuid` 读取 DOORS 模块属性、行（rows）内容做分析或对比。
- 用户要刷新一个 DOORS 模块，或提到 `refresh_doors_module` / `doors_refresh_tool.py`。
- 用户提到 `upload_doors_module` / `get_doors_module` / `doors_upload_tool.py` /
  `update_doors_links` / `doors_update_links_tool.py` / `doors_get_tool.py` /
  `doors_refresh_tool.py` / `fix_upload_file.py`。
- 用户遇到"文件格式看起来正常但 DOORS 拒绝上传"。
- 用户说明文件被 Excel/WPS 修改过。

## 关键前提

- Python 环境可用（优先使用用户指定解释器；默认环境 `python` 即可）。
- 工具会调用 MCP 服务：`http://10.54.7.36:8000/mcp`。
- 上传场景需要用户提供：
  - `module_uuid`
  - `username`（NT 账号）
  - `password`（优先通过 `--prompt-password` 或 `--password-env`，不要在日志/聊天中回显）
- 更新 links 场景需要用户提供：
  - links Excel 文件路径
  - `username`（NT 账号）
  - `password`（优先通过 `--prompt-password` 或 `--password-env`）
  - 可选 `module_uuid`（默认 `links-batch`）
- 读取/刷新场景只需要 `module_uuid`，不需要账号/密码。

---

## 一、读取 DOORS 模块流程

### 第 1 步：调用 `doors_get_tool.py`

命令格式（PowerShell）：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_get_tool.py" "<module_uuid>"
```

示例：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_get_tool.py" "1-3a1288eb3f4712b8-M-3e54f001d7539" --init-timeout 30 --get-timeout 300
```

可选参数：

- `--server-url http://10.54.7.36:8000/mcp`
- `--init-timeout 15`
- `--get-timeout 180`
- `--out <path.json>` —— 自定义输出 JSON 路径

### 第 2 步：默认产物

- 默认输出文件：`output/doors_module_<module_uuid>.json`（已存在则覆盖）。
- 文件结构：

  ```text
  {
    "code": 0,
    "message": "Successful",
    "data": {
      "FULLNAME": "...",
      "URL": "doors://...",
      "data_refresh_time": "...",
      "propertyInfo-*": "...",
      "rows": [
        {
          "AbsoluteNumber": "...",
          "DescriptionOfRequirementRB": "...",
          "RB_*": "...",
          "Link": {"In": [], "External": [], "Out": []},
          "rowUrl": "doors://...",
          ...
        },
        ...
      ]
    }
  }
  ```

### 第 3 步：判定结果

成功特征：

- 控制台出现 `[SUCCESS] Fetch completed successfully.`
- 返回 `code == 0`
- `output/doors_module_<uuid>.json` 中 `data.rows` 长度 > 0（一般是数十～数百行）

失败特征：

- `[FAILED] Fetch failed.`
- 非 0 `code` 或异常信息

### 第 4 步：在 JSON 中按条件查询（按需）

当用户给出过滤条件（如 `AbsoluteNumber=443`、`Frame name=ESP_FD3`、`RB_RS_MS_Status=new`）时，
直接用 Python 读 `output/doors_module_<uuid>.json` 的 `data.rows` 做过滤即可，例如：

```python
import json
from pathlib import Path

data = json.loads(Path("output/doors_module_<uuid>.json").read_text(encoding="utf-8"))
rows = data.get("data", {}).get("rows", [])
hit = [r for r in rows if str(r.get("AbsoluteNumber", "")) == "443"]
```

不要为这种一次性查询新增长期脚本到 `scripts/`，避免污染 skill 工程。

---

## 二、刷新 DOORS 模块流程

### 第 1 步：调用 `doors_refresh_tool.py`

命令格式（PowerShell）：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_refresh_tool.py" "<module_uuid>"
```

示例：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_refresh_tool.py" "1-3a1288eb3f4712b8-M-3e54f001d753b" --user-nt CIZ1CGD4 --out "output\refresh_result.json"
```

可选参数：

- `--user-nt <NT账号>` —— 传给 MCP 工具的用户标识，默认 `unknown`
- `--server-url http://10.54.7.36:8000/mcp`
- `--init-timeout 15`
- `--refresh-timeout 300`
- `--out <path.json>` —— 自定义输出 JSON 路径

### 第 2 步：判定结果

成功特征：

- 控制台出现 `[SUCCESS] Refresh completed successfully.`
- 返回 `code == 0`

失败特征：

- `[FAILED] Refresh failed.`
- 非 0 `code` 或异常信息
- 若返回 `HTTPConnectionPool(...): Read timed out`，表示请求已到 MCP，但 DOORS 后端服务超时，通常需要稍后重试或确认服务端状态。

---

## 三、上传 Excel 到 DOORS 流程

### 第 1 步：判断是否需要修复

如果文件满足以下任一条件，先执行修复：

- 文件经过 Excel/WPS 打开并另存。
- 上传报格式错误或服务端拒绝解析。
- 不确定文件是否仍是 DOORS 原始导出结构。

若文件是刚从 DOORS 导出且未被编辑，可直接尝试第 3 步上传。

### 第 2 步：修复 Excel（`fix_upload_file.py`）

`scripts/fix_upload_file.py` 支持命令行参数输入输出，会重建首行元数据
（`sizeRow` / `sizeColumn`）和后续结构，输出修复文件。

运行示例（PowerShell）：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\fix_upload_file.py" "<input.xlsx>" "<input_FIXED.xlsx>"
```

可选参数：

- `--sheet-name "CS Data"`
- `--skip-verify`

### 第 3 步：上传到 DOORS（`doors_upload_tool.py`）

命令格式：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_upload_tool.py" "<excel_file>" "<module_uuid>" "<username>" --prompt-password
```

示例：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_upload_tool.py" "C:\path\to\input_FIXED.xlsx" "1-3a1288eb3f4712b8-M-3e54f001d7539" "ciz1cgd4" --prompt-password
```

可选参数：

- `--server-url http://10.54.7.36:8000/mcp`
- `--init-timeout 15`
- `--upload-timeout 180`
- `--prompt-password`
- `--password-env <ENV_NAME>`

### 第 4 步：判定结果

成功特征：

- 控制台出现 `[SUCCESS] Upload completed successfully.`
- 返回 `code == 0`，常见 `Data: SUCCESS:<n>`

失败特征：

- `[FAILED] Upload failed.`
- 非 0 `code` 或异常信息

---

## 四、上传 DOORS Links Excel 流程

### 第 1 步：确认输入文件

`update_doors_links` 使用 links Excel 文件更新 DOORS link 关系。默认 `module_uuid`
为 MCP schema 中定义的 `links-batch`，一般无需额外传入；若服务端要求指定批次或模块，可用
`--module-uuid` 覆盖。

### 第 2 步：调用 `doors_update_links_tool.py`

命令格式（PowerShell）：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_update_links_tool.py" "<links_excel_file>" "<username>" --prompt-password
```

示例：

```powershell
python ".\.agents\skills\doors-upload-workflow\scripts\doors_update_links_tool.py" "C:\path\to\links.xlsx" "ciz1cgd4" --prompt-password
```

可选参数：

- `--module-uuid <module_uuid>` —— 默认 `links-batch`
- `--server-url http://10.54.7.36:8000/mcp`
- `--init-timeout 15`
- `--update-timeout 180`
- `--prompt-password`
- `--password-env <ENV_NAME>`

### 第 3 步：判定结果

成功特征：

- 控制台出现 `[SUCCESS] Links update completed successfully.`
- 返回 `code == 0`
- 若服务端返回 `data`，脚本会打印 `Data: ...`

失败特征：

- `[FAILED] Links update failed.`
- 非 0 `code` 或异常信息

---

## 常见问题与处理

- `File not found`
  - 检查传入文件路径是否存在，注意引号与反斜杠。
- `Session initialization failed` / MCP 连接失败
  - 检查网络连通性与 `MCP_SERVER_URL` 可访问性。
- 上传超时
  - 重试一次；若仍失败，优先用修复文件再试；必要时确认服务端状态。
- 格式相关报错（常见于编辑后文件）
  - 必须先执行 `fix_upload_file.py`，再上传修复输出文件。
- Links 更新失败
  - 确认 links Excel 文件是服务端期望的格式；
  - 如服务端要求非默认批次，使用 `--module-uuid <module_uuid>` 指定。
- 读取返回内容看起来"少了行"
  - 多数情况下是 DOORS 端筛选/视图差异，不是脚本问题；
  - 直接以 `output/doors_module_<uuid>.json` 的 `data.rows` 数量为准。

## PowerShell 调用注意事项

- 不要在脚本内联 `python -c "..."` 中使用大量逗号与等号——Windows PowerShell 会把
  `,` `(` `=` 当成自己的语法解析，导致命令被吃掉。
- 推荐做法：
  - 对一次性查询，使用 Python 文件路径方式调用，例如先 `Write` 一个临时脚本然后
    `python script.py args`，或直接在 Python 脚本里完成。
  - 命令路径使用单引号 `'...'`，而不是双引号嵌套 `$var`。

## 操作约束

- 不要在日志/聊天中回显用户密码。
- 非必要不要改动 `scripts/doors_upload_tool.py` / `scripts/doors_get_tool.py` 中的
  MCP 协议字段、JSON-RPC 结构、SSE 解析逻辑。
- 当用户说"文件修改过"时，默认执行"修复 -> 上传"完整链路，不要跳步。
- 不要把临时辅助脚本（如 `_query_row.py`、`_summary.py` 等）长期保留在 `scripts/`，
  跑完应清理。

---

## 期望输出模板

读取场景：

1. 模块 UUID
2. 是否成功（`code` / `message`）
3. 输出 JSON 路径
4. 模块概览：`FULLNAME`、`rows` 总数、关键状态分布（如 `RB_RS_MS_Status`）
5. 若用户给了过滤条件，附上命中条目摘要

刷新场景：

1. 模块 UUID
2. 是否成功（`code` / `message`）
3. 若写入 `--out`，附输出 JSON 路径
4. 若失败，附服务返回的核心错误信息

上传场景：

1. 输入文件与模块 UUID
2. 是否执行修复（以及修复输出文件）
3. 上传命令是否执行成功
4. 服务返回核心结果（`code` / `message` / `data`）
5. 下一步建议（重试、换文件、检查网络等）

Links 更新场景：

1. 输入 links Excel 文件
2. 使用的用户 NT 账号与 `module_uuid`（默认 `links-batch`）
3. 更新命令是否执行成功
4. 服务返回核心结果（`code` / `message` / `data`）
5. 若失败，附核心错误信息与下一步建议
