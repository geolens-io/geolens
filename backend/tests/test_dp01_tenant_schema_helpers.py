"""DP-01: Per-tenant data schema helper unit tests (Phase 1209-01).

Tests
-----
A: tenant_data_schema / tenant_reader_role in single_tenant — always return
   global defaults ('data' / 'geolens_reader') regardless of tenant_id.
B: tenant_data_schema / tenant_reader_role in multi_tenant — return
   per-tenant names derived from the UUID.
C: tenant_data_schema / tenant_reader_role raise ValueError on non-UUID input
   in multi_tenant.
D: apply_tenant_data_schema in single_tenant — hard no-op (conn.execute never
   awaited; schema not created in DB).
E: apply_tenant_data_schema in multi_tenant — creates schema + role (idempotent:
   double-call does not error).
F: Cross-tenant USAGE isolation — geolens_reader_t_{A} has USAGE on data_t_{A}
   but NOT on data_t_{B} (has_schema_privilege false for A on B).
G: tenant_shard_id in single_tenant returns None.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_dp01_tenant_schema_helpers.py -x -q
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# Hard-coded test UUIDs matching init-test-db.sh per-tenant fixture
_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"

_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"
_ROLE_A = "geolens_reader_t_00000000_0000_0000_0000_000000000001"
_ROLE_B = "geolens_reader_t_00000000_0000_0000_0000_000000000002"


async def _get_test_db_url() -> str:
    from app.core.config import settings

    return settings.test_database_url


# ---------------------------------------------------------------------------
# Test A: single_tenant — global defaults, no-op regardless of tenant_id
# ---------------------------------------------------------------------------


class TestHelperNamesInSingleTenant:
    """A: tenant_data_schema / tenant_reader_role always return global defaults."""

    def test_tenant_data_schema_none_single_tenant(self, monkeypatch):
        """tenant_data_schema(None) returns 'data' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_data_schema

        assert tenant_data_schema(None) == "data"

    def test_tenant_data_schema_with_uuid_single_tenant(self, monkeypatch):
        """tenant_data_schema(uuid) still returns 'data' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_data_schema

        assert tenant_data_schema(_TENANT_A) == "data"

    def test_tenant_reader_role_none_single_tenant(self, monkeypatch):
        """tenant_reader_role(None) returns 'geolens_reader' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_reader_role

        assert tenant_reader_role(None) == "geolens_reader"

    def test_tenant_reader_role_with_uuid_single_tenant(self, monkeypatch):
        """tenant_reader_role(uuid) still returns 'geolens_reader' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_reader_role

        assert tenant_reader_role(_TENANT_A) == "geolens_reader"


# ---------------------------------------------------------------------------
# Test B: multi_tenant — per-tenant names derived from UUID
# ---------------------------------------------------------------------------


class TestHelperNamesInMultiTenant:
    """B: tenant_data_schema / tenant_reader_role return per-tenant names."""

    def test_tenant_data_schema_returns_per_tenant_name(self, monkeypatch):
        """tenant_data_schema(uuid) returns data_t_{underscore_uuid} in multi_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db import tenant_schema as mod

        # Force reload to pick up the monkeypatched is_multi_tenant
        import importlib

        importlib.reload(mod)
        from app.core.db.tenant_schema import tenant_data_schema

        assert tenant_data_schema(_TENANT_A) == _SCHEMA_A

    def test_tenant_data_schema_none_fails_closed_in_multi_tenant(self, monkeypatch):
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_data_schema

        with pytest.raises(ValueError, match="tenant_id is required"):
            tenant_data_schema(None)

    def test_tenant_reader_role_returns_per_tenant_name(self, monkeypatch):
        """tenant_reader_role(uuid) returns geolens_reader_t_{uuid} in multi_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_reader_role

        assert tenant_reader_role(_TENANT_A) == _ROLE_A

    def test_tenant_reader_role_none_fails_closed_in_multi_tenant(self, monkeypatch):
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_reader_role

        with pytest.raises(ValueError, match="tenant_id is required"):
            tenant_reader_role(None)

    def test_tenant_writer_role_none_fails_closed_in_multi_tenant(self, monkeypatch):
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_writer_role

        with pytest.raises(ValueError, match="tenant_id is required"):
            tenant_writer_role(None)


# ---------------------------------------------------------------------------
# Test C: ValueError on non-UUID input in multi_tenant
# ---------------------------------------------------------------------------


class TestHelperNamesValueError:
    """C: ValueError on non-UUID input in multi_tenant."""

    def test_tenant_data_schema_rejects_non_uuid(self, monkeypatch):
        """tenant_data_schema raises ValueError for non-UUID tenant_id in multi_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_data_schema

        with pytest.raises(ValueError, match="invalid tenant_id|Invalid tenant_id"):
            tenant_data_schema("not-a-uuid")

    def test_tenant_reader_role_rejects_non_uuid(self, monkeypatch):
        """tenant_reader_role raises ValueError for non-UUID tenant_id in multi_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_reader_role

        with pytest.raises(ValueError, match="invalid tenant_id|Invalid tenant_id"):
            tenant_reader_role("../etc/passwd")

    def test_tenant_data_schema_rejects_sql_injection_attempt(self, monkeypatch):
        """tenant_data_schema raises ValueError for SQL-injection-style input."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import tenant_data_schema

        with pytest.raises(ValueError):
            tenant_data_schema("'; DROP TABLE users; --")


