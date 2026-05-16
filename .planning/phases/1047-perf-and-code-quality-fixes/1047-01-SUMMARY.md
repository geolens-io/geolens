---
phase: 1047
plan: 01
subsystem: builder/layer-adapters, e2e/perf
tags: [ca-01, cc-15, perf-fixture, filter-utility, tdd]
depends:
  requires: []
  provides:
    - syncLayerFilter helper in layer-adapters/shared.ts
    - e2e/fixtures/seed-large-builder-map.ts (createLargeBuilderMap, deleteBuilderMap)
    - e2e/perf/builder-large-map.spec.ts (perf spec scaffold for Plans 02-04)
  affects:
    - fill-adapter.ts (5 filter call sites replaced)
    - line-adapter.ts (2 filter call sites replaced)
    - circle-adapter.ts (1 filter call site replaced)
    - heatmap-adapter.ts (2 filter call sites replaced)
tech_stack:
  added: []
  patterns:
    - syncLayerFilter: canonical filter-null-toggling in shared.ts (CA-01 remediation)
    - TDD: RED commit f911ca4b → GREEN/REFACTOR commit e488bfa0
key_files:
  created:
    - frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts
    - e2e/fixtures/seed-large-builder-map.ts
    - e2e/perf/builder-large-map.spec.ts
  modified:
    - frontend/src/components/builder/layer-adapters/shared.ts
    - frontend/src/components/builder/layer-adapters/fill-adapter.ts
    - frontend/src/components/builder/layer-adapters/line-adapter.ts
    - frontend/src/components/builder/layer-adapters/circle-adapter.ts
    - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
    - .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
    - package.json
decisions:
  - "hillshade and raster adapters have no filter branches (confirmed by grep); plan listed them as targets but actual code has no pattern to replace"
  - "syncLayerFilter placed after finalizeLayer in shared.ts; imports FilterSpecification from maplibre-gl"
  - "heatmap addLayers: syncLayerFilter call wrapped inside try block matching existing adapter convention"
metrics:
  duration: ~10 minutes
  completed: "2026-05-16"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 7
requirements_satisfied: [CODE-02, CODE-03, CODE-04]
---

# Phase 1047 Plan 01: Perf-Test Fixture and Trivial Wins Summary

Shipped the two P0 trivial audit wins (CA-01 filter utility, CC-15 audit verification) and seeded the 50-layer test fixture + Playwright perf spec scaffold that Waves B-D need for before/after metric capture.

## Task Results

### Task 1: syncLayerFilter helper (CA-01) — TDD

**Contract:** `syncLayerFilter(map, layerId, filter)` — calls `map.setFilter(layerId, filter)` when filter is a non-empty array; calls `map.setFilter(layerId, null)` when filter is null/undefined/empty; is a no-op when `map.getLayer(layerId)` returns undefined.

**Adapter call-site count:**

| Adapter | Call sites replaced |
|---------|-------------------|
| fill-adapter.ts | 5 (outline+extrusion addLayers; main+outline+extrusion syncPaint) |
| line-adapter.ts | 2 (arrowLayer sync, line syncPaint) |
| circle-adapter.ts | 1 (syncPaint) |
| heatmap-adapter.ts | 2 (addLayers, syncPaint) |
| hillshade-adapter.ts | 0 (no filter branches — confirmed by grep) |
| raster-adapter.ts | 0 (no filter branches — confirmed by grep) |
| **Total** | **10** |

**Net LOC delta (6 adapter files):** -15 lines net (10 replaced branches × avg 3 lines each = -30, plus import additions = net -15).

**TDD gate:**
- RED commit: `f911ca4b` — 5 failing tests
- GREEN commit: `e488bfa0` — 5 passing tests + all adapter refactors

### Task 2: CC-15 audit verification — annotation path

