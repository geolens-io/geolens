---
phase: 1003-map-stack-inspector-interaction-polish
plan: 02
subsystem: frontend
tags: [map-builder, map-stack, inspector, accessibility, vitest]

requires:
  - phase: 1003-map-stack-inspector-interaction-polish
    provides: Plan 1003-01 stable layer order for row identity
  - phase: 1000-kepler-inspired-map-stack-and-basemap-layer-controls
    provides: Unified Map Stack sidebar and sidebar-local inspector
provides:
  - Data-first empty Map Stack affordance
  - Stack row state badges and data attributes for selected, hidden, locked, unsupported, disabled, and error-like states
  - Visible keyboard focus treatment for inspector tabs and back control
affects: [map-builder, layer-inspector, accessibility, responsive-polish]

tech-stack:
  added: []
  patterns: [row state badges over existing MapStackEntry metadata, data-first empty stack prompt]

key-files:
  created: []
  modified:
    - frontend/src/components/builder/map-stack.ts
    - frontend/src/components/builder/MapStackPanel.tsx
    - frontend/src/components/builder/MapStackItem.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/__tests__/map-stack.test.ts
    - frontend/src/components/builder/__tests__/MapStackPanel.test.tsx
    - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - frontend/src/i18n/locales/de/builder.json

key-decisions:
  - "Keep all Map Stack groups visible on empty maps, but put the Add Data prompt before stack sections."
  - "Expose row state through badges plus data attributes without changing existing layer-item test IDs or Expand options action names."
  - "Treat missing terrain source as the row-level error-like state for current stack metadata."

patterns-established:
  - "MapStackItem derives visual row state from existing entry metadata and layer capabilities."
  - "Inspector tab focus is handled with stable tab dimensions and focus-visible rings."

requirements-completed: [STACK-01, STACK-02, STACK-03, STACK-04, STACK-05, STACK-06]

duration: 24min
completed: 2026-05-11
---

# Phase 1003 Plan 02: Map Stack and Inspector Polish Summary

**The Map Stack now starts empty maps with data, exposes row state clearly, and improves keyboard focus through the layer inspector.**

## Performance

- **Duration:** 24 min
- **Started:** 2026-05-11T20:18:00Z
- **Completed:** 2026-05-11T20:22:00Z
- **Tasks:** 3 completed
- **Files modified:** 11

## Accomplishments

- Added a compact "Start with data" prompt before stack sections for empty maps, wired to the existing Add Data callback.
- Added unsupported-layer detection, state badges, row `data-state`, locked/visible attributes, and state-specific visual treatment.
- Added keyboard-visible focus styling to the inspector back control and tab buttons.
- Extended focused Vitest coverage for empty state order, row states, unsupported layers, missing terrain, and inspector tab focus.
- Added builder locale strings for English, Spanish, French, and German.

## Task Commits

1. **Task 1: Add data-first empty stack affordance** - `b5491c54` (feat)
2. **Task 2: Make row states scannable and stable** - `91c60eed` (feat)
3. **Task 3: Tighten inspector keyboard focus** - `44662c93` (feat)

## Files Created/Modified

- `frontend/src/components/builder/MapStackPanel.tsx` - Empty data-first prompt.
- `frontend/src/components/builder/MapStackItem.tsx` - Row state badges, attributes, and focus-visible row styling.
- `frontend/src/components/builder/map-stack.ts` - Unsupported vector layer badge classification.
- `frontend/src/components/builder/LayerEditorPanel.tsx` - Inspector tab and back-button focus treatment.
- `frontend/src/components/builder/__tests__/MapStackPanel.test.tsx` - Empty prompt and row state coverage.
- `frontend/src/components/builder/__tests__/map-stack.test.ts` - Unsupported and missing terrain metadata coverage.
- `frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx` - Inspector keyboard focus coverage.
- `frontend/src/i18n/locales/{en,es,fr,de}/builder.json` - New empty-state and row-state copy.

## Decisions Made

- Kept the existing sidebar-local inspector model rather than introducing a new overlay.
- Used metadata already produced by `buildMapStack` for disabled/missing terrain state instead of adding new API fields.
- Preserved existing E2E contracts: `layer-item-*` row IDs and `Expand options` inspector action name.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Vitest continues to print the existing `--localstorage-file` warning; targeted tests pass.

## User Setup Required

None - no external service configuration required.

## Verification

- `cd frontend && npm run test -- MapStackPanel map-stack LayerStyleEditor --run` - passed, 3 files / 50 tests.
- `cd frontend && npm run lint` - passed.

## Next Phase Readiness

Phase 1004 can polish deeper styling/filter controls on top of a clearer stack and inspector interaction surface. Phase 1005 still owns public viewer stable identity for legacy duplicate-order maps if required.

---
*Phase: 1003-map-stack-inspector-interaction-polish*
*Completed: 2026-05-11*
