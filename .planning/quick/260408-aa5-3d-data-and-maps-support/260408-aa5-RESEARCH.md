---
quick_id: 260408-aa5
gathered: 2026-04-08
status: Ready for design doc
confidence: HIGH
---

# Quick Task 260408-aa5: 3D Data & Maps Support — Research

**Researched:** 2026-04-08
**Domain:** GIS 3D rendering & data model — MapLibre native + PostGIS + Titiler
**Confidence:** HIGH

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Deliverable is a design document, not code.** Output is a `.md` file in the quick task directory; no backend/frontend changes shipped.
- **Three pillars must be covered:** terrain (DEM), building extrusions, PostGIS 3D geometry.
- **Rendering target: MapLibre native** (terrain + fill-extrusion). No new rendering dependencies.
- **Doc must close with a recommended follow-on phase breakdown** so the team can promote it to ROADMAP entries.
- **What MapLibre native cannot do** (true 3D meshes, point clouds, 3D Tiles, CityGML, glTF) is explicitly out of scope and deferred to future milestones.

### Claude's Discretion
- Depth of investigation per pillar (actionable, not exhaustive).
- Output file location: `260408-aa5-DESIGN.md` in the same directory.
- Doc structure (suggested: Overview → Current State → Per-Pillar Analysis → Gaps → Recommended Phases → Open Questions).
- Whether to include small illustrative code snippets (yes).
- Whether to reference external libraries, specs, blog posts (yes — research deliverable).

### Deferred Ideas (OUT OF SCOPE)
- deck.gl overlay, 3D Tiles plugin, Cesium.
- True 3D meshes, point clouds, CityGML, glTF.
- Any actual implementation work — this is a spike only.

## Summary

GeoLens is unusually well-positioned for a MapLibre-native 3D first slice. Three findings drive the design:

1. **Terrain is essentially free.** GeoLens already runs `ghcr.io/developmentseed/titiler:2.0.0`, which ships built-in `terrainrgb` and `terrarium` algorithms for elevation encoding. A user-uploaded DEM COG can be rendered as a MapLibre `raster-dem` source by appending `?algorithm=terrainrgb` to the existing tile URL pattern. No new service, no new code path on the backend, no rio-rgbify pre-processing. [VERIFIED: titiler docs + GeoLens docker-compose.yml + GeoLens raster pipeline at backend/app/raster/cog.py]

2. **Building extrusion is a single style-layer added to the existing MVT pipeline.** GeoLens's ST_AsMVT tile pipeline (`backend/app/tiles/service.py`) already serves arbitrary attribute columns alongside geometries. A `fill-extrusion` layer that reads `["get", "height"]` from MVT properties would render any polygon dataset with a numeric `height` column in 3D — zero backend changes. The hard problem is UX (height column picker, viewer toggle), not data plumbing. [VERIFIED: GeoLens tile service code + MapLibre style spec]

3. **PostGIS 3D geometry is structurally blocked at the tile boundary.** The MVT 2.1 spec is 2D-only ("X axis is positive to the right, Y axis is positive downward" — no Z). `ST_AsMVTGeom` therefore drops Z. GeoLens's current `geom_4326` column is declared as base `Geometry` (no dimension constraint), so Z values from a 3D source survive ingestion — but they're invisible to MVT consumers. Exposing 3D geometry to the client requires a parallel non-MVT endpoint (GeoJSON-Z stream) or an attribute-promotion strategy (extract Z into a numeric column at ingest, then read it via `["get", "elev"]`). [VERIFIED: MVT 2.1 spec + PostGIS docs + GeoLens add_4326_column at backend/app/ingest/metadata.py:452]

**Primary recommendation:** Ship terrain and building-extrusion as a single small frontend phase first (Phase A). Defer the PostGIS-3D geometry story to a separate, larger backend phase (Phase B) because it touches ingestion, the catalog model, and a new endpoint shape. The two phases share zero code paths and can be sequenced or parallelized freely.

