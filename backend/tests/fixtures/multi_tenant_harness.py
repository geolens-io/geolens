"""Reusable multi_tenant test harness (ISO-03, ISO-04, Phase 1208-03).

Provides a ``multi_tenant_rls`` pytest fixture (and a matching
``MultiTenantContext`` dataclass) that scopes RLS enablement to a single test:

    enable FORCE RLS → seed tenant_a + tenant_b → yield → disable RLS (try/finally)

The teardown is **unconditional** — it runs even when the test body raises, so
the shared per-worker test DB is always left in single_tenant / RLS-disabled
state for subsequent tests.

Usage
-----
::

    @pytest.mark.rls
    async def test_isolation(multi_tenant_rls):
        ctx = multi_tenant_rls
        async with ctx.tenant_session(ctx.tenant_a) as session:
            rows = (await session.execute(select(User))).scalars().all()
            # Only tenant_a rows visible

Reused by Plan 04 (GATE-01 cross-tenant gate) and Phase 1209.

Design notes
------------
- ``GEOLENS_TENANCY_MODE=multi_tenant`` is set via ``monkeypatch.setenv`` +
  config reload so ``is_multi_tenant()`` returns True for the test body.
- ``apply_tenancy_rls(conn)`` enables + FORCEs RLS on the full boundary over an
  AUTOCOMMIT connection (DDL visible immediately to subsequent connections).
- Two tenant UUIDs (tenant_a, tenant_b) are seeded into ``catalog.users`` so
  the leak-lint and gate tests have real rows to check against.
- Teardown disables + un-FORCEs RLS via AUTOCOMMIT DDL, deletes the seeded
  rows, and reloads settings to single_tenant — making this fixture safe to
  interleave with single_tenant tests on the same per-worker DB.

Marker
------
Tests that use this fixture must be marked with ``@pytest.mark.rls``.
Document the marker in ``pyproject.toml [tool.pytest.ini_options] markers``.
"""

from __future__ import annotations

