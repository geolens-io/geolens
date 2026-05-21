# Quick Task 260413-fvg: Extract DatasetStatsLine, DatasetHeroMap, and BuilderSidebar

## Results

| Metric | Before | After |
|--------|--------|-------|
| DatasetPage.tsx | 719 lines | 584 lines (−135) |
| MapBuilderPage.tsx | 697 lines | 423 lines (−274) |
| New components | 0 | 3 |

## Components Created

1. **DatasetStatsLine.tsx** (120 lines) — Stats bar with record type badge, geometry, EPSG, visibility, etc.
2. **DatasetHeroMap.tsx** (97 lines) — Hero map container with skeleton, DatasetMap, raster error overlay, retry.
3. **BuilderSidebar.tsx** (355 lines) — Desktop sidebar with resize handle, collapse button, header inputs, button tray, SidebarContent.

## Commits

| # | Hash | Description |
|---|------|-------------|
| 1 | cf6a237f | Extract DatasetStatsLine from DatasetPage |
| 2 | 81b775ce | Extract DatasetHeroMap from DatasetPage |
| 3 | f5b055b5 | Extract BuilderSidebar and SidebarContent from MapBuilderPage |

## Verification

- TypeScript: `tsc --noEmit` clean after each commit
- Tests: 947/947 passed, 0 failures
- Pure extraction — no behavior changes
- `HeroState` type exported from `use-hero-state.ts` (was internal)
- `SidebarContent` re-exported from BuilderSidebar for mobile Sheet usage
