# Phase 1148: Render-Mode Persistence Fix - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); grounded in the v1033 live-MCP audit.

<domain>
## Phase Boundary

DEM and raster layers must restore their saved render mode on every map load. `'terrain'` and `'image'` must survive the style-config normalize round trip so (a) the 3D terrain mesh attaches on fresh load and (b) the raster "Render as" control never silently reverts to Image after save+reload.

Single root cause (validated live + in code — see `.planning/audits/BUILDER-LABEL-RASTER-AUDIT-v1033.md`, findings F1+F2):
- `frontend/src/lib/normalize-style-config.ts:92` — `RENDER_MODES = new Set(['heatmap','hillshade','symbol','arrow','cluster'])` omits `'terrain'` and `'image'`.
- `normalizeRenderMode()` (`:174-188`) returns `undefined` for any value not in that set → `'terrain'` is discarded on every read.
- `frontend/src/types/api.ts:863` — `render_mode?: 'heatmap'|'hillshade'|'symbol'|'arrow'|'cluster'` — union also omits `'terrain'`/`'image'`.
- `frontend/src/components/builder/DEMEditorScene.tsx:22-29` — `DemRenderMode = 'image'|'hillshade'|'terrain'` with a boundary cast + a "BSR-09 follow-up" comment that this phase resolves.
- Downstream: `BuilderMap.tsx:379-411` `applyTerrainConfig()` requires a layer with `style_config.render_mode === 'terrain'` (`:392`); once stripped, terrain never attaches (`setTerrain(null)`).
</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion (grounded by the audit)
- **Fix is frontend-only.** `api.ts` is hand-maintained (no codegen header); backend `style_config` is opaque jsonb and already persists `render_mode:'terrain'` correctly. Do NOT regen OpenAPI/SDK for this union change. `make openapi-check` must still show no drift.
- Add both `'terrain'` and `'image'` to `RENDER_MODES` and to the `StyleConfig['render_mode']` union. (`'image'` is the DEM default and is also currently stripped; including it makes the round trip lossless and removes the implicit-fallback ambiguity.)
- Remove the `DemRenderMode` boundary cast and the BSR-09 follow-up comment in `DEMEditorScene.tsx` now that the union is authoritative. Keep `DemRenderMode` as a domain alias if useful, but it should be assignable to/from `StyleConfig['render_mode']` without casting.
- Preserve all existing normalize behavior for `heatmap`/`hillshade`/`symbol`/`arrow`/`cluster` (no regressions). The heatmap special-case branch (`normalize-style-config.ts:231-238`) must remain intact.
- Verify no other code path treated a missing `render_mode` as semantically "image"; if `getRenderMode()` in DEMEditorScene already defaults absent→image, the now-preserved explicit `'image'` must produce identical UI/behaviour.

### Out of scope
Label indicator (Phase 1149), point-control consolidation + hillshade guard + cache bound (Phase 1150), MCP close-gate (Phase 1151).
</decisions>

<code_context>
## Existing Code Insights

- `frontend/src/lib/normalize-style-config.ts` — `RENDER_MODES` (l.92), `normalizeRenderMode()` (l.174), heatmap branch (l.231).
- `frontend/src/types/api.ts:863` — `StyleConfig['render_mode']` union.
- `frontend/src/components/builder/DEMEditorScene.tsx:22-29,53-56,168-188` — `DemRenderMode`, `getRenderMode()`, mode-change handler.
- `frontend/src/components/builder/BuilderMap.tsx:379-411` — `applyTerrainConfig()` (the consumer that needs `render_mode==='terrain'`).
- Tests: `frontend/src/lib/__tests__/normalize-style-config.test.ts` (round-trip pins go here).
</code_context>

<specifics>
## Specific Ideas

- RMODE-01: after the allowlist+union fix, Map A (`8dd6a129-8eb0-4ba9-b421-716c83b160dd`) fresh load has `map.getTerrain()` non-null + a `terrain-dem` source (verified at close-gate via orchestrator MCP).
- RMODE-02: DEM "Render as" persists across save+reload (editor shows saved mode, not Image).
- RMODE-03: remove cast + BSR-09 comment; add round-trip unit tests for `terrain`/`image`/`hillshade`.
- Add a regression test asserting `RENDER_MODES` contains all six modes the editors can emit (point/line/poly/raster), so a future contributor can't silently drop one again.
</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.
</deferred>
