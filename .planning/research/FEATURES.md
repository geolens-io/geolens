# Feature Landscape — v1034 Raster Stretch & Colormap Completion

**Domain:** Map builder raster rendering — completing half-built per-band stretch and configurable bounds for a GIS catalog map builder.
**Researched:** 2026-05-29
**Reference tools surveyed:** QGIS 3.44 (raster properties dialog), ArcGIS Pro stretch function, ArcGIS Online stretchRenderer spec, ArcGIS Maps SDK for JavaScript RasterStretchRenderer, Titiler/rio-tiler statistics API, rio-tiler BandStatistics spec.

---

## Scope

This research answers three scoped questions for v1034:

1. **Per-band multi-band stretch** — UX and behavior conventions for independently stretching RGB channels of an ortho or multi-band raster.
2. **Configurable stretch bounds** — conventional controls for percentile clip values and σ multiplier; table-stakes vs differentiator vs anti-feature classification.
3. **Stretch ↔ colormap coupling on single-band** — what users expect when switching between gray and a colormap while stretch is active (RASTER-STRETCH-UI-02 deferred from v1032).

Substrate confirmed by code-read (HIGH confidence):
- `backend/app/processing/tiles/router.py` — `_fetch_band_statistics` fetches `/cog/statistics`, `_compute_stretch_rescale` builds `rescale=lo,hi` per band, `_apply_stretch_rescale` patches `render_params`. Currently `n_bands=1` is hardcoded in the `stretch != minmax` branch (line 581) — multi-band stretch is the single code-path gap.
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — COLORMAP section is gated `band_count === 1`; stretch select (minmax/percentile/stddev) lives in the same gate. Multi-band rasters (band_count >= 3) see only the 4 MapLibre paint sliders and no stretch/colormap controls.
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — `buildColormapTileUrl` appends `colormap_name` and `stretch` query params; `_colormap` and `_stretch` are builder-private paint keys, not in `RASTER_OWNED_PAINT_PROPERTIES`, so they never hit MapLibre's `setPaintProperty`. The URL diff in `syncRasterLayer` triggers source teardown+recreate when either changes.
- `backend/app/processing/tiles/router.py` — Titiler `rescale` format is `rescale=lo,hi` repeated once per band (confirmed by Titiler Discussion #304: `rescale=0,1000&rescale=0,3000&rescale=0,2000`). Backend already sorts band stats by numeric suffix (`b1 < b2 < b3`). The existing `_compute_stretch_rescale` loop already iterates `range(n_bands)` — only the call site uses `n_bands=1`.

---

## Table Stakes

Features users expect for a raster renderer with stretch controls. Missing = product feels incomplete relative to QGIS and ArcGIS Map Viewer.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Per-band percentile stretch for multi-band (RGB) | QGIS 3.44 does this by default on multiband color renderer: "automatically fetches Min and Max values for each band." Washed-out orthos are a daily GIS pain point. | Low–Med | Backend almost there: `_compute_stretch_rescale` loops per band, call site just needs `n_bands=min(band_count, 3)` instead of hardcoded 1. Frontend needs a "Stretch" select in the multi-band section (currently no controls for band_count >= 3). |
| Per-band stddev stretch for multi-band | Same reference tools; stddev 2σ is the standard "auto-improve washed imagery" preset. | Low | Same backend fix as percentile. |
| Stretch defaults to minmax (dtype rescale) on new layers | All tools default to a visible starting state — minmax dtype rescale is the safest non-lossy default. GeoLens already does this (`_titiler_render_params`). | None | Verify new multi-band layers surface the stretch select with `minmax` pre-selected. |
| Reset-to-minmax affordance | After experimenting with percentile/stddev, users expect a way back to the dtype default without reloading. | Low | Existing "RESET" collapsible in RasterEditor can extend to reset `_stretch` to `minmax`. |
| Configurable percentile clip values (e.g., 2%/98% → 5%/95%) | ArcGIS Pro stretch function exposes `minPercent`/`maxPercent` (0–99); QGIS "Cumulative count cut" exposes the 2%/98% inputs as editable fields. Both treat user-configurable bounds as table stakes for imagery workflows. QGIS issue #15683 explicitly classifies this as "basic functionality in commercial GIS." | Med | Titiler `/cog/statistics` accepts `p=N` repeated params to compute named percentiles. If user sets clip to 5/95, backend must request `p=5&p=95` and read `percentile_5`/`percentile_95`. Requires: (a) new `_stretch_percentile_lo`/`_stretch_percentile_hi` builder-private paint keys, (b) backend query-param forwarding, (c) dynamic key lookup on the stats dict. |
| Configurable σ multiplier (1σ / 2σ / 3σ) | ArcGIS Pro `numberOfStandardDeviations` param; QGIS "Mean ± standard deviation × N" control. The 1/2/3 preset is universal; 2σ is the sensible default (already hardcoded as `_STDDEV_SIGMA = 2.0`). | Low | Simpler than percentile config: just expose a segmented control or numeric input for σ multiplier. Backend needs one new query param (`stretch_sigma`). No additional Titiler call needed — std is already in the stats dict. |

---

## Differentiators

Features that set the product apart. Not expected by default, but valued by power users.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Band-level min/max display (read-only stat cards) | Show computed lo/hi values per band after a percentile/stddev stretch so users can see what the auto-stretch resolved to. QGIS and ArcGIS both expose per-band stat readouts in the min/max value settings panel. Builds trust — user understands why the image looks the way it does. | Med | Requires the frontend to fire a `/cog/statistics` fetch and display `b1.percentile_2, b1.percentile_98` etc. as read-only display values alongside the stretch select. Worth building as a secondary concern once the stretch itself works. |
| "Stretch on current view" (dynamic range) | ArcGIS and QGIS both offer "Updated canvas" statistics extent — min/max recomputed from the current viewport extent, not the whole COG. Useful for large mosaics where global stats are poor. | High | Titiler supports POST `/cog/statistics` with `bbox` param for spatial clipping. This requires client-side viewport → bbox plumbing and cache invalidation on pan. Skip for v1034. |
| Per-band independent vs. linked mode toggle | ArcGIS RGB composite renderer allows "stretch per band" or "stretch all bands together." Linked mode applies one global rescale across all bands. Useful for false-color composites where band ranges differ wildly. | Med | A single "Linked bands" checkbox that, when on, applies the stretch from band 1 stats to all 3 bands. When off (default), computes per-band independently. Not table stakes — per-band independent is the right default and covers 95% of cases. |

---

## Anti-Features (DO NOT BUILD in v1034)

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Manual min/max numeric inputs per band | ArcGIS exposes user-typed min/max per band for power-override. Useful in isolation but adds 6 number inputs to an already-crowded editor. In a web map builder (vs. a desktop GIS tool), users have no way to know the "right" numbers without computing stats first. | Expose stat-based presets (minmax/percentile/stddev) with readable computed values. Manual override via Style JSON for power users. |
| Histogram visualizer inline | QGIS and ArcGIS Pro show a histogram for each band in the stretch panel. High value for desktop analysis workflows. High implementation cost in a web panel (canvas rendering, stats request, UX real estate). | Defer; keep the stat cards (read-only lo/hi values) as the lightweight substitute. |
| Custom band math / band algebra | Titiler supports `expression=(b2-b1)/(b1+b2)` etc. for computing derived indices. Out of scope for a styling panel — this crosses into raster analysis. | Defer; document in help text that style JSON export allows Titiler URL overrides. |
| Sigmoid / histogram equalization stretch | ArcGIS and some tools offer sigmoid and histogram equalization. Rarely used; sigmoid requires strength parameter tuning; histogram eq. is non-linear (unsuitable for scientific data). Adds UI complexity for minimal gain. | The minmax/percentile/stddev trio covers the standard use cases. |
| Stretch applied to DEM layers | DEM layers use `algorithm=terrainrgb` in `render_params`. This encoding is not a display stretch — it encodes elevation into RGB channels for MapLibre terrain mesh decoding. Applying rescale to a DEM corrupts the elevation values and breaks terrain. The existing guard (`render_params.startswith("algorithm=")`) is correct and must stay. | Preserve existing guard; do not expose stretch controls in DEMEditorScene. |
| Colormap selection for multi-band (band_count >= 3) | A colormap replaces the RGB channel composite with a single-channel pseudocolor lookup. For multi-band imagery that inherently encodes RGB, applying a global colormap is almost always wrong and confuses users. QGIS only exposes colormap for singleband renderers. | Keep colormap gated on `band_count === 1`. This is correct behavior, not a limitation. |

---

## Stretch ↔ Colormap Coupling (RASTER-STRETCH-UI-02)

**What the deferred coupling issue is:** When `_colormap` is `'gray'` (the default) and `_stretch` is `'percentile'`, the stretch fires correctly because `buildColormapTileUrl` forwards `stretch` independently of colormap (the comment in `raster-adapter.ts:48` explicitly documents this). The coupling issue is the opposite direction: when a user picks `viridis` colormap and then switches stretch to `percentile`, should the colormap persist, or does stretch imply gray?

**What established tools do:**

QGIS treats stretch and colormap/renderer as orthogonal concerns for singleband pseudocolor — the min/max bounds define the stretch extent, and the color ramp is applied over that stretched range. QGIS issue #15683 explicitly requests "allowing singleband gray stats functionality (specified min/max, percentile) to define the linear bounds of available pseudocolor ramps" — meaning both should coexist. The community treats stretch-bounds-that-feed-colormap as the expected behavior.

ArcGIS `stretchRenderer` applies to singleband continuous data and does not have a separate colormap concept — the stretch IS the display. ArcGIS image layer uses a separate `colormap renderer` for discrete maps. The two do not interact.

**Expected behavior (HIGH confidence from QGIS issue + ArcGIS docs):**

Users expect stretch and colormap to compose: "percentile stretch applied, then viridis colormap over the stretched range." This is already what the GeoLens backend delivers — the `stretch` param computes `rescale=lo,hi` and `colormap_name=viridis` is appended separately; Titiler applies the rescale first and then maps the result through the colormap. The implementation is correct. The UI already allows both selects to operate independently (they are two separate `<Select>` controls in the same COLORMAP section). The deferred RASTER-STRETCH-UI-02 issue is specifically a *labeling/hint gap*: there is no copy indicating that stretch feeds the colormap's input range. Users who change the colormap to `viridis` and then set stretch to `percentile` may be surprised that the image gets much better looking without understanding why. The fix is documentation/hint copy — not a behavior change.

**Concrete recommendation for v1034:**

Add a one-line hint below the Stretch select when stretch is not `minmax` and colormap is not `gray`: e.g., "Stretch sets the input range for the colormap." This closes RASTER-STRETCH-UI-02 as a copy win, not a code win. No behavior change needed.

---

## Configurable Bounds: UX Patterns

### Percentile clip

**QGIS pattern:** Two numeric inputs labeled "Min" and "Max" (defaulting to 2 and 98), constrained to [0, 100], validated as a pair. When the user changes either input, QGIS re-fetches stats from the appropriate extent. The inputs are always visible alongside the "Cumulative count cut" option — not hidden behind an expand.

**ArcGIS pattern:** `minPercent` and `maxPercent` parameters surfaced in the Layer Properties dialog as numeric inputs. Range 0–99. The documentation describes a "2 percent at the low and high end" example.

**Recommended pattern for GeoLens:**

Show two small numeric inputs (`<Input type="number" min={0} max={99} step={1}`) labeled "Low %" and "High %" inline under the stretch select when stretch is `percentile`. Default to 2 and 98. Tail-validate: if low >= high, clamp or error. These become `_stretch_percentile_lo` and `_stretch_percentile_hi` builder-private paint keys forwarded as `percentile_lo`/`percentile_hi` query params to the raster tile proxy.

Backend change: `raster_tile_proxy` receives `percentile_lo: int = 2` and `percentile_hi: int = 98`, passes `p=percentile_lo&p=percentile_hi` to `/cog/statistics`, reads `band.get(f"percentile_{percentile_lo}")` and `band.get(f"percentile_{percentile_hi}")`. The allowlist of valid percentile values should be integers 1–99 (FastAPI `Query(ge=1, le=99)`). Cache key must incorporate percentile values (currently the cache key is `open_path` only — this becomes invalidating when percentile changes, which is correct because tile URLs encode the params).

**Complexity: Medium** — 2 new query params, cache-key expansion, frontend 2 inputs + validation.

### σ multiplier

**QGIS pattern:** A single "Standard deviations" numeric input (default 1.0, typical range 0.5–3.0). The input appears when "Mean ± standard deviation" is selected as the Min/Max strategy.

**ArcGIS pattern:** `numberOfStandardDeviations` property; a single number, typically 1, 2, or 3. ArcGIS Pro exposes a numeric input with no preset chips.

**Recommended pattern for GeoLens:**

A segmented control with 3 values: `1σ / 2σ / 3σ` (3 buttons). More discoverable than a free numeric input and covers all practical use cases. The selected value becomes `_stretch_sigma` builder-private paint key, forwarded as `stretch_sigma=N` query param.

Backend change: `stretch_sigma: float = 2.0` param replaces the hardcoded `_STDDEV_SIGMA = 2.0`. Validate `ge=0.5, le=5.0`. No extra Titiler call — std is already in the stats response.

**Complexity: Low** — 1 new query param, 3-button segmented control, replace hardcoded constant.

---

## Feature Dependencies

```
Per-band multi-band stretch (RASTER-STRETCH-03)
  → Requires: backend n_bands fix (n_bands=min(band_count,3) instead of 1)
  → Requires: frontend Stretch select exposed for band_count >= 3
  → Requires: tile URL diff in syncRasterLayer already handles it (no change needed there)

Configurable percentile bounds (RASTER-STRETCH-UI-01, percentile variant)
  → Requires: backend 2 new query params + dynamic stats key lookup
  → Requires: frontend 2 numeric inputs shown when stretch=percentile
  → Requires: cache key expansion (open_path + percentile_lo + percentile_hi)

Configurable σ multiplier (RASTER-STRETCH-UI-01, stddev variant)
  → Requires: backend 1 new query param, replace hardcoded constant
  → Requires: frontend 3-button segmented control when stretch=stddev

Stretch ↔ colormap hint (RASTER-STRETCH-UI-02 resolution)
  → Requires: copy/hint addition only — no behavior change
  → Depends on: RASTER-STRETCH-03 (so hints appear for both single-band and multi-band)
```

---

## MVP Recommendation

### Build in v1034

1. **Per-band multi-band stretch** (table stakes) — backend one-liner + frontend section. Affects the most users (every ortho RGB raster gets better with percentile/stddev).
2. **σ multiplier segmented control** (table stakes) — low complexity, replaces a hardcoded constant.
3. **Configurable percentile clip values** (table stakes) — medium complexity, required for power-user workflows.
4. **Stretch ↔ colormap hint copy** (RASTER-STRETCH-UI-02 closure) — copy only, no behavior change.
5. **Non-DEM single-band raster fixture** (TESTDATA-01) — a small redistributable GeoTIFF seeded in the seed script so the colormap/stretch UI can be verified end-to-end rather than only against the ADK DEM.
6. **Dead-code cleanup** — `onRenderModeChange` member + `hillshadeTerrainNote` advisory (called out in PROJECT.md).

### Defer from v1034

- Band-level stat readouts (differentiator) — useful but not table stakes; adds a second Titiler fetch per layer-editor-open
- "Stretch on current view" (differentiator) — high complexity, viewport → bbox plumbing
- Per-band independent vs. linked toggle (differentiator) — independent is the right default; linked is a power-user concern
- Histogram visualizer (anti-feature for v1034) — high cost, narrow benefit in a web builder panel

---

## Sources

### Official Documentation (HIGH confidence)

- [QGIS 3.44 Raster Properties Dialog — Symbology tab](https://docs.qgis.org/3.44/en/docs/user_manual/working_with_raster/raster_properties.html)
- [QGIS issue #15683 — Singleband gray contrast stretch for singleband pseudocolor](https://github.com/qgis/QGIS/issues/15683)
- [ArcGIS Pro Stretch Function documentation](https://desktop.arcgis.com/en/arcmap/latest/manage-data/raster-and-images/stretch-function.htm)
- [ArcGIS Web Map Specification — stretchRenderer](https://developers.arcgis.com/web-map-specification/objects/stretchRenderer/)
- [Titiler /cog endpoint reference](https://developmentseed.org/titiler/endpoints/cog/)
- [Titiler Discussion #304 — Range adjustment by band (per-band rescale pattern)](https://github.com/developmentseed/titiler/discussions/304)
- [rio-tiler BandStatistics model — percentile field names](https://cogeotiff.github.io/rio-tiler/advanced/statistics/)

### Internal Substrate (HIGH confidence — code read)

- `backend/app/processing/tiles/router.py` — `_compute_stretch_rescale`, `_fetch_band_statistics`, `raster_tile_proxy` signature, `_STDDEV_SIGMA`, `_ALLOWED_STRETCH`, `_band_stats_cache`
- `backend/tests/test_raster_colormap_proxy.py` — `_BAND_STATS` fixture (confirms `percentile_2`, `percentile_98`, `min`, `max`, `mean`, `std` field names)
- `frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx` — `band_count === 1` gate, `_colormap`/`_stretch` private paint keys
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — `buildColormapTileUrl`, `RASTER_OWNED_PAINT_PROPERTIES`, colormap/stretch comment on RASTER-STRETCH-UI-02
- `frontend/src/components/builder/map-sync.ts` — `syncRasterLayer` source-URL diff and teardown/recreate path
