---
phase: 1047-perf-and-code-quality-fixes
plan: 02
type: execute
wave: 2
depends_on: [1047-01]
files_modified:
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/components/builder/BuilderDialogs.tsx
  - frontend/vite.config.ts
  - e2e/perf/builder-large-map.spec.ts
  - .planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md
autonomous: true
requirements: [PERF-01, PERF-05, PERF-06]
must_haves:
  truths:
    - "DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene, BasemapSublayerEditorScene, and StyleJsonDialog are lazy-imported and load only when their host scene/dialog opens"
    - "DatasetSearchPanel is lazy-imported and loads only when the Add Data dialog opens (PB-07)"
    - "MapBuilderPage entry chunk drops at least 25% in uncompressed bytes vs the Phase 1046 baseline (281.76 KB → ≤ 211 KB target)"
    - "Lazy chunks fall back to a centered Loader2 spinner inside each scene boundary (per UI-SPEC PERF-05 row), with role=status + aria-label='Loading panel'"
    - "Builder e2e smoke (e2e:smoke:builder) stays green; cold first build ≤ 1.7s; vitest builder suite ≤ 10.5s (PERF-06 budget)"
    - "Before/after chunk sizes documented in 1047-02-CHUNK-SIZES.md"
  artifacts:
    - path: "frontend/src/pages/MapBuilderPage.tsx"
      provides: "Lazy imports for 5 editor scenes + StyleJsonDialog"
      contains: "lazy(() =>"
    - path: "frontend/src/components/builder/BuilderDialogs.tsx"
      provides: "Lazy DatasetSearchPanel import"
      contains: "lazy(() =>"
    - path: ".planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md"
      provides: "Before/after chunk size table"
      contains: "MapBuilderPage"
  key_links:
    - from: "frontend/src/pages/MapBuilderPage.tsx"
      to: "DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene, BasemapSublayerEditorScene, StyleJsonDialog"
      via: "React.lazy + Suspense fallback"
      pattern: "lazy\\(\\(\\) => import"
---

<objective>
Reduce MapBuilderPage route entry chunk by lazy-loading 5 editor scenes + DatasetSearchPanel (PB-01 + PB-07). Target 40% chunk-size reduction per BUILDER-PERF-BASELINE.md "Recommended Targets for PERF-05".

Purpose: Builder entry chunk is currently 281.76 KB — largest in the app. Five editor scenes are imported synchronously even when the user never opens them. Lazy-loading is the single biggest mechanical PERF win in the phase.

Output: `MapBuilderPage.tsx` and `BuilderDialogs.tsx` lazy-import editor scenes + DatasetSearchPanel; Suspense fallbacks per UI-SPEC; before/after chunk-size sidecar doc.
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
@.planning/phases/1047-perf-and-code-quality-fixes/1047-01-SUMMARY.md

<interfaces>
<!-- Current static imports in MapBuilderPage.tsx (lines 25-39) — these become lazy() -->
import { DEMEditorScene } from '@/components/builder/DEMEditorScene';
import { SettingsEditorScene } from '@/components/builder/SettingsEditorScene';
import { BasemapGroupEditorScene, BasemapGroupEditorFooter } from '@/components/builder/BasemapGroupEditorScene';
import { BasemapSublayerEditorScene } from '@/components/builder/BasemapSublayerEditorScene';   // verify exact import path
import { LayerEditorPanel, type LayerEditorHandlers } from '@/components/builder/LayerEditorPanel';
import { StyleJsonDialog } from '@/components/builder/StyleJsonDialog';

<!-- Existing lazy pattern in MapBuilderPage.tsx (lines 19-23) — copy this approach -->
const BuilderMap = lazy(() =>
  import('@/components/builder/BuilderMap').then((m) => ({ default: m.BuilderMap })),
);

<!-- Existing Suspense fallback (MapBuilderPage.tsx:1167) -->
<Suspense fallback={<LoadingState />}>...</Suspense>

<!-- UI-SPEC PERF-05 fallback contract (inline spinner for scene panels, NOT full LoadingState) -->
<!-- frontend/src/components/builder/BuilderDialogs.tsx currently statically imports DatasetSearchPanel: -->
import { DatasetSearchPanel } from '@/components/builder/DatasetSearchPanel';
<!-- Audit PB-07: only render DatasetSearchPanel inside <Dialog open={showAddData}> — defer the import -->

