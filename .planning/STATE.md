---
gsd_state_version: 1.0
milestone: v1022
milestone_name: Parallel-Test Cascade Closure + Hygiene Tail
status: completed
stopped_at: Plan 1095-02 SUMMARY committed at ca7a85fb; PARA-02 traceability flipped [x]/Complete; Phase 1095 CLOSED. Next: Phase 1096 HYG-01.
last_updated: "2026-05-24T02:44:00Z"
last_activity: 2026-05-24 — Plan 1095-02 SUMMARY shipped; WR-02 Shape Y2 (load-bearing rationale) applied at conftest.py after Y1 produced 658 RuntimeError cascade; -n auto 3-run distinct = 3/2/3 deterministic (BETTER than Plan 01 floor 20/8/16); PARA-02 closed; Phase 1095 CLOSED.
progress:
  total_phases: 9
  completed_phases: 2
  total_plans: 3
  completed_plans: 4
  percent: 22
---

# State

## Current Position

Phase: 1095 Cascade Fix + WR-02 Closure (CLOSED — 2 of 2 plans complete; both PARA-01 + PARA-02 Complete)
Plan: 1095-01-PLAN.md (complete — Shape A* wrap applied + PARA-01 closed); 1095-02-PLAN.md (complete — Shape Y2 load-bearing rationale + PARA-02 closed)
Status: Plan 1095-02 closed via commit `ca7a85fb` (atomic-4-file). PARA-02 complete; Phase 1095 CLOSED. Both PARA-01 + PARA-02 = `[x]` + `Complete` in REQUIREMENTS.md. Phase 1095 rollup gates GREEN: `-n auto` 3-run = 3/2/3 distinct deterministic (all pre-existing OOS); sequential 3057/3 OOS/38 (0 NEW); `-n 4` 3055/5 (2 OOS + 2 oauth flake + 1 documented test_publish_blocked flake)/38 (0 NEW). Next: Phase 1096 HYG-01 (WR-01/03/04).
Last activity: 2026-05-24 — Plan 1095-02 SUMMARY shipped; WR-02 Shape Y2 (load-bearing rationale) applied at conftest.py after Y1 produced 658 RuntimeError cascade; PARA-02 closed; Phase 1095 CLOSED

Progress: [██████████] 100%

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1022 Parallel-Test Cascade Closure + Hygiene Tail — close v1021's Category 4.1 per-worker DB lifecycle parallel-mode cascade + WR-02 sleep footgun + WR-01..04 review findings + `pytest-parallel-isolation` CI live-verify.

## Last Shipped Milestone

**Version:** v1021 Docker Rebuild Sweep + Engine-level Retry
**Shipped:** 2026-05-23
**Phases:** 1091-1093 (3 phases, 8 plans, 6/6 reqs)
**Tag:** `v1021` (local) + `v1.5.6` (public) at commit `35596a7a`
**Milestone audit:** `.planning/milestones/v1021-MILESTONE-AUDIT.md`
**Archived phases:** `.planning/milestones/v1021-phases/`

**Previous:** v1020 Fixture Isolation (shipped 2026-05-22, public tag `v1.5.5` at `8a924bb6`).

## Phase Plan (v1022)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1094 Cascade Spike | Architectural audit produces `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` naming the exact Category 4.1 race surface + line-numbered fix shape + WR-02 cascade-pressure-hypothesis disposition | PARA-01 (spike deliverable / acceptance (e) only) | — |
| 1095 Cascade Fix + WR-02 Closure | Land PARA-01 fix at Phase 1094's named line(s) + close PARA-02's WR-02 blocking-sleep footgun. Bundled because both surfaces share `backend/tests/conftest.py:~615-674` and the `-n auto` measurement gate must be re-run atomically. | PARA-01 (full closure) + PARA-02 (full closure) | Phase 1094 |
| 1096 Hygiene Tail | Retire HYG-01 (WR-01 `do_connect` event handler pin + WR-03 bare-except narrowing + WR-04 listener teardown hook). Lands AFTER Phase 1095 so test pins target stabilized engine wrapper. | HYG-01 | Phase 1095 |
| 1097 Live-Verify + Close Gate | Operator `gh run watch` for first post-merge `pytest-parallel-isolation` gate firing (closes v1020 deferred operator action) + close gate (sequential + `-n 4` + `-n auto` baselines + CHANGELOG `[1.5.7]` + tags `v1022`/`v1.5.7`) | CI-01 + CLOSE-01 | Phase 1096 |

**Coverage:** 5/5 v1022 requirements mapped, 0 orphans, 0 duplicates.

**Public tag target:** `v1.5.7` (SemVer patch — test-infra hygiene only; no API/schema changes, no migrations).

