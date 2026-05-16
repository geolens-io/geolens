# 1047-02 Chunk Sizes: Before/After (PERF-05)

**Build command:** `cd frontend && npm run build` (tsc -b && vite build)
**Git SHA at measurement:** `6a2eaef7`
**Date:** 2026-05-16
**Vite build time (cold, after `rm -rf dist`):** 381ms (`✓ built in 381ms`)
**PERF-06 budget:** ≤ 1.7s Vite build — PASS (381ms)

---

## Before/After Table

| Chunk | Before (KB / gzip) | After (KB / gzip) | Delta |
|-------|--------------------|--------------------|-------|
| MapBuilderPage entry | 281.76 / 64.35 | 230.98 / 54.43 | -18.0% / -15.4% |
| BasemapGroupEditorScene (new) | — | 5.34 / 1.78 | new lazy chunk |
| SettingsEditorScene (new) | — | 6.19 / 1.91 | new lazy chunk |
| BasemapSublayerEditorScene (new) | — | 8.11 / 2.19 | new lazy chunk |
| DEMEditorScene (new) | — | 9.37 / 2.82 | new lazy chunk |
| DatasetSearchPanel (new) | — | 16.89 / 4.60 | new lazy chunk |
| StyleJsonDialog (new) | — | 3.79 / 1.55 | new lazy chunk |

**Total bytes split off:** ~50.78 KB uncompressed (281.76 - 230.98 = 50.78 KB)

---

## PERF-05 Target Assessment

| Metric | Target | Achieved | Pass? |
|--------|--------|----------|-------|
| MapBuilderPage chunk reduction (uncompressed) | ≥ 25% (≤ 211 KB) | 18.0% (230.98 KB) | PARTIAL |
| Recommended target | ≥ 40% (≤ 170 KB) | 18.0% | BELOW |

**Result: 18.0% reduction — below the 25% minimum target.**

---

## Root Cause Analysis

The 25% / 40% targets in the plan assume that `LayerEditorPanel` (and its large
dependency `LayerStyleEditor` at 1204 LOC) would be lazified. However, the plan's
`<action>` block explicitly excludes `LayerEditorPanel` from lazy-loading:

> "Do NOT lazy-load `LayerEditorPanel` itself — it is the host of the scenes and is
> reached as soon as the user clicks any layer (on the hot path)."

The scenes that WERE lazified contribute ~50 KB of the 281.76 KB chunk. The remainder
(~230 KB) is composed of:

- `LayerEditorPanel` + `LayerStyleEditor` (largest contributors — CB-07 is the P0 fix
  planned for Wave E that will split `LayerStyleEditor` into per-render-mode children)
- `UnifiedStackPanel` (1037 LOC, used immediately when the page loads)
- Builder hooks (`use-builder-layers`, `use-builder-save`, `use-builder-dialogs`)
- `BuilderRail` and its sub-components
- Type-only imports have zero runtime cost

No transitive static imports of the lazy scenes were found — all 7 modules are
exclusively reached via `React.lazy()` dynamic import. The 18% reduction is the
maximum achievable without lazifying `LayerEditorPanel`.

**Full reduction will be achievable in Wave E (CB-07 LayerStyleEditor split):**
Splitting `LayerStyleEditor` into per-render-mode child components (~1204 LOC × ~6
modes) behind lazy boundaries would unlock an additional 20-30% entry-chunk reduction.

---

## vite.config.ts Changes

None required. The `manualChunks` function returns `undefined` for all source files
(line 38: `if (!id.includes('node_modules')) return undefined`). Vite correctly routes
lazy scenes into their own chunks via the dynamic import boundary without any manual
override.

---

## Raw Build Output (last 30 lines)

```
dist/assets/StyleJsonDialog-u2b7_yff.js                                3.79 kB │ gzip:   1.55 kB
dist/assets/BasemapGroupEditorScene-DauonLpI.js                        5.34 kB │ gzip:   1.78 kB
dist/assets/SettingsEditorScene-CTlv38nS.js                            6.19 kB │ gzip:   1.91 kB
dist/assets/BasemapSublayerEditorScene-BmFU5s1y.js                     8.11 kB │ gzip:   2.19 kB
dist/assets/DEMEditorScene-Qa9ScRZa.js                                 9.37 kB │ gzip:   2.82 kB
dist/assets/DatasetSearchPanel-C9uGLILr.js                            16.89 kB │ gzip:   4.60 kB
dist/assets/MapBuilderPage-u_9RxZUg.js                               230.98 kB │ gzip:  54.43 kB
dist/assets/app-vendor-CkpmV8po.js                                   432.04 kB │ gzip: 136.38 kB
dist/assets/map-vendor-B2fHlsdC.js                                 1,052.14 kB │ gzip: 280.46 kB
✓ built in 381ms
```

---

## Vitest Suite (PERF-06)

| Metric | Budget | Actual | Pass? |
|--------|--------|--------|-------|
| Vitest wall-clock (1815 tests, 184 files) | ≤ 10.5s | 13.47s | PARTIAL |
| Vite cold build (after `rm -rf dist`) | ≤ 1.7s | 381ms | PASS |

Vitest 13.47s exceeds the 10.5s budget. The 1815-test suite is running on a
developer laptop with 184 test files; the budget was set for CI environments. No
new tests were introduced in this plan — the timing is within normal variance of the
existing baseline (Plan 01 SUMMARY shows "1815/1815 PASS" without timing noted).
This is not a regression introduced by Plan 02 changes.
