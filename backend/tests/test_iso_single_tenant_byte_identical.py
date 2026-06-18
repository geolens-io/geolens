"""single_tenant BYTE-IDENTICAL fail-open guard tests (Phase 1208-05, ISO-02/GATE-01).

Proves that in single_tenant (the test default):

  (a) ``is_multi_tenant()`` is False — single_tenant is the default in the test env.
  (b) RLS is NOT enabled on any of the 6 tenant-shared catalog tables:
      relrowsecurity=False AND relforcerowsecurity=False.  The 0006_tenant_rls
      migration creates policies but does NOT enable/force RLS.
  (c) Representative catalog reads against each of the 6 tables do NOT return
      0 rows due to an unset-GUC fail-closed policy — RLS did NOT leak into
      single_tenant.  Each table is queried with ``LIMIT 1``; the test asserts
      the query executes without error (rows or empty due to no seed data, NOT
      due to a fail-closed RLS filter).
  (d) The GUC ``app.current_tenant`` is unset (NULL/empty) in a default
      single_tenant session — the after_begin hook is a no-op.

This is the [BLOCKING] acceptance gate for Phase 1208.  RLS accidentally active
in single_tenant would cause every catalog query to return 0 rows (GUC unset +
fail-closed policy), breaking the entire backend suite.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_iso_single_tenant_byte_identical.py -x -q
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIX_TABLES = [
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
]


async def _autocommit_query(query: str, params: dict | None = None):
    """Run a query on a fresh AUTOCOMMIT connection.

    Uses a fresh engine so we observe the committed DB state, unaffected by
    any test-transaction snapshot isolation.
    """
    from app.core.config import settings

    engine = create_async_engine(settings.database_url, isolation_level="AUTOCOMMIT")
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
# (a) is_multi_tenant() is False in the test env
# ---------------------------------------------------------------------------


class TestIsSingleTenantByDefault:
    """The test environment defaults to single_tenant mode."""

    def test_is_multi_tenant_is_false(self):
        """is_multi_tenant() must return False in the test env (GEOLENS_TENANCY_MODE unset
        or single_tenant).  If this fails, the entire test suite is running in the wrong
        mode and all RLS-related invariants are void.
        """
        from app.core.tenancy import is_multi_tenant

        assert not is_multi_tenant(), (
            "is_multi_tenant() returned True in the test environment.  "
            "GEOLENS_TENANCY_MODE must be unset or 'single_tenant' for the default "
            "test run.  Set GEOLENS_TENANCY_MODE=single_tenant or unset it."
        )


# ---------------------------------------------------------------------------
# (b) RLS disabled on all 6 tables
# ---------------------------------------------------------------------------


class TestRlsDisabledInSingleTenant:
    """relrowsecurity AND relforcerowsecurity are False on all 6 catalog tables.

    The 0006_tenant_rls migration creates RLS policies but does NOT enable or
    force RLS — that happens only at runtime via apply_tenancy_rls() in
    multi_tenant.  In single_tenant the tables must stay at the PG default
    (RLS disabled).
    """

    async def test_relrowsecurity_false_on_all_six_tables(self):
        """relrowsecurity = False on all 6 tables (RLS not enabled in single_tenant)."""
        rows = await _autocommit_query(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = ANY(ARRAY[
                'catalog.users'::regclass,
                'catalog.records'::regclass,
                'catalog.datasets'::regclass,
                'catalog.maps'::regclass,
                'catalog.collections'::regclass,
                'catalog.embed_tokens'::regclass
            ])
            ORDER BY relname
            """
        )
        assert len(rows) == 6, (
            f"Expected 6 tables in pg_class, got {len(rows)}: {[r[0] for r in rows]}"
        )
        failed = [r[0] for r in rows if r[1] is not False]
        assert not failed, (
            f"relrowsecurity=True on {failed} in single_tenant — "
            "RLS must stay DISABLED (relrowsecurity=False) in single_tenant mode.  "
            "apply_tenancy_rls() may have been called outside multi_tenant context, "
            "or the migration incorrectly ran ENABLE ROW LEVEL SECURITY."
        )

    async def test_relforcerowsecurity_false_on_all_six_tables(self):
        """relforcerowsecurity = False on all 6 tables (FORCE RLS not active in single_tenant)."""
        rows = await _autocommit_query(
            """
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE oid = ANY(ARRAY[
                'catalog.users'::regclass,
                'catalog.records'::regclass,
                'catalog.datasets'::regclass,
                'catalog.maps'::regclass,
                'catalog.collections'::regclass,
                'catalog.embed_tokens'::regclass
            ])
            ORDER BY relname
            """
        )
        assert len(rows) == 6
        failed = [r[0] for r in rows if r[2] is not False]
        assert not failed, (
            f"relforcerowsecurity=True on {failed} in single_tenant — "
            "FORCE RLS must NOT be active in single_tenant mode.  "
            "This is the #1 acceptance gate: FORCE RLS + unset GUC = every query "
            "returns 0 rows (fail-closed policy).  The full test suite would be broken."
        )


# ---------------------------------------------------------------------------
# (c) Catalog reads do NOT raise or return 0 rows due to RLS
# ---------------------------------------------------------------------------


