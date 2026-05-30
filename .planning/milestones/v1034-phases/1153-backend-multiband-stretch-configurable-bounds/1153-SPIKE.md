# Phase 1153 — SPIKE-01 Findings: Titiler `p=` Percentile Support

**Run:** 2026-05-29 (orchestrator, live Titiler container `http://titiler:8000`)
**Question:** Does the running Titiler support arbitrary percentile params (`?p=<float>&p=<float>`) on `/cog/statistics` and return `percentile_<N>` keys? This gates whether RASTER-STRETCH-UI-01 (configurable bounds) is a simple param+cache-key change or needs a different approach.

## Result: ✅ SUPPORTED — simple path confirmed

Tested against the seeded single-band uint8 fixture (`GRAY_50M_SR.tif`, open_path `/app/staging/rasters/4767.../source.cog.tif`):

| Request | `percentile_*` keys returned |
|---------|------------------------------|
| `/cog/statistics?url=<cog>` (default) | `percentile_2`, `percentile_98` |
| `/cog/statistics?url=<cog>&p=5&p=95` | `percentile_5`, `percentile_95` |

Titiler honors arbitrary repeated `p=` params and returns the matching `percentile_<N>` keys. **No alternative approach needed** — configurable percentile bounds = forward `p=pmin&p=pmax` to `/cog/statistics`, read `percentile_<pmin>`/`percentile_<pmax>` from the response, and extend the stats cache key to include the bounds.

## Multi-band stats shape confirmed (de-risks RASTER-STRETCH-03)

Tested against the 3-band uint8 RGB ortho (`adk_high_peaks_ny_orthos_3857.tif`):

```
band keys: ['b1', 'b2', 'b3']
b1 p2=63.0 p98=164.0 mean=101.9 std=27.7
b2 p2=76.0 p98=155.0 mean=106.2 std=21.1
b3 p2=81.0 p98=148.0 mean=106.4 std=18.2
```

Each band returns distinct `percentile_*`/`mean`/`std` under `b1`/`b2`/`b3` keys (NOT integer `1`/`2`/`3` keys). The existing `_fetch_band_statistics` sort-by-`int(k[1:])` logic is correct for this `"b"+int` format. Per-band stretch will produce 3 distinct `rescale=lo,hi` fragments.

## Implications for planning

1. **RASTER-STRETCH-UI-01 (configurable bounds)** — simple path:
   - Thread `pmin`/`pmax` (percentile) and `sigma` (stddev multiplier) query params into `raster_tile_proxy` → `_fetch_band_statistics` (forward as repeated `p=`) → `_compute_stretch_rescale`.
   - **CRITICAL**: change the `_band_stats_cache` key from `open_path` (str) to include the bounds, e.g. `(open_path, pmin, pmax)`. Without this, different bounds serve stale cached stats → silent no-op.
   - Read `percentile_<pmin>`/`percentile_<pmax>` dynamically (key name depends on the requested value) rather than hardcoded `percentile_2`/`percentile_98`.
   - Validate bounds: `pmin < pmax`, `0 <= pmin`, `pmax <= 100`, `sigma > 0` → HTTP 422 on violation.

2. **RASTER-STRETCH-03 (multi-band)** — one call-site change at `tiles/router.py:~581`: `n_bands=1` → `n_bands=min(band_count or 1, 3)`. `band_count` is available on the resolved raster row. Existing `_compute_stretch_rescale` loop already handles n_bands>1. Pin with a unit test asserting 3 `rescale=` fragments for a 3-band input.

3. **Test data available**: single-band fixture `GRAY_50M_SR.tif` (band_count=1, is_dem=f) + RGB ortho `adk_high_peaks_ny_orthos_3857.tif` (band_count=3) both seeded and live.
