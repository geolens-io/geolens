---
phase: 1039-ux-audit-and-test-debt-closeout
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/__tests__/EmptyStackState.integration.test.tsx
  - frontend/src/components/builder/__tests__/StackRow.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts
autonomous: true
requirements: [POL-19, POL-20, POL-21]
must_haves:
  truths:
    - "Developer runs `npx vitest run src/components/builder/` and sees 0 failures and 0 unhandled worker errors."
    - "EmptyStackState.integration Tests 2, 3, and 5 pass (they currently throw `Cannot read properties of undefined (reading 'name')` because `SUGGESTED_DATASETS` ships empty)."
    - "StackRow `clicking \"Delete layer\" in the kebab calls onRemove(layer.id)` passes (it currently fails with `expected vi.fn() to be called once, but got 0 times` because `Delete layer` now opens an inline alertdialog instead of removing immediately)."
    - "UnifiedStackPanel `calls onAddDataClick when ＋ Add data button is clicked` passes (it currently fails because `getByRole('button', { name: /Add data/i })` matches both the header `＋ Add data` button and the EmptyStackState stub's `Add dataset` button)."
    - "`use-builder-layers.add-dataset.test.ts` runs to completion without `Worker exited unexpectedly` / `Timeout terminating forks worker`; root cause is identified and noted in the test file's header comment for traceability."
    - "Tested behaviors are preserved: the test changes assert the same product contracts (BSR-17, BSR-18, BSR-12 delete-confirm flow, header add-data button wiring, handleAddDataset sort_order/onSuccess) but with corrected setup."
  artifacts:
    - path: "frontend/src/components/builder/__tests__/EmptyStackState.integration.test.tsx"
      provides: "Tests 2/3/5 pass via a vi.mock that injects a non-empty SUGGESTED_DATASETS fixture"
      contains: "vi.mock('@/components/builder/suggested-datasets'"
    - path: "frontend/src/components/builder/__tests__/StackRow.test.tsx"
      provides: "`Delete layer` test reflects the alertdialog-confirm flow (click Delete in confirm, not the menu item)"
      contains: "alertdialog"
    - path: "frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx"
      provides: "onAddDataClick test disambiguates the header button from the EmptyStackState stub button (rename stub button or scope query to header / use exact name match)"
      contains: "onAddDataClick"
    - path: "frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts"
      provides: "Test file runs without worker exit; header comment documents the root cause and the applied mitigation"
      contains: "Worker exit root cause"
  key_links:
    - from: "EmptyStackState.integration.test.tsx beforeEach"
      to: "@/components/builder/suggested-datasets module"
      via: "vi.mock factory that returns a populated SUGGESTED_DATASETS array"
      pattern: "vi\\.mock\\(['\"]@/components/builder/suggested-datasets"
    - from: "StackRow.test.tsx Delete layer test"
      to: "the inline alertdialog `Delete` button"
      via: "click `Delete layer` menuitem → query `role=alertdialog` → click `Delete` button"
      pattern: "alertdialog|confirmDelete"
    - from: "UnifiedStackPanel.test.tsx onAddDataClick test"
      to: "the header `＋ Add data` Button only"
      via: "either rename the stub button in `vi.mock('../EmptyStackState')` so it does not match `/Add data/i`, OR query for the exact `＋ Add data` text"
      pattern: "onAddDataClick"
---

<objective>
Close the 5 pre-existing builder vitest failures and the
`use-builder-layers.add-dataset.test.ts` worker-timeout regression so that
`npx vitest run src/components/builder/` reports 0 failures and 0 unhandled
worker errors. All failures are real regressions — not type drift — and each
root cause has been confirmed by re-running the failing tests:

1. **EmptyStackState integration Tests 2/3/5** — `SUGGESTED_DATASETS` ships
   empty by default (commit `4a5ee284`); tests reference `SUGGESTED_DATASETS[0]`
   and crash on `.name` access. Fix: `vi.mock` the module to inject a populated
   fixture.
2. **StackRow `Delete layer`** — The kebab `Delete layer` item no longer calls
   `onRemove` directly; it sets `confirmingDelete=true` to open an inline
   `<div role="alertdialog">` with `Delete` / `Keep layer` buttons. Fix: drive
   the test through the confirm step.
3. **UnifiedStackPanel `calls onAddDataClick`** — `getByRole('button', { name:
   /Add data/i })` matches both the header button (`＋ Add data`) and the
   EmptyStackState mock-stub's button (`Add dataset`). Fix: disambiguate.
4. **`use-builder-layers.add-dataset.test.ts` worker timeout** — The forks
   worker exits during teardown (V8 stack frames in the crash log point to
   microtask/promise GC). Confirmed regression on `8cab335e`. Investigate
   fixture cleanup / mock leak first per CONTEXT.md guidance; document the
   actual root cause and the applied mitigation in the test file header so
   POL-20's "documented in phase summary" criterion is satisfied.

Purpose: Unblock the v1009 milestone — POL-21 (`vitest run
src/components/builder/` green) is the milestone close-out gate. Without
this plan, every subsequent v1009 phase touching `EmptyStackState`,
`StackRow`, `UnifiedStackPanel`, or `use-builder-layers` cannot run a clean
vitest pass.

Output: Four test files modified; production code untouched (per CONTEXT.md
"test fixes must keep tests passing AND not change tested behaviour — these
are real regressions, not stale assertions" — corrected here: failures 1 and 3
are stale test setup; failure 2 is a stale assertion against shipped behaviour
change; failure 4 is a runtime environment issue).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/phases/1039-ux-audit-and-test-debt-closeout/1039-CONTEXT.md

# Test files being modified
@frontend/src/components/builder/__tests__/EmptyStackState.integration.test.tsx
@frontend/src/components/builder/__tests__/StackRow.test.tsx
@frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
@frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts

# Source files referenced for shipped behavior (DO NOT MODIFY)
@frontend/src/components/builder/EmptyStackState.tsx
@frontend/src/components/builder/StackRow.tsx
@frontend/src/components/builder/UnifiedStackPanel.tsx
@frontend/src/components/builder/suggested-datasets.ts
@frontend/src/components/builder/hooks/use-builder-layers.ts

<interfaces>
<!-- Key contracts the executor needs. Production code is the source of truth. -->

From `frontend/src/components/builder/suggested-datasets.ts`:
- `export interface SuggestedDataset { id: string; name: string; record_type: 'vector_dataset' | 'raster_dataset' | 'vrt_dataset'; geometry_type?: string; feature_count?: number; crs?: string }`
- `export const SUGGESTED_DATASETS: SuggestedDataset[] = []` — ships empty; tests must override via `vi.mock`.
- `SuggestCard` in `EmptyStackState.tsx` hides any card whose `id` is not a UUID v4 (regex `/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i`). The mock fixture's IDs MUST be valid UUIDs or the cards never render and the failing tests will still not find them.

From `frontend/src/components/builder/StackRow.tsx` (lines 317-389):
- Clicking the `Delete layer` `DropdownMenuItem` runs `setConfirmingDelete(true)`.
- That renders `<div role="alertdialog" aria-label="Are you sure? This cannot be undone." ...>` with two `<Button>`s: `Delete` (variant=destructive, calls `onRemove(layer.id)`) and `Keep layer` (variant=outline, dismisses).
- The aria-label text comes from i18n key `layerEditor.confirmDelete.message` with defaultValue `'Are you sure? This cannot be undone.'`; the `Delete` button text comes from `layerEditor.confirmDelete.delete` with defaultValue `'Delete'`.

From `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` lines 32-44 (the EmptyStackState mock):
- The mock stub renders a button labelled `Add dataset` (in addition to `Browse all datasets` and `Search`).
- The `Add dataset` label matches the regex `/Add data/i` (substring match), which collides with the header `＋ Add data` button rendered by `UnifiedStackPanel.tsx:681`.
- The empty-state stub button is only present when `layers=[]` (the no-layers branch). The failing `calls onAddDataClick` test uses `defaultProps({ onAddDataClick })` which defaults `layers: []` — so the empty-state mock IS in the DOM at the same time as the header button.

From `frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts`:
- 4 synchronous tests using `renderHook(() => useBuilderLayers(...))`.
- All 4 test bodies complete fast; worker exits during teardown.
- File already mocks `react-router`, `react-i18next`, `sonner`, `@/components/builder/hooks/use-ephemeral-layers`, `@/components/builder/hooks/use-layer-map-sync`, `@/components/builder/map-sync`, `@/components/builder/layer-adapters/registry`, `@/lib/basemap-utils`, `@/lib/tile-utils`, `@/components/builder/label-layer-utils`, `@/components/builder/renderAs`.
- V8 stack frames in the failure log: `PromiseFulfillReactionJob` → `MicrotaskQueue::RunMicrotasks` — consistent with a dangling promise or unclosed QueryClient in `renderHook` wrapper at teardown.

From `frontend/vite.config.ts` (`test` block):
- `environment: 'jsdom'`, no explicit `pool` setting (vitest defaults to `forks` in v4). No per-file `// @vitest-environment` overrides in the failing file.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix the three EmptyStackState.integration test failures + the StackRow Delete-layer test + the UnifiedStackPanel onAddDataClick test</name>
  <files>
    frontend/src/components/builder/__tests__/EmptyStackState.integration.test.tsx,
    frontend/src/components/builder/__tests__/StackRow.test.tsx,
    frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
  </files>
  <action>
Fix the 5 stale vitest failures by correcting test setup, not production behaviour. Each fix is local to the test file.

**1. `EmptyStackState.integration.test.tsx` — Tests 2/3/5 (3 failures)**

Root cause: `SUGGESTED_DATASETS` ships empty by default (per `suggested-datasets.ts` commit `4a5ee284`); tests dereference `SUGGESTED_DATASETS[0].name` and crash. The commit message says "Test fixture overrides the constant via vi.mock" — that override is missing.

Add a module-level `vi.mock('@/components/builder/suggested-datasets', ...)` to inject a populated fixture. Requirements for the fixture:
- IDs MUST be valid UUID v4 (8-4-4-4-12 hex) or `SuggestCard` will hide the cards via the `UUID_RE` gate at `EmptyStackState.tsx:46-59`. Use stable hand-written UUIDs (e.g., `'11111111-1111-4111-8111-111111111111'`).
- Export the same `SuggestedDataset` interface and a non-empty `SUGGESTED_DATASETS` array with at least one entry.
- The test already mocks `@/api/datasets` `getDataset` to resolve, so the `useQuery` will resolve and `isError=false` for every card.

Then verify Tests 2/3/5 pass without changing their assertion text. Test 1 and Test 4 (currently passing) MUST continue to pass — both reference DOM that exists regardless of whether suggestions render (the inline searchbox and "Browse all" button).

**2. `StackRow.test.tsx` — `clicking "Delete layer" in the kebab calls onRemove(layer.id)` (1 failure, lines 200-210)**

Root cause: The shipped `Delete layer` flow added an inline alertdialog confirmation (StackRow.tsx:317-389) — `Delete layer` menuitem now only sets `confirmingDelete=true`. `onRemove` is called by the alertdialog's destructive `Delete` button.

Update the test to drive through the confirm step:
1. Open kebab via `pointerDown` on the kebab trigger (unchanged).
2. `fireEvent.click(screen.getByRole('menuitem', { name: /Delete layer/i }))` — unchanged, opens the alertdialog.
3. Assert the alertdialog appeared: `expect(screen.getByRole('alertdialog')).toBeInTheDocument()`.
4. Click the destructive `Delete` button inside the alertdialog: `fireEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: /^Delete$/ }))`. Import `within` from `@/test/test-utils` (re-exported from `@testing-library/dom`).
5. Existing assertions on `onRemove` continue to hold (`toHaveBeenCalledOnce()`, `toHaveBeenCalledWith('delete-layer')`).

This preserves the tested behaviour (delete-confirm path BSR-12 → `onRemove` invocation) and aligns the test with the alertdialog that the kebab now opens.

**3. `UnifiedStackPanel.test.tsx` — `calls onAddDataClick when ＋ Add data button is clicked` (1 failure, lines 268-274)**

Root cause: The `EmptyStackState` mock stub at lines 32-44 renders a button with text `Add dataset`; the regex `/Add data/i` matches both that stub button AND the real header `＋ Add data` button. Test fails with `Found multiple elements with the role "button" and name /Add data/i`.

Two equally valid fixes — pick whichever keeps the file most readable:

Option A (preferred — minimal change): rename the empty-state stub button text to something that does not collide. Change line 41 of `UnifiedStackPanel.test.tsx` from `>Add dataset<` to `>+Add suggestion<` (or `>Pick suggestion<`). The stub is only used to verify wiring (`onAddDataset` is called), not text — so the rename is safe. Update lines that interact with that stub (the test does not actually click `Add dataset` anywhere else in this file — `grep` to confirm before changing).

Option B: scope the query — change line 272 to `fireEvent.click(screen.getByRole('button', { name: '＋ Add data' }))` (exact-match string, not regex). The header button's `aria-label` defaultValue is `'＋ Add data'` (from `UnifiedStackPanel.tsx:681` via the `unifiedStack.addData` translation key).

Choose Option A — it's a one-character rename of a fake stub label and avoids exact-text fragility against future i18n string tweaks.

**Verification**

Run each fixed file:
- `npx vitest run src/components/builder/__tests__/EmptyStackState.integration.test.tsx` — expect 5/5 pass.
- `npx vitest run src/components/builder/__tests__/StackRow.test.tsx` — expect all tests pass (currently 22 skipped + 1 fail; should be all pass).
- `npx vitest run src/components/builder/__tests__/UnifiedStackPanel.test.tsx` — expect all tests pass.

DO NOT modify any production code. If a test cannot be made to pass by editing the test alone, STOP and surface the conflict — that means the failure is a real source regression, not stale test setup, and the plan needs revision.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/EmptyStackState.integration.test.tsx src/components/builder/__tests__/StackRow.test.tsx src/components/builder/__tests__/UnifiedStackPanel.test.tsx --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>
All 5 previously-failing tests pass. No production code modified (`git diff --name-only frontend/src/components/builder/` shows only `__tests__/*.test.tsx` files). EmptyStackState Tests 1 and 4 (previously passing) still pass.
  </done>
</task>

<task type="auto">
  <name>Task 2: Fix the `use-builder-layers.add-dataset.test.ts` worker-timeout regression and document root cause</name>
  <files>frontend/src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts</files>
  <action>
Root-cause and fix the `Worker exited unexpectedly` / `Timeout terminating forks worker` regression in `use-builder-layers.add-dataset.test.ts`. POL-20 requires the root cause to be identified and documented; the test file header comment is the canonical location (so the next maintainer reading the file finds the explanation in-line).

**Investigation order (per CONTEXT.md `<specifics>` — "rule out test isolation issues (fixture cleanup, mock leak) before touching production code")**

Step 1 — Confirm the regression is the worker, not the test bodies:
- Re-run with `--reporter=verbose`: all 4 test bodies should run fast (the failure log shows them complete; the worker exits ~9-10s later during teardown). Confirms teardown-phase issue.

Step 2 — Isolate the heavy import. The file already mocks 11 modules. Two paths the mocks don't cover:
- `@tanstack/react-query` — `renderHook` from `@/test/test-utils` wraps with `QueryClientProvider`; the `QueryClient` may not be `.clear()`-ed at teardown, leaving the `gcTime` timer holding the worker alive.
- `useBuilderLayers` itself imports `useEphemeralLayers`, `useLayerMapSync`, `map-sync`, `layer-adapters/registry`, `basemap-utils`, `tile-utils`, `label-layer-utils`, `renderAs` (all mocked) PLUS direct imports of `@tanstack/react-query` and React state — none of these should be heavy after mocking.

Step 3 — Apply the lightest-touch mitigation that resolves the worker exit. Try in order, stopping at the first that fixes it:

**Mitigation A (try first): Add `afterEach` / `afterAll` teardown that clears `QueryClient` cache and resets all mocks.**
```ts
import { afterEach, afterAll } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();           // unmount any lingering renderHook results
  vi.clearAllMocks();  // reset spy state
});

afterAll(() => {
  vi.resetModules();   // drop module-graph references that may pin timers
});
```
The current file imports `act` and `renderHook` but does NOT call `cleanup()` between tests — `renderHook` returns are pinned across the 4 tests and only torn down at worker exit, which is exactly where the crash happens.

**Mitigation B (if A is insufficient): Force the test file to use `pool: 'threads'` or single-process via a per-file config directive.**
Add a top-of-file vitest directive: `// @vitest-environment jsdom` (already implicit) AND configure `pool` via a per-file override using `vi.hoisted` is not supported in v4; if pool override is needed, use `vitest.workspace.ts` — but PREFER mitigation A and document the workaround if B is needed.

