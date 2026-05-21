# 260426-ihc — Research: PR1 Search Hot-Path Caching

**Researched:** 2026-04-26
**Scope:** PERF-2 (`_handle_search`) + PERF-7 (`get_facet_counts`) anonymous caching
**Confidence:** HIGH (all claims verified by reading the named source files)

## Summary

- **Anon detection is dirt-simple.** Both `_handle_search` (`search/router.py:324-327`) and `search_facets_endpoint` (`search/router.py:570-573`) already short-circuit to `user_roles = set()` when `user is None`. Reuse exactly that test — no new role-set inspection required.
- **`_handle_search` returns a Pydantic `OGCFeatureCollectionResponse`** (`search/router.py:519-528`) with `features: list[OGCRecordResponse]` and `links: list[OGCRecordLink]`. The links are pure pagination/self/root URLs derived from `params.offset/limit/q/...` plus `public_api_url` — they are deterministic given the SAME inputs we plan to hash. Cache the assembled response after links and round-trip via `model_dump(mode="json")` ↔ `OGCFeatureCollectionResponse(**cached)`. No need to re-run link assembly on hit.
- **`SearchFilters` is a frozen `@dataclass(slots=True)`** (`search/service.py:90-118`), NOT a Pydantic model. It has no `model_dump`. Use `dataclasses.asdict(filters)` and serialize with `json.dumps(default=str, sort_keys=True)` to handle `date`/`UUID` fields cleanly. `geometry_geojson` is already a `str`; `bbox` is `list[float]`; no GeoAlchemy/WKB types appear in the dataclass.
- **`get_facet_counts` returns a `FacetCounts` `TypedDict`** (`search/service.py:55-60, 544-550`) — already pure JSON-friendly. Cache the dict directly; no model coercion on hit.
- **Singleton in-memory cache persists across tests.** `init_cache()` runs once per session (`tests/conftest.py:174`); there is no per-test reset fixture. Tests must either (a) use unique filter values per test, or (b) call `await get_cache().delete_pattern("catalog:search:*")` in a fixture. There is no precedent for the second — adopt option (a) where possible.
- **`base_url` / `public_api_url` is request-derived but stable per deployment.** It only varies when `PUBLIC_API_URL` setting is changed or when `request.url` host differs. For a single test client / single deployment, it's effectively constant; we still must include it in the key to be safe (otherwise a deployment URL change would serve stale links). Recommended: include `public_api_url` in the hash input.

## 1. Anon-detection

The canonical pattern already exists, used identically in both target routes:

```python
# search/router.py:324-327 (_handle_search)
if user is not None:
    user_roles = await get_user_roles(db, user)
else:
    user_roles = set()
```

Same pattern at `search/router.py:570-573` (facets endpoint).

- `get_optional_user` (`auth/dependencies.py:61-102`) returns `User | None`. It tries API-key (header **and** `?api_key=` query param), then JWT Bearer; returns `None` on any failure path.
- `get_user_roles` (`auth/visibility.py:96-106`) is a DB query — only ever called for authenticated users. Returns `set[str]` of role names (e.g. `{"admin"}`, `{"editor"}`, `{"viewer"}`). Empty set is reserved for the anon path.
- Anon roles are stable across requests by construction: anon = literal `set()`, not "no roles fetched yet." Two anon callers will produce the SAME serialized roles tuple.

**Recommendation:** the cacheability gate is exactly `user is None`. Do NOT introduce a "public role check" — the empty set IS the anon signal in this codebase. Use the existing `if user is not None: roles = ... else: roles = set()` pattern; cache only when `user is None`.

**Edge case worth flagging in the plan:** an API-key request that resolves to a user with empty role assignments would have `user is not None` and `user_roles == set()`. That's an authed-but-no-roles case and should NOT hit the anon cache. Keying on `user is None` (not on `user_roles == set()`) handles this correctly.

## 2. Response shape (PERF-2)

`_handle_search` returns:

```python
# search/router.py:519-528
return OGCFeatureCollectionResponse(
    type="FeatureCollection",
    timeStamp=datetime.now(timezone.utc).isoformat(...).replace("+00:00", "Z"),
    numberMatched=total,
    numberReturned=len(features),
    features=features,            # list[dict] coerced to list[OGCRecordResponse]
    links=links,                  # list[OGCRecordLink]
)
```

