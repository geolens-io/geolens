---
quick_id: 260426-ihc
plan_id: 260426-ihc-PLAN
mode: quick-full
status: ready
must_haves:
  truths:
    - "Anonymous GET /search/datasets/ returns the cached payload on the second request within 30s — proven by mutating the DB between calls and asserting the second response equals the first (stale)."
    - "Authenticated GET /search/datasets/ (admin_auth_header) bypasses the cache — proven by mutating the DB and asserting the second response reflects the mutation."
    - "Anonymous GET /search/facets/ returns the cached FacetCountResponse on the second request within 30s — proven the same way as above."
    - "Authenticated GET /search/facets/ bypasses the cache — proven by mutation visibility."
    - "Cache writes are JSON-serializable: PERF-2 stores `model_dump(mode='json')` and PERF-7 stores the FacetCounts TypedDict directly, so RedisCacheProvider's `json.dumps(value, default=str)` (backend/app/platform/cache/redis.py:86) accepts them without TypeError."
    - "Existing `invalidate_catalog_cache()` (backend/app/platform/cache/tiles.py:8) flushes the new keys because they share the `catalog:` prefix — `fnmatch('catalog:search:foo', 'catalog:*')` is True (memory.py:32) and Redis `SCAN match=catalog:*` matches across `:` (redis.py:110)."
    - "Anon cacheability gate is exactly `user is None` (NOT `user_roles == set()`) — keeps API-key-authed-but-no-roles users off the anon cache path."
    - "Cache key for /search/datasets includes `public_api_url` and `semantic_enabled` per RESEARCH.md §4 so that a deployment URL change or SEMANTIC_SEARCH_ENABLED flip rotates keys naturally."
    - "Test suite baseline is preserved at 1962 of 1965 (the 3 pre-existing red audit/* tests are NOT touched and NOT in scope per CONTEXT.md canonical_refs lines 122-124)."
  artifacts:
    - backend/app/modules/catalog/search/cache.py
    - backend/app/modules/catalog/search/router.py
    - backend/app/modules/catalog/search/service.py
    - backend/tests/test_search_cache.py
  key_links:
    - "backend/app/modules/catalog/search/router.py:313-328 — `_handle_search` entry point: cache lookup placed AFTER `params.to_filters()` and AFTER the `user_roles` resolution block (lines 322-327), BEFORE the `search_datasets` call at line 330."
    - "backend/app/modules/catalog/search/router.py:519-528 — `_handle_search` return point: cache write placed immediately before `return` after the `OGCFeatureCollectionResponse` is assembled, calling `model_dump(mode='json')` per RESEARCH.md §2."
    - "backend/app/modules/catalog/search/router.py:564-595 — `search_facets_endpoint`: cache lookup placed AFTER `_parse_spatial_params` and the user_roles block (lines 570-573), BEFORE `get_facet_counts` at line 589; cache write placed immediately before `return result`."
    - "backend/app/modules/catalog/search/service.py:90-118 — `SearchFilters` is a `@dataclass(frozen=True, slots=True)` so the helper uses `dataclasses.asdict(filters)` (NOT `.model_dump()`)."
    - "backend/app/modules/catalog/search/service.py:715 — `SEMANTIC_SEARCH_ENABLED.get(session)` is read inside `search_datasets`; the cache helper reads it again in `_handle_search` for the key (per RESEARCH.md pre-flight Q1 — read twice, persistent_config is process-cached)."
    - "backend/app/platform/cache/provider.py:51-55 — `get_cache()` is the only entry point; helper imports from `app.platform.cache`."
    - "backend/app/modules/catalog/datasets/api/router.py:65-99 — reference pattern for the `model_dump(mode='json')` round-trip; PERF-2 mirrors this structure but with the cacheability gate inverted (`user is None` instead of `is_admin`)."
    - "backend/tests/conftest.py:174 — singleton `init_cache()` shared across tests; the new test file MUST add an `autouse` fixture that calls `await get_cache().delete_pattern('catalog:search:*')` before each test (RESEARCH.md §6, mitigation 1)."
