---
phase: 237-search-service-decomposition
plan: 05
subsystem: backend
tags: [catalog, search, ogc-records, stac, assets]
requires:
  - phase: 237-04
    provides: dataset search split and public facade re-export
provides:
  - Focused OGC/STAC record conversion module
  - Thin public search service facade
affects: [search-service-decomposition, ogc-records, stac, modality-assets]
tech-stack:
  added: []
  patterns: [public-facade, focused-service-module]
key-files:
  created:
    - backend/app/modules/catalog/search/service_records.py
  modified:
    - backend/app/modules/catalog/search/service.py
key-decisions:
  - "Kept _build_stac_assets re-exported from service.py because existing tests import that helper from the public search service path."
  - "Moved all media-type constants and OGC/STAC conversion helpers together to avoid cross-module serialization coupling."
patterns-established:
  - "service.py now has only facade imports and __all__; implementation lives in focused sibling modules."
requirements-completed: [SRCH-01, SRCH-02, SRCH-05]
duration: 3 min
completed: 2026-05-03
---

# Phase 237 Plan 05: OGC Record Assets Module Summary

**OGC/STAC asset building and record conversion now live in `service_records.py`, leaving `service.py` as a stable public facade.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-03T23:32:25Z
- **Completed:** 2026-05-03T23:35:19Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Extracted media-type constants, `build_assets`, `_build_stac_assets`, `_build_themes`, `_build_time`, and `dataset_to_ogc_record` into `backend/app/modules/catalog/search/service_records.py`.
- Replaced `service.py` with a thin facade that re-exports the public search API and existing test-facing compatibility helpers.
- Preserved STAC router and modality asset imports from `app.modules.catalog.search.service`.

## Task Commits

1. **Extract assets and record conversion and preserve OGC/STAC callers** - `819b4359` (`feat`)

## Files Created/Modified

- `backend/app/modules/catalog/search/service_records.py` - modality assets, STAC asset rows, OGC themes/time, and OGC Record conversion.
- `backend/app/modules/catalog/search/service.py` - thin public facade with explicit `__all__`.

## Decisions Made

- Kept `_build_stac_assets`, `_build_themes`, and `_build_time` available from the facade for compatibility, even though only `_build_stac_assets` is currently imported by tests.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The initially planned pytest node IDs for `test_stac_record_output.py` used the wrong class name. Reran with the actual class names (`TestBuildStacAssets` and `TestStacDatetime`); tests passed.

## Verification

- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_modality_assets.py tests/test_stac_record_output.py::TestBuildStacAssets::test_build_stac_assets_full tests/test_stac_record_output.py::TestStacDatetime::test_datetime_range_with_start_and_end -q` - passed, 10 tests.
- `cd backend && uv run python - <<'PY' ... build_assets/dataset_to_ogc_record facade check ... PY` - passed.
- `cd backend && uv run ruff check app/modules/catalog/search/service.py app/modules/catalog/search/service_records.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/search/service.py app/modules/catalog/search/service_records.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 06 to add facade regression coverage, update architecture allowlists, and run focused close verification.

---
*Phase: 237-search-service-decomposition*
*Completed: 2026-05-03*
