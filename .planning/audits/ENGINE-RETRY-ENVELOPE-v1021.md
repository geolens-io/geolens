---
captured: 2026-05-23
milestone: v1021
phase: 1093-engine-level-retry-envelope
plan: 01
requirement: TEST-01
host: macOS darwin/arm64 (Apple M-series, 16-core)
worker_count_under_n_auto: 16
postgres_max_connections: 30
head_sha: 46f45c1bef8d9f5d5494b1eebddbe56537bdba98
sequential_passed_count: 3051
sequential_failed_count: 3
sequential_skipped_count: 38
sequential_deselected_count: 14
sequential_wallclock_seconds: 550.02
sequential_oos_failures:
  - "tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact (pre-existing OOS, documented)"
  - "tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook (pre-existing OOS, documented)"
  - "tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap (pre-existing-at-v1021-HEAD; introduced by Phase 1092 commit 04d9abc6 LOC-cap violation in backend/app/modules/catalog/maps/router.py:1807 > cap 1800; OUT OF SCOPE for Phase 1093 engine-retry work)"
nauto_run_1_passed: 2930
nauto_run_1_failed: 99
nauto_run_1_errors: 27
nauto_run_1_skipped: 38
nauto_run_1_wallclock_seconds: 402.44
nauto_run_1_raw_cascade_lines: 509
nauto_run_1_invalid_catalog_name_lines: 4
nauto_run_1_junit_failures: 99
nauto_run_1_junit_errors: 27
nauto_run_1_distinct_failures: 126
nauto_run_2_passed: 2919
nauto_run_2_failed: 102
nauto_run_2_errors: 37
nauto_run_2_skipped: 38
nauto_run_2_wallclock_seconds: 398.34
nauto_run_2_raw_cascade_lines: 585
nauto_run_2_invalid_catalog_name_lines: 0
nauto_run_2_junit_failures: 102
nauto_run_2_junit_errors: 37
nauto_run_2_distinct_failures: 139
nauto_run_3_passed: 2687
nauto_run_3_failed: 54
nauto_run_3_errors: 329
nauto_run_3_skipped: 27
nauto_run_3_wallclock_seconds: 307.29
nauto_run_3_raw_cascade_lines: 271
nauto_run_3_invalid_catalog_name_lines: 616
nauto_run_3_junit_failures: 54
nauto_run_3_junit_errors: 329
nauto_run_3_distinct_failures: 383
chosen_shape: RetryingAsyncEngine wrapper class (composition over inheritance)
chosen_shape_target_file: backend/tests/conftest.py
chosen_shape_target_line_range: "around line 605 (adjacent to _acquire_test_session_with_retry) + applied at function exit of _make_test_async_engine (line 67-77)"
---

# Engine-Level Retry Envelope — Plan 1093-01 Audit (v1021 TEST-01)

This is the architectural-decision-record + pre-fix-baseline-measurement
deliverable for Phase 1093 Plan 1093-01 (TEST-01 spike). It consolidates Plan
1088-04's architectural escalation REPORT into a single planning-grade audit,
chooses ONE engine-retry wrapper shape, and measures the v1021-HEAD baseline
against which Plan 1093-02's post-fix delta is judged.

The audit was produced spike-first per v1019 Phase 1085 / v1020 Phase 1087
precedent — no code changes land in Plan 1093-01. The chosen shape (Section 3)
is implemented verbatim by Plan 1093-02.

**Key references (cross-reference targets):**
- Architectural REPORT: `.planning/milestones/v1020-phases/1088-fixture-isolation-fixes-regression-pins/1088-04-SUMMARY.md` (iter-3 residual analysis)
- Perf methodology mirror: `.planning/audits/PYTEST-XDIST-PERF-v1020.md` (Section 1 sampling protocol + Step 1b stale-DB cleanup)
- Existing test-fixture engine factory: `backend/tests/conftest.py:54-77` (`_make_test_async_engine`)
- Reused exception tuple: `backend/tests/conftest.py:343-347` (`_TRANSIENT_CONTENTION_EXCEPTIONS`)
- Reused backoff budget: `backend/tests/conftest.py:324` (`_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)`)
- Call site that returns the engine: `backend/tests/conftest.py:876`
- Dispose call site (second protected surface): `backend/tests/conftest.py:959`
- Locked-down pool-sizing pins: `backend/tests/test_conftest_pool_sizing.py:245` (`test_xdist_engine_uses_nullpool`) + `:271` (`test_sequential_engine_uses_queuepool`)

