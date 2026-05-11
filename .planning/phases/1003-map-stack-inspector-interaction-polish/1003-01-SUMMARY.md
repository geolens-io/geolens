---
phase: 1003-map-stack-inspector-interaction-polish
plan: 01
subsystem: backend
tags: [map-builder, map-layers, sort-order, api, pytest]

requires:
  - phase: 1002-kepler-guided-builder-workflow-audit-and-triage
    provides: F-1002-01 duplicate sort-order finding
provides:
  - Omitted add-layer sort orders resolve to the next available map layer order
  - Regression coverage for omitted and duplicate-dataset layer insertion
affects: [map-builder, layer-management, public-viewer-ordering]

tech-stack:
  added: []
  patterns: [Pydantic model_fields_set for omitted-field detection]

key-files:
  created: []
  modified:
    - backend/app/modules/catalog/maps/service_layers.py
    - backend/tests/test_maps.py

key-decisions:
  - "Only omitted sort_order values are auto-assigned; explicit values, including zero, remain honored."
  - "Use the highest existing map layer sort_order plus one as the next default order."

patterns-established:
  - "Map-layer create defaults can use Pydantic model_fields_set to distinguish omitted fields from explicit defaults."

requirements-completed: [STACK-02]

duration: 12min
completed: 2026-05-11
---

# Phase 1003 Plan 01: Stable Add-Layer Ordering Summary

**Add-layer calls without explicit order now append to the map stack instead of creating duplicate order values.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-11T20:15:00Z
- **Completed:** 2026-05-11T20:22:00Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments

- Updated `add_layer` to assign the next available `sort_order` when callers omit the field.
- Preserved explicit `sort_order` behavior for import and advanced callers.
- Added endpoint regression coverage for multiple omitted insertions and duplicate dataset layer insertion.

## Task Commits

1. **Task 1: Assign next available layer order when omitted** - `6f1c9669` (fix)
2. **Task 2: Cover omitted sort order insertion** - `8dbe1b97` (test)

## Files Created/Modified

- `backend/app/modules/catalog/maps/service_layers.py` - Resolves omitted sort order before creating a layer.
- `backend/tests/test_maps.py` - Covers omitted order and duplicate dataset insertion.

## Decisions Made

- Used `body.model_fields_set` so explicit `sort_order: 0` remains distinct from omission.
- Kept the fix in the service layer so all add-layer routes share the same behavior.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Initial backend pytest attempts failed because the local compose DB is published on port `5434`, not `5432`. Rerunning with `POSTGRES_PORT=5434` passed.

## User Setup Required

None - no external service configuration required.

## Verification

- `cd backend && POSTGRES_PORT=5434 uv run pytest tests/test_maps.py -k "add_layer"` - passed, 11 tests.
- `cd backend && uv run ruff check app/modules/catalog/maps/service_layers.py tests/test_maps.py` - passed.
- `cd backend && uv run ruff format --check app/modules/catalog/maps/service_layers.py tests/test_maps.py` - passed.

## Next Phase Readiness

Plan 1003-02 can rely on stable layer ordering for stack row selection, duplicate disambiguation, and reorder semantics.

---
*Phase: 1003-map-stack-inspector-interaction-polish*
*Completed: 2026-05-11*
