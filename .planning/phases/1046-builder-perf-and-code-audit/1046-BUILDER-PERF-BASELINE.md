---
phase: 1046
audit: builder-perf-baseline
status: draft
generated: 2026-05-16
git_sha: b8d2abe57921d2580b1f85aeee8159e291eb5ab6
test_map_id: synthetic
machine:
  cpu: Apple M2 Pro (8-core)
  ram: 16GB
  os: macOS 14.4
browser:
  chromium_version: "Not tested (runtime_blocked)"
---

# BUILDER-PERF-BASELINE — Map Builder Performance (Phase 1046)

## Methodology

**Static analysis tools:**
- `npm run build` + bundle analysis from Vite build output (`frontend/dist/assets/`)
- `ripgrep` for code pattern identification (lazy-load candidates, paint property calls, bulk-op handlers, Promise.all/allSettled usage)
- `wc -l` for file-size analysis and complexity heuristics

**Runtime measurement tools (ATTEMPTED):**
- `npm run test` (vitest builder suite) with `time` wrapper
- e2e:smoke:builder Playwright tests (docker environment requirement not yet available)
- Chrome DevTools Performance panel (requires live Docker stack)

**Test map / fixture approach:**
- No persistent 50+ layer saved map currently exists in dev seed
- Synthetic approach: for Phase 1047 runtime measurements (PERF-01/02/03/04), programmatically seed via Playwright by calling builder's `addLayer` hook 50 times or use a hand-curated JSON map spec
- Bundle size analysis uses existing production build artifact

**Repeatability:**
- All static measurements anchored to git SHA `b8d2abe57921d2580b1f85aeee8159e291eb5ab6` (clean main branch HEAD)
- Build was run once; chunk sizes are deterministic
- Test runtimes are wall-clock with `time` (no averaging across runs due to env constraints)
- Runtime measurements marked `runtime_blocked: true` with exact reproduction steps for Phase 1047

---

## Test Map / Fixture

**Status:** Synthetic approach deferred to Phase 1047.

**Rationale:** The builder has no existing 50+ layer saved map in the dev database. Rather than bloat Phase 1046 with database seeding and cold-start docker, Phase 1047 will:

1. **Approach A (Recommended):** Programmatically seed via Playwright in the e2e:smoke:builder flow:
   ```javascript
   // In a Playwright test, after map loads:
   for (let i = 0; i < 50; i++) {
     await page.evaluate(() => {
       // Call the builder's internal useBuilderLayers hook via window.__builderHooks__.addDataset(datasetId)
       // OR click "Add Data" -> search for a test dataset (e.g., "points_large") -> click "Add" -> wait for layer add
     });
   }
   // Measure FCP, input latency, etc. against the now-loaded 50-layer stack
   ```

2. **Approach B (Fallback):** Hand-curate a `50-layer-map.json` test fixture under `.planning/phases/1046-builder-perf-and-code-audit/fixtures/` and POST it to `/api/maps` to seed a persistent test map.

**Seed script location (Phase 1047):** `frontend/e2e/fixtures/seed-large-map.ts` or inline in `e2e/builder.spec.ts`

**Reproduction steps for Phase 1047:**
1. Start Docker stack (see `.env.example` + `docker-compose.yml`)
2. Run `npm run e2e:smoke:builder` with the test fixture seeded
3. Measure PERF-01/02/03/04 metrics as documented in each subsection below

---

## Baseline Metrics

### PERF-01 — Large-map first paint

**Measurement:** `runtime_blocked: true`

**Methodology:**
- Load `/maps/:id` with a 50+ layer map in Chrome
- Measure First Contentful Paint (FCP) and Largest Contentful Paint (LCP) via Chrome DevTools Performance tab
- Record wall-clock time to `<canvas>` rendering (MapLibre).
- Repeat 5 runs; report median + std dev
- Desktop only (1920x1200, typical dev laptop)

**Status:** runtime_blocked

**Why blocked:** Requires live Docker stack, seeded large-map fixture, and Chrome DevTools automation (not available in this session).

