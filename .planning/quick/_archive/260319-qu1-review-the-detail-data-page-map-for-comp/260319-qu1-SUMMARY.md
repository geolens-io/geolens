---
phase: quick-260319-qu1
plan: 01
subsystem: ui
tags: [maplibre, accessibility, aria-label, dataset-map, react]

requires:
  - phase: 198
    provides: Hero state machine and no-tile badge for raster/VRT maps
provides:
  - Accessibility audit and fixes for DatasetMap controls
  - Comprehensive a11y test suite for DatasetMap
affects: [dataset-map, accessibility]

tech-stack:
  added: []
  patterns:
    - "All icon-only map controls must have both title and aria-label"
    - "Map container uses role=region with aria-label"

key-files:
  created: []
  modified:
    - frontend/src/components/dataset/DatasetMap.tsx
    - frontend/src/components/dataset/__tests__/DatasetMap.test.tsx

key-decisions:
  - "Map container uses role=region (landmark) with aria-label for screen readers"
  - "Zoom-to-extent and edit geometry buttons get aria-label matching their title prop (consistent with v12.1 pattern)"

patterns-established:
  - "DatasetMap a11y: all interactive controls carry aria-label"

requirements-completed: [QU1-REVIEW]

duration: 2min
completed: 2026-03-19
---

# Quick Task 260319-qu1: DatasetMap Audit Summary

**Accessibility fixes for 3 map controls (region role, zoom-to-extent, edit geometry) plus full audit documenting 7 areas of correctness**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-19T23:23:06Z
- **Completed:** 2026-03-19T23:25:19Z
- **Tasks:** 2 (1 auto + 1 checkpoint auto-approved)
- **Files modified:** 2

## Accomplishments

- Systematic audit of DatasetMap across all record types, geometry types, edge cases, accessibility, state management, and potential bugs
- Fixed 3 BUG-level accessibility gaps: missing aria-label on map container, zoom-to-extent button, and edit geometry button
- Added 4 accessibility-focused tests in a new `DatasetMap accessibility` test suite

## Audit Findings

### BUG (fixed)

1. **Map container missing role and aria-label** -- Screen readers had no landmark for the map region. Fixed with `role="region"` and `aria-label`.
2. **Zoom-to-extent button missing aria-label** -- Had `title` but no `aria-label`, inconsistent with v12.1 pattern. Fixed.
3. **Edit geometry button missing aria-label** -- Same issue. Fixed.

### OBSERVATION (documented only)

4. **GeometryCollection fallback** -- Falls into the polygon/fill branch of `addVectorLayers`. This is a reasonable default since most GeometryCollections contain polygons, and handling every combination would add complexity without clear benefit.
5. **Dateline-crossing bbox polygon** -- When `minx > maxx`, the bbox GeoJSON polygon wraps incorrectly. BBoxPreview handles this correctly but DatasetMap does not. Pre-existing issue, not caused by recent work.
6. **Raster error handler uses fragile string matching** -- `e.error.message.includes('raster-tile-source')` could break if MapLibre changes internal error messages. Works correctly today. The fallback checks for HTTP status codes (404, 500) provide resilience.
7. **Theme basemap switching style comparison** -- `style.name` comparison may fail if style JSON lacks a `name` field, but the `typeof newStyle === 'string'` guard prevents issues in practice.
8. **No vector tile error handling** -- Vector tile failures are silently ignored. Low priority since vector tiles are served from the same origin and failures are rare.
9. **NavigationControl visibility** -- Only shown during drawing mode for vectors but always for raster/VRT. Intentional UX choice since vector hero map is static/non-interactive by design.
10. **scrollZoom only in fullscreen** -- Intentional UX choice to prevent accidental zoom on scroll-heavy pages.
11. **Collection record type in DatasetMap** -- Collections render DatasetMap if they have bbox/tableName. This is correct since collections can have spatial extent.

### CORRECTNESS CONFIRMED

- All 4 record types handled correctly (vector, raster, VRT, collection)
- Point/Line/Polygon geometry types render with appropriate layer types
- Edge cases: null bbox + valid tableName, null bbox + null tableName, large extent, zero-area bbox all handled correctly
- State management: vectorLayersAdded/rasterLayersAdded refs reset on prop changes, tile token refresh updates source in-place
- Vector tile auth uses query-param (buildSignedTileUrl), raster tile auth uses Bearer header via transformRequest -- correct separation
- Hero state machine transitions (loading->loaded, loading->error, error->loading via retry) work correctly

## Task Commits

1. **Task 1: Audit DatasetMap and DatasetPage for correctness issues** - `d60661d0` (fix)
2. **Task 2: Human verification checkpoint** - auto-approved

## Files Created/Modified

- `frontend/src/components/dataset/DatasetMap.tsx` - Added role="region", aria-label to container, zoom-to-extent, and edit geometry controls
- `frontend/src/components/dataset/__tests__/DatasetMap.test.tsx` - Added 4 accessibility tests

## Decisions Made

- Map container uses `role="region"` (landmark) with `aria-label` for screen reader discoverability
- Aria-labels match `title` prop values (consistent with v12.1 pattern established in Phase 195)

## Deviations from Plan

None - plan executed exactly as written. All BUG-level findings were accessibility gaps that the plan explicitly called out for fixing.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All DatasetMap a11y gaps resolved
- Observations documented for future reference (dateline-crossing bbox, vector tile error handling)

---
*Quick Task: 260319-qu1*
*Completed: 2026-03-19*