- `OGCFeatureCollectionResponse` is the Pydantic model in `search/schemas.py:145-156`.
- `features` is built from `dataset_to_ogc_record(...)` (`search/service.py:994+`) which returns plain `dict`. Pydantic coerces these to `OGCRecordResponse` on construction.
- `links` is built fresh from `params` + `public_api_url` (`search/router.py:466-517`). Given identical hash inputs, the links are byte-identical, so caching after link assembly is safe.
- `timeStamp` is the ONE non-deterministic field. It is informational metadata, not part of the response semantics. Caching it as part of the payload means cache hits return a slightly-stale timestamp — acceptable trade-off, and matches what "30s passive TTL" implies. If desired, the cache helper can re-stamp it on hit (cheap), but it's not required for correctness.

**Recommendation:** Cache the FULL `OGCFeatureCollectionResponse` payload (after link assembly). Round-trip:
- Set: `cache.set(key, response.model_dump(mode="json"), ttl=30)`
- Get: `OGCFeatureCollectionResponse(**cached)` — mirrors the existing pattern at `datasets/api/router.py:87`.

The natural cache boundary is at the very end of `_handle_search`, immediately before `return`. Place the cache lookup at the top of the function (after `params.to_filters()` so we can hash filters) — early-return on hit.

## 3. SearchFilters serialization

```python
# search/service.py:90-118
@dataclass(frozen=True, slots=True)
class SearchFilters:
    q: str | None = None
    bbox: list[float] | None = None
    keywords: list[str] | None = None
    geometry_type: str | None = None
    srid: int | None = None
    source_organization: str | None = None
    record_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    vintage_start: date | None = None
    vintage_end: date | None = None
    datetime_param: str | None = None
    exclude_synthetic: bool = True
    collection_id: uuid_mod.UUID | None = None
    spatial_predicate: Literal["intersects", "within"] = "intersects"
    geometry_geojson: str | None = None
    cql2_filter: str | None = None
    cql2_filter_lang: str = "cql2-text"
    sort_by: str = "relevance"
    sort_desc: bool | None = None
    skip: int = 0
    limit: int = 10
```

NOT a Pydantic model — no `.model_dump()`. Fields needing care:

| Field | Type | Serialization note |
|-------|------|-------------------|
| `date_from`, `date_to`, `vintage_start`, `vintage_end` | `date` | Not JSON-native. Use `default=str` in `json.dumps` — produces ISO `YYYY-MM-DD`. |
| `collection_id` | `uuid.UUID` | Same — `default=str` produces canonical hex. |
| `bbox` | `list[float]` | Native JSON. |
| `keywords` | `list[str]` | Native JSON. **Order-sensitive** — request params already define order; do NOT sort here (different keyword orders can be intentional). |
| `geometry_geojson` | `str` (already-serialized JSON string) | Treat as opaque string — do NOT re-parse. Whitespace/key-order in user input WILL produce different cache keys; that's acceptable (low miss rate, never wrong). |
| Everything else | `str / int / bool / None` | Native JSON. |

**Recommendation:**

```python
import dataclasses, json, hashlib

def _filters_fingerprint(f: SearchFilters) -> str:
    payload = json.dumps(dataclasses.asdict(f), default=str, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()
```

`sort_keys=True` makes field order deterministic across Python versions. `default=str` covers `date` and `UUID`. `slots=True` does not break `dataclasses.asdict` (verified in Python 3.10+).

Note: `SearchFilters` already includes `skip` and `limit` (lines 117-118), so pagination is captured in the fingerprint without extra work.

## 4. Hash inputs

CONTEXT.md proposes `(SearchFilters_dict, offset, limit, roles_sorted_tuple, endpoint_kind)`. After reading the code:

