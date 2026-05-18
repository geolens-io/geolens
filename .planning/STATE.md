---
gsd_state_version: 1.0
milestone: v1011.1
milestone_name: Builder Hygiene Carryover
status: Roadmap created — ready for `/gsd-discuss-phase`
stopped_at: Roadmap for v1011.1 written — Phase 1052 + 5 success criteria + traceability table populated.
last_updated: "2026-05-18T17:47:09.271Z"
last_activity: 2026-05-18 — Roadmap created for v1011.1 (5 reqs → Phase 1052)
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 7
  completed_plans: 5
  percent: 0
---

# State

## Current Position

Phase: 1052 (builder-hygiene-carryover) — single phase in v1011.1
Plan: — (TBD via `/gsd-plan-phase` after `/gsd-discuss-phase` settles EMRG-FN-01 Path A vs Path B)
Status: Roadmap created — ready for `/gsd-discuss-phase`
Last activity: 2026-05-18 — Roadmap created for v1011.1 (5 reqs → Phase 1052)

Progress: [███████░░░] 71%

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-18 — v1011 Map Builder Polish & Bug Sweep shipped, v1011.1 milestone scoped)

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1011.1 Phase 1052 — close 4 EMRG-FN carryforward findings + CTRL-01 close gate.

## Last Shipped Milestone

**Version:** v1011 Map Builder Polish & Bug Sweep
**Shipped:** 2026-05-18
**Phase:** 1051 (1 phase, 13 plans, 13/13 BUG/UX/RESP/INV/EMRG/CTRL reqs + 21 inline code-review fixes + 2 in-flight regression fixes)
**Tag:** v1011 (local)
**Archive:** `.planning/milestones/v1011-ROADMAP.md`

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- v1011 Phase 1051 CTRL-01: defer all 4 EMRG-FN findings to v1011.1 hygiene milestone (P2-defer; outside v1011 scope-boundary).
- v1011.1 milestone scope: single hygiene phase, sequential plans, single CTRL-01 close gate per `feedback_hygiene_milestone_pattern.md`. Mirrors v1009.1 / v1010.1 / v1010.2 / v1011 hygiene precedent.
- EMRG-FN-01 Path A REMOVE vs Path B FIX decision deferred to `/gsd-discuss-phase` — phase goal accommodates either path.
- [Phase ?]: Test 14 EMRG-FN-01 regression pin mirrors Test 13 INV-01 positive-form queryBy* pattern

### Pending Todos

- **EMRG-FN-01 — BasemapSublayerEditorScene Phase 1038 dead-stub cleanup** (from v1011 EMRG-01 triage). Tracking: `.planning/todos/pending/2026-05-18-basemap-sublayer-phase-1038-dead-stubs.md`. Path A REMOVE (~10min, mirror INV-01 precedent) vs Path B FIX (~3-5 days, implement Phase 1038 sublayer styling persistence).
- **EMRG-FN-02 — `settings.toggleWidget` orphan i18n key** (4 locales × 1 key from Plan 07 UX-04). Trivial 4-file edit, no tests.
- **EMRG-FN-03 — UnifiedStackPanel.tsx unused-eslint-disable warnings** (lines 679 + 720 from Phase 1041). Single-file 2-line removal.
- **EMRG-FN-04 — SublayerConfigIndicators `layer=null` branch** (Plan 05 UX-02 deferred enhancement). Auto-resolved by EMRG-FN-01 Path A or covered by explicit regression test under Path B.

### Blockers/Concerns

None. v1011 baseline is green; EMRG-FN-01 path decision is a planning conversation, not a blocker.

## Deferred Items

Items acknowledged and carried forward from v1011 milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| EMRG-FN | BasemapSublayerEditorScene Phase 1038 dead-stub callbacks | In v1011.1 scope (EMRG-FN-01) | 2026-05-18 (v1011 close) |
| EMRG-FN | `settings.toggleWidget` orphan i18n key | In v1011.1 scope (EMRG-FN-02) | 2026-05-18 (v1011 close) |
| EMRG-FN | UnifiedStackPanel.tsx unused-eslint-disable warnings | In v1011.1 scope (EMRG-FN-03) | 2026-05-18 (v1011 close) |
| EMRG-FN | SublayerConfigIndicators `layer=null` branch | In v1011.1 scope (EMRG-FN-04) | 2026-05-18 (v1011 close) |

## Session Continuity

Last session: 2026-05-18T17:47:09.266Z
Stopped at: Roadmap for v1011.1 written — Phase 1052 + 5 success criteria + traceability table populated.
Resume file: None
