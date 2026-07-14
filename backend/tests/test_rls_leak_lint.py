"""ISO-04 leak-lint: unscoped multi_tenant query fails closed (Phase 1208-03).

The chokepoint proof: in multi_tenant mode with FORCE RLS active, any raw
query against a tenant-shared table that does NOT set the ``app.current_tenant``
GUC must fail closed.

Why ``SET LOCAL ROLE geolens_reader``
--------------------------------------
The test DB connects as ``geolens`` which is a PostgreSQL superuser
(``rolsuper=True, rolbypassrls=True``).  PostgreSQL always exempts superusers
from RLS — even ``FORCE ROW LEVEL SECURITY`` cannot override superuser
privilege.  The **real** enforcement target is non-privileged application
roles like ``geolens_reader`` (rolsuper=False, rolbypassrls=False), which are
subject to FORCE RLS.

The leak-lint therefore uses ``SET LOCAL ROLE geolens_reader`` inside a
transaction to simulate the non-privileged app role, proving the fail-closed
policy stops an unscoped query.  The harness grants ``catalog`` schema USAGE
to ``geolens_reader`` for the duration of the test and revokes it on teardown.

Fail-closed behaviour
---------------------
When the GUC is unset and ``current_setting('app.current_tenant'::text)``
is evaluated by the RLS policy (without ``missing_ok=true``), Postgres raises
``UndefinedObjectError: unrecognized configuration parameter "app.current_tenant"``.
The caller sees a ``ProgrammingError`` — the query is blocked.

Test breakdown
--------------
A — Unscoped query (GUC never set) via ``geolens_reader`` with both tenant_a
    and tenant_b rows seeded: RAISES ProgrammingError — fail-closed proof.
    This is the DB-level backstop for the ~535 raw .execute() sites.

B — Scoped query (GUC set to tenant_a) via ``geolens_reader``: returns ONLY
    tenant_a's row (not tenant_b's). Proves the scoped path works.

C — Scoped to tenant_b: returns only tenant_b's row (symmetric proof).

D — No-pollution check: after harness teardown, a plain single_tenant query
    against catalog.users sees ALL rows (RLS disabled; no GUC required).

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_rls_leak_lint.py -x -q
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


# ---------------------------------------------------------------------------
# Role used for the fail-closed probe
# ---------------------------------------------------------------------------

# geolens_reader is a non-superuser, non-BYPASSRLS role that is subject to
# FORCE ROW LEVEL SECURITY.  The connecting role (geolens) is a superuser and
# always bypasses RLS, so probes must use SET LOCAL ROLE to simulate the
# non-privileged app role.
_PROBE_ROLE = "geolens_reader"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _unscoped_count_as_reader(db_url: str, row_id: str) -> int:
    """Count catalog.users rows for a specific id WITHOUT setting the GUC.

    Uses ``SET LOCAL ROLE geolens_reader`` so the RLS policy is enforced.
    Expects ProgrammingError (policy raises on unset GUC) — callers catch it.
    """
    engine = create_async_engine(db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(sa.text(f"SET LOCAL ROLE {_PROBE_ROLE}"))
                # Do NOT set the GUC — this is the unscoped fail-closed probe.
                result = await conn.execute(
                    sa.text("SELECT count(*) FROM catalog.users WHERE id = :id"),
                    {"id": row_id},
                )
                return int(result.scalar_one())
    finally:
        await engine.dispose()


async def _scoped_count(ctx, tenant_id: str, row_id: str) -> int:
    """Count catalog.users rows for a specific id WITH the tenant GUC set.

    Uses the harness ``tenant_session()`` helper which sets current_tenant_var,
    triggering the engine begin-hook to issue set_config on transaction start.
    The tenant GUC scopes the query to *tenant_id* under RLS.
    """
    async with ctx.tenant_session(tenant_id) as session:
        result = await session.execute(
            sa.text("SELECT count(*) FROM catalog.users WHERE id = :id"),
            {"id": row_id},
        )
        return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Test A: unscoped query fails closed (the chokepoint proof)
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestUnscopedQueryFailsClosed:
    """An unscoped query in multi_tenant + RLS enabled must fail closed.

    With ``SET LOCAL ROLE geolens_reader`` (non-superuser, no BYPASSRLS) and
    no GUC set, the RLS policy calls ``current_setting('app.current_tenant'::text)``
    which raises ``UndefinedObjectError`` — the query cannot return any rows.

    This is the DB-level backstop for the ~535 raw .execute() sites.
    """

    async def test_unscoped_query_raises_for_tenant_a_row(self, multi_tenant_rls):
        """Without the GUC set (as geolens_reader), the query raises — fail-closed."""
        ctx = multi_tenant_rls
        # The query should raise ProgrammingError (UndefinedObjectError from Postgres).
        # We accept both: raise OR 0 rows — both satisfy fail-closed.
        raised = False
        count = -1
        try:
            count = await _unscoped_count_as_reader(ctx.db_url, ctx.user_a_id)
        except Exception as e:
            raised = True
            # Confirm it's the expected RLS error (not an unrelated DB error).
            err_str = str(e)
            assert (
                "app.current_tenant" in err_str
                or "UndefinedObjectError" in err_str
                or "unrecognized" in err_str
            ), f"ISO-04 FAIL: Unexpected error (expected GUC/RLS error):\n{err_str}"

        assert raised or count == 0, (
            f"ISO-04 FAIL: Unscoped multi_tenant query (as {_PROBE_ROLE}) for tenant_a "
            f"did NOT fail closed.\n"
            f"  count={count}, raised={raised}\n"
            f"  user_a_id={ctx.user_a_id!r}, tenant_a={ctx.tenant_a!r}\n"
            f"  A raw .execute() without SET LOCAL can leak cross-tenant data.\n"
            f"  Expected: ProgrammingError (UndefinedObjectError) OR 0 rows."
        )

    async def test_unscoped_query_raises_for_tenant_b_row(self, multi_tenant_rls):
        """Without the GUC set (as geolens_reader), tenant_b's row is also inaccessible."""
        ctx = multi_tenant_rls
        raised = False
        count = -1
        try:
            count = await _unscoped_count_as_reader(ctx.db_url, ctx.user_b_id)
        except Exception:
            raised = True

        assert raised or count == 0, (
            f"ISO-04 FAIL: Unscoped multi_tenant query (as {_PROBE_ROLE}) for tenant_b "
            f"did NOT fail closed.\n"
            f"  count={count}, raised={raised}\n"
            f"  user_b_id={ctx.user_b_id!r}, tenant_b={ctx.tenant_b!r}"
        )

    async def test_no_cross_tenant_rows_in_broad_unscoped_query(self, multi_tenant_rls):
        """Broad SELECT * without GUC (as geolens_reader) leaks no rows from either tenant."""
        ctx = multi_tenant_rls
        engine = create_async_engine(ctx.db_url, poolclass=NullPool)
        rows = []
        raised = False
        try:
            async with engine.connect() as conn:
                async with conn.begin():
                    await conn.execute(sa.text(f"SET LOCAL ROLE {_PROBE_ROLE}"))
                    # No GUC set — must fail closed.
                    result = await conn.execute(
                        sa.text("SELECT id FROM catalog.users WHERE id = ANY(:ids)"),
                        {"ids": [ctx.user_a_id, ctx.user_b_id]},
                    )
                    rows = result.fetchall()
        except Exception:
            raised = True
        finally:
            await engine.dispose()

        assert raised or len(rows) == 0, (
            f"ISO-04 FAIL: Broad unscoped query (as {_PROBE_ROLE}) leaked "
            f"{len(rows)} cross-tenant row(s).\n"
            f"  Found ids: {[r[0] for r in rows]}\n"
            f"  Expected: ProgrammingError OR 0 rows."
        )


