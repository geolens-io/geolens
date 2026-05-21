# Quick Task: Extract DatasetStatsLine, DatasetHeroMap, BuilderSidebar - Research

**Researched:** 2026-04-13
**Domain:** React component extraction (pure refactor)
**Confidence:** HIGH

## Summary

The deferred plans in `docs-internal/audits/post-impl-20260413-deferred-plans.md` are accurate with minor corrections. Both source files exist at the expected sizes (DatasetPage: 719 lines, MapBuilderPage: 696 lines -- plans said ~720 and ~697, close enough). The target directory `frontend/src/pages/components/` does not yet exist and must be created.

**Primary recommendation:** Execute both extractions as described in the deferred plans. The plans are correct and current.

## Plan Verification Against Current Code

### 1. DatasetStatsLine Extraction

**Plan accuracy: CORRECT** [VERIFIED: codebase read]

- `Sep` component: line 59 -- confirmed, trivial separator
- `statsLine` JSX: lines 348-445 -- confirmed, renders stats bar with record type badge, geometry type, feature count, EPSG, 3D indicator, raster stats, VRT stats, visibility badge, status, and updated date
- Props needed: `dataset: DatasetResponse` and `rasterGsd: number | null` -- confirmed, these are the only external values referenced in the statsLine block
- Imports listed in plan match actual usage: `useTranslation`, `Eye`/`EyeOff`/`ShieldAlert`, `RecordTypeBadge`, `Badge`, `cn`, `visibilityColors`, `formatRelativeDate`/`formatNumber`, `getRecordStatusLabel`/`getGeometryTypeLabel`

**One addition not in plan:** The `isTable` local variable (line 288: `const isTable = dataset.record_type === 'table'`) is used inside statsLine (line 363: `isTable ? 'rows' : 'features'`). The new component should derive this internally from `dataset.record_type` rather than accepting it as a prop.

### 2. DatasetHeroMap Extraction

**Plan accuracy: CORRECT with caveats** [VERIFIED: codebase read]

- Hero map JSX: lines 573-621 -- confirmed
- Props listed in plan are correct: `dataset`, `datasetId`, `bbox`, `isEditor`, `isDrawing`, `mapContainerRef`, `onFeatureClick`, `isRasterOrVrt`, `heroState`, `retryCount`, `mapKey`, `handleRetry`, `onMapReady`, `onTileError`
- **Additional context:** The hero map also needs `isRaster`, `isVrt`, `isTable` (for the `canEdit` prop computation on line 596 and the no-tile-url badge on line 604). These are derivable from `dataset.record_type` inside the component.
- The `isDataTabExpanded` guard (line 573: `!isDataTabExpanded && !isTable &&`) should remain in DatasetPage.tsx as it controls whether the hero map renders at all.

### 3. BuilderSidebar Extraction

**Plan accuracy: CORRECT** [VERIFIED: codebase read]

- `SidebarContent` function: lines 105-151 -- confirmed, currently a local function component
- `SIDEBAR_WIDTH_KEY`/`SIDEBAR_MIN`/`SIDEBAR_MAX` constants: lines 55-57 -- confirmed
- Sidebar resize state and `handleDragStart`: lines 168-210 -- confirmed
- Desktop sidebar JSX: lines 344-528 -- confirmed
- Props listed in plan match what's needed
- `SidebarContent` is also used by the mobile Sheet (line 338) -- confirmed, must be re-exported

**Note on `dialogs` object:** The plan lists individual props like `sidebarCollapsed`, `setSidebarCollapsed`, `showChat`, `setShowChat`. The current code uses `dialogs.sidebarCollapsed` etc. from `useBuilderDialogs` hook return. Either pass individual props (cleaner API) or pass the whole `dialogs` object. The plan's approach of individual props is better for component reusability.

## Directory State

| Path | Exists | Action |
|------|--------|--------|
| `frontend/src/pages/components/` | NO | Create directory |
| `frontend/src/pages/components/DatasetStatsLine.tsx` | NO | Create |
| `frontend/src/pages/components/DatasetHeroMap.tsx` | NO | Create |
| `frontend/src/pages/components/BuilderSidebar.tsx` | NO | Create |

## Existing Tests Impact

Three test files reference the source pages:

1. **`DatasetPage.hero.test.tsx`** -- Tests the hero state machine (skeleton, loaded, error, retry). Imports `DatasetPage` directly and renders the full page. After extraction, these tests should still pass without changes because `DatasetHeroMap` will be rendered inside `DatasetPage` transparently.

2. **`DatasetPage.edit-affordances.test.tsx`** -- Tests edit capabilities. Same transparent rendering, no changes needed.

3. **`MapBuilderPage.header-actions.test.tsx`** -- Tests header actions. Same pattern.

**Conclusion:** No test file modifications needed. The extractions are purely internal refactors; the public API of both pages (their default exports) remains unchanged.

## Verification Commands

```bash
# Type check
npx tsc --noEmit

# Run affected tests
npx vitest run frontend/src/pages/__tests__/DatasetPage.hero.test.tsx
npx vitest run frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx
npx vitest run frontend/src/pages/__tests__/MapBuilderPage.header-actions.test.tsx
```

## Common Pitfalls

### Pitfall 1: Forgetting derived locals
**What goes wrong:** The statsLine and hero map reference local variables (`isTable`, `isRaster`, `isVrt`, `bbox`, `rasterGsd`) that are computed inside DatasetPage. These must either be passed as props or re-derived inside the new components.
**How to avoid:** Derive `isTable`/`isRaster`/`isVrt` from `dataset.record_type` inside each new component. Pass `bbox` and `rasterGsd` as props since they involve computation.

### Pitfall 2: walkStatusChain extraction mentioned but not needed
**What goes wrong:** The plan mentions extracting `walkStatusChain` helper, but looking at current code (lines 306-346), there is no `walkStatusChain` helper -- the publish/unpublish logic is inline in `handlePublishToggle` and `handleUnpublish`. The `PUBLISH_CHAIN` and `UNPUBLISH_CHAIN` constants are defined inside the component's render body.
**How to avoid:** Move `PUBLISH_CHAIN` and `UNPUBLISH_CHAIN` to module level as the plan suggests, but skip the `walkStatusChain` extraction since it doesn't exist as a named function.

### Pitfall 3: useTranslation namespace
**What goes wrong:** DatasetPage uses `useTranslation('dataset')`. New components must use the same namespace.
**How to avoid:** Each new component should call `useTranslation('dataset')` with the correct namespace. BuilderSidebar uses `useTranslation('builder')`.

## Sources

### Primary (HIGH confidence)
- Direct codebase read of all source files, test files, and deferred plans document
