---
gsd_state_version: 1.0
milestone: v14.0
milestone_name: getgeolens.com Marketing Site
status: planning
stopped_at: Phase 214 shipped; Phase 215 not yet planned
last_updated: "2026-04-08T00:00:00.000Z"
last_activity: 2026-04-08
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 6
  completed_plans: 6
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-04)

**Core value:** Users can find any dataset in the catalog in seconds -- search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 215 — Homepage (v14.0 marketing site)

## Current Position

Phase: 215
Plan: Not started (no CONTEXT.md yet — discuss-phase recommended)
Status: Phase 214 shipped; Phase 215 ready to discuss/plan
Last activity: 2026-04-08 - Completed quick task 260408-aa5: 3d data and maps support

Progress: [█████░░░░░] 50% (3/6 phases complete in v14.0)

## Performance Metrics

**Velocity:**

- Total plans completed: 6
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 212 | 2 | - | - |
| 213 | 2 | - | - |
| 214 | 2 | - | - |

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

## Session Continuity

Last session: 2026-04-08T00:00:00.000Z
Stopped at: Session resumed — Phase 214 shipped and verified; Phase 215 Homepage ready to discuss/plan
Resume file: (none — Phase 215 has no CONTEXT.md yet)
