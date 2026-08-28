# FSCS Content Review Reference

Detailed specification of the FSCS content review (`scripts/review_fscs.py`) — rules, report format, and action flow. Read this when triaging a review report, adjusting compliance rules, or explaining results to a system engineer.

## Review 策略 (v1.7)

Review 是对**生成结果**的质量检查，不是输入校验（输入校验是 Phase 1 的 Pydantic gate，会落到 `fscs_generation_report.txt`）。Review 永远 **advisory** —— 发现问题只写报告、打 WARNING，绝不阻塞 pipeline、不改退出码。

**核心原则：Review 报告永远跟随 `fscs.json` 走。** 每次 `fscs.json` 状态变化时，同一目录下的 `fscs_review_report.txt` 都会被**覆盖刷新**，保证两者不会出现漂移。

**三条触发路径**（都写同一个报告文件 `outputs/fscs/fscs_review_report.txt`）：

| 触发时机 | 入口 | 带 input JSON 一致性检查? | 可 opt-out? |
|---|---|---|---|
| Phase 1 生成末尾 | `pipeline.py --phase fscs` | ✅ 是 | `--no-review` / `DID_NO_REVIEW=1` |
| xlsx-import 后 | `pipeline.py --phase xlsx-import [--input xxx.json]` | 取决于是否传 `--input` | 不可（xlsx-import 必然刷 report）|
| 命令行 on-demand | `pipeline.py --phase review [--input xxx.json]` | 取决于是否传 `--input` | 就是 on-demand 本身，无所谓 opt-out |

**Review 目标:**
1. 检查生成的 FSCS 内容是否符合业务合规性要求（Business Compliance）
2. 检查 Service 22/2E 的 session + security 配置是否符合标准（Configuration Compliance）
3. 检查 FSCS 与输入 JSON 的一致性（Data Consistency，仅在持有 input JSON 时运行）
4. 生成 Review 报告供人工审查

**与 validate 的区别:**

| 维度 | validate（Pydantic gate）| review（本文档）|
|---|---|---|
| 产物 | `fscs_generation_report.txt` | `fscs_review_report.txt` |
| 失败后果 | 单条 DID 被 skip，不进入 `fscs.json` | 记录到报告，不影响 `fscs.json` / 后续 phase |
| 目的 | 结构性门禁 | 业务体检 |
| 触发 | Phase 1 生成时天然跑 | 生成后 / CSV import 后 / on-demand |

## Review 检查项

### 1. 业务合规性检查 (Business Compliance)

**仅 2E 写 DID 检查:**
- **业务规则:** 所有 DID 必须至少支持读操作（Service 22）
- **检查逻辑:** 对比 FSCS_22 和 FSCS_2E 的 DID 列表，找出仅在 Service 2E 中出现但不在 Service 22 中的 DID
- **结果:** 这类 DID 在业务上不合规，需要联系系统工程师确认 DID 设计

**示例 - 不合规 DID 发现:**
```
[仅 2E 写 DID 检查]
业务规则: 所有 DID 必须至少支持读操作（Service 22）
  ✗ 发现 2 个不合规 DID:
    - DID 0xF184: 仅在 Service 2E 中出现，缺少 Service 22 支持（不合规：所有 DID 应至少支持读操作）
    - DID 0xF199: 仅在 Service 2E 中出现，缺少 Service 22 支持（不合规：所有 DID 应至少支持读操作）
```

### 2. 配置合规性检查 (Configuration Compliance)

**Service 22 配置标准:**
- 应支持所有诊断会话：defaultSession + extendedDiagnosticSession
- 应使用安全等级：L0

**Service 2E 配置标准:**
- 应仅支持诊断会话：extendedDiagnosticSession（不应有 defaultSession）
- 应使用安全等级：L1

**示例 - 配置异常:**
```
[Service 22] 标准: defaultSession + extendedDiagnosticSession + L0
  ✗ DID 0x0101: 缺少 defaultSession（标准要求支持 defaultSession + extendedDiagnosticSession）
  ✓ 其他 XX 个 DID 符合标准

[Service 2E] 标准: extendedDiagnosticSession only + L1
  ✗ DID 0xF184: 缺少 L1 安全等级（标准要求 L1）
  ✓ 其他 XX 个 DID 符合标准
```

### 3. 数据一致性检查 (Data Consistency)

**完整性检查:**
- JSON 中 `supported_by_ecu=Y` 的 DID 是否都在 FSCS 中生成
- FSCS 中的 DID 是否都在 JSON 输入中有定义

**rw_state 一致性:**
- Service 22 中的 DID，在 JSON 中 `rw_state` 应为 "R" 或 "RW"
- Service 2E 中的 DID，在 JSON 中 `rw_state` 应为 "W" 或 "RW"

**示例 - 一致性异常:**
```
[JSON → FSCS 一致性]
  ✗ DID 0xF1A0: 在 FSCS 中出现但 JSON 输入中不存在
  ✓ JSON 中所有 supported_by_ecu=Y 的 DID 都在 FSCS 中

[FSCS ↔ JSON rw_state 一致性]
  ✗ DID 0x0101: FSCS_22 中存在但 JSON 中 rw_state="W"（预期 R 或 RW）
```

