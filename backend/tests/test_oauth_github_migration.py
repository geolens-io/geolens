"""Migration round-trip + constraint-state regression for Phase 1237 (GitHub provider type).

Verifies the 0010_oauth_github_provider_type migration:
  - Adds 'github' to the chk_oauth_providers_type CHECK constraint
  - Retains 'saml' on both upgrade and downgrade
  - Leaves the alembic head as a single head and schema drift-free

Tests
-----
A: upgrade head → downgrade -1 → upgrade head all exit 0 (reversibility)
B: after upgrade head, a github-typed row inserts successfully into
   catalog.oauth_providers (constraint admits 'github')
C: after upgrade head, a saml-typed row still satisfies the constraint;
   after downgrade -1, a saml-typed row still satisfies it (saml not dropped)
D: alembic heads reports a single head; alembic check reports no drift

Notes
-----
- These tests shell out to ``alembic`` via subprocess so they exercise the real
  alembic.ini / env.py stack (the same path CI uses).
- Run against the per-worker test DB (POSTGRES_DB set to postgres_db_test) so the
  destructive downgrade/upgrade roundtrips never mutate the shared main DB.
- DB-mutating alembic calls run sequentially (not in parallel) per project convention.
- Run with: cd backend && set -a && source ../.env.test && set +a &&
            uv run pytest tests/test_oauth_github_migration.py -x -q
"""

