"""Regression tests for Phase 1207 dormant tenancy schema (TSEAM-01, TSEAM-02).

Verifies:
  A: Every tenant-shared control-plane table has a nullable tenant_id column.
  B: organizations, tenants, org_memberships tables exist in catalog schema.
  C: single_tenant global uniqueness — duplicate username with tenant_id IS NULL raises.
  D: multi_tenant per-tenant uniqueness — same username in DIFFERENT tenants succeeds;
     same username in SAME tenant raises.

Requires:
  - A running Postgres database with alembic migrations applied (alembic upgrade head).
  - The test DB is the live database (POSTGRES_DB from .env.test).

These tests are NOT marked @pytest.mark.asyncio; they are owned by AnyIO
(anyio_mode = "auto" in pyproject.toml) and run via the test_db_session fixture.
See the note in test_regenerate_vrt_integration.py for the event-loop rationale.
"""

import uuid

import pytest
import sqlalchemy.exc
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Shared tables under test
# ---------------------------------------------------------------------------

_SHARED_TABLES = [
    "users",
    "records",
    "datasets",
    "maps",
    "collections",
    "embed_tokens",
]

_TENANT_TABLES = [
    "organizations",
    "tenants",
    "org_memberships",
]


# ---------------------------------------------------------------------------
# Test A: every shared table has a nullable tenant_id column
# ---------------------------------------------------------------------------


class TestTenantIdColumns:
    """TSEAM-01: tenant_id is present on all tenant-shared control-plane tables."""

    async def test_tenant_id_exists_and_nullable(self, client, test_db_session):
        """Each of the six shared tables has tenant_id (nullable) in catalog."""
        result = await test_db_session.execute(
            text(
                """
                SELECT table_name, column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'catalog'
                  AND column_name = 'tenant_id'
                  AND table_name = ANY(:tables)
                ORDER BY table_name
                """
            ),
            {"tables": _SHARED_TABLES},
        )
        rows = {row.table_name: row.is_nullable for row in result.mappings()}

        missing = [t for t in _SHARED_TABLES if t not in rows]
        assert not missing, (
            f"tenant_id column missing from tables: {missing}. "
            "Run 'alembic upgrade head' against the test DB."
        )

        not_nullable = [t for t, nullable in rows.items() if nullable != "YES"]
        assert not not_nullable, (
            f"tenant_id must be nullable (dormant) on: {not_nullable}"
        )


# ---------------------------------------------------------------------------
# Test B: tenancy tables exist
# ---------------------------------------------------------------------------


