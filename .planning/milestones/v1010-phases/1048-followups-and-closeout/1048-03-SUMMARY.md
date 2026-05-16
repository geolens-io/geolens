---
phase: 1048-followups-and-closeout
plan: 03
subsystem: testing
tags: [vitest, react-testing-library, SourcesTab, vrt, dataset]

# Dependency graph
requires:
  - phase: 1048-02
    provides: prior followup tasks in the same closeout phase
provides:
  - "8 live vitest cases covering SourcesTab backlog (position order, link href, banners, disabled states, confirm dialog, source picker filter)"
  - "Deletion of .planning/backlog/SourcesTab-test-todos.md — backlog drained to zero"
affects: [future SourcesTab feature work, CI coverage gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level vi.mock('@/api/search') for testing useQuery-dependent components"
    - "fireEvent.click + screen.findByText for async picker interaction in vitest"

key-files:
  created: []
  modified:
    - frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
  deleted:
    - .planning/backlog/SourcesTab-test-todos.md

key-decisions:
  - "All 8 backlog items shipped as live tests — no migrations needed; component implements every described behavior"
  - "Picker filter test uses vi.mock('@/api/search') to intercept useQuery searchDatasets call; assertion targets picker button roles to avoid false positives from table text"
  - "Remove dialog test uses screen.getAllByText (multiple elements) rather than getByText to handle title+action button duplication"

patterns-established:
  - "To test the source-picker filter, mock @/api/search at module level and assert absence of linked IDs as button roles (not raw text, which may appear in the table)"

requirements-completed:
  - FOLLOWUP-03

# Metrics
duration: 8min
completed: 2026-05-16
---

# Phase 1048 Plan 03: SourcesTab Test Drain Summary

**Drained all 8 deferred SourcesTab vitest backlog items to live passing tests; net it.todo count is 0 and backlog file deleted**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-16T22:25:00Z
- **Completed:** 2026-05-16T22:33:46Z
- **Tasks:** 2
- **Files modified:** 1 (test file); 1 deleted (backlog doc)

## Accomplishments

- Shipped all 8 SourcesTab backlog cases as live vitest assertions (9 new tests total — "disables add" and "disables remove when regenerating" are split for clarity)
- Added `vi.mock('@/api/search')` to enable async picker-filter testing without a real network layer
- Deleted `.planning/backlog/SourcesTab-test-todos.md` per its own "delete when all 8 are landed" instruction
- FOLLOWUP-03 complete: net `it.todo` count = 0, vitest 11/11 pass, typecheck clean

## Shipped Test Cases

| # | Backlog Item | Test Name | Commit |
|---|---|---|---|
| 1 | renders source table with rows in position order | `renders source table with rows in position order` | ffb5e5de |
| 2 | source title is a clickable link to /datasets/{dataset_id} | `source title is a clickable link to /datasets/{dataset_id}` | ffb5e5de |
| 3 | shows regenerating banner when status === "regenerating" | `shows regenerating banner when dataset.raster.status === "regenerating"` | ffb5e5de |
| 4 | shows failed banner when status === "failed" | `shows failed banner when dataset.raster.status === "failed"` | ffb5e5de |
| 5 | disables add/remove when regenerating (add) | `disables the Add Source button when status is "regenerating"` | ffb5e5de |
| 6 | disables add/remove when regenerating (remove) | `disables remove buttons when status is "regenerating"` | ffb5e5de |
| 7 | remove button triggers confirm dialog | `remove button triggers the confirm dialog` | ffb5e5de |
| 8 | disables remove when only 2 sources | `disables remove buttons when only 2 sources remain (minimum floor)` | ffb5e5de |
| 9 | add source picker filters out already-linked sources | `add source picker filters out already-linked sources from search results` | ffb5e5de |

Note: Items 5+6 were both captured under "disables add/remove when regenerating" — shipped as two focused tests rather than one compound test.

## Migrated Items

None — all 8 backlog items shipped as live tests.

## Task Commits

1. **Task 1: Ship live vitest cases for SourcesTab backlog items** - `ffb5e5de` (feat)
2. **Task 2: Delete the backlog document** - `962e1897` (chore)

## Files Created/Modified

- `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx` — added 8 new it() blocks + `vi.mock('@/api/search')` module mock; +176 lines
- `.planning/backlog/SourcesTab-test-todos.md` — deleted (all items shipped)

## Decisions Made

- Backlog item 5 ("disables add/remove when regenerating") was split into two tests: one for Add Source button, one for remove buttons. This produced cleaner single-assertion tests and is within the ≤20 LOC per test budget.
- Picker filter test (`screen.findByText` for the unlinked result + `screen.queryAllByRole('button', ...)` for the absence check) avoids false positives because "Source COG A" appears both in the table and potentially in the picker.
- `vi.mock('@/api/search')` added at module level alongside the existing vrt hooks mock. `searchDatasets` is resolved directly via TanStack Query's `enabled` gate (query fires once the debounced input reaches ≥2 chars via `fireEvent.change`).

## Deviations from Plan

None — plan executed exactly as written. All 8 items shipped; no migrations required.

## Issues Encountered

Two test failures on first run (both fixed immediately):
1. `getByText('Remove Source')` matched both the dialog `<h2>` title and the `<AlertDialogAction>` button — fixed to `getAllByText(...).length > 0` after confirming `getByRole('alertdialog')` is the primary assertion.
2. `queryByText('Source COG A')` found the text in the source table, not just the picker — fixed to query for `role='button'` named "Source COG A" which only picker items would match.

## User Setup Required

None.

## Next Phase Readiness

FOLLOWUP-03 is complete. All SourcesTab test debt from Phase 278 (TEST-07) is closed. No open backlog items remain for this component.

---
*Phase: 1048-followups-and-closeout*
*Completed: 2026-05-16*

## Self-Check

### Created files exist:
- `frontend/src/components/dataset/__tests__/SourcesTab.test.tsx` — FOUND (modified)
- `.planning/backlog/SourcesTab-test-todos.md` — FOUND deleted (expected)

### Commits exist:
- `ffb5e5de` — FOUND (feat commit, Task 1)
- `962e1897` — FOUND (chore commit, Task 2)

### Verification:
- `grep -c 'it.todo' SourcesTab.test.tsx` = 0 — PASS
- `npx vitest run SourcesTab.test.tsx` = 11/11 passed — PASS
- `npx tsc --noEmit` = clean — PASS
- backlog file deleted — PASS

## Self-Check: PASSED
