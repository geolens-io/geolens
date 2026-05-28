# Phase 1144: Contour Spike - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

An evidence-backed audit exists that describes exactly why the `maplibre-contour` worker emits ~28 MapLibre error events on enable and recommends harden or cut with a rough effort estimate for the harden path. Audit-only phase — NO production code changes (a temporary `CONTOUR_CONTROL_ENABLED` flip for reproduction must be reverted before the phase closes).

Requirement: **CONTOUR-01**.
</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

Known facts entering the spike (from code read):
- Trigger path: `map-sync.ts:919` calls `syncContourLayer` for every DEM layer (`is_dem===true`) on every sync; it no-ops unless paint has `_contour-enabled: true`. The UI toggle that sets that key is gated off by `CONTOUR_CONTROL_ENABLED=false` (`DEMEditorScene.tsx:28`).
- `syncContourLayer` body is fully `try/catch`-wrapped (`contour-sync.ts:125-218`), so the ~28 errors are NOT synchronous throws — they are async MapLibre `error` events emitted by the `maplibre-contour` worker while fetching/decoding DEM tiles via the generated `contour://` protocol URL, and/or by the vector source (`source-layer: 'contours'`).
- `DemSource` is configured with `encoding: 'mapbox'` (Terrain-RGB) + `worker: true` (`contour-sync.ts:88-93`). GeoLens DEM tiles are served by Titiler; if they are not Mapbox Terrain-RGB encoded, the worker decode fails per tile.
- The `addProtocol`-as-Map-instance bug was already fixed (`716b1927`); that is NOT the remaining root cause.

Reproduction target: builder map `8dd6a129-8eb0-4ba9-b421-716c83b160dd` ("Adirondack High Peaks — 3D Relief"), DEM dataset `raster_5ef1387b8bde45e3` (`catalog.raster_assets.is_dem=true`).

Reproduction method: frontend is Vite dev (`Dockerfile.dev`, source bind-mount, HMR). Temporarily flip `CONTOUR_CONTROL_ENABLED=true`, enable contour via the live UI, capture console + MapLibre error events via Playwright MCP, inventory by category, then revert the flag.
</decisions>

<code_context>
## Existing Code Insights

- `frontend/src/components/builder/contour-sync.ts` (219 LOC) — companion line-layer sync + `maplibre-contour` DemSource registry.
- `frontend/src/components/builder/map-sync.ts:918-919` — call site.
- `frontend/src/components/builder/DEMEditorScene.tsx:28,424-425` — `CONTOUR_CONTROL_ENABLED` gate + UI block.
- `frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx:534-619` — 5 `it.skip` dormant tests.
- `frontend/package.json:44` — `maplibre-contour: ^0.1.0` (pre-1.0).
</code_context>

<specifics>
## Specific Ideas

Output: `.planning/audits/CONTOUR-WORKER-v1032.md` with (1) reproduced error inventory by category, (2) root-cause analysis of the worker/isoline/tile path distinct from the fixed `716b1927` bug, (3) harden-or-cut recommendation, (4) rough effort estimate for the harden path. Default bias per REQUIREMENTS.md: cut if hardening is not clearly cheap.
</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped.
</deferred>
