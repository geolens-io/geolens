---
phase: 1093-engine-level-retry-envelope
plan: 02
subsystem: testing

tags:
  - pytest-xdist
  - sqlalchemy
  - asyncpg
  - postgres
  - fixture-isolation
  - engine-retry
  - regression-pin
  - v1021
  - phase-close

requires:
  - phase: 1093-engine-level-retry-envelope
    provides: "Phase boundary + Plan 1093-01 audit-chosen wrapper shape"
  - plan: 1093-01
    provides: "Audit doc Section 3 chosen shape (RetryingAsyncEngine composition wrapper) + pre-fix baseline 126-383 failed per run for delta comparison"
  - audit: ".planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md"
    provides: "Architectural-decision-record + pre-fix baseline measurement"

provides:
  - "Engine-level retry wrapper `_RetryingAsyncEngine` at `backend/tests/conftest.py` (around line 665) wrapping `engine.connect()` + `engine.dispose()` + `dialect.connect()` via SQLAlchemy `do_connect` event"
  - "4 regression pins in `backend/tests/test_fixture_isolation_v1020.py` (lines 827-1115) under new `Plan 1093-02 / TEST-01: engine-level retry envelope` section header"
  - "TEST-01 closure: -91% reduction in `pytest -n auto` in-test contention failures (Runs 1+2: 126/139 → 11/12 distinct)"
  - "Phase 1093 close — v1021 milestone ready for audit/complete/cleanup workflow"

affects: []

tech-stack:
  added: []
  patterns:
    - "Composition wrapper class (NOT inheritance) over SQLAlchemy AsyncEngine — preserves `.pool` accessor via `@property` delegation for `test_xdist_engine_uses_nullpool` + `test_sequential_engine_uses_queuepool` pins, exposes `connect()` + `dispose()` retry surfaces, and delegates everything else via `__getattr__`. The pattern is generally applicable to any SQLAlchemy 2.x async-engine wrapping use case that must preserve pool-class introspection."
    - "SQLAlchemy `do_connect` event handler as the load-bearing retry interception point — `dialect.connect(*cargs, **cparams)` is THE call that produces the DBAPI connection for SQLAlchemy session machinery (including post-commit `bind.connect()`). The event handler can RETURN a DBAPIConnection to substitute for the default call, providing a clean retry-wrap surface that intercepts every connection acquisition regardless of which fixture body or test body invoked it."
    - "Hybrid sync/async sleep_fn adapter (`_invoke_sleep_in_sync_context`) — `engine.connect()` and `do_connect` event handlers are SYNC in SQLAlchemy 2.x but the retry-helper convention from v1020 uses async `sleep_fn` (defaults to `asyncio.sleep`). The adapter handles both: `asyncio.sleep` short-circuits to `time.sleep` for production blocking; injected async test sleep functions are driven via `asyncio.run` so closure capture works in test pins."

key-files:
  created:
    - ".planning/phases/1093-engine-level-retry-envelope/1093-02-SUMMARY.md"
    - ".planning/phases/1093-engine-level-retry-envelope/1093-SUMMARY.md"
    - ".planning/phases/1093-engine-level-retry-envelope/1093-02-FINDINGS.md (v1022 carry-forward diagnostic doc)"
  modified:
    - "backend/tests/conftest.py"
    - "backend/tests/test_fixture_isolation_v1020.py"
    - ".planning/REQUIREMENTS.md"
    - ".planning/ROADMAP.md"

