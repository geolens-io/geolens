---
phase: 218-demo-themed-collections
plan: "02"
subsystem: demo-seeder
tags: [demo, seeder, python, raster, gebco, srtm, natural-earth, fixtures, theme1]
dependency_graph:
  requires:
    - phase: 218-01
      provides: "frozen orchestrator, ingest helpers, per-theme module stubs, fixture_schema, apply_fixture"
  provides:
    - scripts/demo/themes/theme1.py — populated with 11 Theme 1 dataset entries (8 NE physical vectors + 3 raster COGs)
  affects:
    - Plan 218-05 — Dockerfile RUN commands for GEBCO, NE shaded relief, and SRTM data staging (document below)
tech-stack:
  added: []
  patterns:
    - "3D-ready forward-compat note embedded in dataset description: when Phase 999.1 ships, GEBCO and SRTM re-use without re-ingest via Titiler ?algorithm=terrainrgb"
    - "DATASETS list in theme module as sole touch-point for Plans 02/03/04 — orchestrator never modified"
key-files:
  created:
    - scripts/demo/fixtures/maps/1-earth-from-space.json — PENDING (Task 2, requires live ingest + UI)
    - scripts/demo/fixtures/maps/1-global-bathymetry.json — PENDING (Task 2, requires live ingest + UI)
  modified:
    - scripts/demo/themes/theme1.py — populated with 11 dataset entries
key-decisions:
  - "VRT mosaic name in orchestrator main_async() is 'Planet Earth Composite VRT' — fixture must use _stem='planet-earth-vrt' (no ext) to resolve it via the existing lookup map"
  - "NE shaded relief filename in NACIS CDN must be verified at execution time per 218-RESEARCH.md G11; likely candidate is NE1_HR_LC_SR_W_DR.zip in the 10m/raster/ directory"
  - "GEBCO download is ~6.7 GB from source.coop S3 — allow 30–90 min depending on bandwidth; gdal_translate downsampling adds ~10 min"
  - "SRTM tile for Himalayas: N28E086 or N27E086 covers Everest region — verify via OpenTopography S3 listing before the Dockerfile"
requirements-completed:
  - DEMO-THEME1-01
  - DEMO-THEME1-02
  - DEMO-THEME1-03
  - DEMO-THEME1-04

# Metrics
duration: partial (Task 1 complete, Task 2+3 paused at checkpoint)
completed: "2026-04-08"
---

# Phase 218 Plan 02: Theme 1 — Planet Earth Summary

**11-entry Theme 1 DATASETS module committed (8 NE physical vectors + GEBCO + shaded relief + SRTM with 3D forward-compat notes); fixture export and visual sign-off paused at human checkpoint pending live ingest run.**

## Performance

- **Duration:** ~5 min (Task 1 only)
- **Started:** 2026-04-08
- **Completed:** Task 1 complete; Tasks 2-3 paused at checkpoint
- **Tasks:** 1/3 complete
- **Files modified:** 1 (theme1.py)

## Accomplishments

- Populated `scripts/demo/themes/theme1.py` with all 11 Theme 1 dataset entries matching the plan spec exactly
- All entries carry `snapshot_date`, `license`, and `summary` fields
- GEBCO and SRTM summaries include the Phase 999.1 terrain forward-compat note ("3D-ready")
- Dry-run confirms orchestrator reports "Planet Earth (2025 Snapshot) (11 datasets)"
- Frozen orchestrator, theme2.py, and theme3.py verified unchanged

## Task Commits

1. **Task 1: Populate theme1.py with 11 Theme 1 dataset entries** — `a6333cd7` (feat)
2. **Task 2: Hand-curate Maps 1.1 + 1.2, run end-to-end ingest, export fixtures** — PENDING (human-verify checkpoint)
3. **Task 3: Human visual sign-off on Maps 1.1 and 1.2** — PENDING (checkpoint:human-verify)

## Files Created/Modified

- `scripts/demo/themes/theme1.py` — Populated DATASETS list: 8 NE physical vector layers (ne_cdn source) + GEBCO 2024 30-arcmin bathymetry COG + NE 10m shaded relief COG + SRTM GL1 30m Himalayas DEM

## Plan 05 Data-Stage Commands (to be verified during Task 2 execution)

The following commands are the intended dev-run data staging process. Plan 05 absorbs the verified versions into the seeder Dockerfile. **None of these have been executed yet — they require verification at Task 2 time.**

### GEBCO 2024 (30 arc-min downsample)

```bash
# ~6.7 GB download, ~10 min GDAL conversion
curl -fsSL -o /tmp/gebco_full.tif \
  "https://s3.us-west-2.amazonaws.com/us-west-2.opendata.source.coop/alexgleith/gebco-2024/GEBCO_2024.tif"
gdal_translate -of COG -co COMPRESS=DEFLATE -co PREDICTOR=3 -tr 0.5 0.5 -r bilinear \
  /tmp/gebco_full.tif /tmp/demo-data/gebco_2024_30arcmin.tif
rm /tmp/gebco_full.tif
```

