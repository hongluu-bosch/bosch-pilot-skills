# Changelog

## [2.3.0] - 2026-06-11

### Added
- **新增 Routine 完整功能**（v2.2.0 延续）：通过自然语言命令直接添加新的 DcmDspRoutine 配置到 ARXML 文件
  - `add_routine` / `新增routine` 命令类型，支持完整的信号定义
  - 自然语言信号解析器：紧凑类型字面量（`UINT8+UINT16`、`UINT8_N(64bit)`）并自动计算信号位置
  - 默认值机制：`signals_start_out` 省略时自动使用 `UINT8_N(8bit)`
  - 固定授权引用：所有新 Routine 自动使用 `DcmDspCommonAuthorization_ExtEol`
  - 交互式 Common 文件选择 + `--file-hint` 参数支持
  - RID 和 Routine 名称唯一性验证、XML 合法性验证
- **22 个单元测试**：`test_signal_and_inserter.py`（14 个 signal_parser + 8 个 arxml_inserter），全部通过
- **新脚本**：
  - `rid_adder.py` — 新增 Routine 工作流编排
  - `signal_parser.py` — 自然语言信号字符串解析
  - `arxml_inserter.py` — 生成 DcmDspRoutine XML 片段并插入 ARXML

### Changed
- **README 文档重组**：新增 Routine 从独立章节整合为"命令详解"中的第 7 项，与 RID 修改命令平级展示
  - 精简 191 行，删除冗余的场景描述和重复表格
  - 保留 1 个信号布局表示例（工厂复位）展示方向列概念
  - "常见问题"独立为单独章节，包含所有 FAQ
- `requirement_parser.py`：新增 `add_routine` 命令解析，支持 `routine_name=` 显式模式
- `orchestrator.py`：新增 `add_routine` 路由，`file_hint` 参数，Windows UTF-8 编码修复

### Fixed (Review Issues)
- **P0 - SUB-CONTAINERS 标签缺失**：修复信号容器不在 `<SUB-CONTAINERS>` 内的问题
- **P0 - 缩进不匹配**：重写缩进常量，使用命名层级匹配项目 ARXML
- **P1 - 前缀重复风险**：自动去前缀处理，防止 `RBAPLCUST_` 重复
- **P1 - 默认值分散**：集中默认值逻辑到 `build_routine_xml()`
- **P2 - 未使用代码**：移除 `signal_parser.py` 中的 `generate_signal_xml()`
- **P2 - 空信号值处理**：改进正则表达式处理空值情况

## [2.2.0] - 2026-06-10

### Added
- **新增 Routine 支持**：通过自然语言命令直接添加新的 DcmDspRoutine 配置到 ARXML 文件
  - `add_routine` / `新增routine` 命令类型
  - 自然语言信号解析器：支持紧凑类型字面量（`UINT8+UINT16`、`UINT8_N(64bit)`）并自动计算信号位置
  - 默认值机制：`signals_start_out` 省略时自动使用 `UINT8_N(8bit)`；`signals_stop_out`/`signals_result_out` 省略时不生成对应容器
  - 固定授权引用：所有新 Routine 自动使用 `DcmDspCommonAuthorization_ExtEol`
  - 交互式 Common 文件选择：当 Common 存在多个 ARXML 文件时，列出文件列表供用户选择
  - RID 和 Routine 名称唯一性验证
  - 插入后 XML 合法性验证（重新解析确认）
- **新脚本**：
  - `rid_adder.py` — 新增 Routine 工作流编排
  - `signal_parser.py` — 自然语言信号字符串解析
  - `arxml_inserter.py` — 生成 DcmDspRoutine XML 片段并插入 ARXML

### Changed
- `requirement_parser.py`：新增 `add_routine` 命令解析逻辑，支持 `routine_name=` 显式模式
- `orchestrator.py`：新增 `add_routine` 路由，支持 `file_hint` 参数，修复 Windows UTF-8 编码
- `rid_adder.py`：Common 文件选择交互、名称前缀防重复处理

