---
phase: 1140-raster-terrain-editor-controls
fixed_at: 2026-05-28T11:17:45Z
review_path: .planning/phases/1140-raster-terrain-editor-controls/1140-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 1140: Code Review Fix Report

**Fixed at:** 2026-05-28T11:17:45Z
**Source review:** .planning/phases/1140-raster-terrain-editor-controls/1140-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4
- Fixed: 4 (CR-01, WR-01, WR-02, IN-01)
- Skipped: 0

## Fixed Issues

### CR-01: Contour interval change has no effect after initial layer add

**Files modified:** `frontend/src/components/builder/contour-sync.ts`
**Commit:** 78ac48a5
**Applied fix:** Replaced the bare `if (!map.getSource(contourSourceId))` guard with a two-branch pattern. When the source does not yet exist, `addSource` is called as before. When it already exists, `existingContourSource.serialize?.()?.tiles[0]` is compared against the freshly-computed `contourProtocolUrl`; if they differ, `setTiles([contourProtocolUrl])` is called on the source object. This keeps the guard (no unnecessary fetches when the URL is unchanged) while ensuring interval slider changes propagate after the first layer add.

### WR-01: color-relief companion layer orphaned when DEM layer is deleted

**Files modified:** `frontend/src/components/builder/map-sync.ts`
**Commit:** 0aca4fa8
**Applied fix:** Added `const colorReliefId = \`${layerId}-colorrelief\`` and `if (map.getLayer(colorReliefId)) map.removeLayer(colorReliefId)` at the top of the companion-removal block in `removeStaleSourcesAndLayers`, before the existing label/arrow/extrusion/outline removals. The contour companion is unaffected (its source is tracked in `managedSourcesRef` and already handled by the source loop).

### WR-02: `_demSources` module-level registry is never pruned

**Files modified:** `frontend/src/components/builder/contour-sync.ts`
**Commit:** 78ac48a5 (same commit as CR-01 — both changes are in contour-sync.ts)
**Applied fix:** Added `_demSources.delete(input.sourceId)` in the `!enabled` early-return branch, after the layer and source removal calls. This releases the `DemSource` (and its Web Worker) so a re-added dataset always gets a fresh `DemSource` with the current tile URL.

### IN-01: No test coverage for contour interval change or color-relief DEM-deletion scenarios

**Files modified:** `frontend/src/components/builder/__tests__/contour-sync.test.ts`, `frontend/src/components/builder/__tests__/map-sync.raster.test.ts`
**Commits:** 78ac48a5 (contour-sync tests), 0aca4fa8 (map-sync.raster test)
**Applied fix:**

1. Updated `createMockMap()` in `contour-sync.test.ts` to return per-source mock objects with `setTiles` and `serialize` spies that track the current tile URL, enabling meaningful assertions on `setTiles` calls.

2. Added three tests to `contour-sync.test.ts`:
   - **CR-01 regression:** Two calls with different intervals assert `addSource` is called once and `setTiles` is called with the new URL on the second call.
   - **CR-01 no-op guard:** Two calls with the same interval assert `setTiles` is never called.
   - **WR-02 regression:** Enable then disable asserts `_demSources.has(sourceId)` is false after disable.

3. Added one test to `map-sync.raster.test.ts` (WR-01 regression): Pre-populates `managedSourcesRef` with `source-dem-wr01` and mocks `getLayer` to return truthy for both `layer-dem-wr01` and `layer-dem-wr01-colorrelief`, then syncs with an empty layers list and asserts `removeLayer` is called for both companion layers and `removeSource` for the source.

All 81 tests in the three targeted files pass. Typecheck (`tsc -b --noEmit`) is clean.

---

_Fixed: 2026-05-28T11:17:45Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
