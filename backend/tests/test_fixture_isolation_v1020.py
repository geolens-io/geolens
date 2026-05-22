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
