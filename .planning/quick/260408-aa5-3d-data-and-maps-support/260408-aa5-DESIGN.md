---
quick_id: 260408-aa5
authored: 2026-04-08
status: Draft for review
deliverable: design doc (no code)
---

# GeoLens 3D Data & Maps Support — Feasibility Spike

**Quick task:** 260408-aa5
**Authored:** 2026-04-08
**Status:** Draft for review

---

## 1. Overview

GeoLens users want to render 3D terrain, visualize buildings extruded from height attributes, and work with datasets that carry native PostGIS 3D geometry (Z coordinates, POINT Z, POLYGON Z, and so on). This document answers: what is the cheapest path to 3D in GeoLens using the stack that already exists, and what follow-on phases should the team create to ship it?

**Three findings drive the design:**

1. **Terrain is essentially free.** GeoLens already runs `ghcr.io/developmentseed/titiler:2.0.0`, which ships built-in `terrainrgb` and `terrarium` encoding algorithms. A user-uploaded DEM COG can be rendered as a MapLibre `raster-dem` source by appending `?algorithm=terrainrgb` to the existing tile URL — no new service, no pre-processing, no new Python dependency.

2. **Building extrusion is a single style layer added to the existing MVT pipeline.** GeoLens's `ST_AsMVT` tile service already delivers arbitrary attribute columns alongside geometries. A polygon dataset with a numeric `height` column already carries that value as an MVT feature property. A `fill-extrusion` layer that reads `["get", "height"]` renders it in 3D with zero backend changes. The hard work is UX, not data plumbing.

3. **PostGIS 3D geometry is structurally blocked at the tile boundary.** The MVT 2.1 spec is 2D-only — there is no Z axis in the protobuf encoding. `ST_AsMVTGeom` drops Z coordinates regardless of input dimensionality. This is a fundamental constraint of the tile format, not a PostGIS bug. Z values survive GeoLens ingestion today and are sitting in PostGIS, but they are invisible to every MVT consumer, including the frontend map.

**Primary recommendation:** Ship Phase A (terrain + extrusions) first — it delivers approximately 80% of the visible 3D value with 20% of the work. Phase B (PostGIS-3D detection and metadata) and Phase C (GeoJSON-Z delivery endpoint) follow in sequence, but only after Phase A proves the 3D UX path.

This is a design document. No code is shipped in this spike. The three follow-on phases described here are candidates for promotion to the ROADMAP, not commitments.

**In scope:** terrain (DEM) rendering, building extrusions via `fill-extrusion`, PostGIS 3D geometry analysis.

**Explicitly out of scope and deferred:** deck.gl overlay, 3D Tiles plugin, Cesium, true 3D meshes, point clouds, CityGML parsing, glTF model overlays, volumetric/voxel rendering.

---

## 2. Current State of GeoLens

The following facts were verified against the live codebase during planning on 2026-04-08.

**Frontend stack:** `maplibre-gl ^5.18.0` and `@vis.gl/react-maplibre ^8.1.0` (verified: `frontend/package.json`). All MapLibre v5 3D features — `raster-dem` source, `fill-extrusion` layer type, `setTerrain`, `TerrainControl`, `NavigationControl` 3D handles — are available without a version upgrade.

**Raster pipeline:** `ghcr.io/developmentseed/titiler:2.0.0` (verified: `docker-compose.yml:166-197`). Titiler 2.0.0 ships `terrainrgb` and `terrarium` as built-in algorithms, accessible by appending `&algorithm=terrainrgb` to a COG tile request. No rio-rgbify pre-processing is needed.

**MVT pipeline:** `backend/app/tiles/service.py` builds MVT tiles using `ST_AsMVT` and `ST_AsMVTGeom`. This is the 2D boundary for all vector data — no Z coordinate can survive this step (see Pillar 3).

**Ingestion (Z preservation):** `backend/app/ingest/ogr.py:319-350, 411-413` invokes ogr2ogr with `-nlt PROMOTE_TO_MULTI -lco GEOMETRY_NAME=geom`. Critically, **no `-dim` flag is set** (verified: `ogr.py:344-346, 411-413`). ogr2ogr preserves source dimensionality by default. 3D shapefiles, GeoPackages, and GeoJSON-Z files are imported with Z intact.

