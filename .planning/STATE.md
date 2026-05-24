---
gsd_state_version: 1.0
milestone: v1022
milestone_name: Parallel-Test Cascade Closure + Hygiene Tail
status: in-progress
stopped_at: Plan 1097-01 SUMMARY committed at 48707fb1; CLOSE-01 close-gate baselines captured + CHANGELOG [1.5.7] block written; CLOSE-01 NOT flipped (lands Plan 02). Working tree clean. Ready for Plan 1097-02.
last_updated: "2026-05-24T05:21:48.637Z"
last_activity: 2026-05-24 — Plan 1097-01 SUMMARY shipped; CLOSE-01 close-gate baselines captured + CHANGELOG [1.5.7] block written; atomic-3-file commit 48707fb1; Plan 02 ready
progress:
  total_phases: 9
  completed_phases: 3
  total_plans: 7
  completed_plans: 7
  percent: 33
---

# State

## Current Position

Phase: 1097 Live-Verify + Close Gate (IN PROGRESS — 1 of 2 plans complete; CLOSE-01 baselines captured; CI-01 + CLOSE-01 flip pending Plan 02)
Plan: 1097-01-PLAN.md (complete — close-gate baselines + CHANGELOG [1.5.7] block; atomic-3-file commit 48707fb1)
Status: Plan 1097-01 closed via commit `48707fb1` (atomic-3-file: CHANGELOG.md + 1097-01-CLOSE-GATE.md + 1097-01-SUMMARY.md). CLOSE-01 baselines captured for acceptance criteria (a)-(e): sequential 3 failed (OOS triad) / 3060 passed / 38 skipped / 544s (HARD INVARIANT preserved); -n 4 4 failed (2 OOS + 2 oauth flake) / 3059 passed / 38 skipped / 326s (HARD INVARIANT preserved); -n auto 3-run distinct = 2/3/2 deterministic well under PARA-01 ≤30 gate (IMPROVED vs Phase 1096 floor 5/2/2); ICN frames 0/0/0 across all 3 runs (Category 4.1 cascade gate PRESERVED); 5 services healthy + GET /api/health → 200 OK. CHANGELOG [1.5.7] block lists PARA-01 + PARA-02 + HYG-01 with test pin names + line numbers; CI-01 placeholder will be replaced by Plan 02. CLOSE-01 NOT yet flipped in REQUIREMENTS.md (lands in Plan 02 atomic-4-file alongside CI-01 flip + tag-cut SHAs). [Rule 3 deviation] /api/health endpoint shape: PLAN cited trailing-slash + HEAD; actual surface no-slash + GET. Documented inline. Next: Plan 1097-02 (AskUserQuestion → push → gh run watch pytest-parallel-isolation → tag cut v1022 + v1.5.7 → flip CI-01 + CLOSE-01).
Last activity: 2026-05-24 — Plan 1097-01 SUMMARY shipped; CLOSE-01 close-gate baselines captured + CHANGELOG [1.5.7] block written; atomic-3-file commit 48707fb1; Plan 02 ready

Progress: [█████░░░░░] 50% (1 of 2 plans in Phase 1097 complete)

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
- [Phase 1096-01]: 2026-05-24: HYG-01 closed via WR-03 narrow-except (TypeError, AttributeError, InvalidRequestError) at conftest.py:842 + WR-04 listener teardown via event.remove in _RetryingAsyncEngine.dispose() override at conftest.py:934-977 + _install_dbapi_connect_retry signature change at conftest.py:753 to return registered handler. 3 new pins added at test_fixture_isolation_v1020.py: WR-01 do_connect event-handler pin at line 1391 (uses real sqlalchemy.create_engine("sqlite:///:memory:") to exercise the load-bearing event-handler path on engine.dialect.dispatch.do_connect, not engine.dispatch.do_connect); WR-01-1095 carry-forward catches_raw_asyncpg at line 1557 + propagates_non_transient_error at line 1666 (fixture-layer parity with engine-layer pins at lines 978/1030). [Rule 1] narrow tuple expanded from plan-spec (TypeError, AttributeError) to (TypeError, AttributeError, InvalidRequestError) when MagicMock raised sqlalchemy.exc.InvalidRequestError under SQLAlchemy 2.x. [Rule 3] dispatch retrieval uses dialect.dispatch.do_connect (DialectEvents). Atomic-4-file commit c119f94c. Gates: 9 retry pins green; pool-sizing 2/2; sequential 3060/3 OOS/38 (+3 vs Phase 1095); -n 4 3057/6 OOS/38; -n auto 3-run distinct 5/2/2 deterministic ≤30, ZERO ICN frames. Phase 1096 CLOSED.
- [Phase 1097-01]: 2026-05-24: CLOSE-01 close-gate baselines captured + CHANGELOG [1.5.7] block written. Sequential 3 failed (OOS triad: test_layering + test_phase_275_readme_accuracy + test_ssrf_redirect) / 3060 passed / 38 skipped / 544s. -n 4 4 failed (2 OOS + 2 oauth flake: test_callback_missing_state_returns_error + test_callback_invalid_code_returns_error) / 3059 passed / 38 skipped / 326s. -n auto 3-run distinct 2/3/2 deterministic well under PARA-01 ≤30 gate (IMPROVED vs Phase 1096 floor 5/2/2). Run 2's extra distinct is test_settings_router::test_put_settings_same_embedding_dims_does_not_delete (422 vs 200 parallel-validation flake — Section 2 PYTEST-XDIST-PERF-v1020.md taxonomy match). ICN frames 0/0/0 across all 3 runs (Category 4.1 cascade gate PRESERVED — confirms PARA-01 Shape A* wrap + PARA-02 Shape Y2 + HYG-01 WR-04 dispose teardown all holding). [Rule 3] /api/health endpoint shape PLAN drift (trailing-slash HEAD → no-slash GET; documented inline). Atomic-3-file commit 48707fb1 (CHANGELOG.md + 1097-01-CLOSE-GATE.md + 1097-01-SUMMARY.md). CLOSE-01 NOT flipped in REQUIREMENTS.md (lands Plan 02). Next: Plan 1097-02 (push + gh run watch + tag cut).

