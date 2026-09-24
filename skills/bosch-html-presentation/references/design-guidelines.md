# Design Guidelines

## Purpose

Produce clean, engineering-oriented visual communication with strong hierarchy and restrained branding.

## Brand asset

The skill bundles one lightweight Bosch logo reference asset at `../assets/bosch-logo.svg`.

Every artifact MUST embed the exact current bytes of `assets/bosch-logo.svg`. Never substitute another logo or draw one from memory. Replace the asset only on explicit user instruction. Asset use does not certify formal corporate approval.

## Color

When an approved palette is not supplied, use a neutral fallback palette and reserve a red accent for emphasis. Example fallback variables:

```css
:root {
  --bg: #ffffff;
  --surface: #f5f6f6;
  --text: #1f2224;
  --muted: #5f6368;
  --line: #d8dcde;
  --accent: #e20015;
  --accent-strong: #c00012;
}
```

These are implementation fallbacks, not an assertion of official Bosch brand values.

## Typography

Default to system fonts so the artifact stays offline and portable:

```css
font-family: Arial, Helvetica, system-ui, -apple-system, sans-serif;
```

For technical/code labels:

```css
font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace;
```

Do not download web fonts by default.

## Composition

Prefer:
- clear left/right or top/down information flow,
- asymmetric layouts where they improve hierarchy,
- generous whitespace,
- large technical diagrams,
- concise captions,
- strong alignment,
- subtle dividers instead of card borders everywhere.

Avoid:
- dense card grids as the default,
- repeated pill labels,
- unnecessary gradients,
- decorative blobs,
- tiny text,
- faux-3D effects that distract from engineering content.

## Logo placement

Default presentation placement:
- top-right or bottom-right,
- visually secondary to slide title,
- consistent location across slides,
- adequate surrounding whitespace.

Do not:
- recolor,
- animate,
- distort,
- rotate,
- crop,
- place over noisy backgrounds without contrast.

## Accessibility

- Ensure text contrast is adequate.
- Minimum body size for projected slides should normally be about 24 px equivalent or larger.
- Never rely on color alone for status or category.
- Use visible keyboard focus.
- Respect reduced-motion preferences.

For scroll-sidebar mode, place the logo at the top of the sticky sidebar and repeat it in a print-only document header. Do not hide branding when adapting to mobile.
