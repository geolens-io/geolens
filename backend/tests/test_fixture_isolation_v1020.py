"""Regression pins for v1020 fixture-isolation fixes (Phase 1088 / FI-03).

One regression test per audit Section 4 category fixed in Phase 1088. Each pin
SHOULD fail on pre-fix HEAD and PASS on post-fix HEAD.

The pins do NOT need a live Postgres host: they exercise the extracted helpers
(`_create_test_db_with_retry`) directly with mocked engine factories, so they
run cleanly under `pytest tests/test_fixture_isolation_v1020.py` even without
the autouse `_test_db_lifecycle` setup completing.

Cross-references:
- Audit: `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` Section 4.1
  (per-worker DB lifecycle race, 407/648 failures, 62.8% of total).
- Plan: `.planning/phases/1088-fixture-isolation-fixes-regression-pins/1088-01-PLAN.md`
  (the fix-first plan that replaced the silent-swallow at conftest.py:275-278
  with a structured `except OperationalError` handler + retry-with-backoff
  via `_create_test_db_with_retry`).
- Requirements: FI-02 (audit-driven fix), FI-03 (regression pin). The
  REQUIREMENTS.md traceability flip is owned by Plan 1088-N per CONTEXT.md
  LOCKED sequencing and the TD-13 `requirements_traceability_flip` rule.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from tests.conftest import _create_test_db_with_retry


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
