---
phase: 1138-easy-win-sweep
plan: "03"
subsystem: ui
tags: [react, maplibre, filter, empty-state, builder, i18n]

requires:
  - phase: 1138-easy-win-sweep
    provides: phase context and EASY-18 scope definition

provides:
  - useFilteredFeatureCount hook (read-only queryRenderedFeatures idle-debounce subscription)
  - LayerFilterEditor featureCount prop + empty-state hint + Clear filter button
  - LayerEditorPanel featureCount prop forwarded to LayerFilterEditor
  - MapBuilderPage wiring of filteredFeatureCount to both LayerEditorPanel mount sites
  - i18n keys layerEditor.emptyResult.{title,help,clear} in en/de/es/fr

affects:
  - builder
  - LayerFilterEditor
  - LayerEditorPanel
  - MapBuilderPage

tech-stack:
  added: []
  patterns:
    - "Read-only queryRenderedFeatures subscription with idle-debounce and cancellation (use-filtered-feature-count.ts)"
    - "Empty-state hint rendered inside editor panel when filter produces 0 rendered features"
    - "Props-only featureCount threading: hook → page → panel → editor (no new action variants)"

key-files:
  created:
    - frontend/src/components/builder/hooks/use-filtered-feature-count.ts
    - frontend/src/components/builder/hooks/__tests__/use-filtered-feature-count.test.ts
  modified:
    - frontend/src/components/builder/LayerFilterEditor.tsx
    - frontend/src/components/builder/__tests__/LayerFilterEditor.test.ts
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "Reuse existing set_filter dispatcher path (MapBuilderPage:346-351) — no new BuilderLayerAction variant"
  - "250ms idle-debounce coalesces consecutive idle events to avoid per-frame queryRenderedFeatures calls"
  - "Return null (not 0) when layer not on map to suppress false-positive hint during source loading"
  - "showEmptyState = filter != null && featureCount === 0 (no parseResult.kind check needed — opaque filters can still be cleared)"

patterns-established:
  - "useFilteredFeatureCount pattern: idle-subscribe + 250ms debounce + cancelled flag guard for unmount safety"

requirements-completed:
  - EASY-18

duration: 6min
completed: 2026-05-28
---

# Phase 1138 Plan 03: useFilteredFeatureCount hook + LayerFilterEditor empty-state hint + Clear-filter dispatcher Summary

**MapLibre queryRenderedFeatures idle-debounce hook surfaces a "0 features" hint with Clear filter button inside LayerFilterEditor when a filter eliminates all visible features; routes through existing set_filter dispatcher with expression=null.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-28T01:18:17Z
- **Completed:** 2026-05-28T01:24:00Z
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments

- New `useFilteredFeatureCount(map, layer)` hook: subscribes to map `idle` events, 250ms-debounced, calls `map.queryRenderedFeatures` read-only, returns null when map null, layer null, no filter set, or layer not yet on map
- LayerFilterEditor renders `role="status"` empty-state block with title + help text + destructive Clear filter button when `filter != null && featureCount === 0`
- Clear filter button calls `onFilterChange(null)` — routes through LayerEditorPanel's `handlers.onFilterChange(layerId, null)` → MapBuilderPage's existing `set_filter` dispatcher — no new BuilderLayerAction variant
- MapBuilderPage invokes hook and passes `filteredFeatureCount` to both LayerEditorPanel mount sites (desktop flyout + mobile Sheet)
- 14 new regression tests across 3 test files: 7 hook null-safety/unmount tests + 5 LayerFilterEditor hint-visibility tests + 2 LayerEditorPanel prop-forwarding tests
- i18n parity: `layerEditor.emptyResult.{title,help,clear}` added to en/de/es/fr

## Task Commits

