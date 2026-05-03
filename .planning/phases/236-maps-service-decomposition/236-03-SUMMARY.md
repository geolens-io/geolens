---
phase: 236-maps-service-decomposition
plan: 03
subsystem: api
tags: [maps, layers, rbac]
requires:
  - phase: 236-02
    provides: CRUD module using shared helpers
provides:
  - Layer access checks and add/remove behavior in service_layers.py
affects: [maps-service-decomposition, boundary-guards]
tech-stack:
  added: []
  patterns: [Sibling implementation module behind public facade]
key-files:
  created:
    - backend/app/modules/catalog/maps/service_layers.py
  modified:
    - backend/app/modules/catalog/maps/service_crud.py
    - backend/app/modules/catalog/maps/service.py
key-decisions:
  - "Moved dataset access checks with layer mutation helpers because duplicate and add-layer paths share that behavior."
patterns-established:
  - "Layer modules use service_shared.py for style/type metadata and never import the facade."
requirements-completed: [MAPS-01, MAPS-02, MAPS-04]
duration: 21min
completed: 2026-05-03
---

# Phase 236: Plan 03 Summary

**Layer access checks and add/remove layer mutation behavior now live in `service_layers.py`.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-05-03T22:25:56Z
- **Completed:** 2026-05-03T22:46:43Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Extracted `bulk_check_dataset_access`, `add_layer`, and `remove_layer` into `service_layers.py`.
- Preserved restricted dataset grants, `UserRole` checks, popup config serialization, raster empty paint/layout behavior, vector default styles, and delete rowcount behavior.
- Wired `duplicate_map` to use the layer helper directly without importing the facade.

## Task Commits

1. **Task 1: Extract layer access and mutation helpers** - `48a01a5b` (feat)
2. **Task 2: Wire duplicate and replacement paths to layer helpers** - `48a01a5b` (feat)

## Files Created/Modified

- `backend/app/modules/catalog/maps/service_layers.py` - Layer access and mutation implementation.
- `backend/app/modules/catalog/maps/service_crud.py` - Duplicate path imports dataset access helper from `service_layers.py`.
- `backend/app/modules/catalog/maps/service.py` - Public facade re-exporting layer symbols.

## Decisions Made

Kept `_replace_layers` in `service_crud.py` because it is part of update-map replacement behavior, while it uses shared style/type helpers.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Sharing, public viewer, token, and dataset-in-use logic can be moved without crossing through CRUD or layer mutation internals.

## Self-Check: PASSED

---
*Phase: 236-maps-service-decomposition*
*Completed: 2026-05-03*
