# 19service-toolkit 用户操作指南

从客户诊断问卷提取 UDS Service 0x19（Read DTC Information）冻结帧（Freeze Frame）信息，生成 FSCS、ARXML、C 代码，可选上传 DOORS。

```
诊断问卷 .xlsx ──► 提取冻结帧 DID ──► 编辑 FSCS ──► 生成 ARXML / C ──► (可选) 上传 DOORS
```

---

## 准备工作

### 1. 安装 Skill

从 [GitLab](https://bdo-repo.apac.bosch.com/bdo-scms/skill-management-dev/ne/ne-sw/dcom/approved/19service-toolkit) 下载 skill zip 包。

解压到：

```
C:\Users\<你的NT账号>\.config\opencode\skills
```

⚠️ **注意**：如果解压出来的文件夹名字带 `-main` 后缀（如 `19service-toolkit-main`），**请手动删除 `-main`**，只保留 `19service-toolkit`。

### 2. 准备项目目录

打开你的 workspace（Bosch 项目根目录），新建目录：

```
.DCOM_AI\19Service_Toolkit_PRJ\inputs
```

把客户的**诊断问卷**（`.xlsx` 或 `.xlsm`）放进这个目录。

> 诊断问卷中应包含 `$19` / `19service` / `snapshot` / `freezeframe` / `冻结帧` 等名称的工作表，工具会自动识别。

### 3. 安装依赖

```bash
pip install -r scripts/requirements.txt
```

---

## 第一步：初始化并提取冻结帧 DID

在 OpenCode 的 Agent 对话框中，输入提示词，例如：

```
帮我从当前项目的诊断问卷中提取 19 服务的冻结帧 DID 信息，生成 FSCS
```

Agent 会自动完成以下工作：

1. 读取 `inputs/` 目录下的诊断问卷
2. 识别 `$19` / `snapshot` / `freezeframe` 等工作表
3. 提取所有冻结帧 DID 信息
4. 生成结构化的 FSCS 数据
5. 输出 Excel 表格供你检查和编辑

⏳ 等待完成，期间不需要手动操作。完成后 Agent 会提示你进行下一步。

### 关于 `--init-project`

`--init-project` 是一个可恢复的状态机，每次调用只向前推进一步：

- **FRESH** → 新建 workspace 骨架（config、inputs、outputs、scripts、state 目录）
- **FOLDERS_ONLY** → 等待你把诊断问卷放进 `inputs/`
- **QUESTIONNAIRE_READY** → 扫描 Bosch 项目树，生成 `config/project.json`，需要你在提示词中提供 `--product-types`
- **COMPLETE** → 下次运行自动进入 Phase 1

示例命令：

```bash
cd /path/to/my-bosch-project
python /path/to/skill/scripts/pipeline.py --init-project --product-types Common,RBU,IPB
```

> `Product_Type` 必须由你**显式提供**，Agent 不会从文件名或项目结构猜测。

---

## 第二步：编辑 FSCS

Agent 会生成一个 Excel 表格，这是你**唯一需要手动编辑的文件**。

**文件位置：**

```
<workspace>\.DCOM_AI\19Service_Toolkit_PRJ\outputs\fscs\fscs_edit.xlsx
```

用 Excel 或 WPS 打开，检查并编辑以下内容：

| 列 | 操作 |
|---|---|
| `used_flag` | `Y` 启用，`N` 排除该 DID（不要删行，只改标记） |
| `Product_Type` | 适用产品，如 `Common`、`RBU`、`IPB`（多个产品用逗号分隔） |
| `record_number` | 快照记录号，默认 `0x01, 0xFF`；按需修改 |
| `impl_notes` | **重点**：实现描述，见下方填写指南 |
| `resolution` / `offset` | 缩放因子和偏移量，会从问卷自动解析，可手动修正 |

### impl_notes 列填写指南

`impl_notes` 是 Phase 3 自动填充 C 代码的核心输入。用简单、明确的格式书写，Agent 更容易理解：

```
Data[0] = SignalA;
if Qualifier_N == C_Qualifier_Normal_N then Data[1] = SignalB else Data[1] = 0xFF;
bit0=SignalC; bit1=SignalD;
byte0 uses SignalA; byte1 uses SignalB;
low nibble SignalA; high nibble SignalB;
SignalA * 0.1; resolution=0.1 offset=0
```

常见写法：

- **直接字节赋值**：`Data[0] = NMSG_VehicleSpeed;`
- **条件赋值**：`if SpeedQualifier == Normal then Data[1] = Speed else Data[1] = 0xFF;`
- **位打包**：`bit0=AVH_Active; bit1=EPB_Active;`
- **高低 nibble**：`low nibble SignalA; high nibble SignalB;`
- **缩放**：`Data[2] = (uint8)(BatteryVoltage * 10);`

编辑完成后**保存 Excel**，回到 OpenCode，告诉 Agent 继续。

---

## 第三步：导回并生成

Agent 会根据你编辑后的 Excel **自动导回**，然后按你选择的 branch 生成：

### Phase 2 — ARXML

将冻结帧配置写入 Bosch 项目树：

```bash
python scripts/pipeline.py --phase arxml
```

写入目标：

```
rb/as/<customer>/core/app/dsm/Cubas_DEM/DemEnvData_RBAPLCUST_EcucValues[.<suffix>].arxml
```

### Phase 3 — C 代码

生成每个 DID 的 snapshot read function stub：

```bash
python scripts/pipeline.py --phase c
```

写入目标：

```
rb/as/<customer>/core/app/dcom/RBAPLCust/src/<PT>/RBAPLCUST_19Snapshot_<DID>_<Name>.c
```

Phase 3 结束时如果是 `[AGENT TODO] X fill / Y stub`：

- **fill**：Agent 会尝试根据 `impl_notes` 自动填充真实实现
- **stub**：证据不足，保留 `TODO(agent)` 块，需要后续手动实现

### 产物目录

所有产物都在：

```
.DCOM_AI\19Service_Toolkit_PRJ\outputs\
```

包含：

- `fscs/fscs.json` — 权威 FSCS 数据源
- `fscs/FSCS_19.txt` — 可读格式的 19 服务 FSCS
- `fscs/fscs_review_report.txt` — 审查报告
- `arxml/merge_report_<PT>.txt` — ARXML 合并报告
- `c/<PT>/generation_report.txt` — C 代码生成报告
- `doors/doors_upload_19.xlsx` — DOORS 上传文件（Phase 4 生成）

> **安全提示**：已存在的代码文件、ARXML 容器不会被覆盖（skip-on-conflict），你手改过的内容会保留。

---

## 第四步（可选）：上传 DOORS

如需将 FSCS 上传到 DOORS，继续以下步骤。

### 1. 配置 DOORS 模块 UUID

打开文件：

```
.DCOM_AI\19Service_Toolkit_PRJ\inputs\doors_mapping.yaml
```

填入 DOORS 模块 UUID：

```yaml
module_uuid: "<你的DOORS内容模块UUID>"
anchor:
  keyword: "<锚点关键词>"   # 用于在 DOORS 中定位插入位置
defaults:
  # 默认值，按项目 DOORS 属性填写
role_values:
  FS:
    # 正向需求行属性
  CS:
    # 客户需求行属性
value_maps:
  RB_Product:
    # Product_Type 到 RB_Product 列的映射
```

> 一个项目只需配置一次。后续如需修改，直接编辑此文件或让 Agent 帮你改。

### 2. 保存配置，让 Agent 继续

告诉 Agent 配置已完成，Agent 会继续执行上传流程。

### 3. 认证（首次需要）

首次上传时，Agent 会要求你提供 DOORS 登录凭据。

⚠️ **安全警告**：

- **绝对不要**在 OpenCode 的 Agent 对话框中输入你的密码
- 请在 **本地 CMD 终端** 中执行以下命令（替换 `<NT>` 和 `<密码>`）：

```bash
python scripts/fscs_doors_sync.py --user-nt <NT> --password <密码> --save-credentials --no-upload
```

- 执行一次后，账号密码会自动保存到系统密钥环，后续不再需要输入

### 4. 完成上传

认证完成后，确认继续，Agent 会完成：

1. 下载现有 DOORS 文档
2. 找到锚点位置
3. 插入新的 FSCS 条目（FS / ARXML 行 + CS / C 代码行）
4. 生成上传报告

上传使用的 xlsx 文件会生成在：

```
.DCOM_AI\19Service_Toolkit_PRJ\outputs\doors\
```

你可以自行预览这些 xlsx，如有需要可手动修改后再上传。

---

## 常见问题

### Q1：找不到 `fscs_edit.xlsx`

确认 Phase 1 已完成。完整路径：

```
<workspace>\.DCOM_AI\19Service_Toolkit_PRJ\outputs\fscs\fscs_edit.xlsx
```

如果 outputs 目录为空，请重新执行第一步（提取冻结帧 DID）。

### Q2：生成 ARXML / C 代码时报错 `fscs.json missing`

必须先完成 Phase 1（提取 DID）和 xlsx-import（导回编辑后的 Excel）。运行：

```bash
python scripts/pipeline.py --phase fscs
```

编辑完 Excel 后，再运行：

```bash
python scripts/pipeline.py --phase xlsx-import
```

### Q3：DOORS 认证失败

- 检查 NT 账号和密码是否正确
- 确认在 **CMD 终端** 中执行了 `--save-credentials` 命令（不要在 Agent 对话框输入密码）
- 企业 DOORS 走 LDAP/AD，连续输错 3-5 次会锁账户，需联系 IT 解锁

### Q4：DOORS 中 `RB_Product` 列为空

检查 `fscs_edit.xlsx` 中的 `Product_Type` 列是否已填写，以及 `doors_mapping.yaml` 中的 `value_maps.RB_Product` 是否已映射。填好后重新运行 xlsx-import 和 DOORS 上传。

### Q5：我之前手改的代码会被覆盖吗？

**不会**。已存在的文件（ARXML 中的条目、C 文件）会自动跳过（skip-on-conflict）。只有新生成的文件才会写入。

### Q6：Phase 3 全是 `TODO(agent)` 怎么办？

检查 `impl_notes` 是否写得足够明确。返回 Phase 1 编辑 `fscs_edit.xlsx` 中的 `impl_notes` 列，保存后重新运行 `--phase xlsx-import` 和 `--phase c`。

---

## 重要约定

1. **唯一需要手动编辑的文件**：`fscs_edit.xlsx`。其他 JSON、ARXML、C 文件都由 Agent 自动生成。
2. **不要手动删除 outputs 目录下的文件**：Agent 依赖这些文件做增量判断。
3. **密码安全**：永远不要在聊天窗口粘贴密码，只在本地 CMD 中执行认证命令。
4. **版本控制建议**：提交 `inputs/` 中的诊断问卷、`config/project.json`；`outputs/` 完全可重新生成，不要提交。
5. **product_types 必须显式提供**：运行 `--init-project` 时一定要带上 `--product-types Common,RBU,...`，Agent 不会猜测。
