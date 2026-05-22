---
gsd_state_version: 1.0
milestone: v1020
milestone_name: Fixture Isolation
status: planning
last_updated: "2026-05-22T14:00:00.000Z"
last_activity: 2026-05-22
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# State

## Current Position

Phase: Not started (roadmap defined; awaiting `/gsd:plan-phase 1087`)
Plan: —
Status: Roadmap defined
Last activity: 2026-05-22 — v1020 roadmap defined, 9/9 requirements mapped, 4 phases (1087-1090)

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 1087 — Fixture-Isolation Spike (first phase of v1020; spike-first, audit doc only)

## Last Shipped Milestone

**Version:** v1019 Hygiene Tail — v1018 Frontend + xdist + Process
**Shipped:** 2026-05-22
**Phases:** 1084-1086 (3 phases, 7 plans, 6/6 reqs)
**Tag:** `v1019` (local) + `v1.5.4` (public) at commit `02cb25db`
**Close-gate doc:** `.planning/phases/1086-process-tightening-close-gate/1086-02-CLOSE-GATE.md`
**Audit:** `.planning/milestones/v1019-MILESTONE-AUDIT.md` (PASSED — tech_debt; 1 v1020 carry-forward)

**Previous:** v1018 Hygiene — v1017 Tech-Debt Tail (shipped 2026-05-21, public tag `v1.5.3` at `d1b76061`, archive `.planning/milestones/v1018-ROADMAP.md`)

## Phase Plan (v1020)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1087 | Fixture-Isolation Spike (Taxonomy) — classify 192 failures, audit doc only | FI-01 | — (sequential 3036/0/38 v1019 baseline is start state) |
| 1088 | Fixture-Isolation Fixes + Regression Pins — 192 → 0 under `-n auto`, per-category pins | FI-02, FI-03 | 1087 |
| 1089 | CI Gate + Perf Baseline + Parallel Default — `pytest-parallel-isolation` job, perf doc, default switch | CI-01, CI-02, PERF-01 | 1088 |
| 1090 | Skip Audit + Flake Hunt + Close-Gate — 38 skip dispositions, 3× flake hunt, v1019 WR-01 paper-trail, tags | HYG-01, HYG-02, HYG-03 | 1089 |

**Coverage:** 9/9 requirements mapped — no orphans, no duplicates.

## Accumulated Context

### Decisions

- **2026-05-22 (v1020 roadmap):** Phase 1087 is spike-first per v1019 Phase 1085 precedent — Plan 1087-01 (or wherever FI-01 lives) MUST commit `PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` as its first deliverable; only then does the FI-02 plan execute. No code changes in Phase 1087.
- **2026-05-22 (v1020 roadmap):** Phase 1088 bundles FI-02 (fixes) + FI-03 (regression pins) — sequenced by FI-01's taxonomy (highest-impact category first). Each root-cause category gets at least one regression pin under `backend/tests/test_fixture_isolation_v1020.py` (or split per-category as the spike directs).
- **2026-05-22 (v1020 roadmap):** Phase 1089 bundles CI-01 (gate) + CI-02 (default switch) + PERF-01 (baseline) — the gate is meaningless before FI-02 lands, the perf doc measures the post-fix state, and the default-switch is only safe after the gate is green. All three depend on Phase 1088 closing.
- **2026-05-22 (v1020 roadmap):** Phase 1090 bundles HYG-01 (38 skip audit) + HYG-02 (3× flake hunt) + HYG-03 (v1019 WR-01 paper-trail) into the close gate — all three are low-risk, documentation-shape deliverables that belong at close rather than disrupting earlier phases. Close gate cuts tags `v1020` + `v1.5.5`.
- **2026-05-22 (v1020 roadmap):** Public tag target `v1.5.5` (patch) — hygiene only; no user-facing features, no migrations, no schema changes.
- **2026-05-22 (v1020 roadmap):** Sequential pytest baseline that MUST stay green throughout v1020: **3036/0/38** (v1019 close-gate). FI-02 acceptance criterion explicitly preserves this — sequential mode must not regress while parallel mode is fixed.
- **2026-05-22 (v1020 roadmap):** Out-of-scope reaffirmations from v1019 spike Section 4: shape (b) `max_connections` bump is rejected (production envelope at 30 is correct), shape (c) artificial `-n` cap below `auto` is rejected (masks the underlying contention). PERF-01 may document an optimal-but-conservative default different from `auto`, but capping `-n` artificially to dodge the fix is excluded.
- **2026-05-22 (v1020 roadmap):** v1019 TD-13 rules are LIVE for v1020 from Day 1: REQ citation pinning (planner MUST validate `path::TestClass::test_name` node-IDs via `git grep -n "def <test_name>" <path>` before committing PLAN.md) + traceability flip (executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` in the SAME commit as SUMMARY.md).

### Pending Todos

None at roadmap time. All 9 FI-*/CI-*/PERF-*/HYG-* items are dispositioned in REQUIREMENTS.md and mapped to phases.

### Blockers/Concerns

None — v1020 roadmap is complete and ready for plan-phase. FI-02 + FI-03 plans will need to re-grep the codebase for cited test names AFTER FI-01's taxonomy lands (standard TD-13 rule).

## Session Continuity

Last session: 2026-05-22T14:00:00.000Z
Stopped at: v1020 roadmap defined; ready for /gsd:plan-phase 1087
Resume file: None

## Operator Next Steps

- Run `/gsd:plan-phase 1087` to begin Phase 1087: Fixture-Isolation Spike (Taxonomy) — spike-first, audit doc only, no code changes

## Deferred Items

Carried into v1020 from v1019 close (2026-05-22):

- **FI-01/FI-02/FI-03** — 192 fixture-scope pytest failures exposed by `pytest -n auto` parallelism (not asyncpg cascade — that is closed; not a regression of TD-10 — sequential mode is clean at 3036/0/38). Needs spike-driven fixture-isolation audit + per-category fixes + regression pins.
- **CI-01** — Wire a `pytest-parallel-isolation` GitHub Actions job sister to v1017's `alembic-clean-db`. No CI gate today blocks regressions to parallel test health.
- **CI-02** — Switch default `make test` invocation to parallel once FI-02 lands; sequential becomes the debugging opt-in.
- **PERF-01** — Benchmark `pytest -n 4`/`pytest -n 8`/`pytest -n auto` post-FI-02 with v1019 spike methodology; pick documented optimal default for CI-02.
- **HYG-01** — Audit current 38 sequential-mode skips; disposition each `KEEP/FIX/REMOVE` once FI-02 lands.
- **HYG-02** — Flake hunt: run `pytest -n auto` 3× consecutive after FI-02 + FI-03 land; log non-deterministic failures.
- **HYG-03** — Paper-trail v1019 WR-01: `frontend/package.json:23` `lint:sec-fu-03-no-false-positive` script is present at HEAD but the v1019 audit noted "no follow-up commit documented." Commit a CHANGELOG line under `[1.5.5]` or a `docs/` note citing v1019's audit and confirming script preserved.