### NE 10m Shaded Relief (COG conversion)

```bash
# Verify exact filename at: https://naciscdn.org/naturalearth/10m/raster/
# Likely candidate (verify at execution time — directory listing not stable):
curl -fsSL -o /tmp/ne_sr.zip \
  "https://naciscdn.org/naturalearth/10m/raster/NE1_HR_LC_SR_W_DR.zip"
unzip -o /tmp/ne_sr.zip -d /tmp/ne_sr/
gdal_translate -of COG -co COMPRESS=DEFLATE \
  /tmp/ne_sr/NE1_HR_LC_SR_W_DR.tif /tmp/demo-data/ne_10m_shaded_relief.tif
rm -rf /tmp/ne_sr.zip /tmp/ne_sr/
```

**URL drift risk:** The NACIS CDN directory listing for 10m rasters changes when NE releases new versions. Verify the filename/URL before committing to Dockerfile.

### SRTM GL1 30m Himalayas (OpenTopography S3)

```bash
# Tile covering Everest/Himalaya region — verify tile ID via OpenTopography S3 listing
# Candidate tiles: N28E086 or N27E086 (covers Mount Everest at 27.9881°N, 86.9250°E)
aws s3 cp \
  s3://raster/SRTM_GL1/SRTM_GL1_srtm_<TILE_ID>.tif \
  /tmp/srtm_tile.tif \
  --endpoint-url https://opentopography.s3.sdsc.edu \
  --no-sign-request
gdal_translate -of COG -co COMPRESS=DEFLATE /tmp/srtm_tile.tif /tmp/demo-data/srtm_himalayas.tif
rm /tmp/srtm_tile.tif
```

**Note for Plan 05:** Document the exact tile ID chosen and verify OpenTopography S3 bucket path format — the exact path may differ from the pattern shown in 218-RESEARCH.md.

## VRT Resolution Notes (for Task 2)

The orchestrator's `main_async()` creates the VRT with stem `planet-earth-vrt` (hardcoded in the `results.append` call). When exporting the Map 1.1 fixture, the VRT dataset will have `source_filename=None` (created via API, not uploaded). The fixture must use:

```json
{
  "_stem": "planet-earth-vrt",
  "_ext": ""
}
```

`apply_fixture` resolves this via the `existing` lookup: `{source_filename: dataset_id}`. The VRT dataset won't have a `source_filename` — so `apply_fixture` or `resolve_fixture` may need a name-based fallback. **Document if this requires a patch in the SUMMARY update at Task 2 completion.** Do not patch the orchestrator — Plan 05 owns that.

## Map Specs (for Task 2 reference)

### Map 1.1 — Earth as Seen from Space

- Basemap: dark-matter, show_basemap_labels=false
- View: center [0, 15], zoom 1.8, bearing 0, pitch 0
- Widgets: measurement, scale
- Layers (bottom to top render order):
  1. Ocean fill: fill-color #0a1e3a (ne_10m_ocean)
  2. VRT mosaic: default raster paint (planet-earth-vrt)
  3. Glaciated areas: fill-color white, fill-opacity 0.6 (ne_10m_glaciated_areas)
  4. Lakes: fill-color #a8d4f0, fill-opacity 0.8 (ne_10m_lakes)
  5. Rivers: line-color #ffffff, line-width data-driven by scalerank (ne_10m_rivers_lake_centerlines)

### Map 1.2 — Global Bathymetry

- Basemap: positron
- View: world extent
- Widgets: measurement, scale
- Layers:
  1. GEBCO COG: viridis_r colormap (gebco_2024_30arcmin)
  2. Country borders: thin dark line (ne_10m_admin_0_boundary_lines_land — cross-theme ref)
  3. Coastline: (ne_10m_coastline)

## Deviations from Plan

None — Task 1 executed exactly as written. Tasks 2 and 3 paused at human-verify checkpoint requiring live ingest and visual sign-off.

## Known Stubs

- `scripts/demo/fixtures/maps/1-earth-from-space.json` — not yet created (requires live ingest + UI map building)
- `scripts/demo/fixtures/maps/1-global-bathymetry.json` — not yet created (requires live ingest + UI map building)

These stubs are intentional: the plan explicitly requires a human checkpoint (Task 3) for visual approval before the fixtures are considered complete.

## Self-Check: PASSED (Task 1 scope)

Files modified:
- FOUND: scripts/demo/themes/theme1.py

Commits verified:
- a6333cd7: feat(218-02): populate Theme 1 DATASETS — 8 NE physical vectors + GEBCO + shaded relief + SRTM

Frozen files unchanged:
- scripts/demo/seed-thematic-demo.py: no diff
- scripts/demo/themes/theme2.py: no diff
- scripts/demo/themes/theme3.py: no diff

---
*Phase: 218-demo-themed-collections*
*Partial completion: 2026-04-08 (Task 1 of 3)*
