# Record Detail QA Findings: Second Pass

Audit date: 2026-03-19

Scope:
- Vector dataset detail: `/datasets/c4085719-be96-4544-96b4-2cbc3baecaf3#overview`
- Raster dataset detail: `/datasets/f15ae3e9-006e-449d-8920-ee55f206a3dc#overview`
- VRT dataset detail: `/datasets/11111111-2222-3333-4444-555555555555#overview`
- Collection detail: `/collections/da93abc1-920d-4de8-8f44-c3880c7b8f2e`

Methods:
- Live Playwright browser QA at `1440x1024` and `375x812`, with manual screenshots saved under [`./evidence/manual`](./evidence/manual).
- Repeatable audit run via `npm run e2e -- e2e/record-detail-ux-audit.spec.ts --project=chromium`.
- Automated result after harness cleanup: `3 passed / 6 failed`.

Important caveat:
- Headless Playwright emits `Failed to initialize WebGL` on dataset maps under SwiftShader. I did not treat that as a product bug. All user-facing map/hero judgments below come from the live browser pass, where vector and raster maps rendered and the VRT tile failures were reproduced directly.

Reference baseline:
- [First-pass findings](../260320-use-the-playwright-mcp-server-to-qa-all-/FINDINGS.md)

## Baseline Re-validation

| Baseline ID | Status | Second-pass update | Evidence |
| --- | --- | --- | --- |
| `F-001` VRT preview fails loudly and leaves the hero in a broken state | Still broken | Reproduced in the live browser. The VRT hero still sits in a visually empty state while repeated `500` tile requests fire in the console. | [vrt-desktop-manual.png](./evidence/manual/vrt-desktop-manual.png), [vrt-mobile-manual.png](./evidence/manual/vrt-mobile-manual.png), [first-pass console-vrt.log](../260320-use-the-playwright-mcp-server-to-qa-all-/logs/console-vrt.log) |
| `F-002` Mobile detail headers do not collapse cleanly | Still broken | The issue is worse than the first pass suggested. Vector mobile measured a `31px` title lane over `7` lines. VRT mobile measured a `31px` title lane over `2` lines. Raster mobile overflows horizontally and hides the H1 from Playwright visibility checks. | [vector-mobile-manual.png](./evidence/manual/vector-mobile-manual.png), [raster-mobile-manual.png](./evidence/manual/raster-mobile-manual.png), [vrt-mobile-manual.png](./evidence/manual/vrt-mobile-manual.png), [notes-vector_dataset-mobile.log](./logs/notes-vector_dataset-mobile.log), [notes-vrt_dataset-mobile.log](./logs/notes-vrt_dataset-mobile.log) |
| `F-003` Raster overview hero underuses the available space | Still broken | Desktop raster still places a small preview inside a very large hero canvas, so the section reads as mostly empty whitespace. | [raster-desktop-manual.png](./evidence/manual/raster-desktop-manual.png), [raster_dataset-desktop.png](./evidence/raster_dataset-desktop.png) |
| `F-004` Collection detail uses a different shell than the dataset variants | Still broken | Collection still reads like a separate product surface: no secondary nav, a standalone metadata card, and a long list-first body. On mobile the title wraps to `4` lines while edit/delete stay inline. | [collection-desktop-manual.png](./evidence/manual/collection-desktop-manual.png), [collection-mobile-manual.png](./evidence/manual/collection-mobile-manual.png), [notes-collection-mobile.log](./logs/notes-collection-mobile.log) |

## New Findings

### F-005: Raster mobile header overflows the viewport and collapses the title
- Severity: `P1`
- Type: `Responsive` / `UX`
- Record type: `raster_dataset`
- Tab/area: `Header / action row`
- Steps: Open `http://localhost:8080/datasets/f15ae3e9-006e-449d-8920-ee55f206a3dc#overview` at `375x812`.
- Expected: The title keeps a readable lane and actions collapse without horizontal scrolling.
- Actual: `Add to Map`, `Download COG`, `Connect`, and the overflow trigger remain inline. The page expands to `472px` wide on a `375px` viewport, the overflow trigger lands at `x=433.98`, and the H1 becomes hidden to Playwright.
- Evidence: [raster-mobile-manual.png](./evidence/manual/raster-mobile-manual.png), [raster_dataset-mobile.png](./evidence/raster_dataset-mobile.png), [axe-raster_dataset-mobile.log](./logs/axe-raster_dataset-mobile.log)
- Suggested fix: Give the title its own row or lane at the mobile breakpoint and move secondary actions, including `Download COG`, into overflow or a stacked action row.
- Effort: `Milestone`

