# Phase 1103: Builder Mixed Layer Reorder - Context

**Gathered:** 2026-05-24
**Status:** Ready for execution
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Fix the builder reorder path so mixed raster/vector stack changes are reflected in the live MapLibre canvas and durable saved-map order.
</domain>

<code_context>
## Existing Code Insights

- `map-sync.ts` owns MapLibre layer ordering; index `0` is intended to render topmost after `reorderDataGeometry`.
- `use-builder-layers.ts` performs an immediate imperative reorder after drag/drop before the save path persists the new `sort_order`.
- Raster sources are per-layer and can keep stale source metadata unless token source specs are compared.
</code_context>

<specifics>
## Specific Ideas

- Reindex the reordered layer array once and pass that same array to the immediate MapLibre reorder call.
- Add a raster/vector regression test that proves a vector row before a raster row is moved later in MapLibre's layer stack.
- Recompose ADK maps with all vector overlays above DEM/aerial in canonical saved order.
</specifics>
