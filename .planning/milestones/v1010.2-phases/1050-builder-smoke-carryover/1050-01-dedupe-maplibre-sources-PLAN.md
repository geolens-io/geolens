---
phase: 1050-builder-smoke-carryover
plan: 01
type: execute
wave: 2
depends_on: [1050-02, 1050-03, 1050-04, 1050-05]
files_modified:
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts
autonomous: true
requirements: [SMOKE-08]

must_haves:
  truths:
    - "Opening a saved map with N layers backed by M unique datasets (M < N) fires ~M unique tile URLs at initial paint, not N copies of the same URL"
    - "map.getSource(sourceId) returns the same Source instance for every non-cluster layer sharing a dataset_table_name"
    - "Toggling a layer's visibility on/off does not call removeSource if another layer still references that source"
    - "Cluster layers continue to render correctly — cluster-source.ts per-layer scoping preserved"
    - "Saved-map round-trip is clean — open, save, re-open the test map and the layer stack + style JSON match the pre-fix snapshot"
  artifacts:
    - path: "frontend/src/components/builder/map-sync.ts"
      provides: "Vector source dedupe via per-dataset keying for non-cluster layers"
      contains: "getSourceIdForLayer"
    - path: "frontend/src/components/builder/hooks/use-builder-layers.ts"
      provides: "swapLayerOnMap + handleAiRemoveLayer updated to derive sourceId via the same keying contract"
      contains: "getSourceIdForLayer"
    - path: "frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts"
      provides: "Assertion that addSource is called M times for M datasets, not N times for N layers"
      contains: "addSource.*toHaveBeenCalledTimes"
  key_links:
    - from: "map-sync.ts:syncVectorLayer"
      to: "getSourceIdForLayer(layer)"
      via: "source id derivation"
      pattern: "getSourceIdForLayer"
    - from: "use-builder-layers.ts:swapLayerOnMap"
      to: "getSourceIdForLayer(layer)"
      via: "source id derivation"
      pattern: "getSourceIdForLayer"
    - from: "use-builder-layers.ts:handleAiRemoveLayer"
      to: "desired-set prune via map-sync"
      via: "trigger resync rather than direct removeSource"
      pattern: "removeSource|syncFromState"
---

<objective>
Map Builder reuses ONE MapLibre vector source per unique `dataset_table_name` across all non-cluster layers that share it. Closes SF-04 / `BUILDER-PERF-DEDUPE-SOURCES` — the only P1 in v1010.2 and the largest scope plan.

Purpose: Eliminate the ~80 vector tile requests fired at initial paint of the v1010.1 test map (8 layers, 2 datasets) — the same MVT path + same signed token is currently fetched 4–5 times per dataset because each layer registers its own MapLibre source. Per SF-04 evidence (requests 299–394 in `01-A-02-builder-loaded`), this is identical `sig=...` and tile coords repeated per duplicate-source layer. Target ≤ ~24 vector tile requests at initial paint.

Output:
- `frontend/src/components/builder/map-sync.ts` — new `getSourceIdForLayer(layer)` helper that returns `source-cluster-${layer.id}` for cluster layers and `source-data-${dataset_table_name}` for non-cluster vector layers; `syncVectorLayer` + `removeStaleSourcesAndLayers` use the new key
- `frontend/src/components/builder/hooks/use-builder-layers.ts` — `swapLayerOnMap` (line 760-783) + `handleAiRemoveLayer` (line 737) updated to derive sourceId via the same helper; per-layer direct `removeSource` calls replaced with a state-driven resync where any other layer still references the dataset
- `frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts` — new test asserting `addSource` is called M times for M datasets across N layers (M < N), not N times
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/ROADMAP.md
@.planning/phases/1050-builder-smoke-carryover/1050-CONTEXT.md
@.planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md
@.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md

@frontend/src/components/builder/map-sync.ts
@frontend/src/components/builder/hooks/use-builder-layers.ts
@frontend/src/components/builder/cluster-source.ts

<interfaces>
<!-- Existing imperative MapLibre source/layer lifecycle. Executor uses these — does NOT re-explore the codebase. -->

