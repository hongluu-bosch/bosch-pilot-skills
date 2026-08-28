# Report Output Guide

Use this guide when the user asks for a reusable report file rather than a chat-only answer.

## Default Behavior

When the user asks for a report, prefer the workflow path that writes files directly to disk under `review-reports/` unless the user specifies a different location. Avoid creating untitled editor files that require a manual Save click.

1. `review-reports/static-code-review-report.current-file.<file-or-function-name>.<timestamp>.html`
2. `review-reports/static-code-review-report.current-file.<file-or-function-name>.<timestamp>.zh-CN.html`

## Output Rules

1. Create the `review-reports/` folder if it does not exist.
2. Keep the English and Chinese HTML reports aligned in finding order and severity counts.
3. Treat the Markdown report in the model response as an intermediate normalization input, not as a default formal file to keep in `review-reports/`.
4. If the user provides a file name or directory, prefer the user-provided path.
5. If the user requests multiple report variants, use explicit file names instead of overwriting silently.
6. Before a new formal report is written, move all existing formal reports in `review-reports/` into `review-reports/archive/`.
7. During a normal review flow, treat any archive or cleanup behavior as pipeline-managed implementation detail. Do not construct, propose, or ask approval for an ad hoc shell or PowerShell archive command.
8. If the user explicitly asks to archive reports separately, prefer the VS Code task `Static Code Review Archive Current Reports` when it exists.

## Naming Guidance

Default names should use one fixed prefix plus a timestamp:

1. `static-code-review-report.current-file.<file-or-function-name>.<timestamp>.html`
2. `static-code-review-report.current-file.<file-or-function-name>.<timestamp>.zh-CN.html`

Default file names should also include the reviewed file name or reviewed function name. Keep the full human-readable review scope in the report title and metadata.

## Content Expectations

Both formal HTML files should contain:

1. Review scope.
2. Summary counts.
3. Findings.
4. Open questions.
5. Risk summary.
6. Suggested next actions.

If older `.md` formal reports already exist from previous workflow versions, they may still be archived for cleanup compatibility, but they are not the default formal output anymore.

## Archive Execution Guidance

1. Do not generate one-off commands such as `powershell -NoProfile -Command "... Move-Item ..."` to archive reports during standard review.
2. Do not ask the user to approve a raw archive command before a normal current-file or function review.
3. Standard review tasks should rely on the built-in review pipeline to archive all existing reports before writing the new formal report.
4. Only use a separate archive action when the user explicitly requests archive-only behavior.

## Chat-Mode Archive Exception

When a formal report is requested directly via chat (not through an active built-in review pipeline), `report-output.md` Output Rule 6 — "move all existing formal reports into `review-reports/archive/` before writing the new formal report" — still applies. In this mode:

1. Execute the project's archive script (e.g., `archive_review_reports.ps1`) to move existing reports into `review-reports/archive/`.
2. Only after the archive step completes should the new formal reports be written to `review-reports/`.
3. This exception does not apply to quick chat-only answers or prose-only responses (see "When Not To Create Files" below).

This exception preserves the intent of Archive Execution Guidance points 1–4 for standard pipeline reviews, while ensuring Output Rule 6 is satisfied when the pipeline is not active.

## Archive Naming Guidance

Archived files should preserve the original report file name and append `.archived.<timestamp>` before the final suffix.

Examples:

1. `static-code-review-report.current-file.RBNET_SCL_Rx_MonitorHandler.c.20260605-095517.archived.20260605-102600.html`
2. `static-code-review-report.current-file.RBNET_SCL_Rx_MonitorHandler.c.20260605-095517.archived.20260605-102600.zh-CN.html`

## When Not To Create Files

Do not auto-create files when:

1. The user only asks for a quick answer in chat.
2. The user explicitly asks for prose only.
3. The environment or task context makes file creation inappropriate.
