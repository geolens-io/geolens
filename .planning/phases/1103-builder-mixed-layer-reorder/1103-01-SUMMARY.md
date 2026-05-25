# Phase 1103 Summary: Builder Mixed Layer Reorder

**Status:** Complete
**Requirements closed:** BUILDER-01, BUILDER-02

## Delivered

- `frontend/src/components/builder/hooks/use-builder-layers.ts` now reuses the reindexed drag/drop result for the immediate `reorderDataLayers` call.
- `frontend/src/components/builder/map-sync.ts` now rebuilds raster/hillshade sources when token tile URL, bounds, tile size, or min/max zoom changes.
- `frontend/src/components/builder/__tests__/map-sync.raster.test.ts` pins vector-over-raster ordering and raster source rebuild behavior.
- `scripts/marketing-data/adk-high-peaks/compose_marketing_maps.py` now emits top-to-bottom saved order with vector overlays above the DEM/aerial raster stack.

## Playwright Evidence

- Dragged `ADK 46er peaks` above `TNM/NY Orthos aerial`, saved the map, reloaded, and verified the order persisted.
- Re-ran the compose script after the smoke exposed the broader canonical order issue; current saved maps now list all six vector overlays before `DEM hillshade (1m)` and `TNM/NY Orthos aerial`.
