---
phase: 260326-f71
verified: 2026-03-26T12:00:00Z
status: gaps_found
score: 3/4 must-haves verified
gaps:
  - truth: "Findings document accurately describes the codebase state"
    status: failed
    reason: "FINDINGS.md incorrectly states no tile cache layer exists in the request path. The codebase has had TileCacheProvider wired into tile_endpoint since commit e53659bd (2026-03-16). The executor reviewed the live code and missed or misread it."
    artifacts:
      - path: "backend/app/tiles/router.py"
        issue: "Lines 416-428 show a fully wired tile cache check-and-return path using get_tile_cache(). The executor reported this as absent."
      - path: "backend/app/cache/tile_cache.py"
        issue: "Full TileCacheProvider with get/set/invalidate_table interface. Created in commit 31270297 (2026-03-16), predates this task by 10 days."
      - path: ".planning/quick/260326-f71-review-the-current-mvt-rendering-and-dat/260326-f71-FINDINGS.md"
        issue: "Section 'Issues Found but NOT Fixed (No Tile Cache Layer)' is factually incorrect. Cache-Control header on cache hits IS a real current issue (no-cache is set on line 425 of router.py), not a hypothetical for future work."
    missing:
      - "FINDINGS.md must be corrected to reflect that TileCacheProvider exists and is wired"
      - "Deferred Fix A (Cache-Control on cache hits) should be reclassified as an ACTIVE issue — the no-cache header on cache hits at router.py:425 defeats server-side caching benefit for repeated requests"
      - "Deferred Fix B (empty tile caching) should be reclassified as an actual optimization opportunity, not deferred pending a cache layer"
      - "The no-cache on cache hits was intentionally introduced in commit 130b99f1 as a stale-tile fix. FINDINGS.md should document this intentional tradeoff so future implementers understand the history rather than treating it as an omission"
---

# Quick Task 260326-f71: MVT Tile Pipeline Review — Verification Report

**Task Goal:** Review the current MVT rendering, database querying and caching for optimization gaps. Write findings doc AND implement easy-win code changes.
**Verified:** 2026-03-26
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Bounds CTE precomputes geom_4326 once, no duplicate ST_Transform in WHERE | VERIFIED | service.py lines 52-75: CTE adds `ST_Transform(...) AS geom_4326`; WHERE uses `bounds.geom_4326` in both `&&` and `ST_Intersects`. Confirmed in commit diff 9c66c241. |
| 2 | Per-tile logging reduced from INFO to DEBUG | VERIFIED | router.py line 438: `logger.debug("tile_access", ...)`. Commit 9c66c241 changed `logger.info` to `logger.debug`. |
| 3 | FINDINGS.md exists and is substantive | VERIFIED (with caveat) | File exists at 133 lines. Substantive analysis on most topics. Fails on accuracy — see truth #4. |
| 4 | Findings document accurately describes the codebase state (cache layer) | FAILED | FINDINGS.md section "Issues Found but NOT Fixed (No Tile Cache Layer)" is factually wrong. TileCacheProvider has been wired into tile_endpoint since 2026-03-16. |

