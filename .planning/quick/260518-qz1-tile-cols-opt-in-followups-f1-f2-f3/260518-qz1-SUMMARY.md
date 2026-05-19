---
status: complete
quick_id: 260518-qz1
slug: tile-cols-opt-in-followups-f1-f2-f3
created: 2026-05-18
---

# Quick Task 260518-qz1 — Tile cols= opt-in follow-ups

## Scope

F1 + F2 + F3 from `.planning/todos/pending/2026-05-18-tile-cols-followups.md`. F4 + F5 are documentation-only.

## F1 — Heatmap live verify (z<10) — CONFIRMED

**Method:** Orchestrator-driven Playwright MCP on `http://localhost:8080` against the live stack at z=2.0 (well below the `_DEFAULT_NO_ATTR_BELOW_ZOOM=10` threshold).

**Repro setup:**

- Created a 20-feature MultiPoint dataset `Test Cities (Population)` (`test_cities_population`) via `POST /api/ingest/upload` → `POST /api/ingest/commit/{job_id}` with population values from ~1M to ~32M. The smoke map had no points before this verify; the natural-earth seeder couldn't reach `naturalearthdata.com` from this network, so a hand-rolled GeoJSON of 20 world cities (NY, LA, Tokyo, Delhi, Sao Paulo, etc.) was used instead.
- Added the dataset to `v1010.1 Smoke Map` via the builder UI, then switched Render As from `Point` → `Heatmap` and chose `population` as the weight column via the LayerEditorPanel's "Weight column" combobox.

**Acceptance:**

| Assertion | Result | Evidence |
|-----------|--------|----------|
| (a) Tile URL contains `&cols=<weight_column>` | ✅ PASS | `source-data-test_cities_population` tile URL is `http://localhost:8080/api/tiles/data.test_cities_population/{z}/{x}/{y}.pbf?sig=…&exp=…&scope=test_cities_population&cols=population` — `&cols=population` confirmed. |
| (b) `map.querySourceFeatures(...)` shows weight column populated | ✅ PASS | 10/10 visible features at z=2 have `population` populated (e.g. 12,325,232 / 2,891,082 / 32,226,000). All features within the z=2 viewport carry the attribute through MVT. |
| (c) Heatmap visually reflects intensity variation | ✅ PASS | Screenshot at `.playwright-mcp/f1-heatmap-z2-with-cols-population.png` shows non-uniform density gradients — denser hotspots over Asia (Delhi=32M, Tokyo=14M, Beijing=22M, Istanbul=15M) and over Sao Paulo (12M), faint blobs over smaller US cities. NOT a uniform blob. |

**Implementation surface verified:** The MapLibre live `getStyle()` returns `heatmap-weight: ["get", "population"]` without the `_heatmap-weight-column` marker (MapLibre validates and strips underscore-prefixed custom paint keys at runtime). The `&cols=population` suffix being present in the tile URL proves that `getDataDrivenColumnsForLayer` (`frontend/src/components/builder/map-sync.ts:428`) is correctly walking the `["get", X]` expression-tree path — exactly the "marker-absent fallback" scenario covered by Task 2's new vitest at `frontend/src/components/builder/__tests__/map-sync.heatmap-cols.test.ts`. The persisted store on the React side retains the marker; only MapLibre's validated live style strips it.

**No bug opened.** F1 acceptance ("confirmed live OR bug opened") satisfied by CONFIRMED.

## F2 — Backend integration tests for ?cols= flow

Two new backend test files created and green (6 tests total, 0 failures).

**Files created:**

- `backend/tests/test_tile_cols_endpoint.py` — 4 integration tests:
  - `test_tile_endpoint_with_cols_param_projects_column_at_low_zoom`: GET ?cols=value at z=2 returns 200 with non-empty MVT; confirms both with-cols and without-cols paths succeed
  - `test_tile_endpoint_cols_silently_drops_invalid_names`: ?cols=does_not_exist returns 200 (silent-drop contract)
  - `test_tile_endpoint_cols_silently_drops_sql_injection_attempt`: ?cols=drop+table+users;-- returns 200 (regex validator drops injection before SQL)
  - `test_tile_endpoint_cols_normalizes_permutations`: ?cols=value,name and ?cols=name,value both return 200 with non-empty MVT