**4326 column (Z survives WGS84 reprojection):** `backend/app/ingest/metadata.py:452-490` creates `geom_4326 geometry(Geometry, 4326)` — the column declaration is unconstrained on dimension (verified: `metadata.py:464`). Z coordinates survive the WGS84 reprojection step as well. In summary: Z is sitting in PostGIS for every 3D dataset that has been uploaded; it is only stripped at the MVT tile delivery boundary.

**Two map components:** `frontend/src/components/viewer/ViewerMap.tsx` is the read-only public viewer used by embed tokens and share links. `frontend/src/components/builder/BuilderMap.tsx` is the editing map with layer panel, draw tools, and style editor. They share the `syncLayersToMap` helper (`frontend/src/components/builder/map-sync.ts`) and the layer adapter registry (`frontend/src/components/builder/layer-adapters/`).

**Known wrapper caveats (from project CLAUDE.md):** The `transformRequest` prop on the v8 `<Map>` component is silently ignored — GeoLens already works around this by calling `map.setTransformRequest()` imperatively in the `onLoad` callback (`ViewerMap.tsx`). Declarative `<Source type="vector">` + `<Layer>` children may fail to register vector tile sources — GeoLens already uses imperative `map.addSource()` + `map.addLayer()` everywhere. The good news for 3D: the declarative `terrain` and `sky` props on `<Map>` **do work** in v8 (verified against the react-maplibre 1.0-release terrain example). Use `terrain` prop declaratively; use imperative `addSource` + `addLayer` for the `fill-extrusion` data layer.

---

## 3. Pillar 1: Terrain (DEM) via MapLibre + Titiler

### What MapLibre native supports

MapLibre GL JS provides a dedicated `raster-dem` source type for elevation data. It accepts three encoding schemes:

| Encoding | Value | Format |
|----------|-------|--------|
| `mapbox` (default) | `elevation = -10000 + (R×65536 + G×256 + B) × 0.1` | Mapbox Terrain-RGB |
| `terrarium` | `elevation = (R×256 + G + B/256) − 32768` | Mapzen Terrarium |
| `custom` | user-specified R/G/B factors | GL JS 3.4.0+ only |

Terrain is activated via `map.setTerrain({ source: 'terrain-dem', exaggeration: 1.5 })`, or equivalently via the declarative `terrain` prop on the `<Map>` component. Standard 3D viewer configuration is `pitch: 70, maxPitch: 85`. The `NavigationControl` automatically gains pitch and rotate handles when 3D is active. The `TerrainControl` component provides a dedicated on/off toggle button.

MapLibre v4.4.0 and later computes per-polygon elevation when terrain is active, so `fill-extrusion` buildings sit correctly on uneven ground (no floating buildings at valleys).

### How Titiler closes the loop

GeoLens already serves raster tiles through `backend/app/tiles/router.py:261-291`, which builds Titiler proxy URLs. To produce a MapLibre-compatible Terrain-RGB encoded tile from any single-band float DEM COG, the only change to that URL builder is appending `&algorithm=terrainrgb`:

```
GET /cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={dem_path}&algorithm=terrainrgb
```

Titiler handles the encoding on the fly. No new container. No pre-processing. No rio-rgbify.

### What is needed to ship

**Backend (minimal):**
- Add a `is_dem` flag to the raster dataset model. The heuristic: single-band float raster + optional user override (the existing `extract_raster_metadata` in `backend/app/raster/cog.py` already records `band_info[].dtype` and `color_interp` — detection is trivial). A NDVI raster is also single-band float, so a manual override in the dataset metadata editor is recommended as a safety valve.
- When serving tiles for a `is_dem` dataset, append `&algorithm=terrainrgb` to the proxy URL in `router.py:261-291`.

