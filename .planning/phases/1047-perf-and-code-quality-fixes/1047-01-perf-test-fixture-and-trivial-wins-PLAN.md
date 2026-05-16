---
phase: 1047-perf-and-code-quality-fixes
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/layer-adapters/shared.ts
  - frontend/src/components/builder/layer-adapters/fill-adapter.ts
  - frontend/src/components/builder/layer-adapters/line-adapter.ts
  - frontend/src/components/builder/layer-adapters/circle-adapter.ts
  - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
  - frontend/src/components/builder/layer-adapters/hillshade-adapter.ts
  - frontend/src/components/builder/layer-adapters/raster-adapter.ts
  - frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts
  - frontend/src/components/builder/map-sync.ts
  - e2e/fixtures/seed-large-builder-map.ts
  - e2e/perf/builder-large-map.spec.ts
  - .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
autonomous: true
requirements: [CODE-02, CODE-03, CODE-04]
must_haves:
  truths:
    - "syncLayerFilter helper exists in adapters/shared.ts and is the only place filter-null toggling logic lives"
    - "All 6 layer adapters call syncLayerFilter instead of duplicating the `filter && Array.isArray && length>0` branch"
    - "Phase 1046 CC-15 finding is resolved: either the unused parameter is removed from map-sync.ts OR the audit doc is annotated explaining the mistaken claim"
    - "A reusable e2e seeder fixture creates a 50-layer test map via API; subsequent perf plans import it"
    - "Phase 1047 has a working perf spec scaffold (`e2e/perf/builder-large-map.spec.ts`) ready for later waves to attach FCP/latency/throughput assertions"
  artifacts:
    - path: "frontend/src/components/builder/layer-adapters/shared.ts"
      provides: "syncLayerFilter export"
      contains: "export function syncLayerFilter"
    - path: "e2e/fixtures/seed-large-builder-map.ts"
      provides: "createLargeBuilderMap(page, layerCount) helper"
    - path: "e2e/perf/builder-large-map.spec.ts"
      provides: "large-map perf spec scaffold + first-load smoke"
  key_links:
    - from: "frontend/src/components/builder/layer-adapters/{fill,line,circle,heatmap,hillshade,raster}-adapter.ts"
      to: "frontend/src/components/builder/layer-adapters/shared.ts"
      via: "import { syncLayerFilter } from './shared'"
      pattern: "syncLayerFilter\\(map,"
---

<objective>
Establish foundation for Phase 1047: ship the two trivial P0 audit wins (CA-01 filter utility, CC-15 dead-param verification), and seed the 50-layer test fixture + Playwright perf spec scaffold that Waves B-D need to capture before/after metrics.

Purpose: Plans 02-04 cannot measure PERF-01..04 without a 50-layer test map. CA-01 is the highest-ROI P0 (extract once, replace 10+ occurrences); CC-15 is a < 1 hour audit-claim verification.

Output: shared `syncLayerFilter` helper, all 6 adapter call-sites refactored, CC-15 resolved (removed or audit-amended), Playwright fixture helper, perf spec scaffold.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md

<interfaces>
<!-- Existing exports from layer-adapters/shared.ts the new helper sits alongside -->
From frontend/src/components/builder/layer-adapters/shared.ts (270 LOC):
- `export function simplifyPaint(paint): Record<string, unknown>`
- `export function filterPaintForLayerType(paint, geomType): Record<string, unknown>`
- `export function finalizeLayer(map, layerId, rawPaint, geomType, opacity, filter, hasExpressions): void`  (already calls setFilter inline)
- `export function getExpressionSafeOpacity(...)`
- `export function syncVectorPaint(map, layerId, paint): void`
- `export function getBuilderStyleConfig(...)`

<!-- Adapters currently use the duplicated 4-line filter branch in these locations -->
Filter-branch occurrences (audit CA-01):
- fill-adapter.ts:91-93 (outline), 114-116 (extrusion), 160-163 (outline syncPaint), 187-190 (extrusion syncPaint)
- line-adapter.ts:171-175
- heatmap-adapter.ts:64-66, 94-98
- circle-adapter.ts:39-42
- hillshade-adapter.ts:52-57
- raster-adapter.ts:29-32, 49-52

<!-- syncLayersToMap signature (map-sync.ts:598) — VERIFIED no selectedLayerId param exists -->
export function syncLayersToMap(
  map: MaplibreMap,
  layers: SyncLayerInput[],
  tokenMap: Map<string, TileToken>,
  tileBaseUrl: string | undefined,
  managedSourcesRef: { current: Set<string> },
  lastOrderKeyRef: { current: string },
  geojsonDataMap?: Map<string, GeoJSON.FeatureCollection>,
  options?: SyncOptions,
)
<!-- CC-15 audit claim is wrong as written. Task 2 verifies + amends the audit. -->