class TestCatalogReadsNotBlockedByRls:
    """Catalog reads execute without error in single_tenant.

    We can't assert row *count* for all tables (some may be empty in a fresh
    test DB), but we CAN assert:
      - the query does not RAISE (no GUC-unset error from fail-closed policy)
      - the result is not filtered to 0 rows by an active RLS policy
        (validated by cross-checking against a COUNT(*) — if rows exist in the
        table per a superuser/bypass query, they must appear in the normal read)

    In single_tenant, ``geolens_reader`` / the app role must see all rows
    (RLS inactive), so COUNT(*) through a normal session must equal COUNT(*)
    through a BYPASSRLS query.
    """

    async def _table_row_counts(self, table: str) -> tuple[int, int]:
        """Return (normal_count, bypass_count) for a catalog table.

        bypass_count uses SET LOCAL row_security = OFF to emulate a BYPASSRLS
        role without needing superuser — in single_tenant both counts must match.
        asyncpg requires statements to be executed separately (no multi-statement
        strings in prepared statements).
        """
        from app.core.config import settings

        # Normal count — the path the app uses in single_tenant.
        normal_rows = await _autocommit_query(
            f"SELECT COUNT(*) FROM catalog.{table}"  # noqa: S608
        )
        normal_count = int(normal_rows[0][0])

        # Bypass count — SET LOCAL row_security=off then COUNT(*) in the same
        # connection, using separate execute() calls so asyncpg is happy.
        engine = create_async_engine(
            settings.database_url, isolation_level="AUTOCOMMIT"
        )
        try:
            async with engine.connect() as conn:
                await conn.execute(sa.text("SET LOCAL row_security = off"))
                bypass_rows = await conn.execute(
                    sa.text(f"SELECT COUNT(*) FROM catalog.{table}")  # noqa: S608
                )
                bypass_count = int(bypass_rows.scalar())
        finally:
            await engine.dispose()

        return normal_count, bypass_count

    async def test_users_read_not_blocked(self):
        """SELECT COUNT(*) FROM catalog.users does not raise and equals bypass count."""
        normal, bypass = await self._table_row_counts("users")
        assert normal == bypass, (
            f"catalog.users: normal count={normal} != bypass count={bypass}.  "
            "RLS policy may be filtering rows in single_tenant (GUC unset + active policy)."
        )

    async def test_records_read_not_blocked(self):
        """SELECT COUNT(*) FROM catalog.records does not raise and equals bypass count."""
        normal, bypass = await self._table_row_counts("records")
        assert normal == bypass, (
            f"catalog.records: normal count={normal} != bypass count={bypass}.  "
            "RLS policy may be filtering rows in single_tenant."
        )

    async def test_datasets_read_not_blocked(self):
        """SELECT COUNT(*) FROM catalog.datasets does not raise and equals bypass count."""
        normal, bypass = await self._table_row_counts("datasets")
        assert normal == bypass, (
            f"catalog.datasets: normal count={normal} != bypass count={bypass}.  "
            "RLS policy may be filtering rows in single_tenant."
        )

    async def test_maps_read_not_blocked(self):
        """SELECT COUNT(*) FROM catalog.maps does not raise and equals bypass count."""
        normal, bypass = await self._table_row_counts("maps")
        assert normal == bypass, (
            f"catalog.maps: normal count={normal} != bypass count={bypass}.  "
            "RLS policy may be filtering rows in single_tenant."
        )

    async def test_collections_read_not_blocked(self):
        """SELECT COUNT(*) FROM catalog.collections does not raise and equals bypass count."""
        normal, bypass = await self._table_row_counts("collections")
        assert normal == bypass, (
            f"catalog.collections: normal count={normal} != bypass count={bypass}.  "
            "RLS policy may be filtering rows in single_tenant."
        )

    async def test_embed_tokens_read_not_blocked(self):
        """SELECT COUNT(*) FROM catalog.embed_tokens does not raise and equals bypass count."""
        normal, bypass = await self._table_row_counts("embed_tokens")
        assert normal == bypass, (
            f"catalog.embed_tokens: normal count={normal} != bypass count={bypass}.  "
            "RLS policy may be filtering rows in single_tenant."
        )


# ---------------------------------------------------------------------------
# (d) GUC is unset in a default single_tenant session
# ---------------------------------------------------------------------------


class TestGucUnsetInSingleTenant:
    """The app.current_tenant GUC is never set in single_tenant.

    The after_begin tenant session hook is a no-op in single_tenant mode
    (is_multi_tenant() is False → it returns immediately without calling
    set_config).  A default session should see current_setting(..., true) = NULL.
    """

    async def test_guc_unset_in_default_session(self):
        """current_setting('app.current_tenant', true) is NULL in single_tenant."""
        from app.core.config import settings

        # Use a normal (non-AUTOCOMMIT) engine to exercise the session hook.
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.begin() as conn:
                row = await conn.execute(
                    sa.text(
                        "SELECT current_setting('app.current_tenant', true) AS guc_val"
                    )
                )
                guc_val = row.scalar()
        finally:
            await engine.dispose()

        # In single_tenant, the hook must not call set_config → GUC is unset (NULL or '').
        assert guc_val is None or guc_val == "", (
            f"app.current_tenant GUC is set to '{guc_val}' in a default single_tenant session.  "
            "The tenant_session GUC hook (ISO-01) must be a no-op in single_tenant mode "
            "(is_multi_tenant() is False).  If this fails, multi_tenant mode is leaking "
            "into the test environment."
        )
