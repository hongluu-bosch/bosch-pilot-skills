# Architecture Reference

Deep-dive into the internal module layout, class responsibilities, and the templating subsystem. Read this when you need to trace how data flows through the code, understand a helper's contract, or change the Phase 7 implementation package.

The top-level `SKILL.md` carries the short system diagram and FSCS governance summary.

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              DID Toolkit                                 │
├──────────────────────────────────────────────────────────────────────────┤
│  Input Layer    │  Processing Layer       │  Output Layer                │
├─────────────────┼─────────────────────────┼──────────────────────────────┤
│  *_did.json     │  Phase 1: FSCS          │  fscs/fscs.json (源真相)      │
│  (only — .xlsx  │  generate_fscs.py       │  fscs_generation_report.txt  │
│   is never      │    + auto-review hook   │  fscs_review_report.txt (1)  │
│   auto-         │    + XLSX export        │  fscs/fscs_edit.xlsx          │
│   discovered)   │                         │                              │
│                 ├─────────────────────────┼──────────────────────────────┤
│  fscs_edit.xlsx  │  XLSX Import            │  fscs.json (updated used=…)  │
│  + fscs.json    │  fscs/xlsx_edit.py      │  fscs/FSCS_22.txt            │
│                 │    + auto-review hook   │  fscs/FSCS_2E.txt            │
│                 │                         │  fscs_review_report.txt (2)  │
│                 ├─────────────────────────┼──────────────────────────────┤
│  fscs.json      │  --phase review         │  fscs/fscs_review_report.txt │
│                 │  review_fscs.py         │    (ad-hoc re-run, no regen) │
│                 ├─────────────────────────┼──────────────────────────────┤
│  FSCS_22/2E.txt │  --phase doors          │  doors_upload.xlsx           │
│  doors_mapping  │  build_doors_payload.py │  doors_payload_report.txt    │
├─────────────────┼─────────────────────────┼──────────────────────────────┤
│  fscs.json      │  Phase 2: ARXML         │  DID_Config.arxml            │
│                 │  generate_arxml.py      │  arxml/validation_report.txt │
├─────────────────┼─────────────────────────┼──────────────────────────────┤
│  fscs.json      │  Phase 3: Impl          │  implementation/             │
│  Config         │  generate_impl.py       │  ├── pdm_entries             │
│                 │                         │  ├── headers                 │
│                 │                         │  └── c_code/                 │
└─────────────────┴─────────────────────────┴──────────────────────────────┘

