---
phase: 1133-audit-first-builder-walkthrough
plan: 04
subsystem: ui
tags: [builder, maplibre, layer-adapters, dnd-kit, grep-audit, contracts]

requires:
  - phase: 1133-01
    provides: Phase walkthrough audit doc with Invariant Grep Checks stub
  - phase: 1133-02
    provides: AI consumer-gating matrix populated
  - phase: 1133-03
    provides: todo.md staleness pass populated

provides:
  - "Invariant Grep Checks section in 1133-BUILDER-WALKTHROUGH-AUDIT.md: 4 grep guards verified PASS on main post-3ed5ceb3"
  - "WALK-04 satisfied: v1008/v1026/v1027 adapter-boundary contracts proven clean"
  - "71 setPaintProperty/setLayoutProperty hits classified with rationale; 0 FAIL rows"
  - "New documented exceptions enumerated: reconciler hooks (use-builder-layers.ts, use-layer-map-sync.ts visibility/opacity fast-paths) and basemap-style-mutation.ts"

affects:
  - 1136-per-render-mode-editor-polish
  - 1134-map-functionality-smaller-screen
  - any phase that adds setPaintProperty calls in editor components

tech-stack:
  added: []
  patterns:
    - "Grep-guard pattern for contract verification: enumerate all hits, classify each row, require explicit rationale for every exception"
    - "Reconciler-hook fast-path exception: visibility/opacity-only mutations in use-layer-map-sync.ts / use-builder-layers.ts are semantically equivalent to adapter calls but bypass full syncPaint for PERF-04 reasons; Phase 1136 must NOT add analogous shortcuts for new paint properties"

key-files:
  created: []
  modified:
    - ".planning/phases/1133-audit-first-builder-walkthrough/1133-BUILDER-WALKTHROUGH-AUDIT.md"

key-decisions:
  - "Reconciler hooks (use-builder-layers.ts, use-layer-map-sync.ts) classified as new documented exceptions, not FAIL rows: they are the v1026 reconciler layer itself, performing visibility/opacity-only and layout-apply mutations that are semantically equivalent to calling the adapter's corresponding sync method"
  - "basemap-style-mutation.ts:149 classified as documented exception: targets basemap-owned MapLibre style layers only (not data layers), per @vis.gl/react-maplibre v8 imperative pattern"
  - "Grep guards passed 4/4 — no Phase 1134 routing entries generated from this plan"

patterns-established:
  - "Pattern: Invariant grep guard with exception rationale table — classify every hit, PASS with rationale or FAIL with routing; no unclassified hits allowed"

requirements-completed:
  - WALK-04

duration: 4min
completed: 2026-05-27
---

# Phase 1133 Plan 04: Invariant Grep Checks Summary

**Live grep audit of 71 setPaintProperty/setLayoutProperty hits + BuilderLayerAction union + v1011 CTRL-01 disabled.droppable + v1027 add/remove boundary: all 4 guards PASS, 0 FAIL rows, WALK-04 verified clean on main post-3ed5ceb3**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-27T15:19:55Z
- **Completed:** 2026-05-27T15:23:23Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Ran all 4 grep guards live against `frontend/src --include="*.ts*"` on `main` post-`3ed5ceb3`
- Classified all 71 `setPaintProperty`/`setLayoutProperty` hits: 30 in `layer-adapters/`, 6 in `map-sync.ts`, 17 in `label-layer-utils.ts`, 1 in `ViewerMap.tsx`, 16 in reconciler hooks, 1 in `basemap-style-mutation.ts`
- Verified `BuilderLayerAction` union has exactly 1 production dispatch site (`use-builder-layers.ts:1125`); TypeScript union enforces shape at compile time; no ad-hoc layer mutation objects outside union shape
- Verified v1011 CTRL-01 `disabled: { draggable: false, droppable: disableForCatalogNonBasemap }` contract intact in `BasemapGroupRowWrapper` (lines 304-307); no regression of basemap-group as collision target
- Verified v1027 add/remove boundary: all `map.addLayer`, `map.addSource`, `map.removeLayer`, `map.removeSource` calls are in adapters, map-sync.ts, or expected reconciler hooks; no declarative `<Source>`/`<Layer>` components used for vector tiles
- Enumerated 3 new documented exceptions (reconciler-hook fast-paths and basemap sublayer surface) not listed in the Plan 04 pre-acknowledged set; all classified PASS with rationale

## Task Commits

1. **Task 1: Run live grep guards and tabulate every hit with classification** - `bb43b9a3` (docs)

## Files Created/Modified

- `.planning/phases/1133-audit-first-builder-walkthrough/1133-BUILDER-WALKTHROUGH-AUDIT.md` — `## Invariant Grep Checks` stub replaced with 4 fully populated grep guards (71-row hit table, BuilderLayerAction check, dnd-kit droppable check, add/remove boundary check)

## Decisions Made

- Reconciler hooks (`use-builder-layers.ts` `handleBulkVisibility`/`handleBulkOpacity`/`swapLayerOnMap`, `use-layer-map-sync.ts` `handleVisibilityChange`/`handleOpacityChange`/`handleLayoutChange`) classified as documented exceptions rather than FAIL rows. These hooks ARE the v1026 reconciler layer; their inline property mutations are visibility-only / opacity-only / layout-apply fast-paths established in v1010 PERF-04 and v1011. They bypass adapter dispatch for performance (BulkVisibility covers 6 companion IDs atomically; opacity formula for heatmap requires compound `opacity * storedOpacity`). Phase 1136 MUST NOT add analogous shortcuts for new RasterEditor/LineEditor paint sliders — those MUST route through adapter `OWNED_PAINT_PROPERTIES` + `syncPaint`.
- `basemap-style-mutation.ts:149` targets basemap-owned MapLibre style layers only (not data layers); its `safeSetPaint` helper is the correct pattern for basemap sublayer overrides per @vis.gl/react-maplibre v8 imperative workaround.

## Deviations from Plan

None — plan executed exactly as written. No FAIL rows were found; no routing-table entries were added from this plan. The pre-acknowledged documented exceptions (`label-layer-utils.ts`, `ViewerMap.tsx`) were confirmed. Three additional documented exceptions (reconciler hooks, basemap sublayer surface) were enumerated and classified PASS with rationale.

## Issues Encountered

None.

## Known Stubs

None. This is an audit-only plan; no code was written.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Next Phase Readiness

- `1133-BUILDER-WALKTHROUGH-AUDIT.md` is complete: all 5 sections (render-mode findings, AI matrix, todo.md staleness, invariant grep checks) are populated except `## SHARE-08 Disposition` which is owned by Plan 05
- Phase 1136 (per-render-mode editor polish) can use this audit as Pitfall #9 watch: every new RasterEditor/LineEditor/FillEditor slider MUST route through the adapter's `OWNED_PAINT_PROPERTIES` + `syncPaint` contract; any direct `setPaintProperty` in an editor component or outside `layer-adapters/` will constitute a new undocumented exception
- Phase 1134 (map functionality + smaller-screen) has no new routing entries from this plan; existing routing-table rows from Plans 01-03 remain the authoritative backlog

## Self-Check

---

*Phase: 1133-audit-first-builder-walkthrough*
*Completed: 2026-05-27*