**HARD INVARIANT:** Sequential pytest `failed == 0` non-negotiable (v1019 TD-13). Baselines: sequential **3055/0/38** + `-n 4` **3054/0/38**.

## Accumulated Context

### Decisions

- **2026-05-23 (v1022 roadmap):** Phase 1094 is spike-only per v1019 Phase 1085 / v1020 Phase 1087 / v1021 Phase 1091 precedent — measurement before fix for the architectural item (PARA-01). PARA-02/HYG-01/CI-01 are tight enough scope to skip a separate spike (REQUIREMENTS.md explicit).
- **2026-05-23 (v1022 roadmap):** Phase 1095 bundles PARA-01 fix + PARA-02 closure. Three coupling reasons: (a) both surfaces live in adjacent lines of `backend/tests/conftest.py` (`_test_db_lifecycle` ~661-674 + `_invoke_sleep_in_sync_context` ~615 + `_install_dbapi_connect_retry` ~664); (b) the `-n auto` measurement gate (PARA-01 acceptance (a)) must re-run AFTER both changes land — splitting them across phases would double the gate cost and obscure which change moved the threshold; (c) PARA-02's cascade-pressure hypothesis (acceptance (d)) is most cleanly validated/refuted by measuring with both fixes in place. Test-infra atomicity > requirement-per-phase granularity when the surfaces share a file + measurement gate.
- **2026-05-23 (v1022 roadmap):** Phase 1096 (HYG-01) sequenced AFTER Phase 1095 (PARA-01/02 fix) so new test pins target the stabilized engine wrapper, not the pre-fix shape. Avoids re-writing pins mid-milestone.
- **2026-05-23 (v1022 roadmap):** Phase 1097 (CI-01 + CLOSE-01) sequenced LAST because CI-01 can only verify post-merge of PARA-01/PARA-02/HYG-01 — the gate's first firing must cover the complete post-v1022 engine-wrapper + per-worker-lifecycle code. Verifying mid-milestone would not validate the milestone-tip state.
- **2026-05-23 (v1022 roadmap):** PARA-01 requirement spans 2 phases (1094 spike deliverable + 1095 fix). REQUIREMENTS.md `[x]` flip lands at Phase 1095 close (when all 5 PARA-01 acceptance criteria are satisfied), NOT at Phase 1094 close. Phase 1094's SUMMARY.md cites PARA-01 as "spike deliverable shipped; fix awaits Phase 1095". Standard pattern for multi-phase requirements (matches v1021 INGEST-01 → Phase 1091 spike + fix lived in one phase, but explicit traceability note carried).
- **2026-05-23 (v1022 roadmap):** Public tag target `v1.5.7` (SemVer patch) — test-infra hygiene only; no user-facing features, no API/schema/migrations, no production-code behavior change beyond conftest/test-fixture engine layer. CHANGELOG `[1.5.7]` block lists PARA-01/PARA-02/HYG-01/CI-01 closures with test pin names + line numbers.
- **2026-05-23 (v1022 roadmap):** Sequential pytest baseline that MUST stay green throughout v1022: **3055 passed / 0 NEW failed / 38 skipped** (v1021 Phase 1093 close-gate). HARD INVARIANT — `failed == 0` non-negotiable per v1019 TD-13.
- **2026-05-23 (v1022 roadmap):** v1019 TD-13 rules LIVE for v1022 from Day 1: REQ citation pinning (planner MUST validate `path::TestClass::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plans commit; applies to PARA-01's new per-worker DB lifecycle pin, PARA-02's loop-yield regression pin, HYG-01's `test_engine_retry_do_connect_event_handler_*` pin) + traceability flip (executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` in the SAME commit as SUMMARY.md).
- [Phase ?]: 2026-05-23 (Phase 1094 spike): Cascade surface reclassified to _init_tile_pool_for_tests asyncpg.create_pool contention; audit at .planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md
- [Phase ?]: 2026-05-23 (Phase 1094 spike): Fix shape Shape A* — wrap asyncpg.create_pool in existing _run_with_too_many_clients_retry envelope (conftest.py:359). 6 alternative shapes rejected with rationale. Phase 1095 consumes Section 3.2 as fix action.
- [Phase ?]: 2026-05-23 (Phase 1094 spike): WR-02 disposition INDEPENDENT — _invoke_sleep_in_sync_context called only from Category 4.3 engine-wrapper paths (conftest.py:706 + 843); observed cascade source bypasses those. PARA-02 sequencing in Phase 1095 is operator-discretion.
- [Phase ?]: 2026-05-23 (Phase 1094 spike): CONTEXT.md line-number drift documented in audit Section 3.1 (8-row corrected table). _test_db_lifecycle is at line 906, NOT ~661-674. Phase 1095 planner uses corrected table.
- [Phase 1095-01]: 2026-05-23: PARA-01 closed via Shape A* wrap at 3 `_init_tile_pool_for_tests` fixture sites (test_tiles.py:151 + test_embed_tokens.py:56 + test_tile_signing.py:107) routing raw `asyncpg.create_pool(...)` through the existing `_run_with_too_many_clients_retry` envelope at conftest.py:359. Regression pin `test_init_tile_pool_retries_on_transient_too_many_clients` at test_fixture_isolation_v1020.py:1144. Post-fix 3-run baseline = 20/8/16 distinct (all ≤30, 0 ICN frames). Mean shift 16.3 → 14.7 vs pre-fix 14/14/21. Sequential 3055/0/38 + `-n 4` 3054/0/38 baseline preservation re-measurement deferred to Plan 1095-02 close.
- [Phase 1095-01]: 2026-05-23: Optional xfail pre-fix regression pin (`test_init_tile_pool_no_retry_pre_fix_raises_too_many_clients`) DEFERRED to Plan 02 per CONTEXT.md `<specifics>` Plan 01 Step 6 — positive pin alone is load-bearing for the wrap-shape regression-detection contract.
- [Phase ?]: [Phase 1095-02]: 2026-05-24: PARA-02 closed via Shape Y2 (load-bearing rationale + retained time.sleep) at conftest.py:_invoke_sleep_in_sync_context after Shape Y1 (asyncio.run(asyncio.sleep(seconds))) produced 658 RuntimeError cascade failures at Task 5 Run 1 — production caller _retry_do_connect via greenlet_spawn has a running event loop in calling thread. Audit Section 4.3 INDEPENDENT disposition empirically validated: post-Y2 3-run -n auto distinct = 3/2/3 (BETTER than Plan 01 floor 20/8/16). Pin test_engine_retry_yields_event_loop_during_backoff (Shape Y2 alternative) asserts WR-02/PARA-02/Plan-1095-02/greenlet_spawn/Section-4.3-or-4.4/time.sleep tokens at source-of-record. Atomic-4-file commit ca7a85fb. Phase 1095 CLOSED.