---

## Section 1 — Post-Commit Failure Surface (from Plan 1088-04 iter-3 residual analysis)

Plan 1088-04 reduced audit category 4.3 (in-test connection contention) from
137 → 48 across three iterations (iter-1 bare-`__aenter__` retry: 137 → 135;
iter-2 added warm-up `SELECT 1` inside the retry envelope of `override_get_db`:
137 → 66; iter-3 Rule-2 extension to `test_db_session`: 66 → 48). The 48
residual stayed **above** the 30 threshold from the audit `<decisions>` exit
criterion. Plan 1088-04 explicitly DID NOT auto-apply a further fix — Rule 4
(architectural decision) reserved the disposition for Plan 1088-N. That
escalation REPORT lives at `1088-04-SUMMARY.md` and named this work as the
v1021 carry-forward closure.

### Verbatim cross-reference from 1088-04-SUMMARY

From `1088-04-SUMMARY.md` "iter-3 residual analysis":

> All 48 residual 4.3 failures route through `bind.connect()` calls that fire
> AFTER `await session.commit()` releases the warm-up's connection. The
> session's warm-up connection is released on commit; subsequent operations
> acquire a fresh asyncpg connection that can race the ceiling again. A
> session-factory-level retry helper CANNOT protect post-commit query
> connection acquisitions because they happen inside test code, not inside the
> fixture envelope. Closing this residual requires either (a) engine-level
> connection retry via custom `creator` or pool subclass, or (b) accepting
> under HYG-02 flake hunt.

From `1088-04-SUMMARY.md` "Deviations from Plan / Rule 4 architectural
decision NOT taken (REPORTED for Plan 1088-N)":

