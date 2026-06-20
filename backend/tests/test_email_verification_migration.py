"""Migration round-trip + ORM drift-gate regression for Phase 1231 (email verification).

Verifies the 0009_email_verification migration is reversible (downgrade is a NO-OP
per the 0008 precedent) and leaves the schema in the exact state the ORM expects
(no alembic check drift after upgrade).

Tests
-----
A: upgrade head → downgrade -1 → upgrade head all exit 0 (reversibility)
B: after upgrade head, catalog.users has email_verified column (NOT NULL boolean)
C: after upgrade head, catalog.email_verification_tokens table exists
D: alembic check reports no drift after upgrade (ORM-declared columns/table)

Notes
-----
- These tests shell out to ``alembic`` via subprocess so they exercise the real
  alembic.ini / env.py stack (the same path CI uses).
- Run against the per-worker test DB (POSTGRES_DB set to postgres_db_test) so the
  destructive downgrade/upgrade roundtrips never mutate the shared main DB.
- DB-mutating alembic calls run sequentially (not in parallel) per project convention.
- Run with: cd backend && set -a && source ../.env.test && set +a &&
            uv run pytest tests/test_email_verification_migration.py -x -q
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


def _run_alembic(*args: str) -> subprocess.CompletedProcess:
    """Run an alembic command via subprocess against the test DB.

    Uses the backend .venv python so the env matches what pytest runs with.
    PYTHONPATH is set so env.py can ``from app.core.config import settings``.
    """
    import os

    from app.core.config import settings

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    # Target the per-worker TEST DB so destructive downgrade/upgrade roundtrips
    # never mutate the shared main DB, which would corrupt sibling workers and
    # break the drift check.
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

    The core-only ``alembic`` subprocess cannot disambiguate ``head`` / ``-1``
    across branches in a multi-head environment, so these tests are skipped
    under the overlay (they still run in the no-overlay Pytest Parallel
    Isolation job).
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
    reason=(
        "OSS migration drift gate; multi-head under enterprise overlay — "
        "runs in the no-overlay Pytest Parallel Isolation job instead."
    ),
)


async def _fresh_query(query: str, params: dict | None = None):
    """Run a query on a fresh autocommit connection, bypassing the test transaction.

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


# ---------------------------------------------------------------------------
# Test A: alembic round-trip exits 0
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestMigrationRoundTripExitCodes:
    """0009_email_verification round-trips with no subprocess errors.

    Downgrade is a NO-OP (passes immediately) per the 0008_oauth_saml_columns
    precedent — so downgrade exit 0 + re-upgrade exit 0 are both guaranteed once
    upgrade head succeeds.
    """

    def test_upgrade_head_exits_zero(self):
        """alembic upgrade head exits 0 (idempotent — may already be at head)."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, (
            f"alembic upgrade head failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_downgrade_minus_one_exits_zero(self):
        """alembic downgrade -1 exits 0 (downgrade is a NO-OP per 0009 docstring)."""
        r = _run_alembic("downgrade", "-1")
        assert r.returncode == 0, (
            f"alembic downgrade -1 failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )

    def test_reupgrade_head_exits_zero(self):
        """alembic upgrade head (re-apply) exits 0 after NO-OP downgrade."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, (
            f"alembic upgrade head (re-apply) failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )


# ---------------------------------------------------------------------------
# Tests B + C: DB state after upgrade head
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestMigrationSchemaState:
    """Schema state reflects the 0009 migration correctly after upgrade head."""

    async def test_email_verified_column_exists(self):
        """catalog.users has email_verified (boolean, NOT NULL) after upgrade head."""
        # Ensure we're at head.
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, f"upgrade head failed: {r.stderr}"

        rows = await _fresh_query(
            """
            SELECT column_name, data_type, column_default, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'catalog'
              AND table_name = 'users'
              AND column_name = 'email_verified'
            """
        )
        assert rows, "email_verified column missing from catalog.users after upgrade"
        col = rows[0]
        assert col[1] == "boolean", f"email_verified is {col[1]!r}, expected 'boolean'"
        assert col[3] == "NO", "email_verified must be NOT NULL"

    async def test_email_verified_server_default_false(self):
        """email_verified server_default is 'false' (new users default to unverified)."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, f"upgrade head failed: {r.stderr}"

        rows = await _fresh_query(
            """
            SELECT column_default
            FROM information_schema.columns
            WHERE table_schema = 'catalog'
              AND table_name = 'users'
              AND column_name = 'email_verified'
            """
        )
        assert rows, "email_verified column missing"
        default_val = rows[0][0]
        assert default_val is not None, "email_verified has no server_default"
        assert "false" in default_val.lower(), (
            f"email_verified server_default is {default_val!r}, expected 'false'"
        )

    async def test_email_verification_tokens_table_exists(self):
        """catalog.email_verification_tokens table exists after upgrade head."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, f"upgrade head failed: {r.stderr}"

        rows = await _fresh_query(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'catalog'
              AND table_name = 'email_verification_tokens'
            """
        )
        assert rows, (
            "catalog.email_verification_tokens table missing after upgrade head"
        )

    async def test_email_verification_tokens_columns(self):
        """email_verification_tokens has all required columns."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, f"upgrade head failed: {r.stderr}"

        rows = await _fresh_query(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'catalog'
              AND table_name = 'email_verification_tokens'
            ORDER BY column_name
            """
        )
        cols = {row[0] for row in rows}
        required = {
            "id",
            "user_id",
            "token_hash",
            "expires_at",
            "consumed_at",
            "created_at",
        }
        missing = required - cols
        assert not missing, f"email_verification_tokens missing columns: {missing}"


# ---------------------------------------------------------------------------
# Test D: alembic check — ORM drift gate
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestAlembicCheckNoDrift:
    """alembic check reports no drift after 0009 is applied."""

    def test_alembic_check_no_drift(self):
        """alembic check exits 0 and prints 'No new upgrade operations detected.'"""
        # Ensure head first.
        _run_alembic("upgrade", "head")

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