# ---------------------------------------------------------------------------
# Test D: apply_tenant_data_schema single_tenant — hard no-op (zero SQL)
# ---------------------------------------------------------------------------


class TestApplySingleTenantNoOp:
    """D: apply_tenant_data_schema is a hard no-op in single_tenant."""

    async def test_single_tenant_issues_zero_sql(self, monkeypatch):
        """In single_tenant, apply_tenant_data_schema returns immediately without
        calling conn.execute at all.
        """
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import apply_tenant_data_schema

        executed: list[str] = []

        class _FakeConn:
            async def execute(self, stmt):
                executed.append(str(stmt))

        await apply_tenant_data_schema(_FakeConn(), _TENANT_A)
        assert executed == [], (
            f"single_tenant apply_tenant_data_schema must issue ZERO SQL; "
            f"got: {executed}"
        )

    async def test_single_tenant_schema_not_created_in_db(self, monkeypatch):
        """In single_tenant, the per-tenant schema does NOT exist in the live test DB."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import apply_tenant_data_schema

        db_url = await _get_test_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        # Use a temp schema name that should definitely not be created by the no-op.
        temp_schema = "data_t_ffffffff_ffff_ffff_ffff_ffffffffffff"
        try:
            async with engine.connect() as conn:
                await conn.execution_options(isolation_level="AUTOCOMMIT")
                await apply_tenant_data_schema(
                    conn, "ffffffff-ffff-ffff-ffff-ffffffffffff"
                )
                row = await conn.execute(
                    sa.text(
                        "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                    ),
                    {"s": temp_schema},
                )
                assert row.fetchone() is None, (
                    f"single_tenant no-op should NOT create schema {temp_schema!r}"
                )
        finally:
            await engine.dispose()


# ---------------------------------------------------------------------------
# Test E: apply_tenant_data_schema multi_tenant — creates schema+role, idempotent
# ---------------------------------------------------------------------------

# Use a test-only UUID to avoid colliding with the init-test-db.sh fixtures.
_TENANT_DYNAMIC = "dddddddd-dddd-dddd-dddd-dddddddddddd"
_SCHEMA_DYNAMIC = "data_t_dddddddd_dddd_dddd_dddd_dddddddddddd"
_ROLE_DYNAMIC = "geolens_reader_t_dddddddd_dddd_dddd_dddd_dddddddddddd"


class TestApplyMultiTenantProvisioning:
    """E: apply_tenant_data_schema creates schema + role in multi_tenant (idempotent)."""

    async def test_provisioning_creates_schema_and_role(self, monkeypatch):
        """apply_tenant_data_schema creates data_t_{tid} schema + geolens_reader_t_{tid} role."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import (
            apply_tenant_data_schema,
            deprovision_tenant_data_schema,
        )

        db_url = await _get_test_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.tenants (id, slug, name) "
                        "VALUES (CAST(:id AS uuid), :slug, :name)"
                    ),
                    {"id": _TENANT_DYNAMIC, "slug": "dp01-dynamic", "name": "DP01"},
                )
                await apply_tenant_data_schema(conn, _TENANT_DYNAMIC)

                # Assert schema exists
                row = await conn.execute(
                    sa.text(
                        "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                    ),
                    {"s": _SCHEMA_DYNAMIC},
                )
                assert row.fetchone() is not None, (
                    f"Schema {_SCHEMA_DYNAMIC!r} should exist after provisioning"
                )

                # Assert role exists and is NOLOGIN
                row = await conn.execute(
                    sa.text(
                        "SELECT rolcanlogin, rolsuper, rolbypassrls "
                        "FROM pg_roles WHERE rolname = :r"
                    ),
                    {"r": _ROLE_DYNAMIC},
                )
                role_row = row.fetchone()
                assert role_row is not None, (
                    f"Role {_ROLE_DYNAMIC!r} should exist after provisioning"
                )
                rolcanlogin, rolsuper, rolbypassrls = role_row
                assert not rolcanlogin, f"{_ROLE_DYNAMIC} must be NOLOGIN"
                assert not rolsuper, f"{_ROLE_DYNAMIC} must NOT be SUPERUSER"
                assert not rolbypassrls, f"{_ROLE_DYNAMIC} must NOT be BYPASSRLS"
        finally:
            # Teardown through the same guarded boundary after deleting the row.
            engine2 = create_async_engine(db_url, poolclass=NullPool)
            try:
                async with engine2.begin() as conn:
                    await conn.execute(
                        sa.text(
                            "DELETE FROM catalog.tenants WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": _TENANT_DYNAMIC},
                    )
                    await deprovision_tenant_data_schema(conn, _TENANT_DYNAMIC)
            finally:
                await engine2.dispose()
            await engine.dispose()

    async def test_provisioning_is_idempotent(self, monkeypatch):
        """apply_tenant_data_schema called twice does NOT raise (IF NOT EXISTS)."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.core.db.tenant_schema import (
            apply_tenant_data_schema,
            deprovision_tenant_data_schema,
        )

        db_url = await _get_test_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO catalog.tenants (id, slug, name) "
                        "VALUES (CAST(:id AS uuid), :slug, :name)"
                    ),
                    {"id": _TENANT_DYNAMIC, "slug": "dp01-idempotent", "name": "DP01"},
                )
                # First call
                await apply_tenant_data_schema(conn, _TENANT_DYNAMIC)
                # Second call — must not raise
                await apply_tenant_data_schema(conn, _TENANT_DYNAMIC)
        finally:
            engine2 = create_async_engine(db_url, poolclass=NullPool)
            try:
                async with engine2.begin() as conn:
                    await conn.execute(
                        sa.text(
                            "DELETE FROM catalog.tenants WHERE id = CAST(:id AS uuid)"
                        ),
                        {"id": _TENANT_DYNAMIC},
                    )
                    await deprovision_tenant_data_schema(conn, _TENANT_DYNAMIC)
            finally:
                await engine2.dispose()
            await engine.dispose()


# ---------------------------------------------------------------------------
# Test F: Cross-tenant USAGE isolation
# ---------------------------------------------------------------------------


class TestCrossTenantPrivilegeIsolation:
    """F: geolens_reader_t_{A} has USAGE on data_t_{A} only, NOT on data_t_{B}."""

    async def test_tenant_a_role_cannot_use_tenant_b_schema(self):
        """Privilege catalog assertion: has_schema_privilege(role_A, schema_B) = false."""
        db_url = await _get_test_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                # _ROLE_A should have USAGE on _SCHEMA_A (provisioned by init-test-db.sh)
                row_a = await conn.execute(
                    sa.text("SELECT has_schema_privilege(:role, :schema, 'USAGE')"),
                    {"role": _ROLE_A, "schema": _SCHEMA_A},
                )
                can_use_own = row_a.scalar_one()
                assert can_use_own is True, (
                    f"{_ROLE_A!r} must have USAGE on its own schema {_SCHEMA_A!r}"
                )

                # _ROLE_A must NOT have USAGE on _SCHEMA_B
                row_b = await conn.execute(
                    sa.text("SELECT has_schema_privilege(:role, :schema, 'USAGE')"),
                    {"role": _ROLE_A, "schema": _SCHEMA_B},
                )
                can_use_other = row_b.scalar_one()
                assert can_use_other is False, (
                    f"CROSS-TENANT ISOLATION FAILURE: {_ROLE_A!r} has USAGE on "
                    f"{_SCHEMA_B!r} — privilege not scoped to own schema"
                )
        finally:
            await engine.dispose()

    async def test_tenant_b_role_cannot_use_tenant_a_schema(self):
        """Privilege catalog assertion: has_schema_privilege(role_B, schema_A) = false."""
        db_url = await _get_test_db_url()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                row = await conn.execute(
                    sa.text("SELECT has_schema_privilege(:role, :schema, 'USAGE')"),
                    {"role": _ROLE_B, "schema": _SCHEMA_A},
                )
                can_use_other = row.scalar_one()
                assert can_use_other is False, (
                    f"CROSS-TENANT ISOLATION FAILURE: {_ROLE_B!r} has USAGE on "
                    f"{_SCHEMA_A!r} — privilege not scoped to own schema"
                )
        finally:
            await engine.dispose()


# ---------------------------------------------------------------------------
# Test G: tenant_shard_id in single_tenant returns None
# ---------------------------------------------------------------------------


class TestTenantShardId:
    """G: tenant_shard_id in single_tenant returns None."""

    def test_shard_id_none_in_single_tenant(self, monkeypatch):
        """tenant_shard_id returns None in single_tenant (routing primitive inactive)."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_shard_id

        assert tenant_shard_id(None) is None
        assert tenant_shard_id(_TENANT_A) is None
