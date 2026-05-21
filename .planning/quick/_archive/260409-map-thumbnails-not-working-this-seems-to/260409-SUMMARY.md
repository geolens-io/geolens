---
phase: 260409-map-thumbnails-not-working-this-seems-to
plan: 01
subsystem: maps
tags: [thumbnail, builder, regression, playwright]

provides:
  - Map thumbnail capture now waits for GeoLens layer sources plus post-layer idle
  - Regression coverage for delayed auto-capture when sources are initially missing
  - Browser-verified fix for duplicated maps that start without a thumbnail

key-files:
  created: []
  modified:
    - frontend/src/hooks/use-builder-save.ts
    - frontend/src/hooks/__tests__/use-builder-save.test.ts

requirements-completed: [QT-260409]
completed: 2026-04-10
---

# Quick Task 260409: Map Thumbnail Regression Summary

## Outcome

Map thumbnails were being generated too early from the builder. On duplicated maps with no thumbnail, the app uploaded the thumbnail before raster/vector tile requests completed, so the resulting preview showed only the basemap shell.

The fix keeps the existing thumbnail upload flow but waits for visible GeoLens layer sources to appear on the map before falling through to the idle-based capture. That makes the capture happen after the rendered layers exist instead of at initial map mount time.

## Evidence

- Targeted frontend tests:
  - `cd frontend && npm test -- --run src/hooks/__tests__/use-builder-save.test.ts src/hooks/__tests__/use-map-thumbnail.test.ts src/components/maps/__tests__/MapCard.test.tsx`
  - `cd frontend && npx tsc --noEmit`
- Existing builder smoke reused per `geolens-smoke`:
  - `npx playwright test e2e/builder.spec.ts --project=chromium --grep "saves map without errors|duplicates map and navigates to new URL"`
- Playwright MCP reproduction:
  - Before fix, duplicated map `fe78a221-351b-4f42-80ef-1c2af47f166b` uploaded `/thumbnail/` before any raster/vector tile requests and produced a basemap-only card preview.
  - After fix, duplicated map `1b7ccb62-4fb8-4c0c-aecd-db1cf69208b2` uploaded `/thumbnail/` only after raster/vector tile requests completed, and the `/maps` card preview showed the bathymetry overlay correctly.

## Notes

- Temporary duplicate maps created for validation were deleted after verification.
- The duplicate builder page still emitted two thumbnail PUTs in local dev; that appears to be the existing dev/runtime behavior, but the important regression is fixed because both uploads now happen after rendered layer content is present.
