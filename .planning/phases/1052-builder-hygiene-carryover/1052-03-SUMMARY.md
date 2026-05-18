---
phase: 1052
plan: 03
subsystem: builder
tags: [builder, dead-code-removal, basemap-sublayer, vitest, regression-pin, path-a-remove, emrg-fn-01]
dependency_graph:
  requires: [EMRG-FN-01-surface-deleted, EMRG-FN-01-i18n-cleaned]
  provides: [EMRG-FN-01-complete]
  affects: [BasemapSublayerEditorScene]
tech_stack:
  added: []
  patterns: [removed-feature-regression-pin, positive-form-queryby]
key_files:
  modified:
    - frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx
decisions:
  - "vi.mock('../StyleColorPicker') block left in place — orphaned but harmless; removing it is out of scope for this plan"
  - "Test count after Plan 03: 7 (Tests 8-14) — net -3 deleted + 1 added vs pre-Plan 03 count of 9"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-18T17:40:12Z"
  tasks_completed: 3
  files_changed: 1
---

# Phase 1052 Plan 03: EMRG-FN-01 Path A REMOVE — vitest cleanup + Test 14 regression pin

**One-liner:** Trimmed BasemapSublayerEditorScene.test.tsx to match Plan 01's props interface deletion; removed Tests 5-7 (STROKE surfaces) + zoom assertions from Test 8; added Test 14 EMRG-FN-01 REMOVE-disposition regression pin mirroring v1011 INV-01 Test 13 pattern.

## What Shipped

Single-file test cleanup aligned with the production surface deletion in Plan 01.

### defaultProps() — Before / After

**Before (11-field helper):**
```ts
function defaultProps(overrides = {}) {
  return {
    sublayerId: 'roads',
    sublayerName: 'Roads',
    strokeColor: '#FF0000',
    strokeWidth: 2,
    casingColor: '#000000',
    casingWidth: 1,
    opacity: 1,
    minZoom: 0,
    maxZoom: 22,
    onStrokeColorChange: vi.fn(),
    onStrokeWidthChange: vi.fn(),
    onCasingColorChange: vi.fn(),
    onCasingWidthChange: vi.fn(),
    onOpacityChange: vi.fn(),
    onZoomChange: vi.fn(),
    onResetSublayer: vi.fn(),
    ...overrides,
  };
}
```

**After (5-field helper — matches Plan 01 surviving props interface):**
```ts
function defaultProps(overrides = {}) {
  return {
    sublayerId: 'roads',
    sublayerName: 'Roads',
    opacity: 1,
    onOpacityChange: vi.fn(),
    onResetSublayer: vi.fn(),
    ...overrides,
  };
}
```

### Tests Deleted vs Preserved

| Test | Action | Reason |
|------|--------|--------|
| Test 5: STROKE section renders 4 fields | DELETED | STROKE section removed in Plan 01 |
| Test 6: color pickers + sliders count | DELETED | Color pickers belonged to STROKE |
| Test 7: width slider → onStrokeWidthChange | DELETED | Slider + callback both removed in Plan 01 |
| Test 8: VISIBILITY opacity slider + zoom inputs | RESTRUCTURED | Kept opacity slider; deleted zoom input assertions (inputs removed in Plan 01); renamed "Test 8: VISIBILITY section renders opacity slider" |
| Test 9: RESET section collapsed by default | UNTOUCHED | Live surface |
| Test 10: Reset alertdialog | UNTOUCHED | Live surface |
| Test 11: Reset / Keep customization | UNTOUCHED | Live surface |
| Test 12: BasemapSublayerEditorFooter | UNTOUCHED | Live surface |
| Test 13: DETAIL LEVEL REMOVE pin (v1011 INV-01) | UNTOUCHED | Canonical pin — must not change |
| Test 14: STROKE/zoom REMOVE pin (EMRG-FN-01) | ADDED | New regression guard |

### Test 14 — Full Text

