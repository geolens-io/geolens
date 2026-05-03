---
phase: 237-search-service-decomposition
plan: 01
subsystem: backend
tags: [catalog, search, filters, ogc, facade]
requires: []
provides:
  - Shared search filter module with SearchFilters and common query filters
  - Initial public search service facade exports
affects: [search-service-decomposition, catalog-search, ogc-records]
tech-stack:
  added: []
  patterns: [public-facade, focused-service-module]
key-files:
  created:
    - backend/app/modules/catalog/search/service_filters.py
  modified:
    - backend/app/modules/catalog/search/service.py
key-decisions:
  - "Kept SearchFilters and parse_ogc_datetime importable from app.modules.catalog.search.service while moving implementation into service_filters.py."
  - "Added explicit __all__ early so later split plans can preserve the stable facade surface."
patterns-established:
  - "Search private modules import shared helpers directly from service_filters.py; external callers keep using service.py."
requirements-completed: [SRCH-01, SRCH-02, SRCH-03, SRCH-04]
duration: 27 min
completed: 2026-05-03
---

# Phase 237 Plan 01: Shared Search Filter Foundation Summary

**SearchFilters, FacetCounts, text matching, OGC datetime parsing, and common SQL filters now live in `service_filters.py` behind the existing public service import path.**

## Performance

- **Duration:** 27 min
- **Started:** 2026-05-03T22:54:00Z
- **Completed:** 2026-05-03T23:21:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Extracted `SearchFilters`, `FacetCounts`, `_build_text_filter`, `parse_ogc_datetime`, and `_apply_common_filters` into `backend/app/modules/catalog/search/service_filters.py`.
- Rewired `backend/app/modules/catalog/search/service.py` to import the moved helpers and expose them via an explicit `__all__`.
- Preserved existing facade imports used by search cache, OGC/STAC code, and tests.

## Task Commits

1. **Extract common search filters and lock initial facade exports** - `b73cfdda` (`feat`)

## Files Created/Modified

- `backend/app/modules/catalog/search/service_filters.py` - shared search filter contracts and query helper stack.
- `backend/app/modules/catalog/search/service.py` - imports moved helpers and advertises the stable public facade.

## Decisions Made

- Kept external imports on `app.modules.catalog.search.service`; private modules will depend on `service_filters.py` directly.
- Added `__all__` before the final facade cleanup so every later plan has an explicit compatibility target.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The first targeted pytest run used the default local port and failed because `geolens_test` did not exist on `localhost:5432`. Rerunning with the documented Compose host env (`POSTGRES_PORT=5434`, primary `geolens` DB) let the test fixture recreate/migrate `geolens_test` and pass.

## Verification

- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_search_datetime.py tests/test_search_cache.py::test_is_anon_cacheable_distinguishes_authed_from_anon -q` - passed, 10 tests.
- `cd backend && uv run python - <<'PY' ... facade import check ... PY` - passed.
- `cd backend && uv run ruff check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 02 to move facet counting and collection search onto the shared filter module.

---
*Phase: 237-search-service-decomposition*
*Completed: 2026-05-03*
