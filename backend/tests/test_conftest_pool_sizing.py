"""Test engines stay within the connection budget when xdist runs 16 workers.

These tests assert that:
1. _derive_test_pool_sizing() keeps the (5, 2) pool in sequential mode and
   returns the (1, 0) NullPool sentinel under xdist, which fits 16 workers
   in a 30-connection budget.
2. _make_test_async_engine() really builds a NullPool engine under xdist, so a
   worker holds no idle connections between tests.
"""

from tests.conftest import (
    _derive_test_pool_sizing,
    _make_test_async_engine,
)

# max_connections from db/postgresql.conf:11 (PERF-05 / Phase 274).
# If this constant changes, re-run the spike doc to verify the new ceiling
# is still satisfied by the per-worker pool sizing.
POSTGRES_MAX_CONNECTIONS = 30

# Admin headroom: psql + alembic + autovac + pg_stat_activity sampler.
ADMIN_HEADROOM = 4

# Worst-case xdist worker count on the reference host (16-core M-series macOS).
XDIST_WORKER_COUNT = 16

# Persistent idle connections from the running API + worker Docker services.
# These are always present during dev-host test runs.
API_SERVICE_CONNECTIONS = 8

# Postgres background processes (autovac + walwriter + checkpointer + etc.)
POSTGRES_BACKGROUND = 5


def test_pool_sizing_for_master_session_is_unchanged(monkeypatch):
    """Sequential pytest (worker_id=master) keeps the historical (5, 2) pool.

    The v1018 baseline (3025/0/38 in 539s) was built against pool_size=5,
    max_overflow=2. Reducing this in sequential mode would serialise request
    handlers that open multiple concurrent DB connections within a single test
    (e.g. reupload, IDOR tests).
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")
    pool_size, max_overflow = _derive_test_pool_sizing()
    assert pool_size == 5, (
        f"Sequential mode must keep pool_size=5 (got {pool_size}). "
        "Do not reduce sequential pool sizing — it breaks multi-conn tests."
    )
    assert max_overflow == 2, (
        f"Sequential mode must keep max_overflow=2 (got {max_overflow}). "
        "Do not reduce sequential pool sizing — it breaks multi-conn tests."
    )


def test_pool_sizing_for_xdist_worker_returns_nullpool_sentinel(monkeypatch):
    """Under xdist (gw0/gw1/...), _derive_test_pool_sizing returns the NullPool sentinel.

    The actual engine creation in the client fixture uses NullPool (not QueuePool)
    for xdist workers, so pool_size/max_overflow values from _derive_test_pool_sizing
    are not directly used for the async engine. The sentinel (1, 0) serves two roles:
    1. Signals "use NullPool" to the engine creation branch.
    2. Remains a valid (pool_size, max_overflow) pair for the budget regression
       test below (16 × (1+0) + 4 ≤ 30 confirms the async pool budget if
       NullPool were replaced with QueuePool as a future regression marker).
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    pool_size, max_overflow = _derive_test_pool_sizing()
    assert pool_size == 1, (
        f"xdist worker sentinel must have pool_size=1 (got {pool_size}). "
        "This signals NullPool usage in the client fixture."
    )
    assert max_overflow == 0, (
        f"xdist worker sentinel must have max_overflow=0 (got {max_overflow}). "
        "max_overflow=0 is the NullPool-mode sentinel."
    )


def test_pool_sizing_sentinel_lives_within_max_connections(monkeypatch):
    """The NullPool sentinel (1, 0) satisfies the max_connections budget arithmetic.

    Under xdist, the actual engine uses NullPool (no idle connections). This test
    verifies that if NullPool were replaced with a QueuePool using the sentinel
    values, the fan-out would still fit within max_connections=30 — acting as a
    regression guard against loosening the sentinel.
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    pool_size, max_overflow = _derive_test_pool_sizing()
    per_worker_ceiling = pool_size + max_overflow
    total = per_worker_ceiling * XDIST_WORKER_COUNT + ADMIN_HEADROOM
    assert total <= POSTGRES_MAX_CONNECTIONS, (
        f"Sentinel {pool_size}+{max_overflow}={per_worker_ceiling} per worker × "
        f"{XDIST_WORKER_COUNT} workers + {ADMIN_HEADROOM} admin = {total} "
        f"exceeds max_connections={POSTGRES_MAX_CONNECTIONS}. "
        "Re-run the spike (.planning/audits/PYTEST-XDIST-SPIKE-v1019.md) and revise."
    )


def test_pool_sizing_with_worker_id_unset(monkeypatch):
    """When PYTEST_XDIST_WORKER is absent (clean env), treat as sequential mode."""
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    pool_size, max_overflow = _derive_test_pool_sizing()
    assert pool_size == 5 and max_overflow == 2, (
        f"Unset PYTEST_XDIST_WORKER must behave like master (5, 2); got ({pool_size}, {max_overflow}). "
        "The env var defaults to 'master' inside _derive_test_pool_sizing()."
    )


# ---------------------------------------------------------------------------
# CR-02: NullPool branch coverage — verifies _make_test_async_engine()
# actually uses NullPool under xdist (not just that the sentinel returns (1,0))
# ---------------------------------------------------------------------------


def test_xdist_engine_uses_nullpool(monkeypatch):
    """_make_test_async_engine() must create a NullPool engine for xdist workers.

    This is the critical regression guard that was missing from the original
    7-test suite. The previous tests only verified _derive_test_pool_sizing()
    returns the (1, 0) sentinel — but the client fixture could silently ignore
    NullPool (e.g. if someone inverted the _is_xdist branch) and all 7 tests
    would still pass. This test pins the actual engine class.

    Uses a fake URL because no live DB is needed to construct the engine object.
    The pool class is resolved at engine creation time, not connection time.
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    engine = _make_test_async_engine(
        "postgresql+asyncpg://testuser:testpass@localhost/testdb"
    )
    try:
        pool_class_name = type(engine.pool).__name__
        assert pool_class_name == "NullPool", (
            f"xdist engine must use NullPool; got {pool_class_name}. "
            "Check the _is_xdist branch in _make_test_async_engine() — "
            "reverting to QueuePool will cause connection fan-out under 16 workers."
        )
    finally:
        import asyncio

        asyncio.run(engine.dispose())


def test_sequential_engine_uses_queuepool(monkeypatch):
    """_make_test_async_engine() must create a non-NullPool engine for sequential mode.

    Sequential mode (PYTEST_XDIST_WORKER unset or 'master') uses the historical
    (5, 2) QueuePool so request handlers that need multiple concurrent DB connections
    within a single test still work (e.g. reupload, IDOR tests).
    """
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    engine = _make_test_async_engine(
        "postgresql+asyncpg://testuser:testpass@localhost/testdb"
    )
    try:
        pool_class_name = type(engine.pool).__name__
        assert pool_class_name != "NullPool", (
            f"Sequential engine must NOT use NullPool; got {pool_class_name}. "
            "Sequential mode needs QueuePool so multi-conn tests can open >1 "
            "concurrent connection within a single test."
        )
    finally:
        import asyncio

        asyncio.run(engine.dispose())
