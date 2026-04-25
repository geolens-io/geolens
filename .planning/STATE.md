---
gsd_state_version: 1.0
milestone: v15.0
milestone_name: Documentation Site
status: defining_requirements
stopped_at: ""
last_updated: "2026-04-25T00:00:00.000Z"
last_activity: 2026-04-25
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-25)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v15.0 Documentation Site — defining requirements

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-04-25 — Milestone v15.0 started

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

- [v15.0 Scope]: Docs site lives in the existing `getgeolens-com` marketing repo (not a new repo, not the geolens monorepo) — shared design tokens, single source of truth for brand identity
- [v15.0 Scope]: Astro Starlight chosen over Mintlify/Docusaurus/VitePress — Astro-native, matches existing marketing-site stack, Pagefind search built in
- [v15.0 Scope]: Subdomain routing via separate Cloudflare Pages project from the same repo — `docs.getgeolens.com` decoupled from marketing-site deploys/caching
- [v15.0 Scope]: Single "latest" version for v15.0 — no versioning machinery; defer until 1.x.y churn justifies it
- [v15.0 Scope]: API reference auto-rendered from FastAPI `openapi.json` at build time — stays in sync with code, no hand-maintained endpoint docs in v15.0
- [v15.0 Scope]: Pagefind static search (Starlight default) — no Algolia DocSearch dependency
- [v15.0 Scope]: Phase 216 split — Quickstart/Install moves to docs site; Features page is built on marketing site as part of this milestone
- [v15.0 Scope]: Map builder polish is being handled in a parallel workstream — explicitly excluded from this milestone

### Roadmap Evolution

- 2026-04-25: Milestone v15.0 initiated — documentation site scope confirmed

### Pending Todos

None yet.

### Blockers/Concerns

- Auto-generated API reference depends on a stable `openapi.json` snapshot — decide whether to commit a snapshot to the docs repo or fetch live at build time
- Migrating `docs/install.md` and `docs/admin.md` from the geolens monorepo will create canonical-vs-source ambiguity until those files are removed/redirected

## Session Continuity

Last session: 2026-04-25T00:00:00.000Z
Stopped at: Defining v15.0 requirements
Resume file: —