### Fixed (Review Issues)
- **P0 - SUB-CONTAINERS 标签缺失**：修复 `DcmDspStartRoutine` 内信号容器不在 `<SUB-CONTAINERS>` 内的问题
- **P0 - 缩进不匹配**：重写缩进常量，使用命名层级（R_ROUTINE=32, SR_ROUTINE=36 等）匹配项目 ARXML
- **P1 - 前缀重复风险**：`arxml_inserter.py` 自动去前缀处理，`rid_adder.py` 不再内部添加前缀
- **P1 - 默认值分散**：集中默认值逻辑到 `build_routine_xml()`，移除 `rid_adder.py` 中的重复逻辑
- **P2 - 未使用代码**：移除 `signal_parser.py` 中的 `generate_signal_xml()`
- **P2 - 空信号值处理**：改进正则表达式，正确处理 `signals_start_out=` 等空值情况

### Added (Testing)
- `test_signal_and_inserter.py`：22 个单元测试（14 个 signal_parser + 8 个 arxml_inserter），全部通过

## [2.1.0] - 2026-06-09

### Changed
- **Strict project root auto-detection**: Removed `--project-root` CLI parameter and `project_root` keyword argument from all Python APIs.
  - The skill now **only** supports automatic project root resolution.
  - A valid root must contain a direct subdirectory with `rb/`, `rba/`, and `rb/as/` present.
  - Detection walks upward from cwd and returns the outermost matching directory.
  - If no matching structure is found, the skill hard-fails with `RuntimeError`.
  - This prevents workspace misplacement caused by manual path overrides.

### Removed
- `--project-root` CLI argument from `orchestrator.py` (standalone scripts `scan_routines.py` and `update_arxml.py` still accept it with a deprecation warning)
- `project_root` parameter from `run_workflow()`, `confirm_and_apply()`, and `--reset-common-auto` handler

## [2.0.0] - 2026-06-08

### Added
- **Natural language command parsing**: 6 supported command types — sequential assign, offset shift, clamp, explicit map, pattern map, name map
- **Auto project root resolution**: Walks upward from cwd to discover the topmost directory containing `rb/as/`
- **Unified diff preview**: Generates `.diff` files before applying changes, showing exact line-by-line modifications
- **Change summary Excel**: Exports `rid_changes_summary.xlsx` with old/new RID values and status
- **`--dry-run` mode**: Preview changes without modifying any arxml files
- **`--yes` mode**: Skip confirmation for automated pipelines
- **New scripts**:
  - `requirement_parser.py` — parses natural language into structured commands
  - `rid_calculator.py` — computes new RIDs and detects conflicts
  - `diff_generator.py` — generates unified diff output

### Removed
- Excel-based user input workflow (`read_excel_updates` removed from `generate_excel.py`)
- CLI `scan` subcommand (scanning is now automatic)
- `--force` flag (conflicts are now blocking by default; use `--yes` to bypass confirmation)

### Changed
- `orchestrator.py` fully rewritten: now a single-pass workflow `parse → scan → calculate → preview → apply`
- `generate_excel.py` no longer reads user input; only exports change summaries
- `SKILL.md` and `README.md` updated to reflect natural language interaction

## [1.1.0] - 2026-06-01

### Fixed
- `scan_routines.py`: Added missing `import json` that caused `NameError` during scan metadata save.
- `update_arxml.py`: Rewrote RID update logic to use **pure text context-aware replacement** instead of `ElementTree.write()`. This guarantees:
  - XML declaration quotes (`'`) are preserved
  - XML comments (`<!-- ... -->`) are preserved
  - Original indentation and whitespace are preserved
  - Only the `<VALUE>` tag inside `DcmDspRoutineIdentifier` is modified

## [1.0.0] - 2026-05-29

### Added
- Scan project ARXML files to extract all `DcmDspRoutine` configurations
- Generate `rid_inventory.xlsx` with current RIDs (decimal + hex)
- Support user editing `New_RID_User_Input` column in Excel
- Validate RID input: decimal or `0x` hex format, range `0–65535`
- Conflict detection: duplicate RIDs across different routines, inconsistent RIDs for same routine across files
- Apply updates back to original ARXML files with `--dry-run` preview
- `--force` flag to apply despite conflicts
- Audit trail: save scan metadata and update logs in `.DCOM_AI/31Service_Toolkit_PRJ/state/`