# ---------------------------------------------------------------------------
# Test B: scoped to tenant_a sees only tenant_a
# ---------------------------------------------------------------------------


@pytest.mark.rls
class TestScopedQuerySeesOnlyOwnTenant:
    """A scoped query (via harness tenant_session) sees exactly its tenant's rows."""

    async def test_tenant_a_sees_own_row(self, multi_tenant_rls):
        """Scoped to tenant_a: user_a's row is visible."""
        ctx = multi_tenant_rls
        count = await _scoped_count(ctx, ctx.tenant_a, ctx.user_a_id)
        assert count == 1, (
            f"ISO-04: tenant_a scoped query should see its own row.\n"
            f"  count={count}, user_a_id={ctx.user_a_id!r}, tenant_a={ctx.tenant_a!r}"
        )

    async def test_tenant_a_cannot_see_tenant_b_row(self, multi_tenant_rls):
        """Scoped to tenant_a: user_b's row (owned by tenant_b) is invisible."""
        ctx = multi_tenant_rls
        count = await _scoped_count(ctx, ctx.tenant_a, ctx.user_b_id)
        assert count == 0, (
            f"ISO-04 FAIL: tenant_a's scoped query can see tenant_b's row!\n"
            f"  count={count}, user_b_id={ctx.user_b_id!r}, tenant_b={ctx.tenant_b!r}\n"
            f"  Cross-tenant data leak — RLS policy is not enforcing tenant isolation."
        )

    async def test_tenant_b_sees_own_row(self, multi_tenant_rls):
        """Scoped to tenant_b: user_b's row is visible."""
        ctx = multi_tenant_rls
        count = await _scoped_count(ctx, ctx.tenant_b, ctx.user_b_id)
        assert count == 1, (
            f"ISO-04: tenant_b scoped query should see its own row.\n"
            f"  count={count}, user_b_id={ctx.user_b_id!r}, tenant_b={ctx.tenant_b!r}"
        )

    async def test_tenant_b_cannot_see_tenant_a_row(self, multi_tenant_rls):
        """Scoped to tenant_b: user_a's row (owned by tenant_a) is invisible."""
        ctx = multi_tenant_rls
        count = await _scoped_count(ctx, ctx.tenant_b, ctx.user_a_id)
        assert count == 0, (
            f"ISO-04 FAIL: tenant_b's scoped query can see tenant_a's row!\n"
            f"  count={count}, user_a_id={ctx.user_a_id!r}, tenant_a={ctx.tenant_a!r}\n"
            f"  Cross-tenant data leak."
        )


