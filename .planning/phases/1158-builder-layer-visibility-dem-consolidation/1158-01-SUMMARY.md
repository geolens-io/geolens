---
phase: 1158-builder-layer-visibility-dem-consolidation
plan: "01"
subsystem: ui
tags: [maplibre, builder, dem, terrain, visibility, layer-stack]

requires:
  - phase: 1157-backend-export-access-route-hygiene
    provides: clean backend routes (EXP-01, API-01) that frontend builder relies on

provides:
  - BLDR-01: reorderBasemapAboveData skips raster-type layers so imagery basemaps never float above data at position='top'
  - BLDR-02: applyTerrainConfig gates on effectiveTerrainEnabled (enabled AND demLayer.visible); terrainLayerKey encodes visible so the terrain effect re-runs on toggle
  - BLDR-03: terrain-mode DEM layer is filtered from the UnifiedStackPanel rendered/sortable stack via isDemTerrainVisualSuppressed (only hillshade/image DEM rows appear)
  - BLDR-04: color-relief companion addLayer carries layout.visibility derived from input.visible, hiding with its parent

affects: [1158-02, 1160-live-playwright-mcp-close-gate]

tech-stack:
  added: []
  patterns:
    - "isDemTerrainVisualSuppressed used both at map-sync render suppression and at UnifiedStackPanel row filter for source-of-truth DEM suppression"
    - "effectiveTerrainEnabled pattern: compute derived bool from (terrainConfig.enabled AND demLayer.visible) before gating map.setTerrain"
    - "terrainLayerKey as reactivity hook: encode per-layer visible in the key string so terrain effect re-runs on visibility change without a separate dep"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/map-sync.ts
    - frontend/src/components/builder/color-relief-sync.ts
    - frontend/src/components/builder/BuilderMap.tsx
    - frontend/src/components/builder/UnifiedStackPanel.tsx

key-decisions:
  - "BLDR-01: add layer.type === 'raster' continue guard after isLandLayer/isWaterLayer in reorderBasemapAboveData; data-source skip at :311 already handled data layers, so any remaining raster is a non-data basemap raster — no source comparison needed"
  - "BLDR-02: use demLayer?.visible !== false (default-visible semantics) so a layer with undefined visible still attaches terrain; extend terrainLayerKey with :${String(layer.visible)} rather than adding a new dep to the terrain effect dep array"
  - "BLDR-03: filter via visibleStackLayers memo in UnifiedStackPanel; raw layers prop forwarded to BulkActionBar + activeLayer drag-overlay so reorder/bulk/drag still see full layer set; no 'Copy N of M' badge (out of scope per plan)"
  - "BLDR-04: layout.visibility placed before paint in addLayer object; because syncColorReliefLayer always does remove+add (Pitfall 1), one layout field covers initial add and all subsequent syncs"

patterns-established:
  - "visibleStackLayers memo pattern: filter the raw layers prop before feeding sortableIds/childrenByGroup/render loop, while forwarding raw layers to child components that need the complete set"

requirements-completed: [BLDR-01, BLDR-02, BLDR-03, BLDR-04]

duration: 3min
completed: 2026-05-30
---

# Phase 1158 Plan 01: Builder Layer Visibility & DEM Consolidation Source Fixes

**Four lowest-touch MapLibre rendering/visibility bug fixes: raster-basemap ordering skip, terrain eye toggle via effectiveTerrainEnabled, terrain-mode DEM row suppression in stack, and color-relief companion visibility threading**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-30T18:28:17Z
- **Completed:** 2026-05-30T18:31:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- BLDR-01 + BLDR-04: `reorderBasemapAboveData` now skips `layer.type === 'raster'` so imagery basemaps stay below data layers at `position='top'`; `syncColorReliefLayer` threads `input.visible` into `layout.visibility` so the hypsometric tint companion hides with its parent DEM layer
- BLDR-02: `applyTerrainConfig` computes `effectiveTerrainEnabled` from `terrainConfig.enabled AND demLayer?.visible !== false`, gating `map.setTerrain(null)` when the layer eye is off; `terrainLayerKey` extended with `:${String(layer.visible)}` so the terrain effect re-runs on every visibility toggle
- BLDR-03: `UnifiedStackPanel` imports `isDemTerrainVisualSuppressed` from `./map-sync` and builds a `visibleStackLayers` memo that filters terrain-mode DEM layers from `sortableIds`, `childrenByGroup`, `isEmpty`, the count badge, and the JSX render loop — while keeping the raw `layers` prop flowing to `BulkActionBar` and the drag-overlay lookup

## Task Commits

1. **Task 1: BLDR-01 + BLDR-04 (map-sync.ts, color-relief-sync.ts)** - `80e3d2da` (fix)
2. **Task 2: BLDR-02 (BuilderMap.tsx)** - `3428c117` (fix)
3. **Task 3: BLDR-03 (UnifiedStackPanel.tsx)** - `1d6d48f0` (fix)

## Files Created/Modified

- `frontend/src/components/builder/map-sync.ts` — BLDR-01: added `if (layer.type === 'raster') continue` guard in `reorderBasemapAboveData`
- `frontend/src/components/builder/color-relief-sync.ts` — BLDR-04: added `layout: { visibility: input.visible ? 'visible' : 'none' }` to `syncColorReliefLayer` addLayer call
- `frontend/src/components/builder/BuilderMap.tsx` — BLDR-02: `effectiveTerrainEnabled` guard in `applyTerrainConfig`; `:${String(layer.visible)}` appended to `terrainLayerKey`
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — BLDR-03: import `isDemTerrainVisualSuppressed`, add `visibleStackLayers` memo, replace `layers` with `visibleStackLayers` in three stack-shaping consumers

## Decisions Made

- Followed audited lowest-touch shapes from PATTERNS.md exactly; no surrounding code refactored
- `visibleStackLayers` memo kept narrow scope — only three stack-shaping consumers updated; BulkActionBar and drag-overlay stay on raw `layers` to preserve reorder/bulk/drag correctness
- No "Copy N of M" duplicate-disambiguation badge added (explicitly out of scope per BLDR-03 action note)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All four fixes applied cleanly; `npm run typecheck` exited 0 after each task.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 1158-02 (unit test pins for BLDR-01/02/03/04) can now proceed — source changes are committed and typecheck-clean
- Phase 1160 Playwright MCP close-gate (QA-01 b/c/d) will live-verify raster-basemap ordering, terrain toggle, and single-DEM-row behavior

## Threat Flags

None. Pure client-side MapLibre rendering/visibility changes — no new network endpoints, auth surfaces, data egress, or trust boundaries introduced.

## Self-Check: PASSED

- `80e3d2da` exists in git log: confirmed
- `3428c117` exists in git log: confirmed
- `1d6d48f0` exists in git log: confirmed
- `frontend/src/components/builder/map-sync.ts` modified: confirmed
- `frontend/src/components/builder/color-relief-sync.ts` modified: confirmed
- `frontend/src/components/builder/BuilderMap.tsx` modified: confirmed
- `frontend/src/components/builder/UnifiedStackPanel.tsx` modified: confirmed

---
*Phase: 1158-builder-layer-visibility-dem-consolidation*
*Completed: 2026-05-30*
