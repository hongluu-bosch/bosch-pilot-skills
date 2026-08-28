---
name: 31service-toolkit
version: 2.3.0
description: >
  Use this skill whenever the user mentions UDS Service 0x31 RoutineControl, RID management,
  routine identifiers, or adding/updating/deleting diagnostic RIDs in Bosch BSW projects.
---

# 31service-toolkit

Manage UDS Service 0x31 (RoutineControl) RIDs across Bosch BSW AUTOSAR configurations via natural language.

**Features:**
1. **Scan & Modify** existing RoutineControl RIDs (reassign, shift, clamp, map)
2. **Add new** DcmDspRoutine entries with signal definitions directly to ARXML files

## What this skill does

1. **Auto-locate** the project root by detecting `rb/as/` structure
2. **Scan** project arxml files to find all `DcmDspRoutine` configurations
3. **Parse** user's natural language requirement into a structured command
4. For existing RIDs:
   - **Calculate** target new RID values for each routine
   - **Validate** and detect conflicts (duplicate RIDs, inconsistent mappings)
   - **Generate** a unified diff preview + Excel change summary for review
   - **Apply** updates back to the original arxml files (after confirmation or with `--yes`)
5. For new routines:
   - **Parse** signal definitions from natural language input
   - **Validate** RID and routine name uniqueness
   - **Generate** complete `DcmDspRoutine` XML fragments
   - **Insert** into target ARXML files at the correct location
   - **Validate** insertion with XML re-parsing

## Python environment

- Python 3.11+ required
- Install dependencies: `pip install openpyxl`
- All scripts are in `<skill-path>/scripts/`

## Project root auto-detection

The skill **strictly** discovers the project workspace root via auto-detection:

- Starts from the current working directory
- Walks **upward** through parent directories
- A valid root must contain at least one direct subdirectory with **all** of:
  - `rb/` folder
  - `rba/` folder
  - `rb/as/` subfolder
- Returns the **topmost** (outermost) directory matching this pattern
- Example: if cwd is `C:\Projects\<project-root>\<variant>\rb\as\...`,
  the resolved root is `C:\Projects\<project-root>`

If no matching structure is found, the skill aborts with an error message.
**Manual override of the project root is not supported.**

## Workspace layout

The skill creates its workspace on first run:

```
<project-root>/                          ← auto-discovered (e.g., <project-root>)
├── rb/as/...                            ← Bosch BSW tree (read + write)
└── .DCOM_AI/
    └── 31Service_Toolkit_PRJ/
        ├── outputs/
        │   ├── rid_changes_YYYYMMDD_HHMMSS.diff    ← Unified diff preview
        │   └── rid_changes_summary.xlsx             ← Change summary Excel
        └── state/
            ├── scan_metadata.json       ← Scan record
            ├── routines.json            ← Raw scan results
            └── update_log_*.json        ← Update audit trail
```

## Supported natural language commands

### A. Sequential range assignment
Assign all RIDs in sorted order (by ProductType then current RID ascending) into a contiguous range.

> *"把所有RID顺序分配到 0xF100-0xF1FF"*
> *"assign all RIDs sequentially to 0xA100-0xA1FF"*

- Fails if the range is smaller than the number of routines

### B. Offset / shift
Shift all RIDs uniformly so the minimum RID becomes the target value.

> *"把所有RID平移到 0xF100 起始"*
> *"shift all RIDs to start at 0xB000"*

- Fails if any shifted RID exceeds 0-65535

### C. Clamp to range
Only modify RIDs that fall outside the specified range.

> *"确保所有RID在 0xF100-0xF1FF 范围内"*
> *"clamp all RIDs within 0x1000-0x1FFF"*

- RIDs already inside the range are left unchanged

### D. Explicit value mapping
Map specific old RID values to specific new values.

> *"把 0xF100 改成 0xA100，0xF101 改成 0xA101"*
> *"map 0xF200 to 0xA200, 0xF201 to 0xA201"*

- Unmentioned RIDs are left unchanged

### E. Pattern (mask) mapping
Map RIDs matching a high-byte pattern, preserving the low byte.

> *"把 0xF1xx 全部改成 0xA1xx"*
> *"replace 0xF2xx with 0xB2xx"*

- `xx` or `??` acts as wildcard for the low byte

### F. Name-based mapping
Map specific routines by their SHORT-NAME.

> *"把 Routine_FactoryReset 改成 0xA100"*
> *"set Routine_Bleed to 0xB200"*

- Name matching is case-insensitive fallback

---

## Adding New Routines (新增诊断服务)

### Command format

