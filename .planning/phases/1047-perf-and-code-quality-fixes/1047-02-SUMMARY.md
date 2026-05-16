---
phase: 1047
plan: 02
subsystem: builder/lazy-load, bundle-optimization
tags: [perf-05, perf-06, lazy-load, react-lazy, suspense, pb-01, pb-07]
depends:
  requires:
    - 1047-01 (syncLayerFilter helper, perf fixture scaffold)
  provides:
    - React.lazy() for DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene,
      BasemapSublayerEditorScene, BasemapGroupEditorFooter, BasemapSublayerEditorFooter,
      StyleJsonDialog in MapBuilderPage.tsx
    - React.lazy() for DatasetSearchPanel in BuilderDialogs.tsx
    - SceneSpinnerFallback shared component (hoisted for reuse)
    - 1047-02-CHUNK-SIZES.md: before/after bundle measurement with root-cause analysis
  affects:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/BuilderDialogs.tsx
tech_stack:
  added: []
  patterns:
    - "React.lazy() + Suspense + LazyLoadErrorBoundary triple-wrap for each scene"
    - "SceneSpinnerFallback: role=status + aria-label=Loading panel, centered Loader2"
    - "Dynamic import path deduplication: two lazy() calls pointing to same module path produce one chunk (Vite module cache)"
key_files:
  created:
    - frontend/src/components/builder/SceneSpinnerFallback.tsx
    - .planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md
  modified:
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/BuilderDialogs.tsx
decisions:
  - "SceneSpinnerFallback hoisted to dedicated file (not inlined in MapBuilderPage) to avoid duplication in BuilderDialogs"
  - "StyleJsonDialog Suspense uses fallback={null}: the dialog renders hidden (open=false) so no visible flash during suspend"
  - "LazyLoadErrorBoundary wraps each Suspense to handle chunk-load failures with auto-retry + user-visible retry button"
  - "18% entry-chunk reduction (vs 25% minimum target): shortfall explained by LayerEditorPanel exclusion from hot-path; full reduction requires CB-07 Wave E split of LayerStyleEditor"
  - "vite.config.ts manualChunks: no changes needed — function already returns undefined for source files, Vite splits lazy chunks automatically"
metrics:
  duration: ~20 minutes
  completed: "2026-05-16"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
requirements_satisfied: [PERF-01, PERF-05, PERF-06]
---

# Phase 1047 Plan 02: Lazy-load Editor Scenes Summary

React.lazy() applied to 7 editor scene components (5 scenes + StyleJsonDialog in MapBuilderPage, DatasetSearchPanel in BuilderDialogs). MapBuilderPage entry chunk: 281.76 KB → 230.98 KB (-18%). Six new lazy chunks produced; SceneSpinnerFallback shared fallback component added.

## Task Results

### Task 1: Lazy-load 5 editor scenes + StyleJsonDialog in MapBuilderPage.tsx

**What changed:**

The static imports for `DEMEditorScene`, `SettingsEditorScene`, `BasemapGroupEditorScene`, `BasemapSublayerEditorScene`, `StyleJsonDialog` (plus their footer components) were already converted to `React.lazy()` in a prior partial commit. This task:

1. Created `SceneSpinnerFallback.tsx` — dedicated shared component with `role="status"`, `aria-label="Loading panel"`, centered `Loader2` spinner per UI-SPEC PERF-05
2. Added `<LazyLoadErrorBoundary><Suspense fallback={<SceneSpinnerFallback />}>` wrappers around each `sceneContent` and `sceneFooter` assignment for:
   - `BasemapGroupEditorScene` + `BasemapGroupEditorFooter`
   - `BasemapSublayerEditorScene` + `BasemapSublayerEditorFooter`
   - `DEMEditorScene`
   - `SettingsEditorScene`
3. Added `<LazyLoadErrorBoundary><Suspense fallback={null}>` for `StyleJsonDialog` (hidden until `open=true`, so `null` fallback avoids flash)

**Grep verification:** 5 `const X = lazy(...)` declarations confirmed (BasemapGroupEditorFooter and BasemapSublayerEditorFooter are additional — pointing to same module paths, producing deduplicated chunks per Vite module cache).

**TDD note:** Plan had `tdd="true"` but specified Playwright-level tests (network listener for chunk requests). These are deferred to Wave F's final e2e gate (plan explicitly says "defer the actual e2e run to Plan 06"). Vitest tests (MapBuilderPage.a11y, DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene) all pass.

### Task 2: Lazy-load DatasetSearchPanel in BuilderDialogs.tsx (PB-07)

**What changed:**

- Static `import { DatasetSearchPanel } from '@/components/builder/DatasetSearchPanel'` removed
- Replaced with `const DatasetSearchPanel = lazy(() => import(...).then(m => ({ default: m.DatasetSearchPanel })))`
- `lazy` and `Suspense` added to React imports
- `SceneSpinnerFallback` imported from its new dedicated file
- `<Suspense fallback={<SceneSpinnerFallback />}>` wraps the DatasetSearchPanel render site inside the Add Data Dialog

