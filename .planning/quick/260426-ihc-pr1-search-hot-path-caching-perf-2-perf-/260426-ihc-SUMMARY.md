---
quick_id: 260426-ihc
subsystem: api
tags: [caching, search, performance, fastapi, redis, in-memory-cache]

requires:
  - phase: pre-existing infra
    provides: app/platform/cache (get_cache, InMemoryCacheProvider, RedisCacheProvider, invalidate_catalog_cache)
provides:
  - "30s passive anonymous response cache for /search/datasets/ (PERF-2)"
  - "30s passive anonymous response cache for /search/facets/ (PERF-7)"
  - "Reusable search-cache helper module (cache key builder + anon gate + thin get/set wrappers)"
affects: [search hot path, future search caching work, future PR2 (KISS-1/KISS-2 search decomposition)]

tech-stack:
  added: []
  patterns:
    - "Anon-only response cache, gate is `user is None` (NOT empty role set)"
    - "SHA-1 over canonical JSON of (filters, endpoint, roles, public_api_url, semantic_enabled) for cache keys"
    - "model_dump(mode='json') round-trip for Pydantic responses through the cache (Redis JSON-safe)"
    - "Cache flush via shared `catalog:*` prefix (existing invalidate_catalog_cache covers VRT mutations)"

key-files:
  created:
    - backend/app/modules/catalog/search/cache.py
    - backend/tests/test_search_cache.py
  modified:
    - backend/app/modules/catalog/search/router.py

key-decisions:
  - "Anon-only caching gate is `user is None` to avoid leaking through API-key-authed-but-no-roles users"
  - "30s passive TTL, no new active invalidation hooks — existing catalog:* prefix flush covers VRT mutations"
  - "Search cache keys include public_api_url + semantic_enabled (URL change or flag flip rotates keys)"
  - "Facets cache keys use public_api_url=None and semantic_enabled=None (facets carry no URLs and don't run semantic ranking)"
  - "Cache the full OGCFeatureCollectionResponse via model_dump(mode='json') ↔ OGCFeatureCollectionResponse(**cached) round-trip; cache the FacetCounts TypedDict directly (already JSON-friendly)"

patterns-established:
  - "Module-level cache helper colocated with the routes it serves (mirrors app/platform/cache/tiles.py pattern)"
  - "Tests with autouse cache-flush fixture depending on `client` to ensure init_cache() runs first"

requirements-completed: []

duration: ~12min
completed: 2026-04-26
---

# Quick Task 260426-ihc: PR1 Search Hot-Path Caching Summary

**Anonymous-only 30s response cache on /search/datasets and /search/facets, hashing full filter+config inputs and reusing the existing catalog:* invalidation prefix.**

## Performance

- **Duration:** ~12 min (from plan dispatch at 13:32 EDT to second code commit at 13:44 EDT)
- **Started:** 2026-04-26T17:32:28Z
- **Completed:** 2026-04-26T17:44:26Z
- **Tasks:** 2
- **Files created:** 2 (cache.py, test_search_cache.py)
- **Files modified:** 1 (router.py)

## Accomplishments

- Cache helper module (`cache.py`) with `is_anon_cacheable`, `build_cache_key`, `get_cached`, `set_cached`, and `SEARCH_CACHE_TTL=30` — single source of truth for the anon gate.
- `_handle_search` (PERF-2) reads from cache after `user_roles` resolution and before `search_datasets()`; writes through immediately before returning the assembled `OGCFeatureCollectionResponse`. Authed callers bypass.
- `search_facets_endpoint` (PERF-7) reads from cache after building `facet_filters` and before `get_facet_counts()`; writes through immediately before `return result`. Authed callers bypass.
- 4 new tests in `tests/test_search_cache.py`, all passing:
  - `test_anon_search_caches_response` — proves hit by mutating DB between two anon calls.
  - `test_authed_search_bypasses_cache` — proves bypass by mutating DB between two authed calls.
  - `test_anon_facets_caches_response` — same hit pattern for facets.
  - `test_authed_facets_bypasses_cache` — same bypass pattern for facets.
