---
gsd_state_version: 1.0
milestone: v14.0
milestone_name: getgeolens.com Marketing Site
status: executing
stopped_at: Phase 222 context gathered
last_updated: "2026-04-13T12:00:51.330Z"
last_activity: 2026-04-13
progress:
  total_phases: 15
  completed_phases: 14
  total_plans: 33
  completed_plans: 33
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-04)

**Core value:** Users can find any dataset in the catalog in seconds -- search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 999.3 — geojson-z-delivery-endpoint

## Current Position

Phase: 999.4
Plan: Not started
Status: Executing Phase 999.3
Last activity: 2026-04-13

Progress: [████░░░░░░] 43% (3/7 phases complete in v14.0)

## Performance Metrics

**Velocity:**

- Total plans completed: 31
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 212 | 2 | - | - |
| 213 | 2 | - | - |
| 214 | 2 | - | - |
| 218 | 5 | - | - |
| 221 | 1 | - | - |
| 220 | 1 | - | - |
| 222 | 1 | - | - |
| 217 | 2 | - | - |
| 999.1 | 4 | - | - |
| 999.2 | 3 | - | - |
| 999.3 | 3 | - | - |
| 999.4 | 2 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 212-repo-bootstrap-and-design-system P01 | 3 | 2 tasks | 10 files |

## Accumulated Context

### Decisions

- [v14.0 Roadmap]: Separate repo (getgeolens.com) — not in GeoLens monorepo; Phase 212 includes the repo bootstrap
- [v14.0 Roadmap]: SEO infrastructure (Phase 213) built before any content pages — every page auto-inherits correct meta/OG/sitemap from day one
- [v14.0 Roadmap]: Product preview assets (Phase 214) run in parallel with SEO (both depend on 212 only) — both must complete before homepage
- [v14.0 Roadmap]: A11Y-01 (contrast) and A11Y-03 (semantic HTML) assigned to Phase 212 — cheapest to fix at design-system time; A11Y-02 and A11Y-04 assigned to Phase 217 (require finished pages)
- [v14.0 Roadmap]: Accessibility audit (Phase 217) is a launch gate, not optional polish — WCAG 2.1 AA required for government procurement (ADA Title II enforcement April 2026)
- [Phase 212-01]: Tailwind 4 uses @tailwindcss/vite Vite plugin (not @astrojs/tailwind) — Astro tailwind integration is for v3 only
- [Phase 212-01]: A11Y-01: primary-700 oklch(0.46 0.16 250) is minimum shade for text on white (4.5:1 AA); primary-500 is decorative only
- [Phase 212-01]: Token sync strategy: geolens/frontend/src/index.css is source of truth; getgeolens.com/src/styles/global.css is manual copy-on-update
- [v14.0 Roadmap]: Phase 218 (Demo Themed Collections) added 2026-04-08 — independent of 215/216/217 marketing site phases; source proposal 260408-lnq; A7 resolved in 260408-mgg (Option C fallback selected)

### Roadmap Evolution

- 2026-04-08: Phase 218 added — Demo Themed Collections (3 themes, 9 maps, seeder-driven)

### Pending Todos

None yet.

### Blockers/Concerns

- Product preview asset style/fidelity is a judgment call — no automated test can verify "looks convincing." Plan a review checkpoint after Phase 214 before proceeding to homepage.
- Contact form (enterprise path) is deferred to future milestone per REQUIREMENTS.md; ensure homepage hero CTA for enterprise is a mailto: or static contact link for now.

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260405-9k2 | lets cleanup the repo and get it ready for public release | 2026-04-05 | b63b47e9 | Needs Review | [260405-9k2-lets-cleanup-the-repo-and-get-it-ready-f](./quick/260405-9k2-lets-cleanup-the-repo-and-get-it-ready-f/) |
| 260405-dn1 | Review landing page for enterprise/community value — consider extracting to getgeolens.com | 2026-04-05 | 4f3d6e15 | Verified | [260405-dn1-review-landing-page-for-enterprise-commu](./quick/260405-dn1-review-landing-page-for-enterprise-commu/) |
| 260408-aa5 | 3d data and maps support | 2026-04-08 | 9333cf5d | Verified | [260408-aa5-3d-data-and-maps-support](./quick/260408-aa5-3d-data-and-maps-support/) |
| 260408-iny | review the table data type — full enhancement pass | 2026-04-08 | 482dc7eb | Needs Review | [260408-iny-review-the-table-data-type-why-are-there](./quick/260408-iny-review-the-table-data-type-why-are-there/) |
| 260408-lnq | demo environment data & maps proposal (themes, sources, automation) | 2026-04-08 | doc-only | Verified | [260408-lnq-come-up-with-an-interesting-series-of-da](./quick/260408-lnq-come-up-with-an-interesting-series-of-da/) |
| 260408-mgg | A7 spike: verify table→polygon join in map builder (verdict: unsupported, Option C fallback) | 2026-04-08 | doc-only | Verified | [260408-mgg-a7-spike-verify-map-builder-can-join-rec](./quick/260408-mgg-a7-spike-verify-map-builder-can-join-rec/) |
| 260409 | map thumbnails not working, this seems to be a regression | 2026-04-10 | d8d59cbd | Verified | [260409-map-thumbnails-not-working-this-seems-to](./quick/260409-map-thumbnails-not-working-this-seems-to/) |
| 260410-d7k | review and make sure during the Import operations are all columns being imported | 2026-04-10 | 630f585f | Verified | [260410-d7k-review-and-make-sure-during-the-import-o](./quick/260410-d7k-review-and-make-sure-during-the-import-o/) |
| 260411-a62 | review and close out remaining items in post-impl-20260410 handoff | 2026-04-11 | cea32bca | Verified | [260411-a62-review-the-remaining-items-in-docs-inter](./quick/260411-a62-review-the-remaining-items-in-docs-inter/) |

## Session Continuity

Last session: 2026-04-11T16:31:23.849Z
Stopped at: Phase 222 context gathered
Resume file: .planning/phases/222-persistent-config-cast-runtime-validation/222-CONTEXT.md
