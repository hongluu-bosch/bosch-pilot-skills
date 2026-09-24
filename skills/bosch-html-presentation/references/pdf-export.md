# PDF Export

HTML is the source of truth. PDF is a static export.

## Browser export

Recommended user workflow:
1. Open the generated HTML in a Chromium-family browser.
2. Print.
3. Destination: Save as PDF.
4. Layout: Landscape for slide decks; Portrait for scroll-sidebar documents.
5. Margins: None.
6. Enable background graphics when required by the design.

The HTML should already provide `@page` and print media styles so minimal manual adjustment is needed.

## Print requirements

In `@media print`:
- disable transitions/animations,
- make every slide visible,
- reveal every progressive-reveal item,
- hide navigation and cursor hints,
- force exact page breaks,
- avoid clipped overflow,
- prefer print-safe backgrounds and text contrast.

## 16:9 page size

A convenient CSS page size is:

```css
@page {
  size: 13.333in 7.5in;
  margin: 0;
}
```

This preserves a 16:9 ratio for PDF pages.

## Headless export

If the execution environment already provides Chrome/Chromium or Playwright, it may be used to print the local HTML to PDF. Do not install a browser/runtime merely because PDF export was requested unless the user explicitly permits dependency installation.

## Scroll-sidebar print mode

Use A4 portrait with normal document flow and sensible margins. Hide the sidebar, skip link, and print controls, but show the `print-brand` header with the same embedded canonical logo. Remove sticky/fixed positioning, viewport heights, and constrained overflow. Keep headings with following text and permit long sections to span pages. Do not force one chapter per page.
