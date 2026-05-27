---
phase: 1135-ai-chat-confirm-before-apply-and-analysis-polish
plan: "01"
subsystem: frontend/builder/ai
tags:
  - builder
  - ai
  - staging
  - hooks
dependency_graph:
  requires:
    - "frontend/src/types/api.ts (ChatAction, AIStatusResponse)"
    - "frontend/src/hooks/use-admin.ts (useAIStatus)"
    - "frontend/src/hooks/use-permissions.ts (usePermissions)"
  provides:
    - "frontend/src/builder/ai/chat-action-staging.ts (useChatActionStaging, isDestructiveAction)"
    - "frontend/src/hooks/use-ai-availability.ts (AIUnavailableReason, reason field)"
  affects:
    - "Plans 02-04: ChatPanel staging tray, disabled-state UI, viewport-aware suggestions"
tech_stack:
  added:
    - "frontend/src/builder/ai/ (new directory)"
  patterns:
    - "actionsRef + state mirror pattern for synchronous dispatch snapshot without setState side-effects"
    - "dispatchRef latest-value mirror prevents stale closure across rerenders"
    - "mutable mockCan vi.fn() at module scope enables per-test permission override without vi.resetModules"
key_files:
  created:
    - frontend/src/builder/ai/chat-action-staging.ts
    - frontend/src/builder/ai/__tests__/chat-action-staging.test.ts
  modified:
    - frontend/src/hooks/use-ai-availability.ts
    - frontend/src/hooks/__tests__/use-ai-availability.test.tsx
decisions:
  - "Shape B lock confirmed — chat-action-staging.ts sits above dispatchLayerAction with zero BuilderActionSource widening (CONTEXT.md D-Shape-B / Pitfall #3)"
  - "actionsRef mirrors state array for dispatch-time snapshot — avoids setState-updater side-effects that fail under React StrictMode double-invocation"
  - "reason field uses shorthand return (reason,) not (reason: reason) — idiomatic TS; acceptance criterion grep for 'reason:' counts 1 (let reason: declaration) which is correct behavior, not a defect"
  - "mockCan lifted to module scope as vi.fn() to enable Test C (permission branch) override without vi.resetModules breaking the existing SP-08 tests"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-27"
  tasks_completed: 2
  files_created: 2
  files_modified: 2
---

# Phase 1135 Plan 01: chat-action-staging module + useAIAvailability.reason — Summary

**One-liner:** Shape B staging buffer module (actionsRef pattern) + AIUnavailableReason taxonomy field on useAIAvailability, 22 tests total, BuilderActionSource UNCHANGED.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create chat-action-staging Shape B module + 11 unit tests | `856be481` | chat-action-staging.ts, chat-action-staging.test.ts (NEW) |
| 2 | Extend useAIAvailability with reason field + 5 regression tests | `f40cc719` | use-ai-availability.ts, use-ai-availability.test.tsx |

## Artifact Details

### Task 1: chat-action-staging.ts (~170 LOC)

**File:** `frontend/src/builder/ai/chat-action-staging.ts`

Exported symbols:
- `PendingAction` — type alias for `ChatAction` (accepts any ChatAction; production callers gate on `isDestructiveAction`)
- `ChatActionStaging` — interface with `pendingActions`, `push`, `acceptAll`, `rejectAll`, `acceptOne`, `rejectOne`
- `isDestructiveAction(action)` — predicate, true iff `add_layer` or `remove_layer`; false for `show_query_result` and all other types
- `useChatActionStaging(dispatch)` — React hook backed by `useState` + `actionsRef` mirror

