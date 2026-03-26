---
phase: 207-branding-toggle
plan: 01
subsystem: api
tags: [persistent-config, branding, enterprise-gating, fastapi]

requires:
  - phase: 206-extension-seam-architecture
    provides: require_enterprise() guard, edition detection
provides:
  - BRANDING_SHOW_BADGE PersistentConfig[bool] instance (key branding.show_badge, default true)
  - Public GET /api/settings/branding/ endpoint
  - Enterprise-gated PUT /api/settings/branding/ endpoint
affects: [207-02, frontend branding toggle UI]

tech-stack:
  added: []
  patterns: [enterprise-gated PUT with public GET for settings]

key-files:
  created:
    - backend/tests/test_branding_settings.py
  modified:
    - backend/app/persistent_config.py
    - backend/app/settings/router.py

key-decisions:
  - "PUT branding endpoint returns 404 in community mode via require_enterprise() guard"
  - "GET branding endpoint is fully public (no auth) so badge logic works for anonymous users"

patterns-established:
  - "Enterprise-gated setting: public GET for reading, enterprise-gated PUT for writing"

requirements-completed: [COMP-04, COMP-05]

duration: 4min
completed: 2026-03-26
---

# Phase 207 Plan 01: Backend Branding API Summary

**PersistentConfig branding.show_badge with public GET and enterprise-gated PUT endpoints, 4 passing tests**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-26T19:26:16Z
- **Completed:** 2026-03-26T19:30:46Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added BRANDING_SHOW_BADGE PersistentConfig[bool] with key "branding.show_badge" defaulting to true
- Added public GET /settings/branding/ endpoint returning show_badge value without auth
- Added enterprise-gated PUT /settings/branding/ with require_enterprise() and require_permission("manage_settings")
- 4 integration tests all passing: default GET, community 404, invalid body, config override

## Task Commits

Each task was committed atomically:

1. **Task 1: Add BRANDING_SHOW_BADGE PersistentConfig and branding API endpoints** - `4b186e26` (feat)
2. **Task 2: Test branding endpoints** - `9eaec526` (test)

## Files Created/Modified
- `backend/app/persistent_config.py` - Added BRANDING_SHOW_BADGE PersistentConfig[bool] in branding tab
- `backend/app/settings/router.py` - Added GET and PUT /settings/branding/ endpoints with enterprise gating
- `backend/tests/test_branding_settings.py` - 4 tests covering default, enterprise gate, validation, and override

## Decisions Made
- PUT endpoint uses require_enterprise() guard (returns 404 in community mode) before body validation
- GET endpoint is fully public (no auth) so badge visibility works for anonymous/embed users

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Backend branding API ready for frontend consumption in 207-02
- GET /api/settings/branding/ returns {"show_badge": true} by default
- PUT /api/settings/branding/ enterprise-gated and tested

---
*Phase: 207-branding-toggle*
*Completed: 2026-03-26*