import importlib
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncGenerator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RLS_TABLES = [
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
    "oauth_accounts",
    "audit_logs",
    "ingest_jobs",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _reload_settings():
    """Force pydantic-settings to re-read os.environ for Settings."""
    import app.core.config as cfg_mod
    import app.core.tenancy as ten_mod

    cfg_mod.settings = cfg_mod.Settings()  # type: ignore[attr-defined]
    importlib.reload(ten_mod)
    return cfg_mod.settings


async def _enable_rls_autocommit(db_url: str) -> None:
    """Enable + FORCE RLS on the full boundary via an AUTOCOMMIT connection.

    Also grants ``USAGE`` on the ``catalog`` schema to ``geolens_reader`` so
    the leak-lint probe can issue ``SET LOCAL ROLE geolens_reader`` and run
    queries.  The grant is idempotent (GRANT is no-op if already granted).
    ``geolens_reader`` has no ``BYPASSRLS`` and is not a superuser, so it is
    subject to RLS — making it the correct role for the fail-closed probe.
    """
    from app.core.db.rls import apply_tenancy_rls

    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            # Grant schema USAGE to geolens_reader for the leak-lint probe.
            # The catalog schema's default ACL only covers the superuser role;
            # geolens_reader needs explicit USAGE to run any query against
            # catalog tables (schema access check happens before RLS).
            await conn.execute(
                sa.text("GRANT USAGE ON SCHEMA catalog TO geolens_reader")
            )
            # Grant table-level SELECT on the RLS-protected tables so the leak-lint
            # probe can attempt reads as geolens_reader — RLS then filters rows by the
            # tenant GUC (without SELECT you get "permission denied for table", not the
            # RLS-scoped result the test asserts). On the per-worker TEST DB conftest
            # only grants geolens_reader on the `data` schema, not `catalog`; on CI's
            # `postgres` it's also absent — so the harness must grant it itself.
            for table in _RLS_TABLES:
                await conn.execute(
                    sa.text(f"GRANT SELECT ON catalog.{table} TO geolens_reader")
                )
            await apply_tenancy_rls(conn)
    finally:
        await engine.dispose()


async def _disable_rls_autocommit(db_url: str) -> None:
    """Disable + un-FORCE RLS on the full boundary via an AUTOCOMMIT connection.

    This is the load-bearing teardown — it must run even on test failure.
    Also revokes the ``catalog`` schema USAGE that _enable_rls_autocommit
    granted to ``geolens_reader`` so the test DB is clean after the harness.
    """
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            for table in _RLS_TABLES:
                await conn.execute(
                    sa.text(f"ALTER TABLE catalog.{table} NO FORCE ROW LEVEL SECURITY")
                )
                await conn.execute(
                    sa.text(f"ALTER TABLE catalog.{table} DISABLE ROW LEVEL SECURITY")
                )
            # Revoke the table SELECT + USAGE grants added in setup — restore state.
            for table in _RLS_TABLES:
                await conn.execute(
                    sa.text(f"REVOKE SELECT ON catalog.{table} FROM geolens_reader")
                )
            await conn.execute(
                sa.text("REVOKE USAGE ON SCHEMA catalog FROM geolens_reader")
            )
    finally:
        await engine.dispose()


async def _seed_users(
    db_url: str,
    tenant_a: str,
    tenant_b: str,
    suffix: str,
) -> tuple[str, str]:
    """Insert one user row per tenant into catalog.users (RLS must be OFF).

    Returns (user_a_id, user_b_id) — the inserted row UUIDs.
    We use AUTOCOMMIT so the rows are committed before we re-enable RLS.
    """
    user_a_id = str(uuid.uuid4())
    user_b_id = str(uuid.uuid4())

    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            for uid, tid, uname in [
                (user_a_id, tenant_a, f"rls_harness_a_{suffix}"),
                (user_b_id, tenant_b, f"rls_harness_b_{suffix}"),
            ]:
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.users "
                        "(id, username, email, status, is_active, token_version, "
                        " auth_provider, tenant_id, created_at, updated_at) "
                        "VALUES (:id, :username, :email, 'active', true, 1, "
                        "        'local', :tenant_id, now(), now())"
                    ),
                    {
                        "id": uid,
                        "username": uname,
                        "email": f"{uname}@rls.test",
                        "tenant_id": tid,
                    },
                )
    finally:
        await engine.dispose()

    return user_a_id, user_b_id


async def _delete_seeded_users(
    db_url: str,
    user_a_id: str,
    user_b_id: str,
) -> None:
    """Delete the seeded users rows by id (unconditional teardown, AUTOCOMMIT).

    Runs AFTER RLS is disabled so the DELETE is not blocked by the policy.
    """
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                sa.text("DELETE FROM catalog.users WHERE id = ANY(:ids)"),
                {"ids": [user_a_id, user_b_id]},
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class MultiTenantContext:
    """Exposes tenant IDs and a scoped session factory to test bodies.

    Attributes
    ----------
    tenant_a, tenant_b:
        UUID strings for the two seeded tenants.
    user_a_id, user_b_id:
        The primary keys of the seeded catalog.users rows.
    db_url:
        The database URL used by this harness (same as settings.database_url
        at fixture time, resolved against the test DB).

    Methods
    -------
    tenant_session(tenant_id):
        Async context manager that opens a session with current_tenant_var
        set to *tenant_id*, so the engine begin-hook issues the GUC and RLS
        filters to that tenant.
    """

    tenant_a: str
    tenant_b: str
    user_a_id: str
    user_b_id: str
    db_url: str
    _session_factory: async_sessionmaker = field(repr=False)

    @asynccontextmanager
    async def tenant_session(
        self, tenant_id: str
    ) -> AsyncGenerator[AsyncSession, None]:
        """Open a session with current_tenant_var set to *tenant_id*.

        The engine begin-hook (installed by install_tenant_session_hook) will
        issue ``set_config('app.current_tenant', tenant_id, true)`` on
        transaction start, scoping all queries to *tenant_id* under RLS.

        The session also issues ``SET LOCAL ROLE geolens_reader`` after BEGIN so
        the connection is subject to FORCE ROW LEVEL SECURITY.  The test DB
        connects as ``geolens`` (superuser, BYPASSRLS=True) which always bypasses
        RLS — we must switch to a non-privileged role within the transaction to
        make the RLS policy visible.  ``geolens_reader`` has no BYPASSRLS and is
        not a superuser, so the policy is enforced.  The ``catalog`` schema USAGE
        grant to ``geolens_reader`` is added by the harness setup and revoked in
        teardown.

        The var is reset on exit (including on exception) via ContextVar.reset().
        """
        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(tenant_id)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    # SET LOCAL ROLE to non-privileged role so FORCE RLS applies.
                    # This must happen inside the transaction (LOCAL = txn-scoped).
                    # The GUC set by the begin-hook survives the role switch in PG.
                    await session.execute(sa.text("SET LOCAL ROLE geolens_reader"))
                    yield session
        finally:
            current_tenant_var.reset(token)