| Input | Required? | Notes |
|-------|-----------|-------|
| `dataclasses.asdict(filters)` | Yes | Includes `skip`/`limit` already — `offset`/`limit` are redundant inputs but harmless. |
| `endpoint_kind` ("search" / "facets") | Yes | Two endpoints share the prefix. |
| `roles_sorted_tuple` | Yes — for forward compat | For now will always be `()` since we only cache anon, but cheap to include. |
| `public_api_url` | **Yes — newly identified** | Links inside the cached `OGCFeatureCollectionResponse` (PERF-2 only) embed this URL. If the URL changes (PUBLIC_API_URL setting flip, request.host change), cached links go stale. Including it in the key is the safe choice. **Not** needed for PERF-7 facets — facets response has no URLs. |
| `semantic_enabled` flag | **Yes — newly identified** | `search_datasets` (`service.py:715-716`) reads `SEMANTIC_SEARCH_ENABLED` and toggles RRF merge ON/OFF. If an admin flips this setting mid-TTL, anon users would see stale ranking. Either (a) include `await SEMANTIC_SEARCH_ENABLED.get(session)` in the key, or (b) call `invalidate_catalog_cache()` from the SEMANTIC_SEARCH_ENABLED setter. (a) is simpler and self-contained; (b) requires touching settings code. **Recommend (a).** |
| `request_id`, IP, X-Forwarded-*, timestamps | NO | Per-request — would defeat the cache. CONTEXT.md already calls this out. |
| User-Agent / Accept | NO | Response is always JSON; content negotiation is not in play here. |
| `Accept-Language` | NO | The codebase calls `parse_accept_language` elsewhere but `_handle_search` does not branch on it — search responses are language-agnostic. (Verified: no `parse_accept_language` reference in `_handle_search` or its callees.) |

**Final recommended hash input** (canonical JSON, sorted keys):
```python
{
  "filters": dataclasses.asdict(filters),       # has skip/limit
  "endpoint": "search" | "facets",
  "roles": sorted(user_roles),                  # always [] for anon
  "public_api_url": public_api_url,             # PERF-2 only; omit/empty for PERF-7
  "semantic_enabled": bool,                     # PERF-2 only; facets don't use semantic
}
```

Final cache key: `f"catalog:search:{endpoint}:{sha1_hex}"` (CONTEXT.md format). The `catalog:` prefix is consumed by the existing `delete_pattern("catalog:*")` invalidator.

## 5. Cache hit reconstruction

**PERF-2 (search):** `OGCFeatureCollectionResponse` is a Pydantic v2 model (`search/schemas.py:145-156`). Round-trip pattern is identical to the existing example at `datasets/api/router.py:87`:

```python
cached = await cache.get(key)
if cached is not None:
    return OGCFeatureCollectionResponse(**cached)   # re-coerces dict -> model
```

This works because `model_dump(mode="json")` on Pydantic v2 produces a dict whose values are JSON-native (datetimes already stringified, UUIDs as hex). Pydantic re-validates on `Model(**cached)`. Confirmed: `OGCRecordResponse` and `OGCRecordLink` (the nested types) accept dict input out of the box. **No custom reconstruction logic needed.**

**PERF-7 (facets):** `get_facet_counts` returns `FacetCounts` TypedDict (`service.py:55-60`). Already pure dict. The router signature is `-> FacetCountResponse`, but FastAPI's `response_model=FacetCountResponse` (`router.py:538`) will coerce a returned dict into the response model automatically. So either:

```python
cached = await cache.get(key)
if cached is not None:
    return cached                                 # FastAPI coerces dict -> FacetCountResponse
```

is fine, or — symmetric with PERF-2 — `return FacetCountResponse(**cached)`. Either works; pick whichever is consistent across the helper.

**Pitfall:** Don't return a `JSONResponse` directly from a cache hit — that bypasses the `response_model` validation and skips OpenAPI schema enforcement. Always return the dict or the model.

## 6. Test conventions

Key conftest facts:

- **Cache singleton, NOT per-test fixture.** `init_cache()` is called inside the session-scoped `client` fixture (`tests/conftest.py:174`). The default backend is `InMemoryCacheProvider` (because `redis_url` is unset in test config; verified at `app/core/config.py:68`).
- **No `_cache_provider` reset between tests.** `_cache_provider` is module-global in `app/platform/cache/provider.py:33`. Once initialized, it persists for the whole pytest session.
- **No precedent for cache-mocking in feature tests.** Searching `tests/test_*.py` for `cache` finds only `test_cache.py` (provider unit tests), `test_tile_cache.py` (separate provider), and 3 mock-call sites in VRT/reupload tests that mock the *invalidator*, not the cache itself. Nothing mocks `get_cache()` for behavioral search tests.
- **Existing search tests are anonymous-friendly.** `test_search_unauthenticated_returns_200` (`tests/test_search.py:909-914`) confirms the anon path returns 200. Auth'd tests use the `admin_auth_header` fixture.

