# dem-pdm-size-sync 使用说明

## 这是什么

`dem-pdm-size-sync` 是一个给 opencode 使用的全局 skill，用来帮助你处理这类问题：

- 改完 freeze-frame / snapshot / DEM 相关配置后，编译开始报错
- `Dem_Cfg_AssertionChk.h` 提示 block length 不匹配
- `NVM_ID_EVMEM_LOC_*` 或 `NVM_ID_DEM_GENERIC_NV_DATA_*` 需要跟着结构体大小一起更新

这个 skill 适合在 **任何同类 Bosch 风格 AUTOSAR 项目** 中使用，不绑定某一个具体项目或工作区。

它的特点是：

- 先分析，再修改
- 只做最小改动
- 只改当前命中的项目和分支
- 把运行报告写到当前项目自己的 `.DCOM_AI/` 工作区里

---

## 用户需要知道什么

你不需要先理解所有底层术语，也不需要先去手动查 `pdmdb`、`Dem_PRJ.pdm`、`NvM_Cfg.h` 这些文件。

你只需要知道三件事：

1. **怎么安装这个 skill**
2. **怎么在某个项目里启用它**
3. **在 opencode 里该怎么提需求**

下面就按这个顺序说明。

---

## 1. 如何安装 skill

如果你拿到的是仓库源码：

把整个 `dem-pdm-size-sync` 目录放到你本机的全局 skill 目录下，例如：

```text
C:\Users\<NT>\.config\opencode\skills\dem-pdm-size-sync\
```

如果你拿到的是打包好的 `.skill` 文件：

- 让 opencode 按你们团队当前的安装方式导入它
- 导入后，确保 opencode 能在全局 skills 中识别到 `dem-pdm-size-sync`

安装完成后，重启 opencode，使 skill 生效。

---

## 2. 如何在某个项目里使用

这个 skill 是全局的，但每个项目都会有自己的本地运行数据。

第一次在某个项目里使用时，skill 会在项目下创建自己的工作区：

```text
<项目根目录>/.DCOM_AI/DEM_PDM_Size_Sync_PRJ/
```

这里会保存：

- 分析报告
- 应用报告
- 校验报告
- 项目级配置

所以你不需要担心它把数据写回 skill 安装目录；它只会把项目运行数据放在当前项目自己的 `.DCOM_AI/` 里。

---

## 3. 在 opencode 里怎么说

最简单的方式不是自己敲脚本命令，而是直接在 opencode 里用自然语言说需求。

### 常见说法 1：只分析

```text
帮我分析一下当前编译选项的 DEM PDM size 是否匹配，不要修改
```

### 常见说法 2：分析 EVMEM

```text
帮我检查当前编译选项下的 NVM_ID_EVMEM_LOC 是否需要更新
```

### 常见说法 3：分析 Generic NV Data

```text
帮我检查当前编译选项下的 NVM_ID_DEM_GENERIC_NV_DATA 是否需要更新
```

### 常见说法 4：确认后最小修改

```text
如果分析结果确认需要更新，就只对当前项目做最小修改
```

### 常见说法 5：只做校验

```text
帮我校验当前生成结果是否已经同步到正确的 block size
```

---

## 4. 最好提供什么信息

为了让 skill 快速工作，建议你在需求里尽量带上：

### 必要信息

- 当前项目根目录
- 当前编译选项 / buildconfig

例如：

```text
帮我分析一下这个项目里 buildconfig `xxx` 的 DEM PDM size 问题，只分析不要修改
```

### 可选补充信息

- 你遇到的报错文件名
- 你怀疑是 `evmem` 还是 `generic`
- 你是否只想影响当前项目

例如：

```text
当前编译报 `Dem_Cfg_AssertionChk.h` 的 block length 错误，帮我分析 EVMEM，确认后只改当前项目
```

---

## 5. 这个 skill 会帮你做什么

当你提出请求后，这个 skill 会按下面的思路工作：

1. 先识别当前项目和编译选项
2. 判断当前实际命中的 `Dem_PRJ.pdm` 和分支
3. 计算真实结构体大小
4. 检查当前 PDM/NvM 配置是不是一致
5. 先把结果告诉你
6. 只有你确认后，才做最小修改

如果你要求“不要修改”，它只会分析，不会写文件。

---

## 6. 这个 skill 会改什么，不会改什么

### 会改什么

在你确认后，它只会改与当前问题直接相关的内容，例如：

- 当前命中的 `Dem_PRJ.pdm` 分支
- 必要时追加 `pdmdb` 里的新 dataitem

### 不会做什么

- 不会默认修改其他项目
- 不会默认批量改所有编译选项
- 不会默认做 Fee/Fls 容量检查
- 不会默认跑完整 regeneration 链
- 不会在没有确认前直接写文件

---

## 7. 分析结果会放在哪里

skill 会把项目相关报告放到：

```text
<项目根目录>/.DCOM_AI/DEM_PDM_Size_Sync_PRJ/outputs/
```

常见输出包括：

- `latest_report.txt`
- `latest_report.json`
- `apply_report.txt`
- `apply_report.json`
- `verify_report.txt`
- `verify_report.json`

如果你只是普通使用者，一般看 `.txt` 报告就够了。

---

## 8. 推荐使用方式

对于普通用户，推荐一直用这种流程：

### 第一步：先分析

```text
帮我分析当前编译选项下的 DEM PDM size 问题，不要修改
```

### 第二步：看结果

skill 会告诉你：

- 当前实际大小是多少
- 当前配置是多少
- 是否需要更新
- 可能影响哪些共享分支

### 第三步：你确认后再改

```text
确认，按最小改动方式只修改当前项目
```

### 第四步：再做校验

```text
帮我检查当前生成结果是否已经同步正确
```

这样最安全，也最适合项目协作。

---

## 9. 一句话记住怎么用

如果你只想记住一种说法，就用这句：

```text
帮我分析当前 buildconfig 的 DEM PDM size 是否匹配，确认后只对当前项目做最小修改
```

这句已经足够触发这个 skill，并让它按正确流程工作。

---

## 10. 补充说明

这个 README 是给使用者看的。

如果你想看更底层的实现规则、结构体大小计算方法、PDM 分支解析规则，可以再看这些内部文档：

- `reference/workspace-model.md`
- `reference/struct-size-calculation.md`
- `reference/pdm-branch-resolution.md`
- `reference/apply-rules.md`
