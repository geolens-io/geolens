---
phase: 1047-perf-and-code-quality-fixes
plan: 05
subsystem: builder/style-editor
tags: [cb-07, cd-19, code-02, code-05, refactor, split]

requires:
  - phase: 1047-03
    provides: opacity debounce wiring (preserved at orchestrator level)

provides:
  - LayerStyleEditor/FillEditor.tsx — fill-mode appearance controls
  - LayerStyleEditor/LineEditor.tsx — line-mode appearance controls
  - LayerStyleEditor/CircleEditor.tsx — circle-mode appearance controls
  - LayerStyleEditor/SymbolEditor.tsx — symbol render mode controls
  - LayerStyleEditor/HeatmapEditor.tsx — heatmap render mode (thin wrapper over HeatmapStyleControls)
  - LayerStyleEditor/ClusterEditor.tsx — cluster render mode controls
  - LayerStyleEditor/RasterEditor.tsx — raster layer placeholder
  - LayerStyleEditor/RenderModeSwitch.tsx — lookup-table dispatch (CD-19 fix)
  - LayerStyleEditor/AdvancedJsonEditor.tsx — advanced JSON panel (extracted)
  - LayerStyleEditor/StrokeControls.tsx — shared stroke toggle+controls
  - LayerStyleEditor/types.ts — BaseStyleEditorProps shared interface
  - LayerStyleEditor/utils.ts — shared constants, helpers, hasUnsavedStyleChanges
  - LayerStyleEditor/index.ts — barrel re-export

affects:
  - 1047-06 (closeout phase — final e2e gate)

tech-stack:
  added: []
  patterns:
    - "RenderModeSwitch lookup table: editorComponents[dispatchKey] replaces nested ternaries"
    - "dispatchKey = geomType (fill/line/circle) + renderMode (heatmap/symbol/cluster) for sub-dispatch"
    - "BaseStyleEditorProps: uniform prop interface passed through RenderModeSwitch to all editors"
    - "Utility extraction to LayerStyleEditor/utils.ts: shared constants + fns usable by both orchestrator and sub-components"

key-files:
  created:
    - frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/CircleEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/SymbolEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/HeatmapEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/ClusterEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx
    - frontend/src/components/builder/LayerStyleEditor/AdvancedJsonEditor.tsx
    - frontend/src/components/builder/LayerStyleEditor/StrokeControls.tsx
    - frontend/src/components/builder/LayerStyleEditor/types.ts
    - frontend/src/components/builder/LayerStyleEditor/utils.ts
    - frontend/src/components/builder/LayerStyleEditor/index.ts
    - frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx
    - frontend/src/components/builder/LayerStyleEditor/__tests__/LineEditor.test.tsx
    - frontend/src/components/builder/LayerStyleEditor/__tests__/CircleEditor.test.tsx
    - frontend/src/components/builder/LayerStyleEditor/__tests__/RenderModeSwitch.test.tsx
  modified:
    - frontend/src/components/builder/LayerStyleEditor.tsx (1231 → 468 LOC)
    - frontend/src/components/builder/LayerStyleEditor/utils.ts (expanded with utility fns)

key-decisions:
  - "dispatchKey semantics: geomType (fill/line/circle) provides the top-level dispatch. For circle/point layers, renderMode (heatmap/symbol/cluster) overrides to heatmap/symbol/cluster. Non-circle non-fill non-line → raster."
  - "hasUnsavedStyleChanges moved to utils.ts, re-exported from LayerStyleEditor.tsx. Public import surface unchanged — test callers import from '../LayerStyleEditor' as before."
  - "AdvancedJsonEditor extracted to LayerStyleEditor/AdvancedJsonEditor.tsx (148 LOC). This was the largest non-sub-component block (130+ LOC). Essential to hit the ≤500 LOC target."
  - "Shared helpers in utils.ts: FILL_DEFAULTS, LINE_DEFAULTS, CIRCLE_DEFAULTS, getPaintValue, getEditableNumericPaintValue, compactBuilder, withBuilderConfig, stylePreviewStyle, hasUnsupportedBuilderState. Both orchestrator and sub-components import from this single source."
  - "Section title/description adapts by dispatchKey: heatmap/symbol/cluster modes retain their own section title (style.sections.heatmap etc.) so existing tests stay green without modification."
  - "ClusterEditor created as a 7th sub-component (not in original plan spec) because cluster is a distinct point render mode alongside heatmap and symbol."

