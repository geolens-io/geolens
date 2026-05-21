# Record Detail QA Findings

Audit scope:
- Vector dataset detail: `/datasets/c4085719-be96-4544-96b4-2cbc3baecaf3`
- Raster dataset detail: `/datasets/f15ae3e9-006e-449d-8920-ee55f206a3dc`
- VRT dataset detail: `/datasets/11111111-2222-3333-4444-555555555555`
- Collection detail: `/collections/da93abc1-920d-4de8-8f44-c3880c7b8f2e`

## P0 Blocking Bugs

### F-001: VRT preview fails loudly and leaves the hero in a broken state
- Severity: `P0`
- Type: `Bug` / `UX`
- Record type: `vrt_dataset`
- Tab/area: `Overview` hero map
- Steps: Open `http://localhost:8080/datasets/11111111-2222-3333-4444-555555555555#overview` on desktop or mobile and wait for the preview to settle.
- Expected: The VRT preview either renders reliably or degrades into a clear empty/error state.
- Actual: The hero area stays visually incomplete/blank while the console floods with repeated 500 tile failures and AJAX errors.
- Evidence: [vrt-desktop.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vrt-desktop.png), [vrt-mobile.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vrt-mobile.png), [console-vrt.log](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/logs/console-vrt.log)
- Suggested fix: Stop retrying failed tile fetches indefinitely, and show a dedicated preview error/empty state with a retry path or a fallback summary card.
- Effort: `Milestone`

## P1 UX Gaps

### F-002: Mobile detail headers do not collapse cleanly
- Severity: `P1`
- Type: `UX`
- Record type: `vector_dataset`, `raster_dataset`, `vrt_dataset`
- Tab/area: Top header / action row
- Steps: Open each detail page at `375x812`.
- Expected: The title stays readable and primary actions collapse into an overflow menu or compact mobile layout.
- Actual: The vector title wraps into many lines, the raster title truncates down to a single visible letter, and the action row remains crowded and inline.
- Evidence: [vector-mobile.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vector-mobile.png), [raster-mobile.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/raster-mobile.png), [vrt-mobile.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/vrt-mobile.png)
- Suggested fix: Clamp the heading to 1-2 lines, prioritize the title over secondary metadata, and collapse non-essential actions behind a kebab menu at the mobile breakpoint.
- Effort: `Easy win`

## P2 Polish / Nice-to-haves

### F-003: Raster overview hero underuses the available space
- Severity: `P2`
- Type: `UX`
- Record type: `raster_dataset`
- Tab/area: Overview hero / quicklook
- Steps: Open `http://localhost:8080/datasets/f15ae3e9-006e-449d-8920-ee55f206a3dc#overview` on desktop.
- Expected: The hero area uses the available canvas to present a strong preview or clearly structured metadata.
- Actual: The preview is small and pinned to the left while most of the hero area reads as empty whitespace.
- Evidence: [raster-desktop.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/raster-desktop.png)
- Suggested fix: Refit the preview to the container or restructure the hero into a preview-plus-facts layout so the large canvas feels intentional.
- Effort: `Easy win`

### F-004: Collection detail uses a different shell than the dataset variants
- Severity: `P2`
- Type: `Consistency` / `UX`
- Record type: `collection`
- Tab/area: Overall page shell
- Steps: Open `http://localhost:8080/collections/da93abc1-920d-4de8-8f44-c3880c7b8f2e` on desktop or mobile.
- Expected: Sibling detail experiences share a consistent wayfinding model and secondary navigation.
- Actual: The collection page has no tabs and jumps directly into the dataset list, which makes it feel like a separate product surface rather than a peer detail variant.
- Evidence: [collection-desktop.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/collection-desktop.png), [collection-mobile.png](/Users/ishiland/Code/geolens/.planning/quick/260320-use-the-playwright-mcp-server-to-qa-all-/evidence/collection-mobile.png)
- Suggested fix: Either align the collection shell with the dataset-detail composition or make the difference explicit with stronger collection-specific framing.
- Effort: `Milestone`

## A11y & Keyboard

- No confirmed keyboard-only blocker was validated in this pass.
- I did not complete a dedicated tab-order sweep after the browser session dropped, so keyboard regression risk remains open.

## Consistency and Content

- The record-type experiences are uneven: vector/raster/VRT have tabbed detail shells, while collection does not.
- The mobile title behavior is inconsistent across types, which creates avoidable cognitive friction when users switch record types.
- The VRT preview failure path should not rely on console noise alone; users need an on-screen explanation.

## Easy wins

- Collapse header actions into a mobile overflow menu.
- Clamp mobile dataset titles to a sensible max number of lines.
- Fit the raster hero preview to the available canvas or reflow it into a denser layout.
- Add an explicit VRT preview error/empty state instead of leaving the map region visually blank.

## Milestone candidate breakdown

- Responsive detail header cleanup: mobile title sizing, action overflow, tab spacing, and header density.
- Preview failure handling: VRT and raster hero fallback states, plus better surfacing of backend tile/preview errors.
- Collection shell alignment: decide whether collection should share the same detail language as the dataset variants or remain intentionally distinct.
