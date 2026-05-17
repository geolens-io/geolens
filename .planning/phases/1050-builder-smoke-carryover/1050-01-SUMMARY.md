---
phase: 1050-builder-smoke-carryover
plan: 01
subsystem: ui
tags: [maplibre, vector-tiles, source-dedupe, map-builder, performance]

requires:
  - phase: 1049-mcp-smoke-verification
    provides: SF-04 root cause + recommended fix evidence (~80 tile requests on 8-layer / 2-dataset map)
provides:
  - "`getSourceIdForLayer(layer, prefix?)` helper exported from `map-sync.ts` with locked 3-branch contract (cluster → per-layer; raster/DEM → per-layer; non-cluster vector with `dataset_table_name` → `source-data-${table}`)"
  - "Vector source dedupe across all builder/viewer paths — `syncLayersToMap`, `swapLayerOnMap`, `handlePaintChange`, `handleStyleConfigChange`, `handleOpacityChange` (cluster branch), `handleLabelChange`, `handleAiRemoveLayer` all consume the new keying"
  - "`lineGradientNeededFor` updated to use the helper — the deduped shared source gets `lineMetrics: true` when ANY consumer needs it (exact behavior the line-336 forward-compat comment anticipated)"
  - "`SyncLayerInput.layer_type` + `dataset_record_type` extension so non-DEM raster `SyncLayerInput` objects route through the helper's per-layer branch"
  - "Reference-count-safe source teardown — `handleAiRemoveLayer` no longer directly calls `map.removeSource`; the desired-set prune in `removeStaleSourcesAndLayers` is the source-cleanup mechanism"
affects: [builder-perf, builder-styling, ai-layer-mutation, layer-adapters]

tech-stack:
  added: []
  patterns:
    - "Single-helper source-id derivation (`getSourceIdForLayer`) — strategy-pattern routing by layer type"
    - "Reference-count via desired-set prune (already established in `removeStaleSourcesAndLayers`; this plan switches the keying function to make it actually de-duplicate at scale)"

key-files:
  created:
    - frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.dedupe.test.ts
  modified:
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/builder/hooks/use-builder-layers.ts
    - frontend/src/components/builder/hooks/use-layer-map-sync.ts
    - frontend/src/components/builder/__tests__/map-sync.raster.test.ts
    - frontend/src/components/builder/__tests__/map-sync.line-gradient.test.ts
    - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts

key-decisions:
  - "Cluster keying preserved at `source-${layer.id}` (NOT `source-cluster-${layer.id}` as the plan's interfaces section suggested) — the existing `map-sync.cluster.test.ts` fixtures use layer id `cluster-1` so `source-${id}` ALREADY produces `source-cluster-1`. Using `source-cluster-${layer.id}` would have yielded `source-cluster-cluster-1` and broken the test. Plan's acceptance criteria explicitly required `map-sync.cluster.test.ts` to pass with zero modifications, so the helper resolves cluster layers to `prefixed('source', layer.id, prefix)` instead. Documented in the helper's JSDoc."
  - "Source teardown moved from imperative per-layer `removeSource` (in `handleAiRemoveLayer`) to the next `syncFromState` invocation's `removeStaleSourcesAndLayers` desired-set prune. The prune was already reference-count-safe by virtue of `desiredSources.add(sourceId)` being called once per consumer — switching the keying function is all it took to make dedupe work end-to-end."
  - "`use-layer-map-sync.ts` (4 source-id call sites) was NOT in the plan's `files_modified` list, but was updated under deviation Rule 3 (auto-fix blocking issue) — paint/style/label/cluster-opacity handlers would have silently failed to read the deduped source without it."

