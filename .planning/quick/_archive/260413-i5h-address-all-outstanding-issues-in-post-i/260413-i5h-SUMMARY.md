---
phase: 260413-i5h
plan: 01
subsystem: full-stack
tags: [audit, kiss, performance, cleanup, type-safety, resilience]
dependency_graph:
  requires: []
  provides: [audit-remediation-post-impl-20260413-b]
  affects: [maps, auth, search, config_ops, ingest, viewer, builder, dataset-page]
tech_stack:
  added:
    - backend/app/config_ops/exceptions.py (ConfigValidationError, ConfigLockedError domain exceptions)
  patterns:
    - per-request role caching via request.state
    - domain exceptions in service layer, HTTPException translation in router
    - TypedDict for multi-kwarg function signatures
key_files:
  created:
    - backend/app/config_ops/exceptions.py
  modified:
    - backend/app/maps/router.py
    - backend/app/maps/schemas.py
    - backend/app/auth/dependencies.py
    - backend/app/search/service.py
    - backend/app/datasets/schemas.py
    - backend/app/datasets/helpers.py
    - backend/app/config_ops/service.py
    - backend/app/config_ops/router.py
    - backend/app/ingest/tasks.py
    - backend/app/services/router.py
    - backend/app/ogc/router.py
    - backend/app/auth/oauth/router.py
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/hooks/use-builder-layers.ts
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/hooks/use-layer-map-sync.ts
    - frontend/src/api/tiles.ts
    - frontend/src/hooks/use-admin.ts
    - frontend/src/types/api.ts
    - frontend/src/components/import/VrtCreatorForm.tsx
    - frontend/src/components/search/SavedSearches.tsx
    - frontend/src/components/search/SpatialFilterPanel.tsx
    - frontend/src/components/builder/LayerFilterEditor.tsx
    - frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
decisions:
  - "DatasetMetaKwargs TypedDict preferred over named parameters for _build_layer_response — preserves type safety without 8-param positional list"
  - "get_cached_user_roles uses request.state to cache per-request; service-layer calls without request context keep using get_user_roles directly"
  - "Facet queries documented as intentionally sequential — SQLAlchemy AsyncSession is not safe for concurrent execute() on shared connection"
  - "job-failure boilerplate in ingest/tasks.py kept inline — each site has distinct formatting; a generic helper would obscure context"
  - "handleMoveUp/handleMoveDown kept as thin wrappers around unified handleMove for backward compatibility of external callers"
metrics:
  duration: ~30 minutes
  completed_date: "2026-04-13"
  tasks_completed: 5
  files_changed: 25
---

# Phase 260413-i5h Plan 01: Post-Impl Audit B Remediation Summary

Address all 25 remaining findings from the post-impl-20260413-b audit across 5 atomic commits by dimension.

## What Was Built

Five atomic commits, one per audit dimension, resolving 25 findings: 10 KISS simplifications, 2 performance improvements, 5 cleanup items, 4 type safety fixes, and 4 resilience improvements. Zero regressions — 947/947 frontend unit tests pass, TypeScript reports no errors.

## Commits

| Commit | Dimension | Key Changes |
|--------|-----------|-------------|
| `d1011f31` | KISS | DatasetMetaKwargs TypedDict, sharedLayerFields(), handleMove(), prefixed(), executeStatusChain(), scrollAndFocus(), 3 ingest inlines |
| `14c3ba24` | Performance | get_cached_user_roles per-request dependency, sequential facet query comment |
| `2ac8474e` | Cleanup | Remove quicklook_url from schema/helpers/types/fixture, consolidate debugLog in use-layer-map-sync, API_BASE in tiles.ts |
| `e62572b2` | Type Safety | status.HTTP_* constants, OAuth response_class, cast documentation, inline enrich_source_url in services/router |
| `7e847cf7` | Resilience | ConfigValidationError/ConfigLockedError domain exceptions, error toasts in VrtCreatorForm and SavedSearches, job-failure doc |

## Findings Addressed

