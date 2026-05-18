---
phase: 1051-map-builder-polish-bug-sweep
fixed_at: 2026-05-18T14:50:00Z
review_path: .planning/phases/1051-map-builder-polish-bug-sweep/1051-REVIEW.md
iteration: 3
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 1051: Code Review Fix Report (Iteration 3)

**Fixed at:** 2026-05-18T14:50:00Z
**Source review:** .planning/phases/1051-map-builder-polish-bug-sweep/1051-REVIEW.md
**Iteration:** 3

**Summary:**
- Findings in scope: 4 (2 Warning + 2 Info from iter-2 re-review)
- Fixed: 4
- Skipped: 0

All 4 findings from the iter-2 adversarial sweep were fixed inline. Iter-2 re-review surfaced these as secondary effects of the iter-1 fixes; none were original review findings.

## Fixed Issues

### WR-01: heatmap-adapter syncPaint double-writes heatmap-opacity (transient flash)

**Files modified:** `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts`
**Commit:** `54ddd1ec`
**Applied fix:** Added `if (prop === 'heatmap-opacity') continue;` inside the generic `for…Object.entries(rawPaint)` loop in `syncPaint`, so the compounded write at the post-loop block (line ~107) is the single writer for `heatmap-opacity`. Eliminates the transient flash to full saturation visible on every master-opacity-driven sync (loop wrote raw 0.8, then post-loop overrode with compounded 0.4). Same defect class as CR-04, which fixed the add-time twin in iter-1. Added a phase-qualified inline comment per AGENTS.md convention.

### WR-02: CR-02 fix has no regression test in BasemapGroupRow.test.tsx

**Files modified:** `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx`
**Commit:** `ec2b8070`
**Applied fix:** Appended Test 4b and Test 4c after the existing row-click test:
- **Test 4b** — fires `click` on the row name with `isMultiSelectionActive: true`; asserts `onSelectGroup` was NOT called.
- **Test 4c** — fires `keyDown` with `Enter` and `Space` on `#stack-row-{groupId}` with `isMultiSelectionActive: true`; asserts `onSelectGroup` was NOT called.

Pins the CR-02 contract (silent-BulkActionBar-unmount prevention) at the test pyramid level so a future refactor that drops the `isMultiSelectionActive` guard re-introduces a test failure. 21/21 BasemapGroupRow vitest tests pass.

### IN-01: structuralKey overloaded — drives popup-clear AND auto-fit (developer hazard)

**Files modified:** `frontend/src/components/builder/BuilderMap.tsx`
**Commit:** `7b599dee`
**Applied fix:** Took Option B from REVIEW.md (lower-churn):

1. Renamed `structuralKey` → `popupInvalidationKey` to make the single consumer (popup-clear at `setPopupInfo(null)`) explicit.
2. Removed it from the auto-fit `useEffect` dep array; the effect short-circuits on `!layerCountChanged`, so `layers.length` (already in the array) is sufficient to detect add/remove.

Added a phase-qualified explanation block at the memo and a second block above the dep array. No external references to `structuralKey` exist in the codebase (verified with `grep -rn` across `frontend/src/`); only two historical doc-comment mentions remain (the rename block itself and an unrelated SP-03 / B-01-followup historical note). 976/976 builder vitest tests pass before and after.

### IN-02: CR-04 fix has no direct unit test (critical-tier behavior unprotected)

**Files modified:** `frontend/src/components/builder/layer-adapters/__tests__/heatmap-adapter.test.ts` (new file, 6 tests, 150 lines)
**Commit:** `97d16e89`
**Applied fix:** Created `frontend/src/components/builder/layer-adapters/__tests__/heatmap-adapter.test.ts` colocated with `shared.test.ts`. Six focused tests:

- **Test 1** — `addLayers` compounds `paint['heatmap-opacity']` × `opacity` (CR-04 contract).
- **Test 2** — falls back to 0.8 default when `rawPaint` omits the key.
- **Test 3** — master `opacity=1` preserves stored value unchanged.
- **Test 4** — regression guard: the formula must NOT equal `(opacity ?? 1) * 0.8` (the pre-CR-04 bug).
- **Test 5** — `syncPaint` writes `heatmap-opacity` **exactly once** per call (WR-01 single-writer contract), and that write is the compounded value, not the raw.
- **Test 6** — `syncPaint` still propagates non-opacity `heatmap-*` properties through the generic loop.

Tests use the same `vi.fn()`-based mock-map pattern as `shared.test.ts`. 6/6 vitest tests pass; full builder suite remains green at 982/982 (was 976 + 6 new).

---

## Verification

All 4 fixes verified via:
- **Tier 1** — re-read modified file sections post-edit to confirm fix text present and surrounding code intact.
- **Tier 2** — TypeScript syntax check via `ts.transpileModule` (OK — no syntax errors) on all modified `.ts`/`.tsx` files.
- **Vitest** — full builder test suite (`npx vitest run src/components/builder`) passes 982/982 after all fixes applied. New tests for WR-02 (2 tests) and IN-02 (6 tests) are green; existing tests show no regressions.

The two test-addition commits (WR-02, IN-02) supply the regression coverage the iter-2 reviewer specifically requested for the iter-1 fixes to CR-02 and CR-04 respectively. The single behavioral fix (WR-01) closes the sync-time twin of CR-04 — the same defect class that iter-1 fixed at add-time. The single refactor (IN-01) is a name-and-deps cleanup with no runtime behavior change.

No findings were skipped. No source files were left in a broken state. No partial or uncommitted changes remain.

---

_Fixed: 2026-05-18T14:50:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 3 (--auto fix loop)_
