# Requirements: GeoLens — v1034 Raster Stretch & Colormap Completion

**Defined:** 2026-05-29
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

> Milestone scope: complete the raster stretch/colormap feature carried since v1031/v1032 — full per-band multi-band stretch, configurable percentile/σ bounds, a real seeded single-band raster fixture to actually verify the colormap/stretch UI, plus the v1033 builder dead-code/note cleanup. Additive changes to ~5 existing files + the seed script. No new deps, no migrations, no new routes.

## v1 Requirements

Requirements for this milestone. Each maps to exactly one roadmap phase.

### Test Data (precondition — must land first)

- [ ] **TESTDATA-01**: A non-DEM **single-band uint8/uint16** raster fixture is seeded idempotently via `scripts/seed-natural-earth.py` and is classified `is_dem=false` after ingest, so the single-band stretch/colormap UI can be verified against real data. MUST NOT be float32/float64 — a single-band float raster is auto-classified as a DEM (`backend/app/processing/.../cog.py:85` heuristic `band_count==1 AND float dtype`) and routed through `algorithm=terrainrgb` (`backend/app/processing/tiles/router.py:477`), silently bypassing stretch/colormap. Acceptance includes a post-ingest `is_dem=false` check. Candidate source: Natural Earth `GRAY_50M_SR` (uint8 grayscale shaded relief, public domain) or a synthetic uint8 COG. Fixture MUST be acquired at seed time, never at pytest time (CI flakiness).

### Multi-Band Stretch

- [ ] **RASTER-STRETCH-03**: Multi-band rasters (e.g. RGB orthos) apply an independent per-band stretch (`minmax`/`percentile`/`stddev`) producing one Titiler `rescale=lo,hi` fragment per band (capped at 3 bands / bidx 1–3). Backend deliverable: change the hardcoded `n_bands=1` call site at `backend/app/processing/tiles/router.py:581` to `n_bands=min(band_count or 1, 3)` (the `_compute_stretch_rescale` loop is already correct). Pinned by a unit test asserting the produced Titiler URL contains 3 `rescale=` fragments for a 3-band input. Frontend deliverable: widen the RasterEditor stretch-section gate at `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx:186` from `band_count === 1` to `band_count >= 1` for the **stretch** control only (colormap stays single-band gated).

### Configurable Stretch Bounds

- [ ] **SPIKE-01**: Confirm whether the running Titiler instance supports arbitrary percentile params (`?p=<float>&p=<float>`) on `/cog/statistics` and returns the corresponding `percentile_<N>` keys. This determines whether RASTER-STRETCH-UI-01 is a simple param+cache-key change or needs a different approach. Spike against the live Titiler container BEFORE wiring configurable-bounds backend. Recorded as a spike finding.
- [ ] **RASTER-STRETCH-UI-01**: User can configure stretch bounds in the RasterEditor — percentile low/high (replacing fixed p2/p98) and σ multiplier (replacing fixed ±2σ) — instead of hardcoded defaults. Backend: thread `pmin`/`pmax`/`sigma` query params into `raster_tile_proxy` and `_compute_stretch_rescale`. **CRITICAL**: extend the `_band_stats_cache` key (`backend/app/processing/tiles/router.py:~241`, currently keyed on `open_path` only) to include the bounds (e.g. `(open_path, pmin, pmax)`) — otherwise configurable bounds is a silent server-side no-op. Frontend: percentile low/high numeric inputs shown when stretch=`percentile`; σ segmented control (1/2/3) shown when stretch=`stddev`. Bounds validated (`pmin < pmax`, `sigma > 0`); recompute debounced.
- [ ] **RASTER-STRETCH-UI-02**: On single-band rasters, a copy-only hint ("Stretch sets the input range for the colormap") is shown below the stretch control when stretch ≠ `minmax` and colormap ≠ `gray`. No behavior change — `buildColormapTileUrl` already forwards `stretch` independently of `colormap_name` and Titiler applies rescale before the colormap lookup (verified correct in research).

### Verification

- [ ] **VERIFY-01**: The single-band stretch (`minmax`/`percentile`/`stddev`) + colormap UI is verified end-to-end against the seeded TESTDATA-01 fixture — distinct tile output across stretch modes and a non-`gray` colormap, with the actual Titiler URL carrying the expected `rescale=` / `colormap_name=` params (not merely HTTP 200).

### Cleanup (v1033 tech debt)

- [ ] **CLEANUP-01**: Remove the dead `onRenderModeChange` optional member in `frontend/src/components/builder/LayerStyleEditor/types.ts`, and rework or remove the unreachable `demEditor.hillshadeTerrainNote` advisory (switching a terrain-bound DEM to hillshade detaches terrain first, so the dual-consumer skip-arm + note never fire in the natural flow — see v1033 audit). Either make the note reachable via the sibling terrain-mode layer path or remove it + its i18n keys. Keep `e2e:smoke:builder` and vitest green.

### QA / Close-Gate

- [ ] **QA-01**: Orchestrator-driven live Playwright MCP close-gate before tagging — verify multi-band per-band stretch on an RGB ortho AND single-band stretch/colormap on the TESTDATA-01 fixture, confirm the emitted Titiler tile URLs carry the expected `rescale=`/`colormap_name=` params, and 0 console errors per surface. Executor subagents lack `mcp__playwright__*` access — orchestrator MUST drive MCP directly (project memory `playwright-mcp-orchestrator-only`). Plus the standard gate: `npm run typecheck` 0, vitest green, `e2e:smoke:builder` green, focused backend raster/tile pytest green, i18n parity, `make openapi-check` no-drift (expected: no API change — `style_config` is opaque jsonb, `api.ts` hand-maintained).

## v2 Requirements

Deferred — acknowledged, not in this milestone's roadmap.

### Raster (future)

- **RASTER-META-01**: `band_count=None` on the `get_dataset_meta` path shows "1 band" for RGB orthos (cosmetic; colormap correctly hidden for imagery). Tracked since v1031/v1033.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Colormap on multi-band rasters | Wrong by definition — replaces the RGB composite with pseudocolor. Colormap stays single-band gated. |
| Stretch applied to DEM layers | Corrupts terrainrgb elevation encoding; the existing `algorithm=`/`is_dem` guard is correct and must be preserved. |
| Per-band manual numeric min/max inputs | Wrong direction — users don't know raw band values; auto-stretch (percentile/σ) is the point. |
| Histogram visualizer in the RasterEditor | High cost for a web panel; out of scope for a completion milestone. |
| Stretching > 3 bands | Titiler render selects at most bidx 1–3; cap at 3. |
| OpenAPI/SDK regen | No API surface change expected (`style_config` opaque jsonb; `api.ts` hand-maintained). `make openapi-check` no-drift is the guard, not a regen task. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| TESTDATA-01 | Phase 1152 | Pending |
| RASTER-STRETCH-03 | Phase 1153 (backend) + Phase 1154 (frontend) | Pending |
| SPIKE-01 | Phase 1153 | Pending |
| RASTER-STRETCH-UI-01 | Phase 1153 (backend) + Phase 1154 (frontend) | Pending |
| RASTER-STRETCH-UI-02 | Phase 1154 | Pending |
| VERIFY-01 | Phase 1155 | Pending |
| CLEANUP-01 | Phase 1154 | Pending |
| QA-01 | Phase 1155 | Pending |

**Coverage:**
- v1 requirements: 8 total
- Mapped to phases: 8/8 ✓
- Unmapped: 0

---
*Requirements defined: 2026-05-29*
*Last updated: 2026-05-29 — traceability populated by roadmapper (phases 1152-1155)*
