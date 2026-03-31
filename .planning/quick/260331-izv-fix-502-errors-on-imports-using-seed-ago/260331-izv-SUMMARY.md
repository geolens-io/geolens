---
phase: 260331-izv
plan: 01
type: quick-fix
subsystem: backend/services
tags: [arcgis, preview, timeout, fix-502]
dependency_graph:
  requires: []
  provides: [FIX-502-PREVIEW]
  affects: [backend/app/services/preview.py, backend/app/services/router.py, backend/app/datasets/router_reupload.py]
tech_stack:
  added: []
  patterns: [result_limit optional param pattern for selective URL parameter injection]
key_files:
  created: []
  modified:
    - backend/app/services/preview.py
    - backend/app/services/router.py
    - backend/app/datasets/router_reupload.py
decisions:
  - result_limit defaults to None so existing ingestion callers are unaffected without code changes
  - resultRecordCount inserted before token in URL to match documented ArcGIS query param order
  - WFS branch deliberately untouched (resultRecordCount is ArcGIS-specific)
metrics:
  duration: 5min
  completed: 2026-03-31
  tasks_completed: 2
  files_modified: 3
---

# Phase 260331-izv Plan 01: Fix 502 Errors on ArcGIS Service Imports Summary

ArcGIS preview queries now cap fetched features to 5 via `resultRecordCount=5` and ogrinfo subprocess timeout doubled to 120s, eliminating 502 errors caused by slow/complex ArcGIS services during preview.

## Objective

ArcGIS preview requests were fetching up to maxRecordCount features (1000-2000) with no limit, causing ogrinfo to exceed the 60s subprocess timeout on complex geometries or slow services. This produced 502 errors visible when running seed-ago-data.py imports.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add result_limit to build_gdal_source, increase timeout to 120s | 9b0a2635 | backend/app/services/preview.py |
| 2 | Pass result_limit=5 from all preview callers | c8918d30 | backend/app/services/router.py, backend/app/datasets/router_reupload.py |

## Changes Made

### Task 1 — backend/app/services/preview.py

- Added `result_limit: int | None = None` parameter to `build_gdal_source()` after `order_field`
- In the ArcGIS branch: appends `&resultRecordCount={result_limit}` to the query URL when `result_limit is not None`, placed before the `&token=` append
- Changed `run_service_preview()` default `timeout` from `60.0` to `120.0`
- WFS branch untouched; `resultRecordCount` is ArcGIS-specific

### Task 2 — backend/app/services/router.py

- `preview_service_layer()` primary `build_gdal_source()` call: added `result_limit=5`
- `preview_service_layer()` WFS namespace-retry `build_gdal_source()` call: added `result_limit=5`

### Task 2 — backend/app/datasets/router_reupload.py

- `reupload_service_preview()` `build_gdal_source()` call: added `result_limit=5`

### Unchanged

- `backend/app/ingest/tasks.py` — full ingestion paths fetch all features; no `result_limit` added

## Verification

```
grep -n "resultRecordCount" backend/app/services/preview.py
# -> 36: query_url += f"&resultRecordCount={result_limit}"

grep -n "result_limit=5" backend/app/services/router.py backend/app/datasets/router_reupload.py
# -> services/router.py:235, services/router.py:281, datasets/router_reupload.py:147

grep -n "result_limit" backend/app/ingest/tasks.py
# -> (no output — correct)

grep -n "timeout.*120" backend/app/services/preview.py
# -> 48: timeout: float = 120.0,
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- backend/app/services/preview.py — modified, exists
- backend/app/services/router.py — modified, exists
- backend/app/datasets/router_reupload.py — modified, exists
- Commit 9b0a2635 — exists
- Commit c8918d30 — exists
