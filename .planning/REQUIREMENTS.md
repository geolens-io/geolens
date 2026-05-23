# Requirements: GeoLens — v1022 Parallel-Test Cascade Closure + Hygiene Tail

**Defined:** 2026-05-23
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

**Milestone goal:** Close v1021's three test-infra carry-forwards in a single hygiene-shape milestone. (1) Category 4.1 per-worker DB lifecycle parallel-mode cascade (`pytest -n auto` produced 3/706 → 5/1020 distinct `InvalidCatalogNameError` failures on Runs 3+4 of Phase 1093-02's post-fix measurement — a different architectural surface than TEST-01's in-test wrapper, per `.planning/milestones/v1021-phases/1093-engine-level-retry-envelope/1093-02-FINDINGS.md`). (2) WR-02 footgun — `_invoke_sleep_in_sync_context` calls blocking `time.sleep()` from greenlet context, freezing the asyncio loop up to 7s on full budget exhaustion and likely compounding Category 4.1 pressure. (3) WR-01/03/04 hygiene closure for the engine-retry envelope. Plus the v1020-deferred operator action: `pytest-parallel-isolation` CI gate first post-merge live-verify.

**Spike-first** per v1019 Phase 1085 / v1020 Phase 1087 / v1021 Phase 1091 precedent — measurement before fix for PARA-01 (the architectural item). PARA-02, HYG-01, CI-01 are tight enough scope to skip the spike.

**Public tag target:** `v1.5.7` (SemVer patch — test-infra hygiene only; no user-facing features, no API contract changes, no migrations, no production-code behavior change beyond conftest/test-fixture engine layer).

**HARD INVARIANT (v1019 TD-13):** `failed == 0` in sequential mode is non-negotiable. Baselines: sequential **3055/0/38** (v1021 Phase 1093 close-gate) + `-n 4` **3054/0/38** (4 OOS — test_layering + test_phase_275 + 2 oauth flakes per PYTEST-XDIST-PERF-v1020.md). REQUIREMENTS.md `[ ]` → `[x]` flip + `Pending` → `Complete` lands in the SAME commit as SUMMARY.md per executor's `requirements_traceability_flip` rule.

---

## v1022 Requirements

Requirements for this milestone. All `PARA-*` / `HYG-*` / `CI-*` / `CLOSE-*` IDs map to roadmap phases in ROADMAP.md.

### Parallel-Test Cascade

