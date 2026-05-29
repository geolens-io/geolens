---
status: passed
phase: "1150"
verified_at: "2026-05-29"
---

# Phase 1150 Verification

## Summary

All three plans executed, committed, and verified. All automated checks pass.

## Plan Map

### POLISH-01: Remove redundant point render-as dropdown

| Criterion | Evidence | Status |
|-----------|----------|--------|
| Point editor has exactly one "Render as" control | POLISH-01 test in LayerStyleEditor.test.tsx: `queryAllByText(/render as/i)` → 0 | PASS |
| No `<Select>` combobox inside LayerStyleEditor | No Select imports/JSX in LayerStyleEditor.tsx | PASS |
| onRenderModeChange removed from LayerStyleEditorProps | `git grep 'onRenderModeChange' LayerStyleEditor.tsx` → 0 | PASS |
| Segmented pill path (handleRenderAsClick) untouched | LayerEditorPanel.tsx segmented control code unchanged | PASS |
| TypeScript clean | `npm run typecheck` → exit 0 | PASS |
| All tests pass | 52/52 in LayerStyleEditor.test.tsx | PASS |

**Live verification:** deferred-to-1151 (point editor single control on a real map)

### POLISH-02: DEM hillshade dual-consumer guard

| Criterion | Evidence | Status |
|-----------|----------|--------|
| isHillshadeTerrainBound exported | `git grep 'export function isHillshadeTerrainBound'` → 1 line | PASS |
| Predicate returns true only for terrain-bound DEM | Tests A-D + variants: 8 predicate tests pass | PASS |
| Map B (terrain disabled) unaffected | Test B: enabled=false → false; syncRasterLayer normal path runs (Test F) | PASS |
| Hillshade skip fires when predicate true | Test E: addSource not called when terrain bound + hillshade mode | PASS |
| DEMEditorScene note renders when hillshade+isTerrainBound=true | DEMEditorScene POLISH-02 test: `getByRole('note')` present | PASS |
| Note absent when Map B / terrain mode / image mode | 4 negative-case tests pass | PASS |
| 4-locale i18n parity | `grep -c 'hillshadeTerrainNote' {en,de,es,fr}/builder.json` → 1 each | PASS |
| test:i18n passes | 2/2 pass | PASS |
| TypeScript clean | `npm run typecheck` → exit 0 | PASS |
| All tests pass | 72/72 across map-sync.raster.test.ts + DEMEditorScene.test.tsx | PASS |

**Live verification:** deferred-to-1151 (Map A terrain still attaches without hillshade-mismatch spam)

### HYG-01: Bound _band_stats_cache

| Criterion | Evidence | Status |
|-----------|----------|--------|
| LRUCache(maxsize=256) in use | `isinstance(_band_stats_cache, LRUCache)` → True; maxsize=256 | PASS |
| dict annotation removed | `grep -c '_band_stats_cache: dict'` → 0 | PASS |
| Eviction at 257th entry | test_band_stats_cache_eviction: PASSED | PASS |
| Cache-hit deduplication | test_band_stats_cache_hit: mock_get.call_count==1 PASSED | PASS |
| Negative caching (None) preserved | test_band_stats_cache_negative: None returned+cached PASSED | PASS |
| No API/schema change | Backend-only change; no OpenAPI diff | PASS |

## Verification Numbers

```
POLISH-01 + POLISH-02 frontend:
  npm run typecheck → exit 0 (0 errors)
  npm run lint → 1 pre-existing warning (not new), 0 errors
  npm run test (LayerStyleEditor + map-sync.raster + DEMEditorScene) → 124/124 pass
  npm run test:i18n → 2/2 pass

HYG-01 backend:
  uv run pytest tests/test_raster_tiles.py -k "band_stats" -v
    test_band_stats_cache_eviction PASSED
    test_band_stats_cache_hit PASSED
    test_band_stats_cache_negative PASSED
    3 passed in 1.89s
```

## Commits

| Plan | Commit | Description |
|------|--------|-------------|
| POLISH-01 | f9257606 | refactor(1150): remove redundant point render-as dropdown |
| POLISH-02 | 65b35fd4 | feat(1150): DEM hillshade dual-consumer guard + advisory note |
| HYG-01 | 5a34cd4d | fix(1150): bound _band_stats_cache with LRUCache(maxsize=256) |

## Deferred Items (deferred-to-1151)

These items cannot be verified without a live running stack and are deferred to the Phase 1151 orchestrator MCP close-gate:

- **POLISH-01**: Point layer Style tab shows exactly one "Render as" section (pill row only, no dropdown)
- **POLISH-02**: Map A with terrain ON + same DEM as hillshade — no `backfillBorder` error spam in console
- **POLISH-02**: Map B (terrain OFF) hillshade path runs normally — raster-dem source is created, hillshade renders
- **HYG-01**: Raster tiles still render correctly end-to-end
