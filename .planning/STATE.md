---
gsd_state_version: 1.0
milestone: v1018
milestone_name: Hygiene — v1017 Tech-Debt Tail
status: "Roadmap created — awaiting `/gsd:plan-phase 1080`"
stopped_at: Roadmap defined; no phases started
last_updated: "2026-05-21T22:30:48.293Z"
last_activity: 2026-05-21 — v1018 roadmap written
progress:
  total_phases: 9
  completed_phases: 2
  total_plans: 5
  completed_plans: 5
  percent: 22
---

# State

## Current Position

Phase: Not started (roadmap defined; ready for plan-phase)
Plan: —
Status: Roadmap created — awaiting `/gsd:plan-phase 1080`
Last activity: 2026-05-21 — v1018 roadmap written

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1080 — Production-Code Drift + Config Hygiene

## Last Shipped Milestone

**Version:** v1017 Test Infra & Audit Tail
**Shipped:** 2026-05-21
**Phases:** 1075-1079 (5 phases, 13/13 reqs)
**Tag:** `v1017` (local) + `v1.5.2` (public) at commit `c968392b`
**Archive:** `.planning/milestones/v1017-ROADMAP.md`

**Previous:** v1016 Hardening Sweep (shipped 2026-05-21, public tag `v1.5.1`, archive `.planning/milestones/v1016-ROADMAP.md`)

## Phase Plan (v1018)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1080 | Production-Code Drift + Config Hygiene | TD-01, TD-07 | — |
| 1081 | Test Fixture & Assertion Drift | TD-02, TD-03, TD-05, TD-06 | 1080 |
| 1082 | Test Environmental | TD-04 | 1081 |
| 1083 | Close Gate | TD-08 | 1080, 1081, 1082 |

**Coverage:** 8/8 requirements mapped — no orphans.

## Accumulated Context

### Decisions

- **2026-05-21 (v1018 roadmap):** Phase 1080 pairs TD-01 (broad-except layering test) + TD-07 (database_connect_args SSL disable branch) — both are production-code changes (1-2 lines each) with regression tests; keeping them in one atomic phase minimises the production touch surface and lets Phase 1081 start from a provably clean baseline.
- **2026-05-21 (v1018 roadmap):** Phase 1081 groups TD-02 + TD-03 + TD-05 + TD-06 — all four are test-side drift fixes with no production-code changes. TD-02/TD-03 share the SEC-S16 root cause; TD-05 collapses two sibling tests with one root cause (per REQUIREMENTS.md intentional `×2` notation); TD-06 is an async loop contamination fix at the fixture or teardown level.
- **2026-05-21 (v1018 roadmap):** Phase 1082 is standalone for TD-04 (ogrinfo environmental dependency) — the decision (skip-with-rationale vs mock-out) is independent of the drift fixes and should be made on a clean baseline after Phase 1081.
- **2026-05-21 (v1018 roadmap):** Phase 1083 is the close gate (TD-08): PYTEST-BASELINE-v1018.md + full sequential pytest + e2e:smoke:builder + live Playwright MCP smoke + CHANGELOG [1.5.3] + tags v1018 + v1.5.3. Must be last.
- **2026-05-21 (v1018 roadmap):** Per Plan 1075-05 protocol — no `pytest.mark.skip` without an explicit issue link. All failures must be dispositioned at root cause.
- **2026-05-21 (v1018 roadmap):** No fresh /sec-audit or /ingest-audit needed — v1016 ran both clean; v1017 audit verdict PASSED; v1018 is hygiene-only (backend test/config, no API contract changes, no migrations, no frontend work).
- **2026-05-21 (v1018 roadmap):** Public tag target `v1.5.3` (patch) — hygiene only; no user-facing features, no migrations, no schema changes.

### Pending Todos

None at roadmap time. All 8 TD items are dispositioned in REQUIREMENTS.md.

### Blockers/Concerns

None — v1018 roadmap is complete and ready for plan-phase.

## Session Continuity

Last session: 2026-05-21T22:30:48.288Z
Stopped at: Roadmap defined; no phases started
Resume file: None

## Operator Next Steps

- Invoke `/gsd:plan-phase 1080` (Production-Code Drift + Config Hygiene — TD-01, TD-07)
- Phase 1081 depends on 1080; phase 1082 depends on 1081; phase 1083 depends on all three.
- Close-gate phase (1083) must capture `.planning/audits/PYTEST-BASELINE-v1018.md` AFTER all TD fixes land.

## Deferred Items

Carried into v1018 from v1017 close (2026-05-21):

- **TD-01** — `test_layering.py::test_no_unjustified_broad_except_sites` — broad-except production-code drift at `tasks_common.py:231,237`
- **TD-02** — `test_phase_279_user_lifecycle.py::test_register_password_too_short` — SEC-S16 password policy drift
- **TD-03** — `test_phase_279_user_lifecycle.py::test_register_password_diversity` — SEC-S16 password policy drift (companion)
- **TD-04** — `test_reupload_idor.py::test_owner_gets_non_404_on_service_preview` — ogrinfo CLI environmental dependency
- **TD-05** — `test_reupload_service.py` ×2 — SSRF gate drift (same root cause, one commit)
- **TD-06** — `test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception` — async loop contamination
- **TD-07** — `backend/app/core/config.py:database_connect_args` SSL disable branch — low operational priority but disable path should be honoured
- **TD-08** — Close gate (capture baseline, full pytest, e2e, MCP smoke, CHANGELOG, tags)
