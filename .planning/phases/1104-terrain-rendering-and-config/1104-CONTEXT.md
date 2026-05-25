# Phase 1104: Terrain Rendering and Config - Context

**Gathered:** 2026-05-24
**Status:** Ready for execution
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Fix terrain tile zoom metadata and terrain settings behavior so the ADK relief map opens and edits without MapLibre terrain errors.
</domain>

<code_context>
## Existing Code Insights

- `backend/app/processing/tiles/router.py` returned hardcoded `maxzoom=18` for every raster token.
- Builder terrain uses a shared `terrain-dem` source from `map-sync.ts`.
- `MapBuilderPage.tsx` attempted live exaggeration updates against `dem-${dataset_id}`, which does not exist.
</code_context>
