# 31service-toolkit

> 用自然语言批量修改 Bosch BSW 项目中的 UDS 0x31 (RoutineControl) RID，支持新增 Routine 及其信号定义，无需手动编辑 Excel。

---

## 安装

依赖仅有一个 Python 包：

```bash
pip install openpyxl
```

将本 skill 文件夹复制到你的 opencode skills 目录（如 `~/.config/opencode/skills/`）即可使用。

---

## 3 步快速上手

1. **说出需求**：用自然语言告诉 Agent 你想怎么改 RID
2. **查看预览**：Agent 自动生成 diff 对比和 Excel 摘要供你审查
3. **确认应用**：回复 "确认" 或 "yes"，Agent 自动将修改写回 arxml 文件

---

## 产品识别规则（v2.1.0+）

Agent 会自动识别你提到的产品名称（如 IPB、RBU、ESP）：

- **提到谁，就改谁**：只修改明确提到的产品，其他产品保持不变。
- **歧义时暂停询问**：如果提到的名称存在歧义（如 `XPB` 可能指 IPB 或 DPB），Agent 会停下来请你确认。
- **没提到产品 = 全部修改**：例如 *"把所有 RID 顺序分配到 0xF100-0xF1FF"* 会应用到所有产品。

### Common 自动同步

Common（通用配置）的 routine 会跨多个 arxml 文件共享。第一次修改某个非 Common 产品时，Common 会自动跟随分配；之后再次修改其他非 Common 产品时，Common 不再自动跟随，除非你明确提到它。如需重置同步状态，运行：

```bash
python scripts/orchestrator.py --reset-common-auto
```

> 顺序分配时，Common 始终排在第一位分配，其余产品按你提到的顺序接续。

---

## 提示词速查表

下面 6 种提示词覆盖了绝大多数 RID 批量修改场景。**中英文都可以使用。**

> **指定产品类型**：以上所有命令格式都支持在句首加上产品名称，只修改对应产品。
>
> 示例：
> - `把 IPB 和 RBU 的 RID 顺序分配到 0x3000-0x30FF`
> - `把 ESP 的 RID 平移到 0xB000`
>
> 未提及的产品（如 DPB、Common 等）将保持不变。

### 1. 顺序范围分配
按当前排序后的顺序，把所有 Routine 的 RID 依次填入指定范围。

| 中文示例 | 英文示例 |
|---|---|
| 把所有RID顺序分配到 0xF100-0xF1FF | assign all RIDs sequentially to 0xA100-0xA1FF |
| 顺序分配所有RID到 0x1000-0x1FFF | allocate all RIDs sequentially within 0x1000-0x1FFF |

> **注意**：范围容量必须大于等于 Routine 总数，否则会报错要求扩大范围。

### 2. 偏移/平移
保持各 RID 之间的相对间隔不变，整体平移到新的起始值。

| 中文示例 | 英文示例 |
|---|---|
| 把所有RID平移到 0xF100 起始 | shift all RIDs to start at 0xB000 |
| 偏移所有RID到 0x1000 | offset all RIDs to 0x1000 |

> **注意**：若平移后某个 RID 超出 0-65535 范围，会报错。

### 3. 范围限制
仅修改超出指定范围的 RID，范围内的保持不变。

| 中文示例 | 英文示例 |
|---|---|
| 确保所有RID在 0xF100-0xF1FF 范围内 | clamp all RIDs within 0x1000-0x1FFF |
| 限制所有RID在 0x2000-0x2FFF | restrict all RIDs to 0x2000-0x2FFF |

### 4. 显式值映射
精确匹配当前 RID 值，替换为目标值。未提及的 RID 保持不变。

| 中文示例 | 英文示例 |
|---|---|
| 把 0xF100 改成 0xA100，0xF101 改成 0xA101 | map 0xF200 to 0xA200, 0xF201 to 0xA201 |
| 将 0xF200 改为 0xB200 | 0xF100 -> 0xA100 |

### 5. 规则式掩码映射
按高字节匹配，低字节保留不变。`xx` 或 `??` 为通配符。

| 中文示例 | 英文示例 |
|---|---|
| 把 0xF1xx 全部改成 0xA1xx | replace 0xF1xx with 0xA1xx |
| 将 0xF2xx 改为 0xB2xx | 0xF2xx -> 0xA2xx |

