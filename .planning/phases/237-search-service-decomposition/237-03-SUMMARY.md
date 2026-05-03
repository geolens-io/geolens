---
phase: 237-search-service-decomposition
plan: 03
subsystem: backend
tags: [catalog, search, semantic-search, rrf, embeddings]
requires:
  - phase: 237-02
    provides: facet and collection helpers split out of service.py
provides:
  - Focused semantic search and RRF helper module
  - CatalogPort-based embedding test seam
affects: [search-service-decomposition, hybrid-search, ai-search]
tech-stack:
  added: []
  patterns: [catalog-port-dispatch, public-facade, focused-service-module]
key-files:
  created:
    - backend/app/modules/catalog/search/service_semantic.py
  modified:
    - backend/app/modules/catalog/search/service.py
    - backend/tests/test_hybrid_search.py
key-decisions:
  - "Semantic search continues to use CatalogPort provider dispatch; catalog search does not import processing embedding providers directly."
  - "Hybrid tests patch service_semantic.generate_embedding, the local wrapper around CatalogPort embedding dispatch."
patterns-established:
  - "Private semantic helpers own actor enrichment and RRF pagination; service.py only re-exports compatibility helpers."
requirements-completed: [SRCH-01, SRCH-02, SRCH-06]
duration: 4 min
completed: 2026-05-03
---

# Phase 237 Plan 03: Semantic RRF Module Summary

**Semantic vector rank lookup, RRF merge, and updated-actor enrichment now live in `service_semantic.py` with `_compute_rrf_scores` preserved on the public facade.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-03T23:23:55Z
- **Completed:** 2026-05-03T23:27:26Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Extracted `_attach_updated_actor_identities`, `_get_vector_ranks`, `_compute_rrf_scores`, and `_run_rrf_merge` into `backend/app/modules/catalog/search/service_semantic.py`.
- Preserved `_compute_rrf_scores` import compatibility from `app.modules.catalog.search.service`.
- Added a semantic-module `generate_embedding` wrapper around CatalogPort dispatch so hybrid tests can patch the correct seam without direct processing imports.

## Task Commits

1. **Extract semantic ranking helpers and preserve facade compatibility** - `d0a8808e` (`feat`)

## Files Created/Modified

- `backend/app/modules/catalog/search/service_semantic.py` - semantic vector lookup, RRF scoring/merge, actor enrichment, and embedding wrapper.
- `backend/app/modules/catalog/search/service.py` - facade import for semantic helpers.
- `backend/tests/test_hybrid_search.py` - patch target updated to the semantic helper module.

## Decisions Made

- Kept embedding generation behind `get_catalog_port().generate_embedding(...)`.
- Exposed `generate_embedding` only in `service_semantic.py` as a test seam for the CatalogPort dispatch path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated stale hybrid-search mock target**
- **Found during:** Task 2 (Preserve semantic facade compatibility)
- **Issue:** `test_hybrid_search.py` patched `app.modules.catalog.search.service.generate_embedding`, but the implementation already used CatalogPort dispatch and no facade-level `generate_embedding` attribute existed.
- **Fix:** Added `service_semantic.generate_embedding()` as a thin CatalogPort wrapper, used it inside `_get_vector_ranks`, and updated hybrid tests to patch that module-local seam.
- **Files modified:** `backend/app/modules/catalog/search/service_semantic.py`, `backend/tests/test_hybrid_search.py`
- **Verification:** Full `tests/test_hybrid_search.py` passed.
- **Committed in:** `d0a8808e`

---

**Total deviations:** 1 auto-fixed (Rule 3).
**Impact on plan:** The change preserved the intended CatalogPort dispatch contract and restored hybrid test coverage without adding product scope.

## Issues Encountered

None beyond the auto-fixed stale mock target.

## Verification

- `cd backend && env PYTHONPATH=. POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin uv run pytest tests/test_hybrid_search.py -q` - passed, 6 tests.
- `cd backend && uv run python - <<'PY' ... _compute_rrf_scores facade check ... PY` - passed.
- `cd backend && uv run ruff check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_semantic.py tests/test_hybrid_search.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/search/service.py app/modules/catalog/search/service_filters.py app/modules/catalog/search/service_semantic.py tests/test_hybrid_search.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 04 to move `search_datasets` and its ranking/sorting orchestration onto the filter and semantic helper modules.

---
*Phase: 237-search-service-decomposition*
*Completed: 2026-05-03*
