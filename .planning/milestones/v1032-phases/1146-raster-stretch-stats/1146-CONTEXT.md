# Phase 1146: Raster Stretch Stats - Context

**Gathered:** 2026-05-28
**Status:** Complete
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary
Implement single-band `percentile` + `stddev` stretch (RASTER-STRETCH-01/02) at the raster tile proxy, computing real per-band statistics → Titiler rescale instead of the `minmax`-only fallback.
</domain>

<decisions>
## Implementation Decisions
- Stats source: **Titiler `/cog/statistics`** (returns per-band min/max/mean/std/percentile_2/percentile_98). No ingest-time stats exist in `band_info` for local COGs, and computing at request time via Titiler avoids a migration + backfill.
- percentile → rescale=[percentile_2, percentile_98]; stddev → rescale=[mean ± 2σ] clamped to [min, max]; rounded to 4 dp.
- Cache per `open_path` (`_band_stats_cache`) — stats are asset-stable, so one /statistics call per asset, reused across tiles.
- Not applied to DEM (`algorithm=terrainrgb` has no rescale). Single-band scope; multi-band is Future RASTER-STRETCH-03.
- Frontend plumbing already existed (`buildColormapTileUrl` forwards `stretch=`; RasterEditor had the select) — only had to un-gate the percentile/stddev options.
</decisions>

<code_context>
## Existing Code Insights
- `backend/app/processing/tiles/router.py` — `raster_tile_proxy` + `_titiler_render_params`; stretch was a logged no-op fallback.
- `frontend/.../layer-adapters/raster-adapter.ts:buildColormapTileUrl` — forwards `stretch` only alongside a non-gray colormap (single-band display).
- `frontend/.../LayerStyleEditor/RasterEditor.tsx` — stretch select (options were `disabled` + "coming soon").
</code_context>

<specifics>
## Specific Ideas
Verified live via a reversible `is_dem=false` DB toggle: minmax (859 B near-blank) vs percentile (25 KB) vs stddev (27 KB) tiles all differ.
</specifics>

<deferred>
## Deferred Ideas
Multi-band stretch (RASTER-STRETCH-03); user-configurable percentile bounds / σ multiplier (RASTER-STRETCH-UI-01).
</deferred>
