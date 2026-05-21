---
phase: quick-51
plan: 01
subsystem: raster
tags: [bug-fix, raster, auth, frontend, backend]
dependency_graph:
  requires: []
  provides: [UAT-GAP-6, UAT-GAP-11, UAT-GAP-8]
  affects: [BuilderMap, AccessSharingTab, datasets-router]
tech_stack:
  added: []
  patterns: [get_optional_user anonymous access pattern]
key_files:
  modified:
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/dataset/tabs/AccessSharingTab.tsx
    - backend/app/datasets/router.py
decisions:
  - Raster layer in BuilderMap only enters raster branch when token?.kind === 'raster' — no layer_type fallback
  - Quicklook anonymous access uses record_status + visibility check inline (no helper); returns 404 to avoid leaking existence
metrics:
  duration: 8 min
  completed: "2026-03-14"
  tasks_completed: 3
  files_modified: 3
---

# Quick Task 51: Fix v10.0 UAT Gaps — Raster Rendering, Export Section, Quicklook Auth

**One-liner:** Three targeted fixes resolving the final UAT gaps blocking v10.0 sign-off — raster tile rendering in map builder, spurious Export card on raster detail pages, and anonymous quicklook access for public catalog thumbnails.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Fix BuilderMap raster branch nested condition bug | b312284 | BuilderMap.tsx |
| 2 | Hide Export section for raster datasets in AccessSharingTab | 85bac32 | AccessSharingTab.tsx |
| 3 | Fix quicklook endpoint to allow anonymous access for public published datasets | c2d4651 | datasets/router.py |

## Fixes Detail

### Task 1 — BuilderMap raster branch (UAT-GAP-6)

**Root cause:** The outer `if` condition was `token?.kind === 'raster' || layer.layer_type === 'raster_geolens'`. When the token had not yet been fetched, the `layer_type` fallback made the outer condition true. The inner `if (token?.kind === 'raster')` then failed, so no source was added — but `desiredSources.add(sourceId)` and `continue` still executed, silently skipping the layer every sync cycle until a page reload.

**Fix:** Collapsed the outer condition to `token?.kind === 'raster'` only. When the token is not yet fetched, the layer falls through to the vector branch (which also won't add a source without a token), then the next `syncLayersToMap` call triggered by `tokenMap` changes adds the raster source correctly.

### Task 2 — AccessSharingTab Export card (UAT-GAP-11)

**Root cause:** The Export card rendered unconditionally in `AccessSharingTab`.

**Fix:** Added `const isRaster = dataset.record_type === 'raster_dataset'` and wrapped the Export card in `{!isRaster && (...)}`. The `record_type` field is already present on `DatasetResponse` from Phase 168.

### Task 3 — Quicklook anonymous access (UAT-GAP-8)

**Root cause:** The `/api/datasets/{id}/quicklook` endpoint used `get_current_active_user` (requires valid JWT). Browser `<img src>` tags do not send Authorization headers, so every catalog thumbnail request returned 401/403.

**Fix:** Changed dependency to `get_optional_user`. For unauthenticated requests, checks `record_status == "published"` and `visibility == "public"` inline and returns 404 if either check fails (avoids leaking dataset existence). Authenticated requests continue to delegate to `check_dataset_access` as before. The existing `Cache-Control: public, max-age=3600` header is correct for browser caching of public quicklooks.

## Verification

- `cd frontend && npx tsc --noEmit` — zero errors
- `cd backend && python -c "from app.datasets.router import router"` — import ok

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- b312284 exists: FOUND
- 85bac32 exists: FOUND
- c2d4651 exists: FOUND
- frontend/src/components/builder/BuilderMap.tsx: modified
- frontend/src/components/dataset/tabs/AccessSharingTab.tsx: modified
- backend/app/datasets/router.py: modified
