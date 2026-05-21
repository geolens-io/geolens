# Quick Task 260318-hoo: Fix spatial filter panel review findings - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Task Boundary

Fix all findings from post-implementation review of SpatialFilterPanel (260318-g6s + 260318-gnv):

### Blockers
1. "Use current map extent" doesn't call `td.setMode('rectangle')` — next draw uses wrong mode
2. Slide animation never fires — component conditionally rendered, CSS transition has no effect. Always render and control via `open` prop.

### Should Fix
3. Mobile "Clear location" doesn't reset `spatial_predicate` (FilterPanel.tsx ~line 749)
4. Polygon draws complex shape but backend uses bbox — misleading precision. Add visual bbox indicator showing actual search area.
5. No keyboard dismiss or focus management — add Escape handler, `role="dialog"`, `aria-modal`, focus trap

### Nice-to-haves
6. Backend: validate `spatial_predicate` with `Literal["intersects", "within"]`
7. Frontend unit tests: search store `spatial_predicate` round-trip in `toParams()`/`restoreParams()`/`resetFilters()`
8. Backend tests: `spatial_predicate=within` in test_search.py
9. Terra Draw/MapLibre recreated on every open/close — always render component to preserve map state

</domain>

<decisions>
## Implementation Decisions

All items from the review should be addressed. No gray areas — findings are specific with suggested fixes.

- Blocker 2 + Nice-to-have 9 converge: always render SpatialFilterPanel and control visibility via `open` prop. This fixes both the animation issue and the recreation cost.
- For polygon bbox indicator: show a dashed rectangle overlay on the map representing the actual bbox being sent to the API.

</decisions>
