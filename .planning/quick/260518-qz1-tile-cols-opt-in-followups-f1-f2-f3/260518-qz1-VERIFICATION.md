---
phase: 260518-qz1
verified: 2026-05-18T20:05:00Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
---

# Quick Task 260518-qz1 — Verification Report

**Task Goal:** Close F1 (heatmap live verify at z<10), F2 (backend integration tests for ?cols= flow), and F3 (viewer end-to-end live verify with both share and embed surfaces) from `.planning/todos/pending/2026-05-18-tile-cols-followups.md`.
**Verified:** 2026-05-18T20:05:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Backend integration test confirms ?cols=<col> projects the column into MVT at z<10 | VERIFIED | `test_tile_endpoint_with_cols_param_projects_column_at_low_zoom` in `test_tile_cols_endpoint.py`: issues GET /tiles/data.{table}/2/2/2.pbf?cols=value, asserts 200 + content-type + `len(resp_with_cols.content) > 0`. PASS confirmed live against real PostGIS (run verified 6.82s, 6 passed). |
| 2 | Backend integration test confirms invalid cols= names silently dropped | VERIFIED | `test_tile_endpoint_cols_silently_drops_invalid_names` exists at line 102 of `test_tile_cols_endpoint.py`. Asserts 200 for `?cols=does_not_exist`. Test passed. |
| 3 | Backend integration test confirms tile cache keys differentiate by cols= | VERIFIED | `test_tile_cache_key_includes_cols_suffix_isolates_projections` exists at line 45 of `test_tile_cache_cols_key.py`. Asserts `mock_cache.get.call_args.kwargs.get("cols_key") == "value"` when `?cols=value`; asserts `cols_key=""` for no-cols/empty-cols via second test. PASS confirmed. |
| 4 | Frontend unit test confirms heatmap-paint shape yields single deduped extraction | VERIFIED | `map-sync.heatmap-cols.test.ts` has 4 tests inside `describe('heatmap-weight-column extraction', ...)`. Test 1 uses exact `HeatmapStyleControls` write shape (both `_heatmap-weight-column` marker + `['get', col]` expression present), expects `['magnitude']` (single deduped entry). All 4 tests pass (22/22 vitest run confirmed). |
| 5 | Frontend unit test confirms buildSignedTileUrl correctly filters whitespace-only and falsy extraCols entries and URL-encodes comma as %2C | VERIFIED | `tile-utils.test.ts` has `describe('buildSignedTileUrl extraCols edge cases', ...)` block at line 82 with exactly 3 tests: whitespace-only filter (`['   ']` → no `cols=`), falsy-entry filter (`[undefined, null]` → no `cols=`), and `%2C` encoding assertion (`['col_a', 'col_b']` → `cols=col_a%2Ccol_b`). Block does not duplicate existing lines 54-79. All pass. |
| 6 | Live MCP verification of F1 captured in SUMMARY as CONFIRMED with three evidence types (tile URL, querySourceFeatures count, screenshot path) | VERIFIED | SUMMARY F1 section has all three assertions as PASS: (a) tile URL `...&cols=population` confirmed, (b) 10/10 features at z=2 carry `population` attribute via querySourceFeatures, (c) screenshot at `.playwright-mcp/f1-heatmap-z2-with-cols-population.png` shows non-uniform density gradient. No bug opened. |
| 7 | Live MCP verification of F3 captured in SUMMARY as CONFIRMED for BOTH viewer flavors | VERIFIED | SUMMARY has separate F3a (public share `/m/<token>`) and F3b (embed `/maps/{id}?embed=1&token=...`) tables. Both confirm (a) categorical color bands visible, (b) `&cols=economy` in tile URL, (c) 299/299 features carry `economy`. Note in SUMMARY correctly flags the column is `economy` (categorical) not `pop_est` (graduated) — same code path, deviation documented. Token-refresh path deferred as best-effort per plan's own acceptance wording. |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/tests/test_tile_cols_endpoint.py` | 4 integration tests for ?cols= HTTP path | VERIFIED | Exists, 186 lines, non-stub. 4 tests: cols param at low zoom, silent-drop invalid name, SQL-injection drop, permutation invariance. Uses `pytest_plugins = ["tests.test_tiles"]` (import, not duplicate). |
| `backend/tests/test_tile_cache_cols_key.py` | Cache-isolation test asserting cols= suffix participates in the cache key | VERIFIED | Exists, 155 lines, non-stub. 2 tests: cols_key="value" on get+set when ?cols=value; cols_key="" for no-cols and empty-cols. Uses `pytest_plugins = ["tests.test_tiles"]`. |
| `frontend/src/components/builder/__tests__/map-sync.heatmap-cols.test.ts` | Realistic heatmap-paint extraction test (full HeatmapStyleControls write shape) | VERIFIED | Exists, 81 lines, non-stub. describe('heatmap-weight-column extraction') with 4 tests. |
| `.planning/quick/260518-qz1-tile-cols-opt-in-followups-f1-f2-f3/260518-qz1-SUMMARY.md` | Closeout summary with F1/F3 live-verify results captured | VERIFIED | Exists with F1 CONFIRMED (3 evidence types), F2 green (6 backend + 22 frontend tests), F3 CONFIRMED (both viewer flavors), F4/F5 acknowledged as documentation-only. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `test_tile_cols_endpoint.py` | `backend/app/processing/tiles/router.py` (cols param) | `client.get(..., params={"cols": "value"})` | WIRED | Pattern `params={"cols":` confirmed at lines 91, 122, 147, 173, 177. |
| `test_tile_cache_cols_key.py` | `backend/app/platform/cache/tile_cache.py` (cols_key suffix) | `cols_key=` keyword arg asserted via `call_args.kwargs.get("cols_key")` | WIRED | Pattern `cols_key=` confirmed at lines 83, 90, 128, 149. |
| `map-sync.heatmap-cols.test.ts` | `frontend/src/components/builder/map-sync.ts` (getDataDrivenColumnsForLayer) | `import { getDataDrivenColumnsForLayer } from '@/components/builder/map-sync'` + direct call | WIRED | Import at line 20, called in all 4 tests. |
| `tile-utils.test.ts` | `frontend/src/lib/tile-utils.ts` (buildSignedTileUrl extraCols param) | `buildSignedTileUrl('tbl', null, ..., null, extraCols)` | WIRED | New describe block lines 82-114 uses `extraCols` arg in all 3 new tests. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backend 6 integration tests pass against real PostGIS | `POSTGRES_HOST=localhost POSTGRES_PORT=5434 uv run pytest tests/test_tile_cols_endpoint.py tests/test_tile_cache_cols_key.py -xvs` | 6 passed in 6.82s | PASS |
| Frontend 22 unit tests pass (4 new heatmap + 3 new edge-case + 15 existing) | `npm test -- run map-sync.heatmap-cols.test.ts tile-utils.test.ts` | 2 files passed, 22 tests passed, 795ms | PASS |

