---
gsd_state_version: 1.0
milestone: v1031
milestone_name: Builder Render-Mode & Share Polish
status: "Roadmap created — ready for `/gsd:plan-phase 1140`"
stopped_at: Phase 1140 UI-SPEC approved
last_updated: "2026-05-28T14:50:53.231Z"
last_activity: 2026-05-28 — Roadmap written (4 phases 1140-1143, 9/9 reqs mapped)
progress:
  total_phases: 12
  completed_phases: 0
  total_plans: 4
  completed_plans: 2
  percent: 0
---

# State

## Current Position

Phase: Not started (roadmap defined, ready for plan-phase)
Plan: —
Status: Roadmap created — ready for `/gsd:plan-phase 1140`
Last activity: 2026-05-28 — Roadmap written (4 phases 1140-1143, 9/9 reqs mapped)

```
Progress: [█████░░░░░] 50%
```

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1031 Builder Render-Mode & Share Polish — new render-mode editor controls (DEM/raster/fill) + OG-image social cards + SharePanel typography, proven on the live builder via Playwright MCP.

## Last Shipped Milestone

**Version:** v1030 Map Builder Polish Sweep
**Shipped:** 2026-05-28
**Phases:** 1133-1139 (7 phases, 38 plans, 44/44 reqs satisfied)
**Tag:** local `v1030`
**Milestone audit:** `.planning/v1030-MILESTONE-AUDIT.md` (PASSED — 44/44 reqs, 10/10 integration, 0 blockers)
**Archive:** `.planning/milestones/v1030-ROADMAP.md` + `v1030-REQUIREMENTS.md`
**Stats:** 173 commits, 84 source files (+8215/−245), 2026-05-27→28
**Carry-forward:** CI-01-v1030 (GH Actions billing); SHARE-08 OG-cards (→v1031 Phase 1142); F2 font-medium hygiene (→v1031 Phase 1142); sibling docs `npm run fetch-openapi` before next deploy.
**Archived phases:** `.planning/milestones/v1030-phases/`

## Phase Plan (v1031)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1140 Raster & Terrain Editor Controls | Users can configure contour overlays, hypsometric tints, and single-band colormaps for DEM and raster layers directly in the editor | EDITOR-DEM-04, EDITOR-DEM-05, EDITOR-RASTER-COLORMAP | — |
| 1141 Fill-Pattern Editor Control | Users can apply a fill-pattern from a curated built-in sprite set to a fill-render-mode layer via the FillEditor | EDITOR-FILL-01 | — |
| 1142 OG-Image Social Cards & SharePanel Typography | Shared map links emit valid OG/Twitter card meta backed by a 1200×630 preview image; SharePanel uses ≤2 font weights | SHARE-08, SHARE-10 | — |
| 1143 Quality Sweep & Playwright Close-Gate | All v1031 new controls and share/OG flows are verified on the live builder and all quality gates are green | QA-01, QA-02, QA-03 | Phases 1140, 1141, 1142 |

**Coverage:** 9/9 v1031 requirements mapped, 0 orphans, 0 duplicates.

**Parallelism note:** Phases 1140, 1141, and 1142 are independent feature surfaces and can run in parallel. Phase 1143 (close-gate) depends on all three.

**HARD INVARIANTS (do NOT relax):**

1. **1143 last (canonical close-gate):** v1027/v1028/v1029/v1030 hard precedent. Live Playwright MCP smoke + typecheck/lint/vitest/backend-pytest/`e2e:smoke:builder`/i18n + CHANGELOG + OpenAPI/SDK refresh.
2. **Playwright MCP is orchestrator-only:** GSD subagents (gsd-executor etc.) lack `mcp__playwright__*` tool access. The orchestrator MUST drive all live MCP verification in Phase 1143 directly. Subagents asked to "run MCP" fabricate PASS/FAIL or write `.spec.ts` instead.
3. **No architecture rewrites:** v1031 is feature-add on the v1026/v1027 substrate. No new files >500 LOC; no rename of >3 exported symbols; no controller/action-boundary widening without a Future Requirement entry first.
4. **EDITOR-FILL-01 sizing escape-hatch:** Prefer curated built-in pattern selection first. Defer custom user sprite-upload backend (sprite storage/serving routes) to Future if it balloons — decide at plan-phase, not mid-execution.
5. **SHARE-08 path pick:** Path A (nullable `og_image_uri` column + `PUT`/`GET /maps/{id}/og-image/` routes) vs Path B (backend resize from native canvas capture) MUST be decided in a planning audit BEFORE plan-01 commits. Do NOT add `@vercel/og` or `satori`.
6. **EDITOR-RASTER-COLORMAP backend scoping:** Titiler single-band colormap render-path research happens at plan-phase (Phase 1140). Backend changes (new params, response schema) trigger OpenAPI/SDK refresh in Phase 1143.
7. **Out-of-scope hold:** 999.18 editor-convenience sub-group (EDITOR-SYMBOL-04, EDITOR-BASEMAP-06), layer-type expansion (text, draw, LiDAR), new LLM providers, new connector backends, enterprise edition changes, marketing/docs, open-core/Cloud backlog (999.6/13-16) — all explicitly OUT. Enforce at review.

## Phase Progress

