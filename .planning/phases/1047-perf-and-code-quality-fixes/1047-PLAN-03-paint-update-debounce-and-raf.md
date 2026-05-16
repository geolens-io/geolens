---
phase: 1047-perf-and-code-quality-fixes
plan: 03
type: execute
wave: 3
depends_on: [1047-01]
files_modified:
  - frontend/src/lib/builder/raf-coalesce.ts
  - frontend/src/lib/builder/__tests__/raf-coalesce.test.ts
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/components/builder/LayerFilterEditor.tsx
  - frontend/src/components/builder/DataDrivenStyleEditor.tsx
  - frontend/src/components/builder/StyleColorPicker.tsx
  - frontend/src/components/builder/hooks/use-layer-map-sync.ts
  - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts
autonomous: true
requirements: [PERF-04, PERF-06]
must_haves:
  truths:
    - "Opacity slider in LayerStyleEditor debounces onOpacityChange at 100ms (PB-02)"
    - "Expression editor + filter editor + data-driven style editor onChange handlers debounce at 200ms (PB-04)"
    - "StyleColorPicker debounce remains at 100ms — confirmed aligned with opacity slider so combined drag does not spike to 200ms (PB-06)"
    - "Paint property writes route through a shared `coalesceFrame(map, layerId, paintKey, value)` helper that collapses multiple updates inside one rAF tick into a single map.setPaintProperty per (layerId, paintKey) pair"
    - "Unit-level rAF coalescing test proves: 10 successive coalesceFrame calls for the same (layerId, paintKey) inside one frame produce exactly 1 map.setPaintProperty call (with the last value)"
  artifacts:
    - path: "frontend/src/lib/builder/raf-coalesce.ts"
      provides: "coalesceFrame helper + getPendingWritesForTest"
      contains: "export function coalesceFrame"
    - path: "frontend/src/lib/builder/__tests__/raf-coalesce.test.ts"
      provides: "rAF coalescing contract test"
      contains: "describe('coalesceFrame'"
    - path: "frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts"
      provides: "integration test proving paint updates collapse to 1 rAF tick"
  key_links:
    - from: "frontend/src/components/builder/LayerStyleEditor.tsx"
      to: "opacity slider onChange"
      via: "debounce(100ms) wrapper around onOpacityChange"
      pattern: "debounce.*onOpacityChange|useDebounce.*opacity"
    - from: "frontend/src/components/builder/hooks/use-layer-map-sync.ts"
      to: "coalesceFrame"
      via: "import { coalesceFrame } from '@/lib/builder/raf-coalesce'"
      pattern: "coalesceFrame\\("
---

<objective>
Coalesce MapLibre paint updates to one repaint per animation frame (PERF-04). Three legs:
1. Add 100ms debounce to opacity slider (PB-02) and align with the existing 100ms color picker debounce (PB-06).
2. Add 200ms debounce to filter expression editor + data-driven style editor onChange (PB-04).
3. Introduce a shared `coalesceFrame` utility in `frontend/src/lib/builder/raf-coalesce.ts` and route paint writes from `use-layer-map-sync.ts` through it.

Purpose: PERF-04 requirement is "paint property updates coalesce into one MapLibre repaint per animation frame; unit-level rAF coalescing test passes." Today the opacity slider fires 50-100 setPaintProperty calls per second during drag.

Output: rAF coalescing helper with unit test; debounce wrappers on opacity + filter + expression editors; integration test proving downstream collapse.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-UI-SPEC.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md

<interfaces>
<!-- Existing debounce helper - reuse, do not create another -->
From frontend/src/hooks/use-debounce.ts (already exists, used in other contexts)

<!-- Existing color picker debounce pattern (StyleColorPicker.tsx:46-48) — copy this shape -->
const [localColor, setLocalColor] = useState(value);
useEffect(() => { const t = setTimeout(() => onChange(localColor), 100); return () => clearTimeout(t); }, [localColor]);

<!-- Opacity slider site in LayerStyleEditor.tsx (line ~579-590) — currently calls onOpacityChange directly on slider change -->
{onOpacityChange && (
  <SliderRow
    label={t('style.opacity')}
    value={layer.opacity}
    onChange={(val) => onOpacityChange(layer.id, val)}
    ... />
)}

<!-- Filter editor: LayerFilterEditor.tsx fires onChange on every keystroke -->
<!-- Data-driven editor: DataDrivenStyleEditor.tsx fires onChange on every keystroke -->

<!-- use-layer-map-sync.ts handlePaintChange (line 94-126 per audit) — central choke point for all paint writes -->
<!-- This is where `coalesceFrame` plugs in: instead of calling adapter.syncPaint(...) immediately, queue via coalesceFrame -->

