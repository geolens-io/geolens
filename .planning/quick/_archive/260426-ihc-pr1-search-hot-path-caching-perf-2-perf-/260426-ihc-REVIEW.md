---
quick_id: 260426-ihc
review_date: 2026-04-26
depth: quick
status: issues_found
files_reviewed: 3
findings: { blocker: 0, major: 0, warning: 6, info: 5 }
---

# Quick Task 260426-ihc — Code Review

**Reviewed:** 2026-04-26
**Files in scope:**
- `backend/app/modules/catalog/search/cache.py` (new)
- `backend/app/modules/catalog/search/router.py` (cache wiring only)
- `backend/tests/test_search_cache.py` (new)

## Summary

Implementation correctly mirrors locked decisions in CONTEXT.md / RESEARCH.md / PLAN.md. Permission-leak surface is well-contained (gate is `user is None`, no per-user fields in cached payload, hash includes `public_api_url` and `semantic_enabled`). JSON-safety for Redis is correct: PERF-2 calls `model_dump(mode="json")` before `cache.set`, FacetCounts is JSON-native. Round-trip on hit matches the `datasets/api/router.py:87` pattern.

Six warnings worth fixing, no blockers, no security findings.

## Warnings

### WR-01 — `SEMANTIC_SEARCH_ENABLED.get(db)` runs unconditionally for every request

**File:** `backend/app/modules/catalog/search/router.py:331`
**Issue:** Read happens BEFORE the `is_anon_cacheable(user)` gate. Authed callers (who never use the cache) pay one extra read per request. Inside `search_datasets` the same value is read again, so authed traffic now does two lookups instead of one. The persistent-config layer is process-cached so cost is small, but it is unnecessary work on the authed path.
**Fix:** Hoist the read inside the gate so it only runs when caching is applicable.

### WR-02 — Anon-hit tests don't positively prove the cache was hit

**File:** `backend/tests/test_search_cache.py:139-159, 239-257`
**Issue:** Tests assert "second response equals first" — necessary but not sufficient. RESEARCH.md §6 calls out this exact false-positive class.
**Fix:** Add a direct cache-key probe after the second GET (`assert await get_cache().get(expected_key) is not None`) or mock-spy on the underlying service to assert call count.

### WR-03 — Misleading docstring on `_reset_search_cache`

**File:** `backend/tests/test_search_cache.py:34-48`
**Issue:** Docstring claims provider is "session-scoped singleton" but `init_cache()` is rebound on every `client` fixture (function-scoped). Defensive flush is still useful for future Redis-backed test runs but the docstring should reflect actual behavior.
**Fix:** Update docstring to reflect that the provider is per-test-fresh and `delete_pattern` is a defensive safety net.

### WR-04 — No unit test pinning the `is_anon_cacheable` contract

**File:** `backend/tests/test_search_cache.py` (whole file)
**Issue:** RESEARCH.md §1 calls out the API-key-authed-with-empty-roles edge case. The gate correctly uses `user is None` (not `user_roles == set()`) but no test locks this invariant. Future "simplification" could regress silently.
**Fix:** Add a direct unit test that `is_anon_cacheable(None) is True` and `is_anon_cacheable(User(...)) is False`.

### WR-05 — Full-response round-trip not asserted

**File:** `backend/app/modules/catalog/search/router.py:546-548` (and tests)
**Issue:** Cached payload is `model_dump(mode="json")`; on hit we do `OGCFeatureCollectionResponse(**cached)`. The round-trip is non-trivial (heterogeneous features, real datasets + collection-merge entries). If a future change breaks reconstruction (e.g., `extra="forbid"` flip), cache-hit returns 500 while cache-miss returns 200 — manifests only under load.
**Fix:** Assert full-body equivalence (modulo `timeStamp`) in the anon test.

### WR-06 — Test cache-flush prefix won't survive future helper-prefix renames

**File:** `backend/tests/test_search_cache.py:46, 48`
**Issue:** Tests hardcode `catalog:search:*`. If `cache.py` ever changes the prefix, the autouse fixture silently no-ops while tests still appear to pass.
**Fix:** Either extract `CACHE_KEY_PREFIX = "catalog:search:"` and import it, or use `catalog:*` (matches the production invalidator's reach).

## Info

### IN-01 — `default=str` is silently permissive

**File:** `backend/app/modules/catalog/search/cache.py:60-62`
Future SearchFilters fields with non-deterministic `__str__` (e.g., `<X at 0x7f…>`) would silently degrade the cache to a no-op. Document the maintenance contract or replace with explicit allowlist.

### IN-02 — Tri-state collapse on `semantic_enabled`

**File:** `backend/app/modules/catalog/search/cache.py:56-58`
`bool(semantic_enabled) if semantic_enabled is not None else False` collapses `None` and `False` to the same digest. Forward-looking; current usage is unambiguous.

### IN-03 — Logger fields lack endpoint discriminator

**File:** `backend/app/modules/catalog/search/cache.py:71-73`
`search_cache_hit` events don't distinguish search vs facets cleanly — only via SHA-1 prefix. Minor.

### IN-04 — Implicit Pydantic v2 dependency

**File:** `backend/app/modules/catalog/search/router.py:547`
`model_dump(mode="json")` is Pydantic v2 only. Codebase is on v2 today; no defensive guard. Note only.

### IN-05 — Keywords-order convention undocumented in code

**File:** `backend/app/modules/catalog/search/cache.py:32-63`
RESEARCH.md §3 documents intentional order-preservation; the helper itself doesn't mention it. One-line comment recommended.

## Verification of stated risks (from review brief)

1. Anon-only gate is `user is None` — confirmed `cache.py:29`. Not roles-based.
2. Stable serialization — confirmed; all current SearchFilters field types are JSON-native.
3. JSON-safety for Redis — confirmed; `model_dump(mode="json")` before `set_cached` for PERF-2; FacetCounts is plain dict.
4. Cache hit reconstruction — confirmed; matches `datasets/api/router.py:87` pattern.
5. TTL + `delete_pattern("catalog:*")` reach — confirmed; both backends match.
6. Test correctness — sound but improvable per WR-02 / WR-05.

## Disposition

Inline fixes will be applied before task finalization (per project convention — fix review findings inline rather than deferring). Targeted set: WR-01, WR-02, WR-04, WR-05, WR-06 (highest-leverage). WR-03 docstring + IN-02/IN-03/IN-05 small comment/cleanup also bundled.