- Full backend suite: **1966 passed / 1969 collected**, 17 skipped, 5 deselected. The 3 failures are the pre-existing audit/* WIP tests (out of scope per constraints). Baseline floor (1962/1965) exceeded by exactly the 4 new tests.
- `uv run ruff check app/`: 0 errors.

## Task Commits

1. **Task 1: cache helper + PERF-2 wiring + 2 datasets tests** — `217eafcf` (perf)
2. **Task 2: PERF-7 wiring + 2 facets tests** — `7ed5ca15` (perf)
3. **Review-loop fixes (WR-01..WR-06, IN-02, IN-05)** — `7aebc4d8` (perf)

## Files Created/Modified

- `backend/app/modules/catalog/search/cache.py` — anonymous response cache helper (key builder, gate, thin get/set wrappers).
- `backend/app/modules/catalog/search/router.py` — wired both `_handle_search` and `search_facets_endpoint` with cache lookup/write-through; imported `SEMANTIC_SEARCH_ENABLED` and the new `cache` module.
- `backend/tests/test_search_cache.py` — 4 integration tests with autouse cache-flush fixture; reuses `_create_search_dataset` pattern from `test_search.py`.

## Decisions Made

- **Anon gate is `user is None`** (not `user_roles == set()`). RESEARCH.md flagged that an API-key-authed user with empty role assignments would be `user is not None` AND `user_roles == set()`; keying on the empty role set would put them on the anon cache path. We use `user is None` only.
- **`semantic_enabled` is read in `_handle_search` for the cache key** (so it gates the hash) **and again inside `search_datasets`**. Per RESEARCH.md pre-flight Q1, this is fine: `persistent_config` is process-cached, so the second read is essentially free.
- **Facets cache key uses `public_api_url=None` and `semantic_enabled=None`** to maximize hit rate — facet responses carry no URLs and `get_facet_counts` does not run semantic ranking.
- **Full-response caching, not per-sub-query.** Mirrors the existing `datasets/api/router.py` admin cache pattern. Sub-query caching would be more invasive and not needed for this fidelity.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Autouse `_reset_search_cache` fixture needed `client` dependency**

- **Found during:** Task 1 (running the new tests for the first time).
- **Issue:** The autouse fixture as specified in the plan called `await get_cache().delete_pattern(...)` directly, but session-scoped `init_cache()` runs inside the `client` fixture (`tests/conftest.py:174`). Without depending on `client`, the autouse fixture ran first and raised `RuntimeError: Cache not initialized. Call init_cache() first.`
- **Fix:** Added `client: AsyncClient` parameter to `_reset_search_cache(...)` so pytest resolves the session-scoped client first, ensuring `init_cache()` is called before any cache flush attempt. Functionality is identical; only the dependency order changed.
- **Files modified:** `backend/tests/test_search_cache.py`.
- **Verification:** `uv run pytest tests/test_search_cache.py -x -v` — all 4 tests pass.
- **Committed in:** `217eafcf` (part of Task 1 commit — caught and fixed before commit).

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking — fixture dependency ordering).
**Impact on plan:** Trivial; the plan's fixture body was correct, only its parameter list needed `client` to satisfy pytest's fixture resolution order. No scope creep.

## Issues Encountered

- **Pre-existing audit/* WIP visible in `git status`.** The worktree was NOT clean of `backend/app/modules/audit/router.py` and `service.py` modifications despite the constraints note. Handled by staging only this task's files explicitly (no `git add -A`). Audit files left untouched and unstaged at completion. Audit/* failures (3) match the documented expected baseline.

## Verification

- `uv run pytest tests/test_search_cache.py -x -v` → 5 passed (4 integration + 1 unit pinning `is_anon_cacheable` contract).
- `uv run pytest tests/test_search.py tests/test_search_facets.py tests/test_hybrid_search.py -q` → 39 passed.
- `uv run pytest -q --tb=line` (post-review-fix) → **1967 passed**, 3 failed (pre-existing audit/* WIP — out of scope), 17 skipped, 5 deselected, ~379s total.
- `uv run ruff check app/ tests/test_search_cache.py` → All checks passed.

## Review Loop

`gsd-code-reviewer` returned 6 warnings + 5 info findings on the initial implementation (no blockers, no security issues). Fixes applied in commit `7aebc4d8`:

- **WR-01:** hoisted `SEMANTIC_SEARCH_ENABLED.get(db)` inside the anon gate so authed callers no longer pay an unnecessary read on every request.
- **WR-02:** anon search/facets tests now positively assert at least one `catalog:search:<endpoint>:*` entry was written (rules out false-positive coincidence).
- **WR-03:** corrected misleading "session-scoped singleton" docstring on the autouse fixture.
- **WR-04:** added direct unit test pinning the `is_anon_cacheable(None) is True` / `is_anon_cacheable(User(...)) is False` contract.
- **WR-05:** anon tests assert full-body equality (modulo `timeStamp`) so reconstruction-breaking regressions in `model_dump(mode="json")` round-trip fail loudly.
- **WR-06:** broadened the test cache-flush pattern from `catalog:search:*` to `catalog:*` so future helper-prefix renames cannot silently no-op the flush.
- **IN-02:** `semantic_enabled` now omitted from the cache-key payload when `None`, eliminating the tri-state collapse.
- **IN-05:** documented keywords-order convention and SearchFilters JSON-native maintenance contract directly in `build_cache_key`.

Remaining info items (IN-01, IN-03, IN-04) are forward-looking notes, not actionable today.
- `grep -n "is_anon_cacheable\|build_cache_key\|search_cache\." backend/app/modules/catalog/search/router.py` → 6 wiring sites, 4 in `_handle_search` (lines 334, 335, 342, 547) and 4 in `search_facets_endpoint` (lines 609, 610, 611, 618, 629, 630).

## Self-Check

- [x] `backend/app/modules/catalog/search/cache.py` exists.
- [x] `backend/tests/test_search_cache.py` exists.
- [x] `backend/app/modules/catalog/search/router.py` modified (cache wiring at expected lines).
- [x] Commit `217eafcf` exists in `git log`.
- [x] Commit `7ed5ca15` exists in `git log`.
- [x] No deletions in either commit (`git diff --diff-filter=D --name-only HEAD~2 HEAD` empty).

**## Self-Check: PASSED**

## Next Steps Readiness

- PR1 ready for review.
- PR2 (KISS-1 + KISS-2 search decomposition) is unblocked by this work — they share the same module but no overlapping line ranges.
- The 3 audit/* failures remain pre-existing red and are tracked outside this task.

---
*Quick task: 260426-ihc*
*Completed: 2026-04-26*
