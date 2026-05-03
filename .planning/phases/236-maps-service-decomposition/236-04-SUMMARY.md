---
phase: 236-maps-service-decomposition
plan: 04
subsystem: api
tags: [maps, sharing, public-viewer]
requires:
  - phase: 236-03
    provides: Layer helpers and CRUD module
provides:
  - Sharing, public viewer, token, and dataset-in-use behavior in service_public.py
affects: [maps-service-decomposition, boundary-guards]
tech-stack:
  added: []
  patterns: [Sibling implementation module behind public facade]
key-files:
  created:
    - backend/app/modules/catalog/maps/service_public.py
  modified:
    - backend/app/modules/catalog/maps/service.py
key-decisions:
  - "Kept EmbedToken as a function-local import inside list_share_tokens."
patterns-established:
  - "Public/share behavior imports CRUD fallback and shared visibility helpers directly from siblings."
requirements-completed: [MAPS-01, MAPS-02, MAPS-05]
duration: 21min
completed: 2026-05-03
---

# Phase 236: Plan 04 Summary

**Sharing, public viewer, token administration, and dataset-in-use checks moved into `service_public.py`.**

## Performance

- **Duration:** 21 min
- **Started:** 2026-05-03T22:25:56Z
- **Completed:** 2026-05-03T22:46:43Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Extracted public visibility validation, dataset-in-use checks, share token creation/update/list/revocation, token validation, shared-layer rendering, shared-map rendering, and dataset map listing.
- Preserved advanced sharing gates, token hashing/hints, expired-token sentinel returns, `CatalogPort` raster asset lookup, and public vs authenticated tile URL strings.
- Kept admin, dataset, router, and tests importing from `app.modules.catalog.maps.service`.

## Task Commits

1. **Task 1: Extract sharing and public viewer implementation** - `48a01a5b` (feat)
2. **Task 2: Preserve public facade imports for cross-domain callers** - `48a01a5b` (feat)

## Files Created/Modified

- `backend/app/modules/catalog/maps/service_public.py` - Sharing, public viewer, tokens, and dataset-in-use implementation.
- `backend/app/modules/catalog/maps/service.py` - Public facade re-exporting public/share symbols.

## Decisions Made

The shared-map fallback uses `get_map` from `service_crud.py` directly, preserving behavior without creating a facade import cycle.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The implementation is split by concern and ready for final facade cleanup plus regression coverage.

## Self-Check: PASSED

---
*Phase: 236-maps-service-decomposition*
*Completed: 2026-05-03*
