---
gsd_state_version: 1.0
milestone: v1034
milestone_name: Raster Stretch & Colormap Completion
status: verifying
stopped_at: Phase 1152 Plan 01 complete — TESTDATA-01 satisfied; fixture dataset_id 4767fc35-f6d6-4985-a28e-aecb158fbc1b
last_updated: "2026-05-29T23:30:00.000Z"
last_activity: 2026-05-29
progress:
  total_phases: 10
  completed_phases: 1
  total_plans: 1
  completed_plans: 1
  percent: 10
---

# State

## Current Position

Phase: 1152 (Single-Band Raster Fixture) — COMPLETE
Plan: 1 of 1 (done)
Status: TESTDATA-01 satisfied — fixture ingested, is_dem=false, band_count=1, idempotent
Last activity: 2026-05-29

```
Phase progress: [ 1152 ][ 1153 ][ 1154 ][ 1155 ]
                [ DONE][      ][      ][      ]
                25% complete (1 of 4 phases)
```

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-29)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1152 — Single-Band Raster Fixture

## Last Shipped Milestone

**Version:** v1033 Builder Terrain, Label & Render-Mode QA
**Shipped:** 2026-05-29
**Phases:** 1148-1151 (4 phases, 7 plans, 9/9 reqs satisfied)
**Tag:** local `v1033` · CHANGELOG `[1.8.0]`
**Milestone audit:** `.planning/milestones/v1033-MILESTONE-AUDIT.md` (`tech_debt` — 9/9 reqs; integration CLEAN 9/9 links + 4/4 E2E flows; 0 blockers)
**Archive:** `.planning/milestones/v1033-ROADMAP.md` + `v1033-REQUIREMENTS.md`
**Delivered:** DEM `render_mode:'terrain'` strip-on-load fixed (3D terrain restores on fresh load; raster "Render as" no longer reverts) + layer-list label indicator + point render-as consolidation + DEM hillshade dual-consumer guard + bounded band-stats cache. Orchestrator Playwright MCP close-gate on both ADK sample maps (0 console errors each).

## Current Milestone: v1034 Raster Stretch & Colormap Completion

**Goal:** Finish the half-done raster stretch/colormap feature — add full per-band multi-band stretch, make percentile/σ bounds configurable, seed a real single-band raster fixture to actually verify the colormap/stretch UI, and clear the v1033 builder dead-code/note tech debt.

**Phases:**

- [ ] 1152: Single-Band Raster Fixture (TESTDATA-01)
- [ ] 1153: Backend — Multi-Band Stretch + Configurable Bounds (RASTER-STRETCH-03 backend, SPIKE-01, RASTER-STRETCH-UI-01 backend)
- [ ] 1154: Frontend Controls + Cleanup (RASTER-STRETCH-03 frontend, RASTER-STRETCH-UI-01 frontend, RASTER-STRETCH-UI-02, CLEANUP-01)
- [ ] 1155: Close-Gate (VERIFY-01, QA-01)

**Key constraint:** SPIKE-01 is the first task of Phase 1153, not its own phase. If Titiler 2.0.2 does not return `percentile_N` keys for arbitrary `p=N` params, escalate before writing any configurable-bounds backend code.

## Accumulated Context

### Decisions (forward-relevant; full milestone log in archives)

