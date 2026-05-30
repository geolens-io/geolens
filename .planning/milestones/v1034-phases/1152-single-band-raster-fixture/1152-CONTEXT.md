# Phase 1152: Single-Band Raster Fixture - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss) — enriched with v1034 research findings

<domain>
## Phase Boundary

A real non-DEM single-band uint8 raster is available in the system so all subsequent colormap and stretch UI verification runs against actual data rather than a DEM that silently bypasses all stretch/colormap logic.

Requirement: **TESTDATA-01**. This is a hard precondition for phases 1154/1155 verification.
</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
Implementation choices are at Claude's discretion (discuss skipped). Guided by ROADMAP goal, success criteria, codebase conventions, and the v1034 research in `.planning/research/`.

### Locked from research (do not re-litigate)
- **Fixture MUST be uint8 or uint16, NOT float32/float64.** A single-band float raster is auto-classified as a DEM by the `is_dem_candidate` heuristic (`band_count==1 AND float dtype`, ~`cog.py:85`) and routed through `algorithm=terrainrgb` (~`tiles/router.py:477`), silently bypassing ALL stretch/colormap logic. Acceptance MUST include a post-ingest `is_dem=false` DB check.
- **Acquire at seed time, never at pytest time** (CI flakiness). The fixture lands via the seed script's normal upload→preview→commit ingest path; the worker COG-converts it.
- **Idempotent** — reuse the existing `existing_by_filename` (source_filename) idempotency pattern in `scripts/seed-natural-earth.py`.
- **Source options** (planner picks): (a) Natural Earth `GRAY_50M_SR` uint8 grayscale shaded relief from the NACIS CDN already used by the seed script (`https://naciscdn.org/naturalearth/50m/raster/GRAY_50M_SR.zip`, public domain), or (b) a GDAL/rasterio-generated synthetic uint8 single-band COG (no network dependency). Prefer the option that is most deterministic for repeat seeding; if download flakiness is a concern, synthetic is acceptable.
</decisions>

<code_context>
## Existing Code Insights

- `scripts/seed-natural-earth.py` currently has NO raster ingest path (vector only). The existing `ingest_dataset()` three-step pattern (upload → preview → commit) works identically for rasters — the server auto-detects raster via the `.tif` extension in `_stamp_raster_metadata`.
- Raster classification heuristic lives in the COG processing module (`backend/app/processing/.../cog.py`). The DEM guard in the tile proxy is `backend/app/processing/tiles/router.py` (~line 477).
- Full integration detail in `.planning/research/ARCHITECTURE.md` and traps in `.planning/research/PITFALLS.md`.
</code_context>

<specifics>
## Specific Ideas

- Add a raster fixture entry/function to `scripts/seed-natural-earth.py` that ingests the single-band uint8 COG idempotently.
- Verify post-ingest: query `is_dem` for the new raster asset → must be `false`.
- Keep the existing vector seed behavior unchanged.
</specifics>

<deferred>
## Deferred Ideas

- Multi-band fixture (RGB ortho) — an existing ortho dataset already covers the multi-band stretch verification path; no new multi-band fixture needed for this phase.
</deferred>
