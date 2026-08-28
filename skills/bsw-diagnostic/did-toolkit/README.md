# did-toolkit 用户操作指南

从客户诊断问卷提取 DID 信息，生成 FSCS、ARXML、C 代码，可选上传 DOORS。

```
诊断问卷 .xlsx ──► 提取 DID ──► 编辑 FSCS ──► 生成代码 ──► (可选) 上传 DOORS
```

---

## 准备工作

### 1. 安装 Skill

从 [GitLab](https://bdo-repo.apac.bosch.com/bdo-scms/skill-management-dev/ne/ne-sw/dcom/approved/did-toolkit) 下载 skill zip 包。

解压到：

```
C:\Users\<你的NT账号>\.config\opencode\skills
```

⚠️ **注意**：如果解压出来的文件夹名字带 `-main` 后缀（如 `did-toolkit-main`），**请手动删除 `-main`**，只保留 `did-toolkit`。

### 2. 准备项目目录

打开你的 workspace（Bosch 项目根目录），新建目录：

```
.DCOM_AI\DID_Toolkit_PRJ\inputs
```

把客户的**诊断问卷**（`.xlsx` 或 `.xlsm`）放进这个目录。

> 只放 `.xlsx`，**不要**放 JSON 文件——JSON 由 Agent 自动生成。

### 3. 安装依赖

```bash
pip install -r scripts/requirements.txt
```

---

## 第一步：提取 DID

在 OpenCode 的 Agent 对话框中，输入提示词，例如：

```
帮我从当前项目的诊断问卷中提取 22/2E 服务的 DID 信息，生成 FSCS
```

Agent 会自动完成以下工作：

1. 读取 `inputs/` 目录下的诊断问卷
2. 提取所有 DID 信息
3. 生成结构化的 FSCS 数据
4. 输出 Excel 表格供你检查和编辑

⏳ 等待完成，期间不需要手动操作。完成后 Agent 会提示你进行下一步。

---

## 第二步：编辑 FSCS

Agent 会生成一个 Excel 表格，这是你**唯一需要手动编辑的文件**。

**文件位置：**

```
<workspace>\.DCOM_AI\DID_Toolkit_PRJ\outputs\fscs\fscs_edit.xlsx
```

用 Excel 或 WPS 打开，检查并编辑以下内容：

| 列 | 操作 |
|---|---|
| `used_flag` | `FALSE` 排除该 DID（不要删行，只改标记） |
| `Product_Type` | 适用产品，如 `DPB`、`ESP`、`Common`（全部产品） |
| `behavior` | **重点**：函数实现描述，见下方填写指南 |

### behavior 列填写指南

根据 `Storage Position`（存储位置）分类填写：

#### EEPROM

Agent 已自动生成默认的 NVM item 名称，如需修改，直接编辑即可。

示例：

```c
NVM_ReadBlock(NvMConf_NvMBlockDescriptor_DID_F190, &rb_f190_VehicleIdentificationNumber[0]);
```

#### ROM / Flash

Agent 已生成 Hard Code 模板，按需求填写具体数值。

示例：

```c
C_DID_VehicleIdentificationNumber_Byte0_UB = 0x33;
C_DID_VehicleIdentificationNumber_Byte1_UB = 0x36;
C_DID_VehicleIdentificationNumber_Byte2_UB = 0x39;
C_DID_VehicleIdentificationNumber_Byte3_UB = 0x30;
C_DID_VehicleIdentificationNumber_Byte4_UB = 0x33;
// ... 按实际字节数继续
```

#### RAM

Agent 已生成 `interface:` 占位符，需自行补充具体接口和赋值逻辑。

示例：

```c
interface:
NMSG_VehicleSpeed_Signal

// → 具体的赋值逻辑，包括 factor、offset 等
rb_did_value = (uint16)(NMSG_VehicleSpeed_Signal * 0.01f);
```

编辑完成后**保存 Excel**，回到 OpenCode，告诉 Agent 继续。

---

## 第三步：导回并生成

Agent 会根据你编辑后的 Excel **自动导回**，然后生成：

- **ARXML 配置** → 直接写入 Bosch 项目树
- **C 代码** → 按产品和存储位置生成
- **Validation 报告** → 代码检查
- **Review 报告** → 人工审查辅助

所有产物都在：

```
.DCOM_AI\DID_Toolkit_PRJ\outputs\
```

生成完成后，回到代码中检查生成内容是否正确。

> **安全提示**：已存在的代码文件不会被覆盖（skip-on-conflict），你手改过的内容会保留。

---

## 第四步（可选）：上传 DOORS

如需将 FSCS 上传到 DOORS，继续以下步骤。

### 1. 配置 DOORS 模块 UUID

打开文件：

```
.DCOM_AI\DID_Toolkit_PRJ\inputs\doors_mapping.yaml
```

找到以下两项，填入你的 DOORS 模块 UUID：

```yaml
doors:
  document_uuid: "<你的DOORS内容模块UUID>"

links:
  enabled: true
  link_module_uuid: "<你的DOORS链接模块UUID>"
```

如暂时不需要建立 Link，可将 `links.enabled` 设为 `false`。

> 一个项目只需配置一次。后续如需修改，直接编辑此文件或让 Agent 帮你改。

### 2. 保存配置，让 Agent 继续

告诉 Agent 配置已完成，Agent 会继续执行上传流程。

### 3. 认证（首次需要）

首次上传时，Agent 会要求你提供 DOORS 登录凭据。

⚠️ **安全警告**：

- **绝对不要**在 OpenCode 的 Agent 对话框中输入你的密码
- 请在 **本地 CMD 终端** 中执行以下命令（替换 `<NT>` 和 `<密码>`）：

```bash
python scripts/fscs/doors/doors_sync.py --user-nt <NT> --password <密码> --save-credentials --no-upload
```

- 执行一次后，账号密码会自动保存到系统密钥环，后续不再需要输入

### 4. 完成上传

认证完成后，确认继续，Agent 会完成：

1. 下载现有 DOORS 文档
2. 找到 `$22` 和 `$2E` 的标题位置
3. 在标题下方插入新的 FSCS 条目
4. 建立 CS → FS 的 Link

上传使用的 xlsx 文件会生成在：

```
.DCOM_AI\DID_Toolkit_PRJ\outputs\doors\
```

你可以自行预览这些 xlsx，如有需要可手动修改后再上传。

---

## 常见问题

### Q1：找不到 `fscs_edit.xlsx`

确认 Phase 1 已完成。完整路径：

```
<workspace>\.DCOM_AI\DID_Toolkit_PRJ\outputs\fscs\fscs_edit.xlsx
```

如果 outputs 目录为空，请重新执行第一步（提取 DID）。

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

检查 `fscs_edit.xlsx` 中的 `Product_Type` 列是否已填写。填好后重新运行 xlsx-import 和 DOORS 上传。

### Q5：我之前手改的代码会被覆盖吗？

**不会**。已存在的文件（ARXML 中的条目、C 文件、Header 定义、PDM 行）会自动跳过（skip-on-conflict）。只有新生成的文件才会写入。

---

## 重要约定

1. **唯一需要手动编辑的文件**：`fscs_edit.xlsx`。其他 JSON、ARXML、C 文件都由 Agent 自动生成。
2. **不要手动删除 outputs 目录下的文件**：Agent 依赖这些文件做增量判断。
3. **密码安全**：永远不要在聊天窗口粘贴密码，只在本地 CMD 中执行认证命令。
4. **版本控制建议**：提交 `inputs/*_did.json`、`config/project.json` 和 `extract_*.py`；`outputs/` 完全可重新生成，不要提交。
