---
created: 2026-05-18T23:15:00.000Z
title: Tile cols= opt-in follow-ups (data-driven styling at low zooms)
area: tiles
files:
  - backend/app/processing/tiles/router.py
  - backend/app/processing/tiles/service.py
  - backend/app/platform/cache/tile_cache.py
  - backend/tests/test_tiles.py
  - backend/tests/test_tile_column_allowlist.py
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/viewer/ViewerMap.tsx
  - frontend/src/lib/tile-utils.ts
  - frontend/src/components/maps/hooks/use-map-layers.ts
  - frontend/src/components/dataset/hooks/use-feature-editing.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
related_commit: c8c9d08f
related_memory: project_tile_cols_optin.md
---

## Context

`c8c9d08f` (2026-05-18) fixed the silent regression where Phase 269 H-23's `_DEFAULT_NO_ATTR_BELOW_ZOOM=10` stripped every attribute column at z<10, causing categorical/graduated/heatmap-weight/3D-extrusion paint to fall to default gray at zoomed-out views. The fix is a runtime `?cols=col1,col2` opt-in on the tile endpoint; frontend extracts data-driven columns from each layer's style_config + paint and unions across all layers sharing a source.

Verified live at z=2 for **categorical** (`economy` column on Admin 0 Countries) and **graduated** (`pop_est`). Three other paint paths that the helper supports were NOT exercised end-to-end and need a smoke pass to confirm.

## Follow-ups

### F1 — Heatmap pipeline unverified live  (P1 — most likely to surface gaps)

The column extractor reads `paint['_heatmap-weight-column']` (frontend/src/components/builder/map-sync.ts) and unit-tests cover it, but no MCP run confirms an actual heatmap layer at z<10 carries its weight column through tiles.

**Repro:** Add a point dataset to a map (the smoke map only has polygons + lines right now). Switch the layer's Render As to `heatmap`. Configure a numeric weight column. Confirm at z=2 that:
1. The tile URL contains `&cols=<weight_column>`
2. `map.querySourceFeatures(...)` shows that column populated on features
3. The heatmap visually reflects intensity variation (not a uniform blob)

If broken, the most likely cause is that the heatmap adapter sets the paint in a code path that runs BEFORE our col extractor sees the source-layer link, or that `_heatmap-weight-column` is stored under a different key in the persisted paint shape.

### F2 — Backend integration test for ?cols= flow  (P2)

Unit tests in `backend/tests/test_tile_column_allowlist.py` cover `_select_tile_columns` directly with `additional_columns`. The HTTP path is uncovered: query-param parsing, validation against `dataset.column_info`, cache-key suffix behavior. The router-level tests in `backend/tests/test_tiles.py` (`TestTileEndpoint`) all currently error out on a missing test database (`asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_..." does not exist`), so the integration layer is untested for any tile code path.

**To do:**
1. Get `test_tiles.py` running against a real test DB (the existing fixtures use real PostGIS — needs the test DB created via `createdb geolens_test_XYZ` or the conftest fixture wired up).
2. Add `test_tile_endpoint_with_cols_param` that POSTs a tile request with `?cols=economy`, decodes the resulting MVT, and asserts the `economy` property is present on feature properties. Verify with z<10 (so the default budget would have stripped it).
3. Add `test_tile_endpoint_cols_validates_against_column_info` to confirm `cols=does_not_exist` is silently dropped.
4. Add `test_tile_cache_key_includes_cols_suffix` to confirm two requests with different `cols` don't collide.

### F3 — Viewer context end-to-end verification  (P2)

`ViewerMap.tsx` got the fix via both paths (token-refresh loop calls `getDataDrivenColumnsForLayer`, and the initial-add path goes through `syncLayersToMap` which uses the source-union helper). Only the **builder** was verified live.

**Repro:** Publish or share-link the smoke map (currently has Admin 0 Countries with graduated `pop_est`). Open the resulting `/m/<slug>` or `/maps/<id>?embed=1` viewer URL at z=2. Confirm:
1. Categorical/graduated colors render correctly (not uniform gray)
2. The tile URL on the source includes `&cols=pop_est`
3. Token refresh (wait ~1hr or force-expire via dev tools) keeps the cols param

Most likely-broken case: an embed-token viewer where the shape of `layer.paint` differs from the builder's `MapLayerResponse` shape. Verify with both an authenticated viewer AND an embed-token viewer.

### F4 — Three `buildSignedTileUrl` callers deliberately not updated  (P3 — document only)

The fix patched the builder's tile-URL flow (`map-sync.ts:syncVectorLayer`, `BuilderMap.tsx` token refresh) and the viewer's flow (`ViewerMap.tsx` token refresh). Three other callers were NOT updated:

| File | Line | Reason skipped |
|------|------|----------------|
| `frontend/src/components/maps/hooks/use-map-layers.ts` | 55, 234 | Dataset detail page uses uniform paint (no data-driven). |
| `frontend/src/components/dataset/hooks/use-feature-editing.ts` | 88 | Feature editing flow uses uniform paint. |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | 878 | Fallback path only triggered when source missing; `syncLayersToMap` refreshes next render with cols. |

**Action:** If a future feature adds data-driven styling to dataset-detail (e.g. an inline preview with categorical mode) or to the feature-editing canvas, those callers must be migrated to pass `extraCols` — otherwise they'll silently regress to gray at z<10. The helper `getDataDrivenColumnsForLayer` is the right entry point.

### F5 — Stale client-cached signed tile URLs  (P3 — operational note)

Anyone with a stale signed tile URL cached in MapLibre's source state (e.g. a long-lived tab opened pre-fix) will continue requesting tiles without `&cols=...` until they hard-reload. No code fix — just a note for any user-facing release announcement: "if you see uniform gray fills on data-driven layers, reload the page."

The Phase 1050 `setTiles` refresh on token expiry will pick up cols once the token next rotates (~1hr session), so this self-heals over time.

## Acceptance

This todo is complete when:

- [ ] F1: heatmap render at z<10 is confirmed live (or a bug is opened with the failure shape)
- [ ] F2: at least one `test_tiles.py` integration test exercises `?cols=` end-to-end (gated on the test-DB story being unblocked)
- [ ] F3: viewer context with embed token confirmed correct (or a bug is opened)
- [ ] F4: this section stays in the codebase as documentation; revisit when adding data-driven styling outside the builder/viewer
- [ ] F5: optional release-notes mention; otherwise self-heals

## Related

- Commit: `c8c9d08f fix(tiles): data-driven styling renders at all zooms via ?cols= opt-in`
- Memory: `project_tile_cols_optin.md` — the contract + why `cols` is intentionally unsigned
- Phase 269 H-23 — original `_DEFAULT_NO_ATTR_BELOW_ZOOM` introduction