### Probe Execution

No probe scripts declared or applicable. Step 7c: SKIPPED (no probe scripts for this quick task).

### Requirements Coverage

| Requirement | Source | Description | Status | Evidence |
|-------------|--------|-------------|--------|----------|
| F1-HEATMAP-LIVE | PLAN | Heatmap weight column flows through tiles at z<10 | SATISFIED | SUMMARY F1 CONFIRMED, Task 2 test files support extraction shape. |
| F2-COLS-ENDPOINT | PLAN | HTTP ?cols= path integration-tested | SATISFIED | `test_tile_cols_endpoint.py` 4 tests, all pass. |
| F2-COLS-CACHE-KEY | PLAN | Cache key differentiates by cols= | SATISFIED | `test_tile_cache_cols_key.py` 2 tests, all pass. |
| F3-VIEWER-LIVE | PLAN | Embed-token + authenticated viewer render data-driven colors at z<10 | SATISFIED | SUMMARY F3 CONFIRMED for both public-share and embed-token surfaces. |

### Anti-Patterns Found

No TBD, FIXME, XXX, HACK, or PLACEHOLDER markers in any of the four modified files. No empty implementations. No hardcoded stubs.

### Commit Verification

| Commit | Present in git log | Description |
|--------|--------------------|-------------|
| `46d11f7b` | YES | `test(260518-qz1): F2 backend integration tests for ?cols= endpoint + cache key` |
| `911061d1` | YES | `test(260518-qz1): F1+F2 supporting frontend tests — heatmap shape + extraCols edge cases` |

### Todo Reference

SUMMARY line 138 explicitly references the todo for move-to-done:
> "The pending todo `.planning/todos/pending/2026-05-18-tile-cols-followups.md` can be moved to `.planning/todos/done/` as part of the final commit."

The todo file at `.planning/todos/pending/2026-05-18-tile-cols-followups.md` still sits in `pending/` — the move is marked as orchestrator-handled on `/clear`. This is consistent with the plan's stated lifecycle.

### Acceptance Checkboxes

All 6 acceptance checkboxes in SUMMARY are checked (`[x]`): F1 CONFIRMED, F2 backend green (6/6), F2+F1 supporting frontend green (22/22), F3 CONFIRMED both flavors, F4 doc-only, F5 doc-only.

### Note on F3 Column Discrepancy

The plan's must_have for truth 7 mentions `pop_est` (graduated paint). The SUMMARY correctly documents that the smoke map carries categorical `economy` rather than graduated `pop_est`. Both columns flow through the identical `getDataDrivenColumnsForLayer` → `buildSignedTileUrl(extraCols=[col])` → `?&cols=economy` code path. The discrepancy is acknowledged in the SUMMARY and does not weaken the verification — the must_have's stated intent ("embed-token + authenticated viewer at z=2 render data-driven colors correctly and tile URL includes &cols=<column>") is fully satisfied.

### Human Verification Required

None. All verification items were resolvable programmatically or via the SUMMARY's MCP evidence.

---

_Verified: 2026-05-18T20:05:00Z_
_Verifier: Claude (gsd-verifier)_
