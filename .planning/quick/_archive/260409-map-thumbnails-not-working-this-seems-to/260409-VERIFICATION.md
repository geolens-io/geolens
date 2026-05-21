---
phase: 260409-map-thumbnails-not-working-this-seems-to
verified: 2026-04-10T13:10:30Z
status: passed
score: 4/4 must-haves verified
---

# Quick Task 260409: Map Thumbnail Regression Verification

## Goal

Ensure builder-generated map thumbnails capture rendered map content rather than only the basemap shell.

## Must-Have Verification

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Auto-generated thumbnails capture rendered map content, not just the basemap shell | ✓ VERIFIED | `/maps` screenshot after the fix showed `Global Bathymetry (copy 2)` with the bathymetry raster visible in the thumbnail |
| 2 | Thumbnail capture waits until GeoLens map sources are present and the map reaches a post-layer idle state | ✓ VERIFIED | Playwright network trace for duplicate `1b7ccb62-4fb8-4c0c-aecd-db1cf69208b2` showed raster/vector tile requests completing before the thumbnail PUT |
| 3 | Manual save thumbnail uploads still work | ✓ VERIFIED | Existing smoke spec `e2e/builder.spec.ts` test `saves map without errors` passed |
| 4 | Regression coverage exists for delayed capture when sources are initially missing | ✓ VERIFIED | New unit test in `frontend/src/hooks/__tests__/use-builder-save.test.ts` passed and asserts no upload occurs before visible layer sources appear |

## Automated Checks

- `cd frontend && npm test -- --run src/hooks/__tests__/use-builder-save.test.ts src/hooks/__tests__/use-map-thumbnail.test.ts src/components/maps/__tests__/MapCard.test.tsx`
  - Result: 28 tests passed
- `cd frontend && npx tsc --noEmit`
  - Result: passed
- `npx playwright test e2e/builder.spec.ts --project=chromium --grep "saves map without errors|duplicates map and navigates to new URL"`
  - Result: 3 tests passed

## Browser Validation

- Pre-fix reproduction:
  - Duplicate `fe78a221-351b-4f42-80ef-1c2af47f166b`
  - Thumbnail PUTs happened before tile requests
  - `/maps` card preview was basemap-only
- Post-fix reproduction:
  - Duplicate `1b7ccb62-4fb8-4c0c-aecd-db1cf69208b2`
  - Thumbnail PUTs happened after tile requests
  - `/maps` card preview showed the colored bathymetry overlay

## Verdict

Passed. The regression is fixed on the real running stack and covered with a focused hook test plus existing builder smoke coverage.
