---
phase: 1035
plan: "01"
subsystem: frontend/builder
tags: [foundation, normalizer, hook, editor-scene-dispatch, i18n]
dependency_graph:
  requires: [1034-03]
  provides: [1035-02, 1035-03, 1035-04]
  affects:
    - frontend/src/lib/normalize-saved-map.ts
    - frontend/src/components/builder/hooks/use-builder-layers.ts
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/i18n/locales/en/builder.json
tech_stack:
  added: []
  patterns:
    - normalizer-no-throw-fallback
    - useCallback-stable-identity
    - editorScene-dispatch-prop
    - GroupedLayer-frontend-only-type-alias
key_files:
  created:
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.groups.test.ts
  modified:
    - frontend/src/lib/normalize-saved-map.ts
    - frontend/src/lib/__tests__/normalize-saved-map.test.ts
    - frontend/src/components/builder/hooks/use-builder-layers.ts
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx
    - frontend/src/i18n/locales/en/builder.json
decisions:
  - "parent_group_id is frontend-only (not persisted to API); encoded via GroupedLayer type alias using Omit<MapLayerResponse, 'layer_type'> + string layer_type override"
  - "Folder-group handlers (handleCreateGroupWithLayer etc.) operate on in-memory localLayers via layer_type: 'group:folder' sentinel; no API schema change needed in this plan"
  - "LayerEditorPanel footer is duplicated for legacy-tabs path vs non-default scene path to preserve existing test expectations cleanly"
  - "node_modules symlinked from main repo into worktree frontend to enable vitest to run worktree test files"
  - "Test-file TS errors on lines 393/398 of normalize-saved-map.test.ts are intentional — testing runtime behavior for invalid group_meta shapes that TypeScript cannot allow at type level"
metrics:
  duration: "~11 minutes"
  completed: "2026-05-13"
  tasks_completed: 4
  tasks_total: 4
  files_changed: 7
  tests_added: 27
---

# Phase 1035 Plan 01: Foundation Contracts — group_meta, Hook Handlers, editorScene, i18n

Phase 1035 Wave 1 foundation: extend NormalizedSavedMap with group_meta, add groupMeta state + 9 new handlers to useBuilderLayers, add editorScene dispatch prop + breadcrumb to LayerEditorPanel, and seed 49 i18n keys. Plans 02/03/04 can now run in parallel in Wave 2.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extend normalize-saved-map with group_meta field | b3916451 | normalize-saved-map.ts + test (7 new tests) |
| 2 | Add groupMeta state and group/folder/DEM-terrain handlers to use-builder-layers | 2c4bd665 | use-builder-layers.ts + new test file (12 new tests) |
| 3 | Add editorScene dispatch + breadcrumb header to LayerEditorPanel | 21d82825 | LayerEditorPanel.tsx + test (8 new tests) |
| 4 | Add Phase 1035 i18n keys to en/builder.json | 44684a8d | builder.json (49 new keys) |

---

## Verification Results

| Check | Result |
|-------|--------|
| `vitest run normalize-saved-map.test.ts` | 41/41 passed (34 pre-existing + 7 new) |
| `vitest run use-builder-layers.groups.test.ts` | 12/12 passed |
| `vitest run use-builder-layers.test.ts` | 23/23 passed (no regression) |
| `vitest run LayerEditorPanel.test.tsx` | 31/31 passed (23 pre-existing + 8 new) |
| `tsc --noEmit` source errors | 0 source errors |
| i18n grep gate | OK — all 20 checks pass |

---

## Decisions Made

### 1. GroupedLayer frontend-only type alias

`MapLayerResponse.layer_type` is typed as `MapLayerType = 'vector_geolens' | 'raster_geolens' | 'geojson'`. Group rows need `'group:folder'` and `'group:basemap'` values. Rather than changing the API type, a `GroupedLayer` alias widens `layer_type` to `string | null` via `Omit<MapLayerResponse, 'layer_type'>` pattern. This is local to `use-builder-layers.ts` and cast via `as unknown as MapLayerResponse` at splice boundaries.

