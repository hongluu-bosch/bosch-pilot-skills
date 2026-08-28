# diagcomm-toolkit 用户操作指南

将诊断通信（DiagComm）参数写入 CusDiag 协议栈 ARXML，并一键同步到 DOORS。

```
用户编辑 Excel → Agent 校验预演 → 用户确认 → 写入 ARXML → (可选) 生成 FSCS 上传 DOORS
```

---

## 准备工作

### 1. 安装 Skill

从 [GitLab](https://bdo-repo.apac.bosch.com/bdo-scms/skill-management-dev/ne/ne-sw/dcom/approved/diagcomm-toolkit) 下载 skill zip 包。

解压到：

```
C:\Users\<你的NT账号>\.config\opencode\skills
```

⚠️ **注意**：如果解压出来的文件夹名字带 `-main` 后缀（如 `diagcomm-toolkit-main`），**请手动删除 `-main`**，只保留 `diagcomm-toolkit`。

### 2. 初始化项目

在 OpenCode 中打开你的 workspace（Bosch 项目根目录），在对话框中输入提示词，例如：

```
帮我配置当前项目的 DiagComm 参数
```

Agent 会自动完成以下工作：
1. 在项目根目录建立工作区 `.DCOM_AI/DiagComm_Toolkit_PRJ/`
2. 生成空白 Excel 模板 `inputs/DiagComm.xlsx`
3. 自动扫描并匹配项目中的 ARXML 路径

⏳ 等待完成，期间不需要手动操作。完成后 Agent 会提示你进行下一步。

### 3. 安装依赖

```bash
pip install -r <skill>/scripts/requirements.txt
```

> `<skill>` 指 skill 安装路径，Windows 下通常为 `%USERPROFILE%\.config\opencode\skills\diagcomm-toolkit`。

---

## 第一步：编辑 Excel 参数

Agent 初始化完成后，这是你**唯一需要手动编辑的文件**。

**文件位置：**

```
<workspace>\.DCOM_AI\DiagComm_Toolkit_PRJ\inputs\DiagComm.xlsx
```

用 Excel 打开，按 Sheet 填写：

| Sheet | 内容 | 你何时需要改 |
|---|---|---|
| **Project & Parameters** | 项目名 + product_type + 23 个诊断参数 | **每次改参数都改这里** |
| **Paths & Options** | ARXML 路径模板 | **接入时一次**（标准布局自动识别，一般不用改） |
| **DOORS Upload** | DOORS 模块 UUID | **接入时一次**（要传 DOORS 时填） |
| **README** | 字段速查 | 只读 |

### 必填字段（9 个）

打开 Sheet 1 就能看到**红色高亮的必填格**，按提示填写：

| 字段 | 示例 | 说明 |
|---|---|---|
| `project.name` | `MyProject` | 项目名 |
| `project.product_type` | `ESP` | 下拉选择：DPB / ESP / IPB / RBU |
| `parameters.CAN_DLC.rx_frame_type` | `ClassicCAN` | 接收帧类型 |
| `parameters.CAN_DLC.tx_frame_type` | `ClassicCAN` | 发送帧类型 |
| `parameters.CAN_DLC.rx_dl` | `8` | 接收数据长度 |
| `parameters.CAN_DLC.tx_dl` | `8` | 发送数据长度 |
| `parameters.CAN_Functional_Request_ID` | `0x7DF` | 功能请求 ID |
| `parameters.CAN_Physical_Request_ID` | `0x7E0` | 物理请求 ID |
| `parameters.CAN_Response_ID` | `0x7E8` | 响应 ID |

> 其余 14 个参数为选填，留空将使用默认值。Excel 中下拉菜单和注释会引导你填写合法值。

**关于 Paths & Options：**
- Agent 已自动根据 workspace 扫描出 ARXML 路径，请检查是否正确
- 如果项目结构特殊（非标准 AUTOSAR 布局），可手动修改 `paths.dcom_root` 等字段

**关于 DOORS Upload：**
- 如需上传 DOORS，填入你的 DOORS 内容模块 UUID（替换占位符 `PUT-DOORS-DOCUMENT-UUID-HERE`）
- 暂时不需要上传可留空，后续再补

编辑完成后**保存 Excel**，回到 OpenCode，告诉 Agent 继续。

---

## 第二步：Agent 自动验证

在 OpenCode 对话框中输入提示词，例如：

```
帮我验证并预演一下刚才填的参数
```

Agent 会自动执行：

```
status → validate → apply --dry-run
```

完成后 Agent 会向你摘要：
- 哪些 ARXML 文件将会发生变化
- 哪几个参数值会改变（before → after）
- 是否有警告或错误

完整差异报告生成在：

```
<workspace>\.DCOM_AI\DiagComm_Toolkit_PRJ\outputs\diff_report.txt
```

---

## 第三步：确认并写入 ARXML

Agent 会问：**"Apply these changes? (yes/no)"**

- 回复 `yes` / `apply` / `go` → Agent 执行 `apply --apply`，按字节精确写入 ARXML
- 其他回复 → 回到第一步继续修改 Excel

写入成功后生成：

- `outputs/FSCS.txt` —— 一页式最终配置快照
- `outputs/diff_report.txt` —— 变更审计报告

> **回滚方式**：如对写入结果不满意，用项目 VCS 回滚  
> `git checkout -- <arxml>`（变更文件清单见 `diff_report.txt`）

---

## 第四步（可选）：上传 DOORS

如需将 FSCS 上传到 DOORS，继续以下步骤。

### 1. 确认 DOORS 配置

确保 `inputs/DiagComm.xlsx` 的 `DOORS Upload` Sheet 已填入模块 UUID。如未填写，Agent 会提示你补充。

### 2. 触发上传

在 OpenCode 中输入：

```
帮我生成 FSCS 并上传到 DOORS
```

Agent 会：
1. 生成当前 FSCS 文本
2. 下载现有 DOORS 文档
3. 找到诊断通讯标题位置
4. 在标题下方**插入新条目**（首次）或**更新已有条目**（后续）

### 3. 认证（首次需要）

首次上传时，Agent 会要求你提供 DOORS 登录凭据。

⚠️ **安全警告**：

- **绝对不要**在 OpenCode 的 Agent 对话框中输入你的密码
- 请在 **本地 CMD 终端** 中执行以下命令（替换 `<NT>` 和 `<密码>`）：

```bash
python <skill>\scripts\doors_sync.py --user-nt <NT> --password "<密码>" --save-credentials --no-upload
```

- 执行一次后，账号密码会自动保存到系统密钥环，后续不再需要输入

### 4. 完成上传

认证完成后，确认继续，Agent 会完成上传。

上传使用的 xlsx 文件会生成在：

```
<workspace>\.DCOM_AI\DiagComm_Toolkit_PRJ\outputs\doors_upload.xlsx
```

你可以自行预览这个 xlsx，如有需要可手动修改后再让 Agent 上传。

> **机制说明**：FSCS 是先 load 下来原本的 DOORS 文档，找到诊断通讯的标题，在下方分别插入新的项，或者根据之前 skill 上传 DOORS 的记录自动更新以前的项。

---

## 触发方式

在 OpenCode 对话框中输入以下**关键词**或**例句**，Agent 会自动加载本 skill：

**例句：**
```
Apply my DiagComm values.
把 CAN Response ID 改成 0x7E8 然后 apply。
帮我修改 P2 timer 到 60 ms，validate 后 apply。
CusDiag 配置走一遍：status → validate → apply --dry-run。
apply 完上传到 DOORS。
```

**关键词：**

| 类别 | 关键词 |
|---|---|
| 概念 | `diagcomm`, `DiagComm`, `CusDiag`, `诊断通信` |
| 操作 | `arxml 参数配置`, `写入 arxml`, `配置 CAN-TP`, `修改 DCM 超时`, `P2 timer`, `上传 DOORS`, `同步到 DOORS` |
| 参数名 | `product_type`, `CAN_Channel`, `CAN_ID_Format`, `Addressing_Method`, `CAN_DLC`, `CAN_Functional_Request_ID`, `CAN_Physical_Request_ID`, `CAN_Response_ID`, `N_As`, `N_Ar`, `N_Bs`, `N_Br`, `N_Cs`, `N_Cr`, `P2_Max`, `P2_Star_Max`, `BS`, `STmin`, `PaddingByte`, `StrictDlcCheck`, `NRC78_Times` |

---

## 常见问题

### Q1：`status` 报 `NEEDS-FILL` 怎么办？

Excel 还有必填格没填。打开 `inputs/DiagComm.xlsx`，把 Sheet 1 中**红色高亮**的格子填满，保存后告诉 Agent 继续。

### Q2：找不到 `inputs/DiagComm.xlsx`

确认 Agent 已完成初始化。如被误删，在项目根目录执行：

```bash
python <skill>/scripts/pipeline.py --init-project --force
```

### Q3：DOORS 认证失败

- 检查 NT 账号和密码是否正确
- 确认在 **CMD 终端** 中执行了 `--save-credentials` 命令（不要在 Agent 对话框输入密码）
- 企业 DOORS 走 LDAP/AD，连续输错 3-5 次会锁账户，需联系 IT 解锁

### Q4：想回滚上次 ARXML 写入

用项目 VCS 回滚：

```bash
git checkout -- <arxml>
```

变更文件清单在 `outputs/diff_report.txt` 中。

### Q5：我之前手改的代码/ARXML 会被覆盖吗？

**不会**。已存在的文件会自动跳过（skip-on-conflict），你手改过的内容会保留。只有新生成的参数节点才会写入。

### Q6：老版本如何迁移？

| 当前版本 | 迁移命令 |
|---|---|
| v1.20.x | `python <skill>/scripts/migrate_v1_20_to_v2.py --from-skill <project-root>/.agents/skills/diagcomm-toolkit` |
| v1.19.x | 先 `python <skill>/scripts/pipeline.py --init-project`，再 `python <skill>/scripts/migrate_v1_19_to_xlsx.py --legacy-from <旧JSON目录>` |

### Q7：如何只看当前 ARXML 里的参数值？

```bash
python <skill>/scripts/pipeline.py landing-report
```

---

## 重要约定

1. **唯一需要手动编辑的文件**：`inputs/DiagComm.xlsx`。其他 JSON、ARXML、FSCS 文件都由 Agent 自动生成。
2. **不要在 OpenCode 聊天窗口输入 DOORS 密码**。只在本地 CMD 终端执行认证命令。
3. **不要手动删除 outputs 目录下的文件**：Agent 依赖这些文件做增量判断。
4. `state/` 目录由 Agent 自动维护，**不要手动修改**。
5. `outputs/` 目录可随时删除，下次命令会自动重建。