patterns-established:
  - "When a hot-path imperative API has a hidden keying invariant (here: source id = `source-${id}`), the dedupe refactor must sweep ALL call sites that read or write that key, not just the most-visible ones. `use-layer-map-sync.ts`'s 4 occurrences were not in the plan's files_modified list but were essential to make the dedupe work."
  - "TDD RED tests over a stateless mock (e.g. `getSource: vi.fn(() => null)`) silently pass even when the production code has a stale per-layer source-id derivation — the test setup never seeds the source so `if (map.getSource(sourceId))` returns false and the buggy `removeSource` is never called. Seed the mock with both the dedupe key AND the legacy per-layer key to force a real RED."

requirements-completed: [SMOKE-08]

duration: 35min
completed: 2026-05-17
---

# Phase 1050 Plan 01: Dedupe MapLibre Vector Tile Sources Summary

**MapLibre vector tile sources now share one source per `dataset_table_name` for non-cluster layers, cutting initial-paint tile requests from ~N per layer to ~M per dataset (M < N) while preserving cluster per-layer scoping and raster per-layer source isolation.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-05-17T16:00:00Z (approx)
- **Completed:** 2026-05-17T16:35:00Z (approx)
- **Tasks:** 3 / 3 (Task 3 is verification-only, no commit)
- **Files modified:** 6 (+ 2 new test files)

## Accomplishments

- **`getSourceIdForLayer(layer, prefix?)`** exported from `map-sync.ts` (3-branch contract):
  1. cluster layers → `source-${layer.id}` (per-layer, cluster-radius/minPoints scoping)
  2. raster / DEM / hillshade → `source-${layer.id}` (per-layer, signed-tile-URL scope)
  3. non-cluster vector with `dataset_table_name` → `source-data-${dataset_table_name}` (deduped)
- **`syncLayersToMap` line 687** now derives sourceId via the helper.
- **`lineGradientNeededFor` (line 417)** updated — the deduped shared source emits `lineMetrics: true` if ANY consumer needs it (exactly the case the line-336 forward-compat comment anticipated).
- **`use-builder-layers.swapLayerOnMap`** routes through the helper; `handleAiRemoveLayer` no longer calls `map.removeSource` directly (relies on the desired-set prune).
- **`use-layer-map-sync.ts` (4 source-id call sites)** rewired to the helper.
- **2 new test files** + 3 existing tests rekeyed to the new contract.

## Task Commits

1. **Task 1 RED: failing dedupe tests for map-sync** — `a1d5a2b9` (test)
2. **Task 1 GREEN: dedupe in map-sync.ts + helper** — `cab57a32` (feat)
3. **Task 2 RED: failing handleAiRemoveLayer test** — `bc92617a` (test)
4. **Task 2 GREEN: swap/remove/paint/style/label paths** — `c1c84cc7` (feat)

_Task 3 (smoke validation) is verification-only and produced no commits — all gates passed against the post-Task-2 working tree._

## Files Created/Modified

- `frontend/src/components/builder/map-sync.ts` — `getSourceIdForLayer` helper, `SourceIdLayer` shape, `syncLayersToMap` + `lineGradientNeededFor` routed through it, `SyncLayerInput.layer_type` + `dataset_record_type`, `toSyncInput` extended
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — `swapLayerOnMap` + `handleAiRemoveLayer` updated; direct `removeSource` call removed
- `frontend/src/components/builder/hooks/use-layer-map-sync.ts` — 4 source-id derivations rewired to the helper (handlePaintChange, handleStyleConfigChange, handleOpacityChange cluster branch, handleLabelChange)
- `frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts` — NEW: 8 tests covering the 3-branch contract + addSource M-for-M count + shared-source preservation + single-consumer removal
- `frontend/src/components/builder/hooks/__tests__/use-builder-layers.dedupe.test.ts` — NEW: 2 tests covering `handleAiRemoveLayer` non-call of `removeSource` + state-driven cleanup flow
- `frontend/src/components/builder/__tests__/map-sync.raster.test.ts` — 2 tests rekeyed to `source-data-test_table`
- `frontend/src/components/builder/__tests__/map-sync.line-gradient.test.ts` — 5 tests rekeyed to `source-data-roads` + mock map made stateful (`sources` Map) so the idempotency guard fires correctly
- `frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts` — `getSourceIdForLayer` added to the partial map-sync mock