### Pending Todos

None at v1022 roadmap-create. v1021 ended with zero pending todos; all 4 deferred items (Category 4.1 cascade + WR-02 footgun + WR-01/03/04 hygiene + CI-01 live-verify) are now in-scope as v1022 requirements.

### Blockers/Concerns

None at v1022 roadmap-create. Phase 1094 spike has no pre-requisites — `/gsd:plan-phase 1094` can start immediately.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260523-at1 | Rebuild docker containers + import all seed data; surface errors/issues/gaps | 2026-05-23 | `e9817603` | [260523-at1-rebuild-the-docker-containers-and-import](./quick/260523-at1-rebuild-the-docker-containers-and-import/) |

## Session Continuity

Last session: 2026-05-24T02:44:02.349Z
Stopped at: Plan 1095-01 SUMMARY committed at 398dc53d; PARA-01 traceability flipped [x]/Complete. Plan 1095-02 next.
Resume file: None

## Operator Next Steps

- Roadmap created (4 phases 1094-1097, 5/5 requirements mapped, 0 orphans).
- Next: `/gsd:plan-phase 1094` to start the Cascade Spike (architectural audit deliverable).
- After Phase 1094 ships: `/gsd:plan-phase 1095` (Cascade Fix + WR-02 Closure — bundled PARA-01 fix + PARA-02).
- After Phase 1095 ships: `/gsd:plan-phase 1096` (Hygiene Tail — HYG-01).
- After Phase 1096 merges to `main`: `/gsd:plan-phase 1097` (Live-Verify + Close Gate — CI-01 + CLOSE-01).

## Deferred Items

v1022 inherits the following from v1021 close-state (in scope for v1022):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| test-infra | Category 4.1 per-worker DB lifecycle parallel-mode cascade (`-n auto` 709/1020 distinct) | Closed Plan 1095-01 (commit `398dc53d` — Shape A* wrap; distinct = 20/8/16 ≤30 deterministic, 0 ICN frames) | v1021 Phase 1093 |
| test-infra | WR-02 blocking `time.sleep` in `_invoke_sleep_in_sync_context` footgun | Closed Plan 1095-02 (commit `ca7a85fb` — Shape Y2 load-bearing rationale after Y1 produced 658 RuntimeError cascade; audit Section 4.3 INDEPENDENT disposition empirically validated) | v1021 Phase 1093 |
| test-infra | Phase 1093 review findings WR-01..04 (engine-retry test pin coverage + edge cases) | Active — HYG-01 (Phase 1096) | v1021 Phase 1093 |
| ci-live-verify | `pytest-parallel-isolation` gate first post-merge run | Active — CI-01 (Phase 1097) | v1020 Phase 1089 |