From map-sync.ts (current state — what must change):
- `getSourceId(layerId: string): string` at line 318 — currently returns `source-${layerId}` (per-layer keying — this is the bug)
- `getLayerId(layerId: string): string` at line 324 — returns `layer-${layerId}` (per-layer keying — PRESERVE, layer ids stay per-layer)
- `syncVectorLayer(map, layer, ...)` at line 406-562 — registers source + layer per-layer; `addSource` at line 493-511
- `removeStaleSourcesAndLayers(map, currentSources, desiredSources, sourcePrefix, prefix)` at line 564-591 — desired-set prune; already reference-count-safe by virtue of `desiredSources.add(sourceId)` being called once per consumer
- `syncTerrainSource(map, terrainConfig)` at line 86-124 — IDEMPOTENT REUSE PATTERN to copy: `existing = map.getSource(sourceId)`; replace only on shape mismatch
- `clusterSourceSignature(layer)` at line 310-316 — cluster sources are already per-(cluster-config-signature), preserve

From cluster-source.ts:
- `getClusterSourceStrategy(layer): { kind: 'fallback' | 'bounded' | 'server-tile' }` at lines 86-108 — `kind !== 'fallback'` means "this is a cluster layer; do NOT dedupe its source"
- `isClusterRenderMode(renderMode): boolean` — convenience predicate

From use-builder-layers.ts:
- `swapLayerOnMap(layer, newRenderMode, paint)` at line 752-835 — reads `sourceId = \`source-${layer.id}\`` (line 760-783); inherits tile URL via `map.getSource(sourceId)`
- `handleAiRemoveLayer(layerId)` at line 723-740 — calls `map.removeSource(\`source-${layerId}\`)` at line 737 (must NOT remove if another layer still uses the dataset)

Source-id derivation choice (from PATTERNS.md decision points — locked: Option C):
- `getSourceIdForLayer(layer)`:
  - if `getClusterSourceStrategy(layer).kind !== 'fallback'` → return `\`source-cluster-${layer.id}\`` (preserve per-layer cluster source)
  - else for vector layers with `dataset_table_name` → return `\`source-data-${layer.dataset_table_name}\``
  - else (raster, hillshade, terrain-as-raster, no dataset_table_name) → keep `\`source-${layer.id}\`` (no dedupe applicable)

