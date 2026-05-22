"""Regression pin for the per-worker pool sizing fix (TD-10 / Phase 1085).

These tests assert that _derive_test_pool_sizing() returns pool parameters that
live within Postgres max_connections=30 (db/postgresql.conf:11) regardless of
which worker_id value is in effect. Any future refactor of conftest.py that
silently reverts the fix will cause these tests to fail immediately, before
the asyncpg cascade can recur.

See .planning/audits/PYTEST-XDIST-SPIKE-v1019.md for the measured fan-out
numbers and the chosen fix rationale (shape (a) selected over (b)/(c)).
"""

import pytest

from tests.conftest import _derive_test_pool_sizing

# max_connections from db/postgresql.conf:11 (PERF-05 / Phase 274).
# If this constant changes, re-run the spike doc to verify the new ceiling
# is still satisfied by the per-worker pool sizing.
POSTGRES_MAX_CONNECTIONS = 30

# Admin headroom: psql + alembic + autovac + pg_stat_activity sampler.
ADMIN_HEADROOM = 4

# Worst-case xdist worker count on the reference host (16-core M-series macOS).
XDIST_WORKER_COUNT = 16


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


def test_pool_sizing_for_xdist_worker_is_reduced(monkeypatch):
    """Under xdist (gw0/gw1/...), pool_size is reduced to 1 and max_overflow to 0."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    pool_size, max_overflow = _derive_test_pool_sizing()
    assert pool_size == 1, (
        f"xdist worker must have pool_size=1 (got {pool_size}). "
        "Per-worker ceiling must stay at 1 conn to avoid cascade under -n auto."
    )
    assert max_overflow == 0, (
        f"xdist worker must have max_overflow=0 (got {max_overflow}). "
        "max_overflow=1 would push 16 workers × 2 conn = 32, exceeding max_connections=30."
    )


def test_pool_sizing_for_xdist_worker_lives_within_max_connections(monkeypatch):
    """Under xdist (gw0/gw1/...), pool sizing scales DOWN per worker.

    Total fan-out across all workers must leave at least ADMIN_HEADROOM connections
    free below Postgres max_connections=30, even at worst-case worker count.

    Math: (pool_size + max_overflow) × XDIST_WORKER_COUNT + ADMIN_HEADROOM ≤ max_connections
    """
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    pool_size, max_overflow = _derive_test_pool_sizing()
    per_worker_ceiling = pool_size + max_overflow
    total = per_worker_ceiling * XDIST_WORKER_COUNT + ADMIN_HEADROOM
    assert total <= POSTGRES_MAX_CONNECTIONS, (
        f"Pool {pool_size}+{max_overflow}={per_worker_ceiling} per worker × "
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
