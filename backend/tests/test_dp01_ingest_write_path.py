"""DP-01 ingest write-path tests: schema/role-parameterized helpers + tenant routing.

Task 1 (pure-function, no DB)
-----------------------------
T1-A: _qtable default schema == 'data' (single_tenant unchanged)
T1-B: _qtable with explicit schema produces correct quoted ref
T1-C: _safe_table_ref default schema == 'data' (single_tenant unchanged)
T1-D: _safe_table_ref with explicit schema produces correct quoted ref
T1-E: _safe_table_ref raises ValueError on invalid schema name
T1-F: _safe_table_ref validates the data_t_<uuid_underscored> schema name
T1-G: grant_reader_access GRANT text targets correct table+role (default)
T1-H: grant_reader_access GRANT text targets per-tenant schema+role

Task 2 (live DB — requires test DB at localhost:5434)
------------------------------------------------------
T2-A: ingest write helpers land a table in data_t_{TENANT_A} in multi_tenant
T2-B: to_regclass('data_t_..._001.probe') is NOT NULL; 'data.probe' IS NULL
T2-C: geolens_reader_t_{A} can SELECT from data_t_{A}; geolens_reader_t_{B} denied

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_dp01_ingest_write_path.py -x -q
"""

from __future__ import annotations

import os
import unittest.mock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# Test tenant IDs (provisioned in init-test-db.sh + conftest.py by Plan 01)
# ---------------------------------------------------------------------------
_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"
_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"
_ROLE_A = "geolens_reader_t_00000000_0000_0000_0000_000000000001"
_ROLE_B = "geolens_reader_t_00000000_0000_0000_0000_000000000002"


# ===========================================================================
# Task 1: Pure-function assertions (no DB)
# ===========================================================================


class TestQtableSchemaParam:
    """T1-A/B: _qtable with schema parameter defaults."""

    def test_default_schema_is_data(self):
        """T1-A: _qtable('ds_abc') == '"data"."ds_abc"' (single_tenant unchanged)."""
        from app.processing.ingest.metadata import _qtable

        assert _qtable("ds_abc") == '"data"."ds_abc"'

    def test_explicit_tenant_schema(self):
        """T1-B: _qtable('ds_abc', schema='data_t_x') returns per-tenant ref."""
        from app.processing.ingest.metadata import _qtable

        assert _qtable("ds_abc", schema="data_t_x") == '"data_t_x"."ds_abc"'

    def test_schema_must_match_safe_pattern(self):
        """T1-B: schema validated — bad schema raises ValueError."""
        from app.processing.ingest.metadata import _qtable

        with pytest.raises(ValueError):
            _qtable("ds_abc", schema="bad-schema!")

    def test_table_name_still_validated(self):
        """_qtable still rejects invalid table name when schema is provided."""
        from app.processing.ingest.metadata import _qtable

        with pytest.raises(ValueError):
            _qtable("bad; DROP", schema="data_t_x")

    def test_tenant_schema_name_accepted(self):
        """Real tenant schema names (data_t_<uuid_underscored>) pass validation."""
        from app.processing.ingest.metadata import _qtable

        result = _qtable("ds_abc", schema=_SCHEMA_A)
        assert result == f'"{_SCHEMA_A}"."ds_abc"'


