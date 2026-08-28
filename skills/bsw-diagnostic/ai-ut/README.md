# `ut-100percent-coverage` SKILL 使用手册

## 1. 适用场景

本手册用于指导你在 **Cantata 环境**、**Opencode 环境** 已就绪，且已申请正式 **Kimi API Key** 的前提下，使用 `ut-100percent-coverage` 这个 Skill，为指定的 `.c` 文件生成面向 **100% C0 / C1 / MC/DC** 覆盖率的单元测试。

该 Skill 适用于以下典型需求：

- 为嵌入式 C 源码生成 Cantata++/GTest 风格单元测试
- 目标覆盖率为 100% Statement / Decision / Boolean Effect
- 不修改被测源文件（SUT）本身逻辑

## 2. 前提条件

开始前，请确保以下环境已经准备完成：

- Cantata 环境已安装并可正常使用
- Opencode 环境已安装并可通过命令行启动，
参考 guideline：https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094307517/003+%E5%AE%89%E8%A3%85OpenCode+%E5%92%8C+Cline
- 已获取正式可用的 Kimi API Key
参考 guideline：https://inside-docupedia.bosch.com/confluence/spaces/CCEAS3CN/pages/7094306832/001+%E7%94%B3%E8%AF%B7Kimi+API+Key

## 3. 使用前准备

### 3.1 新建工作目录

新建一个用于本次 UT 生成的空文件夹，作为当前 `workspace`。

### 3.2 拷贝必要文件

将以下内容复制到新建的 `workspace` 根目录下：

- `opencode.json`
- `.agents` 文件夹

复制完成后，目录示例如下：

```text
workspace/
├─ opencode.json
└─ .agents/
```

### 3.3 配置 Kimi API Key

编辑 `workspace` 根目录下的 `opencode.json`，将你申请到的正式 Kimi API Key 替换到 `"apiKey"` 字段中。

示例：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "local-kimi": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Kimi-K2.5",
      "options": {
        "baseURL": "http://10.54.7.15:44302/kimi-k2.5/v1",
        "apiKey": "替换为你的正式Kimi_API_Key"
      },
      "models": {
        "Kimi-K2.5": {
          "name": "Kimi-K2.5"
        }
      }
    }
  }
}
```

### 3.4 准备待测 `.c` 文件编译出来的项目SwitchSettings_*.csv文件

在当前 `workspace` 下，为要做 UT 的 `.c` 文件新建一个同名文件夹，并将该 `.c` 文件和csv文件放入该文件夹中。

例如，要测试 `xxx.c`，则目录应整理为：

```text
workspace/
├─ opencode.json
├─ .agents/
└─ xxx/
   └─ xxx.c
   └─ SwitchSettings_*.csv
```

## 4. 使用步骤

### 4.1 打开命令窗口

在当前 `workspace` 根目录打开 `cmd` 命令窗口。

### 4.2 启动 Opencode

在命令窗口中输入：

```cmd
opencode
```

启动后进入 Opencode CLI 交互窗口。

### 4.3 输入 Skill 提示词

在 Opencode CLI 窗口中输入以下提示词：

```text
Generate 100% coverage unit tests for C:\完整\绝对路径\xxx.c
```

建议这里直接填写 `.c` 文件的**绝对路径**，这样可以节省模型查找目标 `.c` 文件的时间，提高执行效率。

其中，将示例路径替换为你的实际被测文件绝对路径，例如：

```text
Generate 100% coverage unit tests for C:\UT_Workspace\RBAPLCUST_SecurityAccess_AES128\RBAPLCUST_SecurityAccess_AES128.c
```

## 5. Skill 执行过程说明

输入提示词后，Skill 会按既定流程自动处理，核心过程包括：

1. 先对目标 `.c` 执行初始化流程
2. 自动调用 `projectsetup.py` 创建标准测试工程结构
3. 在 `test_<ComponentName>` 目录下生成或补充测试文件
4. 调用 Cantata 执行构建、测试和覆盖率分析
5. 循环补充测试，直到覆盖率满足目标或触发停止条件

Skill 的强制规则包括：

- 必须先执行 `projectsetup.py`
- 不允许修改被测 `.c` 源文件逻辑
- 仅在当前组件目录范围内工作
- 若发现逻辑不可达或自相矛盾，应上报问题而不是修改 SUT

## 6. 预期生成目录

当 Skill 正常执行后，目标组件目录通常会形成如下结构：

```text
<ComponentName>/
├─ <ComponentName>.c
└─ test_<ComponentName>/
   ├─ test_<ComponentName>.h
   ├─ test_<ComponentName>.cpp
   └─ work/
      ├─ cantata_coverage.bat
      ├─ input/
      └─ output/
         └─ cantata/
            └─ ASIL_D_cov.ctr
```

## 7. 结果确认

完成后，重点检查以下内容：

- `test_<ComponentName>` 目录是否已生成
- `test_<ComponentName>.h` 与 `test_<ComponentName>.cpp` 是否已生成或更新
- `work/output/cantata/ASIL_D_cov.ctr` 是否已生成
- 覆盖率报告中 Statement、Decision、Boolean Effect 是否达到 100.0%

## 8. 常用提示词示例

可直接使用如下格式：

```text
Generate 100% coverage unit tests for C:\完整\绝对路径\xxx.c
```

推荐写法示例：

```text
Generate 100% coverage unit tests for C:\UT_Workspace\DemoModule\DemoModule.c
Generate 100% coverage unit tests for C:\UT_Workspace\MotorCtrl\MotorCtrl.c
Generate 100% coverage unit tests for C:\UT_Workspace\RBAPLCUST_SecurityAccess_AES128\RBAPLCUST_SecurityAccess_AES128.c
```

## 9. 注意事项

- `workspace` 根目录下必须同时存在 `opencode.json` 和 `.agents`
- `opencode.json` 中必须填写有效的正式 Kimi API Key
- 被测 `.c` 文件必须放在与其同名的目录中
- 在 Skill 提示词中，建议始终使用 `.c` 文件的绝对路径，而不是仅写文件名
- 不建议手工提前创建 `test_*` 目录结构，交由 Skill 自动初始化
- 若 Cantata、Cook-san 或测试工程初始化失败，应先修复环境问题后再重新执行

## 10. 一句话操作总结

准备好 `workspace` -> 配置 `opencode.json` 中的 Kimi API Key -> 放入目标 `.c` 文件 -> 在 `workspace` 打开 `cmd` 执行 `opencode` -> 在 CLI 中输入 `Generate 100% coverage unit tests for C:\完整\绝对路径\xxx.c`
