---
phase: 1047-perf-and-code-quality-fixes
plan: 05
type: execute
wave: 5
depends_on: [1047-03]
files_modified:
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/index.ts
  - frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/CircleEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/SymbolEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/HeatmapEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/LineEditor.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/CircleEditor.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/RenderModeSwitch.test.tsx
autonomous: true
requirements: [CODE-02, CODE-05]
must_haves:
  truths:
    - "LayerStyleEditor.tsx drops from 1204 LOC to ≤ 500 LOC (file-size threshold met for CODE-05)"
    - "Public import surface preserved: `import { LayerStyleEditor } from '@/components/builder/LayerStyleEditor'` continues to resolve to the same component with the same props (CODE-06)"
    - "Per-render-mode sub-components (FillEditor, LineEditor, CircleEditor, SymbolEditor, RasterEditor, HeatmapEditor) live under `frontend/src/components/builder/LayerStyleEditor/` directory"
    - "Nested render-mode ternaries (CD-19) are replaced by a `RenderModeSwitch` component using a lookup object, not nested ternaries"
    - "Existing LayerStyleEditor.test.tsx continues to pass against the refactored composition; new per-sub-component tests cover FillEditor, LineEditor, CircleEditor in isolation"
    - "Vitest builder suite stays ≤ 10.5s (PERF-06 budget); typecheck clean"
  artifacts:
    - path: "frontend/src/components/builder/LayerStyleEditor/index.ts"
      provides: "Barrel re-export"
      contains: "export { LayerStyleEditor }"
    - path: "frontend/src/components/builder/LayerStyleEditor.tsx"
      provides: "Orchestrator (top-level component) — delegates to per-mode sub-components via RenderModeSwitch"
      max_lines: 500
    - path: "frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx"
      provides: "Lookup-table dispatch instead of nested ternaries"
  key_links:
    - from: "frontend/src/components/builder/LayerStyleEditor.tsx"
      to: "FillEditor, LineEditor, CircleEditor, SymbolEditor, RasterEditor, HeatmapEditor"
      via: "RenderModeSwitch dispatch by renderMode key"
      pattern: "RenderModeSwitch"
    - from: "Existing callers (LayerEditorPanel.tsx)"
      to: "`@/components/builder/LayerStyleEditor`"
      via: "Unchanged import — barrel resolves to the same export"
      pattern: "from '@/components/builder/LayerStyleEditor'"
---

<objective>
Split the 1204 LOC LayerStyleEditor.tsx into a thin orchestrator + per-render-mode sub-components, eliminating the nested-ternary CD-19 finding (200+ LOC of nested ternaries for render-mode UI) and dropping the file below the milestone-defined LOC threshold for CODE-05.

Purpose: LayerStyleEditor is the single largest file in the builder surface (CB-07 P0). It mixes 6 render-mode UIs into one component with nested ternaries (CD-19 P1). Splitting unblocks future style work AND addresses two P0/P1 findings in one refactor.

Output: `frontend/src/components/builder/LayerStyleEditor/` directory with 6 per-mode child files + a RenderModeSwitch + a thin barrel; `LayerStyleEditor.tsx` reduced to ≤ 500 LOC orchestrator; public import surface unchanged so no caller updates needed.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-03-SUMMARY.md

<interfaces>
<!-- LayerStyleEditor public contract (frontend/src/components/builder/LayerStyleEditor.tsx) -->
<!-- Props: extracted from lines 1-40; will preserve as the orchestrator's public interface -->
export interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
  onStyleConfigChange: (layerId: string, sc: StyleConfig) => void;
  onOpacityChange?: (layerId: string, opacity: number) => void;
  // … additional handler props as defined in source
}

<!-- Existing internal helpers / constants used by all modes (frontend/src/components/builder/LayerStyleEditor.tsx) -->
- const FILL_DEFAULTS, LINE_DEFAULTS, CIRCLE_DEFAULTS (lines 100-130)
- function getPaintValue, getOpacitySafeColor (utility helpers)
- imports HeatmapStyleControls + SliderRow from './HeatmapStyleControls'
- lazy(DataDrivenStyleEditor) — already lazy (line 10)