class TestSafeTableRefSchemaParam:
    """T1-C/D/E/F: _safe_table_ref with schema parameter."""

    def test_default_schema_is_data(self):
        """T1-C: _safe_table_ref('ds_abc') == '"data"."ds_abc"' (single_tenant unchanged)."""
        from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

        assert _safe_table_ref("ds_abc") == '"data"."ds_abc"'

    def test_explicit_tenant_schema(self):
        """T1-D: _safe_table_ref with explicit schema returns correct ref."""
        from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

        assert _safe_table_ref("ds_abc", schema="data_t_x") == '"data_t_x"."ds_abc"'

    def test_invalid_schema_raises_value_error(self):
        """T1-E: _safe_table_ref raises ValueError on invalid schema name."""
        from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

        with pytest.raises(ValueError, match="Invalid schema"):
            _safe_table_ref("ds_abc", schema="bad-schema!")

    def test_invalid_schema_with_space_raises(self):
        """Schema with spaces is rejected."""
        from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

        with pytest.raises(ValueError, match="Invalid schema"):
            _safe_table_ref("ds_abc", schema="data t x")

    def test_tenant_schema_name_accepted(self):
        """T1-F: Real tenant schema names pass SAFE_TABLE_NAME_RE validation."""
        from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

        result = _safe_table_ref("ds_abc", schema=_SCHEMA_A)
        assert result == f'"{_SCHEMA_A}"."ds_abc"'

    def test_table_name_still_validated(self):
        """_safe_table_ref still rejects invalid table name with explicit schema."""
        from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

        with pytest.raises(ValueError, match="Invalid table"):
            _safe_table_ref("bad; DROP", schema="data_t_x")


class TestGrantReaderAccessSignature:
    """T1-G/H: grant_reader_access kwargs default to data/geolens_reader."""

    def _make_mock_session(self):
        """Create a mock AsyncSession that captures the SQL text emitted."""
        session = unittest.mock.AsyncMock()
        captured = []

        async def capture_execute(stmt, *args, **kwargs):
            captured.append(str(stmt))

        session.execute.side_effect = capture_execute
        return session, captured

    @pytest.mark.asyncio
    async def test_default_targets_data_geolens_reader(self):
        """T1-G: grant_reader_access defaults to schema='data', role='geolens_reader'."""
        from app.processing.ingest.metadata import grant_reader_access

        session, captured = self._make_mock_session()
        await grant_reader_access(session, "ds_abc")

        assert len(captured) == 1
        sql = captured[0]
        assert '"data"."ds_abc"' in sql
        assert "geolens_reader" in sql
        assert "GRANT SELECT" in sql.upper()

    @pytest.mark.asyncio
    async def test_per_tenant_schema_and_role(self):
        """T1-H: grant_reader_access with per-tenant kwargs targets correct schema+role."""
        from app.processing.ingest.metadata import grant_reader_access

        session, captured = self._make_mock_session()
        await grant_reader_access(
            session,
            "ds_abc",
            schema=_SCHEMA_A,
            role=_ROLE_A,
        )

        assert len(captured) == 1
        sql = captured[0]
        assert f'"{_SCHEMA_A}"."ds_abc"' in sql
        assert _ROLE_A in sql
        assert "GRANT SELECT" in sql.upper()


# ===========================================================================
# Task 2: Live DB tests — require test DB at localhost:5434
# These tests are marked DB and skipped when POSTGRES_HOST is not set.
# ===========================================================================

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("POSTGRES_HOST"),
    reason="Requires test DB (set POSTGRES_HOST in .env.test)",
)


def _db_url() -> str:
    # Use the per-worker TEST database that conftest provisions with the
    # per-tenant data_t_* schemas + geolens_reader_t_* roles/grants — NOT the
    # main app DB (POSTGRES_DB), which is `postgres` on CI and never receives
    # the per-tenant provisioning, causing "schema does not exist" there. Mirrors
    # the working dp02 `_get_test_db_url()` pattern.
    from app.core.config import settings

    return settings.test_database_url


