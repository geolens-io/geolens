# Requirements: GeoLens v1024 ADK High Peaks Marketing-Ready

**Defined:** 2026-05-24
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v1024 Requirements

### ADK Marketing Data

- [x] **ADK-DATA-01**: Operator can run the ADK pipeline with a TNM API aerial fetch path that attempts NAIP 0.6m imagery for the High Peaks AOI and replaces the prior soft 3.5 MB ArcGIS REST aerial when TNM publishes matching imagery.
- [x] **ADK-DATA-02**: If TNM does not publish NAIP imagery for the AOI, the pipeline records that fact with the exact TNM query evidence and uses a documented high-fidelity fallback without silently keeping the prior low-resolution aerial.
- [x] **ADK-DATA-03**: Operator can ingest NHD hydrography for the ADK High Peaks AOI and see it as a styled layer in the marketing map.
- [x] **ADK-DATA-04**: Operator can ingest the remaining ADK 46er peaks relevant to the map set, replacing the prior 12-peak AOI subset limitation where the broader marketing map needs complete 46er context.
- [x] **ADK-DATA-05**: `scripts/marketing-data/adk-high-peaks/compose_marketing_maps.py` remains idempotent and updates or reuses existing datasets/maps rather than duplicating them.

### ADK Saved Maps

- [x] **ADK-MAP-01**: The primary ADK High Peaks marketing map contains high-fidelity aerial, DEM hillshade, NHD hydrography, land classification, Blue Line context, hiking trails, and complete 46er peak overlays with vectors above rasters.
- [x] **ADK-MAP-02**: A bonus ADK High Peaks 3D relief variant Map 2 is composed with terrain enabled, an intentional exaggeration value, and a layer/style stack suitable for marketing screenshots.
- [x] **ADK-MAP-03**: Re-running the ADK compose script end-to-end produces or updates both maps without a manual `PUT /api/maps/{id}` terrain fix or manual layer-order PATCH.

### Builder Ordering

- [x] **BUILDER-01**: User can drag a vector layer above raster aerial/DEM layers in the builder and see the MapLibre canvas order update immediately without page reload.
- [x] **BUILDER-02**: User-set mixed raster/vector layer order survives `PATCH /api/maps/{id}/layers` plus browser reload, with an automated regression test covering vectors above rasters.

### Terrain Rendering

- [x] **TERRAIN-01**: Raster tile tokens for DEM terrain use per-dataset min/max zoom derived from COG metadata instead of hardcoded `maxzoom=18`.
- [x] **TERRAIN-02**: A terrain-enabled ADK map opens without `dem dimension mismatch`, missing terrain source, or elevation maxzoom console errors at the intended screenshot zoom range.
- [x] **TERRAIN-03**: `POST /api/maps/` with `terrain_config={enabled:false}` preserves the explicit disabled state after the first frontend builder open.
- [x] **TERRAIN-04**: Builder terrain settings and exaggeration controls update terrain on the live map without throwing console errors.

### Builder Error Hygiene

- [x] **TOAST-01**: MapLibre internal terrain/DEM errors are not routed into the basemap-connection toast bucket.
- [x] **TOAST-02**: The basemap-error toast no longer overlaps the top-left NavigationControl.
- [x] **BASEMAP-01**: Positron basemap loads cleanly when no terrain layer is present; if it does not, the actual basemap fetch path is fixed or documented with evidence.
- [x] **SPRITE-01**: OpenFreeMap Positron `road_` / `us-state_` sprite-missing warnings are resolved or suppressed without hiding unrelated image-loading errors.

### Verification

- [x] **VERIFY-01**: Playwright MCP smoke opens the freshly composed primary ADK map in the builder and verifies zero browser console errors/warnings.
- [x] **VERIFY-02**: Playwright MCP smoke exercises layer reorder, terrain settings, and exaggeration controls in the builder.
- [x] **VERIFY-03**: Close gate documents test commands, Playwright MCP evidence, map IDs, screenshot targets, and any accepted third-party data-source limitations.

## Future Requirements

### CI Infrastructure

- **CI-01-v1024**: Live-verify `pytest-parallel-isolation` on real GitHub Actions infrastructure after geolens-io billing is resolved. This is a rolling external blocker from v1022 and v1023, not part of the ADK marketing-ready hard invariant.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Rebuilding the whole map-builder information architecture | v1024 is a targeted data/rendering/debuggability milestone anchored to 260524-o57 dogfooding findings. |
| Cloud multi-tenant infrastructure | Unrelated backlog scope; keep this milestone focused on marketing maps and builder rendering. |
| Vendor-hosted basemap replacement | Only fix GeoLens handling of Positron warnings/errors; do not replace the basemap provider unless required by verification. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ADK-DATA-01 | Phase 1101 | Complete |
| ADK-DATA-02 | Phase 1101 | Complete |
| ADK-DATA-03 | Phase 1101 | Complete |
| ADK-DATA-04 | Phase 1101 | Complete |
| ADK-DATA-05 | Phase 1101 | Complete |
| ADK-MAP-01 | Phase 1102 | Complete |
| ADK-MAP-02 | Phase 1102 | Complete |
| ADK-MAP-03 | Phase 1102 | Complete |
| BUILDER-01 | Phase 1103 | Complete |
| BUILDER-02 | Phase 1103 | Complete |
| TERRAIN-01 | Phase 1104 | Complete |
| TERRAIN-02 | Phase 1104 | Complete |
| TERRAIN-03 | Phase 1104 | Complete |
| TERRAIN-04 | Phase 1104 | Complete |
| TOAST-01 | Phase 1105 | Complete |
| TOAST-02 | Phase 1105 | Complete |
| BASEMAP-01 | Phase 1105 | Complete |
| SPRITE-01 | Phase 1105 | Complete |
| VERIFY-01 | Phase 1106 | Complete |
| VERIFY-02 | Phase 1106 | Complete |
| VERIFY-03 | Phase 1106 | Complete |

**Coverage:**
- v1024 requirements: 21 total, 21 complete
- Mapped to phases: 21
- Unmapped: 0

---
*Requirements defined: 2026-05-24*
*Last updated: 2026-05-24 after v1024 milestone initialization*