**Frontend (minimal):**
- When a DEM dataset is active in the viewer, add a `raster-dem` source (encoding `mapbox`) pointing at the terrain tile URL.
- Activate terrain: pass the declarative `terrain` prop to `<Map>`, or call `map.setTerrain(...)` in the `onLoad` callback.
- Add a 3D toggle button to the viewer toolbar that transitions `pitch` from 0 to 70.

**Illustrative snippet (not shipped in this spike):**

```tsx
// illustrative only — not shipped in this spike
const terrain = { source: 'terrain-dem', exaggeration: 1.5 };
<Map pitch={70} maxPitch={85} terrain={terrain}>
  <Source id="terrain-dem" type="raster-dem"
          url="/tiles/raster-proxy/{id}/tiles.json?algorithm=terrainrgb"
          tileSize={256} />
  <TerrainControl {...terrain} position="top-left" />
</Map>
```

### Known MapLibre v5 3D bugs

| Issue | Workaround |
|-------|-----------|
| `setPaintProperty` only applies on every other call when terrain is active | Call `map.triggerRepaint()` after paint changes |
| Hillshade detail decreases when terrain is simultaneously active | Use either hillshade OR terrain, not both |
| `fill-extrusion` `setFilter` is stale until next zoom when terrain active | Call `map.triggerRepaint()` after `setFilter` |
| `setTerrain` throws at extreme negative zoom on very small map containers | Set `minZoom={1}` (already done in `ViewerMap.tsx`) |