**Cache contamination risk:** because the cache is shared across tests in a session, two tests hitting `/search/datasets/?q=foo` as anon would share a cache entry. If test A's database state differs from test B's, test B's first request returns test A's cached response — false PASS.

**Mitigations the plan should adopt (pick at least one):**

1. **Per-test invalidation fixture** — add an `autouse` fixture in the new test file (or in `conftest.py`) that calls `await get_cache().delete_pattern("catalog:search:*")` before each test. Cleanest, recommended.
2. **Unique queries per test** — ensure each test's filters produce a unique key (e.g. unique `q=` strings). Fragile; relies on author discipline.

For the cache-hit-detection assertion itself (test "anon hit"), the standard pattern is: spy on the cache via `unittest.mock.patch` on `app.platform.cache.get_cache` (or on a new `_cache` attribute in the helper module). Alternative: assert side effects — second call with same params is faster, OR mutate DB between calls and assert the cached (stale) response is returned.

**Recommended test structure (mirrors `test_cache.py:104-111` for delete_pattern, and `test_search.py:909-914` for anon search):**

- `test_anon_search_caches_response` — call `/search/datasets/?q=X` twice anon, mutate DB between calls, assert second call returns first call's data (proves cache hit).
- `test_authed_search_bypasses_cache` — call once with admin_auth_header, mutate DB, call again with same header, assert second call sees mutation (proves bypass).
- Same two patterns for `/search/facets/`.

## 7. Pitfalls

Things to NOT cache, or to verify before caching, on the anon path:

| Concern | Verdict | Source |
|---------|---------|--------|
| `created_by_username` per-user fields | **NOT in response.** `dataset_to_ogc_record` does not include any `*_username` field. Verified: `grep created_by_username search/{router,service}.py` returns nothing. | `search/service.py:994-1110+` |
| `updated_by_display` (provenance) | **Safe.** Derived from the editor's `User` row (`derive_last_edited` at `sources/provenance.py:92-125`). Same dataset → same display → same value regardless of viewer. Privacy-sensitive *for anon* only if RESTRICTED_ACTOR_LABEL leaks PII — it does not (it's a literal placeholder). | `provenance.py:80-89` |
| `extent_geojson_map` | **Safe.** Built from `Record.spatial_extent` via `ST_AsGeoJSON` (`search/router.py:404-415`). Geometry is a property of the record, not the requester. |
| RBAC-filtered facet counts | **Safe IF anon-keyed.** `get_facet_counts` calls `apply_visibility_filter(stmt, user, user_roles, ...)` (`service.py:443-445`). For `user=None`, that filter narrows to `visibility=PUBLIC AND record_status='published'`. Caching anon responses ONLY guarantees these are the same numbers every anon caller would compute. |
| `numberMatched` / `numberReturned` | **Safe.** Derived from filter + RBAC; anon-deterministic. |
| `timeStamp` | **Stale by design.** Cached value will be the timestamp of the first miss inside the TTL window. Acceptable. |
| `request_id`, `X-Request-ID`, X-Forwarded-* | **Not in response body.** None of these appear in `_handle_search`'s output dict. They're response headers / log context only. No leak risk via cache. |
| `public_api_url` in `links[]` | **Cached** but cache-keyed by it (see §4). If `PUBLIC_API_URL` setting is flipped, must rely on TTL (30s) for natural rotation. Acceptable. |
| Saved-search results | **Out of scope.** `/search/saved/*` requires auth (`router.py:622-680`). Not anon-cacheable. |
| Collection-search "merge" rows on first page | **Safe.** Built from `search_collections(db, q, user, user_roles, ...)` (`router.py:437`); collections themselves don't carry user-bound data. |

**No leaks identified.** The anon path response is purely a function of (filters, public-data, RBAC-filter-for-anon, public_api_url, semantic_enabled).

## 8. Invalidation reach