> **匹配规则**：`0xF1xx` 匹配 `0xF100` ~ `0xF1FF`，仅替换高两位，低两位保留。

### 6. 按名称映射
根据 Routine 的 SHORT-NAME 精确替换为指定 RID。

| 中文示例 | 英文示例 |
|---|---|
| 把 Routine_FactoryReset 改成 0xA100 | set Routine_FactoryReset to 0xA100 |
| 将 Routine_Bleed 改为 0xB200 | Routine_Bleed -> 0xB200 |

### 7. 新增 Routine（诊断服务）
添加新的 DcmDspRoutine 配置，包含完整的信号定义。

| 中文示例 | 英文示例 |
|---|---|
| 新增routine Common RID=0xF200 routine_name=TestRoutine signals_start_in=UINT8+UINT16 | add routine Common RID=0xF200 routine_name=TestRoutine signals_start_in=UINT8,UINT16 |
| 新增routine IPB RID=0x3100 routine_name=FactoryReset signals_start_in=UINT8 signals_start_out=UINT8 | add routine IPB RID=0x3100 routine_name=FactoryReset signals_start_out=UINT8 |

> **信号格式**：使用紧凑类型字面量，用 `+`、`,` 或 `和` 分隔。
> 示例：`UINT8+UINT16`、`UINT8_N(64bit)`、`BOOLEAN`
> **省略的信号**：`signals_start_out` 省略时默认 `UINT8_N(8bit)`；`signals_stop_out`/`signals_result_out` 省略时不生成对应容器。

## 命令详解

### 1-6. RID 修改命令

前 6 种命令（顺序分配、偏移/平移、范围限制、显式值映射、规则式掩码映射、按名称映射）都用于**修改现有 Routine 的 RID 值**，不改变 Routine 的其他配置。

所有修改命令都支持：
- 在句首指定产品类型：`把 IPB 的 RID 平移到 0xB000`
- `--dry-run` 预览、`--yes` 直接应用
- 冲突自动检测（重复 RID、范围越界等）

### 7. 新增 Routine

在 ARXML 中插入新的 DcmDspRoutine 配置。

#### 命令格式

```text
新增routine <产品类型> RID=<RID值> routine_name=<Routine名称> [signals_start_in=<信号列表>] [signals_start_out=<信号列表>] [signals_stop_out=<信号列表>] [signals_result_out=<信号列表>]
```

| 参数 | 必填 | 说明 |
|------|------|------|
| `产品类型` | 是 | Common / IPB / ESP / DPB / RBU / ESPCL |
| `RID` | 是 | 十六进制（`0xF200`）或十进制 |
| `routine_name` | 是 | 纯英文，不加 `RBAPLCUST_` 前缀 |
| `signals_start_in` | 否 | Start 输入信号，省略则不生成 StartRoutineIn |
| `signals_start_out` | 否 | Start 输出信号，省略则默认 `UINT8_N(8bit)` |
| `signals_stop_out` | 否 | Stop 输出信号，省略则不生成 Stop 容器 |
| `signals_result_out` | 否 | Result 输出信号，省略则不生成 Result 容器 |

#### 信号类型

| 类型 | 大小 | 示例 |
|------|------|------|
| `UINT8` / `SINT8` / `BOOLEAN` | 8 bit | `UINT8` |
| `UINT16` / `SINT16` | 16 bit | `UINT16` |
| `UINT32` / `SINT32` | 32 bit | `UINT32` |
| `UINT8_N(nbit/Byte)` | n bits | `UINT8_N(64bit)` |
| `UINT16_N(nbit)` | n bits | `UINT16_N(128bit)` |
| `UINT32_N(nbit)` | n bits | `UINT32_N(256bit)` |

> 多个信号用 `+` 连接：`UINT8+UINT16`。数组类型必须带单位（`bit` 或 `Byte`）。

#### 示例

```bash
# 最简配置（只有默认的 Start 输出）
新增routine Common RID=0xF200 routine_name=BootloaderCheck

# 带输入参数
新增routine IPB RID=0x3100 routine_name=FactoryReset signals_start_in=UINT8+UINT16 signals_start_out=UINT8

# 完整生命周期（含 Stop 和 Result）
新增routine DPB RID=0x3300 routine_name=SelfTest signals_start_in=UINT32 signals_start_out=UINT8_N(64bit) signals_stop_out=UINT8 signals_result_out=UINT16
```

