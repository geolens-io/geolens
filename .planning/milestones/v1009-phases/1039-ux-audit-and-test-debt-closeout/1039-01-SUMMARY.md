---
phase: 1039-ux-audit-and-test-debt-closeout
plan: 01
subsystem: frontend/builder/tests
tags: [test-debt, vitest, closeout, POL-19, POL-20, POL-21]
requires: [POL-19, POL-20, POL-21]
provides: [builder-vitest-green]
affects:
  - frontend/src/components/builder/__tests__/EmptyStackState.integration.test.tsx
  - frontend/src/components/builder/__tests__/StackRow.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
  - frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.groups.test.ts
key-files:
  modified:
    - frontend/src/components/builder/__tests__/EmptyStackState.integration.test.tsx
    - frontend/src/components/builder/__tests__/StackRow.test.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
    - frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.groups.test.ts
metrics:
  duration: ~1h15m
  tasks_completed: 3
  files_modified: 6
  tests_passing: 692
  tests_failing: 0
  worker_errors: 0
completed: 2026-05-14
---

# Phase 1039 Plan 01: Test Debt Closeout Summary

Closed the 5 pre-existing builder vitest failures (POL-19), resolved the
`use-builder-layers.add-dataset.test.ts` worker-exit regression (POL-20),
and brought `npx vitest run src/components/builder/` to fully green
(POL-21). Two additional pre-existing failures that had been masked by the
worker exit were also fixed in scope. **All test-only changes — production
code untouched.**

## Final Test Count (POL-21 evidence)

```
 Test Files  54 passed (54)
      Tests  692 passed (692)
   Duration  4.26s
```

No `Worker exited unexpectedly`, no `Timeout terminating forks worker`, no
`Unhandled Errors` block. Captured at `/tmp/1039-vitest.log`.

## Worker-exit root cause (POL-20 quote)

Quoted verbatim from
`frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts`
header comment:

> The previous version of this file shipped with two compounding problems
> that together produced `Worker exited unexpectedly` /
> `Timeout terminating forks worker` on every run (and a V8 heap OOM under
> `--pool=threads`):
>
> 1. 11 file-local `vi.mock(...)` factories for transitive deps
>    (react-router, react-i18next, sonner, use-ephemeral-layers,
>    use-layer-map-sync, map-sync, layer-adapters/registry, basemap-utils,
>    tile-utils, label-layer-utils, renderAs). The sibling
>    `use-builder-layers.test.ts` exercises the same hook with the same
>    `renderHook` wrapper and zero `vi.mock` declarations, runs in <1 s,
>    and passes 23/23. Direct bisection (copying the sibling's body into
>    this file's path) confirms the issue is per-file mock setup — once
>    removed, the same hook + wrapper + path combination passes.
>
> 2. `mapData.layers = []` (empty array) initial fixture. Combined with
>    the hook's two layer-init useEffects (`use-builder-layers.ts` lines
>    108-131) and the prior `vi.mock` graph, this produced a
>    microtask/promise loop that V8 surfaces as `Builtins_PromiseConstructor`
>    → `Builtins_PromiseFulfillReactionJob` → `MicrotaskQueue::RunMicrotasks`
>    recursion until the worker hits the heap limit and is SIGTERM'd.
>    Tests A/B/C/D never executed (`tests 0ms` in the reporter).
>
> Mitigation: drop the per-file `vi.mock` block AND pass a non-empty
> layers fixture (a single placeholder layer) to `useBuilderLayers`. The
> placeholder has no effect on the contract under test —
> `handleAddDataset` posts the new layer with `sort_order: 0` regardless
> of current stack size, and the addLayerMutation stub records the call
> without invoking any onSuccess/onError unless the test explicitly
> drives it.
>
> Alternatives attempted and rejected:
> - `afterEach(cleanup); afterEach(vi.clearAllMocks)` — does NOT resolve
>   the OOM (the leak is intra-test, not cross-test).
> - `vi.hoisted` stable-reference refactor for `useSearchParams` /
>   `useTranslation` mocks — does NOT resolve the OOM (mock factories
>   themselves are the trigger, not reference instability).
> - `--pool=threads` override — reproduces the same OOM as
>   `ERR_WORKER_OUT_OF_MEMORY`, confirming the issue is in-worker heap
>   exhaustion, not a forks-pool teardown bug.

## Tests Changed

### POL-19 set (Task 1 — 5 stale-setup failures)

- **EmptyStackState integration — BSR-17 / BSR-18 > Test 2: clicking suggest-card body calls onOpenAddData(suggestion.name)** — Added a module-level `vi.mock('@/components/builder/suggested-datasets', ...)` injecting a populated SUGGESTED_DATASETS fixture with valid UUID v4 IDs so the `SuggestCard` UUID_RE gate (`EmptyStackState.tsx:46-59`) does not hide the cards.
- **EmptyStackState integration — BSR-17 / BSR-18 > Test 3: clicking ＋ button calls onAddDataset(id) ...** — Same `vi.mock` fix; the test now finds `SUGGESTED_DATASETS[0]`.
- **EmptyStackState integration — BSR-17 / BSR-18 > Test 5 (regression): ＋ button stopPropagation** — Same `vi.mock` fix.
- **StackRow > clicking "Delete layer" in the kebab calls onRemove(layer.id)** — Updated to drive through the inline alertdialog confirm step (`StackRow.tsx:357-389`). Imports `within` from `@/test/test-utils` and clicks the destructive `Delete` button inside the alertdialog after the kebab item opens it.
- **UnifiedStackPanel > calls onAddDataClick when ＋ Add data button is clicked** — Renamed the `EmptyStackState` mock stub button from `Add dataset` to `Pick suggestion` to avoid substring collision with the header `＋ Add data` button under regex `/Add data/i`. Stub is only used to verify wiring (`onAddDataset` invocation) — no other reference relies on the old label.