## Review 报告

**报告位置:**
```
.DCOM_AI/DID_Toolkit_PRJ/outputs/fscs/fscs_review_report.txt
```

**报告格式:**
```
================================================================================
FSCS Content Review Report
================================================================================
生成时间: 2025-XX-XX XX:XX:XX
Service 22 DID 数: XX
Service 2E DID 数: XX

================================================================================
一、业务合规性检查 (Business Compliance)
================================================================================

[仅 2E 写 DID 检查]
业务规则: 所有 DID 必须至少支持读操作（Service 22）
  ✗ 发现 2 个不合规 DID:
    - DID 0xF184: 仅在 Service 2E 中出现，缺少 Service 22 支持
    - DID 0xF199: 仅在 Service 2E 中出现，缺少 Service 22 支持
  说明: 这些 DID 在业务上不合规，应至少支持读操作

================================================================================
二、配置合规性检查 (Configuration Compliance)
================================================================================

[Service 22] 标准: defaultSession + extendedDiagnosticSession + L0
  ✗ DID 0x0101: 缺少 defaultSession
  ✓ 其他 XX 个 DID 符合标准

[Service 2E] 标准: extendedDiagnosticSession only + L1
  ✓ 所有 XX 个 DID 符合标准

================================================================================
三、数据一致性检查 (Data Consistency)
================================================================================

  ✓ FSCS 与 JSON 输入完全一致

================================================================================
总结: 发现 3 个异常 (不影响后续执行)
  - 业务不合规: 2 个 (仅 2E 写 DID)
  - 配置异常: 1 个
  - 一致性异常: 0 个
================================================================================
```

## 参数说明 (Standalone Review CLIs)

- `--fscs-json`: 权威 `fscs.json` 路径（Phase 1 产出；三个 reviewer 都硬依赖此文件，文件缺失会提示先跑 Phase 1）。
- `--input-json` (仅 `review_fscs`): 原始 DID 定义 JSON，用于 FSCS 与输入的一致性对比。
- `--arxml` / `--impl-dir`: 被审对象的路径。
- `--output`: Review 报告输出路径（各 reviewer 有各自的默认值）。

Command-line invocations are documented in [`commands.md`](commands.md) (section *Independent Review Runs*).

## Operator-Deselected DIDs (`status: DESELECTED`)

When a reviewer sets `used_flag=FALSE` in `fscs_edit.xlsx`, both internal `service_22.used` and `service_2e.used` become `False`. The DID remains in `fscs.json` but is excluded from every generated/reviewed artefact (`FSCS_*.txt`, ARXML, C, headers, PDM, and DOORS upload content).

- **FSCS Review** — deselected DIDs are skipped entirely; they do not participate in business, configuration, or consistency checks.
- **FSCS TXT / DOORS** — `FSCS_22.txt` / `FSCS_2E.txt` render only effective services, and the DOORS payload is built from those TXT files, so deselected DIDs are not uploaded.
- **ARXML / Impl reviewers** — via `adapter.to_review_dicts`, deselected DIDs are dropped from the reviewer scope entirely (nothing to compare against a non-existent ARXML container or C file). If the CSV keeps `used_flag=TRUE` but clears `service_2e_support`, the DID is projected as read-only, so the reviewer sees the same effective surface as the generator.
- **Phase 2 / Phase 3 `validation_report.txt`** — generation validation may still show the DID with `status: DESELECTED` for traceability. This is a validation summary marker, not a review finding, and deselected DIDs are **not** listed under *Failed DIDs Details*.

This means `DESELECTED` is an intentional, non-actionable state. It is separate from `ERROR` (bad input) and `WARNING` (suspicious but passable).

## Review 问题处理

**处理原则:**
1. Review 发现的问题**不会阻断**后续 Phase (ARXML 生成、代码生成) 的执行
2. 业务不合规问题需联系系统工程师确认 DID 设计
3. 配置异常需调整输入 JSON 后重新生成
4. 一致性异常可能表示生成逻辑有误，需检查代码

**建议流程 (v1.7):**
1. 运行 Phase 1 生成 FSCS —— `fscs_review_report.txt` 会自动同步产出
2. 查看 Review 报告，识别问题（Phase 1 的 console 输出会提示问题数）
3. 根据问题类型采取行动:
   - 业务不合规 → 联系系统工程师（不合规不一定是 bug，也可能是配置意图）
   - 配置异常 → 修改输入 JSON → 重新跑 `--phase fscs`（会自动刷新报告）
   - 一致性异常 → 检查生成脚本 / inputs 是否对齐
4. 在 `outputs/fscs/fscs_edit.xlsx` 里调整 `used_flag` / `service_XX_support` 或其他可编辑列后运行 `python scripts/pipeline.py --phase xlsx-import` —— 报告会自动重新生成一遍
5. 想在不改动的前提下复跑一次 review（例如规则版本升级后）：
   `python scripts/pipeline.py --phase review [--input inputs/xxx.json]`
