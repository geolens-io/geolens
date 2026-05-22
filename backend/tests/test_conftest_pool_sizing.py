"""Regression pin for the per-worker pool sizing + setup-stagger fix (TD-10 / Phase 1085).

These tests assert that:
1. _derive_test_pool_sizing() returns pool parameters that live within
   Postgres max_connections=30 (db/postgresql.conf:11).
2. _SETUP_STAGGER_SECONDS gives enough inter-worker delay to prevent setup
   connection spikes that would saturate Postgres.
3. NullPool is used for xdist async engines (no idle connections post-setup).

Any future refactor of conftest.py that silently reverts these fixes will cause
these tests to fail immediately, before the asyncpg cascade can recur.

The actual cascade root cause was twofold:
- Setup phase: 16 workers all starting setup simultaneously while API/worker
  services hold 8 persistent idle connections → total exceeds max_connections=30.
- Test phase: original pool_size=5 * 16 workers = 80 theoretical connections.

Both dimensions are addressed via staggered startup + NullPool in xdist mode.

See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for the measured fan-out
numbers and the chosen fix rationale (shape (a) selected over (b)/(c)).
"""

import os
import pytest

from tests.conftest import (
    _SETUP_STAGGER_SECONDS,
    _derive_test_pool_sizing,
    _get_setup_stagger_delay,
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


def test_setup_stagger_delay_for_master_is_zero(monkeypatch):
    """Sequential mode (worker_id=master) must have zero setup stagger."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")
    delay = _get_setup_stagger_delay()
    assert delay == 0.0, (
        f"Sequential mode must not stagger (got {delay}s). "
        "Stagger is only needed under xdist to prevent concurrent setup spikes."
    )


def test_setup_stagger_delay_for_xdist_workers(monkeypatch):
    """xdist workers get a stagger delay proportional to their worker number.

    Worker gw0 gets no delay (starts immediately), gw1 gets 1×stagger, etc.
    This prevents all 16 workers from opening dev_engine connections simultaneously.
    """
    for worker_num in [0, 1, 7, 15]:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", f"gw{worker_num}")
        delay = _get_setup_stagger_delay()
        expected = worker_num * _SETUP_STAGGER_SECONDS
        assert abs(delay - expected) < 1e-6, (
            f"gw{worker_num} stagger delay should be {expected}s (got {delay}s). "
            "The delay must scale linearly with worker number."
        )


def test_stagger_window_prevents_concurrent_setup_spikes():
    """The stagger window ensures setup phases don't overlap across workers.

    The stagger must be ≥ the per-worker setup time (dev_engine + test_engine_sync +
    alembic + _saml_bridge_engine ≈ 3-5s) to guarantee at most 1 worker is in
    the migration phase simultaneously. This prevents concurrent Postgres connections
    from stacked alembic sessions exceeding max_connections=30.

    The last worker (gw15) delays for 15 × SETUP_STAGGER_SECONDS. This adds overhead
    to the parallel run's wall clock, but the overall run is still far faster than
    sequential mode (539s baseline). Acceptable range: 30-120s overhead.
    """
    # Stagger must be ≥ setup time per worker (empirically ~3-5s for 22 migrations).
    # Use a conservative minimum of 4s.
    min_stagger_to_prevent_overlap_seconds = 4.0
    assert _SETUP_STAGGER_SECONDS >= min_stagger_to_prevent_overlap_seconds, (
        f"_SETUP_STAGGER_SECONDS ({_SETUP_STAGGER_SECONDS}s) is too small to prevent "
        f"migration overlap. Minimum is {min_stagger_to_prevent_overlap_seconds}s "
        "(empirical per-worker setup time for 22 alembic migrations)."
    )

    # Total overhead (last worker delay) must be bounded to a reasonable window.
    max_stagger_overhead_seconds = 120  # 15 workers × 5s = 75s < 120s budget
    last_worker_delay = (XDIST_WORKER_COUNT - 1) * _SETUP_STAGGER_SECONDS
    assert last_worker_delay <= max_stagger_overhead_seconds, (
        f"Last worker stagger ({last_worker_delay}s) exceeds budget "
        f"({max_stagger_overhead_seconds}s). Reduce _SETUP_STAGGER_SECONDS — "
        "the stagger is larger than the setup time that needs separating."
    )