<!-- Existing API client for layer creation (seeder helper will reuse this pattern via direct HTTP) -->
From frontend/src/api/maps.ts:
- `export async function addLayerToMapApi(mapId, body): Promise<MapLayerResponse>`
- `POST /maps/{mapId}/layers` accepts { dataset_id: string }

<!-- E2E test scaffold lives at e2e/ — Playwright config at ./playwright.config.ts -->
<!-- Existing builder smoke specs: e2e/builder.spec.ts, builder-styling.spec.ts, builder-v1-5.spec.ts -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Extract syncLayerFilter helper and refactor all 6 adapters (CA-01)</name>
  <files>
    frontend/src/components/builder/layer-adapters/shared.ts,
    frontend/src/components/builder/layer-adapters/fill-adapter.ts,
    frontend/src/components/builder/layer-adapters/line-adapter.ts,
    frontend/src/components/builder/layer-adapters/circle-adapter.ts,
    frontend/src/components/builder/layer-adapters/heatmap-adapter.ts,
    frontend/src/components/builder/layer-adapters/hillshade-adapter.ts,
    frontend/src/components/builder/layer-adapters/raster-adapter.ts,
    frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts
  </files>
  <read_first>
    frontend/src/components/builder/layer-adapters/shared.ts (read fully, 270 LOC),
    frontend/src/components/builder/layer-adapters/fill-adapter.ts (note 4 filter-branch sites),
    frontend/src/components/builder/layer-adapters/line-adapter.ts,
    frontend/src/components/builder/layer-adapters/circle-adapter.ts,
    frontend/src/components/builder/layer-adapters/heatmap-adapter.ts,
    frontend/src/components/builder/layer-adapters/hillshade-adapter.ts,
    frontend/src/components/builder/layer-adapters/raster-adapter.ts,
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md (CA-01 detail)
  </read_first>
  <behavior>
    - Test 1: `syncLayerFilter(map, 'L', ['==', 'foo', 1])` calls `map.setFilter('L', ['==', 'foo', 1])` exactly once
    - Test 2: `syncLayerFilter(map, 'L', null)` calls `map.setFilter('L', null)`
    - Test 3: `syncLayerFilter(map, 'L', undefined)` calls `map.setFilter('L', null)`
    - Test 4: `syncLayerFilter(map, 'L', [])` (empty array) calls `map.setFilter('L', null)` — empty filter is treated as "no filter"
    - Test 5: helper is a no-op when `map.getLayer(layerId)` returns undefined (does not throw) — confirms safe to call on missing layers
  </behavior>
  <action>
    Add `export function syncLayerFilter(map: MaplibreMap, layerId: string, filter: FilterSpecification | unknown[] | null | undefined): void` to `frontend/src/components/builder/layer-adapters/shared.ts` (place after `finalizeLayer`). Body: if `!map.getLayer(layerId)` return; if `filter && Array.isArray(filter) && filter.length > 0` then `map.setFilter(layerId, filter as FilterSpecification)` else `map.setFilter(layerId, null)`. Type the signature using maplibre-gl's `FilterSpecification` already imported elsewhere in shared.ts. Then replace every audit-identified occurrence (fill-adapter outline + extrusion blocks, line-adapter, circle-adapter, heatmap-adapter, hillshade-adapter, raster-adapter) with a single `syncLayerFilter(map, <id>, filter)` call. Do NOT touch the `finalizeLayer` body (it handles the master fill/line/circle paint sync — keep its inline `setFilter` for now; just leverage the new helper for outline + extrusion + sibling-adapter call sites). Preserve all existing comments. Add per CODE-03 (duplication remediation). Write `frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts` (new file) implementing the 5 behavior tests above with a `createMockMap()` factory that records `setFilter`/`getLayer` calls. Re-export `syncLayerFilter` from `frontend/src/components/builder/layer-adapters/index.ts` if a barrel exists; otherwise import from `./shared` in each adapter.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/components/builder/layer-adapters/__tests__/shared.test.ts</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/layer-adapters</automated>
    <automated>cd frontend && grep -c "syncLayerFilter" src/components/builder/layer-adapters/fill-adapter.ts src/components/builder/layer-adapters/line-adapter.ts src/components/builder/layer-adapters/circle-adapter.ts src/components/builder/layer-adapters/heatmap-adapter.ts src/components/builder/layer-adapters/hillshade-adapter.ts src/components/builder/layer-adapters/raster-adapter.ts | grep -v ':0'</automated>
    <automated>cd frontend && rg -n "if \\(filter && Array\\.isArray\\(filter\\) && filter\\.length > 0\\)" src/components/builder/layer-adapters/ | grep -v shared.ts | wc -l</automated>
  </verify>
  <acceptance_criteria>
    - `syncLayerFilter` exported from shared.ts with the exact 5 behaviors covered by the new test file
    - All 6 adapter files import `syncLayerFilter` from `./shared` (count > 0 in each)
    - Zero remaining occurrences of the duplicated `if (filter && Array.isArray(filter) && filter.length > 0)` branch outside `shared.ts` (rg count == 0 in adapter directory, excluding shared.ts which now houses the canonical version)
    - All existing layer-adapter tests still pass (no behavior regression)
    - Net LOC across the 6 adapters drops (duplication removed)
  </acceptance_criteria>
  <done>Adapters share one filter-sync helper; duplication eliminated; tests cover the helper's 5 contract behaviors.</done>
