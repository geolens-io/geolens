---
phase: 237-search-service-decomposition
plan: 06
subsystem: backend
tags: [catalog, search, facade, architecture, regression-tests]
requires:
  - phase: 237-05
    provides: thin search facade and record conversion module
provides:
  - Search service facade regression coverage
  - Updated concrete User ORM import allowlist for decomposed search modules
  - Focused search/OGC/STAC/hybrid verification pass
affects: [search-service-decomposition, architecture-guards, catalog-search]
tech-stack:
  added: []
  patterns: [public-facade, architecture-allowlist-maintenance]
key-files:
  created: []
  modified:
    - backend/tests/test_search.py
    - backend/tests/test_layering.py
key-decisions:
  - "Validated the public facade with attribute and __all__ assertions rather than source-introspection checks."
  - "Moved the Phase 214 concrete User import allowlist from search/service.py to search/service_semantic.py."
patterns-established:
  - "Phase 238 remains responsible for private-module import and size-budget architecture guards."
requirements-completed: [SRCH-01, SRCH-02, SRCH-03, SRCH-04, SRCH-05, SRCH-06]
duration: 2 min
completed: 2026-05-03
---

# Phase 237 Plan 06: Facade Regression Verification Summary

**Search facade regression coverage and architecture allowlist maintenance now prove the decomposed service keeps its public import surface and existing behavior.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-03T23:35:25Z
- **Completed:** 2026-05-03T23:37:17Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Added `test_search_service_facade_exports_public_api` to assert the stable public search service API remains exposed from `service.py`.
- Updated `test_cross_domain_does_not_import_user_from_auth_models` to allow the legitimate `User` lookup in `service_semantic.py` and no longer allowlist the public facade.
- Ran the focused search, facets, cache, hybrid, OGC collection/queryables, OGC record, STAC record, modality asset, architecture, ruff, and format checks.

## Task Commits

1. **Add facade regression and maintain architecture allowlist** - `e29833e3` (`test`)

## Files Created/Modified

- `backend/tests/test_search.py` - public search facade export regression.
- `backend/tests/test_layering.py` - concrete User ORM import allowlist updated for decomposed search semantic module.

## Decisions Made

- Kept the facade test source-light and deferred private module boundary/size-budget enforcement to Phase 238.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `cd backend && uv run python - <<'PY' ... search facade export check ... PY` - passed.
- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_search.py::test_search_service_facade_exports_public_api tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models -q` - passed, 2 tests.
- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_search.py tests/test_search_facets.py tests/test_search_cache.py tests/test_hybrid_search.py tests/test_ogc_collection_metadata.py tests/test_ogc_queryables.py tests/test_ogc_record_properties.py tests/test_stac_record_output.py tests/test_modality_assets.py tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models -q` - passed, 100 tests.
- `cd backend && uv run ruff check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_facets.py app/modules/catalog/search/service_collections.py app/modules/catalog/search/service_semantic.py app/modules/catalog/search/service_datasets.py app/modules/catalog/search/service_records.py tests/test_search.py tests/test_layering.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_facets.py app/modules/catalog/search/service_collections.py app/modules/catalog/search/service_semantic.py app/modules/catalog/search/service_datasets.py app/modules/catalog/search/service_records.py tests/test_search.py tests/test_layering.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 237 is ready for final goal verification and roadmap completion. Phase 238 can add boundary guards and size-budget checks for the new private search modules.

---
*Phase: 237-search-service-decomposition*
*Completed: 2026-05-03*
