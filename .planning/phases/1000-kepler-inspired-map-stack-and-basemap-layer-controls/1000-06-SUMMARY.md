---
phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
plan: 06
subsystem: ui
tags: [react, maplibre, public-viewer, basemap-config, vitest]

requires:
  - phase: 1000-04
    provides: persisted basemap_config API and style transform contract
  - phase: 1000-05
    provides: public viewer terrain/style reload alignment
provides:
  - Public viewer consumption of persisted basemap_config
  - ViewerMap runtime reapplication of curated basemap appearance
  - Focused public-viewer regression coverage
affects: [map-stack, public-viewer, basemap-config, MAPSTACK-04, MAPSTACK-06, MAPSTACK-07]

tech-stack:
  added: []
  patterns:
    - Reuse builder applyBasemapConfigToMap in public viewer with viewer-source- managed source prefix.

key-files:
  created:
    - frontend/src/pages/__tests__/PublicMapViewerPage.test.tsx
    - frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx
  modified:
    - frontend/src/components/viewer/ViewerMap.tsx
    - frontend/src/pages/PublicViewerPage.tsx
    - frontend/src/pages/PublicMapViewerPage.tsx
    - frontend/src/pages/__tests__/PublicViewerPage.test.tsx

key-decisions:
  - "Public viewers use the existing builder basemap style transform rather than duplicating appearance logic."
  - "ViewerMap excludes viewer-managed data layers from basemap transforms with the viewer-source- prefix."

patterns-established:
  - "Public viewer pages pass persisted map appearance fields directly into ViewerMap."
  - "Viewer style reload handlers reapply terrain and basemap appearance after MapLibre setStyle resets."

requirements-completed: [MAPSTACK-04, MAPSTACK-06, MAPSTACK-07]

duration: 4 min
completed: 2026-05-11
---

# Phase 1000 Plan 06: Public Viewer Basemap Config Summary

**Public saved maps now render persisted basemap appearance through both public viewer entrypoints and ViewerMap runtime reapplication.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-11T14:52:20Z
- **Completed:** 2026-05-11T14:56:29Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Passed `basemap_config` from shared-token and authenticated public map viewer pages into `ViewerMap`.
- Applied `applyBasemapConfigToMap` in `ViewerMap` after data-layer sync, MapLibre `style.load`, and runtime basemap config / legacy label changes.
- Added focused regression tests for public-page prop forwarding and viewer runtime reapplication with representative road, boundary, building, tone, relief, and label settings.

## Task Commits

1. **Task 1: Pass basemap_config from both public viewer pages** - `b169cafe` (feat)
2. **Task 2: Apply basemap_config in ViewerMap runtime** - `cb93328d` (feat)
3. **Task 3: Add representative public-viewer basemap regression coverage** - `be520f06` (test)

**Plan metadata:** included in final docs commit

## Files Created/Modified

- `frontend/src/pages/PublicViewerPage.tsx` - Forwards shared-token `data.basemap_config ?? null` into `ViewerMap`.
- `frontend/src/pages/PublicMapViewerPage.tsx` - Forwards authenticated map `data.basemap_config ?? null` into `ViewerMap`.
- `frontend/src/components/viewer/ViewerMap.tsx` - Accepts `basemapConfig` and reapplies curated basemap style with the `viewer-source-` managed source prefix.
- `frontend/src/pages/__tests__/PublicViewerPage.test.tsx` - Captures mocked `ViewerMap` props and asserts shared-token basemap config forwarding.
- `frontend/src/pages/__tests__/PublicMapViewerPage.test.tsx` - Adds authenticated public map viewer prop forwarding coverage.
- `frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx` - Covers load, `style.load`, and runtime basemap config / label reapplication.

## Decisions Made

- Reused `applyBasemapConfigToMap` from the builder path so public rendering honors the same curated basemap behavior.
- Used `viewer-source-` as the source prefix so basemap transforms exclude viewer-managed data layers.
- Kept null `basemap_config` compatible with legacy `show_basemap_labels` behavior through the existing normalizer.

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope changes.

## Issues Encountered

Vitest emitted the existing `--localstorage-file` warning during focused runs, but all targeted tests passed.

`gsd-tools state advance-plan`, `state update-progress`, `state record-metric`, and `state record-session` could not update this repository's custom `STATE.md` layout automatically, so the required Phase 1000 plan counts and session continuity lines were updated manually. `roadmap update-plan-progress` reported success, but the Phase 1000 row still required the manual 6/6 plan count adjustment.

## User Setup Required

None - no external service configuration required.

## Verification

- `cd frontend && npm run test -- PublicViewerPage PublicMapViewerPage --run` - passed, 2 files / 4 tests.
- `cd frontend && npm run test -- ViewerMap.basemap-config --run` - passed, 1 file / 1 test.
- `cd frontend && npm run test -- ViewerMap.basemap-config PublicViewerPage PublicMapViewerPage --run` - passed, 3 files / 5 tests.
- `cd frontend && npm run lint` - passed.

## Next Phase Readiness

Phase 1000's recorded public-viewer basemap gap is closed. `1000-VERIFICATION.md` can be rerun or refreshed to move MAPSTACK-04 and MAPSTACK-06 from gap-found to passed.

---
*Phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls*
*Completed: 2026-05-11*