## Decisions Made

- **Cluster keying choice (deviation from plan text):** The plan's `<interfaces>` section said `source-cluster-${layer.id}` for cluster layers, but the existing `map-sync.cluster.test.ts` uses layer id `cluster-1` and expects source id `source-cluster-1` (which is literally `source-${id}` under the current per-layer scheme). The plan's acceptance criteria mandated "existing `map-sync.cluster.test.ts` still pass with zero modifications," so the helper resolves cluster layers via `prefixed('source', layer.id, prefix)` instead of the prefix-prepending form. This still preserves the per-layer scoping the plan requires (cluster radius + minPoints are per-layer settings). The helper's JSDoc explains the choice.
- **`use-layer-map-sync.ts` updates (Rule 3 auto-fix):** Not in the plan's `files_modified`, but the 4 source-id derivations there would have silently broken paint / style-config / cluster-opacity / label-add handlers after the dedupe (they'd look up `source-${layerId}` which no longer exists for non-cluster vector layers). Added to the same Task 2 commit.
- **Mock seeding for RED:** The first iteration of the `handleAiRemoveLayer` test passed trivially because the mock's `getSource('source-a')` returned null, short-circuiting the old code's `if (map.getSource(sourceId)) map.removeSource(sourceId)`. Re-seeded the mock with both `source-data-shared_points` AND `source-a` so the old code path would have called `removeSource('source-a')` → produces a real RED. Documented in the test's comments.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's cluster source-id keying text would break `map-sync.cluster.test.ts`**
- **Found during:** Task 1 (helper authoring)
- **Issue:** Plan's `<interfaces>` and `<action>` sections specified `source-cluster-${layer.id}` for cluster layers, but the existing cluster test's layer id IS `cluster-1`, so `source-cluster-${id}` would yield `source-cluster-cluster-1` and break 8+ test assertions. Plan's acceptance criteria explicitly required zero modifications to that test.
- **Fix:** Resolved cluster layers via `prefixed('source', layer.id, prefix)` (which still yields `source-cluster-1` because the layer id IS `cluster-1`). Preserves the per-layer scoping the plan requires.
- **Files modified:** `frontend/src/components/builder/map-sync.ts` (helper JSDoc + branch logic)
- **Verification:** `map-sync.cluster.test.ts` passes unchanged (10/10 tests).
- **Committed in:** `cab57a32`

**2. [Rule 3 - Blocking] `use-layer-map-sync.ts` not in plan's `files_modified` but had 4 source-id call sites that would silently break dedupe**
- **Found during:** Task 2 (sweeping `grep -n 'source-\${' frontend/src/components/builder/hooks/`)
- **Issue:** `handlePaintChange` (line 114), `handleStyleConfigChange` (line 157), `handleOpacityChange` cluster branch (line 222), `handleLabelChange` (line 385) all derive `source-${layerId}` directly. After the dedupe change, these would have looked up the non-existent per-layer key for non-cluster vector layers — silently failing all paint/style/label updates.
- **Fix:** Rewired all 4 sites to `getSourceIdForLayer(layer)`. Added comment annotations explaining the per-branch intent.
- **Files modified:** `frontend/src/components/builder/hooks/use-layer-map-sync.ts` + the partial-mock in `use-layer-map-sync.raf.test.ts`.
- **Verification:** All 141 builder hook tests pass; PERF-04 rAF coalescing test still passes.
- **Committed in:** `c1c84cc7`