Add new DcmDspRoutine entries with complete signal definitions:

> *"新增routine Common RID=0xF200 routine_name=TestRoutine signals_start_in=UINT8+UINT16"*
> *"add routine IPB RID=0x3100 routine_name=FactoryReset signals_start_in=UINT8 signals_start_out=UINT8"*

**Required parameters:**
- `routine_name`: Short name (without `RBAPLCUST_` prefix, auto-added)
- `RID`: Explicit RID value (decimal or hex, e.g., `0xF200`)
- `product`: Target product type (Common, IPB, ESP, DPB, etc.)

**Optional signal parameters:** (omit = use default or no container)
- `signals_start_in`: Start routine input signals
- `signals_start_out`: Start routine output signals (default: `UINT8_N(8bit)` if omitted)
- `signals_stop_out`: Stop routine output signals
- `signals_result_out`: Request result output signals

### Signal format

Use compact type literals, separated by `+`, `,`, or `和`:

| Type | Example | Size |
|------|---------|------|
| `UINT8` / `SINT8` / `BOOLEAN` | `UINT8` | 8 bit |
| `UINT16` / `SINT16` | `UINT16` | 16 bit |
| `UINT32` / `SINT32` | `UINT32` | 32 bit |
| `UINT8_N(n)` / `UINT16_N(n)` / `UINT32_N(n)` | `UINT8_N(64bit)` | n bits |
| `SINT8_N(n)` / `SINT16_N(n)` / `SINT32_N(n)` | `SINT8_N(8Byte)` | n bits |

**Array types must include unit:**
- ✅ `UINT8_N(64bit)` — 64 bits
- ✅ `UINT8_N(8Byte)` — 64 bits (8 bytes)
- ❌ `UINT8_N(64)` — **rejected** (missing unit)

**Auto-layout:** Signal position (`pos`) and length are computed automatically from left to right.

**Examples:**
- `UINT8 + UINT16` → Signal_0 (pos=0, len=8), Signal_1 (pos=8, len=16)
- `UINT32_N(128bit)` → Signal_0 (pos=0, len=128)
- `UINT8, UINT8, UINT16` → 3 signals with auto positions

### Defaults

If signal parameters are omitted:
- `signals_start_out` omitted → defaults to `UINT8_N(8bit)` (1 byte)
- `signals_stop_out` / `signals_result_out` omitted → no container created
- `signals_start_in` omitted → no `StartRoutineIn` container

### Authorization

All new routines automatically reference:
```
/Dcm/DcmConfigSet/DcmDsp/DcmDspCommonAuthorization_ExtEol
```

### Common file selection

When adding to **Common** product with multiple ARXML files, the agent will:
1. List all Common variant files
2. Ask user to select by number (e.g., `1` or `1,3,5`)
3. Or type `all` to insert into all Common files

> Example: User says *"新增routine Common RID=0xF200 routine_name=TestRoutine"*
> - Agent: *"检测到 Common 配置存在 5 个 ARXML 文件，请选择目标文件编号..."*
> - User: *"2"* → inserts into file #2 only

### Validation

Before insertion, the skill validates:
1. **RID uniqueness** — No duplicate RIDs in target file(s)
2. **Name uniqueness** — No duplicate routine names in target file(s)
3. **XML well-formedness** — Target file parses successfully after insertion
4. **Signal validity** — Type names and array lengths are valid

### Workflow for adding routines

```python
from orchestrator import run_workflow

# Phase 1: Parse and preview (for Common, may need file selection)
result = run_workflow("新增routine Common RID=0xF200 routine_name=TestRoutine", dry_run=True)

# If Common file selection needed:
# result["status"] == "need_common_file_selection"
# User picks file(s), then:

# Phase 2: Apply with selected file
result = run_workflow(
    "新增routine Common RID=0xF200 routine_name=TestRoutine",
    file_hint="2"  # or "all" for all Common files
)
```

---

## Product Recognition Rules

When the user mentions product names (e.g., IPB, RBU, ESP) in their requirement, the skill follows these rules:

### 1. Explicit mention = modify; unmentioned = unchanged
If the user explicitly names one or more products, **only those products are modified**. All other products are automatically excluded and remain unchanged.

> Example: *"把 IPB 和 RBU 的 RID 分配到 0x3000-0x30FF"*
> - IPB → modified
> - RBU → modified
> - ESP, DPB, Common → **unchanged (no confirmation needed)**

### 2. Ambiguous product names require clarification
When the user mentions a product name that is **similar** to other existing products, the skill stops and asks for clarification.

