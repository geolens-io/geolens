---
gsd_state_version: 1.0
milestone: v1035
milestone_name: Builder, Maps & Export Bug Sweep
status: executing
stopped_at: "Session resumed — v1035 roadmap in place (Phases 1156-1160, 0 plans); next action `/gsd:plan-phase 1156` (SEC-01)"
last_updated: "2026-05-30T19:17:49.449Z"
last_activity: 2026-05-30
progress:
  total_phases: 10
  completed_phases: 3
  total_plans: 8
  completed_plans: 7
  percent: 30
---

# State

## Current Position

Phase: 1159 (Maps/Search UI & Blob Hygiene) — EXECUTING
Plan: 2 of 2
Next Phase: 1158 (Builder Layer Visibility & DEM Consolidation)
Status: Ready to execute
Last activity: 2026-05-30

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-30)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1159 — Maps/Search UI & Blob Hygiene

## Last Shipped Milestone

**Version:** v1034 Raster Stretch & Colormap Completion
**Shipped:** 2026-05-30
**Phases:** 1152-1155 (4 phases, 5 plans, 8/8 reqs satisfied)
**Tag:** local `v1034`
**Milestone audit:** `.planning/milestones/v1034-MILESTONE-AUDIT.md` (`tech_debt` — 8/8 reqs; integration CLEAN; CLEAR-TO-TAG)
**Archive:** `.planning/milestones/v1034-ROADMAP.md` + `v1034-REQUIREMENTS.md`
**Delivered:** Per-band multi-band stretch + configurable percentile/σ bounds + seeded single-band raster fixture (`GRAY_50M_SR.tif`). The Playwright MCP close-gate found + fixed two latent v1031/v1032 defects: raster colormap/stretch controls were in an unmounted component (extracted shared `RasterStretchControls`) and builder-private paint keys 422'd on save (allowlisted into `style_config.builder` + re-injected on load). Feature now works end-to-end (live-verified: set → save 200 → reload retains + tiles re-render). **Carry-forward:** band_count hydration on fresh-add (section appears only after first save+reload) — minor UX.

## Current Milestone: v1035 Builder, Maps & Export Bug Sweep

**Goal:** Close the defects surfaced by quick task 260530-ezw + its production-readiness QA pass — one anonymous data leak (security blocker), four map-builder rendering/visibility bugs, an export-access gap, an app-wide console error, and supporting hygiene/regression coverage. Fixes to existing files only — no new deps, migrations, or user-facing features. Phase numbering continues from v1034's 1155. GitHub issues: #120, #121, #122, #123, #124, #125.

**Phases:**

- [x] 1156: Vector-Tile Egress Authorization (SEC-01) — security blocker, ships first
- [x] 1157: Backend Export Access + Route Hygiene (EXP-01, EXP-02, API-01)
- [ ] 1158: Builder Layer Visibility & DEM Consolidation (BLDR-01, BLDR-02, BLDR-03, BLDR-04)
- [ ] 1159: Maps/Search UI & Blob Hygiene (MAPS-01, MAPS-02, HYG-01)
- [ ] 1160: Live Playwright MCP Close-Gate (QA-01)

**Key constraints:**

- **SEC-01 is a real anonymous data leak** (live-proven: 1842 bytes of MVT served to anon for a public-unpublished dataset). Sequence Phase 1156 first; the raster path (`tiles/router.py:438,467`) is the correct model to mirror across the four vector entry points (`_authorize_vector_tile_request` :1053, `_DatasetMeta`/`_resolve_dataset_meta` :1015, `get_tile_token` :866, `get_tile_tokens_batch` :939, `cluster_tile_endpoint` :1130).
- **EXP-02 needs a draft/ready vector dataset** — none exists in the dev DB; seed or construct one in the regression test.
- **Orchestrator drives all live Playwright MCP** (Phase 1160). Executor subagents lack `mcp__playwright__*` access — see project memory `playwright-mcp-orchestrator-only`.

## Accumulated Context

### Decisions (forward-relevant; full milestone log in archives)