1. **Task 1: Create useFilteredFeatureCount hook** - `41e92279` (feat)
2. **Task 2: Wire featureCount through LayerEditorPanel → LayerFilterEditor** - `ac26b48e` (feat)
3. **Task 3: MapBuilderPage wiring** - `8f92ae7f` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `frontend/src/components/builder/hooks/use-filtered-feature-count.ts` — new hook, 70 lines, READ-ONLY queryRenderedFeatures + idle-debounce
- `frontend/src/components/builder/hooks/__tests__/use-filtered-feature-count.test.ts` — 7 EASY-18 regression tests
- `frontend/src/components/builder/LayerFilterEditor.tsx` — featureCount prop + showEmptyState block + Clear button
- `frontend/src/components/builder/__tests__/LayerFilterEditor.test.ts` — 5 new EASY-18 tests appended
- `frontend/src/components/builder/LayerEditorPanel.tsx` — featureCount prop added + forwarded to LayerFilterEditor
- `frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx` — 2 new EASY-18 tests + spy mock for LayerFilterEditor
- `frontend/src/pages/MapBuilderPage.tsx` — import + hook invocation + featureCount on both LayerEditorPanel mounts
- `frontend/src/i18n/locales/en/builder.json` — layerEditor.emptyResult.{title,help,clear}
- `frontend/src/i18n/locales/de/builder.json` — layerEditor.emptyResult.{title,help,clear}
- `frontend/src/i18n/locales/es/builder.json` — layerEditor.emptyResult.{title,help,clear}
- `frontend/src/i18n/locales/fr/builder.json` — layerEditor.emptyResult.{title,help,clear}

## Decisions Made

- **No new BuilderLayerAction variant:** Clear filter reuses `set_filter` with `expression: null` — the exact same dispatcher path as ActiveFilterChips. Zero contract widening.
- **null not 0 when layer not on map:** `map.getLayer(layer.id)` guard prevents false-positive hint flashing while the tile source is still loading (queryRenderedFeatures returns [] for missing layers).
- **250ms idle-debounce:** MapLibre `idle` fires once when the map settles, but consecutive pans/zooms can fire many. The debounce coalesces back-to-back idles to avoid per-frame queryRenderedFeatures overhead (T-1138-10 mitigation).
- **No parseResult.kind check for empty-state:** Opaque filters can still be cleared via the same null dispatch; requiring `kind === 'editable'` would suppress a useful signal for opaque expressions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fix createMockMap `undefined` override for getLayerResult**
- **Found during:** Task 1 (RED phase, test 4 failing)
- **Issue:** `createMockMap({ getLayerResult: undefined })` — the `??` nullish coalescing operator treats `undefined` as falsy and fell back to the default stub layer, so `map.getLayer()` returned a real stub instead of `undefined`. The test expected `count === null` but got `0`.
- **Fix:** Added `noLayer: true` flag to the mock factory so the intent is explicit; updated test 4 to pass `{ noLayer: true }`.
- **Files modified:** `use-filtered-feature-count.test.ts`
- **Committed in:** `41e92279` (Task 1 commit, inline fix during GREEN phase)

---

**Total deviations:** 1 auto-fixed (1 bug in test mock)
**Impact on plan:** Test-only fix. Production code unaffected. Required to get GREEN on test 4.

## Null-safety Branches Discovered During Testing

- **map null:** `useEffect` returns immediately — count stays `null`
- **layer null:** `useEffect` returns immediately — count stays `null`
- **layer.filter null:** `setCount(null)` called synchronously — hint suppressed
- **layer not on map:** `map.getLayer(layer.id)` returns falsy — `setCount(null)`, queryRenderedFeatures NOT called
- **basemap-group pseudo-layer:** Has no `filter` field → hook returns `null` cleanly; empty-state hint never fires for basemap group rows

## i18n Parity

4/4 locales (en/de/es/fr) contain `layerEditor.emptyResult.{title,help,clear}`. `npm run test:i18n` passes (2/2).

## Pitfall #9 Compliance

`grep -nE "map\.setFilter|map\.setPaintProperty|map\.setLayoutProperty"` returns 0 lines across all modified files. The hook exclusively uses `map.queryRenderedFeatures` (READ-ONLY) and `map.getLayer` (READ-ONLY).

## BuilderLayerAction / BuilderActionSource Invariant

`git diff -- frontend/src/components/builder/builder-action-contract.ts | wc -l` returns 0. Contract unchanged.

## Issues Encountered

None beyond the mock factory gotcha documented as Deviation 1.

## Next Phase Readiness

- EASY-18 success criterion 3 fully met: empty-state hint visible when filter active + 0 rendered features; Clear button routes through existing dispatcher
- Plan 04 MCP smoke can verify the live hint at 800px (orchestrator follows the checklist)
- No pending deferred items

---
*Phase: 1138-easy-win-sweep*
*Completed: 2026-05-28*
