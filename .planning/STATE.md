---
gsd_state_version: 1.0
milestone: v1017
milestone_name: Test Infra & Audit Tail
status: planning
last_updated: "2026-05-21T17:31:25.504Z"
last_activity: 2026-05-21
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: 1075 (next — not started)
Plan: —
Status: Roadmap complete; awaiting `/gsd:plan-phase 1075`
Last activity: 2026-05-21 — Milestone v1017 roadmap created (5 phases: 1075-1079, 13/13 reqs mapped)

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1017 Test Infra & Audit Tail — restore pytest signal accuracy (TI-01/TI-02 conftest refactor + 11 baseline failures), close 7 deferred P2 ingest findings (ING-01..07), wire `test_alembic_upgrade_clean_db.sh` into CI (CI-01), re-verify Phase 1071 KNOWN-02 docker smoke (VG-01), trim 174-item quick_tasks tail (HYG-01). Public tag target: `v1.5.2` (patch).

## Last Shipped Milestone

**Version:** v1016 Hardening Sweep
**Shipped:** 2026-05-21
**Phases:** 1071-1074 (4 phases, 26/26 reqs)
**Tag:** `v1016` (local) + `v1.5.1` (public) at commit `70241f96`
**Archive:** `.planning/milestones/v1016-ROADMAP.md`

**Previous:** v1015 Ingest/Export Lifecycle Hardening (shipped 2026-05-20, public tag `v1.5.0`, archive `.planning/milestones/v1015-ROADMAP.md`)

## Phase Plan (v1017)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1075 | Conftest Test-DB Lifecycle Refactor + Baseline Fixes | TI-01, TI-02 | — |
| 1076 | Backend Ingest P2 Closure | ING-02, ING-03, ING-04, ING-06, ING-07 | 1075 |
| 1077 | Frontend Ingest P2 Closure | ING-01, ING-05 | 1075 |
| 1078 | CI Alembic Clean-DB Upgrade Workflow | CI-01 | — |
| 1079 | Close Gate + Hygiene | TI-03, VG-01, HYG-01 | 1075, 1076, 1077, 1078 |

**Coverage:** 13/13 requirements mapped — no orphans.

## Accumulated Context

### Decisions

- **2026-05-21 (v1017):** Test infrastructure MUST run first (Phase 1075) so every downstream phase gets clean pytest signal — TI-01 conftest refactor is a precondition for accurate test results on ING-02 regression test + close-gate.
- **2026-05-21 (v1017):** TI-03 pytest baseline doc is the LAST phase work (Phase 1079) — it captures the post-fix steady state after all 4 prior phases land.
- **2026-05-21 (v1017):** CI-01 alembic workflow (Phase 1078) is independent of test infra and ingest P2 work — can execute in parallel with Phase 1076/1077 if/when capacity allows.
- **2026-05-21 (v1017):** Ingest P2 split by surface — backend (Phase 1076: ING-02/03/04/06/07) needs new regression test for P2-02 commit boundary; frontend (Phase 1077: ING-01/05) is mostly helper extraction. Splitting allows the backend phase to gate on the new regression test independently.
- **2026-05-21 (v1017):** Re-audit NOT scheduled at the front — v1016 audits passed clean 1 day prior (2026-05-21). Audits run at close-gate as verification only, not gating.
- **2026-05-21 (v1017):** Public tag target `v1.5.2` (patch) — hygiene/hardening only, no user-facing features, no migrations beyond what's needed for ING-02 regression test fixtures.

### Pending Todos

- 174 v1014/v1015/v1016 quick_tasks queued for triage in HYG-01 (Phase 1079) — review, archive superseded, promote still-relevant to `.planning/todos/pending/`, target <50 active.

### Blockers/Concerns

None — v1017 roadmap is complete and ready for plan-phase.

## Session Continuity

Last session: 2026-05-21
Stopped at: v1017 roadmap created; STATE.md updated
Resume file: None

## Operator Next Steps

- Invoke `/gsd:plan-phase 1075` to plan the conftest test-DB lifecycle refactor (foundation phase — gates downstream test signal)

## Deferred Items

Carried into v1017 from v1016 close (2026-05-21):

- **174 quick_tasks** — triaged in Phase 1079 HYG-01 (target: trim to <50 active)
- **1 verification_gap** — Phase 1071 KNOWN-02 docker smoke (deferred from Phase 1074 close-gate); re-verified live in Phase 1079 VG-01
- **8 v1015-carried P2** — TD-DEFER-01..08; 7 closed in v1017 ING-01..07 (1 was closed in v1016 Phase 1073 REMED-01/02)
- **11 v1015 baseline pytest failures + 1363 test-DB-lifecycle conftest infra errors** — Phase 1075 TI-01 (conftest) + TI-02 (11 failures)
- **SEC-OBSV-03 alembic-clean-DB CI wiring** — Phase 1078 CI-01