> **工厂复位示例的信号布局**：
>
> | 方向 | Signal | pos | len | 类型 |
> |------|--------|-----|-----|------|
> | StartIn | Signal_0 | 0 | 8 | UINT8 |
> | StartIn | Signal_1 | 8 | 16 | UINT16 |
> | StartOut | Signal_0 | 0 | 8 | UINT8 |

#### Common 文件选择

Common 配置跨多个 ARXML 文件共享。新增时会列出所有文件请你选择编号，或输入 `all` 应用到全部文件。

#### 验证规则

添加前自动检查 RID 唯一性、名称唯一性、信号格式合法性和 XML 合法性。

---

## 完整工作流程

```
用户输入自然语言需求
        |
        v
自动发现项目根目录（向上回溯寻找 rb/as/）
        |
        v
扫描所有 Dcm_CusDiag_Services*.arxml 文件
        |
        v
解析需求，计算每个 Routine 的新 RID
        |
        v
冲突检测（重复 RID、同名 Routine 不同值）
        |
        v
生成 diff 预览 + Excel 变更摘要
        |
        v
[Agent 暂停] 展示预览，等待用户确认
        |
        v
用户回复 "确认" / "yes"
        |
        v
应用修改到原始 arxml 文件
        |
        v
保存审计日志
```

---

## CLI 参数参考

你也可以直接通过命令行调用：

```bash
# 仅预览（不修改文件）
python scripts/orchestrator.py "把所有RID平移到 0xF100 起始" --dry-run

# 跳过确认直接应用（适合自动化管道）
python scripts/orchestrator.py "把所有RID平移到 0xF100 起始" --yes
```

**注意**：项目根目录由脚本自动检测，不支持手动指定。运行前请确保当前目录在项目结构内。

| 参数 | 说明 |
|---|---|
| `--dry-run` | 仅生成 diff 和 Excel 摘要，不修改任何 arxml 文件 |
| `--yes` | 跳过人工确认，直接应用更改 |
| `--reset-common-auto` | 重置 Common 自动同步状态，下次非 Common 修改时 Common 将再次跟随 |
| `--file-hint` | 指定 Common 文件编号（如 `2` 或 `all`），跳过交互式选择 |

---

## 输出文件说明

运行后会在项目根目录下创建 `.DCOM_AI/31Service_Toolkit_PRJ/` 工作区：

```
<project-root>/
└── .DCOM_AI/
    └── 31Service_Toolkit_PRJ/
        ├── outputs/
        │   ├── rid_changes_YYYYMMDD_HHMMSS.diff    ← 统一差异格式预览
        │   └── rid_changes_summary.xlsx             ← 变更摘要表格
        └── state/
            ├── routines.json                        ← 扫描结果缓存
            ├── scan_metadata.json                   ← 扫描元数据
            └── update_log_YYYYMMDD_HHMMSS.json      ← 审计日志
```

| 文件 | 用途 |
|---|---|
| `.diff` | 统一差异（unified diff）格式，显示每处修改的上下文，方便代码审查 |
| `.xlsx` | Excel 表格，列出所有 Routine 的旧值、新值、状态（Changed/Unchanged） |
| `.json` | 机器可读的审计日志，记录命令、变更列表、时间戳、错误信息 |

---

## 安全说明

- **只改值不改格式**：仅替换 `DcmDspRoutineIdentifier` 后的 `<VALUE>...</VALUE>` 内容，XML 声明、注释、缩进、换行全部原样保留
- **直接修改原文件**：arxml 文件会被直接覆盖，请在应用前确保项目已纳入版本控制（Git/SVN）
- **默认需要确认**：除非使用 `--yes`，否则 Agent 会在修改前停下来等待你确认
- **冲突自动拦截**：若检测到同一 RID 分配给不同 Routine，或同名 Routine 在不同文件中被分配不同值，会自动报错阻止

---

## 目录结构