| Phase | Status | Evidence |
|-------|--------|----------|
| 1140 Raster & Terrain Editor Controls | Not started | — |
| 1141 Fill-Pattern Editor Control | Not started | — |
| 1142 OG-Image Social Cards & SharePanel Typography | Not started | — |
| 1143 Quality Sweep & Playwright Close-Gate | Not started | — |

## Quick Tasks Completed

| Date | Quick ID | Slug | Status | Notes |
|------|----------|------|--------|-------|
| 2026-05-24 | 260524-o57 | adk-high-peaks-data | Delivered + 6 findings | Marketing-data ingest for ADK High Peaks AOI (1m DEM + NY 2023 orthos + 4 vector layers + curated 46er peaks). Map `c39be324-6815-40e5-8143-00a2723827b2` shippable; 6 GeoLens dogfooding findings filed in [260524-o57-API-ISSUES.md](quick/260524-o57-adk-high-peaks-data/260524-o57-API-ISSUES.md). |

## Accumulated Context

### Decisions

- **2026-05-28 (v1031 roadmap):** 4-phase structure (1140 raster/terrain → 1141 fill-pattern → 1142 sharing → 1143 close-gate). Phases 1140/1141/1142 are independent feature surfaces and can run in parallel; Phase 1143 is the mandatory serial close-gate per v1027/v1028/v1029/v1030 precedent.
- **2026-05-28 (v1031 roadmap):** No audit-first walkthrough phase — v1031 is a feature-add milestone (not a polish/bug-sweep). The v1030 audit-first invariant was v1030-specific; it does not carry forward when adding new editor controls.
- **2026-05-28 (v1031 roadmap):** EDITOR-DEM-04/05 and EDITOR-RASTER-COLORMAP grouped into Phase 1140 (shared DEM/raster editor surface; EDITOR-RASTER-COLORMAP carries the most backend Titiler risk and should be scoped first in plan-01). EDITOR-FILL-01 is Phase 1141 (distinct fill-mode + sprite-handling surface).
- **2026-05-28 (v1031 roadmap):** SHARE-08 and SHARE-10 grouped into Phase 1142. SHARE-08 is substantial (OG-image pipeline, Path A/B decision); SHARE-10 is cosmetic (≤2 font weights). Grouping justified: same SharePanel surface, same phase dependency profile (none on 1140/1141), cosmetic makes natural tail of the sharing phase.
- **2026-05-27 (1134-01, carried):** Cluster adapter intentionally keeps raw `map.setFilter` for compound `combineFilter` shape — NOT migrated to `syncLayerFilter`. The compound filter must include the cluster/unclustered base predicate unconditionally and cannot go through the syncLayerFilter nil-guard path.
- **2026-05-27 (1134-01, carried):** Fill extrusion companion does not receive layout.visibility block at addLayers add-time (pre-existing gap). Controlled via syncVisibility. Documented in fill-adapter.test.ts.
- [Phase 1135, carried]: SF-MCP-01: backend chat_actions.py:_collect_chat_action() never emits rows on show_query_result for non-spatial queries; frontend inline card is ready but backend wiring missing. Carry-forward from v1030.
- [Phase 1135, carried]: AI-05 zoom-aware chips deferred in headless: headless WebGL failure prevents MapLibre idle events; 8 unit tests cover the contract; interactive verification documented in 1135-MCP-SMOKE.md.
- [Phase 1136, carried]: BLANK_BASEMAP_ID sentinel reuse in BasemapGroupEditorScene: existing 'blank' constant already routes through swapBasemapPreset to hasVisibleBasemap=false with zero controller change.
- [Phase 1136, carried]: deriveExtrusionRange string coercion — API returns dataset_sample_values as strings; parseFloat() coercion added; range hint now works in production.
- [Phase 1136, carried]: Basemap pre-flight reset pattern — smoke tests that need basemap group row must PUT basemap_style before navigation; blank state yields no row in stack.
- [Phase ?]: band_count=None for get_dataset_meta path (no RasterAsset join); frontend gate band_count===1
- [Phase ?]: stretch=percentile/stddev accepted with minmax fallback; stats-based computation deferred to v1032

### Pending Todos

None for v1031 yet (phases not started).

### Blockers/Concerns

- **CI-01-v1030 billing prerequisite (carry-forward from v1023):** Operator must resolve GH Actions billing at https://github.com/organizations/geolens-io/settings/billing before CI-01 can close GREEN. Remains outside the v1031 feature invariant. Standing blocker — unblock independently of milestone execution.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| ci-live-verify | `pytest-parallel-isolation` gate live-verify on real GitHub Actions (billing block) | Carried forward to v1031+ as CI-01-v1030 | v1023 Phase 1100 degraded close (mirrors v1022 deferral) |
| ux-error-reporting | React error page should file a bug via the GitHub issue template | Completed as ERROR-FU-01 | post-v1028 follow-up |

## Session Continuity

Last session: 2026-05-28T14:50:53.227Z
Stopped at: Phase 1140 UI-SPEC approved
Resume file: None

## Operator Next Steps

- Run `/gsd:plan-phase 1140` to scope the raster/terrain editor controls (EDITOR-DEM-04, EDITOR-DEM-05, EDITOR-RASTER-COLORMAP). Research Titiler single-band colormap render-path at plan-01.
- Phases 1140, 1141, 1142 are independent — can be planned and executed in any order or in parallel.
- Phase 1143 (close-gate) must run last; orchestrator drives all live MCP directly.
