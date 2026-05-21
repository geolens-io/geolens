# Quick Task 260424-lqy: Map builder basemap selector — layer disappearance bug + UX polish - Context

**Gathered:** 2026-04-24
**Status:** Ready for planning

<domain>
## Task Boundary

Fix the map builder basemap selector bug where rapid basemap toggling causes data layers to disappear, and polish the basemap picker UX (thumbnails, selected state, animation, labels toggle placement).

</domain>

<decisions>
## Implementation Decisions

### Basemap Selector UX Scope
- **Polish current pattern**: Keep the dropdown grid approach. Fix thumbnail sizing, add a visible selected-state ring, improve expand/collapse animation, and clean up the "Show place labels" toggle placement.
- Do NOT redesign into a popover, sidebar panel, or fundamentally different interaction pattern.

### Style Switching Strategy
- **Fix the race condition only**: Keep `styleDiffing={false}` + `style.load` event re-sync pattern. Fix the race by debouncing basemap changes, cancelling stale `style.load` listeners, and ensuring the final `style.load` always fires `syncLayersToMap()`.
- Do NOT switch to `transformStyle` callback approach.
- The blank basemap's fallback glyph URL (`demotiles.maplibre.org`) causes CORS errors — fix by using a CORS-safe glyph URL or skipping glyphs for inline styles.

### Claude's Discretion
- Specific debounce timing and implementation details
- Exact thumbnail dimensions and selected-state styling
- Whether to animate the basemap grid expansion or keep it instant

</decisions>

<specifics>
## Specific Ideas

### Bug Reproduction Evidence (Playwright)
- Single basemap switches (Positron→Dark, Dark→OSM, OSM→None) work fine — layers survive
- Rapid toggling (4 switches in quick succession) reliably causes layer loss
- After rapid toggle, map shows only basemap tiles with no data layers
- 58 CORS errors from `demotiles.maplibre.org/font/` during None basemap transitions
- Root cause: `style.load` event listener cleanup race in `BuilderMap.tsx:205-234`

### Key Code Locations
- `BuilderMap.tsx:205-234` — style.load re-sync effect (the bug)
- `BuilderMap.tsx:86-94` — basemap style computation
- `BuilderMap.tsx:454` — `styleDiffing={false}` prop
- `BasemapPicker.tsx` — the UI component
- `basemap-utils.ts:64-96` — `toMaplibreStyle()` with inline style generation
- `map-sync.ts:70-86` — `reorderBasemapLabels()`

</specifics>
