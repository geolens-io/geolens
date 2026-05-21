# Quick Task 260322: Vector detail page map editing review - Research

**Researched:** 2026-03-20
**Confidence:** High

## Live Verification

Verified against the running app at `http://localhost:8080` as `admin`:

- `Admin 0 Countries (10m)` (`MULTIPOLYGON`): edit toolbar shows `Select`, `Polygon`, `Rectangle`, `Circle`, `Freehand`.
- `Graticules 10 (10m)` (`MULTILINESTRING`): edit toolbar shows `Select`, `Line`.
- `Airports (10m)` (`MULTIPOINT`): edit toolbar shows `Select`, `Point`.
- Selecting a polygon feature on `Admin 0 Countries (10m)` enters edit mode and exposes `Save`, `Cancel`, `Edit attributes`, and `Delete`.
- In-app client-side navigation from `Airports (10m)` to `Reefs (10m)` requested a fresh tile token and `data.reefs_10m` tiles, so dataset-to-dataset route changes are reloading vector tiles.

## Automated Checks

- `cd frontend && npx vitest run src/components/dataset/__tests__/DatasetMap.test.tsx src/hooks/__tests__/use-terra-draw.test.ts src/components/drawing/__tests__/DrawingToolbar.test.tsx`
  - Result: 46/46 tests passed.
- `npx playwright test e2e/dataset-detail.spec.ts --project=chromium`
  - Result: 3 failed, 1 passed.
  - Failure cause: the suite still looks for the old search input placeholder `Search datasets by name, description, tags...` and times out before reaching the detail page.

## Code Trace

### Multi-geometry edit path

- `extractSingleGeometry()` intentionally downgrades `MultiPoint` to `Point`, `MultiLineString` to `LineString`, and `MultiPolygon` to `Polygon`.
- `selectFeatureFromMap()` always calls `extractSingleGeometry()` before loading the selected feature into Terra Draw.
- `update_feature()` on the backend accepts single-part GeoJSON for multi-part dataset types, then writes that geometry directly to `geom` and `geom_4326`.

Combined effect:

- Editing any selected multi-part feature can persist only the first part back to the database.
- During edit mode, the visualization also becomes incomplete because the hidden tile feature is replaced by a Terra Draw overlay containing only that first part.

## Coverage Assessment

Current unit coverage is mostly UI-shell coverage:

- `DatasetMap.test.tsx` mocks `@vis.gl/react-maplibre`.
- `DatasetMap.test.tsx` also mocks `useTerraDraw`.
- `DatasetPage.edit-affordances.test.tsx` replaces `DatasetMap` with a stub.

This means the real selection/edit/save/delete path through MapLibre + Terra Draw is not protected by automated tests.
