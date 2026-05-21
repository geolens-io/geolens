---
phase: 260318-i0y
plan: 01
started: "2026-03-18T17:03:54Z"
completed: "2026-03-18T17:07:16Z"
duration: "3min"
status: complete
subsystem: search/spatial
tags: [spatial-filter, geojson, viewport, polygon, backend, frontend]
dependency_graph:
  requires: []
  provides: [geometry-geojson-spatial-filter, viewport-persistence]
  affects: [search-datasets, search-facets, ogc-items]
tech_stack:
  added: []
  patterns: [ST_GeomFromGeoJSON, module-level-viewport-ref]
key_files:
  created: []
  modified:
    - backend/app/search/router.py
    - backend/app/search/service.py
    - frontend/src/stores/search-store.ts
    - frontend/src/components/search/SpatialFilterPanel.tsx
    - frontend/src/components/search/FilterPanel.tsx
decisions:
  - Geometry GeoJSON takes precedence over bbox when both provided
  - Module-level variable for viewport persistence (survives component unmount)
  - Polygon draws send actual GeoJSON geometry; rectangles still use bbox
metrics:
  duration: 3min
  tasks_completed: 2
  tasks_total: 2
  files_modified: 5
---

# Phase 260318-i0y Plan 01: Spatial Filter Technical Debt Summary

Polygon spatial filter now sends actual GeoJSON geometry to backend using ST_GeomFromGeoJSON instead of lossy bbox extraction; mini-map viewport persists across panel open/close via module-level variable.

## What Was Done

### Task 1: Backend - Add geometry GeoJSON parameter (976cc94e)
- Added optional `geometry` query parameter to all 4 endpoints that accept `bbox`: `_handle_search`, `search_facets_endpoint`, `search_datasets_endpoint`, `collection_items`
- Parse and validate GeoJSON (must have `type` and `coordinates` keys)
- Updated all 3 spatial filter locations in `service.py` (`get_facet_counts` main query, `_apply_facet_filters` sub-query, `search_datasets`) to use `ST_GeomFromGeoJSON` when geometry is provided
- Geometry takes precedence over bbox -- when geometry is provided, bbox parsing is skipped
- Added geometry to pagination URL active_params for correct next/prev links

### Task 2: Frontend - Viewport persistence + polygon GeoJSON passthrough (0aa19637)
- Added module-level `savedViewport` variable that persists map center/zoom across panel open/close and component unmount/remount
- Changed `onApply` prop signature to accept optional `GeoJSON.Geometry` third parameter
- In `handleApply`, when `drawMode === 'polygon'`, extracts actual GeoJSON geometry from TerraDraw snapshot and passes it through
- Rectangle mode continues to send only bbox (backward compatible)
- Added `geometry` field to search store (string, serialized GeoJSON), included in `toParams()` and `restoreParams()`
- Wired geometry through FilterPanel's `onApply` callback with `JSON.stringify`
- Clear geometry when clearing bbox filter (3 locations)
- Removed dashed bbox overlay useEffect for polygon mode (no longer needed since backend now accepts actual geometry)

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- TypeScript compiles cleanly (`npx tsc --noEmit` passes)
- Python syntax valid for both modified backend files
- API container running and responding normally

## Self-Check: PASSED

All files exist. All commits verified.