class TestTenancyTablesExist:
    """TSEAM-01: organizations, tenants, org_memberships exist in catalog schema."""

    async def test_tenancy_tables_present(self, client, test_db_session):
        """All three tenancy tables are present in catalog schema."""
        result = await test_db_session.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'catalog'
                  AND table_name = ANY(:tables)
                """
            ),
            {"tables": _TENANT_TABLES},
        )
        found = {row.table_name for row in result.mappings()}
        missing = set(_TENANT_TABLES) - found
        assert not missing, (
            f"Tenancy tables not found in catalog schema: {missing}. "
            "Run 'alembic upgrade head' against the test DB."
        )


# ---------------------------------------------------------------------------
# Test C: single_tenant global uniqueness (tenant_id IS NULL)
# ---------------------------------------------------------------------------


class TestSingleTenantGlobalUniqueness:
    """TSEAM-02: uq_users_username_global enforces global uniqueness when tenant_id IS NULL."""

    async def test_duplicate_username_null_tenant_raises(self, client, test_db_session):
        """Two users with the same username and tenant_id IS NULL must fail.

        This proves single_tenant byte-identical global uniqueness is preserved
        by the uq_users_username_global partial index (UNIQUE(username) WHERE
        tenant_id IS NULL).
        """
        unique_suffix = uuid.uuid4().hex[:8]
        username = f"tseam02_test_{unique_suffix}"

        # Insert first user — must succeed.
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.users "
                "(username, email, status, is_active, token_version, auth_provider, "
                " created_at, updated_at) "
                "VALUES (:username, :email, 'active', true, 1, 'local', now(), now())"
            ),
            {
                "username": username,
                "email": f"{unique_suffix}_1@tseam02.test",
            },
        )
        await test_db_session.flush()

        # Second user with same username and tenant_id IS NULL — must raise unique violation.
        with pytest.raises(
            sqlalchemy.exc.IntegrityError, match="uq_users_username_global"
        ):
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.users "
                    "(username, email, status, is_active, token_version, auth_provider, "
                    " created_at, updated_at) "
                    "VALUES (:username, :email, 'active', true, 1, 'local', now(), now())"
                ),
                {
                    "username": username,
                    "email": f"{unique_suffix}_2@tseam02.test",
                },
            )
            await test_db_session.flush()

        # Roll back to keep the test session clean for subsequent tests.
        await test_db_session.rollback()


# ---------------------------------------------------------------------------
# Test D: multi_tenant per-tenant uniqueness
# ---------------------------------------------------------------------------


class TestMultiTenantPerTenantUniqueness:
    """TSEAM-02: per-tenant partial indexes allow cross-tenant sharing, deny intra-tenant dupes."""

    async def test_same_username_different_tenants_succeeds(
        self, client, test_db_session
    ):
        """Two users with the same username in DIFFERENT tenants must succeed.

        This proves the uq_users_username_tenant partial index
        (UNIQUE(tenant_id, username) WHERE tenant_id IS NOT NULL) allows
        cross-tenant sharing.
        """
        unique_suffix = uuid.uuid4().hex[:8]
        username = f"tseam02_mt_{unique_suffix}"
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()

        # First user in tenant A.
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.users "
                "(username, email, tenant_id, status, is_active, token_version, "
                " auth_provider, created_at, updated_at) "
                "VALUES (:username, :email, :tenant_id, 'active', true, 1, "
                "        'local', now(), now())"
            ),
            {
                "username": username,
                "email": f"{unique_suffix}_a@tseam02.test",
                "tenant_id": str(tenant_a),
            },
        )
        # Second user in tenant B — same username, different tenant. Must succeed.
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.users "
                "(username, email, tenant_id, status, is_active, token_version, "
                " auth_provider, created_at, updated_at) "
                "VALUES (:username, :email, :tenant_id, 'active', true, 1, "
                "        'local', now(), now())"
            ),
            {
                "username": username,
                "email": f"{unique_suffix}_b@tseam02.test",
                "tenant_id": str(tenant_b),
            },
        )
        await test_db_session.flush()
        # Clean up.
        await test_db_session.rollback()

    async def test_same_username_same_tenant_raises(self, client, test_db_session):
        """Two users with the same username in the SAME tenant must fail.

        This proves uq_users_username_tenant enforces intra-tenant uniqueness
        when tenant_id IS NOT NULL.
        """
        unique_suffix = uuid.uuid4().hex[:8]
        username = f"tseam02_st_{unique_suffix}"
        tenant_id = uuid.uuid4()

        # First user in the tenant — must succeed.
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.users "
                "(username, email, tenant_id, status, is_active, token_version, "
                " auth_provider, created_at, updated_at) "
                "VALUES (:username, :email, :tenant_id, 'active', true, 1, "
                "        'local', now(), now())"
            ),
            {
                "username": username,
                "email": f"{unique_suffix}_1@tseam02.test",
                "tenant_id": str(tenant_id),
            },
        )
        await test_db_session.flush()

        # Second user in the SAME tenant, same username — must raise.
        with pytest.raises(
            sqlalchemy.exc.IntegrityError, match="uq_users_username_tenant"
        ):
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.users "
                    "(username, email, tenant_id, status, is_active, token_version, "
                    " auth_provider, created_at, updated_at) "
                    "VALUES (:username, :email, :tenant_id, 'active', true, 1, "
                    "        'local', now(), now())"
                ),
                {
                    "username": username,
                    "email": f"{unique_suffix}_2@tseam02.test",
                    "tenant_id": str(tenant_id),
                },
            )
            await test_db_session.flush()

        await test_db_session.rollback()