Grep confirmed: `selectedLayerId` has **0 occurrences** in `frontend/src/components/builder/map-sync.ts`. The parameter exists in `UnifiedStackPanel.tsx` and `SidebarRail.tsx` (UI selection state) but those files were not the CC-15 target. No code change required.

**Disposition:** Appended `**Status (Phase 1047):**` annotation to CC-15 finding in `1046-BUILDER-CODE-AUDIT.md` explaining the claim could not be reproduced and noting where `selectedLayerId` actually lives.

### Task 3: 50-layer seeder fixture + perf spec scaffold

**Fixture import surface:**
```typescript
import { createLargeBuilderMap } from './fixtures/seed-large-builder-map';
```

**Usage by downstream plans:**
```typescript
const { mapId, layerIds } = await createLargeBuilderMap(request, {
  name: 'Perf test map',
  layerCount: 50,
  datasetId,
});
```

**Spec structure:** `describe('Builder large-map perf — PERF-01..04')` with:
- `beforeAll`: seeds 50-layer map via `createLargeBuilderMap`
- `afterAll`: cleans up via `deleteBuilderMap`
- Smoke test: canvas visible within 8s
- `test.skip(!process.env.E2E_BACKEND_AVAILABLE)` guard
- Placeholder comment slots for Plans 02-04 wave assertions

**New script in package.json:**
```
"e2e:smoke:perf": "npx playwright test e2e/perf/builder-large-map.spec.ts --project=chromium"
```
Not chained to `e2e:smoke` (keeps smoke gate fast).

## Verification Results

| Check | Result |
|-------|--------|
| `syncLayerFilter` 5-test vitest suite | 5/5 PASS |
| Full vitest suite (1815 tests) | 1815/1815 PASS |
| TypeScript typecheck (`tsc --noEmit`) | CLEAN |
| Duplicate filter-branch count outside shared.ts | 0 |
| `selectedLayerId` in map-sync.ts | 0 occurrences |
| Playwright spec discoverable (`--list`) | FOUND |
| `e2e:smoke:perf` script in package.json | PRESENT |

## Commits

| Hash | Type | Description |
|------|------|-------------|
| `f911ca4b` | test | add failing tests for syncLayerFilter helper (RED) |
| `e488bfa0` | feat | extract syncLayerFilter helper; replace 8 duplicate filter branches (CA-01) |
| `552e8281` | chore | verify CC-15 selectedLayerId claim; annotate audit as not reproducible (CODE-04) |
| `ffcd121c` | feat | add 50-layer seeder fixture and Playwright perf spec scaffold (PERF-01..04) |

## Deviations from Plan

### Auto-observations (no code change needed)

**1. hillshade-adapter and raster-adapter have no filter branches**
- **Found during:** Task 1
- **Issue:** Plan listed `hillshade-adapter.ts:52-57` and `raster-adapter.ts:29-32, 49-52` as filter-branch targets. Actual file inspection found neither adapter calls `map.setFilter` at all — hillshade and raster layer types don't support filters in MapLibre.
- **Resolution:** No refactor needed; confirmed by grep. Adapter file list in plan was likely carried forward from an earlier audit snapshot. Net count is 10 replaced sites (not 12), still eliminating all actual duplication.
- **Files modified:** None

## Known Stubs

None — no stub patterns introduced. Perf spec has placeholder comments (not stubs) that Plans 02-04 will fill with real assertions.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. Seeder fixture only exercises existing `/api/maps/` and `/api/maps/{id}/layers/` endpoints.

## Self-Check: PASSED

- `frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts` — FOUND
- `frontend/src/components/builder/layer-adapters/shared.ts` (syncLayerFilter export) — FOUND
- `e2e/fixtures/seed-large-builder-map.ts` — FOUND
- `e2e/perf/builder-large-map.spec.ts` — FOUND
- Commit `f911ca4b` — FOUND
- Commit `e488bfa0` — FOUND
- Commit `552e8281` — FOUND
- Commit `ffcd121c` — FOUND
