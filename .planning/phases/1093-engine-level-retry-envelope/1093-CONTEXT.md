# Phase 1093: Engine-level Retry Envelope - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

A developer running `cd backend && uv run pytest -n auto tests/` on a canonical 16-core M-series host sees ≤10 failed tests across 3 consecutive runs (down from v1020's HYG-02 baseline of 48 deterministic + 173 non-deterministic = up to 221), while the `-n 4` CI default and sequential baseline stay green.

**One requirement (per REQUIREMENTS.md):**

- **TEST-01** — Land the engine-level retry envelope for `pytest -n auto` that v1020 deferred. Phase 1088-04 produced the architectural escalation REPORT (not auto-applied) at `.planning/milestones/v1020-phases/1088-fixture-isolation-fixes-regression-pins/1088-04-SUMMARY.md`: the 48 residual failures + 173 non-deterministic node-IDs in HYG-02's 16-worker flake hunt all fire AFTER `await session.commit()` releases the warm-up connection — outside any session-factory-level retry envelope. The fix lives at the engine layer (sqlalchemy `create_async_engine` pool configuration + a retry-on-`OperationalError` wrapper around `engine.connect()` / `engine.dispose()` calls that surface raw asyncpg `TooManyConnectionsError` / `CannotConnectNowError`).

**Acceptance criteria:**
- (a) `cd backend && uv run pytest -n auto tests/` produces ≤10 failed tests across 3 consecutive runs (down from v1020 baseline of up to 221).
- (b) `-n 4` sequential 3043 (current actual; ROADMAP cites 3047 but stale) baseline preserved — no regression on the operationally-default CI gate.
- (c) At least one regression pin in `backend/tests/test_fixture_isolation_v1020.py` (or new `test_engine_retry_envelope.py`) covers the engine-level retry shape under the same `TooManyConnectionsError` / `CannotConnectNowError` injection model that v1020 already uses for the fixture-layer pins.
- (d) PERF-01 default `-n 4` stays unchanged in `Makefile:29` and `.github/workflows/ci.yml:493-595` — the engine envelope is additive defense, NOT a replacement.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting.

### Locked from REQUIREMENTS.md
- **Scope: test-fixture engine ONLY.** App-engine retry (FastAPI request-path connection pool) is OUT OF SCOPE — different acceptance criteria (request latency vs test determinism).
- **Scope: engine-layer retry wrapper.** Wrap `engine.connect()` / `engine.dispose()` calls in `backend/tests/conftest.py` engine factory. Same `_TRANSIENT_CONTENTION_EXCEPTIONS` tuple v1020 introduced (`OperationalError, asyncpg.TooManyConnectionsError, asyncpg.CannotConnectNowError`).
- **PERF-01 default unchanged:** `-n 4` stays the CI default. `-n auto` becomes a developer-mode reliable option but not the CI gate.
- **Out of scope (carried from v1020 + REQUIREMENTS.md):** `max_connections` bump (production envelope at 30 is correct); artificial `-n` cap below `auto`; engine-level retry for app-code request path.

### v1020 Phase 1088-04 architectural notes (locked context)
The Phase 1088-04 REPORT specifies:
- Bottleneck is the WINDOW between `session.commit()` releasing the warm-up connection and the next operation acquiring a new one. During this window, 173 non-deterministic node-IDs fire `TooManyConnectionsError` because the post-commit acquire races with other workers.
- v1020's three retry helpers (`_create_test_db_with_retry`, `_run_with_too_many_clients_retry`, `_acquire_test_session_with_retry`) cover the fixture-layer paths. The residual 48 deterministic + 173 non-deterministic fires through `engine.connect()` / `bind.connect()` paths that the fixture-layer helpers don't wrap.
- The fix shape recommended in 1088-04: a `RetryingAsyncEngine` wrapper class (or equivalent) that intercepts `engine.connect()` and `engine.dispose()`, retries on `_TRANSIENT_CONTENTION_EXCEPTIONS` with the same `(1.0, 2.0, 4.0)` budget. OR an `event.listen(engine, "connect", retry_handler)` shim. OR a `NullPool`-style approach with retries baked into the pool's `_acquire()` method.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Known seed surfaces:
- `backend/tests/conftest.py` — engine factory `_make_test_async_engine` (around line 250-300). Currently uses `NullPool` per v1019 TD-10 fix. The three v1020 retry helpers (`_create_test_db_with_retry`, `_run_with_too_many_clients_retry`, `_acquire_test_session_with_retry`) live here.
- `backend/tests/test_fixture_isolation_v1020.py` — 11 v1020 regression pins. The new TEST-01 regression pin can land here (`test_engine_retry_*` shape) OR in a new `test_engine_retry_envelope.py`.
- `.planning/milestones/v1020-phases/1088-fixture-isolation-fixes-regression-pins/1088-04-SUMMARY.md` — the architectural REPORT that named this work. Read this first.
- `.planning/audits/PYTEST-XDIST-PERF-v1020.md` — perf baseline doc. `-n auto` = 442.75s, `-n 4` = 356.12s.
- `Makefile:29` — `test: uv run pytest -n 4 -v --tb=short`. STAYS unchanged.
- `.github/workflows/ci.yml:493-595` — `pytest-parallel-isolation` job runs `-n 4`. STAYS unchanged.

</code_context>

<specifics>
## Specific Ideas

**Verification approach (acceptance criterion (a)):**
After landing the engine-retry wrapper, run `cd backend && uv run pytest -n auto tests/` 3 times consecutively. Each run should produce ≤10 failed tests. Compare to v1020 HYG-02 baseline (6 deterministic + 173 non-deterministic across 3 runs).

**Regression pin shape (acceptance criterion (c)):**
- `test_engine_retry_succeeds_on_transient_too_many_clients` — pytest fixture that monkeypatches `asyncpg.connect` to raise `TooManyConnectionsError` once then succeed; assert engine wrapper retries and acquires successfully.
- `test_engine_retry_propagates_non_transient_operational_error` — assert non-transient `OperationalError` is NOT swallowed.
- `test_engine_retry_exhausts_budget_then_fails_loudly` — assert retries hit the `(1.0, 2.0, 4.0)` budget and propagate after exhausting.

Pin shape mirrors the existing v1020 fixture-layer pins in `test_fixture_isolation_v1020.py` for consistency.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. Phase 1093 closes the v1020 carry-forward; if `-n auto` still produces >10 failures after the engine wrapper, that's a SECOND architectural escalation (probably toward `max_connections` config dynamic-sizing) which falls outside v1021 scope.

</deferred>