</task>

<task type="auto">
  <name>Task 2: Verify CC-15 selectedLayerId claim — either remove dead param or amend the audit</name>
  <files>
    frontend/src/components/builder/map-sync.ts,
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
  </files>
  <read_first>
    frontend/src/components/builder/map-sync.ts (lines 598-720, the syncLayersToMap export and reorder helpers),
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md (CC-15 finding detail, lines ~110-125)
  </read_first>
  <action>
    The Phase 1046 audit asserts `syncLayersToMap` has an unused `selectedLayerId: string | null` parameter. Pre-planning inspection found NO such parameter — verified actual signature is `(map, layers, tokenMap, tileBaseUrl, managedSourcesRef, lastOrderKeyRef, geojsonDataMap?, options?)`. Do one final grep across `frontend/src` for `selectedLayerId` to confirm no dead parameter exists ANYWHERE in map-sync.ts or other audited builder source files. If grep finds a genuine unused parameter (in map-sync.ts or elsewhere flagged): remove it and update all call sites. If grep confirms no dead parameter exists (expected outcome): append a `**Status (Phase 1047):** resolved — audit claim could not be reproduced. `selectedLayerId` does not appear in syncLayersToMap signature at git SHA b8d2abe5; verified 2026-05-16. No code change required.` line under the CC-15 finding in BUILDER-CODE-AUDIT.md. Do not silently skip — every P0 needs a written disposition (per CODE-02). This satisfies CODE-04 (dead-code re-verification) for CC-15.
  </action>
  <verify>
    <automated>rg -n "selectedLayerId" frontend/src/components/builder/map-sync.ts | grep -v '^#' | wc -l | grep -E '^0$'</automated>
    <automated>grep -c "Status (Phase 1047)" .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md</automated>
    <automated>cd frontend && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `selectedLayerId` does not appear in `frontend/src/components/builder/map-sync.ts` (rg count 0, excluding comments)
    - BUILDER-CODE-AUDIT.md has a `**Status (Phase 1047):**` annotation appended under the CC-15 section explaining the resolution (either "removed" with commit ref OR "resolved — claim not reproducible")
    - frontend typecheck remains clean
  </acceptance_criteria>
  <done>CC-15 is closed with a written disposition; either the param is removed or the audit is amended.</done>
</task>