<!-- Adapter syncPaint signature (frontend/src/components/builder/layer-adapters/types.ts) -->
syncPaint(map: MaplibreMap, input: AdapterLayerInput): void
<!-- Adapters call map.setPaintProperty internally — many calls per syncPaint invocation -->
<!-- For PERF-04 the coalescing is at the PER-FRAME level for the WHOLE syncPaint invocation, not per individual setPaintProperty -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Create coalesceFrame utility + unit test (rAF coalescing contract)</name>
  <files>
    frontend/src/lib/builder/raf-coalesce.ts,
    frontend/src/lib/builder/__tests__/raf-coalesce.test.ts
  </files>
  <read_first>
    frontend/src/hooks/use-debounce.ts (existing debounce pattern to match style),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md (Specifics block: "Introduce `frontend/src/lib/builder/raf-coalesce.ts`"),
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md (PERF-04 section + PB-02/04/06)
  </read_first>
  <behavior>
    - Test 1: `coalesceFrame(key, fn)` with the same key called 10 times inside one frame results in `fn` being called exactly once (the last queued fn) on the next rAF tick
    - Test 2: Different keys do NOT coalesce — `coalesceFrame('A', fnA)` and `coalesceFrame('B', fnB)` both fire on the next tick
    - Test 3: After the rAF tick fires, the next `coalesceFrame('A', fn)` queues a new rAF — keys do not "stick" across frames
    - Test 4: `coalesceFrame` is a no-op in SSR / environments where `requestAnimationFrame` is undefined (falls back to invoking fn synchronously) — covers vitest environment with no rAF mocking
    - Test 5: Test exposes `__getPendingForTest()` introspection helper so other tests can assert the pending map is non-empty pre-tick and empty post-tick
  </behavior>
  <action>
    Create `frontend/src/lib/builder/raf-coalesce.ts`. Module-scoped Map `pending = new Map<string, () => void>()` and `rafHandle: number | null = null`. Export `coalesceFrame(key: string, fn: () => void): void`:
    1. `pending.set(key, fn)` — overwrites any prior fn for the same key (this is the coalescing semantics; later writes win, which matches "last value in the frame is what the user sees").
    2. If `rafHandle === null`, schedule via `rafHandle = requestAnimationFrame(flush)` where `flush` iterates `pending`, calls each fn inside a try/catch (DEV-mode `console.debug` on throw), then `pending.clear()` + `rafHandle = null`.
    3. SSR fallback: if `typeof requestAnimationFrame === 'undefined'`, invoke `fn()` synchronously and return (no queuing).

    Export a test-only `__getPendingForTest(): ReadonlyMap<string, () => void>` and `__flushForTest(): void` helpers. Both are no-ops in production builds — wrap in `if (import.meta.env.DEV || import.meta.env.MODE === 'test') { export ... }` pattern, OR simply export unconditionally (the helpers are harmless in prod and the audit does not care).

    Write the test file with vitest's `vi.useFakeTimers()` + `vi.advanceTimersToNextFrame()` (vitest 4.x supports this), or fall back to mocking `requestAnimationFrame` directly. Cover all 5 behaviors above. Use the existing test patterns in `frontend/src/hooks/__tests__/use-debounce.test.ts` as a style reference (read it before writing).
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/lib/builder/__tests__/raf-coalesce.test.ts</automated>
    <automated>cd frontend && grep -c "export function coalesceFrame" src/lib/builder/raf-coalesce.ts | grep -v ':0'</automated>
    <automated>cd frontend && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - 5 behavior tests pass (run the test file in isolation)
    - `coalesceFrame` exported with the documented contract; module-level pending map; rAF-based flush
    - SSR / no-rAF fallback works (invoke fn synchronously)
    - Typecheck clean
  </acceptance_criteria>
  <done>rAF coalescing utility ships with a contract test that proves it collapses N updates per frame to 1.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Debounce opacity slider + filter expression + data-driven style editors</name>
  <files>
    frontend/src/components/builder/LayerStyleEditor.tsx,
    frontend/src/components/builder/LayerFilterEditor.tsx,
    frontend/src/components/builder/DataDrivenStyleEditor.tsx,
    frontend/src/components/builder/StyleColorPicker.tsx
  </files>
  <read_first>
    frontend/src/components/builder/LayerStyleEditor.tsx (read the opacity SliderRow at line 579-590 + line 596+ + line 605+ + line 679+),
    frontend/src/components/builder/StyleColorPicker.tsx (existing 100ms debounce at line 46-48 — confirm pattern + extract it if reusable),
    frontend/src/components/builder/LayerFilterEditor.tsx (find the onChange callback that fires on every keystroke),
    frontend/src/components/builder/DataDrivenStyleEditor.tsx (find the onChange that fires per keystroke),
    frontend/src/hooks/use-debounce.ts (existing debounce hook — prefer this over hand-rolling new ones)
  </read_first>
  <behavior>
    - Test 1 (LayerStyleEditor opacity slider): rapid `onChange(0.1) → onChange(0.2) → onChange(0.3)` within 50ms results in exactly ONE `onOpacityChange` call with value 0.3 after the debounce window
    - Test 2 (LayerFilterEditor): typing 10 characters within 200ms fires `onChange` exactly once with the final string value
    - Test 3 (DataDrivenStyleEditor): similar to Test 2 for expression edits
    - Test 4: StyleColorPicker existing 100ms debounce is unchanged (regression check — its test continues to pass)
    - Test 5: Opacity + color picker debounce timers are NOT aligned to the same absolute clock (audit PB-06 worried about jank spikes at 200ms intervals if they fire on different edges); verify by running both simultaneously and confirming neither produces a >120ms gap on a typical drag — this is verification, not enforcement
  </behavior>
  <action>
    Pattern: use the existing `useDebounce` hook from `frontend/src/hooks/use-debounce.ts` (or replicate StyleColorPicker's local-state pattern if useDebounce isn't a callback variant). Apply consistently across all four files.

    LayerStyleEditor.tsx: at line ~579 the master opacity SliderRow calls `onChange={(val) => onOpacityChange(layer.id, val)}`. Replace with a local-state pattern: `const [localOpacity, setLocalOpacity] = useState(layer.opacity); useEffect(() => { const t = setTimeout(() => onOpacityChange(layer.id, localOpacity), 100); return () => clearTimeout(t); }, [localOpacity, layer.id]);` and bind the slider to `localOpacity` + `setLocalOpacity`. Also sync `localOpacity` back to `layer.opacity` when the layer prop changes (effect dependency: `useEffect(() => setLocalOpacity(layer.opacity), [layer.opacity]);`). Apply the same pattern to the other SliderRow instances at lines 596, 605, 679+ (read the file to find them all — any slider whose onChange flows through to a paint setter needs the same treatment, but ONLY if it currently fires on every pixel).

    LayerFilterEditor.tsx: identify the onChange callback that fires on every keystroke (likely a textarea or Input bound to `setFilter`). Apply the same local-state + 200ms debounce pattern.

    DataDrivenStyleEditor.tsx: same — find the onChange fired per keystroke. 200ms debounce.

    StyleColorPicker.tsx: confirm the existing 100ms debounce at line 46-48 still works after any auto-fix tooling runs. Do NOT change its timing — PB-06 confirmed it's already correct.

    Write 3 new tests (or extend existing test files): `LayerStyleEditor.test.tsx` add a "opacity slider debounces" test, `LayerFilterEditor.test.ts` add a "filter editor debounces at 200ms", `DataDrivenStyleEditor.test.tsx` add an "expression editor debounces at 200ms". Use vitest fake timers.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/LayerStyleEditor.test.tsx src/components/builder/__tests__/LayerFilterEditor.test.ts src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx</automated>
    <automated>cd frontend && grep -cE "setTimeout.*100|useDebounce.*100" src/components/builder/LayerStyleEditor.tsx | awk '$1 >= 1 {print "OK"; exit 0}'</automated>
    <automated>cd frontend && grep -cE "setTimeout.*200|useDebounce.*200" src/components/builder/LayerFilterEditor.tsx src/components/builder/DataDrivenStyleEditor.tsx | awk -F: 'BEGIN{ok=0} $2 >= 1 {ok++} END{exit ok >= 2 ? 0 : 1}'</automated>
    <automated>cd frontend && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - Master opacity slider in LayerStyleEditor debounces at 100ms; rapid changes coalesce into 1 onOpacityChange call
    - LayerFilterEditor and DataDrivenStyleEditor onChange callbacks debounce at 200ms
    - StyleColorPicker 100ms debounce unchanged (no regression)
    - New tests pass; existing tests pass (no regression)
    - Typecheck clean
  </acceptance_criteria>
  <done>Three editor surfaces now debounce paint writes; PB-02, PB-04, PB-06 closed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Route use-layer-map-sync paint writes through coalesceFrame + integration test</name>
  <files>
    frontend/src/components/builder/hooks/use-layer-map-sync.ts,
    frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts
  </files>
  <read_first>
    frontend/src/components/builder/hooks/use-layer-map-sync.ts (read fully — find handlePaintChange, handleVisibilityChange, etc.),
    frontend/src/lib/builder/raf-coalesce.ts (from Task 1),
    frontend/src/components/builder/layer-adapters/registry.ts (getAdapter returns an adapter with syncPaint method),
    frontend/src/components/builder/layer-adapters/types.ts (AdapterLayerInput shape)
  </read_first>
  <behavior>
    - Test 1: `handlePaintChange(layerId, paint)` called 10 times in rapid succession for the same layer results in adapter.syncPaint being called exactly ONCE on the next rAF tick (with the final paint value)
    - Test 2: `handlePaintChange('layer-A', paintA)` and `handlePaintChange('layer-B', paintB)` BOTH fire on the next rAF tick (different keys do not coalesce)
    - Test 3: Visibility changes also coalesce (or are explicitly kept synchronous — pick one and document; visibility writes are cheaper than paint and may not need coalescing). Lean toward: paint writes coalesce, visibility writes stay synchronous to keep toggle latency at 0. Document the choice in the action body.
  </behavior>
  <action>
    Open `frontend/src/components/builder/hooks/use-layer-map-sync.ts`. Locate `handlePaintChange` (line ~94-126 per audit). It currently calls `adapter.syncPaint(map, input)` synchronously inside a useCallback. Replace the direct call with:

    `coalesceFrame(\`paint:${layerId}\`, () => adapter.syncPaint(map, input));`

    Import `coalesceFrame` from `@/lib/builder/raf-coalesce`. The cache key `paint:${layerId}` ensures multiple paint updates for the SAME layer collapse to one rAF tick, while paint updates for DIFFERENT layers all fire on the same rAF tick (separate keys, single shared rAF — that's the helper's contract).

    Do NOT change visibility/filter/order handlers — keep those synchronous. Document this in a code comment: `// Paint writes coalesce via rAF (PERF-04); visibility/filter/order remain synchronous because they're idempotent and cheap, and synchronous semantics let UI toggles feel instant.`

    Write the integration test at `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts`. Use `@testing-library/react`'s `renderHook` to mount `useLayerMapSync`. Mock the adapter's `syncPaint` via vi.mock on the registry. Call the returned `handlePaintChange` 10 times rapidly; flush the rAF; assert `syncPaint` mock was called exactly once with the LAST paint value.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts</automated>
    <automated>cd frontend && grep -c "coalesceFrame" src/components/builder/hooks/use-layer-map-sync.ts | grep -v ':0'</automated>
    <automated>cd frontend && npm run typecheck</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/hooks/__tests__/ 2>&1 | tail -10</automated>
  </verify>
  <acceptance_criteria>
    - `coalesceFrame` is imported and used inside `handlePaintChange` (grep count ≥ 1)
    - Integration test proves: 10 successive handlePaintChange calls → 1 adapter.syncPaint call after rAF tick
    - Visibility/filter/order handlers unchanged (synchronous)
    - All existing use-layer-map-sync.test (if any) tests pass
    - Typecheck clean
  </acceptance_criteria>
  <done>Paint writes from use-layer-map-sync collapse to 1 MapLibre repaint per rAF; PERF-04 unit-level coalescing test passes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| User input → debounce buffer → setPaintProperty | Debounce introduces a 100/200ms gap; rapid edits accumulate in component state but only fire the latest. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1047-03-01 | Information disclosure | Debounced filter editor | accept | Filter expressions are MapLibre style only — no PII, no auth boundary. Debounce timing is not a side-channel. |