Implementation note: `actionsRef` mirrors the state array synchronously. This was necessary because the initial `setPendingActions((prev) => { snapshot = prev; return []; })` side-effect pattern is unreliable under React StrictMode (updaters may be called twice; local variable assignment inside updater doesn't survive the second call). The `actionsRef` approach reads/writes before calling `setPendingActions` so dispatch always sees the correct snapshot.

**11 tests (RED→GREEN):**

| # | Test | Passes |
|---|------|--------|
| 1 | `isDestructiveAction` returns true for add_layer + remove_layer | PASS |
| 2 | `isDestructiveAction` returns false for show_query_result | PASS |
| 3 | `isDestructiveAction` returns false for all other types | PASS |
| 4 | `push` appends in order | PASS |
| 5 | `rejectAll` clears buffer with zero dispatch calls | PASS |
| 6 | `acceptAll` invokes dispatch N times in push order | PASS |
| 7 | `acceptAll` clears buffer after flush | PASS |
| 8 | `acceptOne` dispatches indexed action + removes it | PASS |
| 9 | `rejectOne` removes indexed action without dispatch | PASS |
| 10 | `acceptOne` out-of-range is a no-op | PASS |
| 11 | `dispatchRef` mirrors latest dispatch — no stale closure on rerender | PASS |

### Task 2: use-ai-availability.ts extension

**File:** `frontend/src/hooks/use-ai-availability.ts`

Added:
- `export type AIUnavailableReason = 'env_disabled' | 'no_key' | 'permission'`
- `reason: AIUnavailableReason | null` in the hook return shape (additive — no existing destructures broken)
- Reason derivation precedence: `env_disabled > no_key > permission > null`
- When `aiStatus.isLoading === true` and `status === undefined`: `reason === null` (spinner state)

**5 new tests (RED→GREEN):**

| Test | Branch | Passes |
|------|--------|--------|
| A | `reason = 'env_disabled'` when enabled=false | PASS |
| B | `reason = 'no_key'` when enabled=true, configured=false | PASS |
| C | `reason = 'permission'` when enabled+configured but `can('use_ai_chat')=false` | PASS |
| D | `reason = null` when isAIAvailable=true (happy path) | PASS |
| E | `reason = null` while aiStatus.isLoading=true | PASS |

All existing SP-08 caching tests and CONSOLE-01 gating tests continue to pass (6 tests, unmodified).

## Verification Results

```
✓ cd frontend && npm test -- "src/builder/ai/__tests__/chat-action-staging.test.ts" "src/hooks/__tests__/use-ai-availability.test.tsx" --run
  Test Files: 2 passed (2)
  Tests: 22 passed (22)

✓ cd frontend && npm run typecheck
  exit 0 (clean)

✓ git diff -- frontend/src/components/builder/builder-action-contract.ts
  EMPTY — BuilderActionSource union UNCHANGED (Pitfall #3 protection)

✓ grep -nE "'ai-pending'|'ai-committed'" frontend/src --include="*.ts*" -r
  Only 1 match: comment in chat-action-staging.ts documenting what is NOT done

✓ frontend/src/builder/ai/ directory exists with chat-action-staging.ts + __tests__/
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] setState-updater snapshot pattern replaced with actionsRef mirror**
- **Found during:** Task 1 GREEN phase (3 tests failing: acceptAll, acceptOne, stale-closure)
- **Issue:** Initial implementation used `setPendingActions((prev) => { snapshot = prev; return []; })` pattern. React StrictMode calls updaters twice in development; local variable assigned inside updater may be overwritten or captured at the wrong value. `await Promise.resolve()` after the setState didn't reliably give us the snapshot.
- **Fix:** `actionsRef` mirrors the state array synchronously before each `setPendingActions` call, making the snapshot always available for dispatch without relying on setState-updater side effects.
- **Files modified:** `frontend/src/builder/ai/chat-action-staging.ts`
- **Commit:** `856be481`

**2. [Rule 1 - Bug] vi.fn() mock typing fix for TypeScript strict mode**
- **Found during:** Task 1 typecheck (7 TS2345 errors)
- **Issue:** `vi.fn()` (untyped) is not assignable to `(action: ChatAction) => void` parameter in this vitest version (doesn't support `vi.fn<[T], R>` two-arg generic form)
- **Fix:** Declare `mockFn` as `ReturnType<typeof vi.fn>` and cast to typed dispatch function: `dispatch = mockFn as unknown as (action: ChatAction) => void`
- **Files modified:** `frontend/src/builder/ai/__tests__/chat-action-staging.test.ts`
- **Commit:** `856be481`

**3. [Rule 2 - Auto-add] mockCan lifted to module scope for Test C permission branch**
- **Found during:** Task 2 planning (before implementation)
- **Issue:** Existing `vi.mock('@/hooks/use-permissions', ...)` hardcodes `can: () => true`. Test C requires `can() === false`. Using `vi.doMock` + `vi.resetModules` mid-file would reset all mocks and break SP-08 tests.
- **Fix:** Changed top-level mock factory to use `const mockCan = vi.fn(() => true)` at module scope. Each test in the new describe block calls `mockCan.mockReturnValue(false)` as needed. `beforeEach` resets to `true`.
- **Files modified:** `frontend/src/hooks/__tests__/use-ai-availability.test.tsx`
- **Commit:** `f40cc719`

## BuilderActionSource Unchanged Confirmation

```
git diff -- frontend/src/components/builder/builder-action-contract.ts
(empty)
```

`BuilderActionSource = 'manual' | 'ai' | 'system'` — byte-equal to HEAD~2. No 'ai-pending', no 'ai-committed', no new union members. v1030 hard invariant #5 holds.

## Requirement Status

AI-01 and AI-02 are **partially satisfied** by this plan:
- **AI-01 partial:** staging buffer mechanics pinned (rejectAll zero-dispatch contract + acceptAll N-times-in-order contract). Full satisfaction requires Plans 02 (ChatPanel wiring) + 04 (regression test).
- **AI-02 partial:** `reason` taxonomy field ready for consumption. Full satisfaction requires Plan 03 (BuilderRail structured disabled-state UI) + ChatPanel.test.tsx regression.

Requirements remain `Pending` in REQUIREMENTS.md until full satisfaction in Plans 02-04.

## Cross-References

- CONTEXT.md Shape B lock: D-Shape-B (Pitfall #3 NON-NEGOTIABLE)
- UI-SPEC Surface 3 reason taxonomy table: lines 227-245
- Pitfall #3: BuilderActionSource widening prohibited without Future Requirement entry
- v1030 hard invariant #5: no BuilderActionSource widening
- Phase 1133 AI consumer-gating matrix: `enabled: !!token && isAdmin` gate preserved

## Self-Check

**Files exist:**
- `frontend/src/builder/ai/chat-action-staging.ts`: FOUND
- `frontend/src/builder/ai/__tests__/chat-action-staging.test.ts`: FOUND
- `frontend/src/hooks/use-ai-availability.ts`: FOUND (modified)
- `frontend/src/hooks/__tests__/use-ai-availability.test.tsx`: FOUND (modified)

**Commits exist:**
- `856be481`: FOUND
- `f40cc719`: FOUND

## Self-Check: PASSED