requirements-completed: [CODE-02, CODE-05]

duration: ~45 minutes
completed: "2026-05-16"
tasks_completed: 3
tasks_total: 3
files_changed: 18
---

# Phase 1047 Plan 05: LayerStyleEditor Split (CB-07 + CD-19) Summary

**LayerStyleEditor.tsx split from 1231 LOC to 468 LOC (62% reduction) via per-render-mode sub-components and RenderModeSwitch lookup-table dispatch. CB-07 (P0 file-size) and CD-19 (P1 nested ternaries) both closed.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-05-16
- **Tasks:** 3 of 3
- **Files changed:** 18

## Accomplishments

### Before / After LOC

| File | Before | After |
|------|--------|-------|
| `LayerStyleEditor.tsx` | 1231 | 468 |

### New Sub-Components (LOC each)

| File | LOC | Role |
|------|-----|------|
| `FillEditor.tsx` | 96 | Polygon/fill mode appearance controls |
| `LineEditor.tsx` | 125 | Line/polyline mode controls (includes gradient toggle, arrow config, dash presets) |
| `CircleEditor.tsx` | 60 | Circle/point mode (default points render) |
| `SymbolEditor.tsx` | 129 | Symbol render mode (icon picker, category mapping) |
| `HeatmapEditor.tsx` | 22 | Heatmap render mode (thin wrapper over HeatmapStyleControls) |
| `ClusterEditor.tsx` | 59 | Cluster render mode (radius, zoom, colors) |
| `RasterEditor.tsx` | 17 | Raster layer placeholder |
| `RenderModeSwitch.tsx` | 59 | Lookup-table dispatch (CD-19 fix) |
| `AdvancedJsonEditor.tsx` | 148 | Advanced JSON editor (extracted from orchestrator) |
| `StrokeControls.tsx` | 60 | Shared stroke toggle + color + width |
| `types.ts` | 47 | BaseStyleEditorProps interface |
| `utils.ts` | 113 | Shared constants, helpers, hasUnsavedStyleChanges, deepEqual |
| `index.ts` | 12 | Barrel re-export |

All sub-components ≤ 300 LOC (FillEditor budget met).

### CD-19 Fix: RenderModeSwitch lookup table

The 200+ LOC nested-ternary block in the old orchestrator is replaced with:
```ts
const editorComponents: Record<EditorDispatchKey, React.ComponentType<BaseStyleEditorProps>> = {
  fill: FillEditor,
  line: LineEditor,
  circle: CircleEditor,
  heatmap: HeatmapEditor,
  symbol: SymbolEditor,
  cluster: ClusterEditor,
  raster: RasterEditor,
};
const Editor = editorComponents[dispatchKey];
return Editor ? <Editor {...rest} /> : null;
```

### Public Import Surface

`LayerEditorPanel.tsx` import unchanged:
```ts
import { LayerStyleEditor } from './LayerStyleEditor';
```
TypeScript module resolution prefers `LayerStyleEditor.tsx` over `LayerStyleEditor/index.ts` — no caller updates needed. The barrel at `LayerStyleEditor/index.ts` exists for discoverability only.

`hasUnsavedStyleChanges` is re-exported from `LayerStyleEditor.tsx`:
```ts
export { hasUnsavedStyleChanges } from './LayerStyleEditor/utils';
```
Test imports continue to resolve without modification.

### Plan 03 Opacity Debounce Preserved

The 100ms debounced opacity slider (PB-02) remains at the orchestrator level:
- `localOpacity` state + `opacityFromPropRef` guard — unchanged
- `setLocalOpacity` passed to master SliderRow — unchanged
- `useEffect` debounce with 100ms timeout — unchanged

## Shared Helpers Location Decision

