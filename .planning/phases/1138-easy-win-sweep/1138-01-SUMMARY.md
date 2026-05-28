---
phase: 1138-easy-win-sweep
plan: "01"
subsystem: ui
tags: [keyboard, save, builder, vitest, maplibre]

requires: []
provides:
  - "Cmd/Ctrl+S listener in use-builder-save.ts unconditionally calls preventDefault and gates handleSave behind dialog-open check"
affects:
  - 1138-easy-win-sweep

tech-stack:
  added: []
  patterns:
    - "dialog-open detection via document.querySelector('[role=\"dialog\"][data-state=\"open\"]') to gate keyboard shortcuts from racing open-modal mutations"
    - "preventDefault moved above isPending guard so browser Save UI is always suppressed in the builder"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts

key-decisions:
  - "preventDefault fires unconditionally on Cmd/Ctrl+S (above the isPending guard) so the browser Save Page As dialog is suppressed in all cases, not just when a save can proceed"
  - "Dialog-open detection uses DOM querySelector on Radix data-state=open contract rather than React state, keeping the check synchronous and decoupled from any specific modal's state"

patterns-established:
  - "Radix dialog-open gate: document.querySelector('[role=\"dialog\"][data-state=\"open\"]') is the canonical check for blocking keyboard shortcuts when any modal is in front of the builder canvas"

requirements-completed:
  - EASY-02

duration: 8min
completed: 2026-05-27
---

# Phase 1138 Plan 01: Cmd/Ctrl+S preventDefault + dialog-open no-op gate Summary

**Cmd/Ctrl+S in the builder unconditionally suppresses the browser Save UI (preventDefault above isPending guard) and is a no-op when any Radix dialog is open (querySelector data-state=open gate), with 5 vitest regression pins.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-27T21:07:00Z
- **Completed:** 2026-05-27T21:15:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Moved `e.preventDefault()` above the `isPending` guard in the Cmd/Ctrl+S handler so the browser "Save Page As" dialog is suppressed in all cases when the builder is focused
- Added `document.querySelector('[role="dialog"][data-state="open"]')` gate so typing Cmd+S inside the Share dialog or Add Dataset modal does not race a layer mutation against open-modal context
- Added 5 EASY-02 regression tests pinning: dialog-open no-op, happy-path fires, preventDefault unconditional, plain-s no-op, unmount negative-control

## Task Commits

1. **Task 1: Add dialog-open no-op gate to Cmd/Ctrl+S listener** - `e45a0ccd` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `frontend/src/components/builder/hooks/use-builder-save.ts` - Added dialog-open querySelector gate; moved preventDefault above isPending guard
- `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` - 5 new EASY-02 regression tests in a dedicated describe block (lines ~894-982)

## New Test Names (EASY-02)

| # | Name | Behavior pinned |
|---|------|-----------------|
| 1 | `EASY-02 — no-op when a Radix dialog is open (role=dialog data-state=open)` | handleSave not called when dialog div in DOM |
| 2 | `EASY-02 — handleSave fires when no dialog is open` | happy-path with Ctrl+S |
| 3 | `EASY-02 — preventDefault fires even when save is pending` | preventDefault spy called unconditionally |
| 4 | `EASY-02 — plain s without modifier does NOT trigger handleSave or preventDefault` | modifier-key guard |
| 5 | `EASY-02 — keydown listener is removed on hook unmount (negative-control)` | listener cleanup on unmount |

## Decisions Made

- Used DOM querySelector for dialog detection rather than threading React state — keeps the check synchronous and decoupled from each individual modal's state.
- Placed the preventDefault call before all guards (dialog-open and isPending) since browser UI suppression should always apply when the builder is mounted.

## Deviations from Plan

None - plan executed exactly as written. The existing listener at lines 721-733 matched the documented shape; the two-line edit was applied as specified.

## Invariant Verification

- `BuilderLayerAction` / `BuilderActionSource` unchanged: `git diff -- frontend/src/components/builder/builder-action-contract.ts` → 0 lines
- Pitfall #9 (no setPaintProperty / setLayoutProperty in use-builder-save.ts): grep returns 0 hits
- `data-state="open"` appears in use-builder-save.ts: 2 occurrences (comment + querySelector literal)
- `EASY-02` grep count in test file: 6 (>= 5 required)
- All 56 vitest tests pass (55 pre-existing + 1 upgraded Ctrl+S test now part of 56 total)
- typecheck: 0 errors

## Issues Encountered

None.

## Next Phase Readiness

- EASY-02 closed; plan 1138-02 (popup URL/media handling) can proceed independently.
- No carry-forward items from this plan.

---
*Phase: 1138-easy-win-sweep*
*Completed: 2026-05-27*
