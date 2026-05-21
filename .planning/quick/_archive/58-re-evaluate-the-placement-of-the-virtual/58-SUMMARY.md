---
phase: quick-58
plan: 01
subsystem: frontend
tags: [vrt, navigation, ux, routing]
dependency_graph:
  requires: [VrtCreatorForm, ImportPage, Navbar, DatasetPage]
  provides: [VrtNewPage, /vrt/new route, navbar VRT entry, raster detail VRT button]
  affects: [frontend routing, navbar create menu, import page tabs]
tech_stack:
  added: []
  patterns: [query-param-pre-selection, lazy-route-page]
key_files:
  created:
    - frontend/src/pages/VrtNewPage.tsx
  modified:
    - frontend/src/components/import/VrtCreatorForm.tsx
    - frontend/src/pages/ImportPage.tsx
    - frontend/src/App.tsx
    - frontend/src/components/layout/Navbar.tsx
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/i18n/locales/en/common.json
    - frontend/src/i18n/locales/en/import.json
decisions:
  - VRT creation moved from Import tab to dedicated /vrt/new route under EditorRoute
  - Pre-selection via ?source query param fetches OGC record from /collections/datasets/items/{id}
  - Layers icon used for VRT menu items (visually represents composing/stacking rasters)
  - Create VRT button only shown for raster_dataset (not vrt_dataset) and editor role
metrics:
  duration: 2min
  completed: 2026-03-15T17:41:12Z
---

# Quick Task 58: Re-evaluate VRT Creation Placement

VRT creation relocated from Import page tab to dedicated /vrt/new route with navbar Create dropdown and raster detail page entry points, using query param pre-selection for contextual navigation.

## Changes

### Task 1: VrtNewPage + VrtCreatorForm pre-selection + Import cleanup
- Created `VrtNewPage.tsx` with `useSearchParams` for `?source` query param
- Added `initialSourceId` prop to `VrtCreatorForm` with `useQuery` fetch from OGC catalog endpoint
- Registered `/vrt/new` route under `EditorRoute` in `App.tsx` (lazy loaded)
- Removed VRT tab from `ImportPage` (now 3 tabs: Upload File, Register Table, Service URL)
- Added `vrt.pageTitle` i18n key
- **Commit:** db1b96cc

### Task 2: Navbar Create dropdown + raster detail button
- Added "Virtual Raster" item with `Layers` icon to navbar `CreateMenu` dropdown, separated by divider
- Added "Virtual Raster" link to mobile nav Create section with separator
- Added "Create VRT" button on raster dataset detail pages linking to `/vrt/new?source={dataset.id}`
- Button conditionally rendered: `isRaster && isEditor` (not shown for VRT datasets)
- Added `nav.virtualRaster` i18n key
- **Commit:** 85959fe4

### Task 3: Visual verification (auto-approved)
- Auto-approved in auto-advance mode

## Deviations from Plan

None - plan executed exactly as written.

## Commits

| # | Hash | Message |
|---|------|---------|
| 1 | db1b96cc | feat(quick-58): create /vrt/new page, add pre-selection support, remove VRT tab from Import |
| 2 | 85959fe4 | feat(quick-58): add Virtual Raster to Create dropdown and raster detail button |
