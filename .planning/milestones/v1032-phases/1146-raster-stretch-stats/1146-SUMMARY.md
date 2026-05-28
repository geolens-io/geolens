---
phase: 1146
phase_name: Raster Stretch Stats
status: complete
requirements: [RASTER-STRETCH-01, RASTER-STRETCH-02]
completed: 2026-05-28
---

# Phase 1146 Summary — Raster Stretch Stats

Implemented single-band `percentile` and `stddev` raster stretch, replacing the `minmax`-only fallback.

## Backend (`tiles/router.py`)
- `_fetch_band_statistics(open_path)` — calls Titiler `/cog/statistics`, parses per-band stats, caches by open_path (`_band_stats_cache`).
- `_compute_stretch_rescale(bands, stretch, n_bands)` — percentile → [p2,p98]; stddev → [mean±2σ] clamped to [min,max]; rounded 4 dp.
- `_apply_stretch_rescale(render_params, parts)` — replaces the dtype `rescale=` with the stats-based one.
- Wired into `raster_tile_proxy`: stretch≠minmax and non-DEM → compute + inject; falls back to minmax + warning when stats unavailable.

## Frontend
- `RasterEditor.tsx` — un-gated the `percentile`/`stddev` options (removed `disabled` + "coming soon" suffix). Plumbing (`buildColormapTileUrl` forwards `stretch=`) already existed.
- Removed the now-unused `stretchComingSoon` i18n key from en/de/es/fr.

## Verification
- backend `test_raster_colormap_proxy.py` 19 passed (rescale math, fallback, DEM-exclusion, caching).
- frontend RasterEditor + raster-adapter 36 passed; i18n parity 2/2; typecheck 0.
- **Live**: reversible `is_dem=false` toggle → minmax (859 B) vs percentile (25 KB) vs stddev (27 KB) tiles all differ; is_dem reverted.

## Scope notes
Single-band only (RASTER-STRETCH-03 multi-band + RASTER-STRETCH-UI-01 configurable bounds are Future). No migration — stats computed at request time via Titiler + cached.