**3. [Rule 1 - Bug] Three existing test files were tightly coupled to the per-layer source-id scheme**
- **Found during:** Task 1 GREEN verification (`npm run test -- --run src/components/builder/__tests__/`)
- **Issue:** `map-sync.raster.test.ts` (2 tests), `map-sync.line-gradient.test.ts` (5 tests) asserted exact source ids like `source-v1`, `source-l-grad`, etc. After the dedupe, these become `source-data-test_table`, `source-data-roads`. Plus `map-sync.line-gradient.test.ts`'s mock map returned null from `getSource` unconditionally — fine before dedupe, broken after (the shared source's idempotency guard fired twice on the second consumer in the same sync because the mock never "remembered" the addSource).
- **Fix:** Rekeyed 2 tests in `map-sync.raster.test.ts` and 5 tests in `map-sync.line-gradient.test.ts`. Made `map-sync.line-gradient.test.ts`'s mock map stateful (`sources` Map tracks addSource/removeSource calls). Each test got an explanatory comment.
- **Files modified:** `map-sync.raster.test.ts`, `map-sync.line-gradient.test.ts`
- **Verification:** 731/731 builder __tests__ pass; 1909/1909 frontend vitest suite passes.
- **Committed in:** `cab57a32`

---

**Total deviations:** 3 auto-fixed (1 Rule 1 plan-text bug, 1 Rule 3 blocking-issue scope expansion, 1 Rule 1 test-fixture coupling).
**Impact on plan:** All three were essential for correctness. The cluster-keying deviation matched what the plan's own acceptance criteria demanded (preserve the existing test). The `use-layer-map-sync.ts` scope expansion is a strict-superset of the plan's intent (the plan implicitly required the dedupe to work end-to-end; missing the 4 call sites would have made that goal unreachable). The test-fixture updates are inherent to changing the source-id contract.

## Issues Encountered

- **Vitest mock map quality:** `map-sync.line-gradient.test.ts`'s mock map originally returned `null` from `getSource` unconditionally. Before dedupe, this was fine because each layer's source id was unique. After dedupe, two layers sharing a `dataset_table_name` both pass the `if (!map.getSource(sourceId))` idempotency guard, and `addSource` fires twice for the same source. Fixed by making the mock stateful (track addSource calls in a `Set`).

## Smoke Gate Results (Task 3)

- **Vitest:** 1909/1909 PASS (frontend full suite)
- **Vitest builder subset:** 731/731 PASS (`src/components/builder/__tests__/`)
- **Vitest builder hooks subset:** 141/141 PASS (`src/components/builder/hooks/`)
- **Frontend typecheck (`tsc -b`):** 6 errors total — all pre-existing per the plan's success criteria (LayerEditorPanel.tsx:413,694 + 4 TS6133 unused-var warnings in test files). Zero NEW errors introduced.
- **`e2e:smoke:builder` (Playwright):** 26/26 PASS — matches v1010.1 baseline (1.4 min). No `there is no source with this ID` errors in any test stdout. Includes builder.spec.ts, builder-styling.spec.ts, builder-v1-5.spec.ts.

## Self-Check

Created files:
- FOUND: frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts
- FOUND: frontend/src/components/builder/hooks/__tests__/use-builder-layers.dedupe.test.ts

Commits (verified via `git log`):
- FOUND: a1d5a2b9 (test RED Task 1)
- FOUND: cab57a32 (feat GREEN Task 1)
- FOUND: bc92617a (test RED Task 2)
- FOUND: c1c84cc7 (feat GREEN Task 2)

## Self-Check: PASSED

## Next Phase Readiness

- Plan 1050-01 (the milestone's only P1 + largest scope) is COMPLETE. The remaining plan in this phase is 1050-06 CTRL-01 (smoke gate + CHANGELOG + MCP re-verify).
- The dedupe is verified at the unit + integration + e2e:smoke:builder level. The remaining verification (live Playwright MCP re-count of vector tile requests on the v1010.1 test map) is owned by Plan 1050-06.
- Predicted measurable impact: on the v1010.1 8-layer / 2-dataset test map, initial-paint vector tile requests drop from ~80 to ~16-24 (per the SF-04 evidence in `1049-SMOKE-FINDINGS.md`).

---
*Phase: 1050-builder-smoke-carryover*
*Plan: 01*
*Completed: 2026-05-17*