**Score:** 3/4 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/tiles/service.py` | Bounds CTE optimization | VERIFIED | Lines 52-53 add `geom_4326` to bounds CTE; lines 74-75 use it in WHERE |
| `backend/app/tiles/router.py` | DEBUG logging + cache wiring | VERIFIED | Line 438 is `logger.debug`; lines 416-428 show existing tile cache check |
| `backend/tests/test_tiles.py` | Tests for CTE optimization | VERIFIED | Lines 245-260: `test_tile_query_uses_correct_params` and `test_tile_query_single_transform_in_where` both assert `bounds.geom_4326` and assert absence of `ST_Transform(bounds.geom, 4326)` |
| `260326-f71-FINDINGS.md` | Accurate findings document | PARTIAL | 133 lines exist; architecture overview, strengths, and non-issues are accurate. Cache section is incorrect. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| router.py tile_endpoint | TileCacheProvider | `get_tile_cache()` import | WIRED | Lines 22, 416-428, 452-453 — cache get before PostGIS, cache set after compress |
| TileCacheProvider | Redis | `redis.asyncio` | WIRED | tile_cache.py uses `decode_responses=False` for binary MVT storage |
| tile_endpoint cache hit | Cache-Control header | Response headers | PARTIAL (intentional) | Line 425 returns `"Cache-Control": "no-cache"` on cache hits — intentional design decision from commit 130b99f1 but undocumented in FINDINGS.md |

---

## The Cache Layer: Detailed Findings

### What the executor said

FINDINGS.md states:

> "The plan called for two cache-related fixes, but the current tile endpoint does **not** have a tile-specific cache layer in the request path. The generic `CacheProvider` (Redis/in-memory) exists but uses JSON serialization, which is incompatible with binary MVT bytes."

### What the codebase actually has

`backend/app/cache/tile_cache.py` — full `TileCacheProvider` class created in commit `31270297` (2026-03-16):
- Binary Redis client (`decode_responses=False`)
- `get(table, z, x, y)` returning `bytes | None`
- `set(table, z, x, y, data, ttl)` with configurable TTL
- `invalidate_table(table)` with SCAN cursor loop
- Prometheus hit/miss counters

`backend/app/tiles/router.py` — wired in commit `e53659bd` (2026-03-16):
- `from app.cache.provider import get_tile_cache` (line 22)
- Cache-first check at lines 416-428: calls `tile_cache.get()` before PostGIS
- Cache population at lines 452-453: calls `tile_cache.set()` after gzip

Both files predated this task by 10 days.

### The actual Cache-Control issue

The cache hit path at router.py line 425 returns `"Cache-Control": "no-cache"`. This was deliberately introduced in commit `130b99f1` (2026-03-20) with the message:

> "The browser was serving stale tiles from its HTTP cache (max-age=300) after feature mutations, causing deleted features to reappear on page refresh."

So the current state is:
- **Cache miss**: `Cache-Control: {scope}, max-age={cache_ttl}` (correct)
- **Cache hit**: `Cache-Control: no-cache` (intentional, but conflicts with browser-level caching goal)

This is a real architectural tradeoff that should have been documented in FINDINGS.md. The fix (ETag/Last-Modified or cache_ttl=0 on mutations) is a legitimate medium-effort recommendation, not a "deferred pending cache layer."

### Empty tile caching

The executor's Deferred Fix B ("cache empty tiles") is also a real optimization opportunity. `get_tile()` returning `None` (line 434) returns a 204 without caching, meaning sparse-dataset tiles hit PostGIS on every request. This is actionable now — a sentinel value in `TileCacheProvider` would work.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/app/tiles/router.py` | 425 | `"Cache-Control": "no-cache"` on cache hits | Warning | Server-side Redis cache serves the byte payload but tells browsers not to cache, so all tile requests still hit the API server. The Redis layer still helps (avoids PostGIS), but browser-level caching provides no benefit for repeated map views. Intentional per commit 130b99f1 but not explained in FINDINGS.md. |

---

## Behavioral Spot-Checks

Step 7b: SKIPPED — tile endpoint requires a running PostGIS + Redis stack.

---

## Human Verification Required

None beyond what was already verified programmatically.

---

## Gaps Summary

The two implemented fixes (bounds CTE precomputation, INFO→DEBUG logging) are correct, well-tested, and verified. The test additions are substantive.

The gap is entirely in the findings document. The executor audited `backend/app/cache/provider.py` but either did not open `backend/app/cache/tile_cache.py` or did not trace `get_tile_cache()` to its import in `router.py`. As a result, FINDINGS.md incorrectly documents two active optimization opportunities (Cache-Control on hits, empty tile caching) as deferred pending a cache layer that already exists. The "no-cache on hits" issue is real and currently active; the empty tile caching issue is implementable today.

The findings document also omits the context that `no-cache` on cache hits was an intentional engineering decision to prevent stale-tile bugs — future readers need that history.

**What needs to be corrected in FINDINGS.md:**

1. Remove the "No Tile Cache Layer" premise — it is false.
2. Move "Deferred Fix A" (Cache-Control on hits) to "Issues Found" with the commit 130b99f1 history documented.
3. Move "Deferred Fix B" (empty tile caching) to "Remaining Optimization Opportunities" as an actionable item.
4. Add `backend/app/cache/tile_cache.py` to the Architecture Overview key files list.

---

_Verified: 2026-03-26_
_Verifier: Claude (gsd-verifier)_