**Similarity criteria:**
- **Prefix containment**: shorter is prefix of longer (e.g., `IPB` vs `IPB11`, `ESP` vs `ESPCL`)
- **Shared substring ambiguity**: a mentioned name matches multiple products via substring (e.g., `X` matches both `IPB` and `DPB`)
- **Known alias expansion**: pre-defined aliases (e.g., `XPB` maps to both `IPB` and `DPB`)

> Example: User says *"把 XPB 的 RID 改成 0xA100"*
> - Agent responds: *"检测到产品名称歧义：'XPB' 可能指 IPB 或 DPB。请确认修改范围。"*

### 3. Distinct names are independent entities
Products with clearly different names are treated as independent. No confirmation is needed for unmentioned products.

> Example: *"把 IPB 的 RID 平移到 0x3000"*
> - IPB → modified
> - RBU, DPB, ESP, Common → unchanged (no prompt)

### 4. No explicit product = apply to all
If the user does **not** mention any product name, the command applies to **all** products (existing behavior).

> Example: *"把所有 RID 顺序分配到 0xF100-0xF1FF"*
> - All products included

## Common (通用配置) 特殊处理规则

Common 类型代表通用配置，其 routine 可能存在于多个 arxml 文件中。针对 Common 的特殊行为如下：

### 1. Common 同名 routine 跨文件共享 RID
当执行顺序分配时，Common 中同名 routine 在所有 arxml 文件中共享相同的 RID。系统会先对 Common 的 `short_name` 去重，再分配连续 RID。

> Example: `RBAPLCUST_FactoryReset` 存在于 `EcucValues.arxml` 和 `EcucValues_SingleCANID.arxml` 中
> - 分配后：两个文件中的 `RBAPLCUST_FactoryReset` 均使用 **相同的新 RID**
> - 实际占用范围可能小于 Common routine 总数（因为去重）

### 2. 顺序分配时 Common 始终优先
无论用户提到产品的顺序如何，**Common 始终排在第一位分配**，其余产品按用户提到的先后顺序接续。

> Example: *"把 IPB 和 Common 的 RID 顺序分配到 0x3000-0x30FF"*
> - 实际分配顺序：Common 先（0x3000 起），然后 IPB（Common 结束后接续）
> - 等价于：*"把 Common 和 IPB 的 RID 顺序分配到 0x3000-0x30FF"*

### 3. Common 自动同步机制
当用户只提到非 Common 产品（未提 Common）时：

- **首次**：Common 自动加入修改列表，跟随分配。
  - Preview 中标注：*"Common 将自动跟随分配（首次同步）"*
  - Apply 成功后保存同步状态到 `.DCOM_AI/31Service_Toolkit_PRJ/state/common_auto_sync.json`
- **后续**：不再自动加入 Common，保持已同步状态不变。
  - Preview 中标注：*"Common 已在此前同步，本次保持不变"*
- **例外**：如果用户**明确提到 Common**（无论此前是否同步过），按用户要求执行。

> Example 1: 首次执行 *"把 IPB 的 RID 分配到 0x3000-0x30FF"*
> - Common 自动跟随，实际修改：Common + IPB
>
> Example 2: 后续执行 *"把 ESP 的 RID 分配到 0x3100-0x31FF"*
> - Common 已同步过，不再自动跟随，只修改 ESP
>
> Example 3: 后续执行 *"把 Common 的 RID 重新分配到 0x2000-0x20FF"*
> - 用户明确提到 Common，按用户要求重新分配

### 4. 重置 Common 同步状态
如需允许 Common 再次自动同步（例如需要为 Common 分配新范围）：

```bash
python <skill-path>/scripts/orchestrator.py --reset-common-auto
```

此命令会删除 `common_auto_sync.json`，下次执行非 Common 产品修改时 Common 将再次自动跟随。

### 5. 跨命令范围重叠检测
系统会检测本次分配范围与历史分配范围是否重叠：
- **不同产品之间**：范围不允许重叠（各自独立）
- **同一产品历史范围**：不允许重叠（防止覆盖已分配 RID）

如果检测到重叠，返回 `range_overlap` 错误并提示用户：
> *"Product 'IPB' new range 0x3000-0x3043 overlaps with previously assigned range 0x3000-0x3043. Please use --reset-common-auto or specify a non-overlapping range."*

## Workflow

### Phase 1 — Parse & Preview

The agent receives a natural language requirement, runs the orchestrator:

```bash
python <skill-path>/scripts/orchestrator.py "<requirement>" [--dry-run]
```