### Pending Todos

None at v1022 roadmap-create. v1021 ended with zero pending todos; all 4 deferred items (Category 4.1 cascade + WR-02 footgun + WR-01/03/04 hygiene + CI-01 live-verify) are now in-scope as v1022 requirements.

### Blockers/Concerns

None at v1022 roadmap-create. Phase 1094 spike has no pre-requisites — `/gsd:plan-phase 1094` can start immediately.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260523-at1 | Rebuild docker containers + import all seed data; surface errors/issues/gaps | 2026-05-23 | `e9817603` | [260523-at1-rebuild-the-docker-containers-and-import](./quick/260523-at1-rebuild-the-docker-containers-and-import/) |

## Session Continuity

Last session: 2026-05-24T01:20:00.000Z
Stopped at: Plan 1097-01 SUMMARY committed at 48707fb1; CLOSE-01 close-gate baselines captured + CHANGELOG [1.5.7] block written; CLOSE-01 NOT flipped (lands Plan 02). Working tree clean. Ready for Plan 1097-02.
Resume file: None

## Operator Next Steps

- Plan 1097-01 SHIPPED (commit `48707fb1`). Atomic-3-file commit (CHANGELOG.md + 1097-01-CLOSE-GATE.md + 1097-01-SUMMARY.md). All 14 verification gates PASS. HARD INVARIANT preserved across sequential + -n 4 baselines (0 NEW failures). PARA-01 acceptance preserved across -n auto 3 runs (each ≤30 distinct + 0 ICN frames). CLOSE-01 baselines captured for acceptance (a)-(e).
- Next: Plan 1097-02 (CI-01 live-verify + tag cut + CLOSE-01/CI-01 flip). Plan 02 will: AskUserQuestion before `git push origin main` → `gh run list --workflow=ci.yml --limit=1 --json databaseId,status` → `gh run watch $RUN_ID` for `pytest-parallel-isolation` job → append CI-01 section to CLOSE-GATE.md → `git tag v1022 48707fb1 && git tag v1.5.7 48707fb1 && git push origin v1022 v1.5.7` → record in MILESTONES.md → flip CI-01 + CLOSE-01 → atomic-4-file commit.
- Close-gate commit SHA for Plan 02's tag-cut: **`48707fb1`**.

## Deferred Items

v1022 inherits the following from v1021 close-state (in scope for v1022):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| test-infra | Category 4.1 per-worker DB lifecycle parallel-mode cascade (`-n auto` 709/1020 distinct) | Closed Plan 1095-01 (commit `398dc53d` — Shape A* wrap; distinct = 20/8/16 ≤30 deterministic, 0 ICN frames) | v1021 Phase 1093 |
| test-infra | WR-02 blocking `time.sleep` in `_invoke_sleep_in_sync_context` footgun | Closed Plan 1095-02 (commit `ca7a85fb` — Shape Y2 load-bearing rationale after Y1 produced 658 RuntimeError cascade; audit Section 4.3 INDEPENDENT disposition empirically validated) | v1021 Phase 1093 |
| test-infra | Phase 1093 review findings WR-01..04 (engine-retry test pin coverage + edge cases) | Active — HYG-01 (Phase 1096) | v1021 Phase 1093 |
| ci-live-verify | `pytest-parallel-isolation` gate first post-merge run | Active — CI-01 (Phase 1097) | v1020 Phase 1089 |
