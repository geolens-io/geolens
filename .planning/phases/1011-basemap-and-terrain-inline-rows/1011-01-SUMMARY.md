# Phase 1011 Plan 01 Summary

**Completed:** 2026-05-12
**Requirements:** BASE-01, BASE-02, BASE-03, BASE-04, TERRAIN-01, TERRAIN-02

## What Changed

- Added an optional derived `basemap_label` to the frontend stack view-model so the basemap row displays the current `BasemapEntry.label`.
- Replaced the separate basemap picker/panel in `MapStackPanel` with row-adjacent inline controls:
  - sublayer controls still write `basemap_config` / `show_basemap_labels`;
  - swap lists enabled registry entries plus the existing blank basemap affordance;
  - reset restores normalized default basemap appearance.
- Moved the terrain row from `surface` into `relief`, keeping the existing terrain metadata and map-level `terrain_config` storage.
- Moved `TerrainControls` into the `relief` section so source/enabled/exaggeration are edited alongside DEM relief.
- Added a raster DEM-only row overflow action, **Use as terrain**, which writes `terrain_config` with the DEM layer's `dataset_id`.

## Boundaries Preserved

- No migration, backend endpoint, table, persisted group, or new map/layer field.
- Basemap controls write only `basemap_style`, `show_basemap_labels`, and `basemap_config`.
- Terrain controls and `Use as terrain` write only `terrain_config`.
- No saved basemap presets and no Add Dataset modal changes in this phase.

## Verification

- `cd frontend && npm run test -- MapStackPanel map-stack renderAs use-builder-layers --run` — passed, 4 files / 57 tests.
- `cd frontend && npm run test -- MapStackPanel map-stack --run` — passed, 2 files / 21 tests after final handler guard.
- `cd frontend && npm run lint` — passed.
- `cd frontend && npm run build` — passed, with the existing large-chunk warning only.

## Handoff

Phase 1012 can focus on the Add Dataset modal states. Sidebar basemap and terrain controls now satisfy the v1 no-migration contract.
