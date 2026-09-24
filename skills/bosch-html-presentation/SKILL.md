---
name: bosch-html-presentation
description: Create Bosch-branded, offline HTML/CSS/vanilla JavaScript presentations, interactive explainers, and visual reports with optional static PDF export. Use for discrete slide decks or continuous scrolling presentations with a sticky left sidebar and scrollspy. Always reuse the bundled Bosch logo from assets; no frontend build tools or external dependencies are needed.
---

# Bosch HTML Presentation

Create self-contained HTML as the source of truth. Export PDF only as its static derivative.

## Mandatory asset contract — complete before authoring

1. Resolve this skill's directory from the loaded `SKILL.md`, not the output directory or current working directory. Read **`assets/bosch-logo.svg`** from that directory. This is the sole logo source for every output mode.
2. **MUST include that exact asset visibly in every generated artifact.** Branding is required even when the user does not mention a logo. In a deck, place it on every slide; in a scrolling document, place it in the sidebar and in the printable document header.
3. Embed the asset's original bytes as an `<img>` with a base64 data URI, `alt="Bosch"`, and `data-brand-asset="assets/bosch-logo.svg"`. Preserve its aspect ratio, colors, and geometry. Use `height:auto`, a readable size, and clear space. Keep it static and visible on a contrasting background.
4. **MUST NOT** redraw, approximate, trace, regenerate, recolor, crop, stretch, animate, or replace it with text, CSS shapes, an icon, another SVG, a remote URL, or a logo from memory. Do not hide it, reduce it to an invisible size, or include it only in comments/metadata. A filename, marker, or hash alone does not establish compliance.
5. If the asset is missing or unreadable, report the missing file and request it. Stop branded delivery; do not invent a fallback. Replace the asset only when the user explicitly supplies or requests a replacement. Never edit the asset or weaken the validator just to pass validation.
6. Regenerate embedded copies from the current asset with `scripts/embed_logo.py <artifact.html>` after copying a template. Verify byte equality with `scripts/check_artifact.py <artifact.html>`. Run scripts from this skill directory so the canonical asset is resolved correctly. These authoring utilities use Python standard library only; the final HTML requires only a browser.

Bundled asset provenance is documented in `NOTICE.md`; using it does not certify official corporate approval. Approval status is not permission to substitute a different logo.

## Output contract

- Use HTML5, CSS, and vanilla JavaScript only. Deliver one self-contained HTML file that opens directly with `file://`.
- Embed styles, scripts, and images. Require no npm, Node.js, React, TypeScript, build step, server, CDN, downloaded fonts, or runtime network access. Ordinary source hyperlinks are allowed; remote resource loading is not.
- Use semantic landmarks, accessible labels, visible focus, sufficient contrast, and responsive layouts. Respect `prefers-reduced-motion`.
- Keep essential information readable without animation and fully visible when printing.

## Require user selection before choosing a template

Before creating any artifact, ALWAYS ask the user which template to use.
This is a mandatory interaction, even when the request appears to imply
a particular mode.

Present these two options in the user's language:

| Option | Starting template | Interaction |
| --- | --- | --- |
| Slide deck | `templates/slide-deck.html` | Discrete 16:9 slides, keyboard navigation, progressive reveal |
| Scroll + sidebar | `templates/scroll-sidebar.html` | Continuous scrolling, sticky left navigation, scrollspy |

Ask: “Bạn muốn dùng dạng Slide deck hay Scroll + sidebar?”

Wait for the user's explicit selection before creating the artifact.
Do not infer the mode, choose a default, or treat silence as consent.
If the answer is ambiguous, clarify before proceeding.

After the user selects:
1. Read the selected template.
2. Preserve its working navigation and required Bosch logo.
3. Customize the content and composition using that template.
4. Do not switch templates without asking the user again.

### Slide-deck mode

- Keep 16:9 slides and one authoritative current-slide index.
- Support Right/PageDown/Space to reveal or advance; Left/PageUp to go back; Home/End to jump. Keep visible navigation buttons and slide count.
- Ignore deck shortcuts inside controls, links, and editable elements. Keep inactive slides out of keyboard focus.
- Print one slide per landscape page; show all slides, diagrams, and reveals regardless of current state, with the logo on each page.

### Scroll-sidebar mode: sticky sidebar + scrollspy

- Use a two-column desktop layout: sticky left navigation and continuous content on the right. Let the document scroll naturally; do not add slide snapping, forced full-screen sections, scroll hijacking, or deck keyboard shortcuts.
- Give each content section a unique stable ID and a matching native anchor in the sidebar. Keep the links usable without JavaScript.
- Track the section at a reading line near the top of the viewport. Update exactly one active link with `aria-current="location"`, visual emphasis, and a non-color cue. Handle both scroll directions, short sections, and the bottom of the document.
- Clicking a sidebar link must scroll to the corresponding section and preserve meaningful hash navigation. Handle initial URL hashes and browser Back/Forward. Do not add history entries during passive scrolling or move focus while merely scrolling.
- Respect reduced motion for scrolling. Keep active navigation visible within long tables of contents without moving the main document unexpectedly.
- On narrow screens, put the navigation above the content with wrapping links; keep the page free of horizontal overflow. Retain ordinary Tab/Enter navigation and a skip-to-content link.
- Print in normal portrait document flow, hide interactive navigation, show the document-header logo and all content, and remove sticky positioning and height/overflow constraints. Do not apply the deck's 16:9 print dimensions to this mode.

## Authoring workflow

1. Identify audience, main message, hierarchy, and output mode. Organize a narrative; avoid arbitrary slide counts and filler.
2. Read `references/design-guidelines.md` and `references/presentation-patterns.md`. Use neutral surfaces, restrained red accents, strong typography, whitespace, and subject-specific diagrams. The fallback palette is not an official brand specification.
3. Copy the selected template, preserve its `data-artifact-mode`, and replace demonstration content. Update section IDs and sidebar links together. Refresh logos from `assets/`.
4. Use CSS for transitions and layout, inline SVG for diagrams, and JavaScript only for useful interaction. Keep motion brief and explanatory. Never animate the logo.
5. Read `references/pdf-export.md` when preparing print output. Keep HTML and PDF content consistent. Claim a PDF export only after actually producing and checking it.
6. Run the validator if Python is available; fix failures before delivery. If unavailable, perform the same asset-byte, resource, navigation, and print checks with available tools and state the validation limitation. Never claim a script passed without running it.
7. Open the final local HTML if browser tools are available. Verify the actual logo renders visibly, no resource requests occur, and no console errors or overflow appear. Test desktop and narrow layouts, keyboard behavior, reduced motion, and print rendering. A static validator cannot prove visual correctness.

## Delivery gate

Do not mark the artifact complete until:
- the visible logo originates from the exact current `assets/bosch-logo.svg`, not a substitute;
- every slide carries it, or the scrolling sidebar and printable header carry it;
- the chosen mode's navigation works and all content is reachable;
- the HTML works offline with all assets embedded;
- print output includes complete content and branding;
- all checks actually run are reported accurately.

Deliver HTML when requested. For PDF, generate from HTML with an available browser export facility; PDF does not retain animation or interactivity. If PDF export is unavailable, deliver the HTML and explain that limitation.
