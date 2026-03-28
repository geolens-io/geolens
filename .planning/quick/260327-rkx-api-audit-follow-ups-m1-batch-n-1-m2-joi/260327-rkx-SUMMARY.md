---
quick_task: 260327-rkx
title: "API Audit Follow-ups: L4 service URL wrapper, L5 datasets/router.py split into sub-routers"
completed_date: "2026-03-28"
duration_minutes: 25
tasks_completed: 1
tasks_total: 1
files_created: 6
files_modified: 8
commits:
  - hash: d5f1d932
    message: "refactor(260327-rkx-01): replace _public_base_url with get_dataset_service_url and split datasets/router.py into sub-routers"
key_decisions:
  - "Re-exported ALLOWED_TRANSITIONS from router.py for backward compatibility with test_publication_lifecycle.py"
  - "Updated test mock patch paths to reference new module locations (router_reupload, router_vrt, helpers)"
  - "Fixed pre-existing test mock in test_vrt_catalog_175.py: was patching check_dataset_access but quicklook uses check_dataset_access_or_anonymous"
---

# Task 2: Replace _public_base_url with get_dataset_service_url (L4) and split datasets/router.py (L5)

DB-backed URL resolution for dataset tile connect URLs, plus decomposition of 2231-line router into 6 focused files.

## What Was Done

### L4: get_dataset_service_url wrapper

1. Added `get_dataset_service_url()` thin wrapper in `backend/app/public_urls.py` that delegates to `get_public_app_url`
2. Replaced all 4 `_public_base_url(request)` call sites with `await get_dataset_service_url(db, request=request)`:
   - `list_all_datasets` (list base URL for raster connect)
   - `create_empty_dataset_endpoint` (new dataset response)
   - `get_single_dataset` (detail view response)
   - `update_dataset_metadata` (post-update response)
3. Deleted the `_public_base_url` function entirely

### L5: Router split by operation type

Created 6 new files from the original 2231-line router.py:

| File | Lines | Endpoints | Purpose |
|------|-------|-----------|---------|
| `helpers.py` | 188 | -- | Shared: _load_actor_identities, _build_raster_metadata, _dataset_to_response |
| `router_reupload.py` | 537 | 6 | Reupload + presigned reupload |
| `router_vrt.py` | 350 | 4 | VRT sources, status, generations, regenerate |
| `router_metadata.py` | 397 | 8+4 | Attributes, column stats, versions, relationships |
| `router_export.py` | 192 | 3 | DCAT catalog/record + COG download |
| `router_data.py` | 219 | 5 | Rows, validate, related, maps, publication status |
| `router.py` (core) | 482 | 7 | List, create, get, update, delete, quicklook, history |

All sub-routers registered in `main.py` with export BEFORE core to prevent /dcat/ path conflict.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Test mock paths updated for new module locations**
- **Found during:** Test verification
- **Issue:** Tests in test_reupload.py, test_reupload_service.py, test_vrt_catalog_175.py, test_vrt_lifecycle_188.py, test_vrt_source_management_174.py patched functions at `app.datasets.router` that moved to sub-modules
- **Fix:** Updated patch paths to match new locations (e.g., `app.datasets.router_reupload`, `app.datasets.router_vrt`, `app.datasets.helpers`)
- **Files modified:** 5 test files
- **Commit:** d5f1d932

**2. [Rule 3 - Blocking] Re-exported ALLOWED_TRANSITIONS for backward compatibility**
- **Found during:** Test verification
- **Issue:** test_publication_lifecycle.py imports `ALLOWED_TRANSITIONS` from `app.datasets.router` but the constant moved to `router_data.py`
- **Fix:** Added re-export: `from app.datasets.router_data import ALLOWED_TRANSITIONS  # noqa: F401`
- **Files modified:** backend/app/datasets/router.py
- **Commit:** d5f1d932

**3. [Rule 1 - Bug] Fixed stale mock in test_vrt_catalog_175.py quicklook test**
- **Found during:** Test verification
- **Issue:** test_quicklook_rejects_table_dataset patched `check_dataset_access` but the quicklook endpoint uses `check_dataset_access_or_anonymous`. Previously passed coincidentally.
- **Fix:** Changed patch target to `check_dataset_access_or_anonymous`
- **Files modified:** backend/tests/test_vrt_catalog_175.py
- **Commit:** d5f1d932

## Pre-existing Failures (Out of Scope)

- `test_tile_signing.py::TestTileAccessLogging::test_tile_access_logged` -- tile access log format mismatch, unrelated
- `test_vrt_lifecycle_188.py::TestVrtGenerationModel::test_model_schema` -- `__table_args__` is a tuple not dict, unrelated

## Verification

All 1521 tests pass (2 deselected pre-existing failures, 5 deselected unrelated):
```
1521 passed, 7 deselected, 10 warnings in 264.36s
```

Dataset-specific test suites: 157 passed in 17.93s.

## Known Stubs

None.

## Self-Check: PASSED