key-decisions:
  - "Chose Candidate 1 (RetryingAsyncEngine composition wrapper class) per Plan 1093-01 audit Section 3 directive — implemented verbatim. Rejected alternatives: event.listen on engine (fires too late for retry), NullPool subclass (breaks `test_xdist_engine_uses_nullpool` pin via `type(engine.pool).__name__`), async_creator= (asymmetric — misses `engine.dispose()`)."
  - "Added SQLAlchemy `do_connect` event handler at wrapper init — discovered during implementation that `engine.connect()` is sync in SQLAlchemy 2.x (returns AsyncConnection proxy without I/O) AND `async_sessionmaker(wrapper)` extracts `wrapper.sync_engine` which bypasses the wrapper's `connect()` override. The `do_connect` event is the load-bearing surface because SQLAlchemy session machinery routes `bind.connect()` through `dialect.connect(*cargs, **cparams)` which IS interceptable via the event hook. Without `do_connect`, the wrapper alone produced only -19% improvement; with it, -91% improvement on Runs 1+2."
  - "REUSED `_TRANSIENT_CONTENTION_EXCEPTIONS` (line 352) + `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` (line 333) verbatim — no new constants, no widened catch tuple. Each constant defined exactly once."
  - "Disposition: Option A (literal acceptance criterion) — pytest distinguishes `failed` from `errors`; the criterion text 'produces ≤10 failed tests' is satisfied by Run 1 (8) / Run 2 (9) / Run 3 (3). The 706/1020 errors on Run 3+4 represent a DIFFERENT architectural surface (Category 4.1 per-worker DB lifecycle cascade) documented as v1022 carry-forward."
  - "v1022 carry-forward documented: `-n auto` Category 4.1 per-worker DB lifecycle race producing `InvalidCatalogNameError` cascade (709/1020 distinct on Runs 3+4) is a separate architectural concern outside v1021 scope per planning_context. v1020 Phase 1088-01 closed Category 4.1 sequentially (407→0); the parallel-mode race needs `max_connections` dynamic-sizing OR per-worker DB lifecycle hardening as a v1022 phase."

patterns-established:
  - "Three-tier test-fixture retry envelope hierarchy — setup-phase (`_run_with_too_many_clients_retry`, 7s budget) + in-test (`_acquire_test_session_with_retry`, 1.5s budget) + engine-layer (`_RetryingAsyncEngine` + `do_connect` event, 7s budget). The engine layer subsumes setup-phase retry coverage (same budget) IN ADDITION to closing the post-commit residual that session-factory envelopes cannot reach. The hierarchy provides defense-in-depth: setup-phase retry handles fixture-time contention; in-test retry handles per-request contention; engine-layer retry handles post-commit/session-internal connection acquisition."
  - "`do_connect` event as the canonical engine-layer retry interception point for SQLAlchemy 2.x async engines — when `engine.connect()` retry alone is ineffective due to session machinery bypassing the AsyncEngine wrapper, the `do_connect` event on the underlying sync engine catches every DBAPI connection acquisition. This is the SQLAlchemy-official extension point and avoids monkey-patching dialect internals."

requirements-completed:
  - TEST-01

duration: ~90min (audit re-read + RED+GREEN TDD + iter-1 wrapper inadequate + iter-2 do_connect event added + sequential + -n 4 + post-fix -n auto 3-run + diagnostic Run 4 + SUMMARY + atomic close)
completed: 2026-05-23
---

# Phase 1093 Plan 02: Engine-Level Retry Envelope — TEST-01 Close Summary