`utils.ts` (in `LayerStyleEditor/` directory): FILL_DEFAULTS, LINE_DEFAULTS, CIRCLE_DEFAULTS, getPaintValue, getEditableNumericPaintValue, compactBuilder, withBuilderConfig, stylePreviewStyle, hasUnsupportedBuilderState, hasUnsavedStyleChanges, deepEqual.

Sub-components import utilities from `../utils` (relative to their directory). The orchestrator imports from `./LayerStyleEditor/utils`.

AdvancedJsonEditor was too large (130+ LOC) for utils.ts — it's a UI component that got its own file.

## New Tests

| File | Tests | Status |
|------|-------|--------|
| `__tests__/FillEditor.test.tsx` | 8 | PASS |
| `__tests__/LineEditor.test.tsx` | 7 | PASS |
| `__tests__/CircleEditor.test.tsx` | 6 | PASS |
| `__tests__/RenderModeSwitch.test.tsx` | 8 | PASS |

## Verification Results

| Check | Result |
|-------|--------|
| TypeScript typecheck (tsc -b --noEmit) | CLEAN (4 pre-existing errors in unrelated test files) |
| LayerStyleEditor.tsx LOC | 468 (≤ 500 ✓) |
| LayerStyleEditor.test.tsx (51 tests) | 51/51 PASS |
| LayerEditorPanel.test.tsx (35 tests) | 35/35 PASS |
| New sub-component tests (29 tests) | 29/29 PASS |
| Builder suite wall-clock | 4.95s (≤ 10.5s PERF-06 ✓) |
| Full vitest suite | 1868/1868 PASS |

## Task Commits

| Task | Name | Commit | Type |
|------|------|--------|------|
| 1 | Carve per-render-mode editors | `380069c3` | feat |
| 2 | RenderModeSwitch lookup-table (CD-19) | `5efc7017` | feat |
| 3 | Reduce orchestrator to ≤500 LOC + barrel | `c888af93` | feat |

## Deviations from Plan

### Auto-added Functionality

**1. [Rule 2] ClusterEditor added as 7th sub-component**
- **Found during:** Task 1
- **Reason:** Cluster is a distinct point render mode (alongside heatmap and symbol). The plan listed 6 sub-components but the orchestrator had 4 point-mode branches. Creating ClusterEditor maintains structural consistency.
- **Impact:** Positive — cleaner RenderModeSwitch dispatch with all 7 modes in the lookup table.

**2. [Rule 2] StrokeControls extracted to shared file**
- **Found during:** Task 1
- **Reason:** Both FillEditor and CircleEditor use stroke controls. Extracting to `StrokeControls.tsx` avoids duplication.
- **Impact:** 60 LOC shared instead of duplicated.

**3. [Rule 1] Test mock `t()` function missing LineGradientControls i18n keys**
- **Found during:** Task 1 (test runs)
- **Issue:** LineEditor test t() mock lacked `style.lineGradient.*` keys so LineGradientControls rendered untranslated text, making button queries fail.
- **Fix:** Added `style.lineGradient.solid`, `style.lineGradient.gradient`, `style.lineGradient.advanced` keys to the test t() mock.

**4. [Rule 1] Section title mismatch for heatmap/symbol/cluster modes**
- **Found during:** Task 3 (existing test regression)
- **Issue:** The test `shows cluster authoring controls...` expected "Cluster appearance" section title. The new orchestrator initially used the generic "Appearance" title for all modes.
- **Fix:** Section title/description computed dynamically by dispatchKey in the orchestrator. CD-19 fix is pure (lookup table in RenderModeSwitch) — the section title adaptation is in the orchestrator JSX only.

## Known Stubs

- `RasterEditor.tsx`: Returns a placeholder text `t('style.rasterControls')`. Raster layers currently have no per-property controls in the builder (opacity is at orchestrator level). A `// TODO(1047-05): further split` comment is in the file.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes. This is a pure frontend refactor (component extraction + file splitting). The only threat boundary (public import surface) is verified by the existing test suite passing unchanged.

## Self-Check: PASSED