## Pillar 1: MapLibre Native 3D Capabilities

### Stack confirmation (verified in `frontend/package.json`)
- `maplibre-gl@5.18.0` (current published 5.22.0) [VERIFIED: npm view + frontend/package.json]
- `@vis.gl/react-maplibre@8.1.0` [VERIFIED: frontend/package.json]
- All MapLibre v5 3D features are available; no upgrade needed for the spike.

### Terrain — `raster-dem` source + `setTerrain`
| Property | Value |
|----------|-------|
| Source type | `raster-dem` |
| Encoding values | `mapbox` (default — Mapbox Terrain-RGB), `terrarium` (Mapzen), `custom` (redFactor/blueFactor/greenFactor/baseShift) |
| `tileSize` default | 512 |
| Browser support | `mapbox` and `terrarium` work in MapLibre GL JS, Native Android, Native iOS. `custom` is GL JS only (3.4.0+). |
| Activation | `map.setTerrain({source: 'terrain-dem', exaggeration: 1.5})` — exaggeration is a vertical scale multiplier |

[CITED: https://maplibre.org/maplibre-style-spec/sources/#raster-dem]

### Fill-extrusion — paint properties available in v5
| Property | Data-driven? | Notes |
|----------|--------------|-------|
| `fill-extrusion-height` | YES (feature-state + interpolate) | Meters; reads from feature attribute via `["get", "height"]` |
| `fill-extrusion-base` | YES | Meters; for floating buildings or floors above ground |
| `fill-extrusion-color` | YES | Per-feature color from attribute |
| `fill-extrusion-opacity` | NO — per-layer only | **Caveat:** transparency is layer-wide, not per-feature |
| `fill-extrusion-pattern` | YES | Texture fill |
| `fill-extrusion-vertical-gradient` | NO — boolean only | Auto-shading on side faces |
| `fill-extrusion-translate` | NO | Offset in screen pixels |

[CITED: https://maplibre.org/maplibre-style-spec/layers/#fill-extrusion]

**MapLibre v4.4.0+ improvement:** filled extrusions now calculate elevation per polygon when terrain is enabled, so buildings sit correctly on uneven ground. [VERIFIED: maplibre-gl-js GitHub issues]

### Camera / pitch / bearing
- 3D mode is unlocked by `pitch > 0` and `maxPitch ≤ 85` on the Map component.
- Standard 3D viewer config: `pitch: 70, maxPitch: 85` — matches the official MapLibre 3D terrain example.
- The `NavigationControl` automatically gains rotate/pitch handles when 3D is in play. `TerrainControl` exists as a dedicated toggle button (also used by react-maplibre's official example).
- No keyboard accessibility regression — pitch/bearing are mouse/touch gestures; existing keyboard zoom/pan still works.

### @vis.gl/react-maplibre v8 — first-class 3D support
**Critical finding (good news):** Unlike `transformRequest` (which CLAUDE.md notes is silently ignored on the v8 `<Map>` component), `terrain` and `sky` ARE proper declarative props. The official react-maplibre 1.0-release example uses them:

```tsx
import { Map, Source, TerrainControl } from '@vis.gl/react-maplibre';
import type { Terrain, Sky } from '@vis.gl/react-maplibre';

const terrain: Terrain = { source: 'terrain-dem', exaggeration: 1.5 };
const sky: Sky = {
  'sky-color': '#80ccff',
  'sky-horizon-blend': 0.5,
  'horizon-color': '#ccddff',
  // ...
};

<Map ... pitch={70} maxPitch={85} terrain={terrain} sky={sky}>
  <Source id="terrain-dem" type="raster-dem"
          url="https://.../tiles.json" tileSize={256} />
  <TerrainControl {...terrain} position="top-left" />
</Map>
```

[VERIFIED: https://raw.githubusercontent.com/visgl/react-maplibre/1.0-release/examples/terrain/src/app.tsx]

**However:** The known v8 caveat about `<Source type="vector">` + `<Layer>` children sometimes failing (per CLAUDE.md) means GeoLens's existing imperative `map.addSource()` + `map.addLayer()` pattern (in `BuilderMap.tsx` and `ViewerMap.tsx`) should be preserved for the new `fill-extrusion` layer. Stick to imperative for the data layer; declarative `terrain` prop is fine for the basemap-side 3D config.

### Known MapLibre v5 3D bugs (flag in design doc)
| Issue | Impact | Workaround |
|-------|--------|-----------|
| `setTerrain` throws at extreme negative zoom on small maps | Very low — only happens at min zoom edge cases | Set sensible `minZoom` (already `minZoom={1}` in ViewerMap) |
| `setPaintProperty` only applies on every other call when terrain is active | Can break dynamic style updates | Force a `triggerRepaint()` or movement after paint changes |
| Hillshade detail decreases when terrain is enabled simultaneously | Visual quality regression if both layers stack | Use either hillshade OR terrain, not both (or accept the look) |
| `fill-extrusion` layers ignore `setFilter` calls until next zoom | Filter UX feels stale | Call `map.triggerRepaint()` after `setFilter` on extrusion layers |

[VERIFIED: maplibre/maplibre-gl-js GitHub issues #1650, #2035, #3001, #3039]

## Pillar 2: PostGIS 3D Geometry Support

### What PostGIS supports (relevant to GeoLens)
| Type | Common in real data | GeoLens ingestion path |
|------|---------------------|------------------------|
| `POINT Z` | YES (LiDAR, GPS, surveying) | Survives ogr2ogr → PostGIS via GeoLens's current ingest |
| `LINESTRING Z` | YES (3D road centerlines, contour lines) | Survives |
| `POLYGON Z` | YES (3D building footprints, terrain triangles, CAD exports) | Survives |
| `POLYHEDRALSURFACE` | RARE (CityGML LOD2 buildings, IFC) | Untested in GeoLens |
| `TIN` | RARE (3D triangulated surfaces) | Untested |
| `TRIANGLE` | VERY RARE (component of TIN) | Untested |

**Practical observation:** 99% of "3D data" in the wild that GeoLens users will upload is just XY polygons + a `height` attribute, or POINT Z LiDAR-derived data. POLYHEDRALSURFACE / TIN should be flagged as "future, not first slice."

### Detection functions GeoLens needs
- `ST_NDims(geom)` — returns 2, 3, or 4. Use this in ingestion to detect Z-bearing geometries.
- `ST_CoordDim(geom)` — same as ST_NDims for most cases.
- `ST_Is3D(geom)` — boolean shorthand.
- `GeometryType(geom)` — returns base type as string (e.g. "POLYGON", "POLYGONZM"); the `Z` suffix indicates 3D.
- `ST_ZMin(geom)`, `ST_ZMax(geom)` — extract elevation range, useful for the catalog metadata card.
- `ST_Z(point)` — extract Z from a single point (useful for promoting Z to an attribute column).

### Conversion / casting
- `ST_Force2D(geom)` — strips Z. Useful for serving a 2D fallback through MVT.
- `ST_Force3D(geom)` — promotes 2D to 3D, default Z = 0. Mostly for testing.
- `ST_ForceSFS(geom)` — strips Z and forces to OGC Simple Features.

[CITED: https://postgis.net/docs/ST_Force2D.html, https://postgis.net/docs/ST_NDims.html]

### Critical gap: ST_AsMVT is 2D-only — CONFIRMED
The Mapbox Vector Tile spec v2.1 is **structurally 2D**: "Coordinates within a geometry MUST be integers" and "the X axis is positive to the right, the Y axis is positive downward" — there is no Z axis in the protobuf encoding, no `MoveToZ` command, no provision for elevation. `ST_AsMVTGeom` consequently produces 2D output regardless of input dimensionality. PostGIS does not document this explicitly, but it is forced by the spec.

**Implications for GeoLens:**
- A PostGIS table with `POLYGON Z` features will tile correctly through the existing pipeline, but **all rendered geometries will be flat at z=0** — Z is silently dropped at the tile boundary.
- The current `geom_4326 geometry(Geometry, 4326)` column declaration in `add_4326_column` (`backend/app/ingest/metadata.py:452`) is **unconstrained on dimension**, so Z survives ingestion. The data is in PostGIS; only the delivery pipeline strips it.
- Three viable options for exposing 3D data to the client:
  1. **Attribute promotion (cheapest):** During ingest, if `ST_Is3D(geom)` and the geometry is point-like, write `ST_Z(geom)` into a new `elev` numeric column. The MVT pipeline carries the column as a normal attribute. Frontend reads it via `["get", "elev"]` for symbolization or extrusion. Loses Z for non-point geometries.
  2. **GeoJSON-Z streaming endpoint:** Add a new `/api/datasets/{id}/features.geojson` endpoint that returns RFC 7946 GeoJSON with three-coordinate positions. RFC 7946 §3.1.1 technically allows altitude as the third coordinate but discourages it. MapLibre GeoJSON sources accept and pass through Z, and `fill-extrusion-height` can read the Z via expressions if needed. Best for small datasets only — no tiling, no LOD, no cache. Use for "preview the first 1000 features in 3D" UX.
  3. **Custom binary format (deferred):** 3D Tiles, glTF, or CesiumJS — out of scope per CONTEXT.md.

[VERIFIED: https://github.com/mapbox/vector-tile-spec/blob/master/2.1/README.md]

### How ogr2ogr currently handles Z in GeoLens
GeoLens runs ogr2ogr with `-nlt PROMOTE_TO_MULTI -lco GEOMETRY_NAME=geom` (see `backend/app/ingest/ogr.py:319-350`). Behavior:
- **No `-dim` flag is set** → ogr2ogr preserves the source dimensionality by default. 3D shapefiles, GeoPackages, and GeoJSON-Z files import with Z intact.
- **`PROMOTE_TO_MULTI` does not strip Z** — it only changes single → multi geometry types.
- The PostGIS column is created without an explicit `geometry(POLYGON, 4326)` constraint on dimension because GeoLens's `add_4326_column` declares it as base `Geometry`. Z survives.
- **Currently invisible to users:** Once ingested, no part of the GeoLens UI exposes the fact that the geometry has Z.

[VERIFIED: backend/app/ingest/ogr.py:319-350 + backend/app/ingest/metadata.py:452-490 + GDAL ogr2ogr docs via web search]

## Pillar 3: Terrain Pipeline for GeoLens (DEM → Viewer)

### The cheapest possible win: Titiler already does it
**Major finding:** GeoLens runs `ghcr.io/developmentseed/titiler:2.0.0` (verified in `docker-compose.yml`). Titiler ships **two built-in terrain encoding algorithms** that take a normal single-band DEM COG and produce MapLibre-compatible RGB-encoded elevation tiles on the fly:

| Algorithm | Format | Use with |
|-----------|--------|----------|
| `terrainrgb` | Mapbox Terrain-RGB (`elevation = -10000 + (R*65536 + G*256 + B) * 0.1`) | `encoding: 'mapbox'` (default) |
| `terrarium` | Mapzen Terrarium | `encoding: 'terrarium'` |

[VERIFIED: https://developmentseed.org/titiler/user_guide/algorithms/]

**Activation pattern (no code changes to Titiler container):**
```
GET /cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url={dem_path}&algorithm=terrainrgb
```

GeoLens's existing raster proxy (`backend/app/tiles/router.py:261-291`) already builds Titiler URLs in this exact form. Adding terrain support requires only:
- An additional query-string parameter (`&algorithm=terrainrgb`) when the dataset is flagged as a DEM, AND
- A new dataset flag/tag indicating "this is a DEM, render as terrain" (could be auto-detected: single float band + name/tag heuristic).

**No new Python dependencies. No rio-rgbify pre-processing. No new service.** This is the single most important finding in this research.

### What's required to make a GeoLens DEM render as terrain in MapLibre
1. **Backend (minimal):**
   - Detect single-band float DEMs at ingest. The current `extract_raster_metadata` in `backend/app/raster/cog.py` already records `band_info[].dtype` and `color_interp` — adding a `is_dem` heuristic is trivial.
   - Add an `&algorithm=terrainrgb` parameter to the `/tiles/raster-proxy/...` URL when serving a flagged DEM.
   - Optionally expose a new tile URL variant (e.g. `/tiles/dem/{id}/{z}/{x}/{y}.png`) so the frontend can distinguish "render as visual raster" from "render as elevation source."

2. **Frontend (minimal):**
   - Add a `<Source type="raster-dem" encoding="mapbox">` when a DEM dataset is added to the viewer.
   - Call `map.setTerrain({source: 'dem-source-id', exaggeration: 1})` (or use the declarative `terrain` prop on `<Map>`).
   - Add a 3D toggle button to the viewer toolbar (transition pitch from 0 → 70).

3. **Pre-processing (optional, only for non-COG sources):**
   - For DEMs already uploaded as plain GeoTIFFs, GeoLens's existing `check_and_prepare_cog` (in `backend/app/raster/cog.py`) already converts them to COG. No change needed.
   - If a user uploads a DEM in non-Web-Mercator projection, Titiler reprojects on the fly. No pre-processing required for the spike.

### Alternatives considered (and rejected for the spike)
| Tool | Why rejected |
|------|--------------|
| `rio-rgbify` | Pre-baked tile generation; Titiler does the same on the fly |
| `titiler-mosaic` | Useful for multi-DEM mosaics; defer until users have multiple DEMs |
| Standalone `terrain-rgb-generator` | No reason to add a new container when titiler 2.0 already has it |

## Pillar 4: Building Extrusion from Existing GeoLens Vector Data

### How it plugs into the existing pipeline
GeoLens's MVT pipeline (`backend/app/tiles/service.py`) returns all non-geometry attribute columns alongside the encoded geometry. A polygon dataset with a numeric `height` column will already deliver `height` as an MVT feature property — no backend change.

The frontend `fill-adapter.ts` currently emits a `fill` layer + outline `line` companion layer. Adding a third companion `fill-extrusion` layer (or replacing the fill type when "3D mode" is on) is straightforward:

```typescript
map.addLayer({
  id: `${layerId}-extrusion`,
  type: 'fill-extrusion',
  source: sourceId,
  'source-layer': sourceLayer,
  minzoom: 14, // performance: only extrude at building-scale zooms
  paint: {
    'fill-extrusion-height': ['coalesce', ['to-number', ['get', heightColumn], 0], 0],
    'fill-extrusion-base': ['coalesce', ['to-number', ['get', baseColumn], 0], 0],
    'fill-extrusion-color': fillColor,
    'fill-extrusion-opacity': 0.85,
    'fill-extrusion-vertical-gradient': true, // free face shading
  },
});
```

The `coalesce + to-number` wrapper handles null/string values from the MVT payload safely.

### Height attribute conventions
| Source | Convention | Notes |
|--------|-----------|-------|
| OpenStreetMap | `height` (numeric, meters) and `building:height` | Already parsed as meters by tools like osm2pgsql |
| OSM (legacy) | `building:levels` × ~3m per level | Frontend can compute on the fly via `["*", ["get", "levels"], 3]` |
| OGC CityGML LOD1 | `measuredHeight` | Rare in GeoLens uploads |
| US Building Footprint datasets | varies — `HEIGHT`, `Height_m`, `BLDG_HT` | Make column user-selectable |

**Recommended pattern:** Don't auto-detect a "height column." Make it a per-layer style choice in the layer style editor: a dropdown listing all numeric columns, with a free-form fallback expression. Default to off (flat fill) so existing layers don't change behavior.

### The "zero-height" fallback
A polygon with no height data (or `null` in the height column) will extrude to 0 with `coalesce ... 0`, which renders as a flat polygon at ground level — visually identical to the existing 2D fill. Safe default.

## Gotchas & Pitfalls Specific to GeoLens

### React wrapper bugs (from CLAUDE.md + research)
| Issue | Affects | Mitigation |
|-------|---------|------------|
| `transformRequest` prop silently ignored on `<Map>` v8 | All custom auth/header injection | Already mitigated: `ViewerMap.tsx:199` calls `map.setTransformRequest()` in `onLoad`. The 3D phase doesn't add new transformRequest needs. |
| `<Source type="vector">` + `<Layer>` declarative children may fail to add tiles | Existing vector layer rendering | Already mitigated: GeoLens uses imperative `map.addSource()` + `map.addLayer()` (see `BuilderMap.tsx` and `ViewerMap.tsx`). Continue this pattern for fill-extrusion. |
| **NEW for 3D:** declarative `terrain` and `sky` props on `<Map>` work fine in v8 | New 3D phase | Use them. They're the only sane way to wire terrain to a React component tree. |

### Theme & basemap integration
GeoLens's theme system (`getThemeBasemap`, `findBasemapById`, `toMaplibreStyle` in `frontend/src/lib/basemap-utils.ts`) auto-switches between light/dark basemap styles when the theme changes. Adding terrain is orthogonal — terrain uses a separate raster-dem source and doesn't conflict with the basemap style.

**One concern:** When the basemap style changes (`<MapGL styleDiffing={false}>` triggers `setStyle()`, which wipes all custom sources/layers), the existing `style.load` listener in `ViewerMap.tsx:373-391` re-syncs data layers. The terrain source and `setTerrain` call would also need to be re-applied on `style.load`. Add to the design doc as a known integration point.

### Mobile performance & accessibility
- Terrain rendering is GPU-heavy. On low-end mobile devices, terrain at high pitch may drop frame rate noticeably. **Recommendation:** make 3D mode opt-in via an explicit toggle, not default on. Also recommend `maxZoom` cap (e.g. 16) for terrain mode.
- WebGL context loss recovery is already handled by `useWebGLRecovery` hook (`ViewerMap.tsx:408`). Terrain doesn't change this.
- The 44px touch target accessibility goal is satisfied by the existing `NavigationControl` and a new toggle button — no new gesture surface area is needed since pitch/rotate gestures use existing two-finger touch handling that MapLibre provides automatically.
- **Keyboard accessibility:** `TerrainControl` from react-maplibre is keyboard-accessible (a single button toggling terrain on/off). Pitch/bearing rotation is mouse/touch-only and not keyboard-accessible — flag in the design doc as a non-blocker for the spike, but a real WCAG concern if 3D becomes a default. The Phase 217 accessibility audit (per STATE.md) is the right place to revisit this.

### Map viewer vs. map builder
GeoLens has **two** map components:
- `frontend/src/components/viewer/ViewerMap.tsx` — read-only public viewer (used by sharing, embed tokens)
- `frontend/src/components/builder/BuilderMap.tsx` — editing map (layer panel, draw tools, style editor)

They share the `syncLayersToMap` helper (`frontend/src/components/builder/map-sync.ts`) and the layer adapter registry (`frontend/src/components/builder/layer-adapters/`). Both consume `fill-adapter.ts` and `raster-adapter.ts`.

**The 3D phase MUST update both, OR ship 3D in viewer first and defer builder.** Recommend the latter for the spike — viewer is simpler, lower-risk, and the most common consumer path.

### Existing draw tools (Terra Draw)
The `terra-draw@1.25.0` and `terra-draw-maplibre-gl-adapter@1.3.0` packages handle drawing in the builder. **They are 2D only** — they will not draw at terrain elevation. If 3D mode is enabled and the builder switches to draw mode, drawn features will land at z=0 with the cursor projected onto the 2D plane. Acceptable for the spike; flag as a future limitation.

### Heatmap layers (no Z impact)
`heatmap-adapter.ts` is screen-space and unaffected by 3D. Safe to ignore.

## Follow-on Phase Sizing

| Phase | Description | Sizing | Why |
|-------|-------------|--------|-----|
| **A. 3D Viewer Toggle (terrain + extrusions)** | Frontend-only. Add a viewer toolbar button that toggles `pitch: 70`, attaches a `raster-dem` source from any dataset flagged `is_dem`, calls `setTerrain`, and switches `fill` layers to `fill-extrusion` for any layer with a configured `height_column`. Adds the height column picker to the layer style editor. Updates `ViewerMap.tsx` and `BuilderMap.tsx` (or just viewer for v1). | **MEDIUM** | Single React component change, two adapter updates, one new dataset metadata flag, no backend changes. ~5-8 tasks. |
| **B. PostGIS 3D Geometry Ingestion + Detection** | Backend. Add `ST_NDims` / `ST_Is3D` checks to the post-ingest `add_4326_column` step. Record dimensionality + Z range (`ST_ZMin`/`ST_ZMax`) on the dataset record. Expose in dataset detail UI ("This dataset has 3D geometry — Z range: 12m to 847m"). Decide on the attribute-promotion strategy (`elev` column for points). Catalog model migration. | **MEDIUM** | New SQL helpers, one Alembic migration, dataset model column, ingest pipeline edit, one UI badge. ~6-10 tasks. Lower than Phase C because it doesn't require new endpoints. |
| **C. Expose 3D Geometry to Client (GeoJSON-Z endpoint)** | Backend + frontend. Add a new `/api/datasets/{id}/features.geojson?include_z=true` endpoint (or extend the existing features endpoint). Stream RFC 7946 GeoJSON with three-coordinate positions. Frontend uses a `<Source type="geojson">` for 3D-aware datasets and reads Z via `fill-extrusion-height` expression `["at", 2, ["geometry-type-coordinates"]]` (or simpler: extract Z to attribute on the server before serving). Cap the feature count (e.g. 5000) to avoid streaming whole tables. | **LARGE** | New endpoint with auth + RBAC parity, new tile-vs-feature decision logic in the frontend, performance limits, fallback to MVT for >5000 features, new "preview in 3D" affordance. ~10-15 tasks. The PostGIS-3D story is genuinely complex when you commit to delivering the data, not just detecting it. |

**Recommended sequencing:** Phase A → ship → gather feedback → Phase B → Phase C only if user demand justifies it. Phase A delivers ~80% of the visible "3D support" value with ~20% of the work.

## Open Questions for the Design Doc Author

1. **3D toggle UX:** Per-viewer state (toggled per session) vs. saved on the layer/dataset (persisted)? Saved requires a new column on the `MapLayer` model. Recommend session-only for the v1 spike to avoid schema changes.
2. **DEM detection heuristic:** Is "single float band" enough to flag a raster as a DEM, or do we require an explicit user tag/checkbox at upload time? Recommend a soft heuristic + a manual override in the dataset metadata editor.
3. **Default exaggeration:** Should terrain exaggeration be fixed at 1.0 or user-adjustable? MapTiler examples use 1.0–2.5. Recommend a hardcoded 1.5 for the spike (matches react-maplibre official example) with a future "Style → Terrain Exaggeration" slider.
4. **Embed token compatibility:** When a 3D viewer is embedded via the existing share link / embed token system (v8.1, v8.2), do terrain tiles also need to flow through the embed-token-aware proxy? **Yes** — terrain tiles use the same Titiler proxy path, so the existing `X-Embed-Token` header injection in `ViewerMap.handleLoad` already covers this. Confirmed by reading `ViewerMap.tsx:198-206`.
5. **Backwards compatibility for the height column:** What happens to a layer styled with `fill-extrusion-height: ["get", "height"]` if a future re-upload removes the `height` column? The `coalesce ... 0` fallback handles it gracefully (flat polygons), but the layer config is now stale. Recommend the layer style editor surface a warning when the bound column disappears at re-upload time. (Existing schema-diff preview from v1.5 is a precedent.)
6. **POLYHEDRALSURFACE / TIN handling:** Defer entirely. If a user uploads CityGML or a TIN, the current pipeline already accepts it (PostGIS supports the types), but rendering it correctly requires 3D Tiles or a glTF pipeline — both out of scope per CONTEXT.md. Add to STATE.md as a deferred decision.
7. **Web Mercator clipping & polar regions:** GeoLens's `clip_to_mercator_bounds` (`backend/app/ingest/metadata.py:432`) clips geometries to ±85.06° latitude. For DEMs of polar regions this would crop the dataset. Out of scope for the spike but worth noting.

## References

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
- **GeoLens code paths verified:**
  - `frontend/package.json` (MapLibre versions)
  - `frontend/src/components/viewer/ViewerMap.tsx` (existing 2D viewer)
  - `frontend/src/components/builder/layer-adapters/fill-adapter.ts` (extrusion integration point)
  - `backend/app/tiles/router.py:261-291` (Titiler proxy URL builder)
  - `backend/app/tiles/service.py` (ST_AsMVTGeom call site)
  - `backend/app/ingest/ogr.py:319-350` (no `-dim` flag, Z survives ingestion)
  - `backend/app/ingest/metadata.py:452-490` (`add_4326_column` declares unconstrained `Geometry`)
  - `backend/app/raster/cog.py` (existing raster metadata extractor)
  - `docker-compose.yml` (titiler version 2.0.0 confirmed)

### Secondary (MEDIUM confidence — community sources, cross-verified)
- **MapLibre 3D buildings example (fill-extrusion height interpolation pattern):** https://harelm.github.io/maplibre-docs-test/examples/3d-buildings/
- **MapTiler 3D map tutorial:** https://docs.maptiler.com/guides/maps-apis/maps-platform/how-to-build-a-3d-map-with-maplibre-v2-gl-js/
- **Sparkgeo blog: 3D shapefile import to PostGIS with ogr2ogr (verifies Z preservation):** https://sparkgeo.com/blog/ogr2ogr-3d-shapefile-import-to-postgis-tip/
- **MapLibre fill-extrusion + terrain known issues (GitHub):** https://github.com/maplibre/maplibre-gl-js/issues/1650, https://github.com/maplibre/maplibre-gl-js/issues/2035, https://github.com/maplibre/maplibre-gl-js/issues/3001, https://github.com/maplibre/maplibre-gl-js/issues/3039

### Assumptions Log
| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Most 3D data GeoLens users will upload is XY polygons + height attribute, or POINT Z LiDAR — not POLYHEDRALSURFACE / TIN | Pillar 2 | LOW — if wrong, the design doc still recommends deferring complex 3D types to a future phase |
| A2 | Drawing tools (Terra Draw) at z=0 in 3D mode is acceptable for the spike | Gotchas | LOW — flagged as known limitation; can be revisited |
| A3 | Mobile users will be the smallest fraction of 3D-mode users, so opt-in toggle is acceptable | Gotchas | LOW — opt-in is the conservative default regardless |
| A4 | The existing tile auth proxy (`X-Embed-Token` header injection in `ViewerMap.handleLoad`) automatically covers terrain raster-dem tiles | Open Q4 | MEDIUM — verified by code reading but not by runtime test; design doc should call out a smoke test |
| A5 | A "single float band" heuristic + manual user override is enough to detect DEMs | Open Q2 | MEDIUM — could mis-flag non-DEM single-band rasters (e.g. NDVI). Manual override mitigates. |