```ts
it('Test 14: STROKE section + zoom range inputs are removed (Phase 1052 EMRG-FN-01 REMOVE disposition pin)', () => {
  // Regression guard for the REMOVE disposition shipped in Phase 1052 Plan 01:
  // the dead-stub STROKE section (color/width/casing color/casing width
  // controls) and VISIBILITY zoom range inputs (min/max) must not be
  // reintroduced without real consumers for sublayer style mutation. If
  // a future feature needs these surfaces, it should re-add the props +
  // JSX AND wire real onStrokeColorChange / onZoomChange handlers that
  // mutate MapLibre style at the same time — this test exists to make
  // that intent explicit at the call site.
  render(<BasemapSublayerEditorScene {...defaultProps({ sublayerName: 'Roads' })} />);

  expect(screen.queryByText(/^STROKE$/)).not.toBeInTheDocument();
  expect(screen.queryByText(/^Stroke color$/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/^Casing color$/i)).not.toBeInTheDocument();
  expect(screen.queryByRole('spinbutton', { name: /Minimum zoom/i })).not.toBeInTheDocument();
  expect(screen.queryByRole('spinbutton', { name: /Maximum zoom/i })).not.toBeInTheDocument();
});
```

### Header Comment Block — Extended

The describe-block header comment now has two paragraphs:
1. INV-01 paragraph (existing — unchanged)
2. EMRG-FN-01 paragraph (new): "Phase 1052 Plan 03 (EMRG-FN-01): STROKE section + zoom range inputs removed — Tests 5-7 ... and the zoom-input assertions in Test 8 deleted alongside their production surface. Test 14 below is the EMRG-FN-01 REMOVE-disposition regression pin."

### Vitest Pass Counts

| Scope | Before Plan 03 | After Plan 03 | Delta |
|-------|---------------|---------------|-------|
| BasemapSublayerEditorScene.test.tsx | Would fail (stale props) | 7/7 PASS | +1 net (3 deleted, 1 added) |
| src/components/builder/__tests__/ | — | 774/774 PASS | 0 regression |
| Full vitest suite | 1981 baseline | 1979/1979 PASS | -2 (net of -3 deleted +1 added, adjusted for baseline differences) |

## Commit

| Hash | Subject | Files | Stat |
|------|---------|-------|------|
| `e8748d9b` | `test(1052): EMRG-FN-01 Path A REMOVE — vitest cleanup + Test 14 regression pin` | 1 | +27/−60 |

## Deviations from Plan

### Deviation 1 — vi.mock('../StyleColorPicker') block not removed

**Plan stated:** "Sanity-check the imports — the `fireEvent` import may now be unused ... Similarly check `screen` (still used), `render` (still used)."

**Actual:** `fireEvent` is still used by Tests 10, 11, 12. `screen` and `render` are used throughout. The `vi.mock('../StyleColorPicker', ...)` block is now orphaned (the production component no longer imports `StyleColorPicker`), but removing it is not called for by the plan's acceptance criteria and would add scope. Leaving the orphaned mock in place is harmless — vitest silently skips mocks for unimported modules without error or warning.

**Assessment:** Out-of-scope micro-cleanup. Logged here for completeness. No correctness impact.

## Threat Surface Scan

Test-only change. No new endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED

- [x] `frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx` modified
- [x] Commit `e8748d9b` exists on main
- [x] defaultProps() has exactly 5 fields (sublayerId, sublayerName, opacity, onOpacityChange, onResetSublayer)
- [x] Tests 5, 6, 7 deleted
- [x] Test 8 restructured — opacity slider only, zoom assertions gone
- [x] Tests 9, 10, 11, 12, 13 untouched
- [x] Test 14 added with 5 positive-form queryBy* assertions + inline rationale
- [x] Header comment block has 2 paragraphs (INV-01 + EMRG-FN-01)
- [x] npx vitest run (file): 7/7 PASS
- [x] npx vitest run (builder __tests__/): 774/774 PASS
- [x] Full vitest suite: 1979/1979 PASS
- [x] Commit touches exactly 1 file
