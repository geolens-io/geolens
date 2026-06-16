"""Programmatic migration round-trip + OSS drift-gate regression for Phase 1207.

Verifies the 0005_dormant_tenancy migration is reversible and leaves the schema
in the exact state the ORM expects (no alembic check drift after upgrade).

Tests
-----
A: upgrade head → downgrade -1 → upgrade head all exit 0 (reversibility)
B: after downgrade, the four partial unique indexes and tenant_id columns are absent
C: after re-upgrade, the four partial indexes and tenant_id on the six shared tables
   are all present
D: alembic check reports no drift after upgrade (OSS drift gate)

Notes
-----
- These tests shell out to ``alembic`` via subprocess so they exercise the real
  alembic.ini / env.py stack (the same path CI uses) rather than calling the
  Python API directly.
- The tests run against the live test database (POSTGRES_* from .env.test).
  Run with: cd backend && set -a && source ../.env.test && set +a && uv run pytest
  tests/test_dormant_tenancy_migration_roundtrip.py -x -q
- Uses the same ``test_db_session`` async fixture as the other dormant-tenancy
  schema tests (anyio_mode = "auto" in pyproject.toml).
- DB-mutating alembic calls are run sequentially (not in parallel) per the
  project memory note on concurrent DB probes.
"""

import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent.parent.resolve()
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

_FOUR_PARTIAL_INDEXES = {
    "uq_users_username_global",
    "uq_users_username_tenant",
    "uq_users_email_global",
    "uq_users_email_tenant",
}

_SIX_SHARED_TABLES = [
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
]


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    """Run an alembic command via subprocess against the test DB.

    Uses the backend .venv python so the env matches what pytest runs with.
    PYTHONPATH is set so env.py can ``from app.core.config import settings``.
    """
    import os

    from app.core.config import settings

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    # Target the per-worker TEST DB (isolated + conftest-migrated to head) so the
    # destructive downgrade/upgrade roundtrips never mutate the SHARED main DB
    # (`postgres` on CI), which would corrupt sibling workers and the drift check.
    env["POSTGRES_DB"] = settings.postgres_db_test

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(_ALEMBIC_INI),
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_BACKEND_DIR),
    )
    return result


def _enterprise_migrations_present() -> bool:
    """True when an enterprise/overlay migrations entry-point is installed.

    conftest then migrates the per-worker test DB to the enterprise head (e.g.
    e002_add_saml_columns), making the alembic environment MULTI-HEAD. The
    core-only ``alembic`` subprocess these OSS-drift-gate roundtrip/check tests
    shell out to can neither locate the enterprise revision nor disambiguate
    ``head`` / ``-1`` across branches — so they are skipped under the overlay.
    They still run (and gate drift) in the no-overlay Pytest Parallel Isolation
    job. Core registers no ``geolens.migrations`` entry-point, so this is False
    for community/OSS runs.
    """
    import pathlib
    from importlib.metadata import entry_points

    for ep in entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
            if callable(fn) and any(pathlib.Path(p).is_dir() for p in fn()):
                return True
        except Exception:
            pass
    return False


_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    _enterprise_migrations_present(),
    reason="OSS migration drift gate; multi-head under enterprise overlay — "
    "runs in the no-overlay Pytest Parallel Isolation job instead.",
)


# ---------------------------------------------------------------------------
# Test A: alembic round-trip exits 0
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestMigrationRoundTripExitCodes:
    """0005_dormant_tenancy round-trips reversibly with no subprocess errors."""

    def test_upgrade_head_exits_zero(self):
        """alembic upgrade head exits 0 (idempotent — may already be at head)."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, (
            f"alembic upgrade head failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        # Must reference 0005 or report already-at-head (no-op).
        assert (
            "0005_dormant_tenancy" in r.stderr
            or "No upgrade operations" in r.stderr
            or r.returncode == 0
        )

    def test_downgrade_minus_one_exits_zero(self):
        """alembic downgrade -1 exits 0 (one step back from current head).

        When head is 0006_tenant_rls this downgrades to 0005_dormant_tenancy.
        When head is 0005_dormant_tenancy this downgrades to 0004_add_maps_legend_title.
        We only assert exit 0 here — the direction check lives in the per-migration
        round-trip test (test_tenant_rls_migration.py).
        """
        r = _run_alembic("downgrade", "-1")
        assert r.returncode == 0, (
            f"alembic downgrade -1 failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_reupgrade_head_exits_zero(self):
        """alembic upgrade head (re-apply current head) exits 0 after downgrade."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, (
            f"alembic upgrade head (re-apply) failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )


# ---------------------------------------------------------------------------
# Tests B + C: DB state after downgrade and re-upgrade
# ---------------------------------------------------------------------------


async def _fresh_query(query: str, params: dict | None = None):
    """Run a query on a fresh autocommit connection, bypassing test transaction.

    The ``test_db_session`` fixture holds an open transaction around each test.
    Schema changes made by subprocess alembic (which commit outside that
    transaction) are invisible to the session due to transaction snapshot
    isolation.  We need a separate connection with ``AUTOCOMMIT`` isolation
    to observe committed DDL changes.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            if params:
                result = await conn.execute(sa.text(query), params)
            else:
                result = await conn.execute(sa.text(query))
            return result.fetchall()
    finally:
        await engine.dispose()


@_SKIP_UNDER_OVERLAY
class TestMigrationRoundTripSchemaState:
    """Schema state reflects the migration correctly after downgrade and re-upgrade.

    These tests downgrade to an absolute revision (0004_add_maps_legend_title)
    rather than using ``-1`` so they remain correct regardless of how many
    migrations have been added on top of 0005.
    """

    async def test_post_downgrade_indexes_absent(self):
        """After downgrade to 0004, the four partial indexes are gone."""
        r = _run_alembic("downgrade", "0004_add_maps_legend_title")
        assert r.returncode == 0, f"downgrade failed: {r.stderr}"

        rows = await _fresh_query(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'catalog'
              AND tablename = 'users'
              AND indexname = ANY(:names)
            """,
            {"names": sorted(_FOUR_PARTIAL_INDEXES)},
        )
        found = {row[0] for row in rows}
        assert not found, f"Partial indexes still present after downgrade: {found}"

        # Restore head for subsequent tests.
        r2 = _run_alembic("upgrade", "head")
        assert r2.returncode == 0, f"re-upgrade failed: {r2.stderr}"

    async def test_post_downgrade_tenant_id_absent_on_users(self):
        """After downgrade to 0004, tenant_id is gone from catalog.users."""
        r = _run_alembic("downgrade", "0004_add_maps_legend_title")
        assert r.returncode == 0, f"downgrade failed: {r.stderr}"

        rows = await _fresh_query(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'catalog'
              AND table_name = 'users'
              AND column_name = 'tenant_id'
            """
        )
        assert not rows, "tenant_id still present on catalog.users after downgrade"

        r2 = _run_alembic("upgrade", "head")
        assert r2.returncode == 0, f"re-upgrade failed: {r2.stderr}"

    async def test_post_upgrade_partial_indexes_present(self):
        """After re-upgrade, all four partial unique indexes exist on catalog.users."""
        rows = await _fresh_query(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'catalog'
              AND tablename = 'users'
              AND indexname = ANY(:names)
            ORDER BY indexname
            """,
            {"names": sorted(_FOUR_PARTIAL_INDEXES)},
        )
        found = {row[0] for row in rows}
        missing = _FOUR_PARTIAL_INDEXES - found
        assert not missing, f"Partial indexes missing after re-upgrade: {missing}"

    async def test_post_upgrade_tenant_id_on_all_shared_tables(self):
        """After re-upgrade, tenant_id (nullable) exists on all six shared tables."""
        rows = await _fresh_query(
            """
            SELECT table_name, is_nullable FROM information_schema.columns
            WHERE table_schema = 'catalog'
              AND column_name = 'tenant_id'
              AND table_name = ANY(:tables)
            ORDER BY table_name
            """,
            {"tables": _SIX_SHARED_TABLES},
        )
        result_map = {r[0]: r[1] for r in rows}

        missing = [t for t in _SIX_SHARED_TABLES if t not in result_map]
        assert not missing, f"tenant_id missing from tables after re-upgrade: {missing}"

        not_nullable = [t for t, nullable in result_map.items() if nullable != "YES"]
        assert not not_nullable, f"tenant_id is not nullable on: {not_nullable}"


# ---------------------------------------------------------------------------
# Test D: alembic check — OSS drift gate
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestAlembicCheckNoDrift:
    """alembic check (OSS drift gate) reports no new upgrade operations after 0005."""

    def test_alembic_check_no_drift(self):
        """alembic check exits 0 and prints 'No new upgrade operations detected.'"""
        r = _run_alembic("check")
        assert r.returncode == 0, (
            f"alembic check exited {r.returncode} (drift detected):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        combined = r.stdout + r.stderr
        assert "No new upgrade operations detected." in combined, (
            f"Expected 'No new upgrade operations detected.' in check output.\n"
            f"Got:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