- **Anonymous-access contract (canonical):** `can_access_dataset()` (`backend/app/platform/extensions/defaults.py:93`) returns `visibility=='public' AND record_status=='published'` for `user is None` (`:109-110`); query-level equivalent is `filter_visible()` anon branch (`:61-65`). Wrappers: `check_dataset_access_or_anonymous()` / `check_dataset_access()` (`backend/app/modules/catalog/authorization.py:75,100`). SEC-01 + EXP-01 must route anonymous through these (or the inline status-aware 3-branch check), not visibility-only.
- **COG-download anon reference (for EXP-01):** `download_cog` (`backend/app/modules/catalog/datasets/api/router_export.py:354`) uses `_resolve_download_user` (`:254`, returns None for valid no-sub download token) then branches on `user is None` → `check_dataset_access_or_anonymous` + public-visibility guard (`:385-407`), keeping the capability check only on the authenticated branch. Mirror this for vector export (`processing/export/router.py:47`).
- **BLDR-02 terrain toggle fix shape (audited):** in `applyTerrainConfig` (`BuilderMap.tsx:~394`, `demLayer` in scope at `:389`) compute `effectiveTerrainEnabled = terrainConfig.enabled && demLayer.visible`; extend `terrainLayerKey` (`:413-418`) with `:${String(layer.visible)}` so the effect re-runs. Lowest-touch option.
- **BLDR-04 color-relief fix shape (audited):** `syncColorReliefLayer` (`color-relief-sync.ts:97-112`) — `AdapterLayerInput` already carries `visible` (`types.ts:23`) and the call site (`map-sync.ts:957-959`) passes `adapterInput` with `visible` populated, so set `layout:{visibility: input.visible ? 'visible':'none'}` on add + on sync. No signature change needed.
- **BLDR-01 fix shape (audited):** `reorderBasemapAboveData` (`map-sync.ts:298-322`) currently skips only vector base fills (`isLandLayer`/`isWaterLayer`/`background`); extend to skip non-data raster basemap layers (`layer.type==='raster'` whose source ≠ data `sourcePrefix`).
- **BLDR-03 (audited):** `UnifiedStackPanel` renders 1 `StackRow` per `MapLayerResponse` (no synthesis); three DEM rows = the DEM dataset added as 3 separate layer records. Recommended: one DEM row + render-mode pill, terrain as map-level setting (no separate terrain layer row); reuse the `MapStackDuplicateMetadata` "Copy N of M" logic (`map-stack.ts:299-337`, currently unshown). `map-stack.ts`/`buildMapStack` is dead in the live UI (only `normalize-saved-map.ts` + tests reference it).
- **MAPS-01:** duplicate `ReactDOMClient.createRoot()` error fires app-wide (3× per load on home/search, `/maps`, dataset detail) — find the offending `createRoot()` call and cache/reuse the root (or unmount before re-rooting). Out of scope: broader StrictMode/HMR mount refactor.
- **API-01:** add `/collections/{id}/items/` trailing-slash dual-shape alias per the Phase 1092 ROUTE-01 stacked-decorator pattern (`redirect_slashes=False` at app level). Frontend uses no-slash today.
- **SEC-01 fix approach (1156-01):** Option A used for `_authorize_vector_tile_request` — thread `user: Identity | None` as keyword param, add `else` status guard mirroring raster lines 465-479; both token endpoints use `check_dataset_access_or_anonymous` one-call form; batch endpoint uses `try/except HTTPException` to preserve per-key error accumulation.

### Pending Todos

None active.

### Blockers/Concerns

- **CI-01-v1030 billing prerequisite (carry-forward from v1023):** Operator must resolve GH Actions billing at https://github.com/organizations/geolens-io/settings/billing before the `pytest-parallel-isolation` CI gate can live-verify GREEN. Standing ops blocker — unblock independently of milestone execution.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260530-ezw | Verify download links/tiles/vector (all working); fix basemap labels-only reorder + thumbnail blob ERR_FILE_NOT_FOUND + clarify import-style creates new map | 2026-05-30 | 452c5ada | [260530-ezw-address-download-links-tile-services-vec](./quick/260530-ezw-address-download-links-tile-services-vec/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| raster-meta | `band_count` cosmetic ("1 band" for RGB ortho on get_dataset_meta path) — RASTER-META-01 | Future | v1033 |
| ci-live-verify | `pytest-parallel-isolation` gate live-verify on real GitHub Actions (billing block) | Carried forward as CI-01-v1030 | v1023 Phase 1100 degraded close |
| public-export-policy | Per-deployment toggle to restrict anonymous public file export | Out of scope (product decision) | v1035 |
| builder-dem-dedupe | BLDR-03 "Copy N of M" duplicate-badge for near-identical hillshade DEM rows (surface `MapStackDuplicateMetadata`) — deferred as net-new UI vs the v1035 no-new-features constraint; the phantom terrain-row suppression (the core fix) shipped | Out of scope (new UI surface) | v1035 Phase 1158 |

## Session Continuity

Last session: 2026-05-30T19:17:49.444Z
Stopped at: Session resumed — v1035 roadmap in place (Phases 1156-1160, 0 plans); next action `/gsd:plan-phase 1156` (SEC-01)
Resume file: None

## Operator Next Steps

- **Phase 1157 complete.** EXP-01 fix (`f24b74b9`) + API-01 alias (`3ff2e0a6`) in Plan 01. EXP-02 + API-01 regression tests (`f3509867`) in Plan 02 — 9/9 passing.
- **Next:** Execute Phase 1158 (BLDR-01 raster basemap ordering, BLDR-02 terrain toggle, BLDR-03 DEM row consolidation, BLDR-04 color-relief visibility).
- **MCP note:** Orchestrator drives all live Playwright MCP (Phase 1160). Executor subagents lack `mcp__playwright__*` access — see project memory `playwright-mcp-orchestrator-only`.