This will:
1. Auto-resolve the project root
2. Scan all `Dcm_CusDiag_Services*.arxml` files
3. Parse the requirement into a command
4. **Detect ambiguous product names and stop for clarification if needed**
5. Calculate new RIDs for each routine (only for explicitly mentioned products)
6. Detect conflicts and abort if any
7. Generate:
   - **Unified diff**: `.DCOM_AI/31Service_Toolkit_PRJ/outputs/rid_changes_*.diff`
   - **Summary Excel**: `.DCOM_AI/31Service_Toolkit_PRJ/outputs/rid_changes_summary.xlsx`
8. Display a preview of the first ~50 changes, including a note about skipped products

**[AGENT STOP]** After preview, tell the user:
> "I found {N} routines to modify across {M} files."
> "The following products will be modified: {product_list}"
> "The following products are unchanged: {skipped_list}"
> ""
> "A diff preview and summary Excel have been generated:"
> "  Diff: `<project-root>/.DCOM_AI/31Service_Toolkit_PRJ/outputs/rid_changes_*.diff`"
> "  Excel: `<project-root>/.DCOM_AI/31Service_Toolkit_PRJ/outputs/rid_changes_summary.xlsx`"
> ""
> "Please review and reply with **'确认'** or **'yes'** to apply the changes."
> "Reply with **'取消'** or **'cancel'** to abort."

### Phase 2 — Confirmation

The user reviews the diff/Excel and responds.

### Phase 3 — Apply (or use `--yes` to skip confirmation)

After user confirms, re-run with `--yes`:

```bash
python <skill-path>/scripts/orchestrator.py "<requirement>" --yes
```

Or, if the agent handles confirmation internally, call:

```python
from orchestrator import confirm_and_apply
confirm_and_apply("<requirement>")
```

This will:
1. Apply RID changes to the original arxml files (pure text replacement)
2. Save an audit log JSON under `state/`
3. Report success/failure

### Dry-run mode

To preview without modifying any files:

```bash
python <skill-path>/scripts/orchestrator.py "<requirement>" --dry-run
```

Generates diff + Excel but does not touch arxml files.

## Validation rules

The skill enforces these rules automatically:

1. **Format**: Accepts decimal (`1234`) or hex (`0x04D2`). Case insensitive.
2. **Range**: Must be `0–65535` (16-bit) / `0x0000–0xFFFF`
3. **Uniqueness check**: Error if same new RID assigned to different routines
4. **Consistency check**: Error if same routine name gets different new RIDs across files
5. **No-op detection**: Skips if new RID equals current RID
6. **Range capacity**: Sequential assign fails if range < number of routines in scope
7. **Overflow check**: Offset shift fails if any result exceeds 0-65535
8. **Product scope**: Only routines from explicitly mentioned products are modified; others are preserved

## What gets modified

**Only** the `<VALUE>` inside `DcmDspRoutineIdentifier` parameters is changed.

The `apply` command uses **pure text replacement** that locates the target routine by its `SHORT-NAME`, then replaces the first `<VALUE>` after the `DcmDspRoutineIdentifier` definition reference within that routine's container. This guarantees:

- XML declaration format (quotes, encoding) is preserved exactly
- XML comments (`<!-- ... -->`) are preserved
- Original indentation, whitespace, and line endings are preserved
- No other parameters or containers are touched

**NOT** modified:
- Routine `SHORT-NAME`
- Start/Stop function names (`DcmDspStartRoutineFnc`)
- Signal definitions (length, type, endianness, position)
- Authorization references
- Any other ECUC parameters

## Safety notes

- **No backup**: Original arxml files are modified in-place. Ensure the project is under version control before applying updates.
- **Direct write**: Changes are written directly to files in `rb/as/.../RBAPLCust/cfg/`. Do not modify files outside this path.
- **Product isolation**: RIDs from different product folders are tracked separately, but updates are applied per-file based on the `ARXML_File_Path`.
- **Confirmation gate**: By default, the skill stops for human confirmation before writing. Use `--yes` only in automated pipelines.

## Diff output format

The generated `.diff` files use **unified diff** format:

```diff
--- rb/as/IPB/core/app/dcom/RBAPLCust/cfg/IPB/Dcm_CusDiag_Services_IPB.arxml
+++ rb/as/IPB/core/app/dcom/RBAPLCust/cfg/IPB/Dcm_CusDiag_Services_IPB.arxml
@@ -1234,7 +1234,7 @@
                 <DEFINITION-REF DEST="ECUC-INTEGER-PARAM-DEF">/Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine/DcmDspRoutineIdentifier</DEFINITION-REF>
-                <VALUE>61728</VALUE>
+                <VALUE>61696</VALUE>
```

