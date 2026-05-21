---
gsd_state_version: 1.0
milestone: v1017
milestone_name: Test Infra & Audit Tail
status: planning
last_updated: "2026-05-21T17:31:25.504Z"
last_activity: 2026-05-21
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
Last activity: 2026-05-21 — Milestone v1017 started

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1017 Test Infra & Audit Tail — close v1015/v1016 hygiene tail (conftest refactor, 11 baseline pytest failures, 8 ingest P2, SEC-OBSV-03 CI wiring)

## Last Shipped Milestone

**Version:** v1016 Hardening Sweep
**Shipped:** 2026-05-21
**Phases:** 1071-1074 (4 phases, 26/26 reqs)
**Tag:** `v1016` (local) + `v1.5.1` (public) at commit `70241f96`
**Archive:** `.planning/milestones/v1016-ROADMAP.md`

**Previous:** v1015 Ingest/Export Lifecycle Hardening (shipped 2026-05-20, public tag `v1.5.0`, archive `.planning/milestones/v1015-ROADMAP.md`)

## Accumulated Context

### Decisions

- **2026-05-21 (v1016):** Audit-first sequencing — Phase 1072 runs `/sec-audit` + `/ingest-audit` fresh; Phase 1073 remediation requirements added mid-milestone after triage lands (precedent: v1014).
- **2026-05-21 (v1016):** Public tag is patch `v1.5.1` (hygiene/hardening only — backward-compatible).
- **2026-05-21 (v1016):** Stale 2026-05-05 `recreate-public-repo-before-launch` todo moved to `resolved/` (1.0.0 already shipped publicly; framing is moot).
- **2026-05-21 (v1016):** Execution mode was `/gsd-autonomous` end-to-end; Playwright MCP used at Phase 1074 close-gate for live smoke.
- **2026-05-21 (v1016):** KNOWN-06 (e2e:smoke:builder + typecheck in close-gate) and KNOWN-07 (full pytest in close-gate) re-mapped from Phase 1071 → Phase 1074 — they are close-gate PROCESS items, not code-change items.

### Pending Todos

- 5 v1014 INFO todos (KNOWN-08..12) archived to `resolved/` during Phase 1071.

### Blockers/Concerns

None — v1016 fully closed.

## Session Continuity

Last session: 2026-05-21
Stopped at: v1016 shipped and archived
Resume file: None

## Operator Next Steps

- Invoke `/gsd-new-milestone` to start v1017

## Deferred Items

Items acknowledged at v1016 close (2026-05-21):

- 174 quick_tasks carried from prior milestones (v1014/v1015/earlier)
- 1 verification_gap (Phase 1071 KNOWN-02 docker smoke — by-design deferred to Phase 1074, verified green there)
- 8 v1015-carried P2 (TD-DEFER-01..08) - for v1017 hygiene
- 11 v1015 baseline pytest failures + 1363 test-DB-lifecycle conftest infra errors - v1015 carryover
- SEC-OBSV-03 alembic-clean-DB CI wiring - v1017
