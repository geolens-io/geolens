---
phase: "1150"
plan: "01"
subsystem: frontend/builder
tags: [polish, ui-cleanup, point-layers]
requires: []
provides: [POLISH-01]
affects: [LayerStyleEditor, LayerEditorPanel]
tech_stack:
  added: []
  patterns: []
key_files:
  created: []
  modified:
    - frontend/src/components/builder/LayerStyleEditor.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
decisions:
  - "Remove onRenderModeChange prop entirely from LayerStyleEditorProps (was only used by now-removed dropdown)"
  - "Inline PointRenderMode as a literal union type on renderMode variable rather than a named type"
  - "Update existing tests to remove stale prop and fix stale combobox index"
metrics:
  duration: "8 minutes"
  completed: "2026-05-29"
  tasks_completed: 2
  files_changed: 3
---

# Phase 1150 Plan 01: POLISH-01 Remove Redundant Point Render-As Dropdown Summary

Removed the duplicate "Render as" combobox from `LayerStyleEditor.tsx` (gated `geomType === 'circle'`) that was creating a second "Render as" section on the point Style tab alongside the canonical segmented pill row in `LayerEditorPanel.tsx`.

## Tasks Completed

### Task 1: Remove redundant dropdown from LayerStyleEditor + clean up prop/imports

**Commit:** `f9257606`

Changes:
- Deleted JSX block (lines 366-384): `{geomType === 'circle' && (<StyleControlSection>...<Select>...</Select></StyleControlSection>)}`
- Removed `PointRenderMode` local type; inlined as `'points' | 'heatmap' | 'symbol' | 'cluster'` literal union
- Removed `onRenderModeChange` from `LayerStyleEditorProps` interface
- Removed `onRenderModeChange` from function destructuring
- Removed `onRenderModeChange` from `editorProps` useMemo object and deps array
- Removed `Select/SelectContent/SelectItem/SelectTrigger/SelectValue` imports from line 5
- Removed `onRenderModeChange` pass-through adapter from `LayerEditorPanel.tsx` (lines 509-514)
- `renderMode` variable retained — still used at data-driven visibility gate

### Task 2: Regression test — point editor renders exactly one render-as control

**Commit:** (same `f9257606` — combined with Task 1)

Test updates:
- Removed all 35+ `onRenderModeChange={vi.fn()}` prop calls from existing tests (prop no longer exists)
- Deleted obsolete test "offers cluster as a render mode for eligible point layers" (tested the removed combobox)
- Updated "renders 'Render as' dropdown for point layers" → asserts heading is ABSENT (POLISH-01 inversion)
- Fixed heatmap weight test: `screen.getAllByRole('combobox')[1]` → `[0]` (render-as combobox gone, weight is now first)
- Fixed symbol controls test: "Symbols" text (was a Select option) → "Symbol appearance" (section heading)
- Added `describe('LayerStyleEditor — POLISH-01 single render-as control')` with 2 tests

## Verification

```
npm run typecheck → exit 0 (0 errors)
npm run test -- --run src/components/builder/__tests__/LayerStyleEditor.test.tsx
Test Files  1 passed (1)
      Tests  52 passed (52)
```

## Deviations from Plan

**None functional.** One structural deviation:
- [Rule 1 - Bug] Fixed 5 pre-existing tests that were relying on the removed dropdown (combobox index, "Symbols" text, render-as heading assertion). These were not regressions — they broke because the dropdown they tested was removed. Fixed inline per POLISH-01 scope.

## Self-Check: PASSED
- `git grep 'onRenderModeChange' frontend/src/components/builder/LayerStyleEditor.tsx` → 0 lines
- `git grep 'Select' frontend/src/components/builder/LayerStyleEditor.tsx | grep import` → 0 lines
- All 52 tests pass
- Typecheck exit 0
