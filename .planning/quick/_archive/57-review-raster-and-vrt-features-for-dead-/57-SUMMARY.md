---
phase: quick-57
plan: 01
subsystem: raster
tags: [refactor, cleanup, DRY]
dependency_graph:
  requires: []
  provides: [_is_float_dtype-helper, build_vrt-dispatch]
  affects: [backend/app/raster/cog.py, backend/app/raster/vrt.py, backend/app/ingest/tasks.py]
tech_stack:
  added: []
  patterns: [helper-extraction, dispatch-function, backward-compatible-wrappers]
key_files:
  created: []
  modified:
    - backend/app/raster/cog.py
    - backend/app/raster/vrt.py
    - backend/app/ingest/tasks.py
    - backend/tests/test_vrt_source_management_174.py
decisions:
  - Kept build_spatial_mosaic_vrt and build_band_stack_vrt as thin wrappers for backward compatibility with existing tests
  - Added check_and_prepare_cog to module-level imports in tasks.py to support removing local import in ingest_raster
metrics:
  duration: 4min
  completed: "2026-03-15T16:31:41Z"
---

# Quick Task 57: Review Raster and VRT Features for Dead Code Summary

DRY cleanup of cog.py float dtype checks, VRT build function unification, and redundant import removal across raster modules.

## Completed Tasks

| # | Task | Commit | Key Changes |
|---|------|--------|-------------|
| 1 | DRY up cog.py -- float dtype helper, dead variable, collapsed branches | 602fe1a1 | Extract _FLOAT_DTYPES + _is_float_dtype(); remove unused res variable; collapse identical elif/else branches |
| 2 | DRY up vrt.py -- unified build function, clean up tasks.py imports | 49b13b3f | Create _build_vrt() + build_vrt() dispatch; remove redundant env kwarg; remove duplicate imports in ingest_vrt and ingest_raster |

## Changes Made

### cog.py (Task 1)
- Extracted `_FLOAT_DTYPES` constant and `_is_float_dtype()` helper at module level
- Replaced duplicate float dtype set definitions in `prepare_with_overviews` and `_predictor_for_dtype`
- Removed unused `res = src.res` variable in `extract_raster_metadata`
- Collapsed identical `elif crs:` and `else:` branches into single `else:` for bounds_wgs84

### vrt.py (Task 2)
- Created `_build_vrt()` core function with `separate` flag parameter
- Added `build_vrt()` dispatch function that routes by vrt_type string
- Converted `build_spatial_mosaic_vrt` and `build_band_stack_vrt` to thin backward-compatible wrappers
- Removed redundant `env={**os.environ}` from subprocess.run (default env=None inherits parent)
- Removed unused `os` import

### tasks.py (Task 2)
- Replaced VRT-type if/else dispatch blocks in both `ingest_vrt` and `regenerate_vrt` with single `build_vrt()` call
- Removed 4 redundant local imports in `ingest_vrt` that shadowed module-level imports
- Removed 2 redundant local imports in `ingest_raster` (advisory item: sha256_file, extract_raster_metadata, check_and_prepare_cog, generate_quicklook)
- Added `build_vrt` and `check_and_prepare_cog` to module-level imports

### test_vrt_source_management_174.py (Task 2)
- Updated test patches from `build_spatial_mosaic_vrt`/`build_band_stack_vrt` to `build_vrt` to match refactored task code

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated test patches for build_vrt**
- **Found during:** Task 2
- **Issue:** Tests in test_vrt_source_management_174.py patched `build_spatial_mosaic_vrt` and `build_band_stack_vrt` on `app.ingest.tasks`, but regenerate_vrt now calls `build_vrt` instead
- **Fix:** Updated 4 patch targets to `app.ingest.tasks.build_vrt`
- **Files modified:** backend/tests/test_vrt_source_management_174.py
- **Commit:** 49b13b3f

**2. [Rule 2 - Advisory] Cleaned up ingest_raster redundant imports**
- **Found during:** Task 2 (plan checker advisory)
- **Issue:** `ingest_raster` had duplicate local imports for `check_and_prepare_cog`, `extract_raster_metadata`, `sha256_file`, and `generate_quicklook` that shadowed module-level imports
- **Fix:** Added `check_and_prepare_cog` to module-level import; removed both local import blocks
- **Files modified:** backend/app/ingest/tasks.py
- **Commit:** 49b13b3f

## Verification

- All raster and VRT tests pass (76 passed, 4 pre-existing failures unrelated to changes)
- New exports `_FLOAT_DTYPES`, `_is_float_dtype`, `build_vrt` all importable
- Zero behavioral changes -- refactor only

## Pre-existing Test Failures (out of scope)

- `TestRasterDeleteCascadeRemovesStorage::test_raster_delete_cascade_removes_storage` -- recursion error
- `TestRasterDeleteCascadeRemovesStorage::test_raster_delete_storage_failure_rolls_back` -- recursion error
- `TestStatusField::test_build_raster_metadata_includes_status` -- ValidationError
- `TestStatusField::test_build_raster_metadata_status_regenerating` -- ValidationError

## Self-Check: PASSED

- [x] backend/app/raster/cog.py exists and contains _FLOAT_DTYPES, _is_float_dtype
- [x] backend/app/raster/vrt.py exists and contains build_vrt, _build_vrt
- [x] backend/app/ingest/tasks.py modified with clean imports
- [x] Commit 602fe1a1 verified
- [x] Commit 49b13b3f verified