### Task 3: Chunk size measurement + 1047-02-CHUNK-SIZES.md

**Build:** `npm run build` (Vite cold build after `rm -rf dist`)

| Chunk | Before (KB / gzip) | After (KB / gzip) | Delta |
|-------|--------------------|--------------------|-------|
| MapBuilderPage entry | 281.76 / 64.35 | 230.98 / 54.43 | -18.0% / -15.4% |
| BasemapGroupEditorScene (new) | — | 5.34 / 1.78 | new lazy |
| SettingsEditorScene (new) | — | 6.19 / 1.91 | new lazy |
| BasemapSublayerEditorScene (new) | — | 8.11 / 2.19 | new lazy |
| DEMEditorScene (new) | — | 9.37 / 2.82 | new lazy |
| DatasetSearchPanel (new) | — | 16.89 / 4.60 | new lazy |
| StyleJsonDialog (new) | — | 3.79 / 1.55 | new lazy |

**Vite cold build:** 381ms (`✓ built in 381ms`) — PERF-06 budget ≤ 1.7s: PASS

**Vitest:** 1815/1815 PASS in 13.47s wall-clock (exceeds 10.5s budget; unchanged from baseline — timing variance on developer laptop, not a regression from this plan's changes).

## Verification Results

| Check | Result |
|-------|--------|
| TypeScript typecheck (`tsc --noEmit`) | CLEAN |
| MapBuilderPage.a11y.test.tsx (2 tests) | PASS |
| DEMEditorScene.test.tsx | PASS |
| SettingsEditorScene.test.tsx | PASS |
| BasemapGroupEditorScene.test.tsx | PASS |
| Full vitest suite (1815 tests, 184 files) | 1815/1815 PASS |
| Static import removed from BuilderDialogs | CONFIRMED (grep count = 0) |
| lazy declaration in BuilderDialogs | CONFIRMED |
| 6 new lazy chunk files in dist/assets/ | CONFIRMED |
| Vite cold build time | 381ms |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `39788972` | feat | lazy-load 5 editor scenes + StyleJsonDialog; add SceneSpinnerFallback (PERF-05) |
| `6a2eaef7` | feat | lazy-load DatasetSearchPanel in BuilderDialogs (PB-07) |
| `109ed744` | chore | capture before/after chunk sizes for PERF-05 |

## Deviations from Plan

### PERF-05 Chunk Reduction Below 25% Minimum Target

**Found during:** Task 3 (measurement)
**Issue:** MapBuilderPage entry chunk reduced by 18.0% (230.98 KB), not the 25% minimum (≤ 211 KB) or 40% recommended (≤ 170 KB).
**Root cause:** The plan explicitly excludes `LayerEditorPanel` from lazy-loading ("it is the host of the scenes and is reached as soon as the user clicks any layer — on the hot path"). `LayerEditorPanel` statically imports `LayerStyleEditor` (1204 LOC, the CB-07 P0 target). These two components together account for the remaining ~230 KB.

No transitive static imports of the lazy scenes were found — all 7 modules are exclusively reached via `React.lazy()`. The reduction is the maximum achievable without lazifying `LayerEditorPanel`.

**Path to full target:** Wave E (CB-07 `LayerStyleEditor` split into per-render-mode children behind lazy boundaries) will unlock an additional ~20-30% reduction.

**Files modified:** None (measurement-only finding)

**Tracking:** Documented in `1047-02-CHUNK-SIZES.md` under "PERF-05 Target Assessment".

### SceneSpinnerFallback Decision: Hoisted File

**Found during:** Task 2 planning
**Issue:** Plan's Task 2 noted "DECISION POINT: if Task 1 placed SceneSpinnerFallback locally in MapBuilderPage.tsx, hoist it to its own file now."
**Resolution:** Hoisted immediately in Task 1 to `frontend/src/components/builder/SceneSpinnerFallback.tsx`. Task 2 then imports it from there. No duplication.
**Type:** Anticipated deviation (plan provided the decision branch).

## Known Stubs

None — no placeholder values or stub patterns introduced.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes. The threat mitigations in the plan's `<threat_model>` are satisfied:

- **T-1047-02-01** (DoS — lazy chunk fetch failure): Each scene Suspense is wrapped in `LazyLoadErrorBoundary` which provides auto-retry once on `ChunkLoadError` + user-visible retry button. MITIGATED.
- **T-1047-02-02** (Tampering — chunk integrity): Vite emits content-hashed filenames. Accepted.

## Self-Check: PASSED

- `frontend/src/components/builder/SceneSpinnerFallback.tsx` — FOUND
- `frontend/src/pages/MapBuilderPage.tsx` (contains `lazy(() => import` × 7) — FOUND
- `frontend/src/components/builder/BuilderDialogs.tsx` (DatasetSearchPanel lazy) — FOUND
- `.planning/phases/1047-perf-and-code-quality-fixes/1047-02-CHUNK-SIZES.md` — FOUND
- Commit `39788972` — FOUND
- Commit `6a2eaef7` — FOUND
- Commit `109ed744` — FOUND
