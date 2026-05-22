---
gsd_state_version: 1.0
milestone: v1020
milestone_name: Fixture Isolation
status: Phase 1090 closed; v1020 milestone shipped; tags v1020 + v1.5.5 cut
stopped_at: "Phase 1090 (HYG-01 + HYG-02 + HYG-03) shipped — v1020 milestone closed; tags v1020 (local) + v1.5.5 (public) at 8a924bb690b197fbbe498542055adbda3cae3cc1"
last_updated: "2026-05-22T21:47:58Z"
last_activity: 2026-05-22 — Phase 1090 closed; v1020 milestone shipped; HYG-01 + HYG-02 + HYG-03 traceability flipped in single TD-13 commit `8a924bb6`; tags `v1020` + `v1.5.5` cut at same SHA
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 11
  completed_plans: 11
  percent: 100
---

# State

## Current Position

Phase: 1090 — Skip Audit + Flake Hunt + Close-Gate — COMPLETE; v1020 milestone shipped
Plan: 1090-02-PLAN.md — COMPLETE (REQUIREMENTS.md + ROADMAP.md + 1090-SUMMARY.md + CHANGELOG.md in single TD-13 atomic commit `8a924bb6`)
Status: Phase 1090 closed; v1020 milestone shipped; tags v1020 + v1.5.5 cut at `8a924bb6`
Last activity: 2026-05-22 — Phase 1090 closed; v1020 milestone shipped; HYG-01 + HYG-02 + HYG-03 traceability flipped in single TD-13 commit (`8a924bb6`); tags `v1020` + `v1.5.5` cut at same close SHA

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1020 closed; next: milestone planning (no carry-forwards beyond v1021 engine-level retry deferral)

## Last Shipped Milestone

**Version:** v1020 Fixture Isolation
**Shipped:** 2026-05-22
**Phases:** 1087-1090 (4 phases, 11 plans, 9/9 reqs)
**Tag:** `v1020` (local) + `v1.5.5` (public) at commit `8a924bb6`
**Close-gate doc:** `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-01-CLOSE-GATE.md`
**Phase summary:** `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-SUMMARY.md`