---

# 260426-ihc — PLAN: PR1 Search Hot-Path Caching (PERF-2 + PERF-7)

**Mode:** quick-full
**Quick ID:** 260426-ihc
**Status:** ready

Implements anonymous-only response caching on the two hot search endpoints flagged as PERF-2 and PERF-7 in `docs-internal/audits/post-impl-20260426-HANDOFF.md`. All implementation choices are locked by `260426-ihc-CONTEXT.md` (decisions) and `260426-ihc-RESEARCH.md` (mechanics). This plan is execution-only; no further research or replanning is expected.

## Tasks

### Task 1 — Add the search cache helper, wire PERF-2, and cover /search/datasets
- **files:**
  - `backend/app/modules/catalog/search/cache.py` (new)
  - `backend/app/modules/catalog/search/router.py` (modify `_handle_search`)
  - `backend/tests/test_search_cache.py` (new — 2 tests for /search/datasets)
- **action:**
  1. Create `backend/app/modules/catalog/search/cache.py` with:
     - `SEARCH_CACHE_TTL = 30` constant (per CONTEXT.md decision).
     - `EndpointKind = Literal["search", "facets"]`.
     - `is_anon_cacheable(user: User | None) -> bool` — returns `user is None` (single source of truth — RESEARCH.md §1 edge case: do NOT use `user_roles == set()`).
     - `build_cache_key(*, endpoint, filters, user_roles, public_api_url=None, semantic_enabled=None) -> str` that produces `catalog:search:<endpoint>:<sha1_hex>` from a canonical JSON payload `{"filters": dataclasses.asdict(filters), "endpoint": endpoint, "roles": sorted(user_roles), "public_api_url": public_api_url or "", "semantic_enabled": bool(semantic_enabled) if semantic_enabled is not None else False}` serialized with `json.dumps(..., default=str, sort_keys=True)` then hashed with `hashlib.sha1` (RESEARCH.md §3, §4 — `default=str` handles `date`/`UUID`; `sort_keys=True` is required).
     - `async def get_cached(key: str) -> dict | None` and `async def set_cached(key: str, payload: dict) -> None` thin wrappers over `get_cache()` using `SEARCH_CACHE_TTL`.
     - Module docstring: `"""Anonymous response cache for search hot-path endpoints (PERF-2, PERF-7)."""`.
     - Use `structlog.stdlib.get_logger(__name__)` and emit `logger.debug("search_cache_hit"|"search_cache_miss", key=key, endpoint=endpoint)` (Claude's Discretion in CONTEXT.md — debug only, never noisy).
  2. Wire into `_handle_search` (`backend/app/modules/catalog/search/router.py:313-528`):
     - Import `cache as search_cache` from the new module at the top of the file.
     - Read `semantic_enabled = await SEMANTIC_SEARCH_ENABLED.get(db)` once, immediately after the `user_roles` block (around line 327). Add the `from app.core.persistent_config import SEMANTIC_SEARCH_ENABLED` import.
     - After `filters = params.to_filters()` and `user_roles` resolution but BEFORE `search_datasets(...)` at line 330, build the key and short-circuit on hit:
       ```python
       cache_key = None
       if search_cache.is_anon_cacheable(user):
           cache_key = search_cache.build_cache_key(
               endpoint="search",
               filters=filters,
               user_roles=user_roles,
               public_api_url=public_api_url,
               semantic_enabled=semantic_enabled,
           )
           cached = await search_cache.get_cached(cache_key)
           if cached is not None:
               return OGCFeatureCollectionResponse(**cached)
       ```
     - Immediately before `return OGCFeatureCollectionResponse(...)` at line 519, build the response into a local variable `response`, then write-through and return:
       ```python
       response = OGCFeatureCollectionResponse(
           type="FeatureCollection",
           timeStamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
           numberMatched=total,
           numberReturned=len(features),
           features=features,
           links=links,
       )
       if cache_key is not None:
           await search_cache.set_cached(cache_key, response.model_dump(mode="json"))
       return response
       ```
     - DO NOT bypass `response_model` by returning a `JSONResponse` — RESEARCH.md §5 pitfall.
  3. Add `backend/tests/test_search_cache.py` with an autouse fixture and 2 tests for /search/datasets:
     ```python
     @pytest.fixture(autouse=True)
     async def _reset_search_cache():
         from app.platform.cache import get_cache
         await get_cache().delete_pattern("catalog:search:*")
         yield
         await get_cache().delete_pattern("catalog:search:*")
     ```
     - `test_anon_search_caches_response`: as anon, GET `/search/datasets/?q=cachetest_<unique>` (use a uuid4 hex slug to avoid cross-test collision), insert a matching published dataset between calls, assert the second response's `numberMatched` matches the FIRST response (stale = cache hit).
     - `test_authed_search_bypasses_cache`: same flow with `admin_auth_header`, assert second response's `numberMatched` reflects the new dataset (live = bypass).
     - Use `client` + `test_db_session` fixtures from `backend/tests/conftest.py`. Mirror dataset-insertion patterns already used in `backend/tests/test_search.py` (e.g. `test_search_unauthenticated_returns_200` at line 909) — do NOT invent new factories.
     - Follow project convention: tests are async, use `await client.get(...)`, no Redis dependency (in-memory provider is the test default per `tests/conftest.py:174` + `app/core/config.py` redis_url unset).
- **verify:**
  - `cd backend && uv run pytest tests/test_search_cache.py -x -v` — 2 new tests pass.
  - `cd backend && uv run pytest tests/test_search.py tests/test_search_facets.py tests/test_hybrid_search.py -q` — no regressions on existing search suites.
  - `cd backend && uv run ruff check app/modules/catalog/search/cache.py app/modules/catalog/search/router.py tests/test_search_cache.py` — 0 errors.
  - `grep -n "is_anon_cacheable\|build_cache_key\|search_cache\." backend/app/modules/catalog/search/router.py` — wiring sites visible at the expected lines (after user_roles block, before return).
- **done:**
  - `backend/app/modules/catalog/search/cache.py` exists with the 4 documented public symbols (`SEARCH_CACHE_TTL`, `is_anon_cacheable`, `build_cache_key`, `get_cached`, `set_cached`).
  - `_handle_search` reads from cache for anon callers and writes through on miss; authed callers go straight to the existing query path.
  - 2 new tests pass; existing search/facets/hybrid_search test files still pass.
  - Atomic commit: `perf(search): cache /search/datasets responses for anonymous callers (PERF-2)` (per constraints — one commit for cache helper + perf-2 wiring + /search/datasets tests).

### Task 2 — Wire PERF-7 (/search/facets) and cover with 2 more tests
- **files:**
  - `backend/app/modules/catalog/search/router.py` (modify `search_facets_endpoint`)
  - `backend/tests/test_search_cache.py` (extend — 2 more tests for /search/facets)
- **action:**
  1. In `search_facets_endpoint` (`backend/app/modules/catalog/search/router.py:539-595`):
     - After the `user_roles` block at lines 570-573 and after `facet_filters = SearchFilters(...)` is constructed at lines 575-587, but BEFORE `await get_facet_counts(...)` at line 589, add:
       ```python
       facet_cache_key = None
       if search_cache.is_anon_cacheable(user):
           facet_cache_key = search_cache.build_cache_key(
               endpoint="facets",
               filters=facet_filters,
               user_roles=user_roles,
               public_api_url=None,
               semantic_enabled=None,
           )
           cached = await search_cache.get_cached(facet_cache_key)
           if cached is not None:
               return cached  # FastAPI coerces dict -> FacetCountResponse via response_model
       ```
     - After `result = await get_facet_counts(...)` and before `return result`, add the write-through:
       ```python
       if facet_cache_key is not None:
           await search_cache.set_cached(facet_cache_key, result)
       return result
       ```
     - `result` is already a JSON-friendly `FacetCounts` TypedDict (`service.py:55-60, 544-550`) — no `model_dump` needed (RESEARCH.md §5 PERF-7 path).
     - PERF-7 keys MUST use `public_api_url=None` and `semantic_enabled=None` because the facets response carries no URLs and does not run semantic ranking — keeping these out of the hash maximizes hit rate.
  2. Extend `backend/tests/test_search_cache.py` with 2 facets tests:
     - `test_anon_facets_caches_response`: as anon, GET `/search/facets/?q=facettest_<unique>`, mutate the DB (insert a matching dataset), GET again, assert `record_type` totals match the FIRST response (stale = hit).
     - `test_authed_facets_bypasses_cache`: same with `admin_auth_header`, assert mutation is visible on the second call.
     - Reuse the autouse `_reset_search_cache` fixture from Task 1 — both endpoints share the `catalog:search:*` namespace.
     - Use the same dataset-insertion helper / pattern adopted in Task 1 — keep it DRY within the test module.
- **verify:**
  - `cd backend && uv run pytest tests/test_search_cache.py -x -v` — all 4 tests pass (2 from Task 1 + 2 new).
  - `cd backend && uv run pytest tests/test_search_facets.py -q` — no regressions.
  - `cd backend && uv run pytest -q --tb=line` — full suite at 1962+ passing of 1965 total (CONTEXT.md canonical_refs: 3 audit/* tests are pre-existing red and out of scope; the verifier baseline is 1962 of 1965, NOT 1965/1965).
  - `cd backend && uv run ruff check app/modules/catalog/search/router.py tests/test_search_cache.py` — 0 errors.
  - `grep -n "facet_cache_key\|search_cache\." backend/app/modules/catalog/search/router.py | head` — 2 cache wiring sites visible inside `search_facets_endpoint` (one before `get_facet_counts`, one after).
- **done:**
  - `search_facets_endpoint` reads from cache for anon callers and writes through on miss.
  - 4 tests pass total in `tests/test_search_cache.py`; no regressions in `tests/test_search_facets.py` or any other suite.
  - Full backend suite: passing count >= 1962 (the only remaining failures are the 3 known pre-existing audit/* WIP tests in `tests/test_audit.py`: `test_export_audit_logs_csv`, `test_export_audit_logs_json`, `test_export_audit_logs_invalid_format` — DO NOT touch `backend/app/modules/audit/` per constraints).
  - Atomic commit: `perf(search): cache /search/facets responses for anonymous callers (PERF-7)` (per constraints — second commit for perf-7 wiring + facets tests).

## Out of scope (do not touch)

- `backend/app/modules/audit/router.py`, `backend/app/modules/audit/service.py` — pre-existing WIP, not this PR.
- KISS-1, KISS-2 (search decomposition) — separate PR per HANDOFF.md PR 2.
- New invalidation call sites — CONTEXT.md decision: 30s passive TTL only; the existing `invalidate_catalog_cache()` already covers VRT mutations and shares the `catalog:` prefix.
- Authed-side caching with per-user keys — CONTEXT.md explicitly defers this.
- New dependencies — use existing `get_cache()`, `structlog`, `hashlib`, `json`, `dataclasses`.

## Verification at PR-completion

Run from `/Users/ishiland/Code/geolens/backend`:

```bash
uv run pytest tests/test_search_cache.py -x -v
uv run pytest tests/test_search.py tests/test_search_facets.py tests/test_hybrid_search.py -q
uv run pytest -q --tb=line                              # >= 1962 passing
uv run ruff check app/modules/catalog/search/ tests/test_search_cache.py
```

Sanity grep:

```bash
grep -n "is_anon_cacheable\|build_cache_key\|search_cache\." backend/app/modules/catalog/search/router.py
# Expect: hits in _handle_search (around lines 327-330 and pre-return) and in search_facets_endpoint
```
