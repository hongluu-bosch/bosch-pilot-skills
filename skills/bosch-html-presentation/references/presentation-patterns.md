# Presentation Patterns

## Deck shell

Recommended DOM:

```html
<main class="deck" aria-label="Presentation">
  <section class="slide is-active" data-title="Title">...</section>
  <section class="slide" data-title="Context">...</section>
</main>
<nav class="presentation-ui" aria-label="Presentation controls">...</nav>
```

## Slide patterns

### Title
Large statement + short subtitle + logo. Avoid extra content.

### Context / problem
One central claim supported by 2–4 concise facts or one diagram.

### Architecture
Use SVG or CSS grid. Favor explicit arrows and labeled boundaries.

### Flow / sequence
Show 3–7 steps. Progressive reveal may help, but the final static state must remain understandable.

### Comparison
Two columns or a compact matrix. Use consistent dimensions.

### Evidence
Chart, benchmark, result, or concise table. Lead with the conclusion, then evidence.

### Closing
One memorable takeaway and optional next action.

## Navigation model

Recommended behavior:

- `ArrowRight`, `PageDown`, `Space`: reveal next item; otherwise next slide.
- `ArrowLeft`, `PageUp`: previous slide.
- `Home`: first slide.
- `End`: last slide.
- Touch swipe: optional.

Ignore global navigation while focus is inside `input`, `textarea`, `select`, `[contenteditable]`, or interactive widgets using arrow keys.

## Progressive reveal model

A slide may contain:

```html
<li class="reveal">First point</li>
<li class="reveal">Second point</li>
```

Keep a reveal index per active slide. When advancing, reveal the next hidden element before moving to the next slide.

Use `.is-revealed` to make the state explicit.

## Transition guidance

Default slide transition:
- active slide: `opacity: 1; transform: translateX(0)`
- entering next: small horizontal movement or opacity shift
- duration: roughly 400–600 ms

Do not use a unique transition for every slide.

## Diagram animation

For SVG connections:

```css
.flow-path {
  stroke-dasharray: var(--path-length, 500);
  stroke-dashoffset: var(--path-length, 500);
  transition: stroke-dashoffset 700ms ease-out;
}
.slide.is-active .flow-path {
  stroke-dashoffset: 0;
}
```

Always show the final path in print/reduced-motion mode.

## Responsive presentation

Use CSS `clamp()` for typography, but ensure projected text remains large enough.

A practical slide shell:

```css
.slide {
  width: min(100vw, calc(100vh * 16 / 9));
  height: min(100vh, calc(100vw * 9 / 16));
  aspect-ratio: 16 / 9;
}
```

For a VS Code webview, allow the deck to fit the available panel while maintaining aspect ratio.

## Continuous presentation: sticky sidebar + scrollspy

Start from `templates/scroll-sidebar.html`. Use native document scrolling and a sticky left table of contents. Define stable chapter IDs and matching anchor links in reading order. Select the last chapter whose top crossed the reading line; select the final chapter at the document bottom. A passive scroll listener schedules at most one update per animation frame. Resize and hash changes also schedule updates. Keep one `aria-current="location"` and a visible border/weight cue.

Leave anchor navigation native so hashes, keyboard activation, direct links, and history work. Never update history on passive scrolling. On mobile, place wrapping navigation above content. In print, remove the sidebar and show the separate logo header.

## Inline editing in scroll-sidebar mode

Keep the template's **Edit page** control. Mark only intended user text with `data-editable`; toggle `contenteditable` for those nodes, and visibly identify editable text on hover and focus. Never make the Bosch logo, section IDs, table-of-contents anchors, scrollspy state, or controls editable. Provide a **Done editing** control and a **Download HTML** download that preserves text edits in a self-contained HTML document while resetting the edit mode. A browser cannot overwrite its own local source file, so explain the download-and-replace workflow in the page. Keep this toolbar hidden in print.

Place Edit page below Print / PDF in the bottom sidebar action area. Keep actions visible while the table of contents scrolls. Show brief status text only when editing or when changes are pending. Export controls must reflect actual changes; print must hide controls and editing outlines.