```
31service-toolkit/
├── scripts/
│   ├── orchestrator.py         # 主入口，协调完整工作流
│   ├── scan_routines.py        # 扫描 arxml 提取所有 Routine
│   ├── requirement_parser.py   # 解析自然语言命令
│   ├── product_resolver.py     # 产品名称识别与歧义检测
│   ├── rid_calculator.py       # 计算新 RID 并检测冲突
│   ├── diff_generator.py       # 生成统一差异（unified diff）
│   ├── generate_excel.py       # 导出变更摘要 Excel
│   ├── update_arxml.py         # 将 RID 修改写回 arxml（纯文本替换）
│   ├── validate_rid.py         # RID 格式与范围校验
│   ├── arxml_utils.py          # arxml 解析工具函数
│   ├── arxml_text_utils.py     # arxml 纯文本 RID 替换（供 diff_generator 和 update_arxml 共享）
│   ├── rid_adder.py            # 新增 Routine 到 ARXML 文件
│   ├── signal_parser.py        # 解析自然语言信号字符串
│   └── arxml_inserter.py       # 生成 Routine XML 片段并插入
├── references/
│   └── arxml-routine-structure.md   # AUTOSAR Routine XML 结构参考
├── SKILL.md                    # AI Agent 操作手册（详细工作流指令）
├── CHANGELOG.md                # 版本历史
├── README.md                   # 本文档
└── requirements.txt            # Python 依赖
```

## 常见问题

### 找不到项目根目录

**现象**：`Could not find project root: no '*/rb/as' + '*/rba' structure found`

**解决**：确保你在项目目录或其子目录下运行 skill。项目根目录的直接子目录中必须同时包含 `rb/`、`rba/` 和 `rb/as/` 结构。不支持手动指定项目根目录。

### 没有扫描到任何 Routine

**现象**：`No routines found`

**解决**：检查项目是否存在以下路径结构的 arxml 文件：
```
rb/as/**/core/app/dcom/RBAPLCust/cfg/**/Dcm_CusDiag_Services*.arxml
```

### 范围太小

**现象**：`Range 0xF100-0xF1FF (256 values) is too small for 300 routines`

**解决**：扩大范围上限，或使用"偏移/平移"命令代替"顺序范围分配"。

### 平移后 RID 越界

**现象**：`Shifted RID 65536 out of 0-65535 range`

**解决**：选择更小的目标起始值，确保最大 RID + 偏移量 ≤ 65535。

### 冲突检测失败

**现象**：`CONFLICT: RID 0xF100 assigned to multiple different routines`

**解决**：两个不同的 Routine 被计算出了相同的新 RID。修改提示词以消除冲突，例如扩大范围、使用偏移而非顺序分配、或显式指定不同值。

### 范围重叠

**现象**：`Product 'IPB' new range 0x3000-0x3043 overlaps with previously assigned range ...`

**解决**：系统会阻止同一产品重复使用已分配过的 RID 范围，也会阻止不同产品之间范围重叠。请选择一个全新的、未使用过的范围。

### 产品名称歧义

**现象**：Agent 回复 `检测到产品名称歧义，请确认修改范围：`

**解决**：你提到的名称（如 `XPB`）可能与多个产品匹配。请明确回复要修改的具体产品，例如："只改 IPB" 或 "IPB 和 DPB 都改"。

### 新增 Routine 时 RID 已存在

**现象**：`RID 0xF200 already exists in target file`

**解决**：选择一个新的 RID 值。可以先扫描现有 RID 确认可用范围：
```bash
python scripts/orchestrator.py "扫描所有RID"
```

### 新增 Routine 时名称重复

**现象**：`Routine name RBAPLCUST_MyRoutine already exists`

**解决**：更换 `routine_name`。Routine 名称在同一 ARXML 文件中必须唯一。

### 信号格式错误

**现象**：`Invalid signal type 'UINT8_N(64)'` 或 `Unknown signal type 'INT16'`

**解决**：
- 数组类型必须带单位：`UINT8_N(64bit)` 或 `UINT8_N(8Byte)`，不能只写数字
- 支持的类型：UINT8/16/32, SINT8/16/32, BOOLEAN
- 检查是否有拼写错误

---

## 相关文档

- [SKILL.md](SKILL.md) — AI Agent 的详细操作指南（含各阶段指令、安全提示、脚本参考）
- [references/arxml-routine-structure.md](references/arxml-routine-structure.md) — AUTOSAR Routine XML 结构参考
- [CHANGELOG.md](CHANGELOG.md) — 版本历史与变更记录