Cluster-source contract (from PATTERNS.md):
```typescript
import { getClusterSourceStrategy } from '@/components/builder/cluster-source';
const isClusterLayer = getClusterSourceStrategy(layer).kind !== 'fallback';
// Only dedupe if NOT a cluster-source layer.
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Introduce getSourceIdForLayer + per-dataset keying in map-sync.ts</name>
  <files>frontend/src/components/builder/map-sync.ts, frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts</files>
  <read_first>
    - frontend/src/components/builder/map-sync.ts:86-124 (syncTerrainSource — idempotent reuse pattern to copy)
    - frontend/src/components/builder/map-sync.ts:310-340 (clusterSourceSignature, getSourceId, getLayerId — current keying)
    - frontend/src/components/builder/map-sync.ts:406-562 (syncVectorLayer — addSource call site)
    - frontend/src/components/builder/map-sync.ts:564-591 (removeStaleSourcesAndLayers — desired-set prune)
    - frontend/src/components/builder/cluster-source.ts (full file — getClusterSourceStrategy contract)
    - frontend/src/components/builder/__tests__/map-sync.raster.test.ts:360-490 (assertion shape for "addSource NOT called when reused")
    - frontend/src/components/builder/__tests__/map-sync.cluster.test.ts:113,137,223,246 (cluster source-id `source-cluster-1` is the prototype to preserve)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 01 section — touch points, analogs, source-id derivation choices)
    - .planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md SF-04 (root cause + recommended fix)
  </read_first>
  <behavior>
    - Test 1 (NEW — `__tests__/map-sync.dedupe.test.ts`): Given 4 non-cluster vector layers split across 2 unique `dataset_table_name` values, syncing the style fires `addSource` exactly 2 times, not 4.
    - Test 2 (NEW): Two layers sharing the same `dataset_table_name` resolve `getSourceIdForLayer(layer)` to the same string.
    - Test 3 (NEW): A cluster layer + a non-cluster layer on the same `dataset_table_name` get DIFFERENT source ids (cluster source must remain per-layer).
    - Test 4 (NEW): `removeStaleSourcesAndLayers` does NOT remove `source-data-${dataset_table_name}` while another layer in `desiredSources` references it.
    - Test 5 (existing raster path — `map-sync.raster.test.ts`): MUST still pass — raster dedupe shape unchanged.
    - Test 6 (existing cluster path — `map-sync.cluster.test.ts`): MUST still pass — cluster `source-cluster-${id}` keying preserved.
  </behavior>
  <action>
    Add a new exported helper `getSourceIdForLayer(layer: BuilderLayer): string` near `getSourceId` (line 318) in `map-sync.ts` with the locked branching contract from `<interfaces>`:
    1. If `getClusterSourceStrategy(layer).kind !== 'fallback'` → return `` `source-cluster-${layer.id}` ``.
    2. Else if `layer.dataset_table_name` is a non-empty string AND the layer is a vector layer (not raster / hillshade / terrain-as-raster) → return `` `source-data-${layer.dataset_table_name}` ``.
    3. Else → return `` `source-${layer.id}` `` (preserves current behavior for raster/hillshade/no-dataset cases).

    Update `syncVectorLayer` (line 406-562):
    - Replace the local `sourceId` derivation (currently `getSourceId(layer.id)`) with `getSourceIdForLayer(layer)`.
    - Preserve the existing `if (!map.getSource(sourceId))` idempotency guard around `addSource` — this is what produces the M-not-N dedupe.
    - Continue to call `desiredSources.add(sourceId)` once per layer; the desired-set prune contract handles reference-counting for free.
    - Layer ids stay per-layer: `getLayerId(layer.id)` (`layer-${id}`) is unchanged so MapLibre still gets one paint/layout per source consumer.

    DO NOT touch the cluster sync path that uses `clusterSourceSignature` (line 310-316) — cluster sources are intentionally per-layer because cluster radius/minPoints are per-layer settings (CONTEXT.md decision; PATTERNS.md constraint).

    Add the new test file `frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts` mirroring the mock-map shape from `map-sync.raster.test.ts:18-60` (`addSource: vi.fn`, `removeSource: vi.fn`, `getSource: vi.fn`). Cover the 4 NEW behaviors above. Use the test prototype: 4 layers across 2 datasets → `expect(map.addSource).toHaveBeenCalledTimes(2)`.

    Imports to add in map-sync.ts: `import { getClusterSourceStrategy } from '@/components/builder/cluster-source';` (verify not already imported).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run src/components/builder/__tests__/map-sync.dedupe.test.ts src/components/builder/__tests__/map-sync.raster.test.ts src/components/builder/__tests__/map-sync.cluster.test.ts</automated>
  </verify>
  <acceptance_criteria>
    - `getSourceIdForLayer` exported from `map-sync.ts` with the 3-branch contract.
    - New `map-sync.dedupe.test.ts` asserts `addSource` called exactly 2× for 4 layers / 2 datasets.
    - `map-sync.dedupe.test.ts` asserts cluster + non-cluster layers on the SAME dataset get DIFFERENT source ids.
    - Existing `map-sync.raster.test.ts` and `map-sync.cluster.test.ts` still pass with zero modifications.
    - `grep -n "source-data-" frontend/src/components/builder/map-sync.ts` returns at least 1 hit (the new keying).
  </acceptance_criteria>
  <done>
    map-sync.ts dedupes non-cluster vector sources by `dataset_table_name`; new dedupe test passes; raster + cluster tests still pass.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Update use-builder-layers.ts to use the new keying contract</name>
  <files>frontend/src/components/builder/hooks/use-builder-layers.ts</files>
  <read_first>
    - frontend/src/components/builder/hooks/use-builder-layers.ts:723-740 (handleAiRemoveLayer — removes `source-${layerId}` directly; must not break dedupe)
    - frontend/src/components/builder/hooks/use-builder-layers.ts:752-835 (swapLayerOnMap — source-id contract; reads tile URL from map.getSource(sourceId))
    - frontend/src/components/builder/map-sync.ts (after Task 1 — `getSourceIdForLayer` available)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 01 — "Reference-count / desired-set pattern" + "Source-id derivation choices")
    - frontend/src/components/builder/__tests__/use-builder-layers.test.ts (if exists — locate test conventions)
  </read_first>
  <behavior>
    - Test 1 (NEW or extended in `use-builder-layers.test.ts`): Calling `swapLayerOnMap` on a non-cluster vector layer reads from `source-data-${dataset_table_name}` (not `source-${layer.id}`).
    - Test 2 (NEW): `handleAiRemoveLayer` for a layer whose dataset is still referenced by another layer in state does NOT call `map.removeSource` for the shared source.
    - Test 3 (NEW): `handleAiRemoveLayer` for a layer whose dataset is NOT referenced by any remaining layer DOES eventually result in source removal (via the desired-set prune on next sync).
    - Test 4 (existing): cluster `swapLayerOnMap` (cluster ↔ non-cluster transition) still works because the cluster branch uses `source-cluster-${layer.id}`.
  </behavior>
  <action>
    In `frontend/src/components/builder/hooks/use-builder-layers.ts`:

    1. Import `getSourceIdForLayer` from `@/components/builder/map-sync` (verify import path — match existing `import { ... } from '@/components/builder/map-sync'` style if present, else add new import line near the top).

    2. `swapLayerOnMap` (line 752-835): Replace the per-layer `sourceId = \`source-${layer.id}\`` derivation with `sourceId = getSourceIdForLayer(layer)`. The `map.getSource(sourceId)` read at line 760-783 then correctly inherits the deduped source's tile URL for non-cluster vector layers; cluster + raster paths are unchanged.

    3. `handleAiRemoveLayer` (line 723-740, specifically the `map.removeSource(\`source-${layerId}\`)` call at line 737): Replace with a guard — DO NOT directly `removeSource` here. Instead, after removing the layer from state, rely on the next `map-sync` invocation's `removeStaleSourcesAndLayers` prune to detect that `source-data-${dataset_table_name}` is no longer in `desiredSources` if it's truly unreferenced. The explicit per-layer `removeSource` was the per-layer cleanup invariant; the desired-set prune (`map-sync.ts:564-591`) is now the reference-count-aware mechanism.
       - Concrete change: remove the direct `map.removeSource(...)` line; if a `map.removeLayer(layerId)` exists nearby, keep it (layer ids remain per-layer). If the function relied on the source removal to fire a re-sync, ensure the post-state-update `useEffect` that calls `syncFromState` (or equivalent) still triggers — confirm by reading surrounding lines.
       - If the codebase relies on a synchronous resync trigger, call the existing `syncFromState` / equivalent function instead of the direct `removeSource`.

    4. If any OTHER call site in `use-builder-layers.ts` derives `source-${layer.id}` directly (search the full file via `grep -n "source-\${"` and `grep -n "\`source-"`), replace with `getSourceIdForLayer(layer)` for consistency. Document any call site that intentionally keeps the per-layer key (e.g. raster) with an inline comment `// per-layer source (raster/hillshade — not deduped)`.

    5. Saved-map layer rows: per CONTEXT.md decision, source-id keying is a frontend runtime concern — the backend `dataset_table_name` is unchanged. NO migration needed.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run src/components/builder/hooks/__tests__/use-builder-layers.test.ts src/components/builder/__tests__/map-sync.dedupe.test.ts && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "getSourceIdForLayer" frontend/src/components/builder/hooks/use-builder-layers.ts` returns ≥ 2 (swap + any other consumer).
    - `grep -vn '^[[:space:]]*//' frontend/src/components/builder/hooks/use-builder-layers.ts | grep -c "removeSource(\`source-"` returns 0 (direct per-layer removeSource is gone or is only inside a code-commented block).
    - Typecheck clean (0 errors).
    - All existing `use-builder-layers.test.ts` tests pass; new tests for reference-count behavior pass.
    - Cluster swap test still passes (cluster source keying preserved).
  </acceptance_criteria>
  <done>
    swapLayerOnMap and handleAiRemoveLayer route through `getSourceIdForLayer`; per-layer `removeSource` calls are replaced by the desired-set prune; cluster behavior preserved.
  </done>
</task>

<task type="auto">
  <name>Task 3: Smoke-validate end-to-end + saved-map round-trip</name>
  <files>frontend/ (no production code changes — vitest + typecheck + e2e:smoke:builder gates only)</files>
  <read_first>
    - frontend/src/components/builder/__tests__/BuilderMap.unit.test.ts (existing builder integration test shape)
    - frontend/src/components/builder/hooks/use-builder-layers.ts (post-Task-2 state)
    - frontend/src/components/builder/map-sync.ts (post-Task-1 state)
    - .planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md SF-04 (Observed evidence: ~80 requests, expected ~16-24)
  </read_first>
  <action>
    Smoke validation only — no new production code in this task. Run:

    1. Targeted vitest sweep: `cd frontend && npm run test -- --run src/components/builder/__tests__/ src/components/builder/hooks/__tests__/use-builder-layers.test.ts` — expect all green.

    2. Frontend typecheck: `cd frontend && npm run typecheck` — expect 0 errors.

    3. e2e:smoke:builder regression check: `cd frontend && npm run e2e:smoke:builder` — expect no new failures vs. v1010.1 baseline (26/26 passing).

    If any test fails, add an inline fix and re-run. Document any deviation in the task `<done>` field.

    Do NOT run the live Playwright MCP re-verify here — that lives in Plan 06 CTRL-01.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run typecheck && npm run test -- --run src/components/builder/ && npm run e2e:smoke:builder</automated>
  </verify>
  <acceptance_criteria>
    - Typecheck exits 0.
    - Targeted vitest suite passes with same-or-greater test count as pre-fix baseline (no skipped/disabled tests).
    - `e2e:smoke:builder` passes with same scenario count as v1010.1 baseline (26/26).
    - Zero MapLibre `there is no source with this ID` errors in any test stdout.
  </acceptance_criteria>
  <done>
    All targeted vitest + e2e:smoke:builder gates green; no regressions vs. v1010 / v1010.1 baseline.
  </done>
</task>

</tasks>

<verification>
- `addSource` is called M times for M datasets, not N times for N layers (asserted in `map-sync.dedupe.test.ts`).
- `map.getSource(sourceId)` returns the same Source instance for non-cluster layers sharing a `dataset_table_name`.
- Cluster layers retain per-layer source keying (`source-cluster-${id}`).
- Saved-map round-trip is preserved (no schema change; runtime-only fix).
- e2e:smoke:builder passes with no new failures.
</verification>

<success_criteria>
1. `map.getSource(sourceId)` returns the same `Source` instance for every non-cluster layer sharing a `dataset_table_name`.
2. New `map-sync.dedupe.test.ts` asserts `addSource` called 2× for 4 layers / 2 datasets.
3. Toggling layer visibility does not call `removeSource` if another layer still references that source (verified via state-driven prune; no MapLibre `there is no source with this ID` errors).
4. Cluster layers continue to render correctly — `cluster-source.ts` per-layer scoping preserved.
5. Targeted vitest suites for `use-builder-layers`, `map-sync` (dedupe + raster + cluster) all pass; no new failures in `e2e:smoke:builder`.
</success_criteria>

<output>
Create `.planning/phases/1050-builder-smoke-carryover/1050-01-SUMMARY.md` when done — record:
- New `getSourceIdForLayer` signature + the 3-branch contract.
- Before/after `addSource` call count from `map-sync.dedupe.test.ts`.
- Confirmation that cluster + raster paths are unchanged.
- Any deviation from the locked Option C source-id derivation choice.
</output>