**Previous:** v1019 Hygiene Tail — v1018 Frontend + xdist + Process (shipped 2026-05-22, public tag `v1.5.4` at `02cb25db`, audit `.planning/milestones/v1019-MILESTONE-AUDIT.md`)

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
- **2026-05-22 (Phase 1087 close):** Measurement against HEAD `d340c22e` produces **648 failures** under `pytest -n auto` (vs v1019's 192-failure estimate — a lower bound). Dominant category: **per-worker `_test_db_lifecycle` session-fixture race on gw15 (407 failures, 62.8%)** — silent-swallow in conftest.py:275-278 catches `OperationalError("too many clients already")` during staggered-startup window, fails to create per-worker DB, downstream tests fail with `InvalidCatalogNameError`. NONE of the 4 v1019 hypothesis categories (Redis singleton, storage override, dependency_overrides leak, autouse-fixture coupling) reproduced — each documented as 0-count in audit Section 4 for traceability.
- **2026-05-22 (Phase 1087 close):** Section 5 fix sequencing for Phase 1088 — fix per-worker DB lifecycle race FIRST (single-file conftest.py fix; clear regression pin shape); 4.2/4.3/4.4 cascade subcategories sequenced behind re-measure gates because cascade categories interact (fixing 4.1 may partially resolve them). Re-measure protocol: drop stale per-worker DBs → sequential baseline `failed == 0` → `pytest -n auto --junitxml=...` → re-categorize → report movement across ALL categories.
- **2026-05-22 (Phase 1088-01 close):** Plan 1088-01 closed category 4.1 (407 → 0) via structural `OperationalError` handler at `backend/tests/conftest.py:275-278` replacing silent-swallow; extracted `_create_test_db_with_retry` helper between `_drop_test_database_if_exists` and `_test_db_lifecycle`. Retry budget `(1.0, 2.0, 4.0)` = 7s cumulative wait; loud fail on exhaust. 3 regression pins (canonical + propagate-non-contention + exhaust-budget). Sequential baseline 3039/0/38 preserved.
- **2026-05-22 (Phase 1088-02 close):** Re-measure gate decision `SPAWN-1088-03-AND-1088-04` — both 4.2 (188 > 50) and 4.3 (172 > 30) exceeded thresholds; cascade did NOT transitively resolve secondary categories. gw15's newly-functioning setup phase shifted demand into 4.2/4.3 rather than reducing total demand (cross-category drift commentary in audit doc).
- **2026-05-22 (Phase 1088-03 close):** Plan 1088-03 closed category 4.2 (188 → 47 → 21) via `_run_with_too_many_clients_retry` async helper + widened catch tuple `_TRANSIENT_CONTENTION_EXCEPTIONS = (OperationalError, asyncpg.TooManyConnectionsError, asyncpg.CannotConnectNowError)`. Iter-1 → iter-2 widening required after first measurement showed 42% coverage; raw asyncpg surfaces through `bind.connect()` → `greenlet_spawn` path. 4 regression pins.
- **2026-05-22 (Phase 1088-04 close):** Plan 1088-04 partial close of category 4.3 (137 → 48) via `_acquire_test_session_with_retry` @asynccontextmanager wrapping `override_get_db` AND `test_db_session` (Rule-2 sibling fixture extension) + eager warm-up `SELECT 1` inside retry envelope (iter-1 zero-coverage → iter-2 → iter-3 progression). 48 residual fires AFTER `await session.commit()` releases warm-up's connection — outside any session-factory-level retry envelope. Architectural escalation REPORTED (NOT auto-applied) for engine-level pool retry vs HYG-02 acceptance. 4 regression pins.
- **2026-05-22 (Phase 1088-05 close):** Phase 1088 close. Cascade 648 → 76 (-88.3%). Threshold relaxation for category 4.3 (=48; original audit threshold <30; relaxed to ≤50) orchestrator pre-approved; deferred to Phase 1090 HYG-02 flake hunt (3× consecutive runs validate determinism). REQUIREMENTS.md FI-02 + FI-03 + ROADMAP.md Phase 1088 + 1088-05-SUMMARY.md flipped in SINGLE commit `6a618198` per TD-13 `requirements_traceability_flip` rule. 11 regression pins consolidated under `backend/tests/test_fixture_isolation_v1020.py`. Sequential 3047/0/38 preserved.
- **2026-05-22 (Phase 1089-01 close):** PERF-01 baseline shipped — audit doc `.planning/audits/PYTEST-XDIST-PERF-v1020.md` ships 4 measured runs (sequential 545.02s 3047/0/38 + n=4 356.12s 3046/1/0 + n=8 370.08s 3044/3/0 + n=auto 442.75s 2952/78/23). Section 5 recommends `-n 4` as the documented default for CI-01 + CI-02. Rationale: n=4 wins on BOTH wall-clock (1.53× speedup vs n=auto's 1.23×) AND cascade failures (1 non-cascade flake vs 101 cascade-class). Peak DB conns at n=4 were 7 of 30 (23% of ceiling). REQUIREMENTS.md `Out of Scope` clause explicitly authorises the divergence as "data-justified" (99% cascade reduction).
- **2026-05-22 (Phase 1089-02 close):** CI-01 wired — `pytest-parallel-isolation` job added at `.github/workflows/ci.yml:493-595` after the `alembic-clean-db` block. Trigger: `backend == 'true' || alembic == 'true' || push`. Test invocation: `uv run pytest -n 4 -v --tb=short -m 'not perf'`. Skip enterprise overlay path (simpler-is-better per CONTEXT.md). `e2e-test` job's `needs:` list extended to include the new job (forward-compat — e2e-test is currently `if: false`). CI live-verification deferred to first post-merge run. Sequential 3047/0/38 preserved (re-verified pre-commit at 543.28s).
- **2026-05-22 (Phase 1089-03 close):** CI-02 default switched — `Makefile:29` `test:` target now runs `-n 4`; new `test-sequential:` target at `Makefile:32` preserves no-args sequential debugging path. REQUIREMENTS.md CI-01 + CI-02 + PERF-01 (3 reqs) + ROADMAP.md Phase 1089 row + 1089-03-SUMMARY.md flipped in SINGLE atomic TD-13 commit `11aae40f` per `requirements_traceability_flip` rule (4-file atomic + 1-file STATE.md follow-up). PERF-01-drives-CI-default contract closed: `diff <(grep "uv run pytest -n " ci.yml)` and `<(grep "uv run pytest -n " Makefile)` agree on `-n 4`. Sequential 3047/0/38 preserved (re-verified pre-commit at 543.12s).
- **2026-05-22 (Phase 1090-01 close):** Plan 1090-01 produced `1090-01-CLOSE-GATE.md` working draft with HYG-01 38-skip audit (all 38 dispositioned KEEP — intentional environment/edition gates) + HYG-02 6-run flake hunt (3× `-n auto` + 3× `-n 4`; `-n 4` produces 0/0/0 across 3 runs validating PERF-01 default; `-n auto` produces 6 deterministic + 173 non-deterministic flake-class node-IDs disposition'd defer-to-v1021) + HYG-03 WR-01 paper-trail draft (grep-verified `frontend/package.json:23` + `:22` script preservation). NO REQUIREMENTS.md / ROADMAP.md / CHANGELOG.md edit — Plan 1090-02 owns atomic TD-13 flip. Sequential baseline 3047/0/38 re-verified pre-Task 1 (542.39s) and post-HYG-02 (544.75s).
- **2026-05-22 (Phase 1090-02 close):** Plan 1090-02 closed Phase 1090 + v1020 milestone. Doc-extension commit `a742c04d` pre-staged close-gate matrix + Playwright MCP 5/5 results (orchestrator-driven; surface 5 placeholder UUID 404 disposition'd as expected). TD-13 atomic close commit `8a924bb6` lands EXACTLY 4 files (REQUIREMENTS.md + ROADMAP.md + 1090-SUMMARY.md + CHANGELOG.md) flipping HYG-01 + HYG-02 + HYG-03 (3 checkboxes + 3 traceability rows) + Phase 1090 row + v1020 milestone status 🚧 → ✅ + per-plan list (2/2 plans complete) + `[Unreleased]` → `[1.5.5] - 2026-05-22` block. Both tags (`v1020` local + `v1.5.5` public) cut at `8a924bb6` — annotated-tag objects differ but both `^{commit}` deref to same SHA. Close-gate matrix all GREEN (sequential 3047/0/38, parallel -n 4 3047/0/0/38, typecheck exit 0, vitest 2105/2105, e2e:smoke:builder 25/0/1, Playwright MCP 5/5). v1021 carry-forward: cascade flake-class residual at `-n auto` (engine-level retry envelope).

### Pending Todos

None — v1020 milestone closed.

### Blockers/Concerns

None at v1020 close. **CI live-verification of `pytest-parallel-isolation` deferred to first post-merge run** per Phase 1089 close-state. Operator runs `gh run list --workflow=ci.yml --limit=1 && gh run watch <run_id>` to confirm green on first post-merge gate firing.

## Session Continuity

Last session: 2026-05-22T21:47:58Z
Stopped at: v1020 Fixture Isolation complete; tags v1020 + v1.5.5 cut at 8a924bb690b197fbbe498542055adbda3cae3cc1
Resume file: None

## Operator Next Steps

- **Push tags to remote** (operator decision; out of plan scope): `git push origin v1020 v1.5.5`.
- **GitHub release notes** (operator decision): generate from `CHANGELOG.md` `[1.5.5]` block.
- **Post-merge CI live-verification:** after this commit lands in main (or on a PR), run `gh run list --workflow=ci.yml --limit=1 && gh run watch <run_id>` to confirm the `pytest-parallel-isolation` gate fires green for the first time. (Phase 1089 deferred item; consume on first post-merge run.)
- **`/gsd-archive-milestone v1020`** to move the v1020 milestone summary into `.planning/milestones/v1020-ROADMAP.md` archive (mirrors v1019 close pattern).
- **Next milestone planning:** v1020 closes clean with one v1021 carry-forward (cascade flake-class residual at `-n auto` → engine-level retry envelope).

## Deferred Items

v1020 milestone complete; deferred items struck through:

- ~~**FI-01**~~ — CLOSED 2026-05-22 by Phase 1087 (audit doc `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` shipped; 648 failures classified across 6 categories; Section 5 sequencing handed to Phase 1088)
- ~~**FI-02 / FI-03**~~ — CLOSED 2026-05-22 by Phase 1088 (cascade 648 → 76 (-88.3%); 11 regression pins consolidated under `backend/tests/test_fixture_isolation_v1020.py`; sequential 3047/0/38 preserved; threshold relaxation for category 4.3 = 48 documented in REQUIREMENTS.md FI-02 acceptance text + Phase SUMMARY)
- ~~**CI-01**~~ — CLOSED 2026-05-22 by Phase 1089-02 (`pytest-parallel-isolation` job present at `.github/workflows/ci.yml:493-595` running `uv run pytest -n 4 -v --tb=short -m 'not perf'`; sister-shape to `alembic-clean-db`; `e2e-test` `needs:` list extended; live-verification deferred to first post-merge `gh run watch`)
- ~~**CI-02**~~ — CLOSED 2026-05-22 by Phase 1089-03 (`Makefile:29` `test:` target runs `uv run pytest -n 4 -v --tb=short`; new `test-sequential:` target at `Makefile:32` preserves no-args sequential debugging path; Option A per CONTEXT.md — `pyproject.toml` `addopts` un-widened)
- ~~**PERF-01**~~ — CLOSED 2026-05-22 by Phase 1089-01 (audit doc `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5 recommends `-n 4` — 1.53× sequential speedup, 99% cascade reduction vs n=auto; consumed verbatim by CI-01 + CI-02)
- ~~**HYG-01**~~ — CLOSED 2026-05-22 by Phase 1090 (38 sequential-mode skips dispositioned KEEP — intentional environment/edition gates; documented in `1090-01-CLOSE-GATE.md` Section HYG-01)
- ~~**HYG-02**~~ — CLOSED 2026-05-22 by Phase 1090 (6-run flake hunt: 3× `-n 4` produces 0/0/0 deterministic, validates PERF-01 default; 3× `-n auto` produces 6 deterministic + 173 non-deterministic, disposition defer-to-v1021 engine-level retry per Phase 1088-04 architectural escalation)
- ~~**HYG-03**~~ — CLOSED 2026-05-22 by Phase 1090 (CHANGELOG `[1.5.5]` block cites `frontend/package.json:23` `lint:sec-fu-03-no-false-positive` script preserved at HEAD; v1019 audit WR-01 paper-trail closed)

### v1021 carry-forward (1)

- **Cascade flake-class residual at `-n auto`** — HYG-02 confirmed 6 deterministic + 173 non-deterministic node-IDs fail under 16-worker parallelism (all cascade-driven timing-race in fixture setup window). Phase 1088 NullPool + 5s stagger + retry helpers shifted bottleneck from capacity to per-window racing. Next architectural step: engine-level retry envelope. `-n 4` CI gate handles operational defense.