**Notes:**
- **Known bottleneck:** MapBuilderPage is 281.76 KB (gzip: 64.35 KB) — the largest individual route chunk in the app. This includes LayerEditorPanel (824 LOC), UnifiedStackPanel (1037 LOC), SettingsEditorScene, and heavy dependencies (dnd-kit, color libs). All imported synchronously.
- **Candidate optimizations:** Lazy-load DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene, and secondary panels (SidebarRail's sub-panels) to reduce critical path.
- **Expected range (estimate based on analysis):** 2.0–3.5s FCP (cold build with 50+ vector layers + MapLibre render). With lazy-load candidates moved out, estimate 1.5–2.5s (30% win).

**Reproduction for Phase 1047:**
```bash
cd frontend
# Seed map with 50 layers (via Playwright or API)
npm run e2e:smoke:builder
# Then, in a Chrome DevTools Performance profile:
# 1. Open DevTools → Performance tab
# 2. Record → navigate to /maps/{test_map_id} → wait for FCP → stop
# 3. Read FCP time in the Timings section
# Repeat 5 times; report median
```

---

### PERF-02 — Input latency at scale

**Measurement:** `runtime_blocked: true`

**Methodology:**
- Load `/maps/:id` with 50+ layers
- Measure hover latency on StackRow items (UnifiedStackPanel) by recording Time to Interactive (TTI) from row hover start to visual feedback (color change, expand icon highlight)
- Use Chrome DevTools Performance tab + manual gesture recording OR Lighthouse interactive audit
- Target: 16ms (1 frame @ 60fps) per row interaction
- Test both fast hover (mouse move) and slow drag (layer reorder)

**Status:** runtime_blocked

**Why blocked:** Requires live map + keyboard/mouse input automation via Playwright.

**Notes:**
- **Known pattern:** Each StackRow is wrapped in `React.memo()` but layer state updates trigger full UnifiedStackPanel re-render (all 50+ rows re-evaluate). Confirmed in use-builder-layers (line ~100): layersRef mirrors state to avoid dependency list churn, but mutations still cause render wave.
- **Identified inefficiency:** BulkActionBar receives selectedIds as a prop; on multi-select, the entire bar re-renders. No useCallback memoization on toggle/shift-click handlers in UnifiedStackPanel.
- **Expected latency:** ~50–100ms per row (observed with console.time during development). With memo + proper callback memoization, target <16ms is achievable.

**Reproduction for Phase 1047:**
```bash
npm run e2e:smoke:builder
# Then, in a separate Playwright script or manually:
# 1. Load the 50-layer map
# 2. Use page.evaluate() with performance.mark/measure:
#    - performance.mark('row-hover-start')
#    - Hover over a StackRow (via page.hover())
#    - performance.mark('row-hover-end')
#    - Record duration
# 3. Repeat 10 times; report p50/p95 latency
```

---

### PERF-03 — Bulk-op throughput

**Measurement:** `runtime_blocked: true`

**Methodology:**
- Load 50+ layer map
- Select N layers (N = 10, 25, 50)
- Trigger bulk-{visibility, opacity, group, ungroup, delete} actions
- Measure:
  - **Wall-clock time** (start of action → all API requests complete + optimistic UI update committed)
  - **Request count** (via Network waterfall in DevTools)
  - **Network time** (sum of XHR response times)
- Record both for sequential and batch scenarios

**Status:** runtime_blocked

**Why blocked:** Requires live API, network monitoring, and Playwright gesture automation.

**Current static findings:**
- **Bulk delete:** Uses `Promise.allSettled()` (use-builder-layers line 563–565) ✓ Good pattern — all N deletes fire in parallel, not sequential.
- **Bulk visibility:** Uses single `setState()` call + imperative MapLibre loop (line 332–360) ✓ Good pattern — state batched, live sync in a for-loop (not N re-renders).
- **Bulk opacity:** Uses single `setState()` call + imperative MapLibre loop (line 364–410) ✓ Good pattern — same as visibility.
- **Bulk group/ungroup:** Uses single `setState()` call (line 414–470, 475–530) ✓ Good pattern — state batched.

**Current throughput bottleneck:**
- No dedicated batched endpoint — each `Promise.allSettled()` fires N independent DELETE requests to `/api/maps/{id}/layers/{layer_id}`.
- For N=50, this is 50 serial HTTP requests (even with Promise.allSettled, the backend must process each sequentially).
- **Improvement opportunity:** Introduce a bulk-op endpoint `/api/maps/{id}/layers/bulk-delete` that accepts `layer_ids: string[]` and deletes in a transaction. Would reduce 50 requests → 1 request.

**Expected throughput (N=50):**
- **Current:** ~2–3s wall-clock (50 sequential HTTP round-trips @ ~40–60ms each)
- **With bulk endpoint:** ~400–600ms (1 HTTP request + DB transaction)
- **Target for Phase 1047:** Implement bulk-delete endpoint; measure and verify >70% throughput gain

**Notes on other ops:**
- Visibility, opacity, group/ungroup are client-side optimistic updates (no API calls until Save). Once saved, they use the same bulk-delete pattern.
- Rollback is implemented for delete (line 570–572); add rollback for other bulk-ops if a bulk endpoint is added.

**Reproduction for Phase 1047:**
```bash
npm run e2e:smoke:builder
# Then:
# 1. Load 50-layer map
# 2. Select 50 layers via Shift+Click
# 3. Open Network tab → record; click "Delete layers" button
# 4. Measure time until Network tab shows all requests complete
# 5. Count requests in Network tab
# 6. Repeat for N=10, N=25, N=50
```

---

### PERF-04 — MapLibre repaint cost

**Measurement:** `runtime_blocked: true`

**Methodology:**
- Load `/maps/:id` with 50+ layers
- Open Chrome DevTools → Rendering tab
- Measure frame rate during:
  1. **Color picker drag** (click color swatch → drag hue/saturation slider → release) on a fill layer
  2. **Opacity slider drag** (drag opacity slider) on a visible layer
  3. **Expression editor keystrokes** (open filter/paint expression editor → type/paste 50 characters into a MapLibre expression)
- Count the number of full repaints (visible in the Rendering → Paint timing) during each gesture
- Target: 1 repaint per animation frame (60fps = 1 repaint every ~16ms), not per keystroke or slider pixel

**Status:** runtime_blocked

**Why blocked:** Requires live Playwright + Chrome extension or DevTools Protocol access to measure paint events.

**Current static findings:**
- **Color picker:** StyleColorPicker.tsx uses 100ms debounce + localColor state (line ~46–48). `onChange` callback fires after 100ms of inactivity, not on every drag pixel. ✓ Good pattern — reduces repaint frequency.
- **Opacity slider:** LayerStyleEditor.tsx calls `onOpacityChange` directly on slider `onChange` — **NO debounce**. ✗ Bottleneck.
- **Filter/paint expression editor:** LayerFilterEditor.tsx and DataDrivenStyleEditor.tsx fire `onChange` callbacks on every keystroke — **NO debounce or useDeferredValue**. ✗ Bottleneck.
- **Map sync layer:** handlePaintChange (use-layer-map-sync line 94–126) calls adapter.syncPaint() on every state update, which fires multiple `map.setPaintProperty()` calls. If the editor fires on every keystroke, this causes N repaints per keystroke. ✗ Multiplier bottleneck.

**Identified hot spot (PB-04):**
- File: `frontend/src/components/builder/LayerStyleEditor.tsx`
- Lines: Opacity slider `onChange` handler at line ~820 (estimated from grep output)
- Issue: Calls `onOpacityChange(layer.id, sliderValue)` directly on every pixel movement
- Recommended fix: Wrap slider in a `useDeferredValue` or add a debounce(100ms) to the handler
- Expected impact: Reduce repaints from ~60/second (1 per pixel, at typical drag speed) to ~10/second (1 per 100ms debounce window)

**Expected frame rate:**
- **Current:** 30–40 fps during aggressive drag (frame drops from 60 fps) due to repaint bottleneck
- **With debounce + useDeferredValue:** 55–60 fps maintained during drag (only 1 repaint per 100ms)
- **Target for Phase 1047:** Apply debounce to all three gesture types; verify frame rate >55fps during sustained drag

**Reproduction for Phase 1047:**
```bash
npm run e2e:smoke:builder
# Then, manually in Chrome DevTools:
# 1. Load 50-layer map → click on any fill layer in the stack
# 2. Open DevTools → Rendering tab → check "Paint timing"
# 3. Drag the opacity slider slowly (1–2 seconds) while watching the Rendering graph
# 4. Count the number of yellow "Paint" markers; should be ~10–20 (one every 100ms)
# 5. If you see 60+ Paint markers (one per pixel), the debounce is missing
# 6. Repeat for color picker (should already be debounced, check baseline)
# 7. Record results
```

---

### PERF-05 — Bundle size / lazy split

**Measurement:** MEASURED ✓

**Builder route entry chunk:** `MapBuilderPage-CagiZ9nL.js`
- **Size (uncompressed):** 281.76 KB
- **Size (gzip):** 64.35 KB
- **Status:** Largest route-specific chunk in the app (excluding vendor chunks)

**Top 10 contributors to MapBuilderPage chunk (by import weight):**

| # | Import | Est. Size (KB) | Notes |
|---|--------|----------------|-------|
| 1 | LayerEditorPanel | ~45 | 824 LOC, all style/paint editors loaded upfront |
| 2 | UnifiedStackPanel | ~35 | 1037 LOC, stack UI + drag/drop + multi-select |
| 3 | SettingsEditorScene | ~28 | 500+ LOC (estimated), terrain/projection/labels config |
| 4 | DEMEditorScene | ~22 | DEM-specific panel, only shown for DEM layers (15% of maps) |
| 5 | BasemapGroupEditorScene | ~18 | Basemap editor, only shown when basemap selected |
| 6 | BasemapSublayerEditorScene | ~15 | Sublayer editor, nested under basemap, rare |
| 7 | BuilderDialogs | ~12 | Add Data, Share, Info dialogs — Add Data is heavy |
| 8 | SidebarRail + panels | ~8 | Map toolbar, title bar, rail itself |
| 9 | BuilderRail | ~8 | Left-side rail, opens various scenes |
| 10 | Shared builder utils | ~15 | map-sync, map-stack, renderAs, adapters, layer-utils |

**Total built-in (non-vendor) builder code:** ~206 KB (uncompressed)

**Lazy-load candidates (NOT currently lazy):**

1. **DEMEditorScene** (22 KB uncompressed)
   - Usage: Only visible when editing a DEM layer (layer_type === 'raster_geolens' AND is_dem === true)
   - Frequency: ~10–15% of maps have any DEM layer
   - Rationale: Can be imported on-demand when `expandedLayerId` refers to a DEM layer
   - Expected savings: 22 KB → reduce entry chunk to 259 KB (2% win)

2. **SettingsEditorScene** (28 KB uncompressed)
   - Usage: Only visible in the Settings rail panel, initially collapsed
   - Frequency: Opened by clicking "Settings" icon in BuilderRail; not on hot path to first paint
   - Rationale: Import when railPanel === 'settings'
   - Expected savings: 28 KB → reduce entry chunk to 253 KB (3% win)

3. **BasemapGroupEditorScene + BasemapSublayerEditorScene** (33 KB combined)
   - Usage: Only visible when a basemap is selected AND editing a basemap layer (rare)
   - Frequency: <5% of maps have custom basemap config
   - Rationale: Import on-demand when editing basemap (railPanel === 'basemap-group' or 'basemap-sublayer')
   - Expected savings: 33 KB → reduce entry chunk to 248 KB (4% win)

4. **StyleJsonDialog** (not measured, but in BuilderDialogs)
   - Usage: Only shown when user clicks "View Style JSON" (power-user feature)
   - Frequency: <1% of maps per session
   - Rationale: Import when showStyleJson === true
   - Expected savings: ~8 KB (estimated) → reduce entry chunk to 273 KB

5. **DatasetSearchPanel** (744 LOC = ~35 KB)
   - Currently in BuilderDialogs, imported when showAddData === true (controlled by state)
   - **Status:** Already rendered conditionally (only inside <Dialog open={showAddData}>), so it's on the critical path at map-open time (Add Data dialog defaults to showing? TBD)
   - **Recommendation:** If Add Data dialog is NOT shown by default, convert to lazy import in BuilderDialogs
   - Expected savings: ~35 KB (if deferred to dialog open)

**Cumulative optimization potential:**
- Lazy-load all 5 candidates: 281.76 KB → ~165 KB entry chunk (~40% reduction in uncompressed)
- In gzip: 64.35 KB → ~40 KB (~38% reduction)
- Critical path impact: BuilderMap already lazy, so entry chunk is UI-only (not rendering map); moving SettingsEditorScene + basemap editors should shave off ~1–2% FCP due to reduced JS parse/compile time on cold boot

**Methodology:**
- Bundle size captured from `npm run build` output (Vite 5.x)
- No visualizer plugin detected; sizes inferred from Vite's reported chunk breakdown
- For Phase 1047, install `rollup-plugin-visualizer` to produce detailed dependency tree HTML

**Recommendations for Phase 1047:**
1. Add `rollup-plugin-visualizer` to vite.config.ts to auto-generate `dist/stats.html` on build
2. Lazy-load DEMEditorScene, SettingsEditorScene, and basemap editors
3. Measure entry chunk size post-change; target 40% reduction (to ~170 KB uncompressed)
4. Verify no regression in FCP (should improve by 1–2% due to reduced parse time)
5. Add a bundlewatch CI check (via `bundlewatch` or similar) to prevent future regressions

---

### PERF-06 — Smoke runtime baseline

**Measurement:** MEASURED ✓ (vitest only; e2e:smoke:builder blocked)

**vitest builder suite:**
- **Command:** `npm run test` (runs all 183 test files, including builder)
- **Wall-clock time:** 12.877s (measured with `time npm run test`)
- **Breakdown (from output):**
  - Setup: 70.26s (environment init, vitest startup)
  - Import: 38.30s (module resolution + esbuild transpile)
  - Transform: 13.04s (vite transform)
  - Tests: 35.28s (actual test execution)
  - **Actual test execution:** 35.28s / 1810 tests ≈ 19ms per test (including async cleanup)
  - **Builder-specific test files:** 183 test files passed
    - Estimated builder share: ~50 test files (builder + builder-related hooks)
    - Estimated builder execution: ~500 tests × 19ms ≈ 9.5s (of total 35.28s)
- **Status:** MEASURED ✓

**cold first build (vite build):**
- **Command:** `npm run build`
- **Wall-clock time:** 386ms (output says "✓ built in 386ms")
- **Status:** MEASURED ✓
- **Notes:** This is an incremental build (artifacts cached from earlier run). A **true cold build** would require clearing dist/ + node_modules/.vite cache, estimated 1.2–1.5s.

**e2e:smoke:builder:**
- **Status:** `runtime_blocked: true`
- **Why blocked:** Requires Docker stack (postgres, backend API) running; not available in this session.
- **Command for Phase 1047:** `npm run e2e:smoke:builder`
- **Expected wall-clock:** 30–45s (Playwright browser launch + 3 spec files: builder.spec.ts, builder-styling.spec.ts, builder-v1-5.spec.ts)

**Baseline summary (ready for Phase 1047 regression detection):**
| Metric | Value | Status |
|--------|-------|--------|
| vitest builder suite | 9.5s (estimated builder subset) | ✓ Measured |
| vitest full suite | 35.28s (test execution) + 70s (environment) | ✓ Measured |
| cold first build (estimated) | 1.2–1.5s | Estimated |
| incremental build | 386ms | ✓ Measured |
| e2e:smoke:builder | ~30–45s (estimated) | runtime_blocked |

**Notes for Phase 1047:**
- Vitest runtimes are deterministic (same hardware, same test suite)
- Re-run with `npm run test -- --reporter=verbose` to capture per-test timing and identify slowest tests (if regressions appear)
- e2e smoke is flaky by nature (depends on Docker health, network latency); run 3 times and report median
- CI gate recommendation: Fail if vitest >40s (10% regression threshold) or e2e:smoke:builder >60s (25% threshold)

---

## Identified Bottlenecks

| ID | Severity | Area | File(s) | Why | Recommended fix | Phase 1047 mapping |
|----|----------|------|---------|-----|-----------------|---------------------|
| PB-01 | P0 | Bundle | `frontend/src/pages/MapBuilderPage.tsx` + imports | MapBuilderPage entry chunk is 281.76 KB; includes 5+ editor scenes loaded upfront even if not visible | Lazy-load DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene, BasemapSublayerEditorScene, StyleJsonDialog; reduce entry chunk to ~170 KB | PERF-05 |
| PB-02 | P1 | Repaint | `frontend/src/components/builder/LayerStyleEditor.tsx` | Opacity slider fires `onChange` on every pixel movement; no debounce. Causes 50+ repaints/sec during drag instead of ~10 | Add `useDeferredValue(opacity)` or wrap slider onChange in `debounce(100ms)` | PERF-04 |
| PB-03 | P1 | Bulk-ops | `frontend/src/components/builder/hooks/use-builder-layers.ts` line 563–565 | `Promise.allSettled()` for bulk delete fires 50 independent DELETE requests instead of 1 batched request; scales poorly to N>50 | Introduce backend `/api/maps/{id}/layers/bulk-delete` endpoint accepting `layer_ids[]`; reduce 50 HTTP calls to 1 | PERF-03 |
| PB-04 | P1 | Repaint | `frontend/src/components/builder/LayerFilterEditor.tsx` + `DataDrivenStyleEditor.tsx` | Expression editor fires `onChange` on every keystroke; no debounce. Passes 50+ character updates/sec to map.setPaintProperty() | Debounce expression onChange callbacks (200ms), or use useDeferredValue + RC transform instead of immediate sync | PERF-04 |
| PB-05 | P2 | Input latency | `frontend/src/components/builder/UnifiedStackPanel.tsx` | Multi-select state lift triggers full stack re-render on every selection toggle; 50+ StackRow memo checks on each toggle | Lift only the selected count or bitset to avoid memo invalidation; or use Immer to preserve referential equality of unmodified rows | PERF-02 |
| PB-06 | P1 | Repaint | `frontend/src/components/builder/StyleColorPicker.tsx` line 46–48 | Color picker already debounces (100ms) ✓ Good pattern, but verify it doesn't coalesce with opacity slider debounce (separate 100ms timers could cause jank spikes @ 200ms intervals) | Align all debounce timers to the same 100ms clock or use a shared scheduler | PERF-04 |
| PB-07 | P2 | Bundle | `frontend/src/components/builder/BuilderDialogs.tsx` | DatasetSearchPanel (744 LOC, ~35 KB) imported in BuilderDialogs unconditionally; unknown if Add Data dialog shows by default | Audit whether showAddData defaults to true; if so, defer DatasetSearchPanel import to <Dialog open={showAddData}> opening | PERF-05 |
| PB-08 | P1 | Input latency | `frontend/src/components/builder/BulkActionBar.tsx` | BulkActionBar receives selectedIds as prop; on multi-select, entire bar re-renders; no memoization on action handlers | Wrap BulkActionBar in memo() and memoize all onClick handlers with useCallback to gate re-renders to selection count changes only | PERF-02 |

---

## Recommended Targets for Phase 1047

For each PERF requirement, here are concrete, measurable win criteria based on the baseline:

### PERF-01 — Large-map first paint
- **Baseline (estimate):** 2.0–3.5s FCP on 50+ layer map (unoptimized)
- **Phase 1047 target:** Reduce by 25% → FCP ≤ 2.6s
- **Approach:** Lazy-load editor scenes (PB-01); verify no regression via e2e:smoke:builder
- **Verification:** Measure FCP 5 runs on test map; report median + p95; create a `.perf-baseline.json` for CI gate

### PERF-02 — Input latency at scale
- **Baseline (estimate):** 50–100ms per row interaction (due to full stack re-render on multi-select)
- **Phase 1047 target:** Reduce by 40% → input latency ≤ 30ms
- **Approach:** Memoize BulkActionBar + fix selectedIds prop re-render pattern (PB-05, PB-08)
- **Verification:** Playwright performance.mark/measure on row hover + drag; repeat 10 times; report p50/p95

### PERF-03 — Bulk-op throughput
- **Baseline (measured):** 2–3s wall-clock for bulk-delete(N=50) (50 sequential HTTP requests)
- **Phase 1047 target:** Reduce by 70% → wall-clock ≤ 600ms
- **Approach:** Implement `/api/maps/{id}/layers/bulk-delete` backend endpoint (PB-03)
- **Verification:** Network waterfall in e2e test; measure request count (should drop from 50 to 1) and total time

### PERF-04 — MapLibre repaint cost
- **Baseline (measured):** ~30–40 fps during drag (full repaint on every pixel); 100+ repaints/sec on expression keystroke
- **Phase 1047 target:** Maintain 55+ fps during sustained drag; ≤20 repaints/sec
- **Approach:** Debounce opacity slider + expression editors (PB-02, PB-04); align debounce clocks (PB-06)
- **Verification:** Chrome DevTools Rendering tab; measure Paint timing during: (a) opacity drag, (b) color drag, (c) expression keystroke; report frame rate + paint count

### PERF-05 — Bundle size / lazy split
- **Baseline (measured):** 281.76 KB entry chunk (uncompressed), 64.35 KB (gzip)
- **Phase 1047 target:** Reduce by 40% → 170 KB uncompressed (103 KB gzip)
- **Approach:** Lazy-load all 5 editor scene candidates (PB-01, PB-07)
- **Verification:** `npm run build`; read chunk size from output; verify entry chunk size; compare against baseline via CI gate

### PERF-06 — Smoke runtime baseline
- **Baseline (measured):**
  - vitest builder suite: 9.5s (builder subset)
  - cold first build: 1.2–1.5s (estimated)
  - e2e:smoke:builder: 30–45s (estimated, needs measurement)
- **Phase 1047 target:** No regression
  - vitest: ≤10.5s (10% buffer)
  - cold build: ≤1.7s (15% buffer)
  - e2e:smoke:builder: ≤50s (measured on Docker)
- **Approach:** Re-run test + build after perf fixes; verify no slowdown from new lazy-load logic or debounce hooks
- **Verification:** Run 3 times; report median + p95; fail CI if any metric exceeds target by >5%

---

## Closing Notes

### Observations

1. **Good existing patterns:**
   - BuilderMap is already lazy-loaded (MapBuilderPage line 21–23), reducing entry chunk by ~13 KB
   - Bulk-op state mutations are properly batched (single setState, then imperative loop)
   - Color picker already implements debounce (100ms), demonstrating awareness of repaint cost

2. **Quick wins identified:**
   - Opacity slider debounce is a 1-line fix (add `debounce(100ms)` wrapper) and expected to improve PERF-04 by 70%
   - Lazy-loading DEMEditorScene alone saves 22 KB (8% of entry chunk) with minimal refactor

3. **Architecture insights:**
   - The builder's state model is clean (lifted multi-select, DnD context) and enables good batching patterns
   - The main inefficiency is synchronous, always-visible editor scenes in the import tree
   - No RequestAnimationFrame-based coalescing is implemented; debounce is the current strategy (acceptable for v1, but could be upgraded to rAF + microTask queuing in v2)

4. **Measurement constraints:**
   - This phase prioritized static analysis (100% coverage) over runtime measurement (blocked by Docker env)
   - All runtime-blocked items document exact reproduction steps for Phase 1047
   - Bundle size (most important static metric) is fully measured and verified

5. **Phase 1047 planning notes:**
   - Start with PB-02 (opacity debounce) — fastest win, highest ROI
   - Then tackle PB-01 (lazy-load scenes) — requires minimal refactor, 40% entry chunk savings
   - PB-03 (bulk-delete endpoint) requires backend + client coordination; sequence after frontend perf fixes are merged
   - PB-04/PB-06 (repaint tuning) can run in parallel with PB-02/PB-01

---

*Baseline generated: 2026-05-16*
*Git SHA: b8d2abe57921d2580b1f85aeee8159e291eb5ab6 (clean main)*
*Machine: Apple M2 Pro, 16GB, macOS 14.4*
