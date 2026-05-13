---
phase: 1035-basemap-group-folder-groups-and-dem-raster
plan: "05"
subsystem: ui
tags: [react, dnd-kit, radix-ui, builder, map-stack, basemap-group, folder-groups, dem, integration]

# Dependency graph
requires:
  - phase: 1035-01
    provides: use-builder-layers folder group + DEM terrain handlers
  - phase: 1035-02
    provides: BasemapGroupRow, BasemapGroupEditorScene, BasemapSublayerEditorScene components
  - phase: 1035-03
    provides: FolderGroupRow component
  - phase: 1035-04
    provides: DEMEditorScene component + StackRow DEM glyph
provides:
  - UnifiedStackPanel renders BasemapGroupRow + FolderGroupRow with dashed-border children containers
  - StackRow "Add to group…" kebab sub-list functional (existing groups + "+ New group…" item)
  - MapBuilderPage editorScene dispatch wiring (basemap-group | basemap-sublayer | dem | default)
  - MapBuilderPage wires sceneContent/sceneFooter/breadcrumbPresetName into LayerEditorPanel
  - Basemap sublayer rows are DnD-disabled (useSortable disabled=true)
  - MapStackPanel / MapStackItem / MapStackSection retired (files deleted from disk)
affects: [1036, 1037, 1038, map-builder-page, unified-stack-panel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "editorScene useMemo: derives 'basemap-group' | 'basemap-sublayer' | 'dem' | 'default' from expandedLayerId + editingLayer.is_dem"
    - "Synthetic MapLayerResponse placeholder for basemap group/sublayer scenes where no real layer object exists"
    - "SublayerRow role=option in role=listbox container (matches StackRow pattern, supports aria-selected)"
    - "ResizeObserver polyfill in test/setup.ts for Radix UI Slider + DropdownMenu in jsdom"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
    - frontend/src/components/builder/__tests__/StackRow.test.tsx
    - frontend/src/test/setup.ts
    - frontend/src/lib/normalize-saved-map.ts
  deleted:
    - frontend/src/components/builder/MapStackPanel.tsx
    - frontend/src/components/builder/MapStackItem.tsx
    - frontend/src/components/builder/MapStackSection.tsx
    - frontend/src/components/builder/__tests__/MapStackPanel.test.tsx

key-decisions:
  - "basemapGroup sublayer in-memory state (sublayerState) deferred to Phase 1038 for persistence via basemap_config"
  - "onAddCustomBasemap is a no-op stub; custom basemap picker wiring deferred to Phase 1037"
  - "Labels sublayer visibility wired to existing showBasemapLabels flag (persisted); other sublayers use local state"
  - "SublayerRow uses role=option in role=listbox (not listitem in list) to support aria-selected + tabIndex"
  - "onSwapBasemap in UnifiedStackPanel opens Add Data modal as proxy until Phase 1037 adds dedicated picker"

patterns-established:
  - "editorScene dispatches from expandedLayerId prefix: 'basemap-group' → Scene B, 'basemap:*' → Scene C, is_dem → DEM scene"
  - "Synthetic layer placeholder shape for non-layer editor scenes: id, dataset_name, layer_type='basemap_group', is_dem=false"
  - "Children containers: marginLeft=28px, paddingLeft=12px, borderLeft=1px dashed var(--border)"

requirements-completed: [BSR-05, BSR-06, BSR-07, BSR-08, BSR-09]

# Metrics
duration: 90min (including context resumption)
completed: 2026-05-13
---

# Phase 1035 Plan 05: Integration & Wiring Summary

**UnifiedStackPanel + MapBuilderPage wired with basemap group / folder group / DEM scenes; MapStackPanel / MapStackItem / MapStackSection deleted; 111 Phase 1035 tests + 24 normalize-saved-map regression tests all green**

## Performance

- **Duration:** ~90 min (including session resumption)
- **Started:** 2026-05-13T17:30:00Z (estimated from session context)
- **Completed:** 2026-05-13T20:03:54Z
- **Tasks:** 5 (+ 1 a11y auto-fix during acceptance verification)
- **Files modified:** 8 modified, 4 deleted

## Accomplishments
- Rewrote UnifiedStackPanel to render BasemapGroupRow + FolderGroupRow with their expanded children containers (28px margin-left + 12px padding-left + 1px dashed border-left); basemap sublayers are DnD-disabled
- Made StackRow "Add to group…" kebab fully functional: DropdownMenuLabel + existing group list items + "+ New group…" item wired to hook handlers
- Wired MapBuilderPage with editorScene dispatch, sceneContent/sceneFooter/breadcrumbPresetName, basemapGroup useMemo (5 sublayers), sublayer visibility/opacity handlers, and all 14 new UnifiedStackPanel props
- Retired all 4 MapStack* files (MapStackPanel, MapStackItem, MapStackSection, MapStackPanel.test.tsx) — zero remaining imports in codebase
- Added ResizeObserver polyfill to test/setup.ts enabling Radix UI Slider to render in jsdom

## Task Commits

1. **Task 1+2: UnifiedStackPanel group rendering + StackRow Add-to-group** - `87941e4d` (feat)
2. **Task 3: MapBuilderPage wiring** - `fe46be47` (feat)
3. **Task 4: Retire MapStack* files** - `be57b81e` (chore)
4. **Task 5: Acceptance verification + a11y fix** - `3be9f722` (fix)

## Files Created/Modified
- `frontend/src/components/builder/UnifiedStackPanel.tsx` - Added BasemapGroupRowWrapper, FolderGroupRowWrapper, SublayerRow; basemap group and folder group rendering with children containers
- `frontend/src/components/builder/StackRow.tsx` - "Add to group…" sub-flow: DropdownMenuLabel + group list + "+ New group…" item; "Move out of group" when parentGroupId set
- `frontend/src/pages/MapBuilderPage.tsx` - editorScene dispatch, basemapGroup useMemo, sublayer handlers, sceneContent/sceneFooter/breadcrumbPresetName wiring, all 14 new UnifiedStackPanel props
- `frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx` - Updated use-builder-layers mock with new handler fields
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` - Tests for group rendering, children containers, indent styling
- `frontend/src/components/builder/__tests__/StackRow.test.tsx` - Tests for Add-to-group sub-flow (6 new cases)
- `frontend/src/test/setup.ts` - ResizeObserver polyfill for jsdom
- `frontend/src/lib/normalize-saved-map.ts` - Updated stale JSDoc comment (removed MapStackPanel reference)
- **DELETED:** `MapStackPanel.tsx`, `MapStackItem.tsx`, `MapStackSection.tsx`, `MapStackPanel.test.tsx`

## Decisions Made
- Labels sublayer visibility wired to existing persisted `showBasemapLabels` flag; other sublayers use in-memory `sublayerState` (persistence is Phase 1038 follow-up per plan)
- `onAddCustomBasemap` is a no-op stub; custom basemap picker wiring is Phase 1037 follow-up (per plan)
- `onSwapBasemap` in UnifiedStackPanel routes to `dialogs.setShowAddData(true)` as proxy until Phase 1037 adds dedicated basemap picker (plan spec referenced `dialogs.setShowBasemapPicker` which doesn't exist in current hook interface)
- SublayerRow changed from `role="listitem"` to `role="option"` in a `role="listbox"` container (required by a11y rules — aria-selected not valid on listitem)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] ResizeObserver polyfill added to test setup**
- **Found during:** Task 3 acceptance (MapBuilderPage.header-actions.test.tsx)
- **Issue:** New `Slider` import in `UnifiedStackPanel.tsx` pulled in `@radix-ui/react-use-size` → `ResizeObserver`, which jsdom doesn't provide; 3 of 4 tests failed with `ResizeObserver is not defined`
- **Fix:** Added a stub `ResizeObserver` class to `frontend/src/test/setup.ts` — standard jsdom polyfill pattern
- **Files modified:** `frontend/src/test/setup.ts`
- **Verification:** All 4 MapBuilderPage.header-actions tests pass
- **Committed in:** `fe46be47` (Task 3 commit)

**2. [Rule 1 - Bug] a11y: SublayerRow role fixed from listitem to option**
- **Found during:** Task 5 acceptance verification (ESLint run)
- **Issue:** `role="listitem"` does not support `aria-selected` or `tabIndex` (3 ESLint jsx-a11y errors)
- **Fix:** Changed `SublayerRow` to `role="option"` and wrapped sublayers container to `role="listbox"` with `aria-label="Basemap sublayers"` — matches StackRow pattern
- **Files modified:** `frontend/src/components/builder/UnifiedStackPanel.tsx`
- **Verification:** ESLint clean, all 111 tests still passing
- **Committed in:** `3be9f722`

**3. [Rule 3 - Blocking] dialogs.setShowBasemapPicker does not exist**
- **Found during:** Task 3 (MapBuilderPage wiring)
- **Issue:** Plan spec referenced `dialogs.setShowBasemapPicker` for onSwapBasemap; this prop is not in the current `useBuilderDialogs` interface
- **Fix:** Used `dialogs.setShowAddData(true)` as proxy (opens Add Data modal) with comment marking Phase 1037 as the proper follow-up
- **Files modified:** `frontend/src/pages/MapBuilderPage.tsx`
- **Verification:** No TypeScript errors; Add Data modal opens on swap click
- **Committed in:** `fe46be47`

---

**Total deviations:** 3 auto-fixed (1 missing infrastructure, 1 bug, 1 blocking)
**Impact on plan:** All auto-fixes necessary for correctness and test stability. No scope creep.

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `onAddCustomBasemap={() => {}}` | `MapBuilderPage.tsx:408` | Phase 1037 will add custom basemap picker |
| `sublayerState` in-memory only | `MapBuilderPage.tsx:186` | Phase 1038 will persist via basemap_config |
| `onSettingsClick={() => {}}` | `MapBuilderPage.tsx:560,574` | Phase 1036 will wire settings |
| `onSwapBasemap` opens Add Data modal | `MapBuilderPage.tsx` | Phase 1037 will add dedicated basemap picker |

All stubs are intentional per the plan's stated scope boundaries. None prevent the plan's goal from being achieved (BSR-05 through BSR-09 all satisfied).

## Verification Results

| Check | Result |
|-------|--------|
| Phase 1035 component tests (8 files, 111 tests) | PASS |
| 1033 normalize-saved-map regression (24 tests) | PASS |
| TypeScript typecheck (tsc --noEmit) | PASS (clean) |
| ESLint (changed files) | PASS (clean after a11y fix) |
| Vite production build | PASS (1 pre-existing chunk size warning) |
| Full vitest suite (1572 tests) | 1571 PASS / 1 FAIL (pre-existing i18n/resources.test.ts on main) |

## Issues Encountered
- `ResizeObserver is not defined` in jsdom when `UnifiedStackPanel` now imports `Slider` from Radix UI — resolved by polyfill in setup.ts
- `role="listitem"` with `aria-selected` rejected by jsx-a11y — resolved by using `role="option"` in `role="listbox"` container (matching StackRow's established pattern)

## Next Phase Readiness
- All 5 BSR requirements (BSR-05..BSR-09) satisfied
- Phase 1035 is complete — all 5 plans executed
- Phase 1036 can wire settings panel (placeholder `onSettingsClick` is ready)
- Phase 1037 can add custom basemap picker (placeholder `onAddCustomBasemap` and `onSwapBasemap` are ready)
- Phase 1038 can persist sublayer state via basemap_config

---
*Phase: 1035-basemap-group-folder-groups-and-dem-raster*
*Completed: 2026-05-13*
