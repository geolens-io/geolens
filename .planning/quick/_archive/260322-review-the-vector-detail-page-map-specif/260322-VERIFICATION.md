---
phase: 260322
verified: 2026-03-20T19:46:00Z
status: gaps_found
score: 2/3 must-haves verified
re_verification: false
---

# Quick Task 260322 Verification Report

## Goal

Review the vector detail page map editing capabilities and determine whether the implementation is correct, complete, and aligned with best engineering practice.

## Must-Have Verification

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Live vector detail pages are checked for point, line, and polygon edit affordances | VERIFIED | Manual browser verification on `Admin 0 Countries (10m)`, `Graticules 10 (10m)`, and `Airports (10m)` showed geometry-appropriate toolbars and live edit entry |
| 2 | The feature edit persistence path is traced from frontend selection to backend update | VERIFIED | `extractSingleGeometry()` in `use-terra-draw.ts`, `selectFeatureFromMap()` in `use-feature-editing.ts`, and `update_feature()` in `backend/app/features/service.py` form a complete trace |
| 3 | The review identifies whether current automated coverage is sufficient for map editing correctness | GAPS FOUND | Targeted unit tests pass, but the real MapLibre/Terra Draw path is still largely mocked; Playwright detail-page coverage is stale and fails before it reaches the reviewed flow |

## Evidence

### Live app checks

- Polygon dataset: toolbar shows `Select`, `Polygon`, `Rectangle`, `Circle`, `Freehand`.
- Line dataset: toolbar shows `Select`, `Line`.
- Point dataset: toolbar shows `Select`, `Point`.
- Polygon feature selection in the live app enters edit mode with `Save`, `Cancel`, `Edit attributes`, and `Delete`.
- Client-side navigation between vector dataset detail pages requested fresh vector tile URLs for the new dataset.

### Automated checks

- `cd frontend && npx vitest run src/components/dataset/__tests__/DatasetMap.test.tsx src/hooks/__tests__/use-terra-draw.test.ts src/components/drawing/__tests__/DrawingToolbar.test.tsx`
  - Passed: 46/46 tests.
- `npx playwright test e2e/dataset-detail.spec.ts --project=chromium`
  - Failed: 3 tests timed out before reaching the detail page because `openWorldCountriesDataset()` still targets an obsolete search input placeholder.

## Gap Summary

### Gap 1: Multi-part geometry edits are unsafe

- Frontend simplification:
  - `frontend/src/hooks/use-terra-draw.ts` converts `MultiPoint` -> `Point`, `MultiLineString` -> `LineString`, `MultiPolygon` -> `Polygon`.
  - `frontend/src/hooks/use-feature-editing.ts` always uses that simplified geometry for selected features.
- Backend acceptance:
  - `backend/app/features/service.py` treats single-part GeoJSON as valid for multi-part dataset types and persists it directly.

Impact:

- Editing a multi-part feature can drop every part except the first.
- The edit-mode visualization is also incomplete, because the hidden tile feature is replaced by a single-part Terra Draw overlay.

### Gap 2: End-to-end coverage is not trustworthy

- `frontend/src/components/dataset/__tests__/DatasetMap.test.tsx` mocks both `@vis.gl/react-maplibre` and `useTerraDraw`.
- `frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx` replaces `DatasetMap` with a stub.
- `e2e/dataset-detail.spec.ts` currently fails at the search page and does not exercise the detail-page map.

Impact:

- The codebase does not currently have a reliable automated test that proves the real vector detail edit stack is safe.

## Final Status

`gaps_found`

This review does **not** support signing off the vector detail page map editing implementation as correct, complete, or best-practice compliant in its current state.
