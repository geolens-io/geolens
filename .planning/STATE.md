---
gsd_state_version: 1.0
milestone: v1012
milestone_name: New-User Hardening + Reupload
status: planning
last_updated: "2026-05-19T20:37:37.509Z"
last_activity: 2026-05-19
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-19 — Milestone v1012 started

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-18 — v1011.1 Builder Hygiene Carryover shipped)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** No active milestone — run `/gsd-new-milestone` to scope the next milestone.

## Last Shipped Milestone

**Version:** v1011.1 Builder Hygiene Carryover
**Shipped:** 2026-05-18
**Phase:** 1052 (1 phase, 7 plans, 5/5 reqs: EMRG-FN-01..04 + CTRL-01)
**Tag:** v1011.1 (local, at `567c701e`)
**Archive:** `.planning/milestones/v1011.1-ROADMAP.md`

**Previous:** v1011 Map Builder Polish & Bug Sweep (shipped 2026-05-18, tag `v1011` local, archive `.planning/milestones/v1011-ROADMAP.md`)

## Accumulated Context

### Open candidate themes for next milestone

- **M001-7n8vpc audit follow-up milestone (17 remaining findings)** — 4 High + 7 Medium + 6 Low captured in `.planning/M001-7n8vpc-dry-run-audit.md`. Top High items: BU-02 already shipped; DOC-02 (`seed-ago-data.py` needs pre-created API key, no docs); CONSOLE-01 (12 401 errors on anonymous Search page — partial regression of v1010.2 SF-06); IMPORT-03 (React setState-during-render warning on every Upload File commit). Natural fit as a hygiene-shape milestone (v1011.2 or similar).
- **6 audit enhancements (EW-01..06)** — consolidate-to-single-compose, add seeder path to quickstart, `.env.example` SSL hint, STAC stage-and-confirm, reframe Register Table empty state. Most are docs/config edits.
- **Post-v1011.1 informal commits to formalize** — the 8 commits between v1011.1 (`567c701e`) and these audit fixes include 2 feature commits (`b285f305` tabbed LayerEditorPanel, `8370e19e` composite map export) + several bug fixes. Currently informal on main; either tag as a release or fold into the next milestone.
- **v1.7 Marketplace & Distribution unpause** — paused at Phase 40 (AWS AMI Build).
- **Multi-tenant Cloud prerequisites** — Phase 999.6 tenant scoping (backlogged, Cloud-tier blocker).
- **Enterprise feature backlog** — Phase 999.13 connector registry, Phase 999.14 Helm/AMI pipeline, Phase 999.15 SBOM, Phase 999.16 schemas package extraction.
- **Public-repo recreate** — 2026-05-05 pending todo.
- **BasemapSublayerEditorScene Path B FIX** — full per-sublayer styling persistence (jsonb-additive `MapBasemapConfig.sublayer_overrides`; live MapLibre dispatch through `applyBasemapConfigToMap`). 3-5 day feature phase; explicitly deferred from v1011.1 EMRG-FN-01 (Path A REMOVE chosen instead). Prioritize separately if/when basemap-sublayer styling is a real user need.

### Pending Todos

- **Recreate public repo before launch** (2026-05-05) — `.planning/todos/pending/2026-05-05-recreate-public-repo-before-launch.md`. Outside v1011.1 scope.

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260518-qz1 | Tile cols= opt-in follow-ups (F1 heatmap live, F2 backend integration tests, F3 viewer end-to-end) | 2026-05-18 | 414c7ff7 | Verified | [260518-qz1-tile-cols-opt-in-followups-f1-f2-f3](./quick/260518-qz1-tile-cols-opt-in-followups-f1-f2-f3/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Feature | BasemapSublayerEditorScene Path B FIX (full sublayer styling persistence) | Out of v1011.1 scope — 3-5 day feature phase; prioritize separately if/when needed | 2026-05-18 (v1011.1 EMRG-FN-01 REMOVE close) |

## Operator Next Steps

- Decide whether to tag today's 3 Critical fixes as a `v1.1.2` patch release (or hold for a larger v1011.2 milestone that bundles them with the post-v1011.1 informal commits and the 17 remaining audit findings).
- Run `/gsd-new-milestone` to scope the next milestone. The M001-7n8vpc audit findings make a strong candidate scope (4 High + 7 Medium + 6 Low + 6 enhancements — fits a hygiene-shape milestone).
- Optionally push the local `v1011.1` tag: `git push origin v1011.1`.
- Optionally push the local `v1011` tag if not already pushed: `git push origin v1011`.
- Address the Dependabot moderate vulnerability surfaced on push (alert 40 at https://github.com/geolens-io/geolens/security/dependabot/40).
