---
gsd_state_version: 1.0
milestone: v1014
milestone_name: Security Audit Remediation
status: executing
last_updated: "2026-05-20T18:25:48Z"
last_activity: "2026-05-20 — Completed 1061-03: SEC-S05 pgvector /related/ seed visibility fix"
progress:
  total_phases: 9
  completed_phases: 0
  total_plans: 6
  completed_plans: 3
  percent: 0
---

# State

## Current Position

Phase: 1061-security-audit-2026-05-19-remediation
Plan: 03 (complete)
Status: In Progress
Last activity: 2026-05-20 — Completed 1061-03: SEC-S05 pgvector /related/ seed visibility fix

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1013 Ingest Hardening — SHIPPED 2026-05-20 (local tag `v1013` + public tag `v1.3.0`; CHANGELOG [1.3.0]); awaiting milestone archive.

## Last Shipped Milestone

**Version:** v1013 Ingest Hardening
**Shipped:** 2026-05-20
**Phases:** 1057-1060 (4 phases, 15 plans, 10/10 reqs)
**Tag:** `v1013` (local) + `v1.3.0` (public, local-only per A-04 — push with `git push origin v1013 v1.3.0`)
**Archive:** TBD — run `/gsd:milestone-complete v1013` to create `.planning/milestones/v1013-ROADMAP.md`
**Inline fixes (close-gate):** 5 fixes from live MCP re-verify — WFS-04 layer 2 (`5b965cfd`), GPKG-03 3-bug close (`831b691f`), BSE-01 load-time apply (`d24371ed`), e2e contract drift + duplicate camelCase (`a400eb89`), close-gate hygiene + CONTEXT amendment (earlier).

**Previous:** v1012 New-User Hardening + Reupload (shipped 2026-05-19, public tag `v1.2.1`, archive `.planning/milestones/v1012-ROADMAP.md`)

## v1013 Phase Map

| Phase | Name | Goal | Requirements | Complexity | Depends on |
|-------|------|------|--------------|------------|------------|
| 1057 | Service URL Reliability | Fast probe completion, accurate VEC/RAS classification, automatic URI-form CRS detection, successful commit for abstract OGC geometry-type WFS sources | WFS-04 (P0), PROBE-05 (P1), CRS-06 (P2), CLASS-07 (P2) | Medium-large | Nothing (first phase) |
| 1058 | Multi-Layer GPKG Handling | Reupload File path layer-select step + preview schema diff (P0 silent-data-swap fix); Bulk Review multi-commit / ingest-all-layers path | GPKG-01 (P0), GPKG-02 (P1), GPKG-03 (P2) | Medium | Nothing (parallel with 1057) |
| 1059 | Basemap Sublayer Editor (Path B FIX) | Restore per-sublayer styling surface (stroke / casing / zoom / opacity) with real persistence path through `MapBasemapConfig.sublayer_overrides` jsonb-additive; round-trip parity across builder/viewer/shared/embed | BSE-01 (Feature) | Large (3-5 day phase) | Nothing (independent surface) |
| 1060 | Close Gate | Delete 3 smoke repro datasets; all smoke gates green; live MCP re-verify of WFS-04/PROBE-05/GPKG-01/GPKG-02/BSE-01; CHANGELOG `[1.4.0]`; tag v1013 + v1.4.0 | CLEAN-01, CTRL-01 | Small-medium (1-2 inline-fix plan slots reserved) | Phases 1057 + 1058 + 1059 |

**Coverage:** 10 v1013 requirements mapped to 4 phases, 0 unmapped, 0 duplicates.

## Accumulated Context

### Active Milestone Notes

- **Source of truth for all findings:** `.planning/quick/260519-smoke-v1012/SMOKE-v1012-REPORT.md`. Each REQ-ID maps to a Finding (1-7) in that report. Executor agents should reference it during plan-phase.
- **Lead item (P0):** Finding 4 — WFS abstract-geometry-type commit failure (`MultiSurface vs MultiPolygon`). 100% reproducible against `ahocevar.com/geoserver/wfs`; likely affects most GeoServer polygon-heavy users.
- **Basemap Sublayer Path B FIX (BSE-01):** 3-5 day feature phase (Phase 1059). Restores the styling surface left as REMOVE in v1011.1 EMRG-FN-01 with a real persistence path. Likely the largest single phase in this milestone.
- **Multi-Layer GPKG:** Finding 1 (File path silent layer-pickup) is P0 silent-data-swap risk. Service URL preview (Finding 2 sibling) is the design reference — column-level schema diff + schema-change warning + chosen-layer-name surfaced.
- **Service URL probe latency (Finding 5):** Easy win — short-circuit `try_all_probes()` on first success. Current 63s probe completes in ~1.5s after the fix.
- **v1.4.0 public tag** created at CTRL-01 close. Minor bump justified by Findings 1 + 3 multi-layer GPKG affordances + BSE-01 styling persistence.

### Repro Fixtures (kept in catalog for v1013 work, cleaned up at CLEAN-01)