Diff headers include metadata:
```
# 31service-toolkit RID Change Diff
# Generated: 2026-06-08 14:30:00
# Command: "把所有RID平移到 0xF100 起始"
# Total changes: 42 routines in 3 files
```

## Scripts reference

| Script | Purpose |
|---|---|
| `orchestrator.py` | Main entry point — auto root resolution, workflow orchestration |
| `scan_routines.py` | Extract routines from arxml files |
| `requirement_parser.py` | Parse natural language into structured commands (includes ADD_ROUTINE) |
| `rid_calculator.py` | Compute new RIDs + conflict detection |
| `rid_adder.py` | Add new DcmDspRoutine entries to ARXML files |
| `signal_parser.py` | Parse natural language signal strings into structured definitions |
| `arxml_inserter.py` | Generate DcmDspRoutine XML fragments and insert into ARXML |
| `diff_generator.py` | Generate unified diff previews |
| `generate_excel.py` | Export change summary Excel (no longer reads input) |
| `update_arxml.py` | Apply RID changes back to arxml (text replacement) |
| `validate_rid.py` | Parse and validate RID input strings |
| `arxml_utils.py` | XML parsing helpers (namespace, container extraction) |
| `product_resolver.py` | Product name extraction, similarity detection, ambiguity resolution |

## Troubleshooting

**"Could not find project root"**
- Ensure you are running from within the project tree (any subdirectory under the root)
- Verify the project has a direct subdirectory containing `rb/`, `rba/`, and `rb/as/`
- Manual override is not supported — the skill relies strictly on auto-detection

**"No routines found"**
- Check that the project has `rb/as/**/core/app/dcom/RBAPLCust/cfg/**/Dcm_CusDiag_Services*.arxml`

**"Conflicts detected"**
- The calculated changes would assign the same RID to different routines
- Revise your requirement (e.g., expand the target range)

**"Range too small"**
- Sequential assign: the specified range has fewer values than routines
- Expand the range or use offset shift instead

**"RID out of range after shift"**
- Offset shift would push some routines beyond 0xFFFF
- Choose a lower target start value

**"Range overlap detected"**
- The new RID range overlaps with a previously assigned range for the same product, or with another product's range
- Different products must use independent RID ranges
- Specify a non-overlapping range or use `--reset-common-auto` if Common sync is involved

**"Ambiguous product names"**
- A mentioned product name is similar to multiple existing products (e.g., `XPB` matches both `IPB` and `DPB`)
- Ask the user to clarify: "Only modify X" or "Modify X and Y"

## Reference

For detailed AUTOSAR Routine XML structure, see:
[`references/arxml-routine-structure.md`](references/arxml-routine-structure.md)

## Changelog

### v2.2.0
- **Add new routines**: Support adding new DcmDspRoutine entries to ARXML files via natural language.
  - `add_routine` / `新增routine` command type
  - Automatic signal parser: compact type literals (`UINT8+UINT16`, `UINT8_N(64bit)`) with auto-layout
  - Defaults: `signals_start_out` → `UINT8_N(8bit)`; omitted `stop_out`/`result_out` → no container
  - Fixed authorization: `DcmDspCommonAuthorization_ExtEol`
  - Interactive Common file selection when multiple Common ARXML variants exist
  - RID and routine name uniqueness validation before insertion
  - Post-insertion XML well-formedness validation
- New scripts: `rid_adder.py`, `signal_parser.py`, `arxml_inserter.py`
- Updated `requirement_parser.py` to recognize `add_routine` commands
- Updated `orchestrator.py` to route `add_routine` to the new workflow

### v2.1.0
- **Strict project root auto-detection**: Removed `--project-root` CLI parameter and manual override support to prevent workspace misplacement.
- **Product Recognition Rules**: Added explicit product mention detection, ambiguity resolution (prefix containment + shared substring), and automatic scope isolation.
- **Common auto-sync**: First-time modification of non-Common products automatically includes Common routines; subsequent runs preserve synced state.
- **Range overlap detection**: Prevents different products from sharing RID ranges and blocks re-assigning ranges already used by the same product historically.
- Added `--reset-common-auto` CLI flag to reset Common sync state.

### v2.0.0
- Replaced Excel-based user input with natural language command parsing
- Added 6 command types: sequential assign, offset shift, clamp, explicit map, pattern map, name map
- Added automatic project root resolution (walks up to find topmost `rb/as/`)
- Added unified diff generation for change preview
- Added `--dry-run` and `--yes` modes
- Removed Phase 1/2/3 Excel workflow; now single-pass with confirmation gate