- **RENDER_MODES allowlist (v1033 RESOLVED):** `RENDER_MODES` (`frontend/src/lib/normalize-style-config.ts:92`) now includes all editor-emittable modes incl. `'terrain'` + `'image'`; the `StyleConfig['render_mode']` union (`frontend/src/types/api.ts`) matches. A round-trip + completeness guard test prevents silently dropping a mode again. `DEMEditorScene` no longer casts at the boundary (BSR-09 closed). `api.ts` is hand-maintained; `style_config` is opaque jsonb on the backend — render-mode changes are frontend-only (no OpenAPI/SDK regen).
- **DEM terrain consumer (v1033):** `applyTerrainConfig` (`BuilderMap.tsx`) requires BOTH map-level `terrain_config.enabled` + `source_dataset_id` AND a layer with `render_mode==='terrain'`. With the normalizer fix, terrain attaches on fresh load.
- **Hillshade dual-consumer guard (v1033 POLISH-02):** `isHillshadeTerrainBound` (exported from `map-sync.ts`) skips the hillshade raster-dem consumer + shows a DEM-editor note when a DEM powers an active terrain source. Inactive when terrain is off, so the primary hillshade path is unaffected. The raw `backfillBorder` error is a MapLibre limitation with non-uniform DEM tiles in the terrain+hillshade dual-consumer case only.
- **Label indicator predicate (v1033):** layer "has labels" ⇔ `!!label_config?.column && render_mode not heatmap/symbol` — the SAME gate `map-sync.ts` uses to render labels. `StackRow` indicator mirrors it.
- **Raster stretch (v1032):** `percentile`/`stddev` compute a stats-based Titiler rescale via `/cog/statistics` (cached). `_band_stats_cache` is now an `LRUCache(maxsize=256)` (v1033 HYG-01). Not applied to DEM. Multi-band = current milestone RASTER-STRETCH-03.
- **band_count (v1031/v1033):** `band_count=None` on the `get_dataset_meta` path (shows "1 band" for RGB ortho — cosmetic; colormap correctly hidden for imagery). Tracked as Future RASTER-META-01.
- **Fixture dtype trap (v1034 critical):** `cog.py:85` sets `is_dem=True` for any `band_count==1 AND float dtype`. Fixture MUST be uint8 or uint16. Verify `is_dem=false` after ingest before any UI smoke.
- **Cache key extension (v1034 critical):** `_band_stats_cache` key must be `(open_path, pmin, pmax)` before the configurable-bounds backend lands. Without this, different pmin/pmax values serve stale p2/p98 stats from cache.
- **Cluster adapter (carried):** intentionally keeps raw `map.setFilter` for the compound `combineFilter` shape — NOT migrated to `syncLayerFilter`.
- **Fill extrusion companion (carried):** no `layout.visibility` block at `addLayers` add-time; controlled via `syncVisibility`. Documented in `fill-adapter.test.ts`.
- **SF-MCP-01 (carried from v1030):** `chat_actions.py:_collect_chat_action()` never emits rows on `show_query_result` for non-spatial queries; frontend inline card ready but backend wiring still missing.
- **TESTDATA-01 fixture (v1034 Phase 1152 DONE):** `GRAY_50M_SR.tif` ingested via `ingest_raster_fixture()` in `scripts/seed-natural-earth.py`. `dataset_id=4767fc35-f6d6-4985-a28e-aecb158fbc1b`, `band_count=1`, `is_dem=false`. Idempotent. PITFALL: upload the `.tif` extracted from the zip (not the zip directly) — `_stamp_raster_metadata` gates raster detection on `.tif`/`.tiff` filename extension.
- **Raster seed filename resolution (v1034):** `RASTER_FIXTURE` has two filename keys: `filename` (CDN zip download/cache key = `GRAY_50M_SR.zip`) and `tif_filename` (uploaded to API / stored as `source_filename` = `GRAY_50M_SR.tif`). Idempotency check uses `tif_filename`.

### Pending Todos

None active.

### Blockers/Concerns

- **CI-01-v1030 billing prerequisite (carry-forward from v1023):** Operator must resolve GH Actions billing at https://github.com/organizations/geolens-io/settings/billing before the `pytest-parallel-isolation` CI gate can live-verify GREEN. Standing ops blocker — unblock independently of milestone execution.
- **SPIKE-01 (Phase 1153 gate):** Titiler 2.0.2 `p=` arbitrary percentile support is unverified end-to-end against the pinned container. Must confirm before writing any configurable-bounds backend code.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| raster-meta | `band_count` cosmetic ("1 band" for RGB ortho on get_dataset_meta path) — RASTER-META-01 | Future | v1033 |
| builder-edge | `onRenderModeChange` dead member + `hillshadeTerrainNote` unreachable advisory | In scope v1034 CLEANUP-01 | v1033 audit |
| ci-live-verify | `pytest-parallel-isolation` gate live-verify on real GitHub Actions (billing block) | Carried forward as CI-01-v1030 | v1023 Phase 1100 degraded close |
| nyquist | VALIDATION.md formalization for 1148-1151 | Optional; coverage strong via close-gate | v1033 milestone audit |

## Session Continuity

Last session: 2026-05-29T23:25:05.409Z
Stopped at: v1034 roadmap created; STATE.md initialized at Phase 1152
Resume file: None

## Operator Next Steps

- **Phase 1152 DONE.** TESTDATA-01 satisfied — `GRAY_50M_SR.tif` fixture in catalog (id `4767fc35-f6d6-4985-a28e-aecb158fbc1b`), `is_dem=false`, `band_count=1`, idempotent.
- **Next:** Phase 1153 — Backend Multi-Band Stretch + Configurable Bounds.
- **Phase 1153 note:** SPIKE-01 is the first task — run `curl http://localhost:8000/cog/statistics?url=<path>&p=5&p=95` against the live Titiler container and inspect response keys before writing any configurable-bounds code.
- **MCP note:** Orchestrator drives all live Playwright MCP (Phase 1155). Executor subagents lack `mcp__playwright__*` access — see project memory `playwright-mcp-orchestrator-only`.
- Phase directories for v1033 (1148-1151) should be in `milestones/v1033-phases/` after cleanup.
