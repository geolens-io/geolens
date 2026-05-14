---
phase: 1038-a11y-i18n-sketch-fidelity-and-uat-closeout
plan: 01
subsystem: ui
tags: [react, maplibre, builder, ux, a11y, sheet, tooltip, alertdialog]

# Dependency graph
requires:
  - phase: 1034-unified-stack-rows-and-layer-editor-flyout
    provides: LayerEditorPanel with isDrillDown prop scaffold, StackRow kebab menu
  - phase: 1037-empty-state-add-dataset-modal-and-flyout-flow
    provides: useBuilderLayout isEditorHidden hook, handleCloseEditor wiring

provides:
  - BSR-13: narrow-viewport (<800px) drill-down Sheet overlay in MapBuilderPage with isDrillDown=true
  - EXP-01: StackRow kebab Delete now shows inline alertdialog confirm before calling onRemove
  - VIS-02: LayerEditorTypePill chip + geometry subtitle in LayerEditorPanel header
  - VIS-03: Settings cog button in UnifiedStackPanel wrapped in Tooltip

affects:
  - 1038-04-playwright-uat (assertions for confirm strip, type pill, and BSR-13 Sheet)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Drill-down Sheet overlay: Sheet open={true} with onOpenChange routing to handleCloseEditor; LayerEditorPanel isDrillDown=true shows ChevronLeft back arrow
    - Inline alertdialog confirm: confirmingDelete state, sibling div outside DropdownMenu, role=alertdialog, two Button variants
    - Type pill component: inline-flex chip with bg-[var(--surface-2)], label resolved via getLayerCapabilities DEM > VRT > Raster > geometry_type > Vector
    - Tooltip on icon button: Tooltip > TooltipTrigger asChild > TooltipContent; no TooltipProvider (global in App.tsx)

key-files:
  created: []
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.test.ts

key-decisions:
  - "BSR-13: Sheet overlay rendered as a sibling outside the three-column grid div (not inside an aside column) so it does not collapse the map column"
  - "Inline confirm for layer delete: placed as sibling fragment child below the row div rather than inside DropdownMenuContent to avoid portaling/focus issues"
  - "Type pill label resolution order: DEM (is_dem=true, raster/vrt) > VRT > Raster > dataset_geometry_type > Vector"
  - "Subtitle omits EPSG: dataset_srid is not on MapLayerResponse; subtitle shows geometry_type only (or '1 band' for rasters)"
  - "TooltipProvider not added to UnifiedStackPanel: App.tsx mounts it globally; SidebarRail.tsx confirms pattern"
  - "Merge conflict resolution: use-builder-layers.test.ts updated upstream wins; BSR-18 tests live in dedicated add-dataset test file"

patterns-established:
  - "Sheet drill-down: always use open={true} with onOpenChange guard for handleCloseEditor; never manage open state separately"
  - "Alertdialog confirm strip: render as React fragment sibling of the row, not inside any portal/menu"

requirements-completed: [BSR-13, BSR-24]

# Metrics
duration: 25min
completed: 2026-05-13
---

# Phase 1038 Plan 01: BSR-13 Drill-Down + Sketch-Fidelity Fixes Summary

**Narrow-viewport Sheet overlay with isDrillDown=true wired (BSR-13), kebab Delete inline alertdialog confirm (EXP-01 BLOCKER), LayerEditorTypePill chip + subtitle in header (VIS-02), and Settings Tooltip (VIS-03)**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-13T00:15:00Z
- **Completed:** 2026-05-13T00:40:00Z
- **Tasks:** 2
- **Files modified:** 5 (4 source + 1 test conflict resolution)

## Accomplishments
- Closed BSR-13: at isEditorHidden (<800px), selecting a layer or basemap/settings scene now opens LayerEditorPanel in a Sheet overlay with a ChevronLeft back arrow
- Closed EXP-01 BLOCKER: StackRow kebab Delete no longer calls onRemove directly; an inline role=alertdialog confirm strip (Delete + Keep layer) appears before destruction
- Added LayerEditorTypePill chip to the LayerEditorPanel header — resolves label as DEM·hillshade, VRT, Raster, or geometry type
- Wrapped UnifiedStackPanel Settings cog in a Tooltip (VIS-03)
- Resolved pre-existing merge conflict in use-builder-layers.test.ts (upstream version keeps BSR-18 tests in dedicated file)

## Task Commits

1. **Task 1: Wire BSR-13 drill-down Sheet variant in MapBuilderPage** - `a2222657` (feat)
2. **Task 2: StackRow inline confirm + LayerEditorPanel type pill + Settings Tooltip** - `7ab84537` (feat)

**Plan metadata:** (committed below with SUMMARY.md)

