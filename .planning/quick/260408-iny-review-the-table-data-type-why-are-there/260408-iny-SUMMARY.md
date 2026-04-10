---
quick_task: 260408-iny
subsystem: ingest, services, search, frontend
tags: [table, arcgis, non-spatial, column-info, duplicate-detection, ogc, quality-score]
key-files:
  created:
    - .planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md
  modified:
    - backend/app/datasets/schemas.py
    - backend/app/ingest/metadata.py
    - backend/app/ingest/ogr.py
    - backend/app/ingest/tasks.py
    - backend/app/ogc/errors.py
    - backend/app/search/schemas.py
    - backend/app/search/service.py
    - backend/app/services/router.py
    - backend/tests/test_ingest.py
    - backend/tests/test_ogc_record_properties.py
    - backend/tests/test_quality_score.py
    - backend/tests/test_services_endpoints.py
    - frontend/src/api/client.ts
    - frontend/src/components/import/ServiceUrlForm.tsx
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/types/api.ts
decisions:
  - Non-spatial ArcGIS table layers require is_non_spatial flag to skip geometry ogr2ogr flags
  - Error handler now preserves dict detail as JSON object (not stringified) for 409 structured payloads
  - Quality score for table records uses 55-point normalization (metadata 30 + attribute 25, no geometry/crs)
  - Duplicate detection keyed on (source_url, source_format, created_by) — per-user, not global
metrics:
  duration: ~4 hours
  completed_date: "2026-04-08"
  tasks_completed: 6
  files_modified: 16
---

# Quick Task 260408-iny: Table Record Type — Full Enhancement Pass

**One-liner:** Fixed non-spatial ArcGIS table ingestion (column_info empty bug), re-normalized quality score, added OGC row/column_count fields, 409 duplicate detection with frontend toast, and Table2 orange thumbnail tile.

## Tasks Completed

| Task | Commit | Description |
|------|--------|-------------|
| T1 — Wave 0 diagnostics | `6bb1d7ea` | Documented 3 gates: column_info root cause (Case 2), 307 not reproducible, /collections/items works |
| T2 — Backend quick wins | `59da8678` | Schema doc, quality score re-normalization, OGC formats, row_count/column_count |
| T3 — Column info fix + ogr2ogr | `faf8c5b7` | is_non_spatial flag, ArcGIS fields fallback in _finalize_ingest |
| T4 — Table2 thumbnail tile | `5576955f` | Orange gradient tile with row/col count span in SearchResultCard |
| T5 — 409 duplicate detection | `7bc248b1` | Duplicate check in services/preview/, ApiError.body, ServiceUrlForm toast handler |
| T6 — CI ship gate (format) | `7ad5f7f4` | ruff format applied to 6 files; all lint/type/test checks passed |

## Root Cause (Wave 0 Gate A)

Non-spatial ArcGIS FeatureServer layers with `geometryType=None` were ingested with ogr2ogr geometry flags (`-nlt PROMOTE_TO_MULTI`, `-t_srs EPSG:4326`, `-lco GEOMETRY_NAME=geom`). For attribute-only tables, ogr2ogr silently drops all attribute columns when these flags are set, leaving `column_info = []`.

**Fix:** Added `is_non_spatial: bool = False` parameter to `run_ogr2ogr_service`. When `True`, all geometry-related flags are skipped. Detected from `user_metadata["geometry_type"]` being falsy in `ingest_service`. Fallback: if ogr2ogr still produces empty column_info, populate from `source_columns` stored in job user_metadata at preview time.

## Wave 0 Gate B

307 redirect on service URL could not be reproduced. All frontend API calls include trailing slashes matching backend route definitions. Skipped per plan instructions.

## Wave 0 Gate C

`/collections/items` returned a valid GeoJSON FeatureCollection for table records. No fix needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Error handler stringified dict detail in 409 response**
- **Found during:** Task 5 (test failure — `body["detail"]` was string, not dict)
- **Issue:** `ProblemDetail.detail: str` caused `_serialize_detail` to JSON-encode dict details, so the 409 body arrived as `{"detail": "{\"code\":\"duplicate_source\",...}"}` — a JSON string.
- **Fix:** Added `isinstance(exc.detail, (dict, list))` branch in `register_error_handlers` to return raw dict directly in JSON response. Plain strings still go through `ProblemDetail`.
- **Files modified:** `backend/app/ogc/errors.py`
- **Impact:** All structured dict/list HTTPException details now arrive as JSON objects, not strings. This is more correct behavior and affects any future structured error bodies.
- **Commit:** `7bc248b1`

## Known Stubs

None — all data paths are wired. The `row_count` and `column_count` fields in OGC Records are derived from live `feature_count` and `column_info` on `Dataset` rows. The thumbnail tile in `SearchResultCard` uses real `properties.feature_count` and `properties.column_count`.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: ssrf | `backend/app/services/router.py` | Duplicate check runs after SSRF validation — no new surface introduced |

## CI Gate Results

| Check | Result |
|-------|--------|
| `ruff check .` | PASSED — 0 errors |
| `ruff format --check .` | PASSED (after auto-format) |
| Backend pytest (targeted) | 77/77 passed (test_services_endpoints, test_quality_score, test_ogc_record_properties, test_ingest) |
| Backend pytest (full, excl. raster/stac) | 1769 passed, 5 deselected — clean (post-commit re-run; earlier 8 failures + 54 errors were transient from mid-session intermediate state before errors.py fix landed) |
| `npm run lint` | PASSED — 0 errors (1 pre-existing React Compiler warning) |
| `npm test` | 104 test files, 930 tests passed |

## Self-Check: PASSED

- DIAGNOSTICS.md exists at `.planning/quick/260408-iny-review-the-table-data-type-why-are-there/260408-iny-DIAGNOSTICS.md`
- All 6 commits exist in git log (verified above)
- Modified files verified present and syntactically valid (lint/type check passed)