| T-1047-03-02 | DoS | rAF coalescing | mitigate | `coalesceFrame` overwrites pending fn per key, bounding queue size by unique key count (= layer count, capped at 200 per `_MAX_LAYERS_PER_MAP`). No unbounded growth. |
| T-1047-03-03 | Tampering | Stale paint after unmount | mitigate | If the component unmounts before the rAF flushes, the cleanup effect should cancel via `cancelAnimationFrame`. The helper does not currently support cancellation per key, but the worst case is one stale setPaintProperty on an unmounted map (caught by try/catch in adapter). Acceptable for v1. |
| T-1047-03-SC | Tampering | npm/pip installs | mitigate | No new packages introduced in this plan. |
</threat_model>

<verification>
- Vitest builder suite: `cd frontend && npm run test` — green
- Typecheck clean
- All 3 task test files pass
- Manual: open builder with a saved map, drag opacity slider — frame rate stays smooth (Chrome DevTools Rendering tab; verify in Plan 06 e2e gate)
</verification>

<success_criteria>
1. `coalesceFrame` helper exists at `frontend/src/lib/builder/raf-coalesce.ts` with full contract test.
2. Opacity slider (100ms), filter editor (200ms), data-driven editor (200ms) all debounce.
3. `use-layer-map-sync.handlePaintChange` routes through coalesceFrame; integration test proves 10:1 coalescing.
4. PERF-04 unit-level rAF coalescing test passes (the integration test in Task 3 is the canonical proof).
5. No regression: vitest builder suite ≤ 10.5s, typecheck clean.
</success_criteria>

<output>
Create `.planning/phases/1047-perf-and-code-quality-fixes/1047-03-SUMMARY.md` when done. Include:
- coalesceFrame contract summary (key collision semantics)
- List of debounce sites + chosen ms values
- Visibility/filter/order: confirmed STAYED synchronous
- Integration test result: "10 paint updates → 1 syncPaint call" — copy the assertion line
</output>