@pytest.mark.asyncio
@pytestmark_db
async def test_ingest_write_helper_lands_table_in_tenant_schema(monkeypatch):
    """T2-A/B: A table created via _qtable(schema=SCHEMA_A) lands in SCHEMA_A, NOT in data.

    This exercises the schema-routing by directly creating a table with the
    parameterized _qtable and then asserting via to_regclass that the table
    exists in the tenant schema only.
    """
    from app.processing.ingest.metadata import _qtable

    # Force multi_tenant mode for this test
    monkeypatch.setenv("GEOLENS_TENANCY_MODE", "multi_tenant")

    probe_table = "dp01_probe_t2a"
    engine = create_async_engine(_db_url(), poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")

            # Clean up from previous runs
            await conn.execute(
                sa.text(f'DROP TABLE IF EXISTS {_SCHEMA_A}."{probe_table}"')
            )
            await conn.execute(sa.text(f'DROP TABLE IF EXISTS data."{probe_table}"'))

            # Create the table in the tenant schema using the parameterized _qtable
            qualified = _qtable(probe_table, schema=_SCHEMA_A)
            await conn.execute(sa.text(f"CREATE TABLE {qualified} (id int)"))

            # T2-B: assert table lives in tenant schema, NOT in data
            row_tenant = await conn.execute(
                sa.text(f"SELECT to_regclass('{_SCHEMA_A}.{probe_table}')")
            )
            assert row_tenant.scalar() is not None, (
                f"Table not found in tenant schema {_SCHEMA_A}"
            )

            row_shared = await conn.execute(
                sa.text(f"SELECT to_regclass('data.{probe_table}')")
            )
            assert row_shared.scalar() is None, (
                "Table must NOT exist in shared data schema"
            )

            # Cleanup
            await conn.execute(
                sa.text(f"DROP TABLE IF EXISTS {_SCHEMA_A}.{probe_table}")
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytestmark_db
async def test_cross_tenant_privilege_denied():
    """T2-C: Tenant A reader role cannot SELECT from tenant B's table (privilege error).

    Asserts at the DB privilege layer — not app convention. geolens_reader_t_{A}
    must receive a permission error when accessing data_t_{B}.some_table, NOT
    empty rows.
    """
    probe_table = "dp01_probe_cross_tenant"
    engine = create_async_engine(_db_url(), poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            # Create a test table in tenant B's schema (as superuser)
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                sa.text(f"DROP TABLE IF EXISTS {_SCHEMA_B}.{probe_table}")
            )
            await conn.execute(
                sa.text(f"CREATE TABLE {_SCHEMA_B}.{probe_table} (id int)")
            )

        # Open a SEPARATE connection to do the role-switch + access check
        # so the autocommit CREATE TABLE is fully visible.
        async with engine.connect() as conn:
            async with conn.begin():
                # Grant access so tenant A's reader can use its OWN schema (baseline)
                # — already done in init-test-db.sh / conftest; we just verify cross.

                # Switch to TENANT A's reader role
                await conn.execute(sa.text(f"SET LOCAL ROLE {_ROLE_A}"))

                # Attempt to SELECT from TENANT B's table — must raise privilege error
                with pytest.raises(
                    Exception, match="permission denied|insufficient privilege"
                ):
                    await conn.execute(
                        sa.text(f"SELECT * FROM {_SCHEMA_B}.{probe_table}")
                    )

        # Cleanup
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                sa.text(f"DROP TABLE IF EXISTS {_SCHEMA_B}.{probe_table}")
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytestmark_db
async def test_tenant_a_reader_can_select_own_schema():
    """T2-C (positive): geolens_reader_t_{A} can SELECT from data_t_{A}.

    Positive control for the cross-tenant test — ensures the per-tenant
    reader role has the USAGE + SELECT grants installed by Plan 01.
    """
    probe_table = "dp01_probe_own_tenant"
    engine = create_async_engine(_db_url(), poolclass=NullPool)
    try:
        # Create a table in tenant A's schema (as superuser)
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                sa.text(f"DROP TABLE IF EXISTS {_SCHEMA_A}.{probe_table}")
            )
            await conn.execute(
                sa.text(f"CREATE TABLE {_SCHEMA_A}.{probe_table} (id int)")
            )
            await conn.execute(
                sa.text(f"GRANT SELECT ON {_SCHEMA_A}.{probe_table} TO {_ROLE_A}")
            )

        # Now switch to reader_t_A and SELECT — must succeed
        async with engine.connect() as conn:
            async with conn.begin():
                await conn.execute(sa.text(f"SET LOCAL ROLE {_ROLE_A}"))
                result = await conn.execute(
                    sa.text(f"SELECT * FROM {_SCHEMA_A}.{probe_table}")
                )
                rows = result.fetchall()
                assert rows == []  # empty table but no error

        # Cleanup
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                sa.text(f"DROP TABLE IF EXISTS {_SCHEMA_A}.{probe_table}")
            )
    finally:
        await engine.dispose()
