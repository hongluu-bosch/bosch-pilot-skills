# Report Templates

Use these templates when the user asks for a reusable review report.

The default behavior for the generic functional-impact workflow is to provide both:

1. A Markdown report.
2. An HTML report.

## Markdown Report Template

```md
# Static Code Review Report

File: <file-or-scope>
Date: <ISO timestamp or date>

## Summary

- Scope: <file, snippet, report, or finding set>
- Total findings: <count>
- Critical: <count>
- Major: <count>
- Minor: <count>
- Info: <count>

## Confirmed Findings

### <severity> - <title>

- **Function:** <function-name>
- **Location:** <line / expression / branch>
- **Evidence:**
  - <code-proven fact>
  - <code-proven fact>
- **Functional Impact:** <yes/no and why>
- **Reasoning:** <why this severity is justified>
- **Suggested Action:** <fix, downgrade, merge, reject, or clarify>

## Open Questions

None.

## Suspected But Unconfirmed Issues

None.

## Risk Summary

<short summary>

## Suggested Next Actions

1. <action>
2. <action>
```

## HTML Report Template

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Static Code Review Report</title>
  <style>
    body { font-family: Segoe UI, Tahoma, sans-serif; background: #f5f7fb; color: #1f2937; margin: 0; padding: 24px; }
    .page { max-width: 1100px; margin: 0 auto; }
    .header { background: linear-gradient(135deg, #0f172a, #1d4ed8); color: #ffffff; padding: 24px; border-radius: 16px; }
    .header h1 { margin: 0 0 8px; font-size: 28px; }
    .meta { display: flex; gap: 16px; flex-wrap: wrap; font-size: 14px; opacity: 0.95; }
    .summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }
    .summary-card { border-radius: 12px; padding: 14px 16px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); }
    .summary-card strong { display: block; font-size: 22px; margin-bottom: 4px; }
    .summary-total { background: #e2e8f0; color: #0f172a; }
    .summary-critical { background: #c2410c; color: #ffffff; }
    .summary-major { background: #facc15; color: #422006; }
    .summary-minor { background: #bef264; color: #365314; }
    .summary-info { background: #bae6fd; color: #0c4a6e; }
    .card { border-radius: 12px; padding: 16px 18px; margin-bottom: 14px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08); border-left: 6px solid #94a3b8; }
    .critical-card { background: #fff1f2; border-left-color: #dc2626; }
    .major-card { background: #fff7ed; border-left-color: #d97706; }
    .minor-card { background: #f7fee7; border-left-color: #65a30d; }
    .info-card { background: #eff6ff; border-left-color: #0284c7; }
    .neutral-card { background: #ffffff; border-left-color: #94a3b8; }
    .section-title { margin: 0 0 10px; font-size: 22px; }
    .badge { display: inline-block; border-radius: 999px; padding: 4px 10px; font-size: 12px; font-weight: 700; letter-spacing: 0.03em; }
    .critical { background: #c2410c; color: #ffffff; }
    .major { background: #facc15; color: #422006; }
    .minor { background: #bef264; color: #365314; }
    .info { background: #bae6fd; color: #0c4a6e; }
    code { background: #e2e8f0; padding: 2px 6px; border-radius: 6px; }
    ul, ol { margin: 10px 0 0 20px; }
    p { line-height: 1.55; }
  </style>
</head>
<body>
  <div class="page">
    <header class="header">
      <h1>Static Code Review Report</h1>
      <div class="meta">
        <span>File: &lt;file-or-scope&gt;</span>
        <span>Date: &lt;date&gt;</span>
        <span>Scope: &lt;scope&gt;</span>
      </div>
    </header>

    <section class="summary">
      <div class="summary-card summary-total"><strong>&lt;count&gt;</strong>Total Findings</div>
      <div class="summary-card summary-critical"><strong>&lt;count&gt;</strong>Critical</div>
      <div class="summary-card summary-major"><strong>&lt;count&gt;</strong>Major</div>
      <div class="summary-card summary-minor"><strong>&lt;count&gt;</strong>Minor</div>
      <div class="summary-card summary-info"><strong>&lt;count&gt;</strong>Info</div>
    </section>

    <section class="card major-card">
      <h2 class="section-title">Confirmed Findings</h2>
      <div>
        <span class="badge major">MAJOR</span>
        <div class="finding-title">&lt;title&gt;</div>

        <p><strong>Function:</strong> <code>&lt;function-name&gt;</code></p>
        <p><strong>Location:</strong> &lt;line / expression / branch&gt;</p>

        <p><strong>Evidence:</strong></p>
        <ul>
          <li>&lt;code-proven fact&gt;</li>
          <li>&lt;code-proven fact&gt;</li>
        </ul>

        <p><strong>Functional Impact:</strong> &lt;yes/no and why&gt;</p>
        <p><strong>Reasoning:</strong> &lt;why this severity is justified&gt;</p>

        <p><strong>Suggested Action:</strong></p>
        <pre><code>&lt;fix or replacement code&gt;</code></pre>
      </div>
    </section>

    <section class="card neutral-card">
      <h2 class="section-title">Open Questions</h2>
      <p>None.</p>
    </section>

    <section class="card neutral-card">
      <h2 class="section-title">Suspected But Unconfirmed Issues</h2>
      <p>None.</p>
    </section>

    <section class="card neutral-card">
      <h2 class="section-title">Risk Summary</h2>
      <p>&lt;summary&gt;</p>
    </section>

    <section class="card neutral-card">
      <h2 class="section-title">Suggested Next Actions</h2>
      <ol>
        <li>&lt;action&gt;</li>
      </ol>
    </section>
  </div>
</body>
</html>
```

## Usage Notes

1. Keep Markdown and HTML content semantically aligned.
2. Use the same finding order in both formats.
3. Always include Function / Location fields for each confirmed finding.
4. Prefer bullet-point evidence over a single vague paragraph.
5. If evidence is weak, reflect that in both reports instead of overstating risk.
6. Prefer concise, reviewer-oriented language over generic risk boilerplate.
7. Prefer the same gradient header, summary cards, and severity badge colors as the main extension report unless the user asks for a different look.