---
phase: 1052
plan: "06"
subsystem: builder
tags: [builder, regression-pin, sublayer-config-indicators, defense-in-depth, emrg-fn-04]
dependency_graph:
  requires: ["1052-05"]
  provides: [EMRG-FN-04-closure]
  affects: []
tech_stack:
  added: []
  patterns: ["grep-then-WHY comment co-location", "EMRG closure explicit documentation"]
key_files:
  modified:
    - frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx
decisions:
  - "EMRG-FN-04 is NOT auto-resolved by Plan 01 (Path A REMOVE) — the layer={null} callsite lives in UnifiedStackPanel.tsx (basemap sublayer row), not in BasemapSublayerEditorScene. CONTEXT.md auto-resolution claim was wrong."
  - "Closure is documentation-shaped only: no production code change needed. The existing Test 1 is the canonical regression pin; we just made its EMRG-FN-04 association explicit."
metrics:
  duration: "5m"
  completed: "2026-05-18"
  tasks_completed: 3
  files_changed: 1
requirements: [EMRG-FN-04]
commit_message: "docs(1052): EMRG-FN-04 — document SublayerConfigIndicators null-branch closure"
---

# Phase 1052 Plan 06: EMRG-FN-04 SublayerConfigIndicators Null-Branch Closure Summary

**One-liner:** Explicit EMRG-FN-04 closure by documenting the intentional `layer={null}` contract in the canonical regression-pin test, with live callsite citation.

## What Was Done

### Task 1: Baseline Verification
- Confirmed `<SublayerConfigIndicators layer={null} />` callsite at `UnifiedStackPanel.tsx:556` is still live and unchanged.
- Confirmed comment block at lines 548-554 documents the intentional-null contract (BasemapSublayerInfo carries id/name/visible/opacity/kind only — not the full `MapLayerResponse`).
- Baseline vitest run: **8/8 tests pass**.
- Test 1 ("renders nothing when layer is null") confirmed at lines 42-46.

### Task 2: Test Docstring Extension
Two surgical edits to `SublayerConfigIndicators.test.tsx`:

**(A) Describe-block header comment** (added immediately before Test 1):
- Cites EMRG-FN-04 as the closure rationale.
- Names `UnifiedStackPanel.tsx:556` as the live consumer of the null branch.
- Explains WHY the null is intentional (BasemapSublayerInfo type constraint, UI-SPEC §UX-02 footnote, deferred enhancement once basemap sublayers gain user-editable filter/label).
- Establishes the regression-pin contract: future PRs must either pass Test 1 or explicitly delete it with documented rationale.

**(B) Inline comment inside Test 1 body**:
- Ties the test directly to EMRG-FN-04.
- States the exact null contract: "render nothing — container.firstChild === null."

Post-edit vitest: **8/8 tests pass** (comments only; zero behavioral change).
TypeScript check: **0 errors**.

### Task 3: Atomic Commit
Commit `06fbe98f` on main — 1 file touched (`SublayerConfigIndicators.test.tsx`, +20 lines).

## CONTEXT.md Auto-Resolution Correction

The original CONTEXT.md `<decisions>` block claimed EMRG-FN-04 was "auto-resolved by EMRG-FN-01 Path A — no callsite passes `layer={null}` to SublayerConfigIndicators anymore." **This was wrong.**

- The `layer={null}` callsite is at `UnifiedStackPanel.tsx:556` (basemap sublayer row rendering).
- Plan 01 targeted `BasemapSublayerEditorScene` — a different file/surface.
- The callsite at `UnifiedStackPanel.tsx:556` was never touched by Plan 01.
- The null branch remains live and intentional.

## Live Callsite Confirmed

```
frontend/src/components/builder/UnifiedStackPanel.tsx:556
  <SublayerConfigIndicators layer={null} />
```

Surrounding comment (lines 548-554) documents the intentional-null contract in the production source — this plan adds the mirrored documentation on the test side.

## Test Before / After

**Before (lines 42-46):**
```ts
describe('SublayerConfigIndicators', () => {
  it('renders nothing when layer is null', () => {
    const { container } = render(<SublayerConfigIndicators layer={null} />);
    expect(container.firstChild).toBeNull();
  });
```

**After (describe block header + Test 1 inline comment added):**
```ts
describe('SublayerConfigIndicators', () => {
  // Phase 1052 Plan 06 (EMRG-FN-04): the `layer={null}` branch closure.
  //
  // The live consumer is UnifiedStackPanel.tsx (around line 556) — the
  // basemap sublayer row passes `layer={null}` because BasemapSublayerInfo
  // only carries id/name/visible/opacity/kind, not the full MapLayerResponse
  // that SublayerConfigIndicators reads from. Per UI-SPEC §UX-02 footnote,
  // the indicator strip renders empty for basemap sublayers in this build
  // (acceptable — opacity-only diffs surface via the LayerEditorPanel
  // flyout). Plumbing the full layer through is a deferred enhancement
  // once basemap sublayers gain user-editable filter / label.
  //
  // Test 1 below is the canonical regression pin for the null branch. Any
  // future PR that changes SublayerConfigIndicators' null handling must
  // pass this test, OR explicitly delete it with a documented rationale
  // (e.g. "basemap sublayers now carry full MapLayerResponse — null branch
  // no longer reachable").

  it('renders nothing when layer is null', () => {
    // EMRG-FN-04 closure: the live caller is UnifiedStackPanel.tsx (basemap
    // sublayer row). The null contract is "render nothing" (no badges, no
    // wrapper div, no debug text) — container.firstChild === null.
    const { container } = render(<SublayerConfigIndicators layer={null} />);
    expect(container.firstChild).toBeNull();
  });
```

## Vitest Results

| Run | Tests | Result |
|-----|-------|--------|
| Baseline (pre-edit) | 8/8 | PASS |
| Post-edit | 8/8 | PASS |

## Deviations from Plan

None. Plan executed exactly as written. The CONTEXT.md auto-resolution correction was already documented in the plan's `<objective>` block — the planner had already identified the error before this plan was run.

## Self-Check: PASSED

- FOUND: `frontend/src/components/builder/__tests__/SublayerConfigIndicators.test.tsx`
- FOUND: commit `06fbe98f` in git log
- EMRG-FN-04 appears 2× in the test file (header comment + inline comment)
