# Kimi Review To Report Bundle

- Mode: review-to-report
- Language: c
- Review scope: file
- Source: <source-file>
- Prompt version: engineered-v1
- Source sha256: <source-sha256>
- Generated at: <generated-at>

## Base Prompt

# Kimi Review And Report Prompt

请只评审本文最后 `## Review Input` 下面的代码，并在一次输出中同时给出评审结论、Markdown 报告和 HTML 报告。

## 严格边界

1. 你真正要评审的对象只有 `## Review Input` 下面的代码。
2. 不要把本文中的 workflow、policy、规则说明、输出约束当作待评审对象。
3. 只有代码本身直接证明失败路径时，才能保留 confirmed finding。
4. 不要把空指针、调用契约、调用方保证、wraparound、portability、defensive programming 之类的推测问题放进 confirmed finding，除非代码直接证明失败路径。
5. 如果某个弱证据问题对 reviewer 没有明显帮助，也不要放进 Open Questions。
6. Confirmed Findings 最多保留 2 条，并优先保留 1 条最核心、最能解释行为风险的 finding。
7. 如果多个问题本质上属于同一个整数转换、比较、边界判断或同一根因的不同表现，只保留 1 条。
8. 不要因为命中很多 guideline 就扩写很多 finding。规则只能作为已确认问题的依据。
9. 如果 `Open Questions` 或 `Suspected But Unconfirmed Issues` 为空，输出 `None.`。
10. 报告语言保持简洁，不要复述大段规则原文。

## 严重级别口径

1. `critical` 仅用于代码直接证明的高风险问题，例如越界、未初始化读、明确的安全暴露或高风险并发破坏。
2. `major` 用于代码直接证明的行为错误，例如语言特性误用、错误处理缺失、数值转换或求值顺序导致结果错误。
3. `minor` 和 `info` 用于非功能性问题。

## 紧凑规则参考

- review-policy.functional-impact: Only code-proven functional issues stay high severity -- Keep major or critical only when the reviewed code directly proves correctness, runtime, memory, concurrency, security, or externally visible impact.
- review-policy.dedup: Collapse same-root-cause findings -- If multiple observations describe the same integer conversion, boundary, or logic defect, keep only the single most specific actionable finding.
- review-policy.speculation: Suppress speculative findings -- Do not keep null-pointer, caller-contract, wraparound, portability, or defensive-programming findings unless the failing path is directly visible in the reviewed code.
- general_coding_rules.4.5: Runtime-error-prone arithmetic and conversion constructs -- Use this rule only when the code directly demonstrates arithmetic or conversion behavior that can change program results.

## 输出要求

你最终只允许输出以下内容，顺序不能变：

1. `Review Result`
2. 评审结论正文
3. `Markdown Report`
4. 一个 ```md 代码块
5. `HTML Report`
6. 一个 ```html 代码块

不要输出额外解释，不要输出多余前言。

## Markdown 报告格式

Markdown 报告必须包含以下 section，标题保持一致：

1. `# Static Code Review Report`
2. `## Summary`
3. `## Confirmed Findings`
4. `## Open Questions`
5. `## Suspected But Unconfirmed Issues`
6. `## Risk Summary`
7. `## Suggested Next Actions`

`Summary` 中必须包含：

- Scope
- Total findings
- Critical
- Major
- Minor
- Info

每条 confirmed finding 必须包含：

- Evidence
- Functional Impact
- Reasoning
- Suggested Action

## HTML 报告格式

1. 输出完整 HTML 文档。
2. HTML 报告语义必须与 Markdown 报告一致。
3. HTML 中必须出现这些 section 标题：`Confirmed Findings`、`Open Questions`、`Suspected But Unconfirmed Issues`、`Risk Summary`、`Suggested Next Actions`。
4. 不要输出空文件或占位 HTML。

## Review Input

下面这段代码是唯一需要评审的输入对象。

```c
uint8 Example_Function_UB(Date_ST *pDate)
{
	uint8 l_actualYear_u8;
	sint16 l_OrdinalDay_s16;
	uint16 l_DaysPerYear_u16;

	/* Calculate ordinal day. */
	l_OrdinalDay_s16 = (sint16)(((pDate->CalendarWeek_u8 * 7U) + pDate->DayOfWeek_u8) - (Example_Get4thJanDay_UB(pDate->Year_u8) + 3U));

	if( l_OrdinalDay_s16 <= 0 )
	{
		/* Year is in the previous calendar year. */
		l_actualYear_u8 = pDate->Year_u8 - 1U;
	}
	else
	{
		/* Calculate the total number of days in the year. */
		l_DaysPerYear_u16 = Example_GetDaysPerYear_UW(pDate->Year_u8);

		if( (uint16)l_OrdinalDay_s16 > l_DaysPerYear_u16 )
		{
			/* Year is in the next calendar year. */
			l_actualYear_u8 = pDate->Year_u8 + 1U;
		}
		else
		{
			l_actualYear_u8 = pDate->Year_u8;
		}
	}

	return l_actualYear_u8;
}
```