---
gsd_state_version: 1.0
milestone: v1011
milestone_name: Map Builder Polish & Bug Sweep
status: Roadmap created; awaiting plan-phase or autonomous executor
stopped_at: Phase 1051 UI-SPEC approved (force-approved on revision 2)
last_updated: "2026-05-17T22:56:12.856Z"
last_activity: 2026-05-17 — ROADMAP.md authored for v1011 (1 phase, 13 plans, 13/13 reqs mapped)
progress:
  total_phases: 1
  completed_phases: 0
  total_plans: 13
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: 1051 — map-builder-polish-bug-sweep
Plan: Not started (roadmap just created)
Status: Roadmap created; awaiting plan-phase or autonomous executor
Last activity: 2026-05-17 — ROADMAP.md authored for v1011 (1 phase, 13 plans, 13/13 reqs mapped)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — opened milestone v1011 Map Builder Polish & Bug Sweep)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1051 — map-builder-polish-bug-sweep (hygiene close of 11 user-reported items + INV-01 + EMRG-01 + CTRL-01)

## Last Shipped Milestone

**Version:** v1010.2 Builder Smoke Carryover
**Shipped:** 2026-05-17
**Phases:** 1050 (1 phase, 6 plans, 5/5 SMOKE-08..12 reqs + 7 inline code-review fixes)
**Tag:** v1010.2 (local)
**Archive:** `.planning/milestones/v1010.2-ROADMAP.md`

## Accumulated Context

### Decisions

- **v1011 is a hygiene-close milestone.** Single phase (1051), 13 sequential plans (11 user-reported items + 1 emergent-findings triage + 1 CTRL-01 close gate). Mirrors v1009.1 Phase 1045, v1010.1 Phase 1049, and v1010.2 Phase 1050 per `feedback_hygiene_milestone_pattern.md`.
- **Phase numbering continues at 1051.** v1010.2 ended at Phase 1050.
- **Execution path:** `/gsd-autonomous` with Playwright MCP orchestrator-scoped verification against live `localhost:8080` stack. MCP verification steps marked `checkpoint:orchestrator` so the autonomous executor hands back per `project_demo_uat_resume.md` and the v1010.1 lesson (MCP is orchestrator-scoped, NOT executor-spawnable).
- **Plan granularity:** atomic — one plan per requirement (favoring clean revert/audit over plan consolidation). RESP-01/02/03 kept atomic even though they share a responsive-layout theme, because their fixes likely touch different files (`NavigationControl` positioning vs `MapCoordReadout` positioning vs flyout chrome).
- **Plan 06 (UX-03 draggable basemap) is the largest scope** — touches DnD setup, basemap-as-group drag semantics, saved-map normalizer, MapLibre layer-order loop, and round-trip persistence. May need a new field on the saved-map schema (minimum surface per Out-of-Scope row 6). All other plans are tight-scope symptom fixes.
- **Plan 11 (INV-01) is a disposition plan** — investigation-then-decision. Orchestrator decides REMOVE vs FIX based on grep + Playwright MCP findings. Disposition recorded in commit message + CHANGELOG.
- **Plan 12 (EMRG-01) opens with placeholder content** and is updated as findings land during plans 01-11. If zero emergent findings, FINDINGS.md is still authored with explicit "0 emergent" note.
- **Per-plan verification:** Each user-reported plan includes (a) Playwright MCP pre-fix repro, (b) implementation, (c) vitest regression (where applicable — pure-CSS responsive fixes use manual MCP verify only), (d) Playwright MCP post-fix verify. Atomic commits.
- **Single CTRL-01 close gate at Plan 13** — batched typecheck + vitest + e2e:smoke:builder + Playwright MCP re-verify of all 11 items + CHANGELOG `[Unreleased]` population. Per `feedback_review_findings_inline.md`: any code-review findings surface during gate get fixed inline before close, not deferred to v1011.1.

### Out of Scope (per REQUIREMENTS.md)

- New Map Builder features beyond the 11 polish items (no renderer expansion, AI capability, time-series, collaboration)
- Backend/API changes outside what's strictly required to fix the 11 items (scope minimum API surface for any backend touch)
- Refactoring `MapBuilderPage`, builder hooks, or layer-adapters except where directly required (no v1010-style code-quality audit)
- Mobile-phone optimization (<800 px portrait) — v1011 small-screen targets tablet and narrow desktop
- New i18n keys beyond what fixes/conversions strictly require
- New saved-map schema fields beyond what UX-03 strictly requires

### Pending Todos

None at roadmap creation. EMRG-01 may produce new pending todos for defer-disposition findings.

### Blockers/Concerns

None at roadmap creation. All 11 user-reported items have either a clear repro URL (BUG-01) or a clear symptom to verify against Playwright MCP. INV-01 has an explicit disposition flow. EMRG-01 has a written-down triage protocol.

## Session Continuity

Last session: 2026-05-17T22:56:12.852Z
Stopped at: Phase 1051 UI-SPEC approved (force-approved on revision 2)
Resume file: .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md

Session resumed: 2026-05-17 — proceeding to `/gsd:plan-phase 1051` (user chose plan-phase over autonomous execute).

## Operator Next Steps

- Begin Phase 1051 via `/gsd:plan-phase 1051` to author per-plan implementation specs, OR
- Begin Phase 1051 via `/gsd-autonomous --from 1051` for end-to-end execution with orchestrator-scoped Playwright MCP verification at each `checkpoint:orchestrator` step
- Ensure `docker compose up -d --build` stack is healthy before starting (5/5 services); Playwright MCP needs `http://localhost:8080` reachable
