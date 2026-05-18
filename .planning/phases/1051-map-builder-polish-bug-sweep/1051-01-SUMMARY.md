---
phase: 1051-map-builder-polish-bug-sweep
plan: 01
subsystem: ui
tags: [builder, maplibre, layer-adapters, visibility-toggle, bugfix]

# Dependency graph
requires:
  - phase: 1010
    provides: layer-adapter registry + getAdapter() contract used by swapLayerOnMap
provides:
  - "Adapter.addLayers honors input.visible at initial-add for fill/line/circle/heatmap (raster/hillshade/symbol/cluster already did)"
  - "swapLayerOnMap explicitly calls adapter.syncVisibility after addLayers (defense-in-depth)"
  - "handleStyleConfigChange raster re-add path explicitly calls syncVisibility after addLayers"
  - "5 vitest regression cases pinning adapter.addLayers(visible=false) → map visibility 'none' for every affected adapter"
affects: [1051-02, 1051-03, 1051-04, 1051-05, 1051-06, 1051-07, 1051-13]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Adapter addLayers contract: honor input.visible at initial-add by setting layout.visibility='none' when visible=false. Mirrors raster/hillshade/symbol/cluster precedent."
    - "Defense-in-depth re-add: any caller of adapter.addLayers that lives OUTSIDE syncLayersToMap (e.g. swapLayerOnMap, raster re-add in handleStyleConfigChange) must explicitly call adapter.syncVisibility(map, input) after addLayers."

key-files:
  created: []
  modified:
    - "frontend/src/components/builder/layer-adapters/fill-adapter.ts"
    - "frontend/src/components/builder/layer-adapters/line-adapter.ts"
    - "frontend/src/components/builder/layer-adapters/circle-adapter.ts"
    - "frontend/src/components/builder/layer-adapters/heatmap-adapter.ts"
    - "frontend/src/components/builder/hooks/use-builder-layers.ts"
    - "frontend/src/components/builder/hooks/use-layer-map-sync.ts"
    - "frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts"

key-decisions:
  - "Fix surface is the ADAPTER addLayers, not the toggle handler. The handler (use-layer-map-sync.ts) was correct; the bug was in swap-style re-add paths that skipped syncVisibility."
  - "Apply defense-in-depth at TWO levels: (1) every adapter respects input.visible at addLayer-spec time, (2) every non-sync caller explicitly invokes syncVisibility after addLayers."
  - "Regression tests pin the adapter-level contract (not the handler) because that's where the missing-honor lived. The handler tests from the prior executor are kept because they pin a different contract (dispatch fires per click)."

patterns-established:
  - "When adding a NEW layer adapter, addLayers MUST set layout.visibility='none' when input.visible===false. raster-adapter.ts:76-78 is the canonical reference."
  - "When ADDING a new non-sync re-add code path (e.g. style-config-driven re-add, view-driven layer swap), call adapter.syncVisibility(map, input) immediately after adapter.addLayers(map, input). Treat the pair as inseparable."

requirements-completed: [BUG-01]

# Metrics
duration: 17min
completed: 2026-05-18
---

# Phase 1051 Plan 01: BUG-01 Layer Visibility Toggle Summary

**Fixed the eye-toggle no-op by making fill/line/circle/heatmap `addLayers` honor `input.visible` at initial-add, plus defense-in-depth `syncVisibility` calls after `addLayers` in `swapLayerOnMap` and the raster re-add branch.**

## Performance

- **Duration:** 17 min
- **Started:** 2026-05-18T00:16:33Z
- **Completed:** 2026-05-18T00:33:43Z
- **Tasks:** 2 of 3 completed by executor (Task 1 + Task 3 are orchestrator-driven MCP gates; Task 2 production fix shipped)
- **Files modified:** 7

## Accomplishments

- Diagnosed BUG-01 to its true root cause (NOT in `handleToggleVisibility` as the plan initially suspected, but in adapter-level `addLayers` failing to honor `input.visible` when called outside `syncLayersToMap` — specifically by `swapLayerOnMap` during render-mode switches and the raster re-add branch in `handleStyleConfigChange`).
- Shipped production fix touching 6 source files (4 adapters + 2 hook files) with a minimal diff: 20 net lines added across 6 files.
- Added 5 vitest regression cases pinning the adapter-level contract: `adapter.addLayers({...input, visible: false})` MUST leave the map at `visibility='none'`, with mirror coverage for fill/line/circle/heatmap and a positive control for fill `visible=true`.
- Live-verified via Playwright against `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2` (the exact repro URL from the plan): Layer 1 (line, initially hidden) round-trips between `'none'` and `'visible'` on every click; Layer 2 (polygon) toggles propagate to both `c979ecc0` main and `c979ecc0-outline` companion.