- `ec18b546-d86d-4375-8e1f-8564b6a75687` — file→file→Service-URL reupload sandbox (now v3, 49 wildfire points)
- `54763119-0cf4-448e-a950-81551d090267` — fresh AGO import (49 features, MultiPoint, EPSG:4326)
- `667a6c65-cdbc-4158-87f2-21a7e791ba7c` — fresh OGC API import (25 features, Polygon, CRS override 4326 applied)

### Pending Todos

- **Recreate public repo before launch** (2026-05-05) — `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`. Outside v1013 scope.

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260518-qz1 | Tile cols= opt-in follow-ups (F1 heatmap live, F2 backend integration tests, F3 viewer end-to-end) | 2026-05-18 | 414c7ff7 | Verified | [260518-qz1-tile-cols-opt-in-followups-f1-f2-f3](./quick/260518-qz1-tile-cols-opt-in-followups-f1-f2-f3/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|

(No deferred items at milestone start. v1011.1's deferred BasemapSublayerEditorScene Path B FIX is now in scope as BSE-01 in Phase 1059.)

## v1013 Source: Post-v1012 Live Smoke (2026-05-19)

Orchestrator-driven Playwright MCP sweep against live `localhost:8080` after v1012 archive. **23/23 v1012 reqs verified PASS** + Service URL addendum covering AGO / GeoServer WFS / OGC API / Reupload-via-URL paths. The 7 findings below are the v1013 requirements seed.

**Report:** `.planning/quick/260519-smoke-v1012/SMOKE-v1012-REPORT.md`

| # | Surface | Sev | Summary | v1013 REQ-ID | Phase |
|---|---|---|---|---|---|
| 1 | Reupload (File path) | P0 | Multi-layer GPKG silently picks `layers[0]`; `dataset.source_layer` not consulted. Silent-data-swap risk. | GPKG-01 | 1058 |
| 2 | Reupload (File path) preview | P1 | No layer-name surfaced when source file has >1 layer (Service URL preview does this correctly). | GPKG-02 | 1058 |
| 3 | Import Bulk Review (GPKG) | P2 | Only one layer per multi-layer GPKG commits; no "ingest all layers" batch path. | GPKG-03 | 1058 |
| 4 | WFS commit | **P0** | `MultiSurface vs MultiPolygon` PostGIS type mismatch fails UPDATE during bounds-clip. 100% reproducible against GeoServer polygon layers. | WFS-04 | 1057 |
| 5 | Service URL probe orchestrator | P1 | No short-circuit on first success — pygeoapi probe took 63s total (adapter succeeded in 1.5s). | PROBE-05 | 1057 |
| 6 | OGC API CRS detection | P2 | URI-form CRS (`http://www.opengis.net/def/crs/OGC/1.3/CRS84`) not parsed to EPSG; user sees "CRS: Unknown" + must enter override. | CRS-06 | 1057 |
| 7 | Service URL layer-select classification | P2 | Layers without `geometry_type` in probe response default to RAS; should fall back to VEC. | CLASS-07 | 1057 |

## Decisions

- **Phase 1059 Plan 02:** Exported StyleLayer, isRoadLayer, isBoundaryLayer, isBuildingLayer, isTextLabelLayer, SUBLAYER_CLASSIFIERS from basemap-utils.ts. applySublayerOverrides uses idle-retry recovery (map.once('idle', retry)). casing_color applied via line-color on layers with 'casing' in id (openfreemap-positron heuristic). ViewerMap.tsx serves viewer/shared/embed — 2 wire-up sites covers all 4 render contexts.
- **Phase 1059 Plan 03:** BasemapSublayerEditorScene restored with 5 sections (STROKE/CASING/ZOOM/OPACITY/RESET). Test 14 inverted from REMOVE-pin to PRESENT-assert. updateSublayerOverride helper in MapBuilderPage uses setBasemapConfig functional updater for atomic sublayer_overrides patch. 9 English i18n keys added. MapSublayerOverride imported directly from api.ts (Plan 02 already landed it).
- **Phase 1059 Plan 04:** 12 new vitest tests (5 ViewerMap.basemap-config + 7 sublayer-overrides.round-trip). All 4 ROADMAP ACs evidenced. de/es/fr i18n parity — 9 new basemapSublayer.* keys in each locale. i18n gate 2/2. No production code changes. Phase 1059 COMPLETE — ready for Phase 1060 close gate.
- **Phase 1061 Plan 03:** SEC-S05 fix applied at API router boundary — check_dataset_access_or_anonymous return value reused as user_roles (no redundant get_user_roles call). Defense-in-depth caller contract documented at _load_self_record_and_embedding. SEC-FU: narrow embedding read to visibility-filtered query (Phase 1063 candidate).

## Operator Next Steps

- Run `/gsd:plan-phase 1057` to break Service URL Reliability into plans.
- Phase 1057, 1058, 1059 can theoretically be planned in any order (no inter-phase code dependencies); recommend P0-led order (1057 → 1058 → 1059) for sequential solo-dev execution.
- Phase 1060 (Close Gate) must wait for 1057 + 1058 + 1059 completion.
- Phase 1059 complete. Phase 1060 (Close Gate) can proceed after Phases 1057 + 1058 also complete.