> Iter-3 measurement showed 48 residual 4.3 failures fire on `bind.connect()`
> calls AFTER `await session.commit()` — OUTSIDE any session-factory-level
> retry envelope. Closing this residual would require:
>
> - (a) Engine-level connection-retry via custom `async_creator=` or pool
>   subclass — invasive change to `_make_test_async_engine`, would alter the
>   v1019 NullPool pattern's surface behavior.
> - (b) Accept under Phase 1090 HYG-02 flake hunt — consistent with audit
>   Section 5 language ("if the residual count after fixes is <30, treat as
>   acceptable flake under HYG-02").

v1020 close-state chose option (b) for the immediate close-gate (the cascade
flake-class residual was accepted under HYG-02). v1021 TEST-01 closes the
deferred option (a): the engine-level wrapper.

### Non-deterministic surface (v1020 HYG-02 flake hunt observation)

In addition to the 48 deterministic post-commit failures, HYG-02's 16-worker
flake hunt observed **+173 non-deterministic** node-IDs firing the same
post-commit `bind.connect()` shape across 3 consecutive `pytest -n auto` runs.
The combined upper-bound (48 deterministic + 173 non-deterministic = up to 221
failures across 3 runs) is the v1020 HYG-02 baseline that REQUIREMENTS.md
TEST-01 acceptance criterion (a) cites.

### Two surfaces the wrapper MUST intercept (CONTEXT.md `<domain>` line 14)

Per CONTEXT.md `<domain>` line 14, the wrapper must protect BOTH:

1. **`engine.connect()`** — the dominant surface. Every test-body
   `session.execute()` / `session.refresh()` after a `session.commit()`
   acquires a fresh asyncpg connection via this path (under NullPool, sessions
   do not hold persistent connections, so commit-release-then-acquire is the
   default lifecycle, not the exception).

2. **`engine.dispose()`** — fires at `client` fixture teardown
   (`conftest.py:959`). While `dispose()` does not acquire a NEW connection
   (it releases existing ones), it can still surface transient errors during
   the asyncpg cleanup path if a worker is racing against the connection
   ceiling at the moment of dispose. Lower-frequency than `connect()` but
   non-zero, and the wrapper should be symmetric.

### Why session-factory retries cannot wrap these

The existing `_acquire_test_session_with_retry` helper at
`backend/tests/conftest.py:474-605` issues a warm-up `SELECT 1` INSIDE the
retry envelope, which forces eager asyncpg connection acquisition. This works
for the **first** connection per session, because the warm-up fires before
the session is yielded to the caller. But once the test body issues
`await session.commit()`, the asyncpg connection is RELEASED back to the pool
(NullPool actually closes it). Any subsequent `session.execute(...)` or
`session.refresh(...)` triggers a fresh `bind.connect()` call — and that call
is OUTSIDE the session-factory's retry envelope. The fixture-level helper
yielded control back to the test body 100ms ago; by the time the contention
fires, the test body owns the call stack, and the helper cannot retroactively
wrap a call it never owned.

The engine-level wrapper closes this gap by intercepting at the LOWEST layer
— wrapping the `engine.connect()` / `engine.dispose()` calls themselves. Every
connection acquisition through the engine, regardless of which fixture body or
test body invoked it, flows through the wrapper and gets retry-on-contention
protection.

---

## Section 2 — Candidate Fix Shapes

Four candidates, each evaluated against the same criteria:

- (a) Does it intercept BOTH `engine.connect()` AND `engine.dispose()` per
  CONTEXT.md?
- (b) Does it preserve the NullPool (xdist) branch AT line 67-69 AND the
  QueuePool (sequential) branch AT line 70-77?
- (c) Does it preserve the existing 17/17 `test_conftest_pool_sizing.py` +
  `test_conftest_lifecycle.py` regression pins? (CRITICAL: those tests do
  `type(engine.pool).__name__` at lines 260+281 — the wrapper MUST expose
  `.pool` from the underlying engine.)
- (d) Testability — can the retry shape be exercised without a live Postgres
  host using the same MagicMock pattern as the v1020 pins?

### Candidate 1 — RetryingAsyncEngine wrapper class (composition over inheritance)

A composition wrapper around `AsyncEngine`:

```python
class _RetryingAsyncEngine:
    """Composition wrapper that adds retry-on-contention to engine.connect()
    and engine.dispose(). Delegates the rest of the AsyncEngine interface to
    the underlying engine via __getattr__ so call sites are drop-in compatible.
    """
    def __init__(self, underlying, sleep_fn=asyncio.sleep, backoffs=_SETUP_PHASE_RETRY_BACKOFFS):
        self._underlying = underlying
        self._sleep_fn = sleep_fn
        self._backoffs = backoffs

    def connect(self):
        # Returns a retry-protected AsyncConnection context manager
        return _RetryingConnectCM(self._underlying, self._sleep_fn, self._backoffs)

    async def dispose(self):
        # Retry dispose on transient contention
        last_exc = None
        attempt_budget = 1 + len(self._backoffs)
        for attempt in range(attempt_budget):
            try:
                return await self._underlying.dispose()
            except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
                last_exc = e
                if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower():
                    raise
                if attempt == attempt_budget - 1:
                    raise
                await self._sleep_fn(self._backoffs[attempt])

    @property
    def pool(self):
        # Preserve .pool accessor for test_conftest_pool_sizing.py
        return self._underlying.pool

    def __getattr__(self, name):
        # Delegate everything else to the underlying engine
        return getattr(self._underlying, name)
```

**Pros:**
- Explicit, fully testable in isolation using MagicMock for the underlying engine.
- Mirrors v1020 helper API shape (`_run_with_too_many_clients_retry`,
  `_acquire_test_session_with_retry`) — same `sleep_fn` injection, same
  `backoffs` tuple, same loud-fail-on-exhaust contract.
- No monkey-patching of SQLAlchemy internals — pure composition.
- `.pool` accessor preserved via explicit `@property` delegation.
- `async_sessionmaker(engine)` works unchanged because async_sessionmaker
  accepts any object whose `connect()` returns an AsyncConnection
  context manager — the wrapper's `connect()` returns exactly that.

**Cons:**
- Must proxy the full `AsyncEngine` interface used by call sites. We use
  `engine.connect()`, `engine.dispose()`, `engine.pool`, and pass the engine
  to `async_sessionmaker(engine, ...)`. `__getattr__` covers the rest.
- Slightly more code than the other candidates.

**Criteria:**
- (a) Intercepts both `connect()` AND `dispose()` ✅
- (b) Both branches preserved — wrapper is applied at function exit, both
  branches return wrapped engines ✅
- (c) `.pool` preserved via `@property` accessor — pool-sizing pins still see
  the underlying NullPool / QueuePool class ✅
- (d) Highly testable — pass a MagicMock for `underlying`, mock `connect()`
  side_effect, assert retry path engaged. Same pattern as v1020 pins. ✅

### Candidate 2 — `event.listen(engine, "connect", retry_handler)`

SQLAlchemy event hook on the bare engine:

```python
def _retry_on_connect(dbapi_conn, connection_record):
    # Fires AFTER DBAPI connection succeeds.
    pass

event.listen(engine.sync_engine, "connect", _retry_on_connect)
```

**Pros:**
- Minimal surface change — no wrapper class, no `connect()` override.

**Cons:**
- **UNVIABLE.** SQLAlchemy connection events fire AFTER the DBAPI connection
  succeeds. By the time the event handler runs, the asyncpg
  `TooManyConnectionsError` has already been raised at the asyncpg layer.
  The handler cannot retry on an exception that fires BEFORE it runs. This
  candidate addresses the wrong layer.
- `engine.dispose()` is not coverable by `event.listen` at all (no
  "dispose" event exists).

**Criteria:**
- (a) Cannot intercept `connect()` (fires too late); cannot intercept
  `dispose()` at all ❌
- (b)/(c)/(d) — moot ❌

### Candidate 3 — NullPool acquire override (subclass NullPool, override `_create_connection`)

Subclass `NullPool` and override `_create_connection` to retry on contention:

```python
class _RetryingNullPool(NullPool):
    def _create_connection(self):
        last_exc = None
        for attempt in range(1 + len(_SETUP_PHASE_RETRY_BACKOFFS)):
            try:
                return super()._create_connection()
            except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
                last_exc = e
                ...
```

**Pros:**
- Lowest-level interception — catches every acquisition path.

**Cons:**
- Deep SQLAlchemy internals. `_create_connection` is a private API that may
  change across SQLAlchemy versions; we'd need defensive version pinning.
- **ONLY works on the NullPool xdist branch.** The sequential QueuePool
  branch (line 70-77) uses a different pool class — subclassing NullPool
  doesn't help. To cover sequential mode, we'd need ANOTHER subclass
  (`_RetryingQueuePool`), doubling the surface area.
- `engine.dispose()` is not a pool-level call. dispose() iterates pool
  connections AND closes the engine's bookkeeping — partially covered by
  pool subclassing but not symmetric.

**Criteria:**
- (a) Intercepts `connect()` indirectly via the pool; does NOT intercept
  `dispose()` symmetrically ⚠️
- (b) Both branches need separate subclasses — significantly more code ⚠️
- (c) `type(engine.pool).__name__` would change from `"NullPool"` to
  `"_RetryingNullPool"` — **BREAKS** `test_xdist_engine_uses_nullpool` at
  `test_conftest_pool_sizing.py:261` ❌
- (d) Testable but requires constructing a real engine + real pool —
  cannot use MagicMock-only pattern ⚠️

### Candidate 4 — `async_creator=` override on `create_async_engine`

Pass a `async_creator=` callable that retries `asyncpg.connect(...)` itself:

```python
async def _retrying_asyncpg_connect():
    last_exc = None
    for attempt in range(1 + len(_SETUP_PHASE_RETRY_BACKOFFS)):
        try:
            return await asyncpg.connect(...)
        except (asyncpg.TooManyConnectionsError, asyncpg.CannotConnectNowError) as e:
            ...

engine = create_async_engine(url, async_creator=_retrying_asyncpg_connect, ...)
```

**Pros:**
- Simple, asyncpg-native, no SQLAlchemy internals.

**Cons:**
- Bypasses SQLAlchemy's dialect connection-config (type-codec setup,
  search_path, schema_translate_map). For our test setup this may be
  acceptable (we don't use custom type codecs), but it's brittle.
- `async_creator=` doesn't intercept `engine.dispose()` — only the per-call
  acquisition path. We'd still need a separate dispose wrapper. Asymmetric.
- The DSN parsing duplicates the URL — we'd be parsing the same URL twice
  (once for the creator, once for SQLAlchemy's dialect config).

**Criteria:**
- (a) Intercepts `connect()` only; does NOT intercept `dispose()` ⚠️
- (b) Both branches need the creator parameter — applied at function exit
  of `_make_test_async_engine`. Workable. ✅
- (c) `.pool` accessor unchanged (we still get the SQLAlchemy-level pool
  class) ✅
- (d) Testable but requires monkey-patching `asyncpg.connect` itself —
  more invasive than MagicMock-only ⚠️

---

## Section 3 — Chosen Shape + Rationale

**Chosen: Candidate 1 — RetryingAsyncEngine wrapper class (composition over inheritance).**

### Rationale against the four criteria

- (a) **Both surfaces intercepted.** The wrapper exposes a custom `connect()`
  method that returns a retry-protected AsyncConnection context manager AND a
  custom `dispose()` method that retries on transient contention. Symmetric
  surface coverage per CONTEXT.md `<domain>` line 14. Candidates 2/3/4 each
  fail this test for at least one surface.

- (b) **Both branches preserved.** The wrapper is applied at the EXIT of
  `_make_test_async_engine` (lines 67-77 unchanged; the wrap fires after
  `create_async_engine` returns). NullPool xdist branch returns
  `_RetryingAsyncEngine(create_async_engine(url, poolclass=NullPool, ...))`;
  QueuePool sequential branch returns
  `_RetryingAsyncEngine(create_async_engine(url, pool_size=..., max_overflow=..., ...))`.
  Both paths get a wrapped engine, the underlying pool class is preserved.

- (c) **`.pool` accessor preserved.** Critical for `test_conftest_pool_sizing.py`:
  the pin at `:260` does `type(engine.pool).__name__ == "NullPool"`. Our
  wrapper has `@property def pool(self): return self._underlying.pool`, so
  `engine.pool` resolves to the underlying NullPool / QueuePool instance and
  `type(...).__name__` reads correctly. The pins do NOT regress.

- (d) **Testable via MagicMock-only.** The 4 regression pins in
  `test_fixture_isolation_v1020.py` can construct a MagicMock for the
  underlying engine, set `mock_engine.connect.side_effect = [op_error,
  success]`, exercise the wrapper, and assert retry path engaged — without
  ever touching a live Postgres host. Same shape as the existing 11 v1020
  pins.

### Helper conventions (REUSED verbatim, no new constants)

- **`_TRANSIENT_CONTENTION_EXCEPTIONS`** (line 343-347) — REUSED verbatim.
  No new exception class added to the catch tuple. If a future need arises
  to widen, that's a Plan 1093-02 deviation rule decision, not a Plan
  1093-01 spike-time choice.

- **`_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)`** (line 324) — REUSED
  verbatim per CONTEXT.md `<decisions>` "same `(1.0, 2.0, 4.0)` budget as
  v1020 fixture-layer helpers". Why the 7s setup-phase budget instead of
  the 1.5s in-test budget? Because the engine-level wrapper fires for EVERY
  connection acquisition through the engine, including the setup-phase
  ones. The setup-phase budget already proved correct in production for
  fixture setup; using the same budget at the engine layer means the
  engine wrapper subsumes the setup-phase retry coverage IN ADDITION to
  closing the post-commit residual. Tighter budgets risk false-positive
  loud-fails under combined setup-phase + commit-phase contention.

- **Substring guard for non-contention OperationalError.** Same pattern as
  `_run_with_too_many_clients_retry` at line 443:
  `if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower(): raise`.

- **Loud-fail-on-exhaust.** Same pattern as `_run_with_too_many_clients_retry`
  at line 446-447: re-raise the last exception after budget exhaustion, NOT
  silent-swallow.

- **`sleep_fn` parameter.** Same as v1020 helpers — defaults to
  `asyncio.sleep`, regression pins patch to no-op for fast test execution.

### Implementation target (Plan 1093-02 directive)

- **Wrapper class definition** at `backend/tests/conftest.py` **around line
  605** — placed AFTER `_acquire_test_session_with_retry` (lines 474-605) so
  the in-test, session-factory, and engine retry helpers are visually
  adjacent. The wrapper class is module-private (leading-underscore name).

- **Wrapper application** at `backend/tests/conftest.py:67-77` — the
  `_make_test_async_engine` function returns wrapped engines from BOTH
  branches. Two-line change:
  - Line 69: `return _RetryingAsyncEngine(create_async_engine(test_database_url, poolclass=NullPool, echo=False))`
  - Line 71-77: wrap the second `create_async_engine(...)` call's return
    value in `_RetryingAsyncEngine(...)`.

- **Function signature preservation.** `_make_test_async_engine(test_database_url)`
  signature is LOCKED by `test_conftest_pool_sizing.py:258,279` (those tests
  call the function with a positional URL argument and assert on
  `engine.pool`). The signature stays exactly as it is today.

### Regression pin family (4 pins in `test_fixture_isolation_v1020.py`)

Following the v1020 in-test pin naming convention (`test_engine_retry_*`):

1. **`test_engine_retry_succeeds_on_transient_too_many_clients`** —
   canonical pin for the SQLAlchemy-wrapped `OperationalError` retry path
   on `engine.connect()`. Asserts: factory invoked >=2 times, post-retry
   connection yielded, configured 1.0s first-backoff used, drift-guard on
   `_SETUP_PHASE_RETRY_BACKOFFS == (1.0, 2.0, 4.0)`.

2. **`test_engine_retry_catches_raw_asyncpg_too_many_connections`** —
   critical-contract pin (mirrors v1020 raw-asyncpg pin at line 665). Locks
   down that `asyncpg.exceptions.TooManyConnectionsError` stays in the
   catch tuple at the engine layer. Without this pin, a future refactor
   could narrow the catch back to `OperationalError`-only and silently drop
   the dominant in-test contention surface.

3. **`test_engine_retry_propagates_non_transient_operational_error`** —
   propagation pin. Asserts non-contention `OperationalError` shapes
   (DNS failure, auth failure, refused connection) propagate IMMEDIATELY
   on the first attempt (no retry, no swallow). Mirrors v1020 setup-phase
   propagation pin.

4. **`test_engine_retry_exhausts_budget_then_fails_loudly`** — exhaustion
   pin. Asserts 1 initial + 3 retries = 4 total attempts when every attempt
   raises a transient contention exception, then re-raises loudly. Mirrors
   v1020 setup-phase exhaustion pin.

### Single directive sentence for Plan 1093-02

**Plan 1093-02 implements the `_RetryingAsyncEngine` composition wrapper class
in `backend/tests/conftest.py` (class definition around line 605 adjacent to
`_acquire_test_session_with_retry`; wrapper application at lines 67-77 of
`_make_test_async_engine`) with 4 regression pins
(`test_engine_retry_succeeds_on_transient_too_many_clients`,
`test_engine_retry_catches_raw_asyncpg_too_many_connections`,
`test_engine_retry_propagates_non_transient_operational_error`,
`test_engine_retry_exhausts_budget_then_fails_loudly`) in
`backend/tests/test_fixture_isolation_v1020.py`.**

---

## Section 4.0 — Sequential baseline re-verify (HARD GATE)

**Captured at:** v1021 HEAD `46f45c1bef8d9f5d5494b1eebddbe56537bdba98` (post-Phase-1092 close, before any Plan 1093 code changes).

**Verbatim pytest summary line** from `/tmp/v1021-1093-01-sequential-baseline.log`:

```
3 failed, 3051 passed, 38 skipped, 14 deselected, 18 warnings in 550.02s (0:09:10)
```

**Decision-logic disposition (per Plan 1093-01 Task 2 + planning_context HARD INVARIANT):**

`failed = 3`, but all 3 failures are PRE-EXISTING at v1021 HEAD, before any Plan 1093 work begins. Documented annotations:

1. `tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` — pre-existing OOS (CONTEXT.md `<planning_context>` documents this as a known pre-existing failure).
2. `tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook` — pre-existing OOS flake (CONTEXT.md `<planning_context>` documents this as a known pre-existing flake).
3. `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` — **pre-existing-at-v1021-HEAD; NOT documented in CONTEXT.md OOS set but reproducibly present BEFORE Plan 1093 work**. Root cause: `backend/app/modules/catalog/maps/router.py` is 1807 lines, exceeding the LOC cap of 1800 by 7 lines. Introduced by Phase 1092 commit `04d9abc6` ("fix(1092-review-CR-01): sweep dual-shape decorators across 27 trailing-slash routes"). This is a Phase 1092 close-gate residual that should have been caught by Phase 1092's verification suite but slipped past the `--tb=no -q` summary line filtering. **OUT OF SCOPE for Phase 1093 engine-retry work** — the LOC-cap violation is in `app/modules/catalog/maps/router.py`, not in `tests/conftest.py` or any test-fixture engine code. Disposition: NOT a regression introduced by Plan 1093; documented here as pre-existing-OOS expansion. Suggested follow-up: track as a Phase 1092 cleanup item (decompose `maps/router.py` to fit under 1800 LOC cap, OR raise the allowlist entry with code review). The acceptance criterion (b) for TEST-01 (sequential baseline preserved) is satisfied for Plan 1093 because Plan 1093 does not touch this code.

**HARD INVARIANT disposition: SATISFIED-WITH-ANNOTATION.** Zero NEW failures attributable to Phase 1093 work (no Phase 1093 work has been done yet at this measurement point — this is the pre-fix baseline). Proceeding to Task 3 (pre-fix `pytest -n auto` 3-run baseline).

---

## Section 4 — Pre-fix Baseline Measurement (3 consecutive `pytest -n auto` runs at v1021 HEAD)

This is the v1021 starting baseline against which Plan 1093-02's post-fix
measurement is compared. Each run preceded by stale per-worker test DB
cleanup per `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 1 Step 1b.

### Section 4.1 — Pre-fix Run 1

**Verbatim pytest summary line** from `/tmp/v1021-1093-01-nauto-run1.log`:

```
99 failed, 2930 passed, 38 skipped, 11 warnings, 27 errors in 402.44s (0:06:42)
```

**Raw error-line counts** from log:
- `asyncpg.exceptions.TooManyConnectionsError`: 509 raw traceback lines
- `InvalidCatalogNameError`: 4 raw lines (category 4.1 — minor recurrence; v1088 fix usually drives this to 0 but minor flake observed)

**JUnit XML distinct counts** from `/tmp/v1021-1093-01-nauto-run1.xml`:
- `<failure>` elements: 99
- `<error>` elements: 27
- Total distinct test-case-level failures (failures + errors): **126**

**Pre-stale-DB count:** 0 (clean steady-state at run start).

### Section 4.2 — Pre-fix Run 2

**Verbatim pytest summary line** from `/tmp/v1021-1093-01-nauto-run2.log`:

```
102 failed, 2919 passed, 38 skipped, 15 warnings, 37 errors in 398.34s (0:06:38)
```

**Raw error-line counts** from log:
- `asyncpg.exceptions.TooManyConnectionsError`: 585 raw traceback lines
- `InvalidCatalogNameError`: 0 raw lines (category 4.1 — clean)

**JUnit XML distinct counts** from `/tmp/v1021-1093-01-nauto-run2.xml`:
- `<failure>` elements: 102
- `<error>` elements: 37
- Total distinct test-case-level failures (failures + errors): **139**

**Pre-stale-DB count:** 1 (one stale DB from Run 1 dropped before Run 2).

### Section 4.3 — Pre-fix Run 3

**Verbatim pytest summary line** from `/tmp/v1021-1093-01-nauto-run3.log`:

```
54 failed, 2687 passed, 27 skipped, 10 warnings, 329 errors in 307.29s (0:05:07)
```

**Raw error-line counts** from log:
- `asyncpg.exceptions.TooManyConnectionsError`: 271 raw traceback lines
- `InvalidCatalogNameError`: **616** raw lines (category 4.1 RECURRENCE — per-worker DB lifecycle race fired heavily this run; downstream tests on the affected worker(s) cascaded through their session)

**JUnit XML distinct counts** from `/tmp/v1021-1093-01-nauto-run3.xml`:
- `<failure>` elements: 54
- `<error>` elements: 329
- Total distinct test-case-level failures (failures + errors): **383**

**Pre-stale-DB count:** 0 (clean steady-state at run start).

### Section 4.4 — Pre-fix Baseline Summary

| Run | passed | failed | errors | wallclock (s) | raw cascade lines |
|-----|--------|--------|--------|---------------|-------------------|
| 1   | 2930   | 99     | 27     | 402.44        | 509               |
| 2   | 2919   | 102    | 37     | 398.34        | 585               |
| 3   | 2687   | 54     | 329    | 307.29        | 271 + ICN=616     |

**Pre-fix v1021-HEAD baseline at `pytest -n auto`: failure-count range across 3 runs is 126–383 (distinct test-case-level failures from JUnit XML; 99–329 at the `<failure>` element level alone before counting `<error>` elements). TEST-01 acceptance criterion (a) requires ≤10 failed per run across 3 consecutive runs.** Pre-fix delta needed: 116–373 fewer per run.

**Observations:**

1. **Run 3 is anomalous in the high direction** — the `InvalidCatalogNameError` recurrence (616 raw lines) indicates that even with v1020's per-worker DB lifecycle fixes, the parallel mode under `-n auto` (16 workers vs. `max_connections=30`) is still vulnerable to the category 4.1 cascade under unfavourable timing. This was a single-run flare; Runs 1 and 2 had ICN=4 and ICN=0 respectively.

2. **Cascade dominance:** Raw `TooManyConnectionsError` line counts (271–585) dominate the failure surface across all 3 runs, confirming that the engine-level retry envelope addresses the bottleneck named in Plan 1088-04's iter-3 residual analysis.

3. **Variance:** Run-to-run variance is high (failure-count range 126–383), indicating timing-driven race-window collisions per Plan 1089 PERF-01's Section 4 commentary. The engine wrapper must close enough of the cascade surface to consistently produce ≤10 failures per run.

---

## Section 5 — Reproducibility Protocol

Ordered list a fresh operator can follow to reproduce this measurement at v1021 HEAD `46f45c1bef8d9f5d5494b1eebddbe56537bdba98`:

**a.** Confirm Docker stack: `docker compose ps db` shows `geolens-db-1` healthy on `127.0.0.1:5434`.

**b.** Confirm env file: `ls /Users/ishiland/Code/geolens/.env.test` exists.

**c.** Capture HEAD SHA: `git rev-parse HEAD` must match frontmatter `head_sha` (`46f45c1bef8d9f5d5494b1eebddbe56537bdba98`).

**d.** Confirm Postgres ceiling: `docker compose exec -T db psql -U geolens -d geolens -c "SHOW max_connections;"` returns 30.

**e.** Drop stale per-worker test DBs (Section 1 Step 1b mirror from PYTEST-XDIST-PERF-v1020.md):
```bash
docker compose exec -T db psql -U geolens -d geolens -At -c \
  "SELECT datname FROM pg_database WHERE datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%';" \
  > /tmp/v1021-1093-01-stale-dbs-pre.txt
while read -r db; do [ -z "$db" ] && continue; echo "DROP DATABASE IF EXISTS \"$db\";"; done \
  < /tmp/v1021-1093-01-stale-dbs-pre.txt > /tmp/v1021-1093-01-drop-stale-pre.sql
docker compose exec -T db psql -U geolens -d geolens < /tmp/v1021-1093-01-drop-stale-pre.sql
```

**f.** Run sequential baseline (Task 2 recipe — HARD GATE):
```bash
set -a && source /Users/ishiland/Code/geolens/.env.test && set +a
cd /Users/ishiland/Code/geolens/backend
uv run pytest tests/ --tb=no -q 2>&1 | tee /tmp/v1021-1093-01-sequential-baseline.log
```
Assert: 0 NEW failures (pre-existing OOS set = test_phase_275, test_ssrf_redirect, test_layering LOC-cap per Section 4.0 annotation).

**g.** For each `RUN ∈ {1, 2, 3}`: drop stale DBs (step e), then:
```bash
set -a && source /Users/ishiland/Code/geolens/.env.test && set +a
cd /Users/ishiland/Code/geolens/backend
uv run pytest -n auto --junitxml=/tmp/v1021-1093-01-nauto-run${RUN}.xml tests/ \
  2>&1 | tee /tmp/v1021-1093-01-nauto-run${RUN}.log
```

**h.** Parse per-run subsections (4.1, 4.2, 4.3) + summary table (4.4) by extracting:
- Pytest's verbatim summary line: `grep -E "^=.*passed.*in [0-9]+\\.[0-9]+s" /tmp/v1021-1093-01-nauto-run${RUN}.log | tail -1`
- Cascade lines: `grep -c "asyncpg.exceptions.TooManyConnectionsError" /tmp/v1021-1093-01-nauto-run${RUN}.log`
- ICN lines: `grep -c "InvalidCatalogNameError" /tmp/v1021-1093-01-nauto-run${RUN}.log`
- JUnit failures: `grep -c "<failure " /tmp/v1021-1093-01-nauto-run${RUN}.xml`
- JUnit errors: `grep -c "<error " /tmp/v1021-1093-01-nauto-run${RUN}.xml`

**Wall-clock numbers are host-dependent**; cascade-failure counts should match within ±20% of the Section 4.4 table above (flake-class variance per Plan 1089 PERF-01's Section 5 commentary).

---

*Phase: 1093-engine-level-retry-envelope*
*Plan: 01 (TEST-01 spike — chosen shape + pre-fix baseline)*
*Captured: 2026-05-23*
*Plan 1093-02 will implement the RetryingAsyncEngine wrapper per Section 3 and re-measure against this baseline.*