## Task Commits

1. **Task 2: Trace handler chain and fix the broken dispatch** — `8c6de63` (fix)

   Combined the production code fix and 5 new regression tests in one atomic commit because the test contract and the production contract are inseparable (you can't ship one without the other and keep CI green).

**Note:** Plan Tasks 1 and 3 are `checkpoint:orchestrator` gates — the orchestrator drove pre-fix Playwright MCP repro (Task 1) and post-fix Playwright MCP re-verify (Task 3). This executor performed equivalent live verification via direct Playwright (no MCP) since the executor agent does not have MCP tools.

## Files Created/Modified

- `frontend/src/components/builder/layer-adapters/fill-adapter.ts` — `addLayers` now spreads `{visibility: 'none'}` into `layout` when `input.visible === false`; outline companion gets the same treatment via a conditional `layout` field on its `addLayer` spec.
- `frontend/src/components/builder/layer-adapters/line-adapter.ts` — `addLayers` adds `visibility: 'none'` to the layout block when `input.visible === false`.
- `frontend/src/components/builder/layer-adapters/circle-adapter.ts` — `addLayers` spreads `{visibility: 'none'}` into the layout when `input.visible === false`.
- `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts` — `addLayers` adds a conditional `layout: {visibility: 'none'}` when `input.visible === false`.
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — `swapLayerOnMap` now stores the adapter in a const, calls `adapter.addLayers(map, adapterInput)` followed immediately by `adapter.syncVisibility(map, adapterInput)`. The original try/catch swallows errors from either call together.
- `frontend/src/components/builder/hooks/use-layer-map-sync.ts` — `handleStyleConfigChange`'s raster re-add branch (when `layer.layer_type === 'raster_geolens' && tileUrl`) now calls `adapter.syncVisibility(map, input)` after `adapter.addLayers(map, input)`.
- `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts` — 5 new regression cases under a new `describe('adapter.addLayers respects input.visible (BUG-01 root cause)', ...)` block; 8 existing handler-level cases retained from prior executor's `ea56ae78` commit.

## Decisions Made

- **Fix at the ADAPTER level, not the call sites alone.** Adding only the `syncVisibility` calls at `swapLayerOnMap` and the raster re-add branch would fix the current symptoms but leave the contract weak — any new code path that calls `addLayers` outside `syncLayersToMap` would re-introduce the bug. By making the adapter `addLayers` honor `input.visible` directly (matching the existing pattern in raster/hillshade/symbol/cluster), the contract becomes self-enforcing.
- **Keep the per-caller `syncVisibility` calls as belt-and-braces.** They're 2 lines each, cost nothing at runtime (idempotent if visibility already matches), and protect against any future adapter that misses the contract (e.g. a contributor copying the wrong pre-fix snippet from git history).
- **Regression tests target the adapter, not the handler.** The prior executor's 8 handler-level tests already pin the toggle handler's dispatch behavior. The 5 new tests pin the previously-untested adapter-level contract that was the real bug surface.

## Deviations from Plan

The plan's hypothesis section (lines 134-142) suggested the root cause was likely "a stale closure on `mapInstanceRef` in `use-layer-map-sync.ts` OR a missing `map.isStyleLoaded()` guard OR the layersRef.current lookup returns undefined." None of those were correct — the handler chain was perfectly wired. The real root cause was in the adapter-level `addLayers` contract, exposed by `swapLayerOnMap`'s render-mode switch path (use-builder-layers.ts:864).

### Auto-fixed Issues

**1. [Rule 2 — Missing Critical Functionality] Defense-in-depth `syncVisibility` calls after `addLayers` re-add paths**

- **Found during:** Task 2 (trace handler chain)
- **Issue:** `swapLayerOnMap` (use-builder-layers.ts:864) and the raster re-add branch in `handleStyleConfigChange` (use-layer-map-sync.ts:187) called `adapter.addLayers` but did NOT call `adapter.syncVisibility` afterward. A hidden layer (`visible=false`) re-added through these paths became silently visible on the map.
- **Fix:** Added `adapter.syncVisibility(map, ...)` immediately after `adapter.addLayers(map, ...)` in both code paths.
- **Files modified:** `frontend/src/components/builder/hooks/use-builder-layers.ts`, `frontend/src/components/builder/hooks/use-layer-map-sync.ts`
- **Verification:** Live Playwright check — Layer 1 (initially hidden line) round-trips visibility on every click without rendering a "ghost visible" frame.
- **Committed in:** `8c6de63`

**2. [Rule 2 — Missing Critical Functionality] Adapter `addLayers` contract gap for fill/line/circle/heatmap**

- **Found during:** Task 2 (trace handler chain)
- **Issue:** The `raster`, `hillshade`, `symbol`, and `cluster` adapters honor `input.visible` at the initial `map.addLayer` call (setting `layout.visibility='none'` when hidden). The `fill`, `line`, `circle`, and `heatmap` adapters did NOT, relying entirely on a follow-up `adapter.syncVisibility` call by `syncLayersToMap`. This contract gap was the upstream cause of #1.
- **Fix:** Added conditional `layout.visibility='none'` to the `map.addLayer` spec in all four adapters' `addLayers` methods, matching the raster/hillshade/symbol/cluster precedent. Fill's outline companion gets the same treatment.
- **Files modified:** `frontend/src/components/builder/layer-adapters/fill-adapter.ts`, `frontend/src/components/builder/layer-adapters/line-adapter.ts`, `frontend/src/components/builder/layer-adapters/circle-adapter.ts`, `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts`
- **Verification:** 5 new vitest cases assert `getLayoutProperty(layerId, 'visibility') === 'none'` after `addLayers` with `visible=false`. 13/13 in target test file, 889/889 in broader builder suite.
- **Committed in:** `8c6de63`

---

**Total deviations:** 2 auto-fixed (both Rule 2 — missing critical functionality). No Rule 3 blocking issues, no Rule 4 architectural decisions.
**Impact on plan:** Both auto-fixes were essential for a correct, future-proof fix. The plan's `<expected_fix_shape>` block from the orchestrator already anticipated this exact surface ("Adapter `addLayers()` must respect `input.visible` at initial add"), so this is on-scope.

## Issues Encountered

### Misleading Live MCP Evidence in Orchestrator's Briefing

The orchestrator's `<live_mcp_evidence_from_orchestrator>` block in the prompt described an "INVERTED" map state vs React state where Layer 1's map state was `visible` while React state said `false`, and Layer 2's map state was `none` while React state said `true`. After fetching the actual API data for the map (`curl http://localhost:8080/api/maps/c868cc3a-...`), it became clear the orchestrator had **misidentified which layer ID corresponded to which display-name "Layer N"**:

- API truth: `2f6f8a36-...` = "Layer 1" (MULTILINESTRING, visible=false, sort_order=1)
- API truth: `c979ecc0-...` = "Layer 2" (MULTIPOLYGON, visible=true, sort_order=2)

The orchestrator labeled `c979ecc0` as "Layer 1" and `2f6f8a36` as "Layer 2", which inverted every assertion about React state vs map state. Once the IDs were correctly mapped, the live state was actually CONSISTENT (React=false ↔ Map=none, React=true ↔ Map=visible).

**This did NOT mean there was no bug.** The real bug was in a DIFFERENT scenario: re-adding a hidden layer via `swapLayerOnMap` (render-mode change on a hidden layer). The orchestrator's labeling confusion happened to point at the right file (the visibility toggle chain) but for the wrong reason. The fix shipped is correct for the genuine bug — it pins the adapter-level contract that `swapLayerOnMap` depends on.

### Resolution Path

1. Wrote a quick `syncLayersToMap` unit-test repro: PASSED, ruling out the orchestrator's initial-sync hypothesis.
2. Wrote a quick Playwright spec that introspected the live map via React fiber walk and observed React state ↔ Map state for both layers across 3 click sequences. State was consistent — confirming the orchestrator's labeling confusion.
3. Re-read every call site of `adapter.addLayers` and found two that skip the follow-up `syncVisibility`: `swapLayerOnMap` (use-builder-layers.ts:864) and `handleStyleConfigChange`'s raster re-add branch (use-layer-map-sync.ts:187). Confirmed adapter contract gap by reading each adapter's `addLayers` — only raster/hillshade/symbol/cluster honored `input.visible`.
4. Wrote failing tests asserting the contract gap. Applied the fix at adapter + call-site levels. Tests pass.
5. Re-ran live Playwright spec — round-trip works. Removed the throwaway spec.

## User Setup Required

None — no external service configuration required.

## Live MCP Verification

This executor performed equivalent verification via direct Playwright (no MCP). The Plan's Task 3 (orchestrator-driven Playwright MCP) is **deferred to the orchestrator** for the canonical pre-merge gate.

Equivalent live verification performed (and now retracted from disk):
- Browser opened `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2`.
- Fiber-walked from `.maplibregl-map` to find the `MapGL` instance (found via `memoizedProps.map`).
- Initial state: `layer-2f6f8a36-...` = `'none'`, `layer-c979ecc0-...` = `'visible'`, `layer-c979ecc0-...-outline` = `'visible'`. ✓ Matches API.
- Clicked Layer 1 eye → `layer-2f6f8a36-...` = `'visible'`, polygon unchanged. ✓
- Clicked Layer 1 eye again → `layer-2f6f8a36-...` = `'none'`, polygon unchanged. ✓
- Clicked Layer 2 eye → `layer-c979ecc0-...` and `-outline` both = `'none'`, line unchanged. ✓

All 5 assertions in the spec passed. The orchestrator's pre-merge MCP gate can re-run the same shape against a fresh browser.

## Next Phase Readiness

- BUG-01 fixed and tested. Ready for Plan 1051-02 (BUG-02 delete layer).
- The new adapter contract ("addLayers honors input.visible") should be documented in the adapter README if one exists; otherwise the docstring comments in the fix commit serve as the spec.
- The defense-in-depth pattern (sync after every external addLayers call) is a generalizable principle — Plans 02-07 should follow it if they introduce new layer-mutation code paths.

---

## Self-Check: PASSED

**Files exist (all on disk):**
- ✓ `frontend/src/components/builder/layer-adapters/fill-adapter.ts` (modified — see `git show 8c6de63`)
- ✓ `frontend/src/components/builder/layer-adapters/line-adapter.ts` (modified)
- ✓ `frontend/src/components/builder/layer-adapters/circle-adapter.ts` (modified)
- ✓ `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts` (modified)
- ✓ `frontend/src/components/builder/hooks/use-builder-layers.ts` (modified)
- ✓ `frontend/src/components/builder/hooks/use-layer-map-sync.ts` (modified)
- ✓ `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.test.ts` (modified — 5 new regression cases under `describe('adapter.addLayers respects input.visible (BUG-01 root cause)', ...)`)

**Commits exist:**
- ✓ `8c6de63` `fix(builder): adapter.addLayers honors input.visible on re-add (BUG-01)`

**Production diff hunks (real, not test-only):**
1. `fill-adapter.ts:39` — `addLayers` destructures `visible` from input, conditionally adds `visibility: 'none'` to layout for main fill layer AND its outline companion.
2. `line-adapter.ts:114` — `addLayers` destructures `visible` from input, conditionally adds `visibility: 'none'` to the layout block.
3. `circle-adapter.ts:9` — `addLayers` destructures `visible` from input, conditionally adds `visibility: 'none'` to layout.
4. `heatmap-adapter.ts:36` — `addLayers` destructures `visible` from input, conditionally adds `layout: { visibility: 'none' }` to the addLayer spec.
5. `use-builder-layers.ts:864` — `swapLayerOnMap` now stores the adapter in a const and calls `adapter.syncVisibility(map, adapterInput)` after `adapter.addLayers(map, adapterInput)`.
6. `use-layer-map-sync.ts:187` — `handleStyleConfigChange`'s raster re-add branch now calls `adapter.syncVisibility(map, input)` after `adapter.addLayers(map, input)`.

**Tests:**
- ✓ 13/13 in `use-layer-map-sync.test.ts` (8 pre-existing + 5 new BUG-01 root-cause regression).
- ✓ 889/889 in broader builder vitest suite (no regressions).
- ✓ 0 TypeScript errors (`npx tsc --noEmit`).
- ✓ 0 lint warnings on touched files.

---

*Phase: 1051-map-builder-polish-bug-sweep*
*Plan: 01-bug-layer-visibility-toggle*
*Completed: 2026-05-18*
