---
phase: 237-search-service-decomposition
plan: 02
subsystem: backend
tags: [catalog, search, facets, collections, facade]
requires:
  - phase: 237-01
    provides: service_filters.py shared filter contracts
provides:
  - Focused facet count module
  - Focused collection search module
affects: [search-service-decomposition, search-facets, ogc-collections]
tech-stack:
  added: []
  patterns: [public-facade, focused-service-module]
key-files:
  created:
    - backend/app/modules/catalog/search/service_facets.py
    - backend/app/modules/catalog/search/service_collections.py
  modified:
    - backend/app/modules/catalog/search/service.py
key-decisions:
  - "Facet counting imports shared filters from service_filters.py and remains re-exported through service.py."
  - "Collection search owns visible member counts in service_collections.py without changing router imports."
patterns-established:
  - "Move service concerns into sibling modules while keeping router/cache callers on app.modules.catalog.search.service."
requirements-completed: [SRCH-01, SRCH-02, SRCH-04]
duration: 2 min
completed: 2026-05-03
---

# Phase 237 Plan 02: Facets and Collections Module Summary

**Facet counting and collection search now live in focused sibling modules while `get_facet_counts` and `search_collections` stay available from the public search service facade.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-03T23:21:40Z
- **Completed:** 2026-05-03T23:23:49Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Extracted `get_facet_counts` into `backend/app/modules/catalog/search/service_facets.py`.
- Extracted `search_collections` into `backend/app/modules/catalog/search/service_collections.py`.
- Trimmed `service.py` imports and re-exported the moved helpers from the stable facade.

## Task Commits

1. **Extract facet count service and collection search service** - `913ef6aa` (`feat`)

## Files Created/Modified

- `backend/app/modules/catalog/search/service_facets.py` - filtered CTE facet counts and collection facet group logic.
- `backend/app/modules/catalog/search/service_collections.py` - text collection search with visible member counts.
- `backend/app/modules/catalog/search/service.py` - facade imports for moved facet/collection helpers.

## Decisions Made

- Kept collection metadata, queryables, sortables, schema, and endpoint cache behavior in router/OGC modules for this phase; only the service-layer helpers moved.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_search_facets.py::test_facets_returns_all_types tests/test_search_facets.py::test_facets_with_text_filter tests/test_search_facets.py::test_facets_includes_collection_count -q` - passed, 3 tests.
- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_search.py::test_ogc_collections_list tests/test_search.py::test_ogc_collection_detail tests/test_search.py::test_ogc_items_search -q` - passed, 3 tests.
- `cd backend && uv run ruff check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_facets.py app/modules/catalog/search/service_collections.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_facets.py app/modules/catalog/search/service_collections.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 03 to extract semantic search, RRF merge, and actor enrichment helpers.

---
*Phase: 237-search-service-decomposition*
*Completed: 2026-05-03*
