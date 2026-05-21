---
quick_id: 260426-ihc
description: PR1 — Search hot-path caching (PERF-2 + PERF-7)
gathered: 2026-04-26
status: ready_for_planning
parent_audit: docs-internal/audits/post-impl-20260426-HANDOFF.md
findings_in_scope: [PERF-2, PERF-7]
---

# Quick Task 260426-ihc: PR1 Search Hot-Path Caching — Context

**Gathered:** 2026-04-26
**Status:** Ready for planning

<domain>
## Task Boundary

Add a caching layer to two hot search endpoints called out as PERF-2 and PERF-7 in
`docs-internal/audits/post-impl-20260426-HANDOFF.md`:

- **PERF-2:** `_handle_search` in `backend/app/modules/catalog/search/router.py:340-481`
  serves both `/search/datasets` and OGC `/collections/datasets/items`. Today it issues
  6–8 sequential queries per request (count, main, asset/raster/VRT bulk, extent
  geojson_map, optional collections, facets) ≈ 80–100 ms warm.
- **PERF-7:** `get_facet_counts` in `backend/app/modules/catalog/search/service.py:445-557`
  runs 5 sequential aggregates against a CTE on every UI filter change (~100–300 ms).

Out of scope:
- KISS-1 (`search_datasets` decomposition) — separate PR.
- KISS-2 (`_handle_search` decomposition) — separate PR.
- Other handoff items (PERF-1, PERF-6, PERF-10, CLEANUP-2, KISS-7/8).

</domain>

<decisions>
## Implementation Decisions

### Cache scope
- **Anonymous only.** Cache reads only when `user is None` (or, more precisely, when
  the resolved roles set is the public/anon role set with no user_id). Authed and admin
  requests bypass the cache and run live.
- Reason: highest safety — no user-specific filter or RBAC mask can leak from a key
  collision. Highest hit rate too (the default browse page is anon-heavy).
- Existing `datasets/api/router.py` caches admin-only; we are NOT mirroring that pattern
  here. Search hot path has the opposite traffic profile (anon-dominant), so the cache
  scope is inverted accordingly. (If we later need authed-side caching, it can be
  layered on with a per-user key — out of scope.)

### TTL + invalidation
- **30 s passive TTL**, no active invalidation hook from this PR.
- Rationale: catalog browse is dominated by reads; 30 s window keeps newly-published
  datasets visible quickly enough for the demo/preview flow without requiring tight
  coupling between every publish path and a cache invalidator.
- The existing `invalidate_catalog_cache()` helper deletes `catalog:*` and is already
  wired on VRT mutations (`processing/ingest/tasks_vrt.py:300,530`). Because our keys
  share that `catalog:*` prefix (see Key format below), VRT-driven invalidation flushes
  search cache too — free freshness. We do **not** add new invalidation call sites in
  this PR (would be a separate scope decision).

### Key format
- Prefix: `catalog:search:` (so existing `catalog:*` `delete_pattern` flushes us).
- Endpoint discriminator: append `count` / `main` / `facets` / `links` when caching
  sub-results, or `aggregate` if caching the full `_handle_search` response.
- Identity component: SHA-1 of a stable JSON dump of `(SearchFilters_dict, offset, limit,
  roles_sorted_tuple, base_url_or_endpoint_kind)`. Hex-prefixed for debug grep.
- Final key: `catalog:search:<endpoint>:<sha1_hex>`.
- Reason: hash-based keys are compact, escape-safe, and let us key on arbitrary filter
  shapes without explosion or quoting bugs.

### Anonymous identity in the key
- "Anonymous" requests must produce the **same** key for any two anonymous callers
  (so they share the cache hit). Use the resolved `user_roles` set serialized in
  sorted tuple form. If `user is None` and the resolved roles tuple is `("public",)` or
  empty, we treat that as the canonical anon key.
- Do NOT include `request_id`, timestamps, IP, or anything per-request in the key.

### What gets cached
- **PERF-2:** Cache the final `_handle_search` response payload (the structured dict
  the route ultimately returns to JSON-encode). Sub-query caching is more invasive and
  not needed at this fidelity. If the response cannot be serialized cleanly (Pydantic
  model with non-JSON fields), cache the model_dump(mode="json") form. If the response
  embeds non-deterministic per-user fields (created_by_username), those fields should
  be omitted on the anon path — verify before keying.
- **PERF-7:** Cache the `get_facet_counts` return value directly (it is already a dict
  of counts).

### Anon identity check
- Use a single helper to decide cacheability on the anon path; do not duplicate the
  check in two routes.

### Claude's Discretion
- Exact helper file/path: prefer adding a `search_cache.py` next to the search router
  if no shared helper module exists, or reusing the existing `tiles.py` pattern. Pick
  whichever blends best with current convention.
- Whether to also add a 1-line log on cache hit/miss (helpful for verification, but
  must not be noisy under load — pick `logger.debug` if added).
- Test approach: at least 2 tests per endpoint (anon hit, authed bypass). Use the
  existing in-memory cache backend; do not require Redis in tests.

</decisions>

<specifics>
## Specific Ideas / References

- Existing infra: `backend/app/platform/cache/{provider,memory,redis}.py` —
  `get_cache()` returns either `RedisCacheProvider` or `InMemoryCacheProvider`.
- Existing example: `backend/app/modules/catalog/datasets/api/router.py:65-99`
  shows the standard get/set pattern around a handler. Mirror its structure but
  invert the user-condition gate.
- Existing invalidation: `backend/app/platform/cache/tiles.py:8` calls
  `cache.delete_pattern("catalog:*")`.
- Tests live alongside in `backend/tests/test_search.py`,
  `backend/tests/test_search_facets.py`, `backend/tests/test_hybrid_search.py`.

</specifics>

<canonical_refs>
## Canonical References

- Source-of-truth audit: `docs-internal/audits/post-impl-20260426.md` (Section 2,
  PERF-2 and PERF-7).
- Handoff: `docs-internal/audits/post-impl-20260426-HANDOFF.md` (PR 1 section).
- Working-tree note: 3 audit/* tests are pre-existing red and unrelated to this PR.
  Verifier should treat the baseline as 1962 passing of 1965 tests, not 1965/1965.

</canonical_refs>
