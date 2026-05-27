---
phase: 1134-map-functionality-and-smaller-screen-polish
plan: "03"
subsystem: testing
tags: [vitest, builder, rename-focus, rAF, dnd-kit, radix, regression-tests]

requires:
  - phase: v1011-map-builder-polish-and-bug-sweep
    provides: BUG-03 rAF-deferred focus fix at commit 80bddc14 in FolderGroupRow.tsx

provides:
  - MAP-16 regression guard: two test surfaces pin the v1011 BUG-03 rAF-deferred focus contract
  - Integration test in UnifiedStackPanel.test.tsx covering rename-group focus end-to-end
  - Negative-control test in FolderGroupRow.test.tsx that fails if rAF deferral is removed

affects:
  - FolderGroupRow.tsx (protected from regressing to synchronous focus)
  - UnifiedStackPanel.tsx (integration path pinned at test level)

tech-stack:
  added: []
  patterns:
    - "?raw Vite import for source-text assertions (existing project pattern, reused)"
    - "vi.importActual to bypass module-level vi.mock for integration testing real component"
    - "rafCallbacks capture pattern: stub rAF to array, flush manually with act()"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
    - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx

key-decisions:
  - "Used ?raw Vite import for source-text pin (established pattern from preserve-drawing-buffer.test.ts) instead of plan-suggested fs.readFileSync — avoids @types/node dependency"
  - "Integration test in UnifiedStackPanel.test.tsx renders real FolderGroupRow via vi.importActual (module-level mock stubs it for routing tests; importActual bypasses that for MAP-16 block)"
  - "Negative-control asserts rafCallbacks.length > 0 rather than pre-flush focus absence: autoFocus on the <input> gives jsdom synchronous focus, so absence-before-flush is not testable; the rAF call count is the definitive contract signal"
  - "Regex in source-text pin uses inputRef.current[\\s\\S]{0,10}?.focus (not optional chaining) to match actual source: if(inputRef.current) { inputRef.current.focus() } rather than inputRef.current?.focus()"

requirements-completed:
  - MAP-16

duration: 4min
completed: 2026-05-27
---

# Phase 1134 Plan 03: Rename-group rAF Focus Integration Test + Negative-Control Pin Summary

**MAP-16 regression tests: rAF-deferred focus pinned at UnifiedStackPanel.test.tsx (integration) and FolderGroupRow.test.tsx (negative control), protecting v1011 BUG-03 fix at commit 80bddc14**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-27T16:23:42Z
- **Completed:** 2026-05-27T16:27:35Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- 2 new MAP-16 tests in UnifiedStackPanel.test.tsx: integration test (vi.importActual real FolderGroupRow, double-click rename, rAF flush, focus assertion) + source-text pin (?raw import, regex matches rAF wrapping the focus call)
- 1 new MAP-16 negative-control test in FolderGroupRow.test.tsx: stubs rAF to capture callbacks, proves rAF deferral path executes (rafCallbacks.length > 0), flushes manually, asserts focus lands
- Zero source code changes — pure test-pin work as specified

## Task Commits

1. **Task 1: UnifiedStackPanel.test.tsx — integration + source-text pin** - `ea37f230` (test)
2. **Task 2: FolderGroupRow.test.tsx — negative-control pin** - `120b5128` (test)

## Files Created/Modified

- `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` — Added `?raw` import of FolderGroupRow.tsx, `DraggableAttributes`/`DraggableSyntheticListeners` type imports, and MAP-16 describe block with 2 tests (integration + source-text pin)
- `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` — Added `act` to test-utils import, appended negative-control test to existing BUG-03 describe block

## Decisions Made

- **?raw over fs.readFileSync**: The plan suggested `fs.readFileSync` but the project's established pattern (preserve-drawing-buffer.test.ts) uses Vite's `?raw` import. Using `?raw` avoids adding `@types/node` to tsconfig.app.json.
- **vi.importActual for integration test**: The module-level `vi.mock('../FolderGroupRow', ...)` stubs the component for routing logic tests. Using `vi.importActual` in the MAP-16 describe block gets the real component without disturbing the stubs used by existing tests.
- **rafCallbacks.length > 0 as key assertion**: The `<input>` in FolderGroupRow has `autoFocus` which gives jsdom synchronous focus on mount. The plan's "assert not focused before rAF flush" is not achievable because autoFocus fires synchronously. The corrected contract: asserting the rAF queue received a callback proves the deferred path exists; if someone removes the rAF wrapper, rafCallbacks would be empty and the test fails.
- **Regex adjustment**: Plan specified `inputRef\.current\?\.focus` (optional chaining) but actual source uses `if (inputRef.current) { inputRef.current.focus() }` (explicit guard). Regex updated to `inputRef\.current[\s\S]{0,10}?\.focus` to match real source.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Source-text regex adapted to match actual source pattern**
- **Found during:** Task 1 (first test run)
- **Issue:** Plan specified `inputRef.current?.focus` with optional chaining but FolderGroupRow.tsx line 96 uses `inputRef.current.focus()` with an explicit `if (inputRef.current)` guard
- **Fix:** Changed regex to `inputRef\.current[\s\S]{0,10}?\.focus` to match the actual pattern
- **Files modified:** frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
- **Verification:** Test runs green after fix; both regex patterns validated via node -e against source
- **Committed in:** ea37f230 (Task 1 commit)

**2. [Rule 2 - Missing Critical] Negative-control assertion adapted for autoFocus behavior**
- **Found during:** Task 2 design
- **Issue:** Plan's "assert not focused before rAF flush" is untestable — `autoFocus` on the `<input>` gives immediate jsdom focus, making pre-flush absence assertion always false
- **Fix:** Replaced with `expect(rafCallbacks.length).toBeGreaterThan(0)` — proves rAF path executed. If rAF deferral is removed, rafCallbacks stays empty and test fails correctly.
- **Files modified:** frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
- **Verification:** Test passes; negative-control invariant verified (if rAF removed from source, rafCallbacks.length would be 0)
- **Committed in:** 120b5128 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 source-text regex mismatch, 1 assertion design adapted for jsdom autoFocus)
**Impact on plan:** Both fixes necessary for correct test behavior. No scope changes.

## Issues Encountered

None beyond the two deviations documented above.

## Self-Check

Cross-reference v1011 BUG-03 commit `80bddc14`: the rAF-deferred focus fix is now doubly pinned.

- `grep -nE "describe.*MAP-16" frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` → line 644
- `grep -nE "negative control.*synchronously" frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` → line 453
- `cd frontend && npm test -- "UnifiedStackPanel" "FolderGroupRow" -- --run` → 108/108 PASS
- `cd frontend && npm run typecheck` → 0 errors
- `git diff --name-only frontend/src/components/builder/ | grep -v __tests__` → empty (no source changes)

## Next Phase Readiness

MAP-16 satisfied. Plan 1134-04 can proceed.

---
*Phase: 1134-map-functionality-and-smaller-screen-polish*
*Completed: 2026-05-27*
