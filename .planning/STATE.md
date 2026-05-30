---
gsd_state_version: 1.0
milestone: v1035
milestone_name: Builder, Maps & Export Bug Sweep
status: v1035 shipped 2026-05-30 — 12/12 reqs; closed + archived; between milestones (awaiting /gsd:new-milestone)
stopped_at: v1035 closed; STATE reconciled; between milestones (2026-05-30)
last_updated: "2026-05-30T21:45:00.000Z"
last_activity: 2026-05-30 — v1035 milestone closed + STATE.md body reconciled
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 9
  completed_plans: 9
  percent: 100
---

# State

## Current Position

Phase: — (no active milestone; v1035 SHIPPED — all 5 phases 1156-1160 complete, tagged `v1035`)
Plan: —
Next Phase: — (start next milestone via `/gsd:new-milestone`)
Status: Between milestones. v1035 shipped 2026-05-30 — 12/12 reqs; close-gate passed; audit `tech_debt`; carry-forward BLDR-TILE-RACE
Last activity: 2026-05-30 — v1035 milestone closed + STATE.md reconciled

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-30)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Between milestones — v1035 shipped; next milestone not yet started. Run `/gsd:new-milestone`.

## Last Shipped Milestone

**Version:** v1035 Builder, Maps & Export Bug Sweep
**Shipped:** 2026-05-30
**Phases:** 1156-1160 (5 phases, 9 plans, 12/12 reqs satisfied)
**Tag:** local `v1035`
**Milestone audit:** `.planning/milestones/v1035-MILESTONE-AUDIT.md` (`tech_debt` — 12/12 reqs; integration CLEAN; CLEAR-TO-TAG)
**Archive:** `.planning/milestones/v1035-ROADMAP.md` + `v1035-REQUIREMENTS.md` + `v1035-phases/` (1156-1160)
**Delivered:** Closed the defects surfaced by quick task 260530-ezw + its production-readiness QA pass. **SEC-01** (blocker): anonymous vector-tile data leak closed across all 5 entry points — vector `.pbf` + single/batch tile-token + cluster endpoints now gate on `visibility=='public' AND record_status=='published'`, mirroring the raster path (live: anon 404 for public+internal). **EXP-01:** anonymous export of public+published datasets, all formats (live: 200, 4 MB) + **EXP-02** allow/deny regression matrix (`test_export_access.py`). **API-01:** `/collections/{id}/items/` trailing-slash dual-shape alias. **BLDR-01** raster basemap stays below data; **BLDR-02** terrain eye toggles 3D (`effectiveTerrainEnabled = terrainConfig.enabled && demLayer.visible`); **BLDR-03** phantom triple-DEM terrain row suppressed (clean 7-row stack); **BLDR-04** color-relief/hypsometric tint honors parent visibility. **MAPS-01** app-wide duplicate `createRoot()` console error killed (dev-HMR cached-root guard); **MAPS-02** search-page quicklook blob-url eviction→revoke; **HYG-01** `registerBlobUrlRevocation` moved out of render into `useEffect`. **QA-01:** orchestrator-driven live Playwright MCP close-gate (all 6 items; SEC-01+EXP-01 round-tripped live: flip-to-internal→404→revert→200). 2 BLOCKERs caught + fixed inline — (1156) `port.check_dataset_access_or_anonymous` didn't exist → SEC-01 fix was non-functional at runtime → fixed via direct import + preserved 401-for-private; (1158 CR-01) shift-click range bulk-delete could silently delete the hidden terrain layer record → fixed with `selectableRowIds` filter. Gates: typecheck 0 · vitest 2640 · e2e:smoke:core 31 · e2e:smoke:builder 26 · backend tiles+export 127 · i18n 2 · openapi-check no-drift. No new deps/migrations.

## Carry-Forwards for Next Milestone

- **BLDR-TILE-RACE** (tech_debt) — ~20% transient tile-token 403 in `builder-v1-5` drag-from-catalog (vector `.pbf` fetched before its HMAC sig via `transformRequest`). **Pre-existing** since v1034 (NOT a v1035 regression), non-functional (tiles recover), mitigated `retries: 2`. Proper fix at the token/transformRequest ordering layer.
- **BLDR-03 "Copy N of M" duplicate badge** — surface `MapStackDuplicateMetadata` for near-identical hillshade DEM rows. Deferred as net-new UI vs v1035's no-new-features constraint (the phantom terrain-row suppression — the core fix — shipped).
- **CI-01-v1030** — GH Actions billing prerequisite (standing ops blocker; resolve independently of milestone execution at https://github.com/organizations/geolens-io/settings/billing).

## Accumulated Context

### Decisions

v1035 fix-shape decisions are shipped and archived in `.planning/milestones/v1035-phases/` (1156-1160). The canonical anonymous-access contract remains forward-relevant: `can_access_dataset()` (`backend/app/platform/extensions/defaults.py:93`) returns `visibility=='public' AND record_status=='published'` for `user is None`; wrappers `check_dataset_access_or_anonymous()` / `check_dataset_access()` (`backend/app/modules/catalog/authorization.py:75,100`). SEC-01 + EXP-01 both route anonymous through these — the established model to mirror for any future public-egress surface.

### Pending Todos

None active.

### Blockers/Concerns

- **CI-01-v1030 billing prerequisite (carry-forward from v1023):** Operator must resolve GH Actions billing before the `pytest-parallel-isolation` CI gate can live-verify GREEN. Standing ops blocker — unblock independently of milestone execution.

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
| builder-dem-dedupe | BLDR-03 "Copy N of M" duplicate-badge for near-identical hillshade DEM rows (surface `MapStackDuplicateMetadata`) — net-new UI vs v1035 no-new-features constraint; phantom terrain-row suppression (core fix) shipped | Carried forward | v1035 Phase 1158 |

## Session Continuity

Last session: 2026-05-30 (resume + STATE reconcile)
Stopped at: v1035 closed; STATE.md body reconciled to between-milestones state; ready for `/gsd:new-milestone`
Resume file: None

## Next Steps

- **v1035 is shipped and closed** (tag `v1035`, 12/12 reqs, audit `tech_debt`). No active milestone.
- **Start the next milestone:** `/gsd:new-milestone` — it will pull from the backlog + carry-forwards above.
- **Backlog seeds:** `.planning/backlog/` — `qa-260530-egress-gating`, `qa-260530-builder-visibility`, `quick-260530-ezw-lowpri`, `ingest-audit-20260519-findings`, `v13.12-low/medium-findings`.
- **MCP note:** Orchestrator drives all live Playwright MCP. Executor subagents lack `mcp__playwright__*` access — see project memory `playwright-mcp-orchestrator-only`.
- **Note:** The 5 `999.x` dirs in `.planning/phases/` are backlog stubs — never auto-execute (see project memory `completing_milestone_in_geolens`).