<!-- BasemapGroupEditorScene exports TWO things — the scene + a footer. Both must come via the same lazy chunk -->
<!-- Either: import the module once and destructure both, OR: lazy-import the scene and statically import the footer if it's small -->
<!-- Confirm via Read: line 27 of MapBuilderPage.tsx: import { BasemapGroupEditorScene, BasemapGroupEditorFooter } -->

<!-- vite.config.ts manualChunks logic at line 29-105 — verify the lazy split doesn't get merged back into map-vendor -->
<!-- manualChunks merges maplibre-gl + @vis.gl/react-maplibre into 'map-vendor' — separate from MapBuilderPage entry chunk -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Lazy-load 5 editor scenes + StyleJsonDialog in MapBuilderPage.tsx</name>
  <files>
    frontend/src/pages/MapBuilderPage.tsx
  </files>
  <read_first>
    frontend/src/pages/MapBuilderPage.tsx (read fully — 1300+ LOC; identify the 5 scene render sites and Suspense host pattern at line 1167),
    frontend/src/components/builder/DEMEditorScene.tsx (export shape — default vs named),
    frontend/src/components/builder/SettingsEditorScene.tsx,
    frontend/src/components/builder/BasemapGroupEditorScene.tsx (note dual export: BasemapGroupEditorScene + BasemapGroupEditorFooter — both must reach the user from the lazy chunk),
    frontend/src/components/builder/BasemapSublayerEditorScene.tsx,
    frontend/src/components/builder/StyleJsonDialog.tsx,
    frontend/src/components/layout/LoadingState.tsx (existing fallback component),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-UI-SPEC.md (PERF-05 fallback contract)
  </read_first>
  <behavior>
    - Test 1: Initial route load of /maps/:id does NOT request the DEMEditorScene chunk until the user expands a DEM layer (verified via Playwright network listener filtering for the chunk filename)
    - Test 2: Initial route load does NOT request the SettingsEditorScene chunk until the user clicks the Settings rail icon
    - Test 3: When a lazy chunk is in-flight, the user sees a centered Loader2 spinner with `role="status"` and `aria-label="Loading panel"` (per UI-SPEC PERF-05)
    - Test 4: MapBuilderPage.test.tsx existing tests still pass (no public contract break)
  </behavior>
  <action>
    Convert the 5 static imports at MapBuilderPage.tsx lines 25-39 to React.lazy:
    - `const DEMEditorScene = lazy(() => import('@/components/builder/DEMEditorScene').then((m) => ({ default: m.DEMEditorScene })));`
    - `const SettingsEditorScene = lazy(() => import('@/components/builder/SettingsEditorScene').then((m) => ({ default: m.SettingsEditorScene })));`
    - For BasemapGroupEditorScene + BasemapGroupEditorFooter (dual export from same module): use a SHARED lazy chunk — define one `BasemapGroupEditorModule = lazy(...)` would fail because lazy needs a default export per child. Instead, create two named lazy components that point to the SAME import path; Webpack/Vite will de-duplicate via the module cache. Pattern: `const BasemapGroupEditorScene = lazy(() => import('@/components/builder/BasemapGroupEditorScene').then((m) => ({ default: m.BasemapGroupEditorScene })));` and `const BasemapGroupEditorFooter = lazy(() => import('@/components/builder/BasemapGroupEditorScene').then((m) => ({ default: m.BasemapGroupEditorFooter })));` — Vite ships one chunk because the module path is identical.
    - `const BasemapSublayerEditorScene = lazy(() => import('@/components/builder/BasemapSublayerEditorScene').then((m) => ({ default: m.BasemapSublayerEditorScene })));`
    - `const StyleJsonDialog = lazy(() => import('@/components/builder/StyleJsonDialog').then((m) => ({ default: m.StyleJsonDialog })));`

    Wrap each scene render site (read MapBuilderPage to find them — search for `<DEMEditorScene`, `<SettingsEditorScene`, etc.) in a `<Suspense fallback={<SceneSpinnerFallback />}>` boundary. Define `SceneSpinnerFallback` as a small local component inside MapBuilderPage.tsx (above the export, OR colocate in `frontend/src/components/builder/SceneSpinnerFallback.tsx` if reused — judgment call) that renders the exact markup specified in UI-SPEC PERF-05: `<div role="status" aria-label="Loading panel" className="flex items-center justify-center p-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>`. Import `Loader2` from `lucide-react`.

    Do NOT lazy-load `LayerEditorPanel` itself — it is the host of the scenes and is reached as soon as the user clicks any layer (on the hot path). Audit PB-01 specifically scopes lazy-load to the 5 scene leaves + StyleJsonDialog, not the panel wrapper.

    Preserve `LayerEditorHandlers` type import (it's a type-only import — already free of runtime cost).

    Keep the EXISTING `<Suspense fallback={<LoadingState />}>` wrapper at line 1167 (it wraps `BuilderMap` — that lazy import was done in Phase 274, do NOT touch it).
  </action>
  <verify>
    <automated>cd frontend && npm run typecheck</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/MapBuilderPage.a11y.test.tsx</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/DEMEditorScene.test.tsx src/components/builder/__tests__/SettingsEditorScene.test.tsx src/components/builder/__tests__/BasemapGroupEditorScene.test.tsx</automated>
    <automated>cd frontend && grep -cE "^const (DEMEditorScene|SettingsEditorScene|BasemapGroupEditorScene|BasemapSublayerEditorScene|StyleJsonDialog) = lazy" src/pages/MapBuilderPage.tsx | grep -E '^5$'</automated>
  </verify>
  <acceptance_criteria>
    - 5 `const X = lazy(...)` declarations exist for DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene, BasemapSublayerEditorScene, StyleJsonDialog (grep count == 5; BasemapGroupEditorFooter is a 6th lazy declaration pointing to the same module — does not affect the count)
    - Each scene render site is wrapped in `<Suspense fallback={<SceneSpinnerFallback />}>` with the spinner markup per UI-SPEC
    - Loader2 imported from lucide-react
    - Existing MapBuilderPage tests still pass
    - Typecheck clean
  </acceptance_criteria>
  <done>Five scenes + StyleJsonDialog ship in separate chunks; user sees the spinner fallback during chunk fetch; no test regressions.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Lazy-load DatasetSearchPanel in BuilderDialogs.tsx (PB-07)</name>
  <files>
    frontend/src/components/builder/BuilderDialogs.tsx
  </files>
  <read_first>
    frontend/src/components/builder/BuilderDialogs.tsx (185 LOC; current line 12 statically imports DatasetSearchPanel),
    frontend/src/components/builder/DatasetSearchPanel.tsx (744 LOC — ~35 KB chunk per audit PB-07),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-UI-SPEC.md (PERF-05 fallback contract — same SceneSpinnerFallback pattern)
  </read_first>
  <behavior>
    - Test 1: BuilderDialogs renders without requesting DatasetSearchPanel chunk when `showAddData` is false (initial state)
    - Test 2: When `showAddData` flips to true, the DatasetSearchPanel chunk is requested and the panel renders after the Suspense fallback resolves
    - Test 3: BuilderDialogs.test.tsx existing tests pass (if any exist — verify and update mocks if needed)
  </behavior>
  <action>
    In `frontend/src/components/builder/BuilderDialogs.tsx`: replace `import { DatasetSearchPanel } from '@/components/builder/DatasetSearchPanel';` (line 12) with `const DatasetSearchPanel = lazy(() => import('@/components/builder/DatasetSearchPanel').then((m) => ({ default: m.DatasetSearchPanel })));` and add `import { lazy, Suspense } from 'react';` if not present.

    Wrap the `<DatasetSearchPanel ... />` render site (currently inside the `<Dialog open={showAddData}>` block at line 87) in a `<Suspense fallback={<SceneSpinnerFallback />}>` boundary. Either re-use the SceneSpinnerFallback from Task 1 (if it was hoisted to a shared file) OR inline the spinner markup here (same structure: `<div role="status" aria-label="Loading panel" className="flex items-center justify-center p-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>`).

    DECISION POINT: if Task 1 placed `SceneSpinnerFallback` locally in MapBuilderPage.tsx, hoist it to `frontend/src/components/builder/SceneSpinnerFallback.tsx` now and update Task 1's MapBuilderPage imports. Use your judgment based on what Task 1 actually shipped (read the file before deciding). Reusing one component avoids drift.

    Do NOT lazy-load `ShareDialog` from `SharePanel` (line 13) — it's small (~5 KB) and was not flagged by the audit. Keep it static.
  </action>
  <verify>
    <automated>cd frontend && npm run typecheck</automated>
    <automated>cd frontend && grep -c "lazy(() => import.*DatasetSearchPanel" src/components/builder/BuilderDialogs.tsx | grep -v ':0'</automated>
    <automated>cd frontend && rg -n "import \\{ DatasetSearchPanel \\} from" src/components/builder/BuilderDialogs.tsx | wc -l | grep -E '^0$'</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/BuilderDialogs 2>&1 | tail -20 || echo "no test file exists — OK"</automated>
  </verify>
  <acceptance_criteria>
    - `DatasetSearchPanel` is imported via `lazy(() => import(...))` only
    - The static `import { DatasetSearchPanel } ...` line at the top of BuilderDialogs.tsx is removed
    - Suspense boundary wraps the DatasetSearchPanel render site
    - Typecheck clean; no test regressions
  </acceptance_criteria>
  <done>DatasetSearchPanel chunk is deferred until the Add Data dialog opens.</done>
</task>

<task type="auto">
  <name>Task 3: Measure chunk sizes before/after + write 1047-02-CHUNK-SIZES.md sidecar</name>
  <files>
    frontend/vite.config.ts,
    .planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md
  </files>
  <read_first>
    frontend/vite.config.ts (manualChunks logic at lines 29-105 — verify lazy splits do not get re-merged into MapBuilderPage chunk by an overly-greedy chunk function),
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md (PERF-05 section — baseline is 281.76 KB / 64.35 KB gzip)
  </read_first>
  <action>
    Run `cd frontend && npm run build` and capture the chunk sizes from stdout. Find the MapBuilderPage entry chunk (current baseline filename `MapBuilderPage-CagiZ9nL.js`; new hash will differ — use the `MapBuilderPage-*.js` glob). Verify the lazy split worked: there should be 5+ NEW chunks named after the lazy-loaded scenes (Vite auto-names lazy chunks based on the dynamic import path — e.g., `DEMEditorScene-{hash}.js`, `SettingsEditorScene-{hash}.js`).

    Open `frontend/vite.config.ts` and inspect the `manualChunks` function. If the function explicitly bundles `@/components/builder` into the MapBuilderPage chunk (look for path-based routing in the chunk fn), confirm it does NOT capture the lazy scenes. If it does, exclude those 5 scene files from the chunk fn (add an early-return branch: `if (id.includes('DEMEditorScene') || id.includes('SettingsEditorScene') || id.includes('BasemapGroupEditorScene') || id.includes('BasemapSublayerEditorScene') || id.includes('StyleJsonDialog') || id.includes('DatasetSearchPanel')) return;` — `return undefined` lets Vite default-route the module into its own chunk via the dynamic-import boundary).

    Write `.planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md` with a before/after table:

    | Chunk | Before (KB / gzip) | After (KB / gzip) | Delta |
    |-------|--------------------|--------------------|-------|
    | MapBuilderPage entry | 281.76 / 64.35 | <new> / <new gzip> | -X% |
    | DEMEditorScene (new) | — | <kb> / <gzip> | new lazy |
    | SettingsEditorScene (new) | — | <kb> / <gzip> | new lazy |
    | BasemapGroupEditorScene (new) | — | <kb> / <gzip> | new lazy |
    | BasemapSublayerEditorScene (new) | — | <kb> / <gzip> | new lazy |
    | StyleJsonDialog (new) | — | <kb> / <gzip> | new lazy |
    | DatasetSearchPanel (new) | — | <kb> / <gzip> | new lazy |

    Include: build command used, git SHA at measurement time, raw build output excerpt (last 30 lines of `npm run build`), and a note on cold first-build wall-clock (use `time npm run build` after deleting `frontend/dist/` + `frontend/node_modules/.vite/` if available).

    Target per PERF-05: MapBuilderPage entry chunk drops by at least 25% (≤ 211 KB uncompressed) — the recommended target is 40% (≤ 170 KB) but 25% is the minimum acceptable; document the actual achieved reduction. If under 25%, investigate (likely a transitive import dragging the modules back in — re-grep for `import.*DEMEditorScene` etc. across builder/ to find any unintentional static reference).
  </action>
  <verify>
    <automated>cd frontend && npm run build 2>&1 | tail -50 | tee /tmp/1047-02-build.log</automated>
    <automated>test -f .planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md</automated>
    <automated>cd frontend && ls -la dist/assets/MapBuilderPage-*.js 2>/dev/null | awk '{print $5}' | head -1</automated>
    <automated>cd frontend && ls dist/assets/ | grep -cE "(DEMEditorScene|SettingsEditorScene|BasemapGroup|BasemapSublayer|StyleJsonDialog|DatasetSearchPanel)" | awk '$1 >= 5 {print "OK"; exit 0} {print "FAIL: only " $1 " lazy chunks found"; exit 1}'</automated>
  </verify>
  <acceptance_criteria>
    - At least 5 new lazy chunks named after the scenes exist in `frontend/dist/assets/` after build
    - MapBuilderPage entry chunk shrinks by at least 25% vs the 281.76 KB baseline (target 40%)
    - `1047-02-CHUNK-SIZES.md` exists with the full before/after table and build-command provenance
    - No regression in cold build runtime: `time npm run build` ≤ 1.7s (PERF-06 budget)
    - vitest builder suite ≤ 10.5s wall-clock
  </acceptance_criteria>
  <done>Bundle reduction measured and documented; PERF-05 target met or actual deviation explained in the sidecar doc.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| User browser → CDN/origin for lazy chunks | Each lazy chunk is fetched on demand; HTTP error surfaces via React error boundary. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1047-02-01 | DoS | Lazy chunk fetch failure | mitigate | `LazyLoadErrorBoundary` already exists in `frontend/src/components/error` (used by LayerStyleEditor for DataDrivenStyleEditor). Wrap each Suspense in the same error boundary OR confirm the page-level boundary catches it. Failure surfaces as a "Failed to load panel" message + retry button. |
| T-1047-02-02 | Tampering | Chunk integrity | accept | Vite emits hashed filenames; CDN-level integrity is out of scope. |
| T-1047-02-SC | Tampering | npm/pip installs | mitigate | No new packages introduced in this plan. |
</threat_model>

<verification>
- Typecheck clean: `cd frontend && npm run typecheck`
- Vitest builder suite green: `cd frontend && npm run test`
- Build succeeds and produces 5+ new lazy chunks: `ls frontend/dist/assets/ | grep -E "(DEMEditorScene|SettingsEditorScene|BasemapGroup|StyleJsonDialog|DatasetSearchPanel)"`
- Entry chunk shrinks ≥ 25%: read sidecar `1047-02-CHUNK-SIZES.md`
- e2e smoke (builder) still passes — defer the actual e2e run to Plan 06 (Wave F final gate) to avoid each wave running the full Playwright suite
</verification>

<success_criteria>
1. 5 editor scenes + StyleJsonDialog + DatasetSearchPanel are lazy-loaded; static imports removed.
2. Each lazy boundary has a Suspense fallback per UI-SPEC PERF-05.
3. MapBuilderPage entry chunk shrinks by at least 25% uncompressed vs the Phase 1046 baseline.
4. Before/after chunk-size table exists at `1047-02-CHUNK-SIZES.md`.
5. No PERF-06 regression: cold build ≤ 1.7s, vitest ≤ 10.5s.
</success_criteria>

<output>
Create `.planning/phases/1047-perf-and-code-quality-fixes/1047-02-SUMMARY.md` when done. Include:
- Before/after MapBuilderPage chunk size (uncompressed + gzip + % delta)
- List of new lazy chunk filenames (Vite auto-generated)
- Decision: was `SceneSpinnerFallback` hoisted to its own file or kept local?
- Any vite.config.ts manualChunks adjustments made
- PERF-06 runtime check: vitest wall-clock and cold build wall-clock
</output>