**`invalidate_catalog_cache()` is the only `catalog:*` deleter** (`platform/cache/tiles.py:8-17`). Implementation:

```python
async def invalidate_catalog_cache() -> None:
    cache = get_cache()
    await cache.delete_pattern("catalog:*")
```

Callers:
- `processing/ingest/tasks_vrt.py:300, 530` (VRT mutations)
- (No other callers — confirmed by `grep -rn "delete_pattern.*catalog\|cache.delete.*catalog:" backend/app/`)

**Conclusion:** keys prefixed `catalog:search:*` will be flushed by every existing call site. No new callers needed for PR1. **Caveat:** this is also a freshness gap — non-VRT mutations (regular dataset publish/unpublish, record edits, visibility flips) do NOT call the invalidator today. Anon users will see up-to-30-seconds-stale results in those cases. CONTEXT.md explicitly accepts this trade-off ("30s passive TTL, no active invalidation hook from this PR").

**Pattern check:** `delete_pattern("catalog:*")` matches `catalog:search:*` correctly:
- `InMemoryCacheProvider`: uses `fnmatch.fnmatch(k, pattern)` (`memory.py:32`). `fnmatch("catalog:search:foo", "catalog:*")` → True. ✅
- `RedisCacheProvider`: uses `client.scan_iter(match=pattern)` (`redis.py:110`). Redis glob `catalog:*` matches across `:` boundaries. ✅

## 9. Cache backend differences

After reading both providers in full:

| Behavior | InMemory (`memory.py`) | Redis (`redis.py`) | Impact on us |
|----------|-----------------------|---------------------|--------------|
| TTL precision | `time.monotonic()` seconds, float | Redis `EX` seconds, integer | Identical for our 30s TTL. |
| Encoding | Native Python objects (no copy, no serialization) | `json.dumps(value, default=str)` (`redis.py:86`) | **Critical.** InMemory will accept and return any Python object, INCLUDING a Pydantic model. Redis will serialize via JSON; a Pydantic model passed directly would raise `TypeError`. **MUST** call `.model_dump(mode="json")` BEFORE `cache.set()` to be Redis-compatible — not just for the round-trip but for the set itself. The existing `datasets/api/router.py:97-99` does this correctly. Mirror that pattern. |
| Decode on get | Python object identity preserved | `json.loads(raw)` returns plain dict | InMemory could return a Pydantic model that was set as one; Redis can never. Always treat the cached value as a plain dict on get. The `Model(**cached)` reconstruction handles both. |
| `delete_pattern` semantics | `fnmatch` against in-process dict keys | `SCAN` iterator + `DEL` per key | Both work for `catalog:*`. Redis `SCAN` is cursor-based and may iterate live keys multiple times under heavy writes, but for our TTL-only flow this is fine. |
| Failure handling | Always succeeds (in-process) | Circuit breaker → falls back to in-memory after `max_failures=5` | Production safety: even if Redis dies, our cache transparently degrades. No code changes needed. |
| Concurrent writes | Last-write-wins on dict | Last-write-wins on Redis | Identical. Both providers are subject to thundering-herd — multiple anon callers can each compute and cache the same result during a TTL miss. Acceptable for 30s TTL; not worth a singleflight in this PR. |
| `default=str` JSON quirk | N/A | `datetime`, `UUID`, `date` serialize to `str(obj)` | Don't rely on Redis to round-trip non-JSON types — that's why `model_dump(mode="json")` is mandatory. |

**Plan-relevant takeaway:** the helper MUST call `model_dump(mode="json")` (PERF-2) or coerce TypedDict fields to JSON-native (PERF-7 already is) before `cache.set()`. The TypedDict from `get_facet_counts` is already pure-dict and pure-JSON-types; verified at `service.py:544-550`.

## 10. Recommended file structure + helper signature

**Decision:** new file `backend/app/modules/catalog/search/cache.py`.

Rationale:
- Co-located with the routes that use it (`search/router.py` and the service it depends on are in the same package).
- `app/platform/cache/tiles.py` is a sibling pattern (search-specific cache helpers next to the search module mirrors tile cache helpers in the platform layer where the tile producer lives).
- Avoids cluttering `app/platform/cache/` with module-specific keying logic that knows about `SearchFilters`.
- One file, no new top-level package — minimal diff.