**Mitigation C (last resort): Add an explicit `QueryClient` provider with `gcTime: 0` via a test wrapper in this file (override `@/test/test-utils`'s default).**
The `@/test/test-utils.tsx` `renderHook` wrapper likely instantiates a default `QueryClient` with a non-zero `gcTime`. Read that file before applying C and decide whether to override locally or fix the wrapper (DO NOT modify the wrapper — it's shared; override locally if needed).

**Documentation requirement (POL-20)**

After the fix lands, prepend a comment block to the file (replace the existing leading docstring or augment it) with:
```ts
/**
 * Focused tests for handleAddDataset — BSR-18
 * Tests: sort_order=0, onSuccessCb chain, error handling, backward-compat.
 *
 * Isolated in a separate file to keep the heavy renderHook call for
 * useBuilderLayers out of the main test suite. Heavy transitive deps are
 * mocked here at the module level so the hook can be imported in jsdom.
 *
 * ----------------------------------------------------------------------
 * Worker-exit root cause (POL-20, Phase 1039):
 *
 *   <2-4 sentences describing the actual root cause discovered during
 *    investigation — likely "renderHook results from the 4 tests were not
 *    cleaned up between tests; QueryClient gcTime/timers held the forks
 *    worker open past Vitest's teardown timeout, causing a SIGTERM that
 *    surfaced as `Worker exited unexpectedly`.">
 *
 *   Mitigation: <which of A/B/C was applied; why the alternatives were
 *    rejected if relevant>.
 * ----------------------------------------------------------------------
 */
```

The phase summary (written by execute-plan) will quote this comment block to satisfy the ROADMAP success criterion #3 "root cause is documented in the phase summary".

**Verification gate**

The fixed test MUST satisfy two conditions:
1. All 4 test bodies (Test A/B/C/D) still pass.
2. `npx vitest run src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts` exits 0 with no `Worker exited unexpectedly`, no `Timeout terminating forks worker`, and no `Unhandled Errors` block in the output.

DO NOT modify `frontend/src/components/builder/hooks/use-builder-layers.ts` (the production hook). If the worker-exit cannot be resolved by test-side mitigation, STOP and surface the constraint.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts --reporter=verbose 2>&1 | tail -25</automated>
  </verify>
  <done>
Test file passes 4/4 with no worker-exit error, no unhandled-error block. Root cause documented in file header comment with concrete description (not "investigation TBD"). Production code (`use-builder-layers.ts`) and shared test utilities (`src/test/test-utils.tsx`) are unmodified — only this single test file changes.
  </done>
</task>

<task type="auto">
  <name>Task 3: Full builder vitest sweep (POL-21 gate)</name>
  <files>(verification only — no files modified)</files>
  <action>
Run the full builder vitest suite to verify POL-21: `npx vitest run src/components/builder/` reports 0 failures and 0 unhandled worker errors.

Steps:
1. From `frontend/`, run `npx vitest run src/components/builder/ --reporter=verbose 2>&1 | tee /tmp/1039-vitest.log`.
2. Confirm the summary line shows `Tests N passed (N)` (no failures, no skipped from the previously-fixing files).
3. Confirm no `Unhandled Errors` block, no `Worker exited unexpectedly`, no `Timeout terminating forks worker`.
4. If any new failure appears that was NOT in the original 5+1 set documented in POL-19/POL-20 (e.g., a regression introduced by Task 1 or Task 2), STOP and fix it in this plan before declaring done — POL-21 is the milestone gate and must be green.

This task is the green-light gate for the phase summary's "all builder tests pass" claim. The phase summary should quote the final test count from `/tmp/1039-vitest.log` for traceability.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/ 2>&1 | tail -10 | grep -E "Tests +[0-9]+ passed" && cd frontend && npx vitest run src/components/builder/ 2>&1 | grep -E "Worker exited|Timeout terminating|Unhandled Error" | wc -l | tr -d ' ' | grep -q '^0$'</automated>
  </verify>
  <done>
`npx vitest run src/components/builder/` reports `Tests N passed (N)` with zero failures, zero unhandled errors, zero worker-exit messages. The output is captured in the phase summary for POL-21 traceability.
  </done>
</task>

</tasks>

<verification>
1. Run `cd frontend && npx vitest run src/components/builder/` — confirm 0 failures, 0 unhandled errors.
2. Run `cd frontend && git diff --name-only src/components/builder/` — confirm only test files modified (no production source).
3. Run `cd frontend && git diff src/components/builder/hooks/use-builder-layers.ts` — confirm empty (production hook untouched).
4. Open `src/components/builder/hooks/__tests__/use-builder-layers.add-dataset.test.ts` — confirm the header comment now contains a concrete "Worker-exit root cause" section describing what was found and what was changed.
</verification>

<success_criteria>
- POL-19 satisfied: 5 previously-failing builder vitest tests pass.
- POL-20 satisfied: `use-builder-layers.add-dataset.test.ts` runs to completion; root cause documented in the test file header (and quotable in the phase summary).
- POL-21 satisfied: `npx vitest run src/components/builder/` is fully green at phase close.
- No production code modified — only test files.
- Test changes preserve the original product contracts (BSR-17, BSR-18, BSR-12 delete-confirm, header add-data wiring, handleAddDataset sort_order/onSuccess) — the tests still verify the same behaviour, just with corrected setup.
</success_criteria>

<output>
After completion, create `.planning/phases/1039-ux-audit-and-test-debt-closeout/1039-01-SUMMARY.md` containing:
- A `**Worker-exit root cause:**` section quoting the exact 2-4 sentences from the `use-builder-layers.add-dataset.test.ts` header comment (POL-20 requires this to surface in the phase summary).
- The pass/fail count from the final `npx vitest run src/components/builder/` run (POL-21 evidence).
- A bulleted "Tests changed" list naming each test by `describe > it` path and a one-line description of the fix.
- A "Production code unchanged" assertion linking to `git diff --name-only` output.
</output>
