---
phase: 260318-gnv
plan: 01
subsystem: search
tags: [spatial-filter, ux, backend]
dependency_graph:
  requires: [search-store, spatial-filter-panel, search-service]
  provides: [st-within-support, predicate-toggle, map-extent-capture, hero-compression]
  affects: [search-api, filter-panel, search-page]
tech_stack:
  patterns: [conditional-spatial-function, store-driven-panel-state]
key_files:
  created: []
  modified:
    - backend/app/search/service.py
    - backend/app/search/router.py
    - frontend/src/stores/search-store.ts
    - frontend/src/components/search/SpatialFilterPanel.tsx
    - frontend/src/components/search/FilterPanel.tsx
    - frontend/src/pages/SearchPage.tsx
decisions:
  - "Predicate toggle defaults to Intersects; Within sends ST_Within to backend"
  - "spatialPanelOpen lives in search store (not local state) so SearchPage can react to it"
  - "Use current map extent resets draw mode to rectangle"
metrics:
  duration: 4min
  completed: "2026-03-18T16:13:01Z"
---

# Phase 260318-gnv Plan 01: Spatial Filter Panel Completeness Summary

Complete spatial filter panel UX with ST_Within backend support, Intersects/Within toggle, map extent capture, area summary, mode icons, and hero compression on panel open.

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Backend ST_Within support + spatial_predicate parameter | 70c46f43 | backend/app/search/service.py, backend/app/search/router.py |
| 2 | Frontend store, panel UX, and hero compression | 9f191322 | frontend/src/stores/search-store.ts, SpatialFilterPanel.tsx, FilterPanel.tsx, SearchPage.tsx |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

1. TypeScript compilation: PASSED (no errors)
2. Backend syntax validation: PASSED (service.py and router.py parse correctly)
3. spatial_predicate in search-store.ts: 4 occurrences (interface, initial state, toParams, restoreParams)
4. ST_Within in service.py: 3 occurrences (count query, FTS search, semantic search)
5. spatialPanelOpen in SearchPage.tsx: present in isLanding check

## Key Changes

- **Backend**: All 3 ST_Intersects locations now conditionally use ST_Within when `spatial_predicate=within`. Parameter exposed on `/search/datasets`, `/search/facets`, and `/collections/datasets/items`.
- **Store**: Added `spatial_predicate` (serialized to URL params when not default) and `spatialPanelOpen` (UI-only, not serialized).
- **Panel**: Square/Pentagon icons on draw mode toggle, Intersects/Within predicate toggle below map, "Use current map extent" button, area summary replacing instructions after drawing.
- **Hero**: Compresses when spatial panel opens (even before applying a filter).
- **Chip**: X button clears both bbox and spatial_predicate.