([Source: maplibre-gl-js GitHub issues #1650, #2035, #3001, #3039](https://github.com/maplibre/maplibre-gl-js/issues/1650))

### Style-reload integration point

When the basemap style changes, `setStyle()` wipes all custom sources and layers. `ViewerMap.tsx:373-391` already has a `style.load` listener that re-syncs data layers. The terrain source and `setTerrain` call must also be re-applied in that same listener. This is a known integration point for Phase A — not a blocker, but it must be wired explicitly.

### Embed token compatibility

Terrain tiles flow through the same Titiler proxy path as standard raster tiles. The existing `X-Embed-Token` header injection in `ViewerMap.handleLoad` (which calls `map.setTransformRequest()`) already covers terrain tile requests. Embed-token-gated terrain viewers do not need new auth plumbing. Recommend a smoke test in Phase A to confirm this assumption at runtime (see Open Questions, Q4).

---

## 4. Pillar 2: Building Extrusions via fill-extrusion

### What MapLibre native supports

MapLibre's `fill-extrusion` layer type renders polygon geometry with a height dimension. The key paint properties:

| Property | Data-driven? | Notes |
|----------|--------------|-------|
| `fill-extrusion-height` | YES | Meters; driven from a feature attribute via `["get", "height"]` |
| `fill-extrusion-base` | YES | Meters from ground; for raised or floating structures |
| `fill-extrusion-color` | YES | Per-feature color from attribute |
| `fill-extrusion-opacity` | **NO — per-layer only** | Transparency is layer-wide, not per-feature; this is a caveat |
| `fill-extrusion-vertical-gradient` | NO | Boolean; auto-shading on side faces — visually free |
| `fill-extrusion-pattern` | YES | Texture fill |

([Spec: https://maplibre.org/maplibre-style-spec/layers/#fill-extrusion](https://maplibre.org/maplibre-style-spec/layers/#fill-extrusion))

### How it plugs into GeoLens

GeoLens's `ST_AsMVT` pipeline in `backend/app/tiles/service.py` returns all non-geometry attribute columns alongside the encoded geometry. A polygon dataset with a numeric `height` column already delivers `height` as an MVT feature property — **zero backend changes are required** to support building extrusions.

The frontend work lives in `frontend/src/components/builder/layer-adapters/fill-adapter.ts`. Today `fill-adapter.ts` emits a `fill` layer plus an outline `line` companion. Adding a `fill-extrusion` layer (or swapping `fill` → `fill-extrusion` when 3D mode is on) is the entirety of the data-plumbing work.

**Illustrative snippet (not shipped in this spike):**

```typescript
// illustrative only — not shipped in this spike
map.addLayer({
  id: `${layerId}-extrusion`,
  type: 'fill-extrusion',
  source: sourceId,
  'source-layer': sourceLayer,
  minzoom: 14, // performance: only extrude at building-scale zooms
  paint: {
    'fill-extrusion-height': ['coalesce', ['to-number', ['get', heightColumn], 0], 0],
    'fill-extrusion-base':   ['coalesce', ['to-number', ['get', baseColumn], 0], 0],
    'fill-extrusion-color': fillColor,
    'fill-extrusion-opacity': 0.85,
    'fill-extrusion-vertical-gradient': true,
  },
});
```

The `coalesce + to-number` wrapper handles null and string-valued attributes safely, falling back to 0.

### Height attribute conventions

Real-world datasets use a variety of column names for building height. The recommended approach is not to auto-detect: make the height column a per-layer dropdown of numeric columns in the layer style editor, with a free-form expression fallback, defaulting to off (flat fill) so existing layers do not change behavior.

| Source | Common column names | Notes |
|--------|---------------------|-------|
| OpenStreetMap | `height`, `building:height` | Numeric, meters |
| OSM (legacy) | `building:levels` | Multiply by ~3m in expression |
| OGC CityGML LOD1 | `measuredHeight` | Rare in GeoLens uploads |
| US building footprint datasets | `HEIGHT`, `Height_m`, `BLDG_HT` | Varies by dataset |

### Zero-height fallback

A polygon feature with no height data (or a null height column) extrudes to 0 via `coalesce ... 0`, rendering as a flat polygon at ground level — visually identical to the existing 2D `fill` layer. This is a safe default that preserves backwards compatibility for all existing layers.

### Terra Draw limitation

The draw tools (`terra-draw@1.25.0`, `terra-draw-maplibre-gl-adapter@1.3.0`) operate at z=0. Features drawn in the builder while 3D mode is active will land flat at ground level, not at terrain elevation. This is acceptable for v1 of the spike — flag as a known future limitation.

---

## 5. Pillar 3: PostGIS 3D Geometry Support

### What PostGIS supports

PostGIS handles a spectrum of 3D geometry types. Their practical frequency in data GeoLens users will upload:

| Type | Common in real data | Notes |
|------|---------------------|-------|
| `POINT Z` | YES | LiDAR, GPS tracks, survey points |
| `LINESTRING Z` | YES | 3D road centerlines, contour lines |
| `POLYGON Z` | YES | 3D building footprints, surveyed areas |
| `POLYHEDRALSURFACE` | RARE | CityGML LOD2 buildings, IFC exports |
| `TIN` | RARE | Triangulated irregular surfaces |
| `TRIANGLE` | VERY RARE | Component of TIN |

Practical observation: approximately 99% of "3D data" GeoLens users upload will be either XY polygons with a numeric `height` attribute, or POINT Z LiDAR-derived point clouds. POLYHEDRALSURFACE and TIN should be deferred.

### Detection functions

To classify uploaded geometry as 3D, GeoLens would use:
- `ST_NDims(geom)` — returns 2, 3, or 4
- `ST_CoordDim(geom)` — equivalent for most geometry types
- `ST_Is3D(geom)` — boolean shorthand
- `GeometryType(geom)` — returns base type string; the `Z` suffix indicates 3D (e.g. `"POLYGONZ"`)
- `ST_ZMin(geom)`, `ST_ZMax(geom)` — elevation range, useful for catalog metadata display
- `ST_Z(point)` — extract Z from a single point

Conversion helpers that would be used in the pipeline:
- `ST_Force2D(geom)` — strips Z for serving a 2D MVT fallback
- `ST_Force3D(geom)` — promotes 2D to 3D with default Z=0
- `ST_ForceSFS(geom)` — strips Z and forces OGC Simple Features (for strict clients)

([PostGIS docs: https://postgis.net/docs/ST_NDims.html](https://postgis.net/docs/ST_NDims.html))

### Current state of GeoLens (verified 2026-04-08)

Z coordinates survive GeoLens ingestion because ogr2ogr has no `-dim` flag (`backend/app/ingest/ogr.py:344-346, 411-413`). They survive the WGS84 reprojection step because `geom_4326` is declared `geometry(Geometry, 4326)` without a dimension constraint (`backend/app/ingest/metadata.py:464`). **Z values are sitting in PostGIS right now for any 3D dataset that has been uploaded.** They are invisible to users and invisible to the MVT pipeline, but the data is there.

### The critical finding: ST_AsMVT is 2D-only

The Mapbox Vector Tile specification v2.1 defines only X and Y axes with integer coordinates:

> "The X axis is positive to the right, the Y axis is positive downward. [...] Coordinates within a geometry MUST be integers."

There is no Z axis in the protobuf encoding, no `MoveToZ` command, and no provision for elevation in the tile format. `ST_AsMVTGeom` produces 2D output regardless of input dimensionality. **This is a structural limitation of the tile format, not a PostGIS bug.**

([MVT 2.1 spec: https://github.com/mapbox/vector-tile-spec/blob/master/2.1/README.md](https://github.com/mapbox/vector-tile-spec/blob/master/2.1/README.md))

**Implications for GeoLens:**
- A PostGIS table with `POLYGON Z` features tiles correctly through the existing pipeline, but all rendered geometries are flat at z=0. Z is silently dropped at the tile boundary.
- Building extrusions (Pillar 2) work around this by carrying height as a **numeric attribute** in an MVT feature property, not as geometry Z. That is why Pillar 2 requires zero backend changes.
- True 3D geometry delivery to the client requires a parallel, non-MVT path.

### Three strategies for exposing 3D geometry to the client

**Strategy 1 — Attribute promotion (cheapest).**
At ingest, if `ST_Is3D(geom)` is true and the geometry is point-like, extract `ST_Z(geom)` into a new `elev` numeric column. The existing MVT pipeline carries `elev` as a normal feature property. The frontend reads it via `["get", "elev"]` for symbolization or as a height source. This loses Z for non-point geometries (lines and polygons), but gives 3D symbolization for LiDAR point datasets at essentially zero cost.

**Strategy 2 — GeoJSON-Z streaming endpoint.**
Add a new `/api/datasets/{id}/features.geojson?include_z=true` endpoint that returns RFC 7946 GeoJSON with three-coordinate positions. MapLibre GeoJSON sources accept and pass through Z coordinates. Best suited for small datasets (recommended cap: 5,000 features). No tiling, no LOD, no server-side caching — this is a "preview first N features in 3D" affordance, not a production tile path.

**Strategy 3 — Custom binary format (deferred, out of scope).**
3D Tiles, glTF, or CesiumJS pipeline. Out of scope per project decisions (CONTEXT.md). Named here so readers understand what was considered and deferred.

### POLYHEDRALSURFACE / TIN

PostGIS accepts `POLYHEDRALSURFACE` and `TIN` geometry today, and GeoLens's unconstrained `geometry(Geometry, 4326)` column stores them without error. However, rendering them correctly requires a 3D Tiles or glTF pipeline — both out of scope for this spike. If a user uploads CityGML or a TIN file, the current pipeline will ingest it, but the frontend will render only the 2D projection. Flag as a deferred decision and add to STATE.md when Phase B is promoted.

### Web Mercator clipping note

`backend/app/ingest/metadata.py:432` clips geometries to ±85.06° latitude (Web Mercator bounds). DEMs of polar regions would be cropped. Out of scope for this spike but worth noting for future DEM support work.

---

## 6. Gaps & Limitations

| # | Limitation | Pillar | Severity | Notes |
|---|------------|--------|----------|-------|
| 1 | ST_AsMVT strips Z — MVT 2.1 spec is 2D-only | PostGIS 3D | **HIGH** | Structural; requires a non-MVT delivery path (GeoJSON-Z endpoint or attribute promotion) |
| 2 | No `is_dem` flag on raster datasets today | Terrain | MEDIUM | New detection heuristic + `is_dem` column needed; a NDVI raster is also single-band float so a manual override is required |
| 3 | Terra Draw draws at z=0 only | Extrusions | LOW | Drawn features land flat in 3D mode. Acceptable for v1; flag as known limitation |
| 4 | Pitch/rotate gestures are not keyboard-accessible | Terrain / All | LOW for v1, MEDIUM long-term | Mouse/touch gestures only; flag for the Phase 217 accessibility audit |
| 5 | Polar DEMs cropped by Mercator bounds clip | Terrain | LOW | Out of scope for this spike |
| 6 | POLYHEDRALSURFACE / TIN rendering requires 3D Tiles or glTF | PostGIS 3D | LOW | Defer to future milestone |
| 7 | `transformRequest` prop silently ignored on v8 `<Map>` | All frontend | Already mitigated | Existing `map.setTransformRequest()` call in `ViewerMap.tsx onLoad` covers terrain tiles |
| 8 | Declarative `<Source type="vector">` + `<Layer>` sometimes fails | Extrusions | Already mitigated | Use imperative `map.addSource()` + `map.addLayer()` for `fill-extrusion` layers |
| 9 | `setStyle()` wipes terrain source; needs re-sync on basemap change | Terrain | MEDIUM | Add terrain source + `setTerrain` re-application to the existing `style.load` hook in `ViewerMap.tsx:373-391` |
| 10 | `setPaintProperty` every-other-call bug when terrain is active | Terrain | LOW | Call `map.triggerRepaint()` after paint changes as a workaround |

### What MapLibre native cannot do

The following capabilities are outside MapLibre GL JS's native feature set. They are deferred to future milestones and are **not** part of any recommendation in this document:

- True 3D meshes (no mesh primitive in the MapLibre style spec)
- Point clouds (no point-cloud source type in MapLibre)
- 3D Tiles (no built-in parser; requires a third-party plugin such as `3d-tiles-renderer`)
- CityGML LOD2+ building rendering (no built-in CityGML parser)
- glTF model overlays (no built-in glTF support)
- Volumetric and voxel rendering

**Alternatives deferred to future milestones:** deck.gl overlay, 3D Tiles plugin (e.g. `3d-tiles-renderer`), CesiumJS. These are named here so readers know they were considered and excluded from the first slice.

---

## 7. Recommended Follow-on Phases

The table below is a decision-ready breakdown. Each phase is sized independently and can be promoted to a ROADMAP entry if the team decides to proceed. See Open Questions — all listed questions must be resolved before promotion.

| Phase | Scope | Sizing | Dependencies | Rough Task Count | Recommendation |
|-------|-------|--------|--------------|-----------------|----------------|
| **Phase A: 3D Viewer Toggle (Terrain + Extrusions)** | Frontend-only. Viewer toolbar 3D toggle button (pitch 0→70). `raster-dem` source attached to any dataset flagged `is_dem`; `setTerrain` call. `fill` → `fill-extrusion` swap for any layer with a configured `height_column`. Height column picker dropdown in the layer style editor. Backend minimal: add `&algorithm=terrainrgb` to the proxy URL for DEM datasets + `is_dem` flag. Ship viewer only; defer `BuilderMap.tsx` support. | **MEDIUM** | None — works on existing data already in PostGIS | ~5–8 tasks | **Ship first.** Delivers ~80% of visible "3D support" value with ~20% of the work. |
| **Phase B: PostGIS 3D Geometry Detection & Metadata** | Backend. Add `ST_NDims` / `ST_Is3D` checks to the post-ingest pipeline. Record dimensionality and Z range (`ST_ZMin`, `ST_ZMax`) on the dataset record. Expose in dataset detail UI ("This dataset has 3D geometry — Z range: 12m to 847m"). Decide on attribute-promotion strategy (`elev` column) for point geometries. Alembic migration for the dataset model. | **MEDIUM** | None — can parallelize with Phase A | ~6–10 tasks | **Ship second**, after Phase A proves the 3D UX path. Parallelizing with Phase A is feasible. |
| **Phase C: Expose 3D Geometry to Client (GeoJSON-Z Endpoint)** | Backend + frontend. New `/api/datasets/{id}/features.geojson?include_z=true` endpoint streaming RFC 7946 three-coordinate positions. Full auth + RBAC parity with existing endpoints. Feature count cap (recommended: 5,000). Frontend decision logic: use GeoJSON source for 3D-aware small datasets; fall back to MVT for large datasets. "Preview in 3D" affordance in the dataset detail view. | **LARGE** | Phase B — requires the `is_3d` and dimensionality metadata from Phase B | ~10–15 tasks | **Defer until user demand justifies.** Phase A + Phase B cover 95% of the practical value. |

**Recommended sequencing:** Phase A first, then Phase B (can overlap), then evaluate whether Phase C is justified before committing resources.

```
Phase A (terrain + extrusions)
  → ship
  → gather feedback
Phase B (PostGIS-3D detection + metadata)   ← can start in parallel with Phase A
  → ship
  → re-evaluate before committing to Phase C
Phase C (GeoJSON-Z endpoint)                ← only if user demand justifies
```

Phase A and Phase B share zero code paths. They can be scheduled sequentially or run in parallel by different team members.

---

## 8. Open Questions

These questions must be resolved before any of Phases A, B, or C is promoted to a real ROADMAP entry.

1. **3D toggle UX: per-session vs. persisted?**
Should the 3D mode toggle persist on the layer or dataset record, or reset to 2D each session? Persisting requires a new column on the `MapLayer` model and a migration. Recommendation: session-only for v1 to avoid schema changes. Re-evaluate after Phase A user feedback.

2. **DEM detection heuristic: automatic or explicit?**
Is "single float band" sufficient to flag a raster as a DEM, or should we require an explicit checkbox at upload time? A NDVI raster is also single-band float and would be mis-flagged. Recommendation: soft heuristic (single float band, name/tag pattern) plus a manual override toggle in the dataset metadata editor.

3. **Default terrain exaggeration: fixed or adjustable?**
Should terrain exaggeration be hardcoded or exposed as a user-adjustable slider? The react-maplibre official example uses `1.5`. MapTiler tutorials show values between 1.0 and 2.5. Recommendation: hardcode `1.5` for the Phase A spike; add a "Terrain Exaggeration" slider in a later UI polish pass.

4. **Embed token compatibility with terrain tiles: verified at runtime?**
The embed-token analysis above (Section 3) concludes that terrain tiles flow through the existing `X-Embed-Token` proxy path and need no new auth plumbing. This was verified by code reading only. Recommendation: add a smoke test for embed-token-gated terrain rendering to the Phase A acceptance criteria.

5. **Height column backwards compatibility on re-upload.**
If a layer is styled with `fill-extrusion-height: ["get", "height"]` and a future re-upload removes the `height` column, the `coalesce ... 0` fallback degrades gracefully to flat polygons — but the layer config is silently stale. Recommendation: surface a warning in the layer style editor when a bound column is absent, using the existing schema-diff preview infrastructure (precedent from v1.5).

6. **POLYHEDRALSURFACE / TIN handling.**
If a user uploads CityGML or a TIN file, the current pipeline accepts it and PostGIS stores it correctly. Rendering it requires 3D Tiles or glTF — out of scope. Add a deferred-decision item to STATE.md when Phase B is promoted: decide whether to surface a UI warning for these geometry types or silently render their 2D projection.

7. **Builder map (edit mode) 3D support: Phase A or later?**
`BuilderMap.tsx` and `ViewerMap.tsx` share the layer adapter registry, but the builder has draw tools and a style editor that both need 3D-mode awareness. Recommendation: ship Phase A in `ViewerMap.tsx` only; defer `BuilderMap.tsx` 3D support to a follow-on phase.

---

## 9. References

### Primary (HIGH confidence — verified against official sources)

- **MapLibre raster-dem source spec:** https://maplibre.org/maplibre-style-spec/sources/#raster-dem
- **MapLibre fill-extrusion paint spec:** https://maplibre.org/maplibre-style-spec/layers/#fill-extrusion
- **MapLibre 3D terrain example:** https://maplibre.org/maplibre-gl-js/docs/examples/3d-terrain/
- **react-maplibre v8 terrain example (source code):** https://github.com/visgl/react-maplibre/tree/1.0-release/examples/terrain
- **Titiler algorithms guide (terrainrgb, terrarium, hillshade):** https://developmentseed.org/titiler/user_guide/algorithms/
- **Titiler /cog endpoint reference:** https://developmentseed.org/titiler/endpoints/cog/
- **MVT 2.1 specification (2D-only confirmation):** https://github.com/mapbox/vector-tile-spec/blob/master/2.1/README.md
- **PostGIS ST_Force2D / ST_Force3D / ST_NDims docs:** https://postgis.net/docs/ST_Force2D.html, https://postgis.net/docs/ST_Force3D.html, https://postgis.net/docs/ST_CoordDim.html
- **PostGIS ST_AsMVT / ST_AsMVTGeom docs:** https://postgis.net/docs/ST_AsMVT.html, https://postgis.net/docs/ST_AsMVTGeom.html
- **Mapbox Terrain-RGB encoding spec:** https://docs.mapbox.com/data/tilesets/guides/access-elevation-data/

### Verified during planning 2026-04-08

The following four specific claims were verified against the live GeoLens codebase during the planning phase:

| Claim | Verified location |
|-------|------------------|
| Titiler version `2.0.0` | `docker-compose.yml:167` — image tag `ghcr.io/developmentseed/titiler:2.0.0` |
| `@vis.gl/react-maplibre ^8.1.0` + `maplibre-gl ^5.18.0` | `frontend/package.json` |
| No `-dim` flag in ogr2ogr invocation (Z survives ingestion) | `backend/app/ingest/ogr.py:344-346, 411-413` |
| `geom_4326 geometry(Geometry, 4326)` unconstrained on dimension (Z survives reprojection) | `backend/app/ingest/metadata.py:464` |

**GeoLens code paths referenced in this document:**

- `frontend/src/components/viewer/ViewerMap.tsx` — read-only viewer; terrain toggle and 3D UX land here first
- `frontend/src/components/builder/BuilderMap.tsx` — editing map; deferred for Phase A
- `frontend/src/components/builder/layer-adapters/fill-adapter.ts` — extrusion companion layer integration point
- `frontend/src/components/builder/layer-adapters/raster-adapter.ts` — DEM source branching
- `frontend/src/components/builder/map-sync.ts` — `syncLayersToMap` helper shared by viewer and builder
- `frontend/src/lib/basemap-utils.ts` — theme + basemap integration surface
- `backend/app/tiles/router.py:261-291` — Titiler proxy URL builder (where `&algorithm=terrainrgb` would be added)
- `backend/app/tiles/service.py` — `ST_AsMVT` / `ST_AsMVTGeom` call site (the 2D tile boundary)
- `backend/app/ingest/ogr.py:319-350, 411-413` — ogr2ogr invocation (no `-dim` flag, Z survives)
- `backend/app/ingest/metadata.py:452-490` — `add_4326_column` (declares `geometry(Geometry, 4326)`, unconstrained on dimension)
- `backend/app/raster/cog.py` — `extract_raster_metadata` (where `is_dem` heuristic would live)
- `docker-compose.yml:166-197` — titiler service definition

### Secondary (MEDIUM confidence — community sources, cross-verified)

- **MapLibre 3D buildings example (fill-extrusion height interpolation pattern):** https://harelm.github.io/maplibre-docs-test/examples/3d-buildings/
- **MapTiler 3D map tutorial:** https://docs.maptiler.com/guides/maps-apis/maps-platform/how-to-build-a-3d-map-with-maplibre-v2-gl-js/
- **Sparkgeo blog: 3D shapefile import to PostGIS with ogr2ogr (verifies Z preservation):** https://sparkgeo.com/blog/ogr2ogr-3d-shapefile-import-to-postgis-tip/
- **MapLibre fill-extrusion + terrain known issues (GitHub):** https://github.com/maplibre/maplibre-gl-js/issues/1650, https://github.com/maplibre/maplibre-gl-js/issues/2035, https://github.com/maplibre/maplibre-gl-js/issues/3001, https://github.com/maplibre/maplibre-gl-js/issues/3039
