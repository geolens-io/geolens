---
phase: 237-search-service-decomposition
plan: 04
subsystem: backend
tags: [catalog, search, datasets, ranking, cql2, rbac]
requires:
  - phase: 237-03
    provides: semantic/RRF helper module
provides:
  - Focused dataset search orchestration module
  - Facade re-export for search_datasets
affects: [search-service-decomposition, catalog-search, ogc-cql2, hybrid-search]
tech-stack:
  added: []
  patterns: [public-facade, focused-service-module]
key-files:
  created:
    - backend/app/modules/catalog/search/service_datasets.py
  modified:
    - backend/app/modules/catalog/search/service.py
key-decisions:
  - "Dataset search owns FTS ranking, search-only filters, sort resolution, count query, semantic merge call, and pagination in service_datasets.py."
  - "External callers continue importing search_datasets from app.modules.catalog.search.service."
patterns-established:
  - "Search modules depend on service_filters.py and service_semantic.py directly, not through the public facade."
requirements-completed: [SRCH-01, SRCH-02, SRCH-03, SRCH-06]
duration: 5 min
completed: 2026-05-03
---

# Phase 237 Plan 04: Dataset Search Module Summary

**Dataset search query orchestration now lives in `service_datasets.py`, preserving FTS ranking, filters, CQL2, sorting, pagination, RBAC, and semantic/RRF fallback behavior through the public facade.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-03T23:27:30Z
- **Completed:** 2026-05-03T23:32:21Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Extracted `_build_fts_rank_col`, `_apply_search_only_filters`, `_resolve_sort_order`, and `search_datasets` into `backend/app/modules/catalog/search/service_datasets.py`.
- Rewired dataset search to import shared filters from `service_filters.py` and RRF/actor enrichment from `service_semantic.py`.
- Reduced `service.py` to facade imports plus OGC/STAC record conversion code for the remaining plan.

## Task Commits

1. **Extract dataset search implementation and preserve callers** - `360c6714` (`feat`)

## Files Created/Modified

- `backend/app/modules/catalog/search/service_datasets.py` - dataset search query construction, count query, sort handling, semantic merge call, pagination, and actor enrichment.
- `backend/app/modules/catalog/search/service.py` - facade import for `search_datasets`.

## Decisions Made

- Kept CQL2 application inside the dataset search module as a search-only filter, preserving the existing lazy import of `app.standards.ogc.filtering.apply_cql2_filter`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_search.py::test_search_text_match tests/test_search.py::test_search_bbox_intersects tests/test_search.py::test_search_filter_by_keywords tests/test_search.py::test_search_sort_by_name tests/test_search.py::test_search_pagination tests/test_search.py::test_search_rbac_private_hidden tests/test_ogc_cql2_filtering.py -q` - passed, 17 tests.
- `cd backend && uv run python - <<'PY' ... SearchFilters/search_datasets facade check ... PY` - passed.
- `cd backend && uv run ruff check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_semantic.py app/modules/catalog/search/service_datasets.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_semantic.py app/modules/catalog/search/service_datasets.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 05 to move OGC/STAC asset and record conversion out of the service facade.

---
*Phase: 237-search-service-decomposition*
*Completed: 2026-05-03*
