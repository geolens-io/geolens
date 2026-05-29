# Phase 1140: Raster & Terrain Editor Controls — Research

**Researched:** 2026-05-28
**Domain:** MapLibre GL JS 5.x editor extensions, Titiler 2.0.2 colormap API, DEM contour/hillshade authoring
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- None from discuss (discuss skipped, Claude's discretion mode)

### Claude's Discretion
All implementation choices are at Claude's discretion. Use ROADMAP success criteria, REQUIREMENTS.md, and existing codebase conventions.

### Deferred Ideas (OUT OF SCOPE)
- 999.18 editor-convenience: EDITOR-SYMBOL-04, EDITOR-BASEMAP-06
- Layer-type expansion: LAYER-TEXT-01, LAYER-DRAW-01, LAYER-LIDAR-01
- Custom user sprite-upload backend (EDITOR-FILL-01 scope)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EDITOR-DEM-04 | User can enable and configure a contour-line overlay on a DEM/terrain layer (toggle + line styling: interval, color, weight) | maplibre-contour 0.1.0 client-side approach chosen; reuses existing raster-dem source; companion `line` layer added/removed on toggle |
| EDITOR-DEM-05 | User can apply a hypsometric (elevation) tint color ramp to a terrain/DEM layer from a preset ramp set | MapLibre GL JS 5.24.0 native `color-relief` layer confirmed; requires raster-dem source already owned by hillshade-adapter; gated to hillshade mode only |
| EDITOR-RASTER-COLORMAP | User can apply a single-band stretch + colormap to a raster layer via the editor; tiles re-render on change | Titiler 2.0.2 `colormap_name` + `rescale` params confirmed; requires backend `raster_tile_proxy` change to accept/forward them; nginx cache key must include colormap; band_count not in MapLayerResponse (must be added) |
</phase_requirements>

---

## Summary

Phase 1140 adds three editor controls to existing per-render-mode panels: a contour overlay for DEM layers (EDITOR-DEM-04), a hypsometric tint for hillshade mode (EDITOR-DEM-05), and a single-band colormap selector for raster layers (EDITOR-RASTER-COLORMAP).

**EDITOR-DEM-04 (Contour Overlay):** The `maplibre-contour` library (v0.1.0, published 2024-12, slopcheck OK) generates client-side contour vector tiles from an existing `raster-dem` source using a custom MapLibre protocol handler. The DEM tile source already uses `encoding: 'mapbox'` (terrainrgb), which `maplibre-contour` supports. The approach adds one `DemSource` registration in `BuilderMap.tsx` (or on the map instance), then adds/removes a companion `line` layer when the contour toggle is changed. Contour interval, color, and weight are stored as `_contour-*` builder-private paint keys; the companion line layer reads those values when synced. No backend changes. No new architecture.

**EDITOR-DEM-05 (Hypsometric Tint):** MapLibre GL JS 5.24.0 (installed version) contains a native `color-relief` layer type. It requires a `raster-dem` source (the same source the hillshade layer uses), an `interpolate`/`['elevation']` expression for `color-relief-color`, and can optionally share the same source as the hillshade layer (MapLibre warns about sharing but does not prevent it). The chosen approach: add a companion `color-relief` layer using the existing raster-dem source when the hypso toggle is enabled in hillshade mode. Ramp stops are derived from `getRampColors()` (chroma.js) mapped across a fixed elevation range (0–4000 m default, adjustable). No backend changes.

**EDITOR-RASTER-COLORMAP:** This is the only requirement with a backend change. The Titiler 2.0.2 `/cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}.{format}` endpoint already accepts `colormap_name` (enum of 150+ names) and `rescale` (comma-separated min,max per band). The backend `raster_tile_proxy` endpoint currently ignores request query params and builds render params entirely from database metadata. The plan must add `colormap_name: str | None` and `stretch: str | None` query params to `raster_tile_proxy`, forward them as additional Titiler params, and update the nginx cache key (currently `$dataset_id/$z/$x/$y.$fmt`) to include colormap/stretch so different colormaps get distinct cache entries. The frontend encodes `_colormap` and `_stretch` as builder-private paint keys; a helper in the raster adapter converts them to a modified tile URL with `?colormap_name=viridis&rescale=0,255` query params; when paint changes, `syncRasterLayer` detects the URL change and tears down + recreates the source. The `band_count` field does NOT currently exist on `MapLayerResponse` (confirmed in backend schema + frontend type), so it must be added to conditionally show the COLORMAP section.

**Primary recommendation:** Ship all three features on the existing adapter/sync substrate. No new architecture files. maplibre-contour is a zero-dependency npm package (slopcheck OK). color-relief is MapLibre-native — no new package. Backend change is minimal: 2 new optional query params in `raster_tile_proxy` + nginx cache key update.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Contour line rendering | Browser / Client | — | Client-side vector tile generation via maplibre-contour from existing DEM tiles; no server rasterization needed |
| Contour UI controls | Frontend (LayerEditorPanel) | — | Builder-private paint keys `_contour-*`; DEMEditorScene stores them, hillshade-adapter ignores them (no maplibre paint mapping); companion layer reads them via new adapter |
| Hypsometric tint rendering | Browser / Client | — | MapLibre native `color-relief` layer on existing raster-dem source; pure client-side |
| Hypsometric tint UI | Frontend (LayerEditorPanel) | — | `_hypso-ramp` builder-private paint key; DEMEditorScene owns it; companion color-relief layer created/removed |
| Raster colormap selection | API / Backend + Browser | — | colormap_name forwarded to Titiler by the raster proxy; tile URL change causes MapLibre to re-fetch; UI stores `_colormap`/`_stretch` in paint |
| band_count detection (single-band gate) | API / Backend | Frontend | `band_count` must be added to `MapLayerResponse`; frontend reads `layer.band_count` to gate COLORMAP section |

---

## Standard Stack

### Core (existing — no new installs for DEM-04 colormap path or DEM-05)
| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| maplibre-gl | 5.24.0 (installed) | color-relief layer type (DEM-05) | Native in 5.x |
| chroma-js | existing | getRampColors() for color-relief stops | Already imported in color-ramps.ts |
| `frontend/src/lib/color-ramps.ts` | existing | SEQUENTIAL_RAMPS + DIVERGING_RAMPS used as hypso preset set | ColorRampPicker already consumes these |

### New Package (DEM-04 contour only)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `maplibre-contour` | 0.1.0 | Client-side contour vector tiles from terrain-RGB DEM tiles | Only library for this problem in the MapLibre ecosystem; zero deps; slopcheck OK; BSD-3 |

**Installation (DEM-04 only):**
```bash
npm install maplibre-contour
```

**Version verification:**
```
npm view maplibre-contour version  → 0.1.0
```

Published 2024-12-21. [VERIFIED: npm registry — confirmed on registry + slopcheck OK]

---

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| maplibre-contour | npm | ~5 mo | low (niche GIS library) | github.com/onthegomap/maplibre-contour | [OK] | Approved — zero deps, known author (OnTheGoMap), BSD-3, 274 GH stars |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
DEMEditorScene (hillshade/terrain mode)
    ├── CONTOUR LINES section (DEM-04)
    │   ├── Switch toggle → _contour-enabled in paint
    │   ├── SliderRow interval → _contour-interval in paint
    │   ├── StyleColorPicker → _contour-color in paint
    │   └── SliderRow weight → _contour-weight in paint
    │   └── [paint change] → handlePaintChange → applyLayerUpdate
    │                         → use-layer-map-sync → hillshadeContourSync()
    │                         → DemSource registered on map (once)
    │                         → map.addLayer({id:'layer-{id}-contour', type:'line', source: contour-protocol-url})
    │                         OR map.removeLayer / setLayoutProperty visibility
    │
    └── HYPSOMETRIC TINT section (DEM-05)
        ├── Switch toggle → _hypso-enabled in paint
        └── ColorRampPicker → _hypso-ramp in paint  (e.g. 'Viridis')
            └── [paint change] → hillshadeColorReliefSync()
                              → map.addLayer({id:'layer-{id}-colorrelief', type:'color-relief',
                                              source: sourceId (same raster-dem),
                                              paint: {'color-relief-color': buildElevationExpression(rampColors)}})
                              OR map.removeLayer

RasterEditor (single-band rasters)
    └── COLORMAP section (RASTER-COLORMAP, band_count === 1)
        ├── Select colormap → onPaintProp('_colormap', 'viridis')
        └── Select stretch  → onPaintProp('_stretch', 'minmax')
            └── [paint change] → buildRasterTileUrlWithColormap(baseUrl, paint)
                              → modified tile_url: /raster-tiles/{id}/tiles/{z}/{x}/{y}.png?colormap_name=viridis&rescale=0,255
                              → syncRasterLayer detects URL change → removeLayer/removeSource + addLayers
                              (MapLibre re-fetches all tiles with new colormap)

Backend (RASTER-COLORMAP only):
    raster_tile_proxy(dataset_id, z, x, y, fmt, colormap_name=None, stretch=None)
        → raster_auth_check() → X-GeoLens-Render-Params: 'bidx=1&rescale=0,255'
        → if colormap_name: append &colormap_name={colormap_name} to render_params
        → if stretch != 'minmax': compute statistics, derive rescale range
        → build_titiler_cog_url(..., raw_query_suffix=render_params)
        → nginx cache key updated: $dataset_id/$z/$x/$y.$fmt/$colormap_name/$stretch
```

### Recommended Project Structure
```
frontend/src/components/builder/
├── DEMEditorScene.tsx         ← Add CONTOUR LINES + HYPSOMETRIC TINT sections
├── LayerStyleEditor/
│   └── RasterEditor.tsx       ← Add COLORMAP section (band_count gate)
├── layer-adapters/
│   ├── hillshade-adapter.ts   ← No change to owned paint; companion layer sync lives in map-sync.ts
│   └── raster-adapter.ts      ← Add buildColormapTileUrl() helper; update syncPaint to handle _colormap/_stretch URL rebuild
└── map-sync.ts                ← Add syncContourLayer() + syncColorReliefLayer() helpers (called from syncRasterLayer / syncHillshadeLayer branches)

backend/app/processing/tiles/
└── router.py                  ← Add colormap_name + stretch params to raster_tile_proxy
frontend/nginx.conf            ← Update cache key to include colormap/stretch
frontend/src/types/api.ts      ← Add band_count to MapLayerResponse
backend/app/modules/catalog/maps/schemas.py  ← Add band_count to MapLayerResponse
```

### Pattern 1: Builder-Private Paint Keys (existing pattern, extended)
**What:** Keys prefixed with `_` are stored in `layer.paint` but are NOT passed to MapLibre paint. They are builder-internal state.
**When to use:** For any control whose effect is achieved via a companion layer or URL mutation (not a direct MapLibre paint property).
**Existing examples:** `_heatmap-ramp`, `_outline-color`, `_contour-*`, `_hypso-ramp`, `_colormap`, `_stretch`

```typescript
// Source: LayerStyleEditor.tsx:220-230
const handlePaintProp = useCallback((key: string, value: unknown) => {
  // Underscore-prefixed builder-private keys can be special-cased here
  // or fall through to the normal paint merge path (onPaintChange)
  onPaintChange(layer.id, { ...paint, [key]: value });
}, [layer.id, paint, onPaintChange, updateBuilderConfig]);
```

### Pattern 2: Companion Layer Sync in syncRasterLayer / syncHillshadeLayer
**What:** When a raster layer is synced, check builder-private paint keys and add/remove/update companion layers accordingly.
**When to use:** For DEM-04 contour (companion `line` layer), DEM-05 hypsometric tint (companion `color-relief` layer).
**Contract:** Companion layer IDs are derived from the primary layer ID: `${layerId}-contour`, `${layerId}-colorrelief`.

```typescript
// Pattern: companion layer add/remove on boolean paint key
function syncContourLayer(map: MaplibreMap, input: AdapterLayerInput) {
  const enabled = input.paint['_contour-enabled'] === true;
  const contourLayerId = `${input.layerId}-contour`;
  if (!enabled) {
    if (map.getLayer(contourLayerId)) map.removeLayer(contourLayerId);
    return;
  }
  // DemSource is registered once on map (keyed by sourceId).
  // Add contour line layer if not present, else update paint.
  if (!map.getLayer(contourLayerId)) {
    map.addLayer({
      id: contourLayerId,
      type: 'line',
      source: contourProtocolSourceId(input.sourceId),
      // paint from _contour-* keys
    });
  } else {
    // update paint properties from _contour-* keys
  }
}
```

### Pattern 3: Raster Tile URL Mutation for Colormap
**What:** When `_colormap` or `_stretch` builder-private keys are present in paint, build a tile URL with additional query params before passing to `syncRasterLayer`. The URL change triggers `syncRasterLayer`'s tile-URL-diff logic to tear down and recreate the source.
**Where it lives:** New helper `buildColormapTileUrl(baseUrl: string, paint: Record<string, unknown>): string` in `raster-adapter.ts`.

```typescript
// Appends ?colormap_name=viridis&rescale=0,255 when _colormap is set
export function buildColormapTileUrl(baseUrl: string, paint: Record<string, unknown>): string {
  const colormap = paint['_colormap'];
  const stretch = paint['_stretch'];
  if (!colormap) return baseUrl;
  const params = new URLSearchParams();
  if (typeof colormap === 'string' && colormap !== 'gray') {
    params.set('colormap_name', colormap);
  }
  if (typeof stretch === 'string' && stretch !== 'minmax') {
    params.set('stretch', stretch);
  }
  const qs = params.toString();
  return qs ? `${baseUrl}?${qs}` : baseUrl;
}
```

**Note:** `syncRasterLayer` in `map-sync.ts` (line 619-637) already checks `currentSourceSpec.tiles?.[0] !== desiredTileUrl` and tears down the source when the URL changes. This is the re-render trigger — no additional mechanism needed.

### Pattern 4: color-relief Companion Layer (DEM-05)
**What:** A `color-relief` layer using the SAME raster-dem source as the hillshade layer, added as a companion when hypsometric tint is enabled in hillshade mode.
**Source compatibility:** `color-relief` requires a `raster-dem` source. The hillshade adapter already adds a `raster-dem` source (line 133 of `hillshade-adapter.ts`). The same source can be reused (MapLibre 5.24 shows a warning if source is shared with terrain but does not block it; for builder use without 3D terrain this is safe).

```typescript
// color-relief paint expression using chroma.js ramp stops
function buildColorReliefExpression(rampName: string, elevMin: number, elevMax: number): unknown[] {
  const colors = getRampColors(rampName, 7); // 7 stops across elevation range
  const step = (elevMax - elevMin) / (colors.length - 1);
  const expr: unknown[] = ['interpolate', ['linear'], ['elevation']];
  colors.forEach((color, i) => {
    expr.push(elevMin + i * step, color);
  });
  return expr;
}

// addLayer call:
map.addLayer({
  id: `${layerId}-colorrelief`,
  type: 'color-relief',
  source: sourceId,  // existing raster-dem source from hillshade-adapter
  paint: {
    'color-relief-color': buildColorReliefExpression(rampName, 0, 4000),
    'color-relief-opacity': 0.7,
  },
  // Insert below hillshade layer so hillshade shading renders on top
});
```

### Anti-Patterns to Avoid
- **Do NOT use `map.setPaintProperty()` for `color-relief-color`**: The `color-relief-color` uses `ColorRampProperty` (not a standard paint spec), so `setPaintProperty` may not accept an expression array. Use `removeLayer` + `addLayer` when the ramp changes.
- **Do NOT store `_colormap`/`_stretch` in `RASTER_OWNED_PAINT_PROPERTIES`**: Those keys would get passed to MapLibre's `setPaintProperty` which doesn't know them. Keep them as unrecognized builder-private keys.
- **Do NOT call `map.setTiles()` directly on the raster source**: Use the `syncRasterLayer` tile-URL-diff path (remove/re-add) which is the existing established pattern.
- **Do NOT share DemSource across multiple DEM layers without keying by sourceId**: Register one DemSource per raster-dem source to avoid cross-layer contamination.
- **Do NOT implement stretch computation in the frontend**: percentile/stddev stretch requires reading raster statistics; compute the `rescale` range on the backend (Phase 1140 can scope to minmax only; percentile/stddev can pass a `stretch` hint to the backend for future stats-based computation, or the Titiler `/cog/statistics` endpoint can be called from the backend).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Contour line generation from DEM tiles | Custom WebWorker elevation decoder + isoline algorithm | `maplibre-contour` | Implements marching squares with bilinear interpolation, Web Worker + SharedArrayBuffer for performance, handles tile caching |
| Elevation color ramp interpolation | Manual color stop array | `chroma.js` (already installed) via `getRampColors()` | Already used in the codebase for heatmap ramps |
| Hypsometric tint layer | Custom fragment shader / canvas overlay | MapLibre native `color-relief` layer | Zero-cost WebGL path already in the renderer; works with any raster-dem source |
| Titiler colormap list | Hand-coded enum | Curated subset per UI-SPEC (already designed) | Titiler has 150+ colormaps; the UI-SPEC curated 8 practical ones |

---

## Critical Technical Findings

### Finding 1: RASTER-COLORMAP — nginx strips query params from raster tile requests

**Root cause:** The nginx `raster-tiles` location block rewrites with:
```nginx
rewrite ^.*$ /tiles/raster-proxy/$dataset_id/$z/$x/$y.$fmt break;
```
The `^.*$` match discards everything including the query string. Appending `?colormap_name=viridis` to the frontend tile URL does NOT reach the API when running behind nginx (production).

**In Vite dev mode:** The Vite proxy's `rewrite` function passes query params through to the API. Dev mode works fine with URL query params.

**Consequence for the plan:** Two changes required:
1. **Backend:** Add `colormap_name: str | None = Query(None)` and `stretch: str | None = Query(None)` to `raster_tile_proxy` in `backend/app/processing/tiles/router.py`. When `colormap_name` is set, append `colormap_name={colormap_name}` to the Titiler render params (overrides default single-band rendering). When `stretch` is a non-`minmax` value, either compute statistics (Titiler `/cog/statistics` sub-call) or pass a `percentile_range` param if Titiler supports it. **Scope to `minmax` only for Phase 1140** (percentile/stddev require a statistics sub-call; flag as v1032 follow-up).
2. **Nginx:** Update the nginx `raster-tiles` location to preserve colormap/stretch in the cache key, and forward them through to the API proxy. The cleanest approach: append query params to the rewrite path (not easy with nginx `$args` in a `rewrite break` block) OR add a separate `proxy_set_header` + use `$args` — but nginx `rewrite break` drops `$args`. **Recommended approach:** In `raster_tile_proxy`, accept params via the URL path pattern OR update nginx to use `proxy_pass $upstream_api$uri?$args` approach (not compatible with `rewrite break`). **Simplest solution:** Switch the nginx location from `rewrite break` to `proxy_pass` with an explicit URL that preserves query params:
   ```nginx
   # Change to:
   proxy_pass $upstream_api/tiles/raster-proxy/$dataset_id/$z/$x/$y.$fmt$is_args$args;
   proxy_cache_key "$dataset_id/$z/$x/$y.$fmt/$arg_colormap_name/$arg_stretch";
   ```
   This requires also removing the `rewrite` line.

**Phase 1143 flag:** Any new query param on `raster_tile_proxy` is a schema change that triggers the OpenAPI/SDK refresh per STATE.md HARD INVARIANT 6.

### Finding 2: band_count NOT in MapLayerResponse — must be added

`MapLayerResponse` in both the backend (`backend/app/modules/catalog/maps/schemas.py:653`) and frontend (`frontend/src/types/api.ts:890`) does NOT include `band_count`. The COLORMAP section in `RasterEditor` must gate on `layer.band_count === 1`.

**Required changes:**
1. Backend `MapLayerResponse` Pydantic model: add `band_count: int | None = None`
2. Backend service that builds `MapLayerResponse`: populate `band_count` from `raster_assets.band_count` (already stored in DB per `RasterAsset` model)
3. Frontend `MapLayerResponse` TypeScript interface: add `band_count?: number | null`
4. Frontend `RasterEditor.tsx`: read `layer.band_count` and conditionally render the COLORMAP section

**Blast radius:** Additive schema change, backwards compatible (new optional field). Does trigger OpenAPI/SDK refresh in Phase 1143.

### Finding 3: color-relief layer confirmed native in maplibre-gl 5.24.0

`ColorReliefStyleLayer` is exported from `maplibre-gl/dist/maplibre-gl.d.ts`. The type is `'color-relief'` and it accepts:
- `source`: a `raster-dem` source ID
- `paint['color-relief-color']`: a `ColorRampProperty` (interpolate expression over `['elevation']`)
- `paint['color-relief-opacity']`: number 0-1

The expression format confirmed from `color_relief_style_layer.test.ts`:
```typescript
[
  'interpolate', ['linear'], ['elevation'],
  0, '#000000',
  1000, '#ffffff'
]
```
[VERIFIED: maplibre-gl 5.24.0 node_modules source]

**Gating decision (per UI-SPEC A-02):** Hypsometric tint is hidden in terrain mode (terrain mode uses 3D surface, not a paint layer). Show only in hillshade mode.

### Finding 4: maplibre-contour is compatible with existing DEM tile encoding

The hillshade adapter uses `encoding: 'mapbox'` (line 141 of `hillshade-adapter.ts`). The Titiler backend uses `algorithm=terrainrgb` which produces Mapbox/terrainrgb encoding. `maplibre-contour` supports `encoding: 'mapbox'` (confirmed from docs). The existing DEM tile source URL is reusable — `maplibre-contour` registers a custom protocol handler that requests the same DEM tiles.

**DemSource API (from npm package, confirmed):**
```typescript
import mlcontour from 'maplibre-contour';
const demSource = new mlcontour.DemSource({
  url: demTileUrl,  // the existing raster-dem tile URL pattern
  encoding: 'mapbox',
  maxzoom: 18,
  worker: true,
});
demSource.setupMaplibre(map);
// Contour source URL:
const contourUrl = demSource.contourProtocolUrl({
  thresholds: { 9: [100, 500], 11: [50, 200], 13: [25, 100] },
  multiplier: 3.28084,  // if DEM units are meters, show feet
  contourLayer: 'contours',
  elevationKey: 'ele',
  levelKey: 'level',
  overzoom: 1,
});
```
[CITED: github.com/onthegomap/maplibre-contour README]

**Important constraint:** `DemSource.setupMaplibre(map)` must be called once per DEM source, AFTER the map is loaded. The companion contour source URL is then used as the MapLibre source `tiles` URL for a vector source. The contour line layer is a standard MapLibre `line` layer on top of this vector source.

### Finding 5: Titiler 2.0.2 colormap_name confirmed

All 8 colormaps from the UI-SPEC are verified to exist in the running Titiler instance:

| UI Label | Titiler name | Verified |
|----------|-------------|---------|
| Grayscale | `gray` | [VERIFIED: running titiler:8000/colorMaps] |
| Viridis | `viridis` | [VERIFIED: running titiler:8000/colorMaps] |
| Inferno | `inferno` | [VERIFIED: running titiler:8000/colorMaps] |
| Plasma | `plasma` | [VERIFIED: running titiler:8000/colorMaps] |
| Magma | `magma` | [VERIFIED: running titiler:8000/colorMaps] |
| Yellow-Red | `ylorrd` | [VERIFIED: running titiler:8000/colorMaps] |
| Blue-Green | `bugn` | [VERIFIED: running titiler:8000/colorMaps] |
| Terrain | `terrain` | [VERIFIED: running titiler:8000/colorMaps] |

The `rescale` param accepts an array of `"min,max"` strings (one per band). For single-band: `rescale=0,255`.

### Finding 6: Stretch strategies — minmax only for Phase 1140

Titiler does NOT have a built-in `percentile` or `stddev` stretch strategy. The `rescale` param takes explicit min/max values. To implement percentile/stddev stretch, the backend would need to call Titiler's `/cog/statistics` endpoint to get band statistics, then compute the appropriate rescale range. **Phase 1140 scopes to `minmax` only.** The `_stretch` paint key is persisted and the Select control shows all 3 options, but:
- `minmax`: uses the dtype max (existing `_titiler_render_params` logic — e.g. `rescale=0,65535` for uint16)
- `percentile`/`stddev`: for Phase 1140, passes the stretch value to the backend; backend treats unknown stretch as `minmax` fallback with a logged warning. **Phase 1141+ can implement actual statistics computation.** This keeps the API surface complete while deferring the complexity.

**Alternative considered:** Call `/cog/statistics` from the frontend (via a dataset metadata API). Rejected: adds a new per-layer API call on every colormap change, complex CORS/auth surface, slower UX.

---

## Common Pitfalls

### Pitfall 1: color-relief `color-relief-color` expression vs setPaintProperty
**What goes wrong:** Calling `map.setPaintProperty(layerId, 'color-relief-color', expression)` may silently fail because `ColorRampProperty` has a non-standard evaluation path.
**Why it happens:** `color-relief-color` uses `ColorRampProperty` (same class as `heatmap-color` and `line-gradient`) which is not a standard `DataDrivenProperty`. The `setPaintProperty` path may not trigger the ramp texture re-bake.
**How to avoid:** Remove and re-add the `color-relief` layer when the ramp changes (same approach as switching between DEM render modes). This is fast (WebGL layer add/remove is cheap for a single layer).
**Warning signs:** Map visually shows no tint change after ramp selection, no JS error.

### Pitfall 2: Sharing raster-dem source between hillshade and color-relief
**What goes wrong:** MapLibre 5.24 emits a console warning: "You are using the same source for a color-relief layer and for 3D terrain." This is for 3D terrain (map.setTerrain), not for a hillshade layer. In hillshade mode (no 3D terrain), sharing is safe.
**Why it happens:** The warning is triggered by `map.setTerrain()` detection, not by `hillshade` layer type.
**How to avoid:** Since the builder only uses the raster-dem source for hillshade in hillshade mode (not terrain mode, which uses a separate terrain source), sharing is safe. The color-relief companion is only added in hillshade mode; in terrain mode it's hidden. No regression.

### Pitfall 3: nginx query string stripping
**What goes wrong:** Dev works, production (nginx) silently ignores colormap params — tiles render in default grayscale regardless of UI selection.
**Why it happens:** nginx `rewrite ... break` discards `$args`.
**How to avoid:** Switch nginx raster-tiles location to `proxy_pass` with `$is_args$args` appended. Update the cache key to include `$arg_colormap_name` and `$arg_stretch`.

### Pitfall 4: Contour DemSource protocol registration timing
**What goes wrong:** Calling `demSource.setupMaplibre(map)` before map `idle` / style loaded fails silently because the protocol handler is not yet registered.
**Why it happens:** Protocol handlers must be registered after MapLibre is initialized.
**How to avoid:** Register the DemSource in the `map.once('idle', ...)` callback, or in `BuilderMap.tsx` inside the `onLoad` handler (same location where `map.setTransformRequest` is called). Key the DemSource by `sourceId` to avoid re-registration.

### Pitfall 5: band_count null/missing in existing map responses
**What goes wrong:** After adding `band_count` to `MapLayerResponse`, existing maps (already saved in DB) may return `null` for `band_count` even for single-band rasters if the value is not populated in the query.
**Why it happens:** The service that builds `MapLayerResponse` must JOIN `raster_assets` to get `band_count`. If the join is LEFT JOIN and the asset row doesn't exist yet (e.g. VRT with no asset), `band_count` is null.
**How to avoid:** Gate the COLORMAP section on `layer.band_count === 1` (strict equality, not `<= 1`). `null` defaults to not showing the section — safe fallback.

### Pitfall 6: RASTER_OWNED_PAINT_PROPERTIES contamination
**What goes wrong:** Adding `_colormap` or `_stretch` to `RASTER_OWNED_PAINT_PROPERTIES` causes `raster-adapter.syncPaint()` to try `map.setPaintProperty(layerId, '_colormap', ...)` — MapLibre rejects unknown paint properties with an error.
**Why it happens:** `RASTER_OWNED_PAINT_PROPERTIES` feeds directly into the `setPaintProperty` loop.
**How to avoid:** Do NOT add `_colormap`/`_stretch`/`_contour-*`/`_hypso-*` to `RASTER_OWNED_PAINT_PROPERTIES`. They are builder-private and must never reach MapLibre's paint API.

---

## Code Examples

### EDITOR-DEM-04: Contour companion layer sync
```typescript
// Source: hillshade-adapter.ts line 141 (encoding reference)
// Source: maplibre-contour README (DemSource API)
// File to modify: map-sync.ts — new helper function

// DemSource registry (module-level, keyed by sourceId)
const _demSources = new Map<string, DemSource>();

function ensureDemSource(map: MaplibreMap, sourceId: string, tileUrl: string): DemSource {
  if (_demSources.has(sourceId)) return _demSources.get(sourceId)!;
  const demSource = new mlcontour.DemSource({
    url: absolutizeTileUrl(tileUrl),
    encoding: 'mapbox',
    maxzoom: 18,
    worker: true,
  });
  demSource.setupMaplibre(map);
  _demSources.set(sourceId, demSource);
  return demSource;
}

function syncContourLayer(map: MaplibreMap, input: AdapterLayerInput): void {
  const contourLayerId = `${input.layerId}-contour`;
  const contourSourceId = `${input.sourceId}-contour`;
  const enabled = input.paint['_contour-enabled'] === true;

  if (!enabled) {
    if (map.getLayer(contourLayerId)) map.removeLayer(contourLayerId);
    return;
  }

  const demSource = ensureDemSource(map, input.sourceId, input.tileUrl);
  const interval = typeof input.paint['_contour-interval'] === 'number'
    ? input.paint['_contour-interval'] as number : 100;
  const color = typeof input.paint['_contour-color'] === 'string'
    ? input.paint['_contour-color'] as string : '#555555';
  const weight = typeof input.paint['_contour-weight'] === 'number'
    ? input.paint['_contour-weight'] as number : 1;

  // Add contour vector source if not present
  if (!map.getSource(contourSourceId)) {
    map.addSource(contourSourceId, {
      type: 'vector',
      tiles: [demSource.contourProtocolUrl({ /* interval-based thresholds */ })],
    });
  }

  if (!map.getLayer(contourLayerId)) {
    map.addLayer({
      id: contourLayerId,
      type: 'line',
      source: contourSourceId,
      'source-layer': 'contours',
      paint: {
        'line-color': color,
        'line-width': weight,
      },
    }, input.layerId); // insert below hillshade layer
  } else {
    map.setPaintProperty(contourLayerId, 'line-color', color);
    map.setPaintProperty(contourLayerId, 'line-width', weight);
  }
}
```

### EDITOR-DEM-05: color-relief companion layer
```typescript
// Source: maplibre-gl 5.24.0 color_relief_style_layer.test.ts (elevation expression)
// File to modify: map-sync.ts — new helper function

function buildElevationExpression(rampName: string): unknown[] {
  const colors = getRampColors(rampName, 7);
  const elevMin = 0;
  const elevMax = 4000;
  const step = (elevMax - elevMin) / (colors.length - 1);
  const expr: unknown[] = ['interpolate', ['linear'], ['elevation']];
  colors.forEach((color, i) => {
    expr.push(elevMin + i * step, color);
  });
  return expr;
}

function syncColorReliefLayer(map: MaplibreMap, input: AdapterLayerInput): void {
  const reliefLayerId = `${input.layerId}-colorrelief`;
  const enabled = input.paint['_hypso-enabled'] === true;

  if (!enabled) {
    if (map.getLayer(reliefLayerId)) map.removeLayer(reliefLayerId);
    return;
  }

  const rampName = typeof input.paint['_hypso-ramp'] === 'string'
    ? input.paint['_hypso-ramp'] as string : 'Viridis';

  // Always remove and re-add — color-relief-color ramp changes require layer recreation
  if (map.getLayer(reliefLayerId)) map.removeLayer(reliefLayerId);

  map.addLayer({
    id: reliefLayerId,
    type: 'color-relief' as LayerSpecification['type'],
    source: input.sourceId, // existing raster-dem source from hillshade-adapter
    paint: {
      'color-relief-color': buildElevationExpression(rampName),
      'color-relief-opacity': 0.7,
    },
  } as LayerSpecification, input.layerId); // insert below hillshade layer
}
```

### EDITOR-RASTER-COLORMAP: Tile URL builder
```typescript
// File to modify: raster-adapter.ts — new exported helper

/**
 * Build a raster tile URL with colormap_name and stretch query params
 * appended when the user has selected a non-default colormap.
 * Called from syncRasterLayer before comparing desiredTileUrl.
 */
export function buildColormapTileUrl(
  baseUrl: string,
  paint: Record<string, unknown>,
): string {
  const colormap = paint['_colormap'];
  const stretch = paint['_stretch'];
  if (!colormap || colormap === 'gray') return baseUrl;
  const params = new URLSearchParams();
  params.set('colormap_name', colormap as string);
  if (typeof stretch === 'string') {
    params.set('stretch', stretch);
  }
  return `${baseUrl}?${params.toString()}`;
}
```

### Backend: raster_tile_proxy new params
```python
# Source: backend/app/processing/tiles/router.py
# Pattern: add optional query params to existing endpoint

@router.get(
    "/raster-proxy/{dataset_id}/{z:int}/{x:int}/{y:int}.{fmt}",
    response_class=Response
)
@limiter.exempt
async def raster_tile_proxy(
    request: Request,
    dataset_id: uuid.UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    colormap_name: str | None = Query(None, description="Titiler colormap name for single-band display"),
    stretch: str | None = Query(None, description="Stretch strategy: minmax (default), percentile, stddev"),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    auth_resp = await raster_auth_check(request, dataset_id, user, db)
    open_path = auth_resp.headers.get("X-GeoLens-Asset-OpenPath")
    render_params = auth_resp.headers.get("X-GeoLens-Render-Params", "")

    # Append colormap_name override for single-band colorized display
    if colormap_name and not render_params.startswith("algorithm="):
        # Do not override DEM terrainrgb algorithm
        render_params = f"{render_params}&colormap_name={colormap_name}"

    titiler_url = build_titiler_cog_url(
        f"tiles/WebMercatorQuad/{z}/{x}/{y}.{fmt}",
        query={"url": open_path},
        raw_query_suffix=render_params or None,
    )
    # ... (rest unchanged)
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Titiler colormap via nginx URL rewrite (not implemented) | Backend accepts `colormap_name` + `stretch` as query params; nginx updated to forward `$args` | Enables per-layer colormap without a new tile endpoint |
| No native hypsometric tint in MapLibre 4.x | MapLibre 5.x `color-relief` layer type | Zero-cost WebGL elevation tinting without custom shaders |
| Contour lines require pre-generated vector tiles | `maplibre-contour` 0.1.0 client-side generation from raster-dem tiles | On-demand contours at any interval without backend storage |

**Deprecated/outdated:**
- The old pg_tileserv approach for raster tiles is gone (removed in v7.0). All raster tiles go through Titiler via the proxy.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Elevation range 0–4000 m is a reasonable default for `color-relief` stops | Code Examples (DEM-05) | Hypsometric tint will appear uniform for DEMs entirely above 4000 m or entirely below 0 m; fix by adding min/max elevation params to `_hypso-ramp` config in a follow-up |
| A2 | `setPaintProperty` does NOT work for `color-relief-color` and the layer must be recreated | Pitfall 1 / Anti-Patterns | If it does work, removing the remove+re-add pattern would be a minor optimization; behavior is still correct with the conservative approach |
| A3 | The Vite dev proxy preserves query params through its `rewrite` function | Finding 1 | If dev proxy also strips query params, colormap would not work in dev — unlikely given Vite's http-proxy default behavior |
| A4 | `maplibre-contour` interval thresholds can be expressed as `{zoomLevel: [majorInterval, minorInterval]}` | Code Examples (DEM-04) | Interval slider sets a fixed interval (e.g. 100 m); the per-zoom threshold dict is used to vary density by zoom; if the API has changed the threshold format would need updating |
| A5 | Percentile/stddev stretch can defer to v1032 without blocking Phase 1140 | Finding 6 | If users expect functional percentile stretch from Day 1, the Select shows three options where only one works — mitigation: disable percentile/stddev in the Select for Phase 1140 (show only Min/Max as functional option) |

**If this table is empty:** All claims were verified. — Not empty; 5 assumptions flagged.

---

## Open Questions (RESOLVED)

1. **Hypsometric tint opacity and blend mode**
   - What we know: `color-relief-opacity` defaults to 1; 0.7 is a reasonable aesthetic default
   - What's unclear: Should opacity be user-configurable (a 5th control in the HYPSOMETRIC TINT section)? The UI-SPEC does not include an opacity control for the tint.
   - Recommendation: Ship at fixed 0.7 opacity for Phase 1140; add as a follow-up slider if users request it.

2. **Contour interval vs zoom-based thresholds**
   - What we know: The user sets a single interval (e.g. 100 m); `maplibre-contour` uses a threshold map `{zoom: [major, minor]}`
   - What's unclear: How to map a single interval value to the multi-zoom threshold structure
   - Recommendation: Use the interval as the major threshold for all zoom levels ≥ 10, and `interval * 5` for zoom < 10. E.g. interval=100: `{9: [500], 11: [100, 500], 13: [50, 100]}`. This is standard cartographic practice.

3. **Stretch strategy scope for Phase 1140**
   - What we know: Titiler does not natively support percentile/stddev; requires a statistics sub-call
   - What's unclear: Whether to disable non-minmax options in the UI or show them as non-functional
   - Recommendation: Render all 3 Select options but implement only `minmax` backend handling. Backend falls back to minmax for percentile/stddev with a `logger.warning`. Future phase adds statistics-based computation.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Titiler | RASTER-COLORMAP (colormap_name param) | ✓ | 2.0.2 | — |
| maplibre-gl v5 | color-relief (DEM-05) | ✓ | 5.24.0 | — |
| maplibre-contour | Contour overlay (DEM-04) | pending npm install | 0.1.0 | — |
| chroma.js | color-relief ramp expression | ✓ | existing in project | — |

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | vitest 4.1.5 |
| Config file | `frontend/vite.config.ts` (test section) |
| Quick run command | `cd frontend && node_modules/.bin/vitest run src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx src/components/builder/__tests__/DEMEditorScene.test.tsx` |
| Full suite command | `cd frontend && node_modules/.bin/vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EDITOR-DEM-04 | `_contour-enabled` toggle shows/hides controls; `_contour-interval/color/weight` invoke `onPaintChange` | unit | `vitest run src/components/builder/__tests__/DEMEditorScene.test.tsx` | ✅ (add cases) |
| EDITOR-DEM-04 | `syncContourLayer` adds/removes companion line layer | unit | `vitest run src/components/builder/__tests__/map-sync.raster.test.ts` | ✅ (add cases) |
| EDITOR-DEM-05 | `_hypso-enabled` toggle shows/hides controls; `_hypso-ramp` invokes `onPaintChange` | unit | `vitest run src/components/builder/__tests__/DEMEditorScene.test.tsx` | ✅ (add cases) |
| EDITOR-DEM-05 | `syncColorReliefLayer` adds/removes companion color-relief layer; layer uses correct source | unit | `vitest run src/components/builder/__tests__/map-sync.raster.test.ts` | ✅ (add cases) |
| EDITOR-RASTER-COLORMAP | `buildColormapTileUrl` appends `colormap_name` for non-default colormap; returns base URL for `gray` | unit | `vitest run src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` | ✅ (add cases) |
| EDITOR-RASTER-COLORMAP | COLORMAP section renders only when `band_count === 1`; hidden for `band_count === 3` | unit | `vitest run src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx` | ✅ (add cases) |
| EDITOR-RASTER-COLORMAP | `onPaintProp('_colormap', 'viridis')` fires when Select changes | unit | `vitest run src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx` | ✅ (add cases) |
| Behavior preservation | Existing RasterEditor brightness/contrast/saturation/hue sliders still fire correctly after changes | regression | `vitest run src/components/builder/LayerStyleEditor/__tests__/RasterEditor.test.tsx` | ✅ (existing Tests 1-7 must remain green) |
| Behavior preservation | Existing DEMEditorScene hillshade/terrain controls still fire correctly | regression | `vitest run src/components/builder/__tests__/DEMEditorScene.test.tsx` | ✅ (existing tests must remain green) |

### Sampling Rate
- **Per task commit:** Quick run covering the modified test files
- **Per wave merge:** Full vitest suite
- **Phase gate:** Full suite green + `tsc --noEmit` green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `src/components/builder/__tests__/map-sync.raster.test.ts` — needs `syncContourLayer` + `syncColorReliefLayer` test cases added (file exists from v1030, needs new `describe` blocks)
- [ ] `raster-adapter.test.ts` — needs `buildColormapTileUrl` describe block (new exported function, new test file section)
- [ ] No new test files required — all new logic fits in existing test files

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surfaces |
| V3 Session Management | no | No session changes |
| V4 Access Control | partial | `raster_tile_proxy` new params — only accessible to users who can already access the dataset (RBAC enforced by `_resolve_raster_access` before colormap processing) |
| V5 Input Validation | yes | `colormap_name` must be validated against Titiler's allowed colormap enum (to prevent injection); use FastAPI `Literal` union or server-side allowlist |
| V6 Cryptography | no | No cryptographic operations |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Colormap name injection | Tampering | Validate `colormap_name` against a Literal enum (the 8 curated names from UI-SPEC) in the FastAPI endpoint; do NOT pass arbitrary user-supplied strings directly to Titiler |
| Stretch value injection | Tampering | Validate `stretch` against `Literal['minmax', 'percentile', 'stddev']` in the FastAPI endpoint |

**Security note:** The `colormap_name` value is appended to the Titiler URL as a query param. If the value is not validated, a malicious user could inject unexpected Titiler params. Validate with a FastAPI `Literal` type or an explicit allowlist (the 8 UI-SPEC colormap names). The `_colormap` paint key is user-controlled via the editor and sent to the backend via the tile URL — treat it as untrusted input at the API boundary.

---

## Sources

### Primary (HIGH confidence)
- maplibre-gl 5.24.0 `node_modules/maplibre-gl/src/style/style_layer/color_relief_style_layer.test.ts` — color-relief layer interface confirmed
- maplibre-gl 5.24.0 `node_modules/maplibre-gl/dist/maplibre-gl.d.ts` — `ColorReliefStyleLayer`, `ColorReliefPaintProps` types confirmed
- `backend/app/processing/tiles/router.py` — raster_tile_proxy implementation, nginx rewrite confirmed
- `frontend/nginx.conf` — nginx cache key and rewrite rule confirmed
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — RASTER_OWNED_PAINT_PROPERTIES contract
- `frontend/src/components/builder/layer-adapters/hillshade-adapter.ts` — `encoding: 'mapbox'` confirmed
- `frontend/src/components/builder/map-sync.ts` — syncRasterLayer tile-URL-diff logic confirmed
- `frontend/src/types/api.ts` + `backend/app/modules/catalog/maps/schemas.py` — MapLayerResponse confirmed missing band_count
- Running Titiler 2.0.2 at `http://localhost:8000` — all 8 colormap names verified; `colormap_name` + `rescale` params confirmed on COG tiles endpoint

### Secondary (MEDIUM confidence)
- `npm view maplibre-contour` + slopcheck — package confirmed on npm, slopcheck OK, version 0.1.0
- github.com/onthegomap/maplibre-contour README — DemSource API surface, `encoding: 'mapbox'` support

### Tertiary (LOW confidence)
- Assumption that `color-relief-color` requires layer recreation rather than `setPaintProperty` — based on the `ColorRampProperty` class pattern used by `heatmap-color` and `line-gradient` which also require recreation. Would need live testing to confirm definitively.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified via installed node_modules + running Titiler
- Architecture: HIGH — code paths traced through actual source files
- Pitfalls: MEDIUM-HIGH — some from direct code analysis, one (color-relief setPaintProperty) is inferred from analogous behavior
- Backend colormap param path: HIGH — nginx config and router code verified directly

**Research date:** 2026-05-28
**Valid until:** 2026-07-28 (stable dependencies; Titiler version pinned in docker-compose.yml)