- `backend/tests/test_tile_cache_cols_key.py` — 2 integration tests:
  - `test_tile_cache_key_includes_cols_suffix_isolates_projections`: mock cache confirms tile_cache.get/set called with cols_key="value" when ?cols=value
  - `test_tile_cache_key_omits_suffix_when_cols_absent_or_empty`: no-cols and empty-cols both call tile_cache.get with cols_key="" (backward-compatible key shape)

**Pytest output:** 6 passed in 6.55s

**Invocation note:** Tests require `POSTGRES_PORT=5434` to reach the Docker DB (local Postgres on port 5432 lacks pgvector, so `_test_db_lifecycle` silently falls through). The full command is:
```
cd backend && POSTGRES_HOST=localhost POSTGRES_PORT=5434 uv run pytest tests/test_tile_cols_endpoint.py tests/test_tile_cache_cols_key.py -xvs
```
This matches the pattern in the project Makefile (`make manifest-contract-check` uses `POSTGRES_PORT=5434`). MVT decode is intentionally out of scope (would require `mapbox-vector-tile` dev dep); correctness of `_select_tile_columns(additional_columns=...)` is already covered by `test_tile_column_allowlist.py`.

**Fixture sharing:** Both files use `pytest_plugins = ["tests.test_tiles"]` to expose `_init_tile_pool_for_tests` without duplicating the fixture body (per plan instructions).

## F3 — Viewer live verify (auth + embed at z<10) — CONFIRMED (both surfaces)

**Method:** Orchestrator-driven Playwright MCP at z=2.12 on two distinct viewer surfaces of `v1010.1 Smoke Map` (Admin 0 Countries layer, categorical `economy` paint — note: the todo mentioned `pop_est` graduated, but the smoke map actually carries categorical `economy`; both flow through the same `getDataDrivenColumnsForLayer` code path).

**Setup:** Made the map public via `PUT /api/maps/{id}` (`visibility=public`), then created a share token (`POST /api/maps/{id}/share/`) and an embed token (`POST /api/maps/{id}/embed-tokens/`). Both reverted/deleted after verification (see Cleanup below).

### F3a — Public share viewer (`/m/<token>`)

| Assertion | Result | Evidence |
|-----------|--------|----------|
| (a) Data-driven colors render correctly (NOT uniform gray) | ✅ PASS | Screenshot `.playwright-mcp/f3-public-share-viewer-z2-categorical.png` — 8-way categorical bands visible across G7 (red), nonG7 (blue), BRIC (green), MIKT (peach), G20 (yellow), Developing (brown), Least developed (pink). |
| (b) Tile URL includes `&cols=economy` | ✅ PASS | `viewer-source-data-admin_0_countries_10m_2` tile URL is `…?sig=475337a3…&exp=1779148800&scope=admin_0_countries_10m_2&cols=economy`. |
| (c) `querySourceFeatures` shows attr populated | ✅ PASS | 299/299 features at z=2 have `economy` populated (sampled: "4. Emerging region: MIKT", "7. Least developed region", "2. Developed region: nonG7"). |

### F3b — Embed-token viewer (`/maps/{id}?embed=1&token=...`)

| Assertion | Result | Evidence |
|-----------|--------|----------|
| (a) Data-driven colors render correctly | ✅ PASS | Screenshot `.playwright-mcp/f3-embed-token-viewer-z2-categorical.png` — identical 8-way categorical render as F3a. |
| (b) Tile URL includes `&cols=economy` | ✅ PASS | Same tile URL shape as F3a; identical sig/scope; `&cols=economy` present. |
| (c) `querySourceFeatures` shows attr populated | ✅ PASS | 299/299 features have `economy`. |

**Token-refresh path (c) deferred:** Not exercised live — would require waiting ~1hr for natural token expiry or force-expiring via dev tools. The `setTiles` refresh code path at `frontend/src/components/viewer/ViewerMap.tsx:632-643` is already covered by code review and Phase 1050 SF-04..08 sweep. Acceptance criterion ("CONFIRMED for both flavors, token-refresh best-effort") satisfied without live token-refresh exercise.

