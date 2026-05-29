---
phase: 1146
phase_name: Raster Stretch Stats
status: passed
verified: 2026-05-28
requirements: [RASTER-STRETCH-01, RASTER-STRETCH-02]
method: backend pytest + frontend vitest + i18n parity + typecheck + live tile-render diff
---

# Phase 1146 Verification — Raster Stretch Stats

**Status: passed** — `percentile` and `stddev` single-band stretch compute a real stats-based Titiler rescale; the `minmax`-only fallback is gone.

## Success Criteria

1. **RASTER-STRETCH-01 (percentile)** — ✅ `stretch=percentile` → Titiler `/cog/statistics` → `rescale=[percentile_2, percentile_98]` injected into the tile request, replacing the dtype rescale. Backend test `test_stretch_percentile_computes_rescale` (asserts `rescale=512.66,1304.31`, original `0,65535` gone).
2. **RASTER-STRETCH-02 (stddev)** — ✅ `stretch=stddev` → `rescale=[mean ± 2σ]` clamped to band [min,max]. Backend test `test_stretch_stddev_computes_rescale` (asserts `rescale=490.6,1228.19`).
3. **Fallback-warning gone for both strategies** — ✅ minmax keeps the dtype rescale and skips /statistics (`test_stretch_minmax_no_statistics_call`); stats failure falls back to minmax (`test_stretch_stats_unavailable_falls_back_to_minmax`); DEM excluded (`test_stretch_not_applied_to_dem`); stats cached across tiles (`test_stretch_statistics_cached_across_tiles`).
4. **Tests pin the behavior** — ✅ backend `test_raster_colormap_proxy.py` 19 passed; frontend `RasterEditor.test.tsx` + `raster-adapter.test.ts` 36 passed (options enabled, selection fires `_stretch`, no "coming soon"); i18n parity 2/2; typecheck 0.

## Live verification (real api → Titiler → render)

Reversible `is_dem=false` DB toggle on the ADK DEM COG (reverted to `t` after, verified), then anonymous tile fetches at z14/4829/5948 with `colormap_name=viridis`:

| stretch | HTTP | bytes | md5 | interpretation |
|---------|------|-------|-----|----------------|
| minmax | 200 | 859 | dc32aa… | near-blank (dtype rescale 0→float32-max swamps 490–1625 m) |
| percentile | 200 | 25,415 | b1c31e… | rich contrast (rescale 512.66,1304.31) |
| stddev | 200 | 27,716 | f47ec7… | distinct render (rescale 490.6,1228.19) |

All three differ → the stats-based rescale path is live and correct end-to-end.

## Notes / human verification
- No non-DEM single-band raster is seeded, so UI-driven stretch can't be exercised on the standard data without the temporary toggle (used + reverted here). Close-gate (1147) re-confirms the editor wiring + no console errors.