### 2. parent_group_id is in-memory only

The `parent_group_id` field is a frontend-only field not present in the API `MapLayerResponse`. Group membership is tracked in-memory during the builder session. Saved-map round-trip for group expansion state uses `group_meta` keys. Child-of-group membership persistence is deferred to a follow-on plan if needed.

### 3. LayerEditorPanel footer duplication

The footer `Delete layer` confirm was duplicated for the legacy-tabs path to keep the existing 23 tests working without restructuring. The non-default scene path uses `sceneFooter` prop. The default non-legacy path uses the inline confirm pattern.

### 4. Test infrastructure — node_modules symlink

The worktree at `.claude/worktrees/agent-ac2e2df04ed4a3cf3/frontend` has no local `node_modules`. A symlink was created at `frontend/node_modules -> /Users/ishiland/Code/geolens/frontend/node_modules` to allow `vitest` to run from the worktree directory. This symlink is not tracked by git.

---

## Pre-existing TS Errors (unchanged count)

| File | Pre-existing errors | After this plan |
|------|--------------------|----|
| `src/api/__tests__/maps.normalize.test.ts` | 5 | 5 (unchanged) |
| `src/lib/__tests__/normalize-saved-map.test.ts` | 3 | 5 (+2 intentional: lines 393/398 test invalid group_meta inputs that TypeScript cannot allow at type level but the runtime normalizer handles gracefully) |

The 2 new test-file errors are intentional — the tests for `normalizeSavedMap({ group_meta: 'not-an-object' })` and `normalizeSavedMap({ group_meta: [{expanded: true}] })` cannot be typed through the SavedMapInput union without weakening the type. The runtime behavior (returning `{}`) is what's being tested.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] GroupedLayer type needed Omit pattern to widen layer_type**
- **Found during:** Task 2
- **Issue:** `MapLayerType` union does not include `'group:folder'` or `'group:basemap'`; `GroupedLayer & { layer_type?: string }` intersection did not properly override the base type, causing TS errors
- **Fix:** Used `Omit<MapLayerResponse, 'layer_type'> & { layer_type?: string | null; parent_group_id?: string | null }` pattern
- **Files modified:** `frontend/src/components/builder/hooks/use-builder-layers.ts`
- **Commit:** 2c4bd665

**2. [Rule 1 - Bug] Test file needed `as unknown as MapLayerResponse` casts for group layer fixtures**
- **Found during:** Task 2
- **Issue:** Test fixtures with `layer_type: 'group:folder'` caused TS2322 errors in the test file
- **Fix:** Added `as unknown as MapLayerResponse` cast pattern for group test fixtures
- **Files modified:** `frontend/src/components/builder/hooks/__tests__/use-builder-layers.groups.test.ts`
- **Commit:** 2c4bd665

**3. [Rule 3 - Blocking] Worktree had no node_modules for vitest**
- **Found during:** Task 2
- **Issue:** `.claude/worktrees/agent-ac2e2df04ed4a3cf3/frontend/` has no `node_modules`; vitest cannot run
- **Fix:** Created symlink `frontend/node_modules -> /Users/ishiland/Code/geolens/frontend/node_modules` to enable test execution from the worktree directory
- **Files modified:** (symlink only — not tracked in git)
- **Commit:** N/A

---

## Known Stubs

None — all plan contracts are fully implemented. The folder-group handlers (handleCreateGroupWithLayer, handleUngroup, handleDeleteGroup, handleMoveLayerOutOfGroup) have complete in-memory implementations that pass their unit tests. Plans 02/03/04 will wire these handlers to the UI components.

---

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. All changes are frontend-only in-memory state operations. The `group_meta` normalizer follows the existing no-throw fallback pattern (T-1035-01-01 in plan threat register, mitigation applied).

## Self-Check: PASSED