(1) Skip with `--no-review` / `DID_NO_REVIEW=1`.
(2) Unconditional on every xlsx-import.
```

## Three-Phase Workflow

### Phase 1: FSCS Generation

**职责**：从 `.DCOM_AI/DID_Toolkit_PRJ/inputs/<customer>_did.json` 读取 records
（agent 写的一次性 `.DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py` 负责把
`.xlsx` 问卷转成这份 JSON——skill 自身不带任何 workbook 解析器），
转换为权威数据源 `fscs.json`，导出 `fscs_edit.xlsx` 交由操作员在
Excel/WPS 中修改，然后通过 xlsx-import 写回最终下游产物。

**关键逻辑**:
- 过滤 `supported_by_ecu=Y` 的记录
- 对每条记录做 Pydantic 逐条校验；格式错误的 DID **被单独跳过**（不再整体
  失败），diagnostics 写入 `fscs_generation_report.txt`
- 移除中文字符和特殊字符
- 排除 `programmingSession` 和 `L_FBL`
- 为 EEPROM DIDs 生成 `NVM Item`
- 为 `service_22.behavior` / `service_2e.behavior` 生成默认 Behavior 模板
  （EEPROM=NVM 读写、RAM=`interface: `、ROM=read-side 单个 `HardCode:` 标题
  加逐字节常量占位）
- 提取子字段的数值范围 / 枚举值
- 从旧的 `fscs.json` 读取 `used_22 / used_2e` 选择和 per-service
  `behavior` 文本并沿用（除非
  `--reset-used`）
- **生成末尾自动调用 `_run_fscs_review`**，把
  `fscs_review_report.txt` 与刚落盘的 `fscs.json` 对齐
- 导出 `outputs/fscs/fscs_edit.xlsx`

**Phase 1 不做的事**:
- 不写 `FSCS_22.txt / FSCS_2E.txt`（这两个文件由 `--phase xlsx-import` 写出）
- Review 失败不会反转 Phase 1 的返回值（advisory 语义）

**Review Integration (v1.7 三条触发路径)**:

| 触发 | 谁调 | 带 input_json? |
|---|---|---|
| Phase 1 结束 | `pipeline.py::run_phase1` → `_run_fscs_review(input_path, fscs.json)` | 是（一致性检查激活）|
| xlsx-import | `pipeline.py::run_xlsx_import` → `_run_fscs_review` | 可选（operator 传 `--input` 时激活）|
| `--phase review` | `pipeline.py::run_review_only` → `_run_fscs_review` | 可选（operator 传 `--input` 时激活）|

三条路径统一写到 `outputs/fscs/fscs_review_report.txt`（覆盖式），所以该文件永远反映**最近一次**对 `fscs.json` 的审查。

**Opt-out**:
- Phase 1 路径：`--no-review` 或 `DID_NO_REVIEW=1`
- xlsx-import 路径：没有开关（工作簿改了就刷新报告）
- `--phase review`：就是 on-demand 本身，无所谓 opt-out

### Phase 2: ARXML Generation

**职责**: 从 FSCS 解析 DID 信息并生成 AUTOSAR DCM 配置。

**命名规范**:
- `DcmDspData`: `RBAPLCUST_{DID}_{Name}Data`
- `DcmDspDataReadFnc`: `RBAPLCUST_{DID}_{Name}_ReadData`
- `DcmDspDataWriteFnc`: `RBAPLCUST_{DID}_{Name}_WriteData` (if RW)
- `DcmDspDid`: `RBAPLCUST_{DID}_{Name}DataDid`

**数据结构**:
- 数据类型统一映射为 `UINT8_N`
- 大小转换为 bits (bytes × 8)
- DID 标识符使用十进制
- 根据 `R/W State` 选择 `DcmDspDidInfo_Read` 或 `ReadAndWrite`

### Phase 3: Implementation Generation

**职责**: 生成完整的实现代码，包括 PDM、头文件和 C 代码。

**四大输出**:

1. **PDM 条目** (仅 EEPROM DIDs):
   ```pdm
   #if (RBFS_DCOM_VariantCoding == RBFS_DCOM_VariantCoding_ON)
   use dataitem NVM_ID_DCOM_VariantCoding
   {
       job interface { }
       plant eol preserve;
       writecycles = 1000;
   }
   #endif /* RBFS_DCOM_VariantCoding */
   ```

2. **头文件内容**:
   - `Config.h`: Feature Switch 默认 OFF
   - `ConfigSettings.h`: Feature Switch 配置 ON
   - `ConfigElements.h`: ON=1, OFF=2 值定义

3. **C 代码**:
   - Read: 使用 EEPROM 或非 EEPROM 模板
   - Write: 根据值范围类型动态生成（枚举 / 数值 / 无限制）

4. **值范围宏** (EEPROM Write DIDs):
   ```c
   #define DID_0101_MIN  0
   #define DID_0101_MAX  255
   #define DID_0101_VAL_0  0x00
   ```

## Data Flow

```
Questionnaire Input (.DCOM_AI/DID_Toolkit_PRJ/inputs/*_did.json — JSON only)
    │  Note: .xlsx is never auto-discovered. Agent writes a one-shot
    │  .DCOM_AI/DID_Toolkit_PRJ/scripts/extract_<customer>.py to convert a workbook to JSON
    │  before Phase 1 will accept it.
    ▼
[FSCSGenerator]  ──→ fscs/fscs.json                   (authoritative source)
    │            └─→ fscs/fscs_generation_report.txt  (kept / filtered / skipped)
    │
    │  v1.2 auto-review hook (pipeline.py::run_phase1):
    │  └─→ fscs/fscs_review_report.txt                (unless --no-review / DID_NO_REVIEW=1)
    ▼
[XLSX export]    reads fscs.json
    │   writes fscs/fscs_edit.xlsx for Excel/WPS editing
    ▼
[XLSX import]    reads fscs_edit.xlsx + fscs.json
    │   operator flips used_flag / service_XX_support (and other flattened fields)
    │   import runs the atomic triple-write:
    │     ├──→ fscs/fscs.json            (updated used flags + edits)
    │     ├──→ fscs/FSCS_22.txt          (derived human view, effective only)
    │     └──→ fscs/FSCS_2E.txt          (derived human view, effective only)
    │
    │  auto-review hook (pipeline.py::run_csv_import):
    │  └─→ fscs/fscs_review_report.txt   (refreshed on every import; no toggle)
    ▼
[--phase review]  reads fscs.json                      (ad-hoc CLI re-run)
    │             └─→ fscs/fscs_review_report.txt
    ▼
[ARXMLGenerator] reads fscs.json ──→ DID_Config.arxml
    │   (skips DIDs where service_22.effective AND service_2e.effective are both false)
    ▼
[ImplementationGenerator] reads fscs.json
    │
    ├──→ pdm_entries.txt
    ├──→ header_config_macros.txt
    ├──→ header_config_settings.txt
    ├──→ header_element_defs.txt
    └──→ c_code/*.c
```

## Core Modules

### 1. DIDPipeline (Main Controller)

协调三个阶段的执行，提供统一的命令行接口。

**关键方法**:
- `phase1_generate_fscs()` — 生成 FSCS 文档并执行 Review
- `phase2_generate_arxml()` — 生成 ARXML
- `phase3_generate_implementation()` — 生成实现代码

### 2. FSCSGenerator

**核心功能**:
- `_clean_name()` — 清理名称（移除中文、特殊字符）
- `_get_nvm_item()` — 生成 NVM Item 名称
- `_get_supported_sessions()` — 解析支持的诊断会话
- `_get_security_levels()` — 解析安全级别（L0/L1 逻辑）
- `_get_value_range()` — 提取值范围（枚举或数值）

**安全级别逻辑**:
- L0 + L1 都支持 → 仅输出 L0
- 仅 L1 支持 → 输出 L1
- 仅 L0 支持 → 输出 L0 + 警告

### 3. ARXMLGenerator

**核心功能**:
- `parse_fscs()` — 从 FSCS 提取 DIDInfo
- `generate_dcm_dsp_data()` — 生成 DcmDspData 容器
- `generate_dcm_dsp_did()` — 生成 DcmDspDid 容器
- `generate_from_dids()` — 组装完整 ARXML

### 4. ImplementationGenerator (`scripts/implementation/` 包)

Phase 7 把 1200+ 行的 `generate_implementation.py` 拆成 `scripts/implementation/` 子包；`scripts/generate_implementation.py` 退化为薄 shim，保持所有旧 import / CLI 调用不变。

**子模块分工**:

- `models.py` – `DIDImplementationInfo` dataclass + pydantic `DIDInput` / `DIDSubField`（输入 JSON 的 fail-fast 校验，`extra='allow'` 以容忍历史字段）。
- `naming.py` – 纯命名函数：`clean_name`、`capitalize_first`、`get_fs_macro`、`get_nvm_id`、`get_range_macro_name`、`get_func_name`，加两个 Bosch 前缀常量。
- `parsers.py` – `parse_enum_values` / `parse_numeric_range` value-range helpers.
- `paths.py` – `product_type_lower` / `product_type_upper` / `product_type_suffix` + `resolve_path`（`{product_type}` / `{product_type_lower}` / `{product_type_upper}` / `{product_type_suffix}` 占位符展开；`{product_type_suffix}` 把 `Common` 槽展开成字面量 `SingleCANID` 以匹配 Bosch 那边的 ARXML 文件命名 `_SingleCANID.arxml`。customer 段不是占位符，`--init-project` 在生成 `paths.*` 时直接烘进字面值）。
- `safety.py` – `guarded_project_write`（dry-run 兼容的项目树写入门面）。skip-on-conflict 不会覆盖任何现有内容，所以没有 rolling backup 机制。
- `generators.py` – 所有 `generate_*` 纯函数（PDM、`Config.h` / `ConfigSettings.h` / `ConfigElements.h` 宏、range 宏、RDBI/WDBI C 源），每个都调用 `scripts/templates/impl/*.j2`。非 EEPROM 桩使用 `_build_inline_todo_block` 把 DID identity / storage classification / RAM 子模式猜测 / FSCS behavior 原文 / 7 条策划上下文路径直接埋进 `.c` 注释——无外部 brief 文件。
- `arxml_merge.py` – Phase 2 项目树投射的纯合并函数。`extract_dcmdsp_short_names` 用 ElementTree 提取目标 ARXML 中 `DcmDsp/SUB-CONTAINERS` 下所有直接子容器的 `SHORT-NAME`；`merge_arxml` 做字节级拼接：新容器按 SHORT-NAME 去重（skip-on-conflict），插入到目标闭合 `</SUB-CONTAINERS>` 之前，目标文件其余字节保持不变。`scripts/generate_arxml.py::ARXMLGenerator._write_to_project` 调度本模块走 `guarded_project_write`（无备份步骤，因为合并是非破坏性的）。
- `orchestrator.py` – `ImplementationGenerator` 类。保留方法签名兼容旧测试，方法体委托给上述纯函数和 `guarded_project_write`。返回的 stats dict 包含 `skipped_c_files` / `agent_fill_targets` / `agent_stub_targets`，用于 Phase 3 收尾的 `[AGENT TODO] X fill / Y stub` 摘要。

**智能头文件合并** (`orchestrator._merge_header_content`):
1. `_extract_existing_macros()` — 提取已有宏
2. 过滤掉已存在的宏定义
3. `_find_insert_position()` — 定位到最后一个 `#endif` 之前
4. 插入新内容并报告统计

**向后兼容**: `generate_implementation.py` 以 `from implementation import *` 重新暴露全部旧符号；`tests/unit/test_package_split.py` 锁定了 shim 与子包指向同一对象，防止两边漂移。

### 5. FSCS Package (`scripts/fscs/`)

- `schema.py` – Pydantic `FSCSDocument` / `DID` / … models that define the on-disk JSON contract.
- `builder.py` – `build_fscs_document()` plus derivation helpers (`_derive_security_levels`, `_derive_value_range`, etc.) turning raw input records into the typed document.
- `adapter.py` – `load_fscs(path)` and `to_review_dicts(document)` — the single entry point every consumer (Phase 2, Phase 3, reviewers) uses to obtain FSCS data.
- `xlsx_edit.py` – spreadsheet round-trip projection: export `fscs.json` to `fscs_edit.xlsx` (with drop-down validations, auto-fit columns, frozen header), import the edited workbook back into a validated `FSCSDocument`.
- `drift.py` – advisory comparison between `fscs.json` and the sidecar `.txt` files.
- `importer.py` – one-shot migration from legacy TXT-only projects (see `scripts/fscs_import.py`).

### 6. Templating (`scripts/templating.py` + `scripts/templates/`)

ARXML 和 Implementation 两个生成器的大段静态文本（C 源码、PDM / header 宏块、`DcmDspData` / `DcmDspDid` 容器）都从 f-string 迁移到 Jinja2 模板，集中放在 `scripts/templates/{impl,arxml}/*.j2`。

**设计要点**:
- 自定义分隔符 `<< >>` / `<% %>` / `<# #>`，避免和 C 代码的 `{ }`、ARXML 的 `<tag>` 冲突，模板本体保留成品样貌。
- `keep_trailing_newline=True`、`trim_blocks=False`、`lstrip_blocks=False`、`autoescape=False` — 字节级等价于原 f-string 输出。
- `undefined=StrictUndefined` — 上下文字段拼错会立即抛错，而不是静默产生空串污染输出树。
- `get_env()` 用 `lru_cache` 单例化；整跑只解析一次模板。

**依赖**:
- `pip install -r scripts/requirements.txt` （`Jinja2>=3.1,<4`, `pydantic>=2.6,<3`）
- xlsx 编辑流程依赖 `xlsxwriter`（写）和 `openpyxl`（读）；两者都在 `scripts/requirements.txt` 中。
- 单元测试 `tests/unit/test_templating.py` 锁定这些不变量，任何修改需同步更新测试。