## Files Created/Modified
- `frontend/src/pages/MapBuilderPage.tsx` - Added BSR-13 Sheet overlay block (isEditorHidden + layer/scene active); isDrillDown=true; same synthetic placeholder as desktop editor column
- `frontend/src/components/builder/StackRow.tsx` - Added Button import, confirmingDelete state, changed kebab Delete onSelect to setConfirmingDelete(true), added inline alertdialog confirm fragment sibling
- `frontend/src/components/builder/LayerEditorPanel.tsx` - Added LayerEditorTypePill component, refactored header title to flex-col with pill + subtitle; subtitle shows geometry type or '1 band' for rasters
- `frontend/src/components/builder/UnifiedStackPanel.tsx` - Added Tooltip/TooltipContent/TooltipTrigger import, wrapped Settings cog button
- `frontend/src/components/builder/hooks/__tests__/use-builder-layers.test.ts` - Resolved merge conflict (upstream wins; comment points to dedicated BSR-18 test file)

## Decisions Made
- **Sheet vs inline panel for BSR-13:** Sheet overlay was chosen because at <800px the three-column grid only has two columns (sidebar + map); a third column cannot appear without grid reconfiguration. The Sheet renders outside the grid as a portal, preserving the map column layout.
- **Inline confirm placement:** The alertdialog confirm strip is a React fragment sibling of the row div, not inside DropdownMenuContent. DropdownMenu portals its content; placing the confirm inside would cause focus and z-index issues. Fragment sibling is the pattern used by FolderGroupRow.tsx (confirmed already correct there).
- **Type pill label resolution:** DEM takes priority over VRT/Raster because is_dem=true layers are a semantic subtype. VRT before Raster because VRT is a more specific format. geometry_type before 'Vector' fallback because specific geometry (MultiPoint, LineString) is more useful.
- **Subtitle EPSG omission:** `dataset_srid` is not on `MapLayerResponse`; the PATTERNS.md reference was aspirational. Subtitle shows geometry type only. No type error; no stub.
- **FolderGroupRow skip:** The plan said to apply confirm to the group-row Delete in StackRow but the grep found `kebabDeleteGroup` only in `FolderGroupRow.tsx`, which already has `confirmingDelete` state and the alertdialog pattern. No change needed there.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Resolved pre-existing merge conflict blocking commits**
- **Found during:** Task 1 commit attempt
- **Issue:** `use-builder-layers.test.ts` had an unresolved merge conflict (<<<<<<< markers), blocking `git commit`
- **Fix:** Accepted "Updated upstream" resolution — BSR-18 `handleAddDataset` tests live in the dedicated `use-builder-layers.add-dataset.test.ts` file per that file's existence on disk
- **Files modified:** `frontend/src/components/builder/hooks/__tests__/use-builder-layers.test.ts`
- **Committed in:** `a2222657` (Task 1 commit)

**2. [Rule 2 - Deviation from pattern doc] Subtitle omits EPSG due to missing field**
- **Found during:** Task 2 (LayerEditorPanel type pill + subtitle implementation)
- **Issue:** `dataset_srid` referenced in PATTERNS.md does not exist on `MapLayerResponse` type; adding it would cause a TypeScript error
- **Fix:** Subtitle shows `dataset_geometry_type` only (or '1 band' for rasters); EPSG line suppressed
- **Files modified:** `frontend/src/components/builder/LayerEditorPanel.tsx`

**3. [Rule 2 - Deviation from plan text] FolderGroupRow group delete already had confirm**
- **Found during:** Task 2 research (StackRow group delete search)
- **Issue:** Plan said to apply confirm to "the group-row Delete group kebab item that exists in StackRow (search for `kebabDeleteGroup`)" but `kebabDeleteGroup` is in `FolderGroupRow.tsx`, not `StackRow.tsx`; FolderGroupRow already had `confirmingDelete` state and alertdialog since a prior phase
- **Fix:** No change needed; existing implementation already matches the pattern
- **Files modified:** None

---

**Total deviations:** 3 (1 blocking fix, 2 pattern adjustments)
**Impact on plan:** All deviations are required for correctness. No scope creep. Plan goals fully achieved.

## Issues Encountered
- Pre-existing TypeScript errors in test files (DEMEditorScene.test.tsx, EmptyStackState.test.tsx, StackRow.test.tsx, UnifiedStackPanel.test.tsx, normalize-saved-map.test.ts) are all pre-existing and out of scope per scope boundary rules.
- Pre-existing `react-hooks/exhaustive-deps` warnings in MapBuilderPage.tsx are pre-existing and unchanged.

## Next Phase Readiness
- BSR-13 wired; Plan 04 Playwright UAT can assert Sheet opens at <800px with back arrow
- EXP-01 confirm strip in place; Plan 04 can assert alertdialog appears on Delete kebab click
- VIS-02 type pill in DOM; Plan 04 can assert `LayerEditorTypePill` text in header
- VIS-03 Tooltip present; Plan 04 can assert tooltip label on hover
- Plans 02 (i18n) and 03 (remaining sketch polish) are independent

---
*Phase: 1038-a11y-i18n-sketch-fidelity-and-uat-closeout*
*Completed: 2026-05-13*