**Sketch (do not implement — planner builds this):**

```python
# backend/app/modules/catalog/search/cache.py
"""Anonymous response cache for search hot-path endpoints (PERF-2, PERF-7)."""
import dataclasses, hashlib, json
from typing import Any, Literal

import structlog
from app.platform.cache import get_cache
from app.modules.auth.models import User
from app.modules.catalog.search.service import SearchFilters

logger = structlog.stdlib.get_logger(__name__)

SEARCH_CACHE_TTL = 30  # seconds — CONTEXT.md decision
EndpointKind = Literal["search", "facets"]


def is_anon_cacheable(user: User | None) -> bool:
    """The single source of truth for "should we use the anon cache?"."""
    return user is None


def build_cache_key(
    *,
    endpoint: EndpointKind,
    filters: SearchFilters,
    user_roles: set[str],
    public_api_url: str | None = None,    # only relevant for "search"
    semantic_enabled: bool | None = None, # only relevant for "search"
) -> str:
    payload = {
        "filters": dataclasses.asdict(filters),
        "endpoint": endpoint,
        "roles": sorted(user_roles),
        "public_api_url": public_api_url or "",
        "semantic_enabled": bool(semantic_enabled) if semantic_enabled is not None else False,
    }
    digest = hashlib.sha1(
        json.dumps(payload, default=str, sort_keys=True).encode()
    ).hexdigest()
    return f"catalog:search:{endpoint}:{digest}"


async def get_cached(key: str) -> dict | None:
    cache = get_cache()
    return await cache.get(key)


async def set_cached(key: str, payload: dict) -> None:
    cache = get_cache()
    await cache.set(key, payload, ttl=SEARCH_CACHE_TTL)
```

Routes call:
```python
# in _handle_search (anon path only)
if is_anon_cacheable(user):
    key = build_cache_key(endpoint="search", filters=filters, user_roles=user_roles,
                         public_api_url=public_api_url, semantic_enabled=...)
    if (cached := await get_cached(key)) is not None:
        return OGCFeatureCollectionResponse(**cached)
# ... existing handler body ...
if is_anon_cacheable(user):
    await set_cached(key, response.model_dump(mode="json"))
return response
```

Symmetric for the facets endpoint, returning a dict (FastAPI coerces to `FacetCountResponse`).

## Pre-flight checks for the planner (open questions remaining)

1. **`semantic_enabled` lookup placement.** `SEMANTIC_SEARCH_ENABLED.get(session)` is currently called INSIDE `search_datasets` (`service.py:715`). To include it in the cache key BEFORE running the query, `_handle_search` (or the cache helper) needs to call it once up-front. This is one extra DB round-trip per request — but it's cached at the persistent_config layer, so the cost is negligible. Confirm with planner: pull it up to `_handle_search`, pass it down? Or accept that we read it twice (once for keying, once inside `search_datasets`)? Reading twice is simpler and safe — the value is process-cached. **Recommendation: read twice, no plumbing change.**

2. **Should `_handle_search`'s collection-merge path participate in the cache?** The collection-results merge (`router.py:430-463`) only runs when `params.q` is non-empty AND `offset == 0` AND no `record_type`/`collection_id` filter. Filters fully determine whether it runs, so the merge IS deterministic given the cache key inputs. **No special-casing needed** — caching the final response covers it.

3. **`numberReturned` vs. `numberMatched` semantics on cache hit.** Both are fields of the cached payload. They are correctly tied to the (filters, offset, limit) tuple — verified. No drift risk.

4. **The 3 pre-existing red `tests/test_audit.py` cases** (CONTEXT canonical_refs, lines 122-124) are unrelated to this work. Baseline expectation is `1962 passing of 1965` until the audit/* WIP is resolved. The PR1 verifier should treat that as the floor, not regress to 1961 or below.

5. **No new feature flag.** CONTEXT.md does not request one; the cache is always on for anon. If we want a kill-switch later, it can be added as a `persistent_config` boolean — out of scope for PR1.

## RESEARCH COMPLETE

**File:** `/Users/ishiland/Code/geolens/.planning/quick/260426-ihc-pr1-search-hot-path-caching-perf-2-perf-/260426-ihc-RESEARCH.md`