<!-- After Plan 03, the master opacity SliderRow at line 579 has a 100ms debounce + local state. -->
<!-- The split MUST preserve this debounce wrapping — move the local-state pattern into the orchestrator (so all sub-components share one debounced opacity), OR replicate per sub-component if each owns its own opacity slider. Pick: keep at orchestrator level — opacity is master-level, not per-mode. -->

<!-- Audit CD-19 (LayerStyleEditor.tsx:380-600 estimated) — nested ternaries for render-mode UI -->
<!-- Audit CB-07 (1204 LOC) — full split required -->

<!-- Existing test: frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx -->
<!-- ~1127 LOC monolith; will continue to pass after split (it tests the orchestrator behavior, which is preserved) -->
<!-- New per-mode tests are ADDITIVE, not replacements -->

<!-- Existing callers of LayerStyleEditor (verify via grep): -->
<!-- - frontend/src/components/builder/LayerEditorPanel.tsx:4 — import { LayerStyleEditor } from './LayerStyleEditor' -->
<!-- - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Carve out per-render-mode editors into LayerStyleEditor/ directory</name>
  <files>
    frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor/CircleEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor/SymbolEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor/HeatmapEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx,
    frontend/src/components/builder/LayerStyleEditor/__tests__/LineEditor.test.tsx,
    frontend/src/components/builder/LayerStyleEditor/__tests__/CircleEditor.test.tsx
  </files>
  <read_first>
    frontend/src/components/builder/LayerStyleEditor.tsx (read fully — 1204 LOC; identify the per-render-mode UI sections),
    frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx (~1127 LOC — read fully to understand the public contract being preserved),
    frontend/src/components/builder/HeatmapStyleControls.tsx (already separate — HeatmapEditor will wrap/re-export it),
    frontend/src/components/builder/LineGradientControls.tsx (already separate — LineEditor uses it),
    frontend/src/components/builder/LayerEditorPanel.tsx (line 4 — verify the LayerStyleEditor import after refactor still resolves)
  </read_first>
  <behavior>
    - Test 1: `<FillEditor layer={fillLayer} onPaintChange={mockFn} />` renders fill-opacity slider, fill-color picker, fill-outline-color picker, outline-width slider; identical visual output to the pre-split fill-mode UI
    - Test 2: `<LineEditor layer={lineLayer} onPaintChange={mockFn} />` renders line-color, line-width, line-opacity, line-gradient toggle; identical to pre-split line UI
    - Test 3: `<CircleEditor layer={circleLayer} onPaintChange={mockFn} />` renders circle-color, circle-radius, circle-stroke-color, circle-stroke-width; identical to pre-split circle UI
    - Test 4: Each sub-component is a default export AND a named export from its file (`export function FillEditor` + `export default FillEditor`)
    - Test 5: All sub-components share the same Props type signature (one of: `BaseStyleEditorProps`, defined in the directory's `types.ts`) — props are uniform so RenderModeSwitch can pass them through identically
  </behavior>
  <action>
    Create `frontend/src/components/builder/LayerStyleEditor/` directory. Create `frontend/src/components/builder/LayerStyleEditor/types.ts` exporting a shared `BaseStyleEditorProps` interface containing every prop currently passed to mode-specific render branches in LayerStyleEditor.tsx (read the file to enumerate — at minimum: `layer: MapLayerResponse`, `onPaintChange`, `onLayoutChange`, `onStyleConfigChange`, `paint: Record<string, unknown>`, `builderConfig: BuilderStyleConfig`). All sub-components consume `BaseStyleEditorProps`.

    Extract the **fill render-mode UI** from LayerStyleEditor.tsx (read the file — the fill branch is approximately lines 600-770, identifiable by `geomType === 'fill'` or `renderMode === 'fill'` guard) into a new file `frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx` exporting `export function FillEditor(props: BaseStyleEditorProps): JSX.Element`. Copy the JSX verbatim. Update relative imports (`./StyleColorPicker` → `../StyleColorPicker`, `./HeatmapStyleControls` → `../HeatmapStyleControls`, etc.).

    Repeat for line, circle, symbol, raster, heatmap. Be precise: each branch was originally guarded by `geomType === '<mode>'` or `renderMode === '<mode>'`; that guard logic moves UP into the orchestrator's RenderModeSwitch (Task 2). The sub-component itself assumes "I am rendering for my mode; no guard needed."

    For `HeatmapEditor.tsx`: most heatmap UI already lives in `HeatmapStyleControls.tsx`. HeatmapEditor is a thin wrapper that imports HeatmapStyleControls and passes `BaseStyleEditorProps`-derived props through. Same approach for `LineEditor` re: `LineGradientControls`.

    For each of FillEditor, LineEditor, CircleEditor: write a co-located unit test (`__tests__/FillEditor.test.tsx`, etc.) that mounts the sub-component with a minimal fixture layer and asserts the expected controls render. SymbolEditor, RasterEditor, HeatmapEditor tests are deferred to existing parent-component tests (already cover them — the goal of Plan 05 is to STRUCTURE, not to add net-new test coverage beyond the 3 most-used modes).

    **DO NOT MODIFY LayerStyleEditor.tsx YET** — Task 2 wires the orchestrator. This task just produces the sub-component files in parallel.

    LOC budget per sub-component: target ≤ 250 LOC each; if any exceeds 300 LOC, leave a `// TODO(1047-05): further split` comment but do not split further this plan.
  </action>
  <verify>
    <automated>test -d frontend/src/components/builder/LayerStyleEditor</automated>
    <automated>for f in FillEditor LineEditor CircleEditor SymbolEditor RasterEditor HeatmapEditor; do test -f frontend/src/components/builder/LayerStyleEditor/$f.tsx || { echo "MISSING: $f.tsx"; exit 1; }; done; echo OK</automated>
    <automated>cd frontend && npm run typecheck</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx src/components/builder/LayerStyleEditor/__tests__/LineEditor.test.tsx src/components/builder/LayerStyleEditor/__tests__/CircleEditor.test.tsx</automated>
  </verify>
  <acceptance_criteria>
    - 6 sub-component files exist under `frontend/src/components/builder/LayerStyleEditor/`
    - Shared `BaseStyleEditorProps` type defined in `types.ts`
    - 3 new test files (FillEditor, LineEditor, CircleEditor) pass in isolation
    - Each sub-component ≤ 300 LOC
    - Typecheck clean
  </acceptance_criteria>
  <done>Six per-render-mode editor files exist; three have isolated unit tests; types are shared.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Replace nested ternaries with RenderModeSwitch (CD-19)</name>
  <files>
    frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx,
    frontend/src/components/builder/LayerStyleEditor/__tests__/RenderModeSwitch.test.tsx
  </files>
  <read_first>
    frontend/src/components/builder/LayerStyleEditor.tsx (lines 380-600 — find the nested ternary block for renderMode UI),
    frontend/src/components/builder/renderAs.ts (RenderAsId + RenderAsAdapterType types),
    frontend/src/components/builder/LayerStyleEditor/types.ts (from Task 1)
  </read_first>
  <behavior>
    - Test 1: `<RenderModeSwitch renderMode="fill" {...props} />` renders FillEditor (verify by mocking FillEditor and asserting its mock receives the props)
    - Test 2: `<RenderModeSwitch renderMode="line" {...props} />` renders LineEditor
    - Test 3: same for circle, symbol, raster, heatmap
    - Test 4: `<RenderModeSwitch renderMode="unsupported-xyz" {...props} />` returns null and emits `console.warn` (DEV mode) — graceful fallback
  </behavior>
  <action>
    Create `frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx` exporting:
    ```
    interface RenderModeSwitchProps extends BaseStyleEditorProps { renderMode: RenderAsId | string }
    export function RenderModeSwitch(props: RenderModeSwitchProps): JSX.Element | null
    ```
    Body: build a lookup object (NOT nested ternaries — the entire point of CD-19's fix):
    ```
    const editorComponents = {
      fill: FillEditor,
      line: LineEditor,
      circle: CircleEditor,
      symbol: SymbolEditor,
      raster: RasterEditor,
      heatmap: HeatmapEditor,
    } as const;
    ```
    Resolve via `const Editor = editorComponents[renderMode as keyof typeof editorComponents]`. If `Editor` is undefined, log a DEV-only `console.warn` and return null. Otherwise `return <Editor {...rest} />`.

    Wrap each lazy load in the orchestrator (Task 3) — do NOT lazy-load the sub-components inside RenderModeSwitch itself (they're cheap and uniformly used; lazy-loading per-mode would over-fragment chunks).

    Co-located unit test `__tests__/RenderModeSwitch.test.tsx`: mock the 6 sub-components (vi.mock), render with each renderMode value, assert the correct mock's element is rendered. Test the unsupported-mode null case.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/components/builder/LayerStyleEditor/__tests__/RenderModeSwitch.test.tsx</automated>
    <automated>cd frontend && grep -c "editorComponents" src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx | grep -v ':0'</automated>
    <automated>cd frontend && rg -n "\\?\\s*<.*Editor.*\\?.*<.*Editor" src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx | wc -l | grep -E '^0$'</automated>
    <automated>cd frontend && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `RenderModeSwitch.tsx` exists with the lookup-table dispatch (no nested ternaries — rg confirms)
    - 7 behavior tests pass
    - Typecheck clean
  </acceptance_criteria>
  <done>Render-mode dispatch is a lookup table; CD-19 (nested ternary anti-pattern) closed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Reduce LayerStyleEditor.tsx to orchestrator + add barrel (preserve public contract)</name>
  <files>
    frontend/src/components/builder/LayerStyleEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor/index.ts
  </files>
  <read_first>
    frontend/src/components/builder/LayerStyleEditor.tsx (read fully again to see what shrinks),
    frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx (from Task 2),
    frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx (the existing monolith test — it must keep passing after the orchestrator delegates)
  </read_first>
  <behavior>
    - Test 1: The existing `LayerStyleEditor.test.tsx` passes WITHOUT modification (the public contract is unchanged)
    - Test 2: `import { LayerStyleEditor } from '@/components/builder/LayerStyleEditor'` resolves whether the path is the FILE (`LayerStyleEditor.tsx`) or the DIRECTORY (`LayerStyleEditor/index.ts`) — TS module resolution prefers the file in this case, so `LayerStyleEditor.tsx` continues to be the resolved import. Both barrels work for documentation but the orchestrator file remains the canonical resolution target.
    - Test 3: LayerStyleEditor.tsx is ≤ 500 LOC after refactor
    - Test 4: Master opacity SliderRow debounce (from Plan 03 Task 2) is preserved at the orchestrator level
  </behavior>
  <action>
    Rewrite `frontend/src/components/builder/LayerStyleEditor.tsx`. The new orchestrator is responsible for:
    1. The exported `LayerStyleEditor` component (preserve props, preserve memo() wrapping, preserve the existing JSDoc).
    2. Computing `renderMode` from `layer` + `builderConfig` (existing logic — keep it).
    3. The master opacity SliderRow (the debounced one from Plan 03 Task 2 — this stays at the orchestrator level, shared across all modes).
    4. The collapsible "Advanced JSON" panel + lazy DataDrivenStyleEditor (these stay at the orchestrator level — they're cross-mode).
    5. Delegating per-render-mode UI to `<RenderModeSwitch renderMode={renderMode} {...props} />`.

    All per-mode JSX moves OUT of this file (already done in Task 1's sub-component files). All shared helpers (getPaintValue, defaults objects) stay in the orchestrator as private helpers — OR migrate to `LayerStyleEditor/utils.ts` if Task 1's sub-components import them. Make this decision based on actual import patterns; prefer colocation.

    Target LOC: ≤ 500 (down from 1204; ~58% reduction). If you can't hit 500, document why in the SUMMARY.

    Create `frontend/src/components/builder/LayerStyleEditor/index.ts` as a barrel:
    ```
    export { LayerStyleEditor } from '../LayerStyleEditor';
    export type { LayerStyleEditorProps } from '../LayerStyleEditor';
    ```
    This is documentation/discoverability — TypeScript module resolution will continue to prefer `LayerStyleEditor.tsx` over `LayerStyleEditor/index.ts` because the file matches first. The barrel exists so future imports can use the directory form if preferred. **Important**: this prevents naming collision because TypeScript's resolution order is `LayerStyleEditor.tsx` > `LayerStyleEditor/index.ts` — Node-style "file beats directory" applies. Test 2 verifies imports continue to work.

    Update the children files' imports to point to the orchestrator if they import any shared types:
    - `BaseStyleEditorProps` lives in `LayerStyleEditor/types.ts` (already created in Task 1).
    - Shared helpers (getPaintValue, etc.) — if needed by sub-components, expose via `LayerStyleEditor/utils.ts`.

    Re-run the FULL existing test suite for LayerStyleEditor to verify no behavior regression: `cd frontend && npm run test -- --run src/components/builder/__tests__/LayerStyleEditor.test.tsx`.
  </action>
  <verify>
    <automated>cd frontend && wc -l src/components/builder/LayerStyleEditor.tsx | awk '$1 <= 500 {print "OK: " $1 " LOC"; exit 0} {print "FAIL: " $1 " LOC > 500"; exit 1}'</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/LayerStyleEditor.test.tsx</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/LayerEditorPanel.test.tsx</automated>
    <automated>cd frontend && grep -c "RenderModeSwitch" src/components/builder/LayerStyleEditor.tsx | grep -v ':0'</automated>
    <automated>cd frontend && npm run typecheck</automated>
    <automated>cd frontend && time npm run test 2>&1 | tail -5</automated>
  </verify>
  <acceptance_criteria>
    - `LayerStyleEditor.tsx` is ≤ 500 LOC
    - Existing `LayerStyleEditor.test.tsx` passes unchanged
    - `LayerEditorPanel.test.tsx` (the most direct caller) passes
    - `RenderModeSwitch` is referenced inside the orchestrator
    - `LayerStyleEditor/index.ts` barrel exists
    - Master opacity SliderRow + lazy DataDrivenStyleEditor still in orchestrator (verify by reading)
    - Vitest builder suite ≤ 10.5s wall-clock (PERF-06)
    - Typecheck clean
  </acceptance_criteria>
  <done>1204 → ≤ 500 LOC; public contract preserved; nested ternaries gone; existing tests pass without modification.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Caller imports LayerStyleEditor → barrel/file resolution | TypeScript module resolution order is the only guard against import-path drift. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1047-05-01 | Tampering | Public component contract regression | mitigate | Existing `LayerStyleEditor.test.tsx` (1127 LOC) runs unchanged; CODE-06 requires it stays green. Failure = revert split. |
| T-1047-05-02 | Tampering | Stale style logic in per-mode files | mitigate | Each sub-component is JSX-verbatim from the original branch; no behavior changes. Per-mode tests (FillEditor/LineEditor/CircleEditor) add isolation safety net. |
| T-1047-05-SC | Tampering | npm/pip installs | mitigate | No new packages introduced in this plan. |
</threat_model>

<verification>
- Typecheck clean
- LayerStyleEditor.tsx ≤ 500 LOC (`wc -l`)
- LayerStyleEditor.test.tsx passes unchanged (public contract preserved)
- LayerEditorPanel.test.tsx passes (most direct caller)
- 3 new per-mode tests pass
- Vitest builder suite ≤ 10.5s
</verification>

<success_criteria>
1. LayerStyleEditor.tsx is ≤ 500 LOC; per-render-mode editors live under `LayerStyleEditor/`.
2. RenderModeSwitch dispatches by lookup table (no nested ternaries — CD-19 closed).
3. Public import surface `import { LayerStyleEditor } from '@/components/builder/LayerStyleEditor'` continues to resolve identically.
4. Existing `LayerStyleEditor.test.tsx` passes unchanged (CODE-06 — public contract preserved).
5. No PERF-06 regression: vitest ≤ 10.5s.
</success_criteria>

<output>
Create `.planning/phases/1047-perf-and-code-quality-fixes/1047-05-SUMMARY.md` when done. Include:
- Before/after LOC for LayerStyleEditor.tsx
- LOC of each new sub-component
- List of imports updated (callers of LayerStyleEditor — confirm none required code changes)
- Decision: where shared helpers landed (`utils.ts` vs orchestrator)
- vitest builder suite runtime delta (PERF-06 check)
</output>
