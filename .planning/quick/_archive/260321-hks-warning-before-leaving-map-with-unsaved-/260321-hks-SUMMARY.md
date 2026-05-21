---
phase: quick-260321-hks
plan: 01
subsystem: ui
tags: [react-router, useBlocker, beforeunload, map-builder, i18n]

provides:
  - "Unsaved changes navigation guard for Map Builder (beforeunload + useBlocker)"
affects: [map-builder]

tech-stack:
  added: []
  patterns: ["useBlocker for in-app navigation guarding", "beforeunload for browser tab close/refresh guard"]

key-files:
  created: []
  modified:
    - frontend/src/hooks/use-builder-save.ts
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/hooks/__tests__/use-builder-save.test.ts
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json

key-decisions:
  - "Mock useBlocker in tests rather than switching to createMemoryRouter -- avoids refactoring all existing test infrastructure"

requirements-completed: [QUICK-260321-HKS]

duration: 3min
completed: 2026-03-21
---

# Quick Task 260321-HKS: Unsaved Changes Navigation Guard Summary

**Browser beforeunload + react-router useBlocker guards with i18n confirmation dialog for Map Builder unsaved changes**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-21T16:45:17Z
- **Completed:** 2026-03-21T16:48:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Browser beforeunload handler prevents tab close/refresh when map has unsaved changes
- react-router useBlocker intercepts in-app navigation with unsaved changes, showing a Stay/Leave confirmation dialog
- All 4 locale files (en/de/es/fr) have leaveWarning keys
- 3 new unit tests verify blocker return and beforeunload listener lifecycle

## Task Commits

1. **Task 1: Add navigation guards and i18n keys** - `ab8810f7` (feat)
2. **Task 2: Add tests and verify no regressions** - `ecfa4c34` (test)

## Files Created/Modified
- `frontend/src/hooks/use-builder-save.ts` - Added hasUnsavedChanges to SaveState, beforeunload useEffect, useBlocker call, blocker in return
- `frontend/src/pages/MapBuilderPage.tsx` - Pass hasUnsavedChanges to useBuilderSave, render leave-warning Dialog
- `frontend/src/hooks/__tests__/use-builder-save.test.ts` - Mock useBlocker, update SaveState, add 3 new test cases
- `frontend/src/i18n/locales/en/builder.json` - leaveWarning section (title, description, stay, leave)
- `frontend/src/i18n/locales/de/builder.json` - leaveWarning section (German)
- `frontend/src/i18n/locales/es/builder.json` - leaveWarning section (Spanish)
- `frontend/src/i18n/locales/fr/builder.json` - leaveWarning section (French)

## Decisions Made
- Mock useBlocker in tests rather than switching to createMemoryRouter -- avoids refactoring all existing test infrastructure while still verifying the hook returns blocker and beforeunload behavior

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Mock useBlocker for data router requirement in tests**
- **Found during:** Task 2
- **Issue:** useBlocker requires a data router context (createMemoryRouter), but test-utils uses MemoryRouter
- **Fix:** Added vi.mock for react-router that re-exports actual module but overrides useBlocker with a mock
- **Files modified:** frontend/src/hooks/__tests__/use-builder-save.test.ts
- **Verification:** All 10 tests pass
- **Committed in:** ecfa4c34

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to make tests pass with existing test infrastructure. No scope creep.

## Issues Encountered
- Pre-existing test failures in i18n/resources.test.ts (missing nav.importData key) and PageShell.test.tsx -- not related to this task

## Known Stubs
None

---
*Quick Task: 260321-hks*
*Completed: 2026-03-21*
