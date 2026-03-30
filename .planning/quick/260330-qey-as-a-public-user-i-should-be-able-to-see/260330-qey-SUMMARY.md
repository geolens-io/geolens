---
phase: 260330-qey
plan: 01
subsystem: maps
tags: [public-access, auth, routing, anonymous]
dependency_graph:
  requires: []
  provides: [PUBLIC-MAPS]
  affects: [maps-routing, maps-backend, navbar]
tech_stack:
  added: []
  patterns: [get_optional_user, MapViewerGate, conditional-ui]
key_files:
  created:
    - frontend/src/pages/MapViewerGate.tsx
    - frontend/src/pages/PublicMapViewerPage.tsx
  modified:
    - backend/app/maps/router.py
    - backend/app/maps/service.py
    - frontend/src/App.tsx
    - frontend/src/components/layout/Navbar.tsx
    - frontend/src/pages/MapsPage.tsx
    - frontend/src/components/maps/MapCard.tsx
    - frontend/src/components/maps/MapCardGrid.tsx
decisions:
  - MapViewerGate dispatches editor vs anonymous by checking isEditor() in auth store
  - PublicMapViewerPage transforms MapLayerResponse to SharedLayerResponse for ViewerMap reuse
  - Visibility filter hidden entirely for anonymous (meaningless since only public maps returned)
  - onDelete made optional on MapCardProps to conditionally hide delete buttons without prop drilling
metrics:
  duration: 10min
  completed: 2026-03-30T23:20:12Z
  tasks_completed: 2
  files_modified: 9
---

# Phase 260330-qey Plan 01: Public Maps Access Summary

**One-liner:** Anonymous users can browse /maps and view public maps via a read-only viewer, with all editor controls hidden behind isEditor() checks.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Backend: anonymous access on GET /maps/ | 02fff7c0 | router.py, service.py |
| 2 | Frontend: public /maps route, navbar link, conditional UI | c4cddc12 | App.tsx, Navbar.tsx, MapsPage.tsx, MapCard.tsx, MapCardGrid.tsx, MapViewerGate.tsx, PublicMapViewerPage.tsx |

## What Was Built

### Backend (Task 1)

- `GET /maps/` now uses `get_optional_user` instead of `get_current_active_user`
- When `user is None` (anonymous), passes `user_id=None` and `user_roles=set()` to `list_maps()`
- Fixed `_apply_vis_filter` anonymous fallback: was a pass-through (leaked all maps), now filters `Map.visibility == "public"`
- Pattern matches existing `get_maps_for_dataset` anonymous filter at line ~1007

### Frontend (Task 2)

- `/maps` and `/maps/:id` moved from `ProtectedRoute > EditorRoute` to public routes in `App.tsx`
- `MapViewerGate.tsx`: dispatches to `MapBuilderPage` for authenticated editors, `PublicMapViewerPage` for anonymous
- `PublicMapViewerPage.tsx`: loads map via `useMap(id)`, transforms `MapLayerResponse` to `SharedLayerResponse`, renders `ViewerMap` full-screen with `LayerLegend`
- `Navbar.tsx`: Maps link shown unconditionally (was gated by `can('edit_metadata')`)
- `MapsPage.tsx`: visibility filter, create button, empty state create action, MapCreateDialog, MapDeleteDialog all wrapped in `{isEditor && ...}`
- `MapCard.tsx` / `MapCardGrid.tsx`: `onDelete` prop made optional (`onDelete?`); delete button only rendered when `onDelete` is provided

## Deviations from Plan

### Auto-added: Create Map button in page header

The original plan only added the button in the empty state. Added a "Create Map" button to the `PageHeader` actions area (visible only when `isEditor`) for better discoverability when maps exist. This is a minor UX improvement aligned with the plan's intent.

None of the core planned changes were deviated from.

## Known Stubs

None. The viewer works end-to-end: `ViewerMap` builds tile URLs from `table_name` via `buildSignedTileUrl`, which produces URLs like `/api/tiles/data.{table}/{z}/{x}/{y}.pbf` without auth params for anonymous sessions.

## Self-Check: PASSED

- `frontend/src/pages/MapViewerGate.tsx` — FOUND
- `frontend/src/pages/PublicMapViewerPage.tsx` — FOUND
- Commit 02fff7c0 — present in git log
- Commit c4cddc12 — present in git log
- `tsc --noEmit` — no errors