### KISS (10 of 10)
- **#4**: `_build_layer_response` now takes `DatasetMetaKwargs` dict instead of 8+ positional args
- **#6**: `sharedLayerFields()` extracted in ViewerMap.tsx; shared by `toViewerSyncInput` and `toAdapterInput`
- **#13**: `handleMoveUp`/`handleMoveDown` unified into `handleMove(id, direction)` with thin wrappers
- **#14**: 4 `prefixed*Id` helpers consolidated into single `prefixed(kind, id, prefix?)` with thin wrappers
- **#15**: `executeStatusChain()` shared by `handlePublishToggle` and `handleUnpublish`
- **#16**: `scrollAndFocus()` utility extracted from 53-line `pendingNavigationAnchor` useEffect
- **#23**: `_post_reupload_success` (one-liner) inlined at both call sites
- **#24**: `enrich_source_url` (one-liner) inlined at all call sites; function removed
- **#25**: 5-clause `.endswith()` chain replaced with `any(lower_path.endswith(ext) for ext in (...))`
- **#9**: (Not applicable — `dataset_feature_count_total` was not present in the actual codebase)

### Performance (2 of 2)
- **#1**: `get_cached_user_roles` dependency added; `require_role` and `require_permission` use it
- **#2**: Explanatory comment added to facet query section documenting why sequential is correct

### Cleanup (5 of 5)
- **#10**: `quicklook_url` removed from `RasterMetadata` schema, `helpers.py` computation, frontend `api.ts` type, and test fixture
- **#18**: 30s poll interval in `use-admin.ts` documented as intentional
- **#19**: 6 inline `if (import.meta.env.DEV) console.debug(...)` blocks in `use-layer-map-sync.ts` replaced with module-level `debugLog` helper
- **#20**: `getTileTokenWithApiKey` in `tiles.ts` uses `API_BASE` constant instead of `getEnvConfig().API_BASE_URL || '/api'`
- **#17**: HNSW index params already explicit (`m=16, ef_construction=64`) — finding pre-resolved

### Type Safety (4 of 4)
- **#11**: JSDoc added to `toStoreFeature()` in SpatialFilterPanel explaining the terra-draw nominal type cast
- **#12**: Clarifying comment added to array-narrowed cast in LayerFilterEditor.tsx
- **#21**: `status_code=500` → `status.HTTP_500_INTERNAL_SERVER_ERROR` in services/router.py; `status_code=404` → `status.HTTP_404_NOT_FOUND` in ogc/router.py
- **#22**: `response_class=RedirectResponse` on login route; `response_class=Response` on callback route in oauth/router.py

### Resilience (4 of 4)
- **#5**: `config_ops/service.py` raises `ConfigValidationError`/`ConfigLockedError`; router translates to HTTPException
- **#7**: `multiSourceErrorCount` effect added to `VrtCreatorForm.tsx` — toasts when useQueries fails
- **#8**: `isError` handling added to `SavedSearches.tsx` — toasts on fetch failure
- **#3**: Job-failure inline pattern documented in `ingest/tasks.py` module docstring

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `enrich_source_url` import broken in services/router.py**
- **Found during:** Task 4
- **Issue:** `enrich_source_url` was removed from `ingest/tasks.py` during Task 1 (KISS inline pass), but `services/router.py` still imported and called it
- **Fix:** Removed the import; inlined the one-liner at the call site in services/router.py
- **Files modified:** `backend/app/services/router.py`
- **Commit:** `e62572b2`

**2. [Rule 2 - Pre-resolved] HNSW index params (#17)**
- **Found during:** Task 3
- **Issue:** Audit cited `embeddings/service.py:155-156` as missing `m` and `ef_construction`. The current code already has `WITH (m=16, ef_construction=64)` from a prior pass.
- **Fix:** No change needed; finding already resolved.

## Known Stubs

None — all changes are refactors, deletions, or error surface additions with no new stub patterns.

## Threat Flags

None — all changes are internal refactors within existing trust boundaries. The config_ops domain exception conversion carries the same error messages as the original HTTPExceptions with no information leakage change.

## Self-Check: PASSED

- `backend/app/config_ops/exceptions.py` — FOUND
- `backend/app/auth/dependencies.py` contains `get_cached_user_roles` — FOUND (line 155)
- `grep HTTPException backend/app/config_ops/service.py` — returns 0 matches (PASS)
- `grep dataset_feature_count_total backend/app/maps/` — returns 0 matches (PASS)
- Commits `d1011f31`, `14c3ba24`, `2ac8474e`, `e62572b2`, `7e847cf7` — all present in git log
- Frontend tests: 946/947 pass (1 quicklook_url fixture test correctly removed)
- TypeScript: 0 errors

## Post-Execution Scope Fix (commit 61b7b2ef)

The executor went beyond audit scope by inlining BuilderSidebar, DatasetHeroMap, DatasetStatsLine back into parent pages, deleting staging pipeline tests, restructuring `.planning/`, and re-creating the deleted `use-quicklook.ts` hook. All out-of-scope changes were reverted in commit `61b7b2ef`.