### POL-20 set (Task 2 — 1 worker-exit regression)

- **handleAddDataset (BSR-18) > Test A/B/C/D** — Dropped the 11 file-local `vi.mock(...)` factories and switched to a non-empty `mapData.layers` fixture (single placeholder layer). All 4 tests now pass in <650 ms with no worker exit. Full root-cause + mitigation analysis is documented in the file header comment (quoted above for POL-20).

### Out-of-scope but in-scope-for-POL-21 (Task 3 — 2 pre-existing failures previously masked)

These were ALREADY broken on `6806d0d6` (plan-start commit) — confirmed by `git stash + git checkout 6806d0d6 -- frontend/src/` + re-run baseline. They had been hidden by the worker-exit terminating the suite before they could run.

- **useBuilderLayers — group_meta / groupMeta > handleToggleGroupExpand toggles groupMeta.basemap.expanded between true/false (UI-only; does NOT mark unsaved)** — Test asserted `hasUnsavedChanges = true` after toggle-expand, but commit `116fe289` (CR-02) intentionally removed that dirty flag because `group_meta` is not yet persisted to the backend schema, so dirtying the map on a UI-only expand was misleading. Test updated to assert `hasUnsavedChanges = false` (the shipped contract) with a comment pointing to the future work that will re-enable the dirty flag when `group_meta` joins the API payload.
- **LayerEditorPanel > editorScene dispatch > Test 6: testids layer-editor-* preserved on all scenes** — Test asserted `layer-editor-footer` is rendered on every editorScene, but the source (`LayerEditorPanel.tsx:680-684`) intentionally omits the footer for non-default scenes without an explicit `sceneFooter` prop. Test split into three checks: (a) default scene → footer present; (b) non-default without `sceneFooter` → footer omitted; (c) non-default WITH `sceneFooter` → footer present + sceneFooter rendered. Reflects shipped contract.

## Production code unchanged

`git diff --name-only 6806d0d6..HEAD -- frontend/src/` reports only the six
test files above. No production source modified. Specifically:

- `frontend/src/components/builder/hooks/use-builder-layers.ts` — untouched (verified via `git diff 6806d0d6..HEAD -- frontend/src/components/builder/hooks/use-builder-layers.ts` → empty diff).
- `frontend/src/test/test-utils.tsx` — untouched.
- `frontend/src/components/builder/EmptyStackState.tsx` — untouched.
- `frontend/src/components/builder/StackRow.tsx` — untouched.
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — untouched.
- `frontend/src/components/builder/LayerEditorPanel.tsx` — untouched.
- `frontend/src/components/builder/suggested-datasets.ts` — untouched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Two additional pre-existing failures revealed by Task 2**

- **Found during:** Task 3 (POL-21 sweep)
- **Issue:** After fixing POL-20 the worker no longer exits early, so two pre-existing failures (groups.test.ts:109, LayerEditorPanel.test.tsx:604) ran to completion and reported failure. Plan Task 3 explicitly directs: "If any new failure appears ... STOP and fix it in this plan before declaring done — POL-21 is the milestone gate and must be green."
- **Fix:** Bisected via `git checkout 6806d0d6 -- frontend/src/` to confirm both failures pre-dated this plan, then updated each test to assert the actual shipped contract (CR-02 dirty-flag removal; conditional footer rendering with `sceneFooter` prop).
- **Files modified:** `frontend/src/components/builder/hooks/__tests__/use-builder-layers.groups.test.ts`, `frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx`
- **Commit:** `5d41b804`

### Auth gates

None.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | `88e00ac7` | Close 5 stale builder vitest failures via test-setup corrections (POL-19) |
| 2 | `a6c6b409` | Resolve worker-timeout in use-builder-layers add-dataset test (POL-20) |
| 3 | `5d41b804` | Align two pre-existing tests with shipped behaviour (POL-21 unblock) |

## Self-Check: PASSED

- ✅ `frontend/src/components/builder/__tests__/EmptyStackState.integration.test.tsx` exists; 5/5 tests pass.
- ✅ `frontend/src/components/builder/__tests__/StackRow.test.tsx` exists; 23/23 tests pass.
- ✅ `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` exists; 19/19 tests pass.
- ✅ `frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx` exists; 31/31 tests pass.
- ✅ `frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts` exists; 4/4 tests pass; file-header documents the worker-exit root cause + mitigation as required by POL-20.
- ✅ `frontend/src/components/builder/hooks/__tests__/use-builder-layers.groups.test.ts` exists; 12/12 tests pass.
- ✅ Commits `88e00ac7`, `a6c6b409`, `5d41b804` exist in `git log --oneline`.
- ✅ Full builder sweep `npx vitest run src/components/builder/`: **Test Files 54 passed (54) / Tests 692 passed (692) / 0 worker errors / 0 unhandled errors** — POL-21 satisfied.
