# Requirements: GeoLens — v1035 Builder, Maps & Export Bug Sweep

**Defined:** 2026-05-30
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

> Milestone scope: close the defects surfaced by quick task 260530-ezw and its production-readiness QA pass — one anonymous data leak (security blocker), four map-builder rendering/visibility bugs, an export-access gap, an app-wide console error, and supporting hygiene/regression coverage. All items are root-caused with file:line in `.planning/backlog/qa-260530-egress-gating.md`, `.planning/backlog/qa-260530-builder-visibility.md`, and `.planning/backlog/quick-260530-ezw-lowpri.md`. Fixes to existing files only — no new deps, no migrations, no new user-facing features. GitHub issues: #120, #121, #122, #123, #124, #125.

## v1 Requirements

Requirements for this milestone. Each maps to exactly one roadmap phase.

### Security (blocker — fix first)

- [x] **SEC-01** (#124): Vector-tile data and tile tokens are denied to anonymous callers for datasets that are `visibility=public` but **not** `record_status=published`. Today the vector-tile authorization checks visibility only and never consults `record_status`, so an unpublished (draft/ready/internal) public dataset leaks its MVT features + a valid HMAC token to anyone. Fix all four entry points to require `published` for non-owner/non-admin, mirroring the already-correct **raster** path (`backend/app/processing/tiles/router.py:438,467`): `_authorize_vector_tile_request` (`tiles/router.py:1053`), carry `record_status` into `_DatasetMeta`/`_resolve_dataset_meta` (`tiles/router.py:1015`), `get_tile_token` (`tiles/router.py:866`), `get_tile_tokens_batch` (`tiles/router.py:939`), and `cluster_tile_endpoint` (`tiles/router.py:1130`). The anonymous-access contract is `visibility=='public' AND record_status=='published'` (`backend/app/platform/extensions/defaults.py:61-65,109-110`). Pinned by a regression test: anonymous tile-token + `.pbf` request on a public-unpublished dataset → 401/404 (today both return 200 + 1842 bytes of feature data).

### Map Builder

- [x] **BLDR-01** (#120): A raster/imagery basemap stays **below** the data layers when `basemap_position='top'` (it must not occlude the data). `reorderBasemapAboveData` (`frontend/src/components/builder/map-sync.ts:298-322`) currently skips only vector base fills (`isLandLayer`/`isWaterLayer`/`background`); extend it to also skip non-data raster basemap layers (`layer.type==='raster'` whose source is not the data `sourcePrefix`). Pinned by a unit test in `UnifiedStackPanel.basemap-drag.test.tsx` asserting a raster basemap layer is not lifted above data at `position='top'`.
- [x] **BLDR-02** (#123): Toggling the visibility eye on a terrain-mode DEM layer enables/disables the 3D terrain. Terrain is currently driven solely by `terrainConfig.enabled` and ignores the layer's `visible` flag, so the toggle is a no-op (`map.getTerrain()` stays set). Compute `effectiveTerrainEnabled = terrainConfig.enabled && demLayer.visible` in `applyTerrainConfig` (`frontend/src/components/builder/BuilderMap.tsx:~394`; `demLayer` is in scope at `:389`) and add `layer.visible` to `terrainLayerKey` (`:413-418`) so the effect re-runs. Pinned by a test asserting `getTerrain()` becomes null when the terrain DEM layer is hidden and re-attaches when shown.
- [x] **BLDR-03** (#123): The map-builder layer stack shows a single, clearly-labeled row per DEM dataset instead of up to three confusing rows ("DEM hillshade (1m)", "DEM hillshade (1m) rendering", "3D terrain (DEM)"). `UnifiedStackPanel` renders one `StackRow` per `MapLayerResponse` (1:1, no synthesis), so the rows come from the DEM being added as multiple layer records; render modes are mutually exclusive per layer (`DEMEditorScene` pills). Consolidate to one DEM row with the render-mode pill and treat terrain as the map-level setting it already is (no separate terrain layer row); surface duplicate "Copy N of M" metadata to flag accidental double-adds. Keep `e2e:smoke:builder` and vitest green.
- [x] **BLDR-04** (#125): When a hillshade DEM layer with hypsometric tint (color-relief) is toggled off, its color-relief companion is also hidden. `syncColorReliefLayer` (`frontend/src/components/builder/color-relief-sync.ts:97-112`) adds `${layerId}-colorrelief` without a `layout.visibility` and is never passed the parent's visible state. Thread the parent `visible` flag in and apply `setLayoutProperty('${layerId}-colorrelief','visibility', …)` on add and on sync. Pinned by a test asserting the colorrelief companion hides with its parent.

### Export

- [x] **EXP-01** (#121): Anonymous users can export a published **public** dataset in all file formats (gpkg/geojson/shp/csv). `export_dataset_endpoint` (`backend/app/processing/export/router.py:47`) currently uses `require_permission("export")`, forcing auth before any visibility check, so anonymous export of public data 401s. Mirror the anonymous COG-download gate: branch on `user is None` to allow public+published via `check_dataset_access_or_anonymous` + a public-visibility defense-in-depth guard (`router_export.py:354`, `_resolve_download_user:254`); keep the `export` capability check on the authenticated path.
- [x] **EXP-02** (QZ-LP-02): A regression test proves anonymous and non-owner export of **private / restricted / unpublished** datasets remains denied (401/403/404) after EXP-01. (No draft/ready vector dataset exists in the dev DB today — seed or construct one in the test.)

### Maps & Search UI

- [x] **MAPS-01** (#122): The app no longer logs the duplicate `ReactDOMClient.createRoot() on a container that has already been passed to createRoot()` error. It fires app-wide (home/search, `/maps`, dataset detail — 3× per load), indicating the root mount or a shared portal/widget is re-rooting an existing container. Identify the offending `createRoot()` call and cache/reuse the root (or unmount before re-rooting). Pinned by a console-error assertion on at least one route.
- [ ] **MAPS-02** (QZ-LP-01): A regression test covers the search-page quicklook thumbnails (`useQuicklook` + `lib/blob-url-cache.ts`) so the blob-URL revoke-on-eviction fix (quick task 260530-ezw) cannot regress into `ERR_FILE_NOT_FOUND`. (Verified healthy live in this QA pass; this requirement pins it.)

### API Hygiene

- [x] **API-01** (QZ-LP-03): `GET /collections/{id}/items/` (trailing slash) resolves like the no-slash form instead of 404, via a dual-shape alias (stacked decorator per the Phase 1092 ROUTE-01 pattern). Low-risk consistency fix; the frontend uses the no-slash form today.

### Code Hygiene

- [x] **HYG-01** (QZ-LP-04): `registerBlobUrlRevocation(queryClient)` is invoked from an effect (or memoized init) rather than during hook render in `frontend/src/components/maps/hooks/use-map-thumbnail.ts` and `use-quicklook.ts`. Behavior is unchanged (already idempotent via a `WeakSet`); this removes the side-effect-in-render smell.

### QA / Close-Gate

- [ ] **QA-01**: Orchestrator-driven live Playwright MCP close-gate before tagging — verify (a) SEC-01: anonymous vector-tile/token request on a public-unpublished dataset is denied; (b) BLDR-01: raster basemap at `position='top'` keeps data visible; (c) BLDR-02: terrain DEM eye toggles 3D on/off (`getTerrain()` null/set); (d) BLDR-04: hiding a hypso-tinted DEM hides the tint; (e) EXP-01: anonymous CSV/GeoJSON export of a public dataset returns a real body; (f) MAPS-01: target routes show 0 `createRoot` errors. Executor subagents lack `mcp__playwright__*` — orchestrator MUST drive MCP directly (project memory `playwright-mcp-orchestrator-only`). Plus the standard gate: `npm run typecheck` 0, vitest green, `e2e:smoke:builder` green, focused backend tiles/export pytest green, i18n parity, `make openapi-check` no-drift.

## v2 Requirements

Deferred — acknowledged, not in this milestone's roadmap.

_None — this milestone is a contained bug/security sweep._

## Out of Scope

| Feature | Reason |
|---------|--------|
| Public anonymous **file export** as a configurable per-deployment policy | EXP-01 makes published-public anonymously exportable (matching OGC/tiles). A toggle to restrict it is a separate product decision. |
| Server-side map thumbnails (Celery + Pillow) | Pre-existing future task; unrelated to these fixes. |
| Broader builder layer-stack redesign | BLDR-03 is a targeted DEM-row consolidation, not a stack redesign. |
| Deeper StrictMode/HMR refactor beyond eliminating the `createRoot` error | MAPS-01 fixes the duplicate-root call; a broader mount refactor is out of scope. |

## Traceability

Which phases cover which requirements. Filled during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SEC-01 | Phase 1156 | Complete |
| BLDR-01 | Phase 1158 | Complete |
| BLDR-02 | Phase 1158 | Complete |
| BLDR-03 | Phase 1158 | Complete |
| BLDR-04 | Phase 1158 | Complete |
| EXP-01 | Phase 1157 | Complete |
| EXP-02 | Phase 1157 | Complete |
| MAPS-01 | Phase 1159 | Complete |
| MAPS-02 | Phase 1159 | Pending |
| API-01 | Phase 1157 | Complete |
| HYG-01 | Phase 1159 | Complete |
| QA-01 | Phase 1160 | Pending |

**Coverage:**
- v1 requirements: 12 total (11 fixes + 1 close-gate)
- Security blockers: 1 (SEC-01)
- GitHub issues: #120, #121, #122, #123, #124, #125