# ---------------------------------------------------------------------------
# Pytest fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def multi_tenant_rls(monkeypatch) -> AsyncGenerator[MultiTenantContext, None]:
    """Scoped multi_tenant RLS harness.

    Sequence:
      1. Set GEOLENS_TENANCY_MODE=multi_tenant + reload config so
         is_multi_tenant() returns True.
      2. Seed two user rows (one per tenant) BEFORE enabling RLS, on an
         AUTOCOMMIT connection so the rows are committed immediately.
      3. Enable + FORCE RLS on the full boundary (AUTOCOMMIT DDL).
      4. Build a session factory with the tenant GUC hook installed and
         yield a MultiTenantContext to the test body.
      5. In try/finally teardown:
         a. Disable + un-FORCE RLS on the full boundary (AUTOCOMMIT DDL).
         b. Delete the seeded user rows (AUTOCOMMIT, after RLS is off).
         c. Restore GEOLENS_TENANCY_MODE to single_tenant + reload config.

    The try/finally ensures teardown runs even when the test body raises, so
    the shared per-worker DB is always returned to single_tenant/RLS-disabled
    state for subsequent tests (T-1208-09).

    Mark tests that use this fixture with ``@pytest.mark.rls``.
    """
    from app.core.config import settings
    from app.core.db.tenant_session import install_tenant_session_hook

    # Step 1: flip to multi_tenant.
    monkeypatch.setenv("GEOLENS_TENANCY_MODE", "multi_tenant")
    _reload_settings()

    # Operate on the per-worker TEST database (conftest provisions catalog/data +
    # geolens_reader + per-tenant schemas there) — NOT the main app DB, which is
    # `postgres` on CI and lacks the test provisioning, causing "permission denied"
    # / missing-schema failures. Mirrors the dp02 `_get_test_db_url()` pattern.
    db_url = settings.test_database_url
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    suffix = uuid.uuid4().hex[:8]

    # Step 2: seed users BEFORE enabling RLS (AUTOCOMMIT, no policy filter).
    user_a_id, user_b_id = await _seed_users(db_url, tenant_a, tenant_b, suffix)

    # Step 3: enable + FORCE RLS.
    await _enable_rls_autocommit(db_url)

    # Step 4: build a session factory with the GUC hook installed.
    engine = create_async_engine(db_url, poolclass=NullPool)
    install_tenant_session_hook(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    ctx = MultiTenantContext(
        tenant_a=tenant_a,
        tenant_b=tenant_b,
        user_a_id=user_a_id,
        user_b_id=user_b_id,
        db_url=db_url,
        _session_factory=session_factory,
    )

    try:
        yield ctx
    finally:
        # Step 5a: disable RLS first (AUTOCOMMIT DDL).
        await _disable_rls_autocommit(db_url)

        # Step 5b: delete seeded rows AFTER RLS is off.
        await _delete_seeded_users(db_url, user_a_id, user_b_id)

        # Step 5c: restore single_tenant mode + reload config.
        monkeypatch.setenv("GEOLENS_TENANCY_MODE", "single_tenant")
        _reload_settings()

        # Dispose the harness engine.
        await engine.dispose()
