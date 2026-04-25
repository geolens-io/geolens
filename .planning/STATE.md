---
gsd_state_version: 1.0
milestone: v15.0
milestone_name: milestone
status: Roadmap created
stopped_at: Phase 223 context gathered
last_updated: "2026-04-25T16:27:41.630Z"
last_activity: 2026-04-25 — Roadmap created for v15.0 (Phases 223–228)
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-25)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v15.0 Documentation Site — roadmap created, ready to plan Phase 223

## Current Position

Phase: Not started (roadmap created)
Plan: —
Status: Roadmap created
Last activity: 2026-04-25 — Roadmap created for v15.0 (Phases 223–228)

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
- [v15.0 Roadmap]: Phase 223 is load-bearing — URL structure, CF Pages multi-project config, token-drift check, `_redirects` stub, GA4, canonical site URL, openapi snapshot strategy, version pin gate all locked here before content begins
- [v15.0 Roadmap]: MIG-01 split across Phase 226 (install stub) and Phase 227 (admin stub) — each stub replaced atomically with the phase that writes its canonical content

### Roadmap Evolution

- 2026-04-25: Milestone v15.0 initiated — documentation site scope confirmed
- 2026-04-25: Roadmap created — 6 phases (223–228), 61 requirements mapped, 100% coverage

### Pending Todos

None yet.

### Blockers/Concerns

None — all blockers resolved during requirements definition.

## Session Continuity

Last session: --stopped-at
Stopped at: Phase 223 context gathered
Resume file: --resume-file