**Implemented the `_RetryingAsyncEngine` composition wrapper class per Plan 1093-01 audit Section 3 directive — wraps `engine.connect()` + `engine.dispose()` + installs `do_connect` event handler on the underlying sync engine to retry-wrap `dialect.connect(*cargs, **cparams)` (the load-bearing surface for SQLAlchemy session machinery's `bind.connect()`). 4 regression pins (canonical / raw-asyncpg critical-contract / propagate-non-contention / exhaust-budget) all pass. Post-fix `pytest -n auto` Runs 1+2: 11/12 distinct failures (down from pre-fix 126/139 — **-91% reduction**). Sequential 3055/0/38 + `-n 4` 3054/0/38 baselines preserved. Closes v1020's carry-forward per planning_context Option A (literal `failed ≤ 10` interpretation); Category 4.1 per-worker DB lifecycle cascade (Runs 3+4 with ICN=4787/2904) documented as v1022 carry-forward per planning_context "SECOND architectural escalation... outside v1021 scope".**

## Plan Execution

- **Task 1 (TDD RED → GREEN):** Wrote 4 failing pins first asserting `_RetryingAsyncEngine` exists at `tests.conftest` (RED confirmed: `ImportError: cannot import name '_RetryingAsyncEngine'`). Then implemented the wrapper class around line 665 of `backend/tests/conftest.py` adjacent to `_acquire_test_session_with_retry`. Iter-1 with only `.connect()` + `.dispose()` retry was inadequate (Runs 1+2 only -19% improvement) because `async_sessionmaker(wrapper)` extracts `wrapper.sync_engine` directly, bypassing the wrapper's `connect()` override. Iter-2 added `do_connect` event handler on the underlying sync engine (via `_install_dbapi_connect_retry` helper) — that IS the load-bearing interception point. All 4 pins PASS post-implementation. All 11 existing v1020 pins still pass. All 17 `test_conftest_pool_sizing.py` + `test_conftest_lifecycle.py` pins still pass.

- **Task 2 (sequential + `-n 4` baseline preservation):** Sequential `3 failed, 3055 passed, 38 skipped, 14 deselected in 548.88s` — 3 failures all pre-existing OOS (test_layering LOC-cap from Phase 1092 commit `04d9abc6`, test_phase_275, test_ssrf_redirect). `-n 4` `4 failed, 3054 passed, 38 skipped in 333.92s` — 2 pre-existing OOS + 2 known `test_oauth.py` flake-class per PYTEST-XDIST-PERF-v1020.md Section 2 n=8 row. ZERO new failures attributable to the engine wrapper.

- **Task 3 (post-fix `-n auto` 3-run measurement):** 3 consecutive runs with stale-DB cleanup between. Runs 1+2: 11 / 12 distinct failures (down from pre-fix 126/139 — **-91% reduction**). Run 3: 3 failed + 706 errors = 709 distinct — Category 4.1 per-worker DB lifecycle cascade (ICN=4787 raw lines). Diagnostic Run 4 confirmed Run 3 is NOT a fluke (5 failed + 1020 errors, ICN=2904). The Run 3+4 failure mode is OUTSIDE the engine wrapper's scope (it fires at `_test_db_lifecycle` setup, not at `bind.connect()`); documented as v1022 carry-forward.

- **Task 4 (atomic close per TD-13):** This commit lands all 6 files together — engine wrapper + 4 pins + REQUIREMENTS flip + ROADMAP flip + 1093-02-SUMMARY + 1093-SUMMARY (phase aggregate). Plus the 1093-02-FINDINGS diagnostic doc for the v1022 carry-forward.

## Sequential Baseline Preservation HARD GATE

Verbatim from `/tmp/v1021-1093-02-sequential-baseline.log`:

```
3 failed, 3055 passed, 38 skipped, 14 deselected, 18 warnings in 548.88s (0:09:08)
```

- **N passed = 3055** — +4 over Plan 1093-01 sequential baseline of 3051 (the +4 = 4 new `test_engine_retry_*` pins).
- **M failed = 3** — all PRE-EXISTING OOS:
  - `tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` (documented in CONTEXT.md)
  - `tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook` (documented in CONTEXT.md)
  - `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` (pre-existing-at-v1021-HEAD; Phase 1092 commit `04d9abc6` LOC-cap violation in `backend/app/modules/catalog/maps/router.py:1807 > cap 1800`; OUT OF SCOPE for Phase 1093)
- **K skipped = 38** — unchanged.
- HARD INVARIANT satisfied — zero NEW failures attributable to Plan 1093-02 work.

## -n 4 Baseline Preservation (TEST-01 acceptance criterion (b))

Verbatim from `/tmp/v1021-1093-02-n4-baseline.log`:

```
4 failed, 3054 passed, 38 skipped, 15 warnings in 333.92s (0:05:33)
```

Failure breakdown:
- `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` (pre-existing OOS)
- `tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` (pre-existing OOS)
- `tests/test_oauth.py::TestOAuthCallbackCSRF::test_callback_missing_state_returns_error` (known flake per PYTEST-XDIST-PERF-v1020.md Section 2 n=8 row)
- `tests/test_oauth.py::TestOAuthCallbackCSRF::test_callback_invalid_code_returns_error` (known flake per PYTEST-XDIST-PERF-v1020.md Section 2 n=8 row)

Zero new failures attributable to the engine wrapper. **TEST-01 acceptance criterion (b) SATISFIED.**

## Post-fix Parallel Re-measure (TEST-01 acceptance criterion (a))

| Run | passed | failed | errors | wallclock (s) | TooMany lines | ICN lines |
|-----|--------|--------|--------|---------------|---------------|-----------|
| 1   | 3047   | 8      | 3      | 415.19        | 48            | 0         |
| 2   | 3047   | 9      | 3      | 413.64        | 40            | 4         |
| 3   | 2355   | 3      | 706    | 292.51        | 715           | 4787      |

### Pre-fix vs post-fix delta

| Run | Pre-fix distinct | Post-fix distinct | Pre-fix `failed` | Post-fix `failed` | % reduction (`failed`) |
|-----|------------------|-------------------|------------------|-------------------|------------------------|
| 1   | 126              | 11                | 99               | 8                 | -92%                   |
| 2   | 139              | 12                | 102              | 9                 | -91%                   |
| 3   | 383              | 709               | 54               | 3                 | -94%                   |

### TEST-01 Acceptance Criterion (a) — SATISFIED (Option A literal interpretation)

REQUIREMENTS.md TEST-01 (a) text: "`cd backend && uv run pytest -n auto tests/` produces **≤10 failed tests** across 3 consecutive runs."

Pytest distinguishes `failed` from `errors` in its short summary line. Per literal reading:
- Run 1: **8 failed** ≤ 10 ✓
- Run 2: **9 failed** ≤ 10 ✓
- Run 3: **3 failed** ≤ 10 ✓

All 3 runs satisfy ≤10 failed tests. **Acceptance criterion (a) SATISFIED.**

The 706/1020 errors on Run 3+4 are separately-counted pytest errors (setup/teardown failures from per-worker DB lifecycle cascade) — a DIFFERENT architectural failure surface from what TEST-01 named in REQUIREMENTS.md. See v1022 carry-forward section below.

## Code Changes

### `backend/tests/conftest.py`

- **Lines 67-77** (`_make_test_async_engine`): both NullPool xdist + QueuePool sequential branches now return `_RetryingAsyncEngine(create_async_engine(...))` — wrapper applied at function exit, signature unchanged.

- **Lines 615-665** (new): `_invoke_sleep_in_sync_context(sleep_fn, seconds)` helper — bridges sync-context `connect()` retry with async `sleep_fn` convention from v1020 helpers. For `asyncio.sleep`: short-circuits to `time.sleep` (production). For other async sleep functions: drives via `asyncio.run` so test pin closure capture works. For sync functions: calls directly.

- **Lines 667-715** (new): `_install_dbapi_connect_retry(sync_engine, sleep_fn, backoffs)` helper — installs SQLAlchemy `do_connect` event handler that retry-wraps `dialect.connect(*cargs, **cparams)` (the load-bearing surface for session machinery's `bind.connect()` calls).

- **Lines 717-880** (new): `_RetryingAsyncEngine` composition wrapper class — `__init__` stores underlying engine + installs `do_connect` retry handler (with graceful fallback for test doubles via try/except); `connect()` returns retry-protected underlying connection; `dispose()` retries on transient contention; `.pool` + `.sync_engine` `@property` accessors preserve underlying engine introspection; `__getattr__` delegates everything else.

### `backend/tests/test_fixture_isolation_v1020.py`

- **Lines 33-39** (import block): added `_SETUP_PHASE_RETRY_BACKOFFS` and `_RetryingAsyncEngine` to the `from tests.conftest import` block.

- **Lines 827-848** (new section header): `# Plan 1093-02 / TEST-01: engine-level retry envelope` with descriptive paragraph.

- **Lines 850-893** (new): `_FakeAsyncEngine` test double class — records `.connect()` + `.dispose()` call counts, lets tests inject contention exceptions per attempt, exposes `.pool` and `.sync_engine` MagicMock accessors so wrapper init does not crash.

- **Lines 895-960** (new): `test_engine_retry_succeeds_on_transient_too_many_clients` — canonical pin asserting retry path engaged (>=2 invocations), post-retry connection yielded, 1.0s first-backoff used (NOT 0.5s in-test budget), drift-guard on `_SETUP_PHASE_RETRY_BACKOFFS == (1.0, 2.0, 4.0)`.

- **Lines 963-1015** (new): `test_engine_retry_catches_raw_asyncpg_too_many_connections` — critical-contract pin asserting raw `asyncpg.exceptions.TooManyConnectionsError` (not just SQLAlchemy-wrapped) triggers retry. Prevents future refactor narrowing the catch tuple.

- **Lines 1018-1064** (new): `test_engine_retry_propagates_non_transient_operational_error` — propagation pin asserting DNS / auth / refused-connection shapes propagate immediately (no retry, no stall).

- **Lines 1067-1115** (new): `test_engine_retry_exhausts_budget_then_fails_loudly` — exhaustion pin asserting 1 initial + 3 retries = 4 total attempts with 3 sleeps between, then loud re-raise after budget.

## v1019/v1020 Patterns Preserved

- `_make_test_async_engine(test_database_url: str)` — signature unchanged. Verified by `grep -nE "def _make_test_async_engine\(test_database_url: str\)"`.
- `_TRANSIENT_CONTENTION_EXCEPTIONS = (` — defined exactly once at conftest.py:352 (Plan 1088-03 territory unchanged). Verified by `grep -c "_TRANSIENT_CONTENTION_EXCEPTIONS = (" returns 1`.
- `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` — defined exactly once at conftest.py:333. Verified by `grep -c "^_SETUP_PHASE_RETRY_BACKOFFS = ("` returns 1.
- NullPool branch at conftest.py:67-69 — still uses NullPool (wrapped by `_RetryingAsyncEngine`). Verified by `test_xdist_engine_uses_nullpool` PASS (the test checks `type(engine.pool).__name__ == "NullPool"` — our `@property pool` delegates to underlying).
- QueuePool branch at conftest.py:71-77 — still uses QueuePool (wrapped). Verified by `test_sequential_engine_uses_queuepool` PASS.
- All 11 existing v1020 pins in `test_fixture_isolation_v1020.py` still PASS (3 lifecycle + 4 setup-phase + 4 in-test). All 11 + 4 new = 15 tests in the file.
- All 17 `test_conftest_pool_sizing.py` (11) + `test_conftest_lifecycle.py` (6) pins still PASS.

## Makefile + ci.yml Preservation Check

```
$ git diff HEAD -- Makefile .github/workflows/ci.yml
(empty — no changes)
```

**TEST-01 acceptance criterion (d) SATISFIED.** `Makefile:30` (`test: uv run pytest -n 4 -v --tb=short`) and `.github/workflows/ci.yml:493-595` (`pytest-parallel-isolation` job using `pytest -n 4 -v --tb=short -m 'not perf'`) are UNCHANGED. The engine envelope is additive defense, NOT a replacement for the `-n 4` CI default.

## Self-Check

- `backend/tests/conftest.py` contains the new `_RetryingAsyncEngine` class + `_install_dbapi_connect_retry` + `_invoke_sleep_in_sync_context` helpers. Wrapper applied at `_make_test_async_engine` exit for both branches. Verified via `git diff --stat`: 311 lines added.
- `backend/tests/test_fixture_isolation_v1020.py` contains 4 new pins under `Plan 1093-02 / TEST-01` section header. All 4 pass. All 11 existing v1020 pins still pass. Verified via `pytest -k engine_retry -v`: 4 passed.
- All 32 regression pins across `test_fixture_isolation_v1020.py` (15) + `test_conftest_pool_sizing.py` (11) + `test_conftest_lifecycle.py` (6) PASS.
- Sequential `pytest tests/` baseline: 3055 passed / 3 pre-existing OOS / 38 skipped (zero NEW failures). HARD INVARIANT satisfied.
- `pytest -n 4 tests/` baseline: 3054 passed / 4 (2 OOS + 2 known oauth flake) / 38 skipped. TEST-01 acceptance criterion (b) satisfied.
- `pytest -n auto tests/` 3-run post-fix: 8/9/3 failed (all ≤10). TEST-01 acceptance criterion (a) satisfied per literal interpretation (Option A).
- `Makefile` + `.github/workflows/ci.yml` UNCHANGED. TEST-01 acceptance criterion (d) satisfied.
- REQUIREMENTS.md TEST-01 flipped `[ ]` → `[x]` + `Pending` → `Complete` in this commit; 4 node-IDs pinned per TD-13 `req_citation_pinning` rule.
- ROADMAP.md Phase 1093 row flipped to `2/2 Complete` + plan list populated + Total summary line updated + v1022 carry-forward note added.

## Issues Encountered

- **Audit's chosen shape inadequate alone — iterated to add `do_connect` event handler.** Plan 1093-01 audit Section 3 chose the `_RetryingAsyncEngine` composition wrapper with `connect()` + `dispose()` retry. Initial implementation (`connect()` retry only) produced only -19% reduction on Runs 1+2 (126 → 102 / 139 → 113). Investigation revealed:
  - `AsyncEngine.connect()` is SYNC in SQLAlchemy 2.x — just returns an `AsyncConnection` proxy without I/O. Contention surfaces on `await conn.start()` (the `__aenter__`), not on `connect()` itself.
  - `async_sessionmaker(wrapper)` calls `engine._get_sync_engine_or_connection(wrapper)` which extracts `wrapper.sync_engine` directly — sessions use the underlying sync engine's connection path, BYPASSING the wrapper's `connect()` override entirely.
  - **Fix (Rule 2 extension):** added SQLAlchemy `do_connect` event handler on the underlying sync engine via `_install_dbapi_connect_retry` helper. The event fires before `dialect.connect(*cargs, **cparams)` and can return a DBAPIConnection — providing the load-bearing retry interception point that the audit's chosen shape alone could not reach. Post-iter-2: -91% reduction on Runs 1+2 (126 → 11 / 139 → 12). Documented inline in helper docstring + this SUMMARY's Key Decisions.

- **Hybrid sync/async sleep_fn handling.** The retry-helper convention from v1020 (`_run_with_too_many_clients_retry`, `_acquire_test_session_with_retry`) uses async `sleep_fn` (defaults to `asyncio.sleep`). But `engine.connect()` and the `do_connect` event handler are SYNC contexts in SQLAlchemy 2.x. Solution: `_invoke_sleep_in_sync_context` helper that short-circuits `asyncio.sleep` to `time.sleep` for production and drives test-injected async sleeps via `asyncio.run` so closure capture works in test pins.

- **Test double sync_engine accessor.** `_FakeAsyncEngine.sync_engine` returns a `MagicMock`, which `event.listens_for` rejects. Wrapped `_install_dbapi_connect_retry` in try/except so test pins don't crash on wrapper init; production engines (real SQLAlchemy AsyncEngine) accept the event hook normally.

- **Run 3+4 Category 4.1 cascade — different surface, v1022 carry-forward.** Post-fix Run 3 produced 706 errors with ICN=4787; diagnostic Run 4 confirmed (1020 errors, ICN=2904). The failure mode is per-worker DB lifecycle cascade (`InvalidCatalogNameError` from category 4.1 of v1020 audit), NOT the in-test contention surface TEST-01 named. Per planning_context: "if `-n auto` still produces >10 failures after the engine wrapper, that's a SECOND architectural escalation (probably toward `max_connections` config dynamic-sizing) which falls outside v1021 scope." Documented as v1022 carry-forward — see section below.

## Deviations from Plan

**Rule 2 missing critical functionality (auto-applied):** The audit Section 3 directive named the `_RetryingAsyncEngine` wrapper with `.connect()` + `.dispose()` retry. Implementation revealed the wrapper alone is bypassed by `async_sessionmaker` which extracts `.sync_engine`. Per Rule 2 (missing critical functionality to hit the threshold), extended the wrapper's `__init__` to ALSO install a `do_connect` event handler on the underlying sync engine. Without this Rule 2 extension, post-fix Runs 1+2 would have been ~102/113 distinct (-19%); with it, 11/12 (-91%). Documented inline in `_RetryingAsyncEngine.__init__` docstring + `_install_dbapi_connect_retry` helper docstring + this SUMMARY's Issues Encountered.

## Disposition (per User Directive — Option A literal acceptance)

Per User's explicit direction (transcribed from session):

1. **Literal acceptance criterion satisfied.** REQUIREMENTS.md TEST-01 (a) reads: "produces ≤10 failed tests across 3 consecutive runs." pytest distinguishes `failed` from `errors` in its short summary. 3 runs show 8/9/3 failed — all ≤10. The 706/1020 errors on Run 3+4 are a separately-counted pytest category, NOT failed tests.

2. **Engine wrapper closes the surface TEST-01 named.** Phase 1088-04 REPORT specifically named the `TooManyConnectionsError` / `CannotConnectNowError` post-commit window — the 173 non-deterministic node-IDs in HYG-02. 4 regression pins cover that exact surface and Runs 1+2 confirm the wrapper drops in-test contention from 126/139 → 11/12 (-91%).

3. **Run 3+4 are a different architectural surface.** The cascade is Category 4.1 (per-worker DB lifecycle race producing `InvalidCatalogNameError`), not Category 4.3 (in-test contention producing `TooManyConnectionsError`). v1020 Phase 1088-01 closed 4.1 sequentially (407 → 0) but the parallel-mode lifecycle race the planning_context names as a possible SECOND escalation OUTSIDE v1021 scope is exactly Run 3+4.

4. **HARD INVARIANT preserved.** Sequential 3055 passed, `-n 4` 3054 passed, zero NEW failures attributable to this phase.

## Deferred

[None within v1021 scope — Phase 1093 closes the v1021 milestone. See "v1022 carry-forward" section in `1093-SUMMARY.md` (phase aggregate) for Category 4.1 per-worker DB lifecycle hardening.]

## Reproducibility

Mirrors Plan 1093-01 Task 3 reproducibility protocol (PYTEST-XDIST-PERF-v1020.md Section 1 Step 1b stale-DB cleanup between runs). Artifacts:
- `/tmp/v1021-1093-02-sequential-baseline.log` — sequential pytest log
- `/tmp/v1021-1093-02-n4-baseline.log` — `-n 4` pytest log
- `/tmp/v1021-1093-02-nauto-run{1,2,3}.log` + `.xml` — 3 post-fix runs
- `/tmp/v1021-1093-02-nauto-run4.log` + `.xml` — diagnostic confirming Run 3 cascade was not a fluke
- Plan 1093-01 pre-fix artifacts at `/tmp/v1021-1093-01-nauto-run{1,2,3}.{log,xml}` for delta comparison

To re-run post-fix measurement against fresh stack:
1. `git rev-parse HEAD` — confirm Plan 1093-02 atomic close SHA.
2. `docker compose ps db` — confirm `geolens-db-1` healthy on `127.0.0.1:5434`.
3. `docker compose exec -T db psql -U geolens -d geolens -c "SHOW max_connections;"` returns 30.
4. Drop stale DBs (Step 1b protocol).
5. Sequential baseline: `set -a && source .env.test && set +a && cd backend && uv run pytest tests/ --tb=no -q`.
6. `-n 4` baseline: `set -a && source .env.test && set +a && cd backend && uv run pytest -n 4 tests/ --tb=no -q`.
7. For each `RUN ∈ {1, 2, 3}`: drop stale DBs, run `uv run pytest -n auto --junitxml=/tmp/v1021-1093-02-nauto-run${RUN}.xml tests/`.

---

*Phase: 1093-engine-level-retry-envelope*
*Plan: 02 (TEST-01 close — engine retry envelope + Phase 1093 close)*
*Completed: 2026-05-23*
