---
quick_id: 260408-aa5
description: 3d data and maps support
gathered: 2026-04-08
status: Ready for planning
---

# Quick Task 260408-aa5: 3d data and maps support - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Task Boundary

Produce a **feasibility spike / design doc** for 3D data and maps support in GeoLens. No code is shipped by this quick task — the output is a written design document that the team can use to scope follow-on phases.

Must cover, at minimum:
- 3D terrain (DEM) rendering
- 2D-polygon building extrusions (height attribute → 3D)
- **PostGIS 3D geometry support** — Z values, POLYHEDRALSURFACE, TIN, ST_Force3D, etc. (raised by user — important because GeoLens is PostGIS-native)

Rendering target is **MapLibre native** (MapLibre GL JS v5 / @vis.gl/react-maplibre v8 already in the stack). The doc should explain what MapLibre native can and cannot do, and flag alternatives (deck.gl overlay, 3D Tiles plugin, Cesium) only as "future options," not as recommendations for the first slice.

</domain>

<decisions>
## Implementation Decisions

### Scope
- **Deliverable is a design document, not code.** Output is a `.md` file written into the quick task directory.
- No backend changes, no frontend changes, no new dependencies added in this quick task.
- The doc should close with a **recommended follow-on phase breakdown** (e.g., "Phase X: terrain; Phase Y: extrusions; Phase Z: 3D geometry ingestion") so the team can promote it to ROADMAP entries if they choose.

### Data Kinds to Investigate
The design doc must cover each of these three pillars and clearly separate them:
1. **Terrain (DEM)** — MapLibre RasterDEM sources; how GeoLens's existing raster/Titiler pipeline can feed terrain tiles; encoding (Mapbox Terrain-RGB vs. Terrarium); 3D toggle UX in the viewer.
2. **Building extrusions** — MapLibre `fill-extrusion` layer; height attribute conventions (`height`, `render_height`, `min_height`); how to expose this from GeoLens's existing vector tile pipeline (ST_AsMVT); zero-height fallback behavior.
3. **PostGIS 3D geometry** — survey of 3D geometry types (POINT Z, LINESTRING Z, POLYGON Z, POLYHEDRALSURFACE, TIN, TRIANGLE); detection via `ST_NDims`/`ST_CoordDim`; how ingestion (ogr2ogr) currently handles Z values; what's lost in ST_AsMVT (MVT is 2D-only — flag this as a key limitation); options for exposing 3D geometry to the client (GeoJSON with Z, custom endpoint, conversion to extrusions, etc.).

### Rendering Target
- **MapLibre native** — terrain + fill-extrusion. No new rendering dependencies.
- Doc should explicitly list **what MapLibre native cannot do** (true 3D meshes, point clouds, 3D Tiles, CityGML, glTF) and note that these are deferred to future milestones.

### Claude's Discretion
- Depth of investigation per area (aim for actionable, not exhaustive).
- Output file location: `.planning/quick/260408-aa5-3d-data-and-maps-support/260408-aa5-DESIGN.md`.
- Format of the doc (suggest: Overview → Current State → Per-Pillar Analysis (terrain / extrusions / PostGIS 3D) → Gaps & Limitations → Recommended Follow-on Phases → Open Questions).
- Whether to include code snippets (yes, small illustrative ones are OK — but no files are modified).
- Whether to reference external libraries, specs, or blog posts (yes — this is a research deliverable).

</decisions>

<specifics>
## Specific Ideas

- GeoLens already has a raster pipeline (Titiler) — terrain DEM reuse should be the cheapest win and worth calling out first.
- ST_AsMVT drops Z coordinates — this is a **critical finding** for the PostGIS-3D story and must be in the doc prominently.
- MapLibre terrain requires `terrain-rgb` encoding; GeoLens's existing raster ingestion does not produce this format by default. Flag as a pipeline gap.
- Building extrusions are the quickest visual win — existing polygon datasets with a `height` column would "just work" with a new style layer.
- The user phrased the task as "3d data **and** maps support" — both pillars (data model + rendering) must be addressed.

</specifics>

<canonical_refs>
## Canonical References

- MapLibre GL JS terrain docs: https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/#setterrain
- MapLibre fill-extrusion style spec: https://maplibre.org/maplibre-style-spec/layers/#fill-extrusion
- PostGIS 3D geometry reference: https://postgis.net/docs/ST_CoordDim.html, https://postgis.net/docs/ST_Force3D.html
- ST_AsMVT docs (2D limitation): https://postgis.net/docs/ST_AsMVT.html
- Mapbox Terrain-RGB encoding spec: https://docs.mapbox.com/data/tilesets/guides/access-elevation-data/
- GeoLens stack reference: `.planning/STATE.md`, `.planning/PROJECT.md`, `frontend/src/components/map/` (existing map components), Titiler integration in backend

</canonical_refs>