import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Helpers (self-contained copies — mirrors test_email_verification_migration.py)
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
    """Run a SELECT query on a fresh autocommit connection.

    The ``test_db_session`` fixture holds an open transaction around each test.
    Schema changes made by subprocess alembic (which commit outside that
    transaction) are invisible to the session due to transaction snapshot
    isolation.  We need a separate connection with ``AUTOCOMMIT`` isolation
    to observe committed DDL changes.

    For DML statements (INSERT/DELETE) use ``_fresh_execute`` instead.
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


async def _fresh_execute(query: str, params: dict | None = None) -> None:
    """Run a DML statement on a fresh autocommit connection (no rows returned)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            if params:
                await conn.execute(sa.text(query), params)
            else:
                await conn.execute(sa.text(query))
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Test A: alembic round-trip exits 0
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestMigrationRoundTripExitCodes:
    """0010_oauth_github_provider_type round-trips with no subprocess errors.

    Downgrade recreates the constraint without 'github' (but keeps 'saml'),
    so both downgrade and re-upgrade are real DDL operations — unlike the
    NO-OP downgrade pattern in 0008/0009.

    The ENTIRE round-trip (upgrade -> downgrade -> re-upgrade) runs in ONE test
    method with the re-upgrade in a finally. It MUST NOT be split into separate
    test methods: under ``pytest -n`` (--dist load) the downgrade and re-upgrade
    would be distributed independently, leaving a per-worker DB with the
    'github'-less constraint between them. Any sibling github-create test
    scheduled on that worker in the gap then fails with a CHECK violation
    (chk_oauth_providers_type) — a real, scheduling-dependent flake. Keeping the
    round-trip atomic means no other test ever runs while the DB is downgraded.
    """

    def test_migration_roundtrip_exits_zero(self):
        """upgrade head -> downgrade -1 -> upgrade head all exit 0, and the DB is
        ALWAYS restored to head before this test returns."""
        import asyncio

        # Start at head (idempotent).
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, (
            f"alembic upgrade head failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )

        try:
            # Delete any github-typed rows so downgrade's ADD CONSTRAINT does not
            # fail with a CHECK violation (sibling provider-create tests use the
            # same per-worker DB as the migration subprocess).
            async def _cleanup():
                await _fresh_execute(
                    "DELETE FROM catalog.oauth_providers WHERE provider_type = 'github'"
                )

            asyncio.run(_cleanup())

            r = _run_alembic("downgrade", "-1")
            assert r.returncode == 0, (
                f"alembic downgrade -1 failed (rc={r.returncode}):\n"
                f"stdout: {r.stdout}\nstderr: {r.stderr}"
            )
        finally:
            # ALWAYS re-upgrade so the worker DB is never left downgraded for
            # sibling tests — even if the downgrade assertion above fails.
            r2 = _run_alembic("upgrade", "head")
            assert r2.returncode == 0, (
                f"alembic upgrade head (re-apply) failed (rc={r2.returncode}):\n"
                f"stdout: {r2.stdout}\nstderr: {r2.stderr}"
            )


# ---------------------------------------------------------------------------
# Test B: github-typed row inserts after upgrade
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestGithubConstraintAfterUpgrade:
    """After upgrade head, the constraint admits 'github'."""

    async def test_github_row_inserts_successfully(self):
        """A github-typed row inserts into catalog.oauth_providers after upgrade."""
        # Ensure we're at head.
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, f"upgrade head failed: {r.stderr}"

        # Insert a minimal github-typed row (all NOT-NULL columns provided).
        # Use a unique slug so repeated test runs do not collide.
        import uuid

        slug = f"test-github-{uuid.uuid4().hex[:8]}"

        await _fresh_execute(
            """
            INSERT INTO catalog.oauth_providers
                (slug, display_name, provider_type, client_id,
                 client_secret_encrypted, scopes, default_role, enabled)
            VALUES
                (:slug, 'Test GitHub', 'github', 'gh-client-id',
                 'gh-secret-enc', 'read:user user:email', 'viewer', true)
            """,
            {"slug": slug},
        )

        # Verify the row exists.
        rows = await _fresh_query(
            "SELECT provider_type FROM catalog.oauth_providers WHERE slug = :slug",
            {"slug": slug},
        )
        assert rows, "github-typed row not found after insert"
        assert rows[0][0] == "github"

        # Clean up.
        await _fresh_execute(
            "DELETE FROM catalog.oauth_providers WHERE slug = :slug",
            {"slug": slug},
        )

    async def test_constraint_check_definition_includes_github(self):
        """The chk_oauth_providers_type constraint definition includes 'github' after upgrade."""
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, f"upgrade head failed: {r.stderr}"

        rows = await _fresh_query(
            """
            SELECT pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conname = 'chk_oauth_providers_type'
              AND conrelid = 'catalog.oauth_providers'::regclass
            """
        )
        assert rows, "chk_oauth_providers_type constraint not found"
        constraint_def = rows[0][0]
        assert "github" in constraint_def, (
            f"'github' not in constraint definition after upgrade: {constraint_def}"
        )
        assert "saml" in constraint_def, (
            f"'saml' missing from constraint definition after upgrade: {constraint_def}"
        )


# ---------------------------------------------------------------------------
# Test C: saml retained on downgrade; github dropped on downgrade
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestSamlRetainedOnDowngrade:
    """After downgrade -1, 'saml' is still in the constraint, 'github' is not."""

    async def test_saml_in_constraint_after_downgrade(self):
        """Downgrading 0010 removes 'github' but keeps 'saml' in the constraint."""
        # Start at head.
        r = _run_alembic("upgrade", "head")
        assert r.returncode == 0, f"upgrade head failed: {r.stderr}"

        # Remove any github-typed rows created by sibling tests before downgrading.
        await _fresh_execute(
            "DELETE FROM catalog.oauth_providers WHERE provider_type = 'github'"
        )

        try:
            # Downgrade one step (removes 0010 = removes 'github', keeps 'saml').
            r = _run_alembic("downgrade", "-1")
            assert r.returncode == 0, f"downgrade -1 failed: {r.stderr}"

            rows = await _fresh_query(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conname = 'chk_oauth_providers_type'
                  AND conrelid = 'catalog.oauth_providers'::regclass
                """
            )
            assert rows, "chk_oauth_providers_type constraint missing after downgrade"
            constraint_def = rows[0][0]
            assert "saml" in constraint_def, (
                f"'saml' dropped from constraint on downgrade — co-owned constraint violation: "
                f"{constraint_def}"
            )
            assert "github" not in constraint_def, (
                f"'github' still present in constraint after downgrade: {constraint_def}"
            )
        finally:
            # ALWAYS re-upgrade for subsequent tests — even if an assertion above
            # fails — so the per-worker DB is never left downgraded (which would
            # fail sibling github-create tests with a CHECK violation).
            r = _run_alembic("upgrade", "head")
            assert r.returncode == 0, f"re-upgrade failed: {r.stderr}"


# ---------------------------------------------------------------------------
# Test D: single head + no drift
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestSingleHeadAndNoDrift:
    """alembic heads is a single head; alembic check detects no drift after upgrade."""

    def test_single_head(self):
        """alembic heads reports exactly one (head) revision."""
        r = _run_alembic("heads")
        assert r.returncode == 0, (
            f"alembic heads failed (rc={r.returncode}):\n"
            f"stdout: {r.stdout}\nstderr: {r.stderr}"
        )
        combined = r.stdout + r.stderr
        head_count = combined.count("(head)")
        assert head_count == 1, (
            f"Expected exactly 1 alembic head, found {head_count}.\nOutput:\n{combined}"
        )

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
