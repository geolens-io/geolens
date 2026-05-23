"""Regression pins for v1020 fixture-isolation fixes (Phase 1088 / FI-03).

One regression test per audit Section 4 category fixed in Phase 1088. Each pin
SHOULD fail on pre-fix HEAD and PASS on post-fix HEAD.

The pins do NOT need a live Postgres host: they exercise the extracted helpers
(`_create_test_db_with_retry`, `_run_with_too_many_clients_retry`) directly
with mocked engine factories / coroutine callables, so they run cleanly under
`pytest tests/test_fixture_isolation_v1020.py` even without the autouse
`_test_db_lifecycle` setup completing.

Cross-references:
- Audit: `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`
    - Section 4.1 (per-worker DB lifecycle race, 407/648 failures, 62.8%)
    - Section 4.2 (setup-phase connection contention, 188 post-1088-01)
- Plans:
    - Plan 1088-01 — replaced silent-swallow at conftest.py:275-278 with
      structured `except OperationalError` handler + retry-with-backoff via
      `_create_test_db_with_retry` (category 4.1).
    - Plan 1088-03 — wrapped `_ensure_roles_and_admin` (the first async-
      session connection acquisition in the `client` fixture) with
      `_run_with_too_many_clients_retry` (category 4.2).
- Requirements: FI-02 (audit-driven fix), FI-03 (regression pin). The
  REQUIREMENTS.md traceability flip is owned by Plan 1088-N per CONTEXT.md
  LOCKED sequencing and the TD-13 `requirements_traceability_flip` rule.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from tests.conftest import (
    _IN_TEST_RETRY_BACKOFFS,
    _SETUP_PHASE_RETRY_BACKOFFS,
    _RetryingAsyncEngine,
    _acquire_test_session_with_retry,
    _create_test_db_with_retry,
    _run_with_too_many_clients_retry,
)


def _make_op_error(msg: str) -> OperationalError:
    """Construct a SQLAlchemy OperationalError carrying ``msg``.

    SQLAlchemy's OperationalError signature is
    ``OperationalError(statement, params, orig)``. We pass a stub statement
    and a plain Exception as ``orig`` so ``str(exc)`` contains ``msg`` —
    this matches the shape SQLAlchemy raises when the DBAPI surfaces a
    Postgres ``too many clients already`` error.
    """
    return OperationalError("SELECT 1", {}, Exception(msg))


def test_lifecycle_retries_on_transient_too_many_clients():
    """Audit Section 4.1 regression pin: transient TooManyConnections during
    per-worker DB CREATE must be retried, NOT silently swallowed.

    Pre-fix HEAD shape (conftest.py:275-278 before Plan 1088-01):
        try:
            with dev_engine.connect() as conn:
                ... DROP + CREATE ...
            should_drop_db = True
        except Exception:
            yield   # ← SILENT SWALLOW
            return  #   per-worker test DB never created → 407 downstream
                    #   InvalidCatalogNameError on this worker's tests.

    Post-fix HEAD shape: `_create_test_db_with_retry` retries on
    OperationalError("too many clients already") up to len(backoffs) times
    with the supplied sleep_fn, and only re-raises if every attempt fails.

    This test simulates one transient failure followed by a success and
    asserts: (1) the engine factory was called at least twice (retry path
    taken), (2) DROP DATABASE + CREATE DATABASE were executed against a
    fresh connection (post-fix code path), (3) the helper returned without
    propagating the OperationalError.

    Against the pre-fix silent-swallow shape this test fails because the
    helper does not exist; against the post-fix shape it passes because the
    retry succeeds on the 2nd attempt.
    """
    # First engine factory call raises "too many clients already"; second
    # succeeds with a context-manager that records the SQL it executed.
    first_engine = MagicMock(name="first_engine")
    first_engine.connect.side_effect = _make_op_error(
        "FATAL:  sorry, too many clients already"
    )

    executed_sql: list[str] = []
    second_engine = MagicMock(name="second_engine")
    second_conn = MagicMock(name="second_conn")
    second_engine.connect.return_value.__enter__.return_value = second_conn
    second_engine.connect.return_value.__exit__.return_value = False

    def _record_execute(stmt, *args, **kwargs):
        # SQLAlchemy text() returns a TextClause; str(stmt) yields the SQL.
        executed_sql.append(str(stmt))
        return MagicMock()

    second_conn.execute.side_effect = _record_execute

    factory_call_count = {"n": 0}

    def make_engine_fn():
        factory_call_count["n"] += 1
        return first_engine if factory_call_count["n"] == 1 else second_engine

    sleep_calls: list[float] = []

    def fake_sleep(seconds):
        # Patch the real sleep to no-op + record so the test does not actually
        # wait the backoff window during the regression check.
        sleep_calls.append(seconds)

    # Exercise the helper. Post-fix HEAD: this returns cleanly after retry.
    # Pre-fix HEAD: this test fails to import _create_test_db_with_retry.
    _create_test_db_with_retry(
        make_engine_fn,
        '"geolens_test_gw15_deadbeef"',
        sleep_fn=fake_sleep,
    )

    # Assertion 1: the factory was called >=2 times (retry path taken).
    assert factory_call_count["n"] >= 2, (
        f"Expected at least 2 engine factory calls (1 fail + 1 retry); "
        f"got {factory_call_count['n']}. The retry path was NOT taken — "
        "this likely means the pre-fix silent-swallow shape was restored."
    )

    # Assertion 2: the post-retry connection ran both DROP + CREATE.
    drop_seen = any("DROP DATABASE IF EXISTS" in sql for sql in executed_sql)
    create_seen = any(
        "CREATE DATABASE" in sql and "DROP" not in sql for sql in executed_sql
    )
    assert drop_seen, (
        f"DROP DATABASE not executed on retry attempt; got SQL={executed_sql!r}. "
        "The per-worker test DB was never recreated — same symptom as the "
        "pre-fix silent-swallow."
    )
    assert create_seen, (
        f"CREATE DATABASE not executed on retry attempt; got SQL={executed_sql!r}. "
        "The per-worker test DB was never created — downstream tests would "
        "fail with InvalidCatalogNameError, the exact 407-failure cascade."
    )

    # Assertion 3: the first engine was disposed (no leaked connection).
    first_engine.dispose.assert_called_once()

    # Assertion 4: the helper slept exactly once between the failure and
    # the retry attempt, using the configured 1.0s first-backoff budget.
    assert sleep_calls == [1.0], (
        f"Expected exactly one 1.0s backoff sleep between attempts; "
        f"got {sleep_calls!r}. Backoff timing drift may indicate the "
        "retry-budget shape changed unexpectedly."
    )


def test_lifecycle_propagates_non_contention_operational_error():
    """Companion pin: OperationalError shapes OTHER than "too many clients
    already" must propagate immediately (NOT retried).

    The fix's `_create_test_db_with_retry` only retries the contention shape;
    DNS failures, refused connections, and auth errors must surface to the
    caller so the fixture can route them to `pytest.skip(f"Postgres
    unreachable: {e}")`. This pin prevents a future refactor from widening
    the retry net to include unreachable-host shapes (which would manifest
    as 3-attempt setup hangs on unit-only test runs).
    """
    engine = MagicMock(name="engine")
    engine.connect.side_effect = _make_op_error(
        "could not translate host name \"postgres\" to address"
    )
    factory_call_count = {"n": 0}

    def make_engine_fn():
        factory_call_count["n"] += 1
        return engine

    with pytest.raises(OperationalError) as excinfo:
        _create_test_db_with_retry(
            make_engine_fn,
            '"geolens_test_gw0_cafef00d"',
            sleep_fn=lambda s: None,
        )

    assert "could not translate host name" in str(excinfo.value), (
        "OperationalError did not propagate; got "
        f"{excinfo.value!r}. Non-contention shapes MUST raise on the first "
        "attempt — the existing pytest.skip path in `_test_db_lifecycle` "
        "depends on it."
    )
    assert factory_call_count["n"] == 1, (
        f"Non-contention OperationalError was retried {factory_call_count['n']} "
        "times; expected exactly 1 attempt. Widening the retry net to include "
        "unreachable-host shapes would hang unit-only test runs."
    )


def test_lifecycle_exhausts_retry_budget_then_fails_loudly():
    """Companion pin: if every retry attempt raises TooManyConnections, the
    helper MUST re-raise (not swallow).

    This is the contract that prevents the pre-fix 407 InvalidCatalogNameError
    cascade. Under the pre-fix silent-swallow, a saturated host would yield
    silently and downstream tests would see a missing DB; under the post-fix
    structured handler, a saturated host raises OperationalError so the
    fixture surfaces it as a fixture error in JUnit XML (loud) rather than
    masking it as 407 downstream catalog-name errors (silent).
    """
    engine = MagicMock(name="engine")
    engine.connect.side_effect = _make_op_error(
        "FATAL:  sorry, too many clients already"
    )
    factory_call_count = {"n": 0}

    def make_engine_fn():
        factory_call_count["n"] += 1
        return engine

    with pytest.raises(OperationalError) as excinfo:
        _create_test_db_with_retry(
            make_engine_fn,
            '"geolens_test_gw15_baadc0de"',
            sleep_fn=lambda s: None,
            backoffs=(0.0, 0.0, 0.0),
        )

    assert "too many clients already" in str(excinfo.value).lower()
    # Budget = 1 initial attempt + 3 retries = 4 total factory calls.
    assert factory_call_count["n"] == 4, (
        f"Expected exhausted retry budget = 1 initial + 3 retries = 4 attempts; "
        f"got {factory_call_count['n']}. If this drifts, the loud-fail contract "
        "from audit Section 4.1 has changed."
    )


# ---------------------------------------------------------------------------
# Plan 1088-03 / audit Section 4.2: setup-phase async-session contention
# ---------------------------------------------------------------------------
#
# After Plan 1088-01 closed category 4.1 (407 → 0), residual category 4.2
# stayed at 188 failures under `pytest -n auto` (see
# `.planning/audits/PYTEST-XDIST-REMEASURE-AFTER-1088-01.md`). The failure
# shape is identical across all 188: `asyncpg.TooManyConnectionsError` raised
# at fixture setup, specifically when the `client` fixture's first async-
# session connection (inside `_ensure_roles_and_admin`) tries to acquire a
# connection from the test_engine's NullPool. Plan 1088-03 wraps that call
# with `_run_with_too_many_clients_retry` (a bounded retry-with-backoff
# helper that mirrors `_create_test_db_with_retry`'s shape — see audit
# Section 4.2 + Plan 1088-03 PLAN.md). These three pins guard the async
# retry path (retry-on-contention, propagate-non-contention, exhaust-then-
# loud-fail) — the same coverage envelope used for the sync helper above.


@pytest.mark.asyncio
async def test_setup_phase_contention_retries_or_serializes():
    """Audit Section 4.2 regression pin: transient TooManyConnections during
    async-session setup (e.g., `_ensure_roles_and_admin`) must be retried
    with bounded backoff, NOT silently swallowed or surfaced as a hard
    fixture error on the first attempt.

    Pre-1088-03 shape (post-1088-01 HEAD before this plan): the `client`
    fixture's body called ``await _ensure_roles_and_admin(test_session_factory)``
    directly. Under `pytest -n auto` against max_connections=30, the
    staggered-startup window placed several workers into the connection-
    saturation window simultaneously, where the first async-session
    connection acquisition (asyncpg) raised
    ``TooManyConnectionsError("sorry, too many clients already")``. With no
    retry path, the worker's fixture failed and every test that requested
    the `client` fixture was reported as "failed on setup" (188 failures
    across the suite — audit Section 4.2 / re-measure category 4.2 = 188).

    Post-1088-03 shape: ``_run_with_too_many_clients_retry`` wraps the call,
    retries on the contention shape with backoff ``(1.0, 2.0, 4.0)``, and
    only re-raises if every attempt fails.

    This test simulates one transient failure followed by a success and
    asserts (1) the callable was awaited at least twice (retry path
    taken), (2) the helper returned without propagating the
    OperationalError, (3) the helper slept exactly once between the
    failure and the retry, using the configured 1.0s first-backoff budget.

    Against the pre-1088-03 HEAD this test fails because
    `_run_with_too_many_clients_retry` does not exist; against the
    post-1088-03 HEAD it passes because the retry succeeds on the 2nd
    attempt.
    """
    # Build a coroutine factory that fails once then succeeds.
    call_count = {"n": 0}

    async def fake_coro():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OperationalError(
                "SELECT 1",
                {},
                Exception("FATAL:  sorry, too many clients already"),
            )
        return "ok"

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    # Exercise the helper. Post-fix HEAD: this returns "ok" after retry.
    # Pre-fix HEAD: this test fails to import `_run_with_too_many_clients_retry`.
    result = await _run_with_too_many_clients_retry(
        fake_coro,
        sleep_fn=fake_sleep,
    )

    # Assertion 1: the callable was awaited >=2 times (retry path taken).
    assert call_count["n"] >= 2, (
        f"Expected at least 2 coroutine invocations (1 fail + 1 retry); "
        f"got {call_count['n']}. The retry path was NOT taken — this likely "
        "means the pre-1088-03 direct-await shape was restored."
    )

    # Assertion 2: the helper returned the post-retry success value.
    assert result == "ok", (
        f"Expected post-retry callable result 'ok'; got {result!r}. The "
        "helper either swallowed the success or returned the wrong value."
    )

    # Assertion 3: the helper slept exactly once between the failure and
    # the retry, using the configured 1.0s first-backoff budget.
    assert sleep_calls == [1.0], (
        f"Expected exactly one 1.0s backoff sleep between attempts; "
        f"got {sleep_calls!r}. Backoff timing drift may indicate the "
        "retry-budget shape changed unexpectedly."
    )


@pytest.mark.asyncio
async def test_setup_phase_contention_retries_raw_asyncpg_too_many_connections():
    """Plan 1088-03 critical-contract pin: the retry helper MUST catch the
    RAW ``asyncpg.exceptions.TooManyConnectionsError`` shape, not only the
    SQLAlchemy-wrapped ``OperationalError`` shape.

    During the initial Plan 1088-03 measurement, the helper as first
    written (catching only ``OperationalError``) achieved only ~42% retry
    coverage (188 → 109) because the majority of contention failures
    surface as RAW asyncpg exceptions through the ``bind.connect()`` →
    ``greenlet_spawn`` → asyncpg connection_class path. The SQLAlchemy
    DBAPI-error wrapper does not always translate these to ``OperationalError``
    when the failure happens during connection acquisition before the
    SQLAlchemy translation layer fully engages.

    Widening the catch to include
    ``asyncpg.exceptions.TooManyConnectionsError`` /
    ``CannotConnectNowError`` (via the module-level tuple
    ``_TRANSIENT_CONTENTION_EXCEPTIONS``) is the fix that actually closes
    the 4.2 cascade. This pin guards against a future refactor narrowing
    the catch back to only ``OperationalError``.
    """
    import asyncpg.exceptions

    call_count = {"n": 0}

    async def fake_coro():
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Raise the RAW asyncpg class (NOT a SQLAlchemy-wrapped
            # OperationalError). This is the shape observed in 109 of
            # the post-1088-03-first-attempt 4.2 failures.
            raise asyncpg.exceptions.TooManyConnectionsError(
                "sorry, too many clients already"
            )
        return "ok"

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    result = await _run_with_too_many_clients_retry(
        fake_coro,
        sleep_fn=fake_sleep,
    )

    # The retry path MUST have engaged for the raw asyncpg shape.
    assert call_count["n"] >= 2, (
        f"Expected >=2 invocations after raw asyncpg.TooManyConnectionsError "
        f"(retry path); got {call_count['n']}. If this is 1, the retry "
        "helper only caught the SQLAlchemy-wrapped OperationalError and "
        "let the raw asyncpg exception propagate — exactly the bug that "
        "limited Plan 1088-03's first measurement to 42% coverage."
    )
    assert result == "ok", (
        f"Expected post-retry result 'ok'; got {result!r}."
    )
    assert sleep_calls == [1.0], (
        f"Expected exactly one 1.0s backoff between attempts; "
        f"got {sleep_calls!r}."
    )


@pytest.mark.asyncio
async def test_setup_phase_propagates_non_contention_operational_error():
    """Companion pin (4.2 symmetry): OperationalError shapes OTHER than
    "too many clients already" must propagate immediately (NOT retried) in
    the async retry path.

    The async helper `_run_with_too_many_clients_retry` only retries the
    contention shape; DNS failures, refused connections, authentication
    errors, etc. must surface to the caller on the first attempt so the
    fixture (or its caller) can route them appropriately. This pin
    prevents a future refactor from widening the retry net to include
    unreachable-host shapes (which would manifest as 3-attempt setup hangs
    under unit-only test runs without Postgres).
    """
    call_count = {"n": 0}

    async def fake_coro():
        call_count["n"] += 1
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("could not translate host name \"postgres\" to address"),
        )

    async def fake_sleep(seconds):
        return None

    with pytest.raises(OperationalError) as excinfo:
        await _run_with_too_many_clients_retry(
            fake_coro,
            sleep_fn=fake_sleep,
        )

    assert "could not translate host name" in str(excinfo.value), (
        "OperationalError did not propagate; got "
        f"{excinfo.value!r}. Non-contention shapes MUST raise on the first "
        "attempt so callers can route them to an appropriate exit path."
    )
    assert call_count["n"] == 1, (
        f"Non-contention OperationalError was retried {call_count['n']} "
        "times; expected exactly 1 attempt. Widening the retry net to "
        "include unreachable-host shapes would hang unit-only test runs."
    )


@pytest.mark.asyncio
async def test_setup_phase_exhausts_retry_budget_then_fails_loudly():
    """Companion pin (4.2 symmetry): if every retry attempt raises
    TooManyConnections, the async helper MUST re-raise (not swallow).

    This is the contract that prevents a future regression from silently
    masking 188-failure cascades like the pre-1088-03 surface. Under the
    post-1088-03 structured handler, a saturated host raises
    OperationalError so the fixture surfaces it as a fixture error in
    JUnit XML (loud) rather than masking it as test-body errors (silent).
    """
    call_count = {"n": 0}

    async def fake_coro():
        call_count["n"] += 1
        raise OperationalError(
            "SELECT 1",
            {},
            Exception("FATAL:  sorry, too many clients already"),
        )

    async def fake_sleep(seconds):
        return None

    with pytest.raises(OperationalError) as excinfo:
        await _run_with_too_many_clients_retry(
            fake_coro,
            sleep_fn=fake_sleep,
            backoffs=(0.0, 0.0, 0.0),
        )

    assert "too many clients already" in str(excinfo.value).lower()
    # Budget = 1 initial attempt + 3 retries = 4 total invocations.
    assert call_count["n"] == 4, (
        f"Expected exhausted retry budget = 1 initial + 3 retries = 4 "
        f"attempts; got {call_count['n']}. If this drifts, the loud-fail "
        "contract from audit Section 4.2 has changed."
    )


# ---------------------------------------------------------------------------
# Plan 1088-04 / audit Section 4.3: in-test connection contention
# ---------------------------------------------------------------------------
#
# After Plan 1088-03 closed category 4.2 (188 → 47, below 50 threshold),
# residual category 4.3 stayed at 137 failures under `pytest -n auto` (see
# `.planning/phases/1088-fixture-isolation-fixes-regression-pins/1088-03-SUMMARY.md`).
# The failure shape: tests internally open multiple DB connections within
# their body (multiple `TestClient.post(...)` calls), each triggering a
# fresh `override_get_db` → `test_session_factory()` connection acquisition.
# Distinct from 4.2 — here the `client` fixture has already completed
# setup and yielded; the test itself is opening a connection mid-execution.
#
# Plan 1088-04 wraps the session-factory acquisition inside `override_get_db`
# with `_acquire_test_session_with_retry` (an `@asynccontextmanager` that
# retries on `_TRANSIENT_CONTENTION_EXCEPTIONS` with a tight backoff budget
# of (0.5s, 1.0s) — bounded total wait 1.5s, well below any reasonable
# request-handler timeout). The pin below guards the in-test retry path.


class _FakeSession:
    """Async-session test double that records `execute()` calls and lets the
    test decide whether each call succeeds or raises a transient contention
    exception. Stands in for the asyncpg-backed ``AsyncSession`` returned by
    the real ``async_sessionmaker(test_engine)``.
    """

    def __init__(self, execute_outcomes):
        # Each item is either ``None`` (success, returns a sentinel Result)
        # or an ``Exception`` instance (raised by the matching execute call).
        self._outcomes = list(execute_outcomes)
        self.execute_calls = []

    async def execute(self, statement, *args, **kwargs):
        self.execute_calls.append(str(statement))
        if not self._outcomes:
            return MagicMock(name="result")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return MagicMock(name="result")


class _FakeSessionCM:
    """Stand-in for the async-session context manager returned by
    ``async_sessionmaker(test_engine)()``. The constructor accepts a
    ``session`` (the object yielded on ``__aenter__``); the failure surface
    is on the session's ``execute()``, mirroring the actual NullPool
    lazy-connection contract.
    """

    def __init__(self, session):
        self.session = session
        self.aexit_called_with = None

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.aexit_called_with = exc_type
        return False


@pytest.mark.asyncio
async def test_in_test_contention_retries_succeeds():
    """Audit Section 4.3 regression pin: transient TooManyConnections during
    in-test ``override_get_db`` → ``test_session_factory()`` acquisition must
    be retried with bounded backoff at the session-factory level, NOT
    surfaced as a hard test-body error on the first attempt.

    Pre-1088-04 shape (post-1088-03 HEAD before this plan): the `client`
    fixture defined ``override_get_db`` as a direct ``async with
    test_session_factory() as session: yield session`` body. Under
    `pytest -n auto` against max_connections=30, tests internally opening
    multiple DB connections (e.g., several sequential ``TestClient.post(...)``
    calls inside a single test body) raced the connection ceiling — 137
    failures across the suite (audit Section 4.3 / re-measure category
    4.3 = 137 post-1088-03).

    Post-1088-04 shape: ``_acquire_test_session_with_retry`` wraps the
    factory acquisition AND issues a warm-up ``SELECT 1`` inside the
    retry envelope so transient contention raised by asyncpg's lazy
    connection acquisition (triggered by the warm-up query) is caught
    and retried. Total wait budget under contention is 1.5s — bounded
    for in-test latency (must not stall test bodies indefinitely),
    shorter than the setup-phase 7s budget because in-test retries fire
    per-request and a single test may issue several sequential requests.

    This test exercises the canonical lazy-connection failure surface:
    ``__aenter__`` succeeds (session object created cheaply), but the
    warm-up ``session.execute(SELECT 1)`` raises ``OperationalError(
    "too many clients already")`` on the first attempt and succeeds on
    the retry.

    Against the pre-1088-04 HEAD this test fails because
    `_acquire_test_session_with_retry` does not exist; against the
    post-1088-04 HEAD it passes because the retry succeeds on the 2nd
    attempt.
    """
    factory_call_count = {"n": 0}
    created_sessions = []

    def fake_factory():
        factory_call_count["n"] += 1
        if factory_call_count["n"] == 1:
            # First attempt: warm-up SELECT 1 raises contention.
            session = _FakeSession(execute_outcomes=[
                OperationalError(
                    "SELECT 1",
                    {},
                    Exception("FATAL:  sorry, too many clients already"),
                )
            ])
        else:
            # Second attempt: warm-up succeeds.
            session = _FakeSession(execute_outcomes=[None])
        created_sessions.append(session)
        return _FakeSessionCM(session)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    # Exercise the helper. Post-fix HEAD: the context manager yields the
    # post-retry session. Pre-fix HEAD: this test fails to import
    # `_acquire_test_session_with_retry`.
    async with _acquire_test_session_with_retry(
        fake_factory,
        sleep_fn=fake_sleep,
    ) as session:
        yielded = session

    # Assertion 1: the factory was invoked >=2 times (retry path taken).
    assert factory_call_count["n"] >= 2, (
        f"Expected at least 2 factory invocations (1 fail + 1 retry); "
        f"got {factory_call_count['n']}. The retry path was NOT taken — "
        "this likely means the pre-1088-04 direct `async with "
        "test_session_factory()` shape was restored."
    )

    # Assertion 2: the helper yielded the post-retry session.
    assert yielded is created_sessions[-1], (
        f"Expected post-retry session sentinel; got {yielded!r}. The "
        "helper either swallowed the success or yielded the wrong value."
    )

    # Assertion 3: the warm-up SELECT 1 was executed at least once on the
    # retry attempt (the lazy-connection contract — see helper docstring).
    assert any(
        "SELECT 1" in stmt
        for s in created_sessions
        for stmt in s.execute_calls
    ), (
        f"Expected the warm-up SELECT 1 to be executed inside the retry "
        f"envelope so asyncpg connection acquisition is triggered eagerly. "
        f"Sessions executed: {[s.execute_calls for s in created_sessions]!r}. "
        "If the warm-up was elided, the lazy-connection failure surface "
        "(asyncpg `_connect_addr`) would fire later, inside the request "
        "handler, OUTSIDE this retry envelope — yielding 0 effective "
        "coverage for category 4.3 (Plan 1088-04 iter-1 measurement)."
    )

    # Assertion 4: the helper slept exactly once between the failure and
    # the retry, using the configured 0.5s first-backoff budget.
    assert sleep_calls == [0.5], (
        f"Expected exactly one 0.5s backoff sleep between attempts; "
        f"got {sleep_calls!r}. In-test retry budget drift may indicate "
        "the `_IN_TEST_RETRY_BACKOFFS` constant changed unexpectedly."
    )

    # Assertion 5: the backoff schedule constant has the canonical shape.
    # Total wait budget 1.5s — bounded for in-test latency.
    assert _IN_TEST_RETRY_BACKOFFS == (0.5, 1.0), (
        f"Expected _IN_TEST_RETRY_BACKOFFS == (0.5, 1.0) for a 1.5s total "
        f"in-test wait budget; got {_IN_TEST_RETRY_BACKOFFS!r}. If this "
        "drifts, the in-test latency contract may have changed and "
        "request-handler test bodies could stall."
    )


@pytest.mark.asyncio
async def test_in_test_contention_retries_raw_asyncpg_too_many_connections():
    """Plan 1088-04 critical-contract pin: the in-test retry helper MUST
    catch the RAW ``asyncpg.exceptions.TooManyConnectionsError`` raised
    during the warm-up ``SELECT 1``, not only the SQLAlchemy-wrapped
    ``OperationalError`` shape.

    Mirrors Plan 1088-03's
    ``test_setup_phase_contention_retries_raw_asyncpg_too_many_connections``
    pin. In production, under SQLAlchemy + asyncpg + NullPool, the
    connection-saturation error raised by asyncpg's ``_connect_addr``
    surfaces RAW through the ``greenlet_spawn`` boundary before
    SQLAlchemy's DBAPI translation layer wraps it — observed in all 137
    of the post-1088-03 category 4.3 failures (`/tmp/v1020-1088-04-xdist.log`).

    This pin guards against a future refactor narrowing the catch back
    to only ``OperationalError`` (which would silently drop the dominant
    in-test contention surface, restoring the 4.3 cascade).
    """
    import asyncpg.exceptions

    factory_call_count = {"n": 0}
    created_sessions = []

    def fake_factory():
        factory_call_count["n"] += 1
        if factory_call_count["n"] == 1:
            session = _FakeSession(execute_outcomes=[
                asyncpg.exceptions.TooManyConnectionsError(
                    "sorry, too many clients already"
                )
            ])
        else:
            session = _FakeSession(execute_outcomes=[None])
        created_sessions.append(session)
        return _FakeSessionCM(session)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    async with _acquire_test_session_with_retry(
        fake_factory,
        sleep_fn=fake_sleep,
    ) as session:
        yielded = session

    # Retry path MUST have engaged for the raw asyncpg shape.
    assert factory_call_count["n"] >= 2, (
        f"Expected >=2 invocations after raw asyncpg.TooManyConnectionsError "
        f"(retry path); got {factory_call_count['n']}. If this is 1, the "
        "retry helper only caught the SQLAlchemy-wrapped OperationalError "
        "and let the raw asyncpg exception propagate — exactly the bug "
        "that would silently drop the dominant in-test contention surface."
    )
    assert yielded is created_sessions[-1]
    assert sleep_calls == [0.5], (
        f"Expected exactly one 0.5s backoff between attempts; "
        f"got {sleep_calls!r}."
    )


@pytest.mark.asyncio
async def test_in_test_propagates_non_contention_operational_error():
    """Companion pin (4.3 symmetry): OperationalError shapes OTHER than
    "too many clients already" must propagate immediately (NOT retried)
    in the in-test retry path.

    Mirrors the setup-phase pin
    ``test_setup_phase_propagates_non_contention_operational_error``.
    DNS failures, refused connections, authentication errors, etc. are
    non-transient — retrying would just stall the test for 1.5s before
    failing with the same exception. The helper must surface them on the
    first attempt.
    """
    factory_call_count = {"n": 0}

    def fake_factory():
        factory_call_count["n"] += 1
        session = _FakeSession(execute_outcomes=[
            OperationalError(
                "SELECT 1",
                {},
                Exception("could not translate host name \"postgres\" to address"),
            )
        ])
        return _FakeSessionCM(session)

    async def fake_sleep(seconds):
        return None

    with pytest.raises(OperationalError) as excinfo:
        async with _acquire_test_session_with_retry(
            fake_factory,
            sleep_fn=fake_sleep,
        ) as session:
            # Should not reach here on the non-contention path.
            pytest.fail(
                "Helper yielded a session despite a non-contention "
                "OperationalError; the retry net was widened beyond the "
                "contention shape."
            )

    assert "could not translate host name" in str(excinfo.value), (
        "OperationalError did not propagate; got "
        f"{excinfo.value!r}. Non-contention shapes MUST raise on the first "
        "attempt so callers can route them to an appropriate exit path."
    )
    assert factory_call_count["n"] == 1, (
        f"Non-contention OperationalError was retried {factory_call_count['n']} "
        "times; expected exactly 1 attempt. Widening the retry net to "
        "include unreachable-host shapes would stall every test body 1.5s."
    )


@pytest.mark.asyncio
async def test_in_test_exhausts_retry_budget_then_fails_loudly():
    """Companion pin (4.3 symmetry): if every retry attempt raises
    TooManyConnections, the in-test helper MUST re-raise (not swallow).

    Mirrors the setup-phase pin
    ``test_setup_phase_exhausts_retry_budget_then_fails_loudly``. Under a
    fully-saturated host, the test fails loudly with OperationalError so
    the JUnit XML carries the actionable error class rather than masking
    it as a request-handler error after 1.5s of silent retries.
    """
    factory_call_count = {"n": 0}

    def fake_factory():
        factory_call_count["n"] += 1
        session = _FakeSession(execute_outcomes=[
            OperationalError(
                "SELECT 1",
                {},
                Exception("FATAL:  sorry, too many clients already"),
            )
        ])
        return _FakeSessionCM(session)

    async def fake_sleep(seconds):
        return None

    with pytest.raises(OperationalError) as excinfo:
        async with _acquire_test_session_with_retry(
            fake_factory,
            sleep_fn=fake_sleep,
            backoffs=(0.0, 0.0, 0.0),
        ) as session:
            pytest.fail(
                "Helper yielded a session despite every warm-up attempt "
                "failing; the loud-fail contract has regressed."
            )

    assert "too many clients already" in str(excinfo.value).lower()
    # Budget = 1 initial attempt + 3 retries = 4 total invocations.
    assert factory_call_count["n"] == 4, (
        f"Expected exhausted retry budget = 1 initial + 3 retries = 4 "
        f"attempts; got {factory_call_count['n']}. If this drifts, the "
        "loud-fail contract from audit Section 4.3 has changed."
    )


# ---------------------------------------------------------------------------
# Plan 1093-02 / TEST-01: engine-level retry envelope
# ---------------------------------------------------------------------------
#
# After Plan 1088-04 partially closed audit category 4.3 (137 → 48 via
# `_acquire_test_session_with_retry`), 48 deterministic + ~173 non-deterministic
# failures remained ABOVE the 30 threshold. Plan 1088-04's iter-3 residual
# analysis identified the failure shape: post-commit `bind.connect()` calls
# fire AFTER `await session.commit()` releases the warm-up's connection —
# OUTSIDE any session-factory-level retry envelope.
#
# Plan 1093-02 implements the `_RetryingAsyncEngine` composition wrapper class
# (chosen per `.planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md` Section 3) that
# wraps the test-fixture engine's `connect()` and `dispose()` calls with
# retry-on-`_TRANSIENT_CONTENTION_EXCEPTIONS` using the
# `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` budget. The wrapper:
# - REUSES `_TRANSIENT_CONTENTION_EXCEPTIONS` (line 343-347) verbatim — no new
#   exception class added to the catch tuple.
# - REUSES `_SETUP_PHASE_RETRY_BACKOFFS` (line 324) verbatim — no new constant.
# - Preserves the underlying engine's `.pool` accessor via `@property`
#   delegation (critical for `test_xdist_engine_uses_nullpool` at
#   `test_conftest_pool_sizing.py:261` and `test_sequential_engine_uses_queuepool`
#   at `:281` — both pins check `type(engine.pool).__name__`).
# - Preserves `_make_test_async_engine(test_database_url: str)` signature
#   unchanged.
# - Provides 4 regression pins below (canonical / raw-asyncpg critical-contract /
#   propagate-non-contention / exhaust-budget) mirroring v1020 in-test pin
#   family naming convention.


class _FakeAsyncEngine:
    """Test double for ``AsyncEngine`` used by the engine-retry wrapper pins.

    Records per-attempt `.connect()` calls and lets the test decide whether
    each attempt succeeds or raises a transient contention exception. The
    `.pool` accessor returns a sentinel that the wrapper's `@property pool`
    delegation must surface unchanged.
    """

    def __init__(self, connect_outcomes, dispose_outcomes=None):
        self._connect_outcomes = list(connect_outcomes)
        self._dispose_outcomes = list(dispose_outcomes or [None])
        self.connect_calls = 0
        self.dispose_calls = 0
        self._pool_sentinel = MagicMock(name="underlying_pool")

    def connect(self):
        self.connect_calls += 1
        if not self._connect_outcomes:
            return MagicMock(name="async_connection")
        outcome = self._connect_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return MagicMock(name="async_connection")

    async def dispose(self):
        self.dispose_calls += 1
        if not self._dispose_outcomes:
            return None
        outcome = self._dispose_outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return None

    @property
    def pool(self):
        return self._pool_sentinel

    # Sync engine accessor used by `async_sessionmaker` via
    # `engine._get_sync_engine_or_connection`.
    @property
    def sync_engine(self):
        return MagicMock(name="sync_engine")


def test_engine_retry_succeeds_on_transient_too_many_clients():
    """Canonical pin: transient SQLAlchemy-wrapped ``OperationalError`` on
    ``engine.connect()`` must be retried at the engine layer, NOT propagated
    on the first attempt.

    Plan 1093-02 / audit `.planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md`
    Section 3: after Plan 1088-04's session-factory wrapper closed the
    in-test warm-up surface, the engine-layer wrapper closes the
    post-commit `bind.connect()` surface that fires OUTSIDE any
    session-factory envelope.

    Asserts: (a) underlying ``connect()`` invoked >=2 times (retry path
    taken — engine_attempt_count >= 2), (b) wrapper returned the post-retry
    connection, (c) the helper slept exactly once between failure and
    retry, using the configured 1.0s first-backoff from
    ``_SETUP_PHASE_RETRY_BACKOFFS``, (d) backoff schedule constant has
    canonical shape ``_SETUP_PHASE_RETRY_BACKOFFS == (1.0, 2.0, 4.0)``
    (drift-guard).

    Pre-Plan-1093-02 HEAD: this test fails to import `_RetryingAsyncEngine`
    (helper does not exist).
    Post-Plan-1093-02 HEAD: passes because the wrapper retries on the
    second attempt.
    """
    fake_engine = _FakeAsyncEngine(connect_outcomes=[
        _make_op_error("FATAL:  sorry, too many clients already"),
        None,  # second attempt succeeds
    ])

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    wrapper = _RetryingAsyncEngine(fake_engine, sleep_fn=fake_sleep)
    result = wrapper.connect()

    # Assertion 1: underlying connect() invoked >=2 times (retry path taken).
    assert fake_engine.connect_calls >= 2, (
        f"Expected at least 2 underlying connect() invocations (1 fail + 1 "
        f"retry); got {fake_engine.connect_calls}. The retry path was NOT "
        "taken — likely the wrapper's connect() does not catch the "
        "_TRANSIENT_CONTENTION_EXCEPTIONS tuple, OR the substring guard "
        "is wrong for OperationalError contention shapes."
    )

    # Assertion 2: wrapper returned the post-retry connection sentinel.
    assert result is not None, (
        f"Expected a post-retry connection; got {result!r}. The wrapper "
        "either swallowed the success or returned the wrong value."
    )

    # Assertion 3: the helper slept exactly once between failure and retry,
    # using the configured 1.0s first-backoff (NOT the in-test 0.5s budget).
    assert sleep_calls == [1.0], (
        f"Expected exactly one 1.0s backoff sleep between attempts; "
        f"got {sleep_calls!r}. Engine-layer wrapper MUST use "
        "_SETUP_PHASE_RETRY_BACKOFFS (1.0s first), NOT _IN_TEST_RETRY_BACKOFFS "
        "(0.5s first). Drift to in-test budget would shrink the retry window "
        "below what setup-phase contention needs."
    )

    # Assertion 4: the setup-phase backoff schedule constant has canonical
    # shape. Total wait budget 7s — same as v1020 setup-phase helpers.
    assert _SETUP_PHASE_RETRY_BACKOFFS == (1.0, 2.0, 4.0), (
        f"Expected _SETUP_PHASE_RETRY_BACKOFFS == (1.0, 2.0, 4.0) for a 7s "
        f"total setup-phase wait budget; got {_SETUP_PHASE_RETRY_BACKOFFS!r}. "
        "If this drifts, the engine-layer retry contract has changed AND "
        "the v1020 setup-phase budget has changed — review Plan 1088-03 + "
        "Plan 1093-02 in tandem."
    )


def test_engine_retry_catches_raw_asyncpg_too_many_connections():
    """Critical-contract pin: the engine-layer wrapper MUST catch the RAW
    ``asyncpg.exceptions.TooManyConnectionsError`` raised during the
    underlying ``engine.connect()``, not only the SQLAlchemy-wrapped
    ``OperationalError`` shape.

    Mirrors Plan 1088-04's
    ``test_in_test_contention_retries_raw_asyncpg_too_many_connections``
    pin. Under SQLAlchemy + asyncpg + NullPool, the connection-saturation
    error raised by asyncpg's ``_connect_addr`` surfaces RAW through the
    ``greenlet_spawn`` boundary before SQLAlchemy's DBAPI translation
    layer wraps it — observed in the dominant share of category 4.3
    failures across v1020 measurements.

    This pin guards against a future refactor narrowing the catch back
    to only ``OperationalError`` (which would silently drop the dominant
    in-test contention surface, restoring the post-commit residual that
    Plan 1093-02 was created to close).
    """
    import asyncpg.exceptions

    fake_engine = _FakeAsyncEngine(connect_outcomes=[
        asyncpg.exceptions.TooManyConnectionsError(
            "sorry, too many clients already"
        ),
        None,  # second attempt succeeds
    ])

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    wrapper = _RetryingAsyncEngine(fake_engine, sleep_fn=fake_sleep)
    result = wrapper.connect()

    # Retry path MUST have engaged for the raw asyncpg shape.
    assert fake_engine.connect_calls >= 2, (
        f"Expected >=2 invocations after raw asyncpg.TooManyConnectionsError "
        f"(retry path); got {fake_engine.connect_calls}. If this is 1, the "
        "engine-layer wrapper only caught the SQLAlchemy-wrapped "
        "OperationalError and let the raw asyncpg exception propagate — "
        "exactly the bug that would silently drop the dominant in-test "
        "contention surface."
    )
    assert result is not None
    assert sleep_calls == [1.0], (
        f"Expected exactly one 1.0s backoff between attempts; "
        f"got {sleep_calls!r}."
    )


def test_engine_retry_propagates_non_transient_operational_error():
    """Propagation pin: ``OperationalError`` shapes OTHER than "too many
    clients already" must propagate immediately (NOT retried) at the
    engine layer.

    Mirrors the v1020 setup-phase / in-test propagation pins. DNS
    failures, refused connections, authentication errors, etc. are
    non-transient — retrying would just stall fixture setup for the
    full 7s budget before failing with the same exception. The wrapper
    must surface them on the first attempt.
    """
    fake_engine = _FakeAsyncEngine(connect_outcomes=[
        _make_op_error("could not translate host name \"postgres\" to address"),
    ])

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    wrapper = _RetryingAsyncEngine(fake_engine, sleep_fn=fake_sleep)

    with pytest.raises(OperationalError) as excinfo:
        wrapper.connect()

    assert "could not translate host name" in str(excinfo.value), (
        "OperationalError did not propagate; got "
        f"{excinfo.value!r}. Non-contention shapes MUST raise on the first "
        "attempt so callers can route them to an appropriate exit path."
    )
    assert fake_engine.connect_calls == 1, (
        f"Non-contention OperationalError was retried {fake_engine.connect_calls} "
        "times; expected exactly 1 attempt. Widening the retry net to "
        "include unreachable-host shapes would stall every fixture setup 7s."
    )
    assert sleep_calls == [], (
        f"Expected zero backoff sleeps on non-contention propagation; "
        f"got {sleep_calls!r}."
    )


def test_engine_retry_exhausts_budget_then_fails_loudly():
    """Exhaustion pin: if every retry attempt raises
    ``asyncpg.TooManyConnectionsError``, the engine-layer wrapper MUST
    re-raise after budget exhaustion (not swallow).

    Mirrors v1020 setup-phase / in-test exhaustion pins. Under a
    fully-saturated host, the test fails loudly with
    ``TooManyConnectionsError`` so the JUnit XML carries the actionable
    error class rather than masking it as a downstream session error.
    """
    import asyncpg.exceptions

    fake_engine = _FakeAsyncEngine(connect_outcomes=[
        asyncpg.exceptions.TooManyConnectionsError("sorry, too many clients already"),
        asyncpg.exceptions.TooManyConnectionsError("sorry, too many clients already"),
        asyncpg.exceptions.TooManyConnectionsError("sorry, too many clients already"),
        asyncpg.exceptions.TooManyConnectionsError("sorry, too many clients already"),
    ])

    sleep_calls: list[float] = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    # Override budget to (0.0, 0.0, 0.0) so the test doesn't actually wait
    # while still exercising the 1 + 3 = 4 attempt shape.
    wrapper = _RetryingAsyncEngine(
        fake_engine, sleep_fn=fake_sleep, backoffs=(0.0, 0.0, 0.0)
    )

    with pytest.raises(asyncpg.exceptions.TooManyConnectionsError) as excinfo:
        wrapper.connect()

    assert "too many clients already" in str(excinfo.value).lower()
    # Budget = 1 initial attempt + 3 retries = 4 total invocations.
    assert fake_engine.connect_calls == 4, (
        f"Expected exhausted retry budget = 1 initial + 3 retries = 4 "
        f"attempts; got {fake_engine.connect_calls}. If this drifts, the "
        "loud-fail contract from audit Section 3 has changed."
    )
    # Sleeps between attempts (3 sleeps for 4 attempts).
    assert len(sleep_calls) == 3, (
        f"Expected 3 sleep calls between 4 attempts; got {len(sleep_calls)} "
        f"({sleep_calls!r})."
    )