<task type="auto">
  <name>Task 3: Seed large-map fixture + Playwright perf spec scaffold</name>
  <files>
    e2e/fixtures/seed-large-builder-map.ts,
    e2e/perf/builder-large-map.spec.ts
  </files>
  <read_first>
    e2e/builder.spec.ts (existing builder smoke patterns: auth, navigation, addLayer),
    e2e/builder-v1-5.spec.ts (existing bulk-op smoke patterns),
    frontend/src/api/maps.ts (addLayerToMapApi, removeLayerFromMapApi),
    backend/app/modules/catalog/maps/router.py (lines 1500-1620 — addLayerEndpoint contract),
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md (Test Map / Fixture section + each PERF Reproduction block)
  </read_first>
  <action>
    Create `e2e/fixtures/seed-large-builder-map.ts` exporting `createLargeBuilderMap(request: APIRequestContext, opts: { name: string; layerCount: number; datasetId: string }): Promise<{ mapId: string; layerIds: string[] }>`. Implementation: (1) `POST /api/maps/` with `{ name, ... }` to create the map and capture `id`; (2) in a loop of `layerCount` iterations, `POST /api/maps/{id}/layers/` with `{ dataset_id: opts.datasetId }`; (3) return `{ mapId, layerIds }`. Add a sibling helper `deleteBuilderMap(request, mapId)` calling `DELETE /api/maps/{mapId}`. Use the existing auth `storageState` from playwright.config.ts so requests inherit JWT — invoke via `request.newContext({ storageState })` or use the page's `request` object.

    Create `e2e/perf/builder-large-map.spec.ts` with a `test.describe('Builder large-map perf — PERF-01..04')` block. Inside: a `beforeAll` that uses `createLargeBuilderMap` to seed a 50-layer map (pick any small dataset id from the existing demo seeder — read e2e/builder.spec.ts to discover the canonical fixture dataset id), an `afterAll` cleanup, and a single placeholder `test('opens 50-layer map and renders canvas', ...)` that navigates to `/maps/{mapId}`, waits for `[data-testid="builder-map-canvas"]` (or the existing canvas selector — confirm from e2e/builder.spec.ts), and asserts the canvas appears within 8s. NO timing assertions yet — those land in Plans 02 (PERF-05) and 04 (PERF-03). This spec is the scaffold subsequent waves attach `performance.mark()` blocks to.

    Wire the new spec into a new `e2e:smoke:perf` script in `package.json` so the spec runs on demand without blocking the default `e2e:smoke:builder`. Add this to `package.json` scripts: `"e2e:smoke:perf": "npx playwright test e2e/perf/builder-large-map.spec.ts --project=chromium"`. Do NOT add it to `e2e:smoke` — keep the smoke gate fast.

    If the seeder cannot run in the planner's environment (no Docker stack available), still write the fixture + spec; mark the test with `test.skip(!process.env.E2E_BACKEND_AVAILABLE, 'requires docker stack')` so CI can opt in.
  </action>
  <verify>
    <automated>test -f e2e/fixtures/seed-large-builder-map.ts && test -f e2e/perf/builder-large-map.spec.ts</automated>
    <automated>cd frontend && npm run typecheck</automated>
    <automated>npx playwright test e2e/perf/builder-large-map.spec.ts --list --project=chromium 2>&1 | grep -E "builder-large-map"</automated>
    <automated>grep -c "e2e:smoke:perf" package.json</automated>
  </verify>
  <acceptance_criteria>
    - `e2e/fixtures/seed-large-builder-map.ts` exists and exports `createLargeBuilderMap` and `deleteBuilderMap`
    - `e2e/perf/builder-large-map.spec.ts` exists with one describe block scaffolding the perf assertions for downstream waves
    - `package.json` has a new `e2e:smoke:perf` script
    - `npx playwright test --list` discovers the new spec
    - Frontend typecheck stays clean (helper compiles)
  </acceptance_criteria>
  <done>Plans 02-04 have a 50-layer test map seeder and a perf spec to attach assertions to.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Test seeder → backend API | Test fixtures hit the real `/api/maps/*` endpoints. Requires authenticated `storageState`. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1047-01-01 | Tampering | syncLayerFilter helper | mitigate | Helper accepts `unknown[] \| null \| undefined`; rejects empty array same as null. Unit tests cover all 5 paths. No filter injection surface — values are already validated by callers. |
| T-1047-01-02 | DoS | Large-map seeder | accept | Test seeder creates 50 layers per test run; runs in dev/CI only. Backend already caps layers at 200/map (`_MAX_LAYERS_PER_MAP` in schemas.py). |
| T-1047-01-SC | Tampering | npm/pip installs | mitigate | No new packages introduced in this plan. |
</threat_model>

<verification>
- Vitest builder suite: `cd frontend && npm run test` — no regressions
- Typecheck: `cd frontend && npm run typecheck` — clean
- Audit re-grep for CC-15: `rg -c "selectedLayerId" frontend/src/components/builder/map-sync.ts` returns 0
- Duplication count: `rg "if \\(filter && Array\\.isArray\\(filter\\)" frontend/src/components/builder/layer-adapters/` returns matches only in `shared.ts`
- Playwright spec discoverable: `npx playwright test --list` includes `e2e/perf/builder-large-map.spec.ts`
</verification>

<success_criteria>
1. `syncLayerFilter` exists in shared.ts with full test coverage; all 6 adapters use it; duplication is eliminated outside the canonical helper.
2. CC-15 has a written disposition in BUILDER-CODE-AUDIT.md (either remediated or annotated "claim not reproducible").
3. `e2e/fixtures/seed-large-builder-map.ts` and `e2e/perf/builder-large-map.spec.ts` exist and compile; subsequent waves can `import { createLargeBuilderMap }` and attach perf assertions.
4. No regressions: vitest builder suite passes, typecheck clean.
</success_criteria>

<output>
Create `.planning/phases/1047-perf-and-code-quality-fixes/1047-01-SUMMARY.md` when done. Include:
- syncLayerFilter contract + adapter call-site count
- CC-15 disposition (which path was taken)
- Fixture import surface example (one-line: `import { createLargeBuilderMap } from './fixtures/seed-large-builder-map'`)
- Net LOC delta across the 6 adapters
</output>