### F-006: Dataset mobile tabs are undersized for touch
- Severity: `P2`
- Type: `Responsive` / `A11y`
- Record type: `vector_dataset`, `raster_dataset`, `vrt_dataset`
- Tab/area: `Tabs`
- Steps: Open any dataset detail page at `375x812`.
- Expected: Tabs remain easy to tap, with comfortable touch height and visible overflow behavior.
- Actual: All dataset mobile tabs measure only `28px` tall. Vector’s `Data` tab is only `48.8px` wide, and the five-tab vector layout feels compressed rather than touch-friendly.
- Evidence: [vector-mobile-manual.png](./evidence/manual/vector-mobile-manual.png), [raster-mobile-manual.png](./evidence/manual/raster-mobile-manual.png), [vrt-mobile-manual.png](./evidence/manual/vrt-mobile-manual.png)
- Suggested fix: Raise tab trigger height to a true mobile target, keep horizontal scrolling, and add stronger affordance that the tab row is scrollable when it overflows.
- Effort: `Easy win`

### F-007: Collection metadata card breaks description-list semantics
- Severity: `P1`
- Type: `A11y`
- Record type: `collection`
- Tab/area: `Metadata card`
- Steps: Run axe on the collection detail page or inspect the metadata card markup.
- Expected: `<dt>` and `<dd>` pairs live inside a `<dl>`.
- Actual: The collection page renders `<dt>` and `<dd>` inside generic `<div>` wrappers, producing a serious axe failure on desktop and mobile.
- Evidence: [axe-collection-desktop.log](./logs/axe-collection-desktop.log), [axe-collection-mobile.log](./logs/axe-collection-mobile.log), [collection-desktop-manual.png](./evidence/manual/collection-desktop-manual.png)
- Suggested fix: Convert the metadata card body to a real `<dl>` with grouped rows, or swap to plain text blocks if the layout does not want description-list semantics.
- Effort: `Easy win`

### F-008: Raster band-details overflow region is not keyboard reachable
- Severity: `P1`
- Type: `A11y`
- Record type: `raster_dataset`
- Tab/area: `Overview -> Raster Properties -> Band Details`
- Steps: Open raster detail on mobile and run axe.
- Expected: The horizontally scrollable table container is keyboard focusable so non-pointer users can reach and scroll it.
- Actual: Axe flags the shared table container (`overflow-x-auto`) as a serious `scrollable-region-focusable` failure.
- Evidence: [axe-raster_dataset-mobile.log](./logs/axe-raster_dataset-mobile.log), [raster-mobile-manual.png](./evidence/manual/raster-mobile-manual.png)
- Suggested fix: Make the shared table container focusable with a visible focus ring, and verify horizontal scrolling works from keyboard focus.
- Effort: `Easy win`

### F-009: VRT status badge fails color contrast
- Severity: `P2`
- Type: `A11y` / `Visual`
- Record type: `vrt_dataset`
- Tab/area: `Overview -> Identity & Derivation`
- Steps: Open the VRT detail page and run axe.
- Expected: Status and trust badges meet WCAG AA contrast against their background.
- Actual: Axe flags an outline badge on the VRT page for `color-contrast`. Based on the current code and screenshot, the likely offender is the green `Ready` status badge in the overview card.
- Evidence: [axe-vrt_dataset-desktop.log](./logs/axe-vrt_dataset-desktop.log), [axe-vrt_dataset-mobile.log](./logs/axe-vrt_dataset-mobile.log), [vrt-desktop-manual.png](./evidence/manual/vrt-desktop-manual.png)
- Suggested fix: Reuse the higher-contrast semantic success badge classes already defined in `status-colors.ts` instead of green text on a near-white outline badge.
- Effort: `Easy win`

## A11y & Keyboard Summary

- Keyboard smoke checks passed for the global chrome on every page.
- No dataset page failed the basic first-Tab / second-Tab smoke test.
- Confirmed serious axe failures:
  - Collection metadata semantics: [`dlitem`](./logs/axe-collection-desktop.log)
  - Raster mobile scrollable table container: [`scrollable-region-focusable`](./logs/axe-raster_dataset-mobile.log)
  - VRT status badge contrast: [`color-contrast`](./logs/axe-vrt_dataset-desktop.log)

## Cross-cutting UX Themes

- The dataset shell is not mobile-safe yet. The top row tries to carry title, CTA group, and overflow at once.
- Raster has two separate hero problems:
  - mobile containment is broken;
  - desktop composition wastes the canvas even when the preview loads.
- The collection page needs an explicit product decision:
  - align it with dataset-detail wayfinding; or
  - keep it distinct, but then give it equally intentional hierarchy and mobile behavior.

## Easy Wins

- Fix collection metadata semantics by wrapping the card content in a real `<dl>`.
- Make the shared scrollable table container keyboard focusable.
- Swap the VRT `Ready` badge to the existing semantic success color token set.
- Increase mobile tab height from `28px` to a real touch target and keep the row scrollable.