# ---------------------------------------------------------------------------
# Test C (no-pollution): single_tenant after harness teardown sees all rows
# ---------------------------------------------------------------------------


class TestNoPollutionAfterHarnessDisable:
    """After harness teardown (RLS disabled), single_tenant queries see all rows.

    This test does NOT use the multi_tenant_rls fixture — it intentionally runs
    in single_tenant / RLS-disabled mode to prove the harness left the shared
    test DB clean (T-1208-09).

    Seeds its own temporary users (no harness dependency) and asserts they are
    visible without any GUC, then deletes them.
    """

    async def test_single_tenant_rows_visible_without_guc(self):
        """In single_tenant, catalog.users rows are visible without any GUC.

        Uses a fresh engine with NO GUC hook — proves RLS is disabled on the
        shared test DB (no residue from a prior harness test on this worker).
        """
        from app.core.config import settings

        db_url = settings.database_url
        uid_1 = str(uuid.uuid4())
        uid_2 = str(uuid.uuid4())
        suffix = uuid.uuid4().hex[:8]

        # Seed two rows WITHOUT tenant_id (single_tenant global users).
        eng_seed = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with eng_seed.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                for uid, uname in [
                    (uid_1, f"nopoll_1_{suffix}"),
                    (uid_2, f"nopoll_2_{suffix}"),
                ]:
                    await conn.execute(
                        sa.text(
                            "INSERT INTO catalog.users "
                            "(id, username, email, status, is_active, token_version, "
                            " auth_provider, created_at, updated_at) "
                            "VALUES (:id, :username, :email, 'active', true, 1, "
                            "        'local', now(), now())"
                        ),
                        {
                            "id": uid,
                            "username": uname,
                            "email": f"{uname}@nopoll.test",
                        },
                    )
        finally:
            await eng_seed.dispose()

        # Query WITHOUT any GUC — must see both rows in single_tenant.
        eng_query = create_async_engine(db_url, poolclass=NullPool)
        count = 0
        try:
            async with eng_query.connect() as conn:
                result = await conn.execute(
                    sa.text("SELECT count(*) FROM catalog.users WHERE id = ANY(:ids)"),
                    {"ids": [uid_1, uid_2]},
                )
                count = int(result.scalar_one())
        finally:
            await eng_query.dispose()

        # Cleanup seeded rows (AUTOCOMMIT, best-effort).
        eng_cleanup = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with eng_cleanup.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    sa.text("DELETE FROM catalog.users WHERE id = ANY(:ids)"),
                    {"ids": [uid_1, uid_2]},
                )
        finally:
            await eng_cleanup.dispose()

        assert count == 2, (
            f"T-1208-09 FAIL: In single_tenant, expected 2 rows visible without GUC "
            f"but got {count}.\n"
            f"  This indicates RLS is STILL ACTIVE on the shared test DB — the "
            f"multi_tenant harness teardown did not disable RLS (or never ran).\n"
            f"  Check that harness try/finally executes _disable_rls_autocommit()."
        )

    async def test_rls_flags_disabled_in_single_tenant_mode(self):
        """Sanity: FORCE RLS is off on the full boundary after harness tests.

        Runs in the default single_tenant mode (no harness fixture).  Verifies
        that the shared test DB is clean — catches leaked FORCE RLS from a
        prior harness test on the same worker.
        """
        from app.core.config import settings

        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sa.text(
                        """
                        SELECT relname, relrowsecurity, relforcerowsecurity
                        FROM pg_class
                        WHERE oid = ANY(
                            ARRAY[
                                'catalog.users'::regclass,
                                'catalog.records'::regclass,
                                'catalog.datasets'::regclass,
                                'catalog.maps'::regclass,
                                'catalog.collections'::regclass,
                                'catalog.embed_tokens'::regclass,
                                'catalog.oauth_accounts'::regclass,
                                'catalog.audit_logs'::regclass,
                                'catalog.ingest_jobs'::regclass
                            ]
                        )
                        ORDER BY relname
                        """
                    )
                )
                state = rows.fetchall()
        finally:
            await engine.dispose()

        assert len(state) == 9, f"Expected 9 tables in pg_class, got {len(state)}"
        leaked = [f"{r[0]}: rls={r[1]}, force={r[2]}" for r in state if r[1] or r[2]]
        assert not leaked, (
            f"T-1208-09 FAIL: RLS is still active on the test DB after harness tests.\n"
            f"  Tables with RLS on: {leaked}\n"
            f"  The harness try/finally teardown must disable the full RLS boundary.\n"
            f"  Check _disable_rls_autocommit() in multi_tenant_harness.py."
        )