- [ ] **PARA-01**: Close the Category 4.1 per-worker DB lifecycle parallel-mode cascade so `pytest -n auto` produces ≤ 30 distinct failures per run **deterministically across 3 consecutive runs** (the v1021 close-gate's literal Option A interpretation of "≤10 failed" was satisfied on Runs 1+2 but BREACHED on Run 3 with 706 errors / 4787 raw `InvalidCatalogNameError` lines per `.planning/milestones/v1021-phases/1093-engine-level-retry-envelope/1093-02-FINDINGS.md`). Spike-first deliverable identifies the exact race surface — most-likely candidates from the findings doc are (a) `_test_db_lifecycle` at `backend/tests/conftest.py:~661-674` lacks retry coverage at the `dev_engine.connect()` path under timing-sensitive `-n auto` conditions, and (b) the engine wrapper INCREASES pressure on per-worker DB CREATE/migrate by allowing more tests to enter warm-up SELECT 1 (Plan 1089 PERF-01 Section 4 "timing-driven race-window collisions" finding). Acceptance criteria: (a) `cd backend && uv run pytest -n auto tests/` produces ≤ 30 distinct failures (`failed + errors`) per run across 3 consecutive runs with stale-DB cleanup between runs (mirroring PYTEST-XDIST-PERF-v1020.md Section 1 Step 1b); (b) sequential pytest baseline preserved at `3055 passed / 0 NEW failed / 38 skipped` (hard invariant — pre-existing OOS rows of `test_layering` + `test_phase_275` + `test_ssrf_redirect` may remain failing, but no NEW failures attributable to v1022 changes); (c) `-n 4` baseline preserved at `3054 passed / 0 NEW failed / 38 skipped` (4 OOS = 2 pre-existing + 2 oauth flake-class per PYTEST-XDIST-PERF-v1020.md Section 2 n=8 row); (d) at least one regression pin in `backend/tests/test_fixture_isolation_v1020.py` (or a new `test_per_worker_db_lifecycle_v1022.py`) covers the per-worker DB lifecycle retry shape under the same `InvalidCatalogNameError` injection model that v1020 already uses for the fixture-layer pins; (e) the spike deliverable (`.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` or equivalent) documents the chosen fix shape with line numbers BEFORE the fix lands. **Out-of-scope reaffirmation:** Postgres `max_connections` bump (production envelope at 30 is correct) and artificial `-n` cap below `auto` (masks contention) — same rationale as v1020 and v1021 out-of-scope tables. The fix must live in the test-infra retry layer, not headroom or concurrency caps.

- [ ] **PARA-02**: Close the WR-02 footgun — `_invoke_sleep_in_sync_context` at `backend/tests/conftest.py:~615` calls blocking `time.sleep()` when invoked from greenlet context (sync-bridge from asyncio retry path), freezing the asyncio event loop for up to 7s on full budget exhaustion (`_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` summed). Per v1021 Phase 1093 review WR-02 and `.planning/milestones/v1021-MILESTONE-AUDIT.md:88`, the blocking sleep may contribute to Category 4.1 cascade pressure on Runs 3+4 because connection-release events queued behind the frozen loop never fire, prolonging connection saturation. Acceptance criteria: (a) `_invoke_sleep_in_sync_context` either yields via `asyncio.get_event_loop().run_in_executor()` / `anyio.sleep()` / a non-blocking equivalent that does NOT starve the loop, OR a load-bearing rationale is inline-commented explaining why blocking sleep is required at this specific call site (with a documented mitigation in the engine wrapper itself); (b) a regression pin in `backend/tests/test_fixture_isolation_v1020.py` (or `test_engine_retry_envelope.py`) asserts the asyncio event loop continues processing other tasks during the retry-backoff window — the existing `test_engine_retry_exhausts_budget_then_fails_loudly` pin could be extended with a concurrent-task scheduling assertion; (c) zero regression on the 4 existing `test_engine_retry_*` pins (`test_engine_retry_succeeds_on_transient_too_many_clients` + `test_engine_retry_catches_raw_asyncpg_too_many_connections` + `test_engine_retry_propagates_non_transient_operational_error` + `test_engine_retry_exhausts_budget_then_fails_loudly` — all 4 must continue passing); (d) PARA-02 is investigated BEFORE PARA-01 lands its fix, OR the PARA-01 spike's findings doc explicitly addresses whether WR-02 closure is a prerequisite for PARA-01's ≤30 threshold to hold — the cascade-pressure hypothesis must be validated or ruled out, not silently deferred.

### Hygiene

- [ ] **HYG-01**: Retire WR-01, WR-03, WR-04 from Phase 1093 review (`.planning/milestones/v1021-MILESTONE-AUDIT.md:87-90`) — the three remaining engine-retry envelope hygiene findings:
  - **WR-01 (pin coverage)** — extend `backend/tests/test_fixture_isolation_v1020.py` with at least one regression pin that exercises the load-bearing `do_connect` event handler retry path (currently the 4 `test_engine_retry_*` pins exercise the `.connect()`/`.dispose()` wrapper-method path; the production-effective path is `_install_dbapi_connect_retry` at `backend/tests/conftest.py:~664`). New pin name suggested: `test_engine_retry_do_connect_event_handler_retries_on_transient_error`.
  - **WR-03 (too-broad except)** — narrow the `except Exception: pass` block during event-listener install (currently in `_install_dbapi_connect_retry`) to explicit exception types or remove the bare-except entirely. v1020 audit Section 4.1 condemned this anti-pattern as silent-swallow; the replacement should EITHER catch a specific SQLAlchemy event-API exception class OR loud-fail (raise) if install fails so future SQLAlchemy event-API changes are visible.
  - **WR-04 (no removal hook)** — add a teardown removal call for the `do_connect` listener so a future refactor wrapping an existing shared engine multiple times does not stack listeners. Candidate: `event.remove(sync_engine, "do_connect", <handler>)` in `_RetryingAsyncEngine.dispose()` override, or a `pytest` fixture-level finalizer.

  Acceptance criteria: (a) all 3 WR findings have inline test pin coverage and/or code-comment justification at the source-of-record line; (b) the 4 existing `test_engine_retry_*` pins + `test_xdist_engine_uses_nullpool` + `test_sequential_engine_uses_queuepool` continue to PASS (the v1021 wrapper invariants — `.pool` accessor preservation via `@property` delegation + `_TRANSIENT_CONTENTION_EXCEPTIONS` line 352 single-definition + `_SETUP_PHASE_RETRY_BACKOFFS` line 333 single-definition — must hold); (c) zero new failures in the sequential / `-n 4` / `-n auto` baselines vs the PARA-01 / PARA-02 post-fix state.

### CI Verification

- [ ] **CI-01**: Live-verify the `pytest-parallel-isolation` CI gate (sister-job to v1017's `alembic-clean-db`, added in v1020 Phase 1089) on its first post-v1022-merge run on real GitHub Actions infrastructure. Closes the v1020 Phase 1089 deferred operator action documented in `.planning/milestones/v1020-MILESTONE-AUDIT.md` Deferred Items table. Acceptance criteria: (a) after v1022 merges to `main`, operator runs `gh run list --workflow=ci.yml --limit=1 --json databaseId,status` to capture the run ID and then `gh run watch <run_id>` to confirm the `pytest-parallel-isolation` job completes green; (b) the run log is attached to or quoted in the v1022 Phase CLOSE-GATE doc with the full job step output as evidence (`gh run view <run_id> --log --job=<job_id>` quoted block); (c) if the gate fails on first live run, the failure is fed back into PARA-01's spike or fix iteration (not silently ignored). **Note:** this requirement is unblocked only AFTER PARA-01 + PARA-02 + HYG-01 are merged — the gate verification is the LAST step before close.

### Close Gate

- [ ] **CLOSE-01**: Close gate for milestone v1022 — sequential pytest baseline preserved, `-n 4` baseline preserved, `-n auto` ≤30 distinct deterministic across 3 runs (PARA-01 acceptance criterion), CHANGELOG `[1.5.7]` entry written with per-requirement evidence, tags `v1022` (local) + `v1.5.7` (public) cut at the close-gate commit SHA. Acceptance criteria: (a) sequential pytest result quoted verbatim in CLOSE-GATE.md showing `3055 passed / 0 NEW failed / 38 skipped` (3 pre-existing OOS may remain — explicit table); (b) `-n 4` result quoted showing `3054 passed / 0 NEW failed / 38 skipped` (4 OOS — explicit table); (c) `-n auto` 3-run measurement table showing ≤30 distinct (failed+errors) per run with stale-DB cleanup between runs; (d) live docker stack health spot-check (`docker compose ps` 5 services healthy + `curl http://localhost:8080/api/health/` returns 200); (e) CHANGELOG `[1.5.7]` block lists PARA-01, PARA-02, HYG-01, CI-01 closures with the test pin names + line numbers; (f) CI-01's live-verify run-watch log embedded; (g) tags cut and recorded in `.planning/MILESTONES.md`.

---

## Future Requirements

Deferred to a later milestone. Catch-net for items that surface during v1022 execution.

_None at roadmap time. If PARA-01's spike surfaces an architectural issue larger than the per-worker DB lifecycle retry (e.g., a fundamental conflict between asyncio + asyncpg + xdist concurrency that warrants a phase of its own), promote that to a v1023+ item rather than blooming v1022 scope. Same precedent as v1021's INGEST-01 spike escalation language._

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Postgres `max_connections` bump | Restated from v1020 + v1021 Out of Scope. Production envelope at 30 is correct; the fix is engine-/lifecycle-layer retry, not headroom. |
| Artificial `-n` cap below `auto` (e.g., `-n 4` becomes the CI ceiling) | Restated from v1020 + v1021. Masks contention. CI default stays at `-n 4` per PERF-01, but `-n auto` must be diagnosable + closable. |
| Engine-level retry for application code (FastAPI request path) | Restated from v1021. Test-fixture engine only. Production engine has different acceptance criteria (request latency, not test determinism). |
| Pre-existing OOS failures (`test_layering` LOC-cap decomposition + `test_phase_275` README sync + `test_ssrf_redirect` flake) | Restated from v1021 OOS list. These are pre-existing OOS rows in the sequential/`-n 4` baselines; PARA-01's (b)/(c) acceptance criteria explicitly say "0 NEW failures" — these may continue failing. Closing them is its own (small) future hygiene milestone. |
| Production-code refactor beyond the conftest/test-fixture layer | v1022 is test-infra hygiene. Any production-code change discovered during the PARA-01 spike must be escalated to a separate requirement or deferred. |
| Documentation site changes (`~/Code/getgeolens.com`) | Sibling repo. v1022 may produce internal `.planning/` audit docs but no docs-site copy. |
| `make test` default change | v1020 PERF-01 already set `make test` → `-n 4` default with `make test-sequential` opt-in. v1022 does not change Makefile defaults. |
| New CI jobs beyond live-verifying the existing `pytest-parallel-isolation` gate | CI-01 is verification-only. Adding new CI jobs (e.g., `pytest -n auto` gate) is out of scope until `-n auto` is deterministic per PARA-01. |
| AGENTS.md or pre-commit hook changes | v1022 is fix + verify scope. Process-hardening changes (like v1019 TD-13's planner/executor skill updates) only land if PARA-01's spike surfaces a planner/executor drift pattern that needs codifying. |

---

## Traceability

Which phases cover which requirements. Updated by the roadmapper during ROADMAP.md creation. Executor flips `Pending` → `Complete` in the SAME commit as the SUMMARY.md write per v1019 TD-13 `requirements_traceability_flip` rule.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PARA-01 | TBD | Pending |
| PARA-02 | TBD | Pending |
| HYG-01 | TBD | Pending |
| CI-01 | TBD | Pending |
| CLOSE-01 | TBD | Pending |

**Coverage:**
- v1022 requirements: 5 total
- Mapped to phases: 0 (roadmapper to fill)
- Unmapped: 5 ⚠ (pre-roadmap state)

---
*Requirements defined: 2026-05-23*
*Last updated: 2026-05-23 after initial definition*