**No bug opened.** F3 acceptance ("confirmed live OR bug opened") satisfied by CONFIRMED on both viewer flavors.

## Supporting frontend tests (Task 2)

Two frontend test files updated, 22 tests total (all pass).

**New file:** `frontend/src/components/builder/__tests__/map-sync.heatmap-cols.test.ts`
- 4 tests covering the full HeatmapStyleControls write shape for `getDataDrivenColumnsForLayer`:
  - Full write shape: both `_heatmap-weight-column` marker + `heatmap-weight: ['get', col]` expression → single deduped entry
  - Marker-absent fallback: only `['get', col]` expression → column extracted via walk()
  - Expression-absent fallback: only marker, `heatmap-weight: 1` default → column extracted via marker
  - Mismatch case: marker ≠ expression → both fed into Set (union semantics)

**Extended file:** `frontend/src/lib/__tests__/tile-utils.test.ts`
- 3 new tests in `describe('buildSignedTileUrl extraCols edge cases', ...)` block, NOT duplicating existing lines 54-79:
  - Whitespace-only entry filter: `['   ']` → URL has no `cols=`
  - Falsy-entry filter: `[undefined, null]` inside non-empty array → URL has no `cols=`
  - Exact %2C URL-encoding: `['col_a', 'col_b']` → URL contains `cols=col_a%2Ccol_b`

**vitest output:** 2 files passed, 22 tests passed

The F1 marker-absent fallback test corresponds 1:1 to the live behavior observed during MCP verification (MapLibre stripped the `_heatmap-weight-column` marker from the runtime style, and the extractor still produced `&cols=population` by walking the `["get", X]` expression-tree path).

## F4 — Three buildSignedTileUrl callers not migrated

DOCUMENTATION-ONLY. The todo file's F4 table captures the three unmigrated callers (`use-map-layers.ts:55,234`, `use-feature-editing.ts:88`, `use-builder-layers.ts:878`). No code action this run. Revisit when adding data-driven styling outside builder/viewer.

## F5 — Stale client-cached signed tile URLs

DOCUMENTATION-ONLY. Self-heals on next token refresh per Phase 1050 `setTiles` refresh. No code action.

## Cleanup performed (post-verify)

- Deleted F3 share token (`DELETE /api/maps/{id}/share/` → 204)
- Deleted F3 embed token (`DELETE /api/maps/{id}/embed-tokens/{token_id}/` → 200)
- Reverted smoke map visibility to `private` (`PUT /api/maps/{id}` → 200)
- Deleted F1 `Test Cities (Population)` dataset (`DELETE /api/datasets/{id}` with `confirm_title` body → 204)
- Heatmap layer changes were never saved (Save button remained at "Unsaved changes"); persisted smoke map layer count confirmed at 2 (Reefs + Admin 0 Countries) post-cleanup. **No drift from v1010.1 baseline.**

## Commits

- `46d11f7b` — `test(260518-qz1): F2 backend integration tests for ?cols= endpoint + cache key`
- `911061d1` — `test(260518-qz1): F1+F2 supporting frontend tests — heatmap shape + extraCols edge cases`

## Acceptance

- [x] F1: CONFIRMED live (tile URL `&cols=population`, 10/10 features carry attribute, heatmap intensity gradient visible at z=2)
- [x] F2: backend integration tests created and green (6/6)
- [x] F2 supporting + F1 supporting: frontend unit tests created and green (22/22)
- [x] F3: CONFIRMED on both viewer flavors (public share `/m/<token>` and embed `/maps/{id}?embed=1&token=...`); `&cols=economy` present, 299/299 features carry attribute, categorical bands visible at z=2.12. Token-refresh path deferred as best-effort per todo F3 wording.
- [x] F4: documentation-only, captured in todo file (no action this run)
- [x] F5: documentation-only, self-healing behavior (no action this run)

All five todo items closed. The pending todo `.planning/todos/pending/2026-05-18-tile-cols-followups.md` can be moved to `.planning/todos/done/` as part of the final commit.
