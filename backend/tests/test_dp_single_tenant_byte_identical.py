"""Data-plane single_tenant BYTE-IDENTICAL guard (Phase 1209-05, DP-02/DP-03).

Proves that the data-plane additions from Phase 1209 (Plans 01-04) are
completely inert in single_tenant — the deployment mode used by Community
and Enterprise editions.

In single_tenant:
  (a) ``tenant_data_schema(x)`` always returns ``"data"`` (the shared schema).
  (b) ``tenant_reader_role(x)`` always returns ``"geolens_reader"`` (global role).
  (c) ``tenant_shard_id(x)`` always returns ``None`` (routing primitive inactive).
  (d) ``apply_tenant_data_schema(conn, x)`` issues ZERO SQL — pure no-op.
  (e) ``_qtable`` / ``_safe_table_ref`` default to the ``"data"`` schema.
  (f) No ``data_t_*`` schema and no ``geolens_reader_t_*`` role is created by a
      normal single_tenant boot/ingest (catalog query asserts none exist beyond
      the init-test-db fixtures).
  (g) The GUC ``app.current_tenant`` is unset in a default single_tenant session
      (the tenant_session hook is a no-op).

This is the [BLOCKING] byte-identical acceptance gate for Phase 1209.
Any regression that activates multi_tenant behavior in single_tenant would
break Community/Enterprise deploys silently.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_dp_single_tenant_byte_identical.py -x -q
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# Hard-coded test UUIDs — used to verify these UUIDs do NOT trigger
# multi_tenant behavior in single_tenant mode.
_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"

_SOME_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_SOME_TABLE = "my_geospatial_dataset"


# ---------------------------------------------------------------------------
# (a/b/c) tenant_data_schema / tenant_reader_role / tenant_shard_id
# All three helpers return single_tenant defaults for any input
# ---------------------------------------------------------------------------


class TestDataPlaneHelpersInSingleTenant:
    """(a/b/c): Data-plane helpers return global defaults in single_tenant.

    These are the load-bearing no-ops: calling helpers with any tenant_id
    in single_tenant must return the shared schema, global reader role, and
    None shard routing — byte-identical to pre-1209 behavior.
    """

    def test_tenant_data_schema_none_returns_data(self, monkeypatch):
        """tenant_data_schema(None) == 'data' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_data_schema

        assert tenant_data_schema(None) == "data"

    def test_tenant_data_schema_with_uuid_returns_data(self, monkeypatch):
        """tenant_data_schema(uuid) still returns 'data' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_data_schema

        assert tenant_data_schema(_TENANT_A) == "data"
        assert tenant_data_schema(_SOME_UUID) == "data"

    def test_tenant_reader_role_none_returns_geolens_reader(self, monkeypatch):
        """tenant_reader_role(None) == 'geolens_reader' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_reader_role

        assert tenant_reader_role(None) == "geolens_reader"

    def test_tenant_reader_role_with_uuid_returns_geolens_reader(self, monkeypatch):
        """tenant_reader_role(uuid) still returns 'geolens_reader' in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_reader_role

        assert tenant_reader_role(_TENANT_A) == "geolens_reader"
        assert tenant_reader_role(_SOME_UUID) == "geolens_reader"

    def test_tenant_shard_id_none_returns_none(self, monkeypatch):
        """tenant_shard_id(None) returns None in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_shard_id

        assert tenant_shard_id(None) is None

    def test_tenant_shard_id_with_uuid_returns_none(self, monkeypatch):
        """tenant_shard_id(uuid) returns None in single_tenant (routing primitive inactive)."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import tenant_shard_id

        assert tenant_shard_id(_TENANT_A) is None


# ---------------------------------------------------------------------------
# (d) apply_tenant_data_schema issues zero SQL in single_tenant
# ---------------------------------------------------------------------------


class TestApplyTenantDataSchemaIsZeroSqlInSingleTenant:
    """(d): apply_tenant_data_schema() issues zero SQL in single_tenant.

    Uses a mock connection and asserts conn.execute is never awaited.
    This proves the function is a pure no-op — no DDL, no schema creation,
    no role creation, nothing.
    """

    @pytest.mark.asyncio
    async def test_apply_tenant_data_schema_noop_single_tenant(self, monkeypatch):
        """apply_tenant_data_schema does not call conn.execute in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import apply_tenant_data_schema

        mock_conn = AsyncMock()
        await apply_tenant_data_schema(mock_conn, _TENANT_A)
        mock_conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_apply_tenant_data_schema_noop_with_any_uuid(self, monkeypatch):
        """apply_tenant_data_schema is a no-op for any UUID in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.db.tenant_schema import apply_tenant_data_schema

        mock_conn = AsyncMock()
        await apply_tenant_data_schema(mock_conn, _SOME_UUID)
        mock_conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# (e) _qtable / _safe_table_ref default to "data" schema
# ---------------------------------------------------------------------------


class TestQtableAndSafeTableRefDefaultInSingleTenant:
    """(e): _qtable and _safe_table_ref default to 'data' schema.

    Single-tenant callers of the ingest helpers pass no schema arg.
    The defaults must produce 'data'-schema-qualified output — unchanged
    from pre-1209 behavior.
    """

    def test_qtable_default_schema_is_data(self, monkeypatch):
        """_qtable(table_name) with no schema arg returns \"data\".\"table\"."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.processing.ingest.metadata import _qtable

        result = _qtable(_SOME_TABLE)
        assert result == f'"data"."{_SOME_TABLE}"', (
            f"Expected _qtable to default to data schema; got {result!r}"
        )

    def test_safe_table_ref_default_schema_is_data(self, monkeypatch):
        """_safe_table_ref(table_name) with no schema arg returns \"data\".\"table\"."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.modules.catalog.datasets.domain._sql_safety import _safe_table_ref

        result = _safe_table_ref(_SOME_TABLE)
        assert result == f'"data"."{_SOME_TABLE}"', (
            f"Expected _safe_table_ref to default to data schema; got {result!r}"
        )

    def test_qtable_explicit_data_schema(self, monkeypatch):
        """_qtable(table_name, schema='data') explicitly produces data-schema form."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.processing.ingest.metadata import _qtable

        result = _qtable(_SOME_TABLE, schema="data")
        assert '"data"' in result
        # Must not contain any per-tenant schema prefix
        assert "data_t_" not in result


# ---------------------------------------------------------------------------
# (f) No per-tenant schema/role in the DB from single_tenant operations
# ---------------------------------------------------------------------------


class TestNoPerTenantSchemaExistsFromSingleTenantBoot:
    """(f): No data_t_* schema or geolens_reader_t_* role is created by
    a normal single_tenant boot or ingest.

    This test queries the live test DB catalog and asserts:
    - No schema with name prefix 'data_t_' exists BEYOND the two fixtures
      provisioned by init-test-db.sh + conftest.py (those are expected
      test fixtures, not production regressions).
    - No role with name prefix 'geolens_reader_t_' exists beyond the two
      test fixtures.

    A violation would mean some code path is creating per-tenant artifacts
    in what should be single_tenant mode.

    Note: init-test-db.sh / conftest.py provision two per-tenant test
    schemas+roles (_TENANT_A and _TENANT_B) as test FIXTURES — not as
    single_tenant behavior.  Those are excluded from the assertion.
    """

    # The two fixture schemas/roles created by init-test-db.sh + conftest.py
    # are expected to exist — they are test fixtures, not production regressions.
    _FIXTURE_SCHEMAS = {
        "data_t_00000000_0000_0000_0000_000000000001",
        "data_t_00000000_0000_0000_0000_000000000002",
    }
    _FIXTURE_ROLES = {
        "geolens_reader_t_00000000_0000_0000_0000_000000000001",
        "geolens_reader_t_00000000_0000_0000_0000_000000000002",
    }

    def test_cluster_global_catalog_guard_is_serialized_by_xdist(self, request):
        """The catalog observer must not overlap cluster-global role mutators."""
        marker = request.node.get_closest_marker("xdist_group")
        assert marker is not None
        assert marker.args == ("tenancy_global_state",)

    @pytest.mark.asyncio
    async def test_no_non_fixture_per_tenant_schemas(self):
        """No data_t_* schemas exist beyond the two init-test-db.sh fixtures."""
        from app.core.config import settings

        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT schema_name FROM information_schema.schemata "
                            "WHERE schema_name LIKE 'data\\_t\\_%'"
                        )
                    )
                ).fetchall()
        finally:
            await engine.dispose()

        found_schemas = {row[0] for row in rows}
        unexpected = found_schemas - self._FIXTURE_SCHEMAS
        assert not unexpected, (
            f"DP single_tenant byte-identical FAIL (f): non-fixture per-tenant schemas "
            f"found in the test DB: {unexpected}. "
            f"Only the two init-test-db.sh fixtures are expected: {self._FIXTURE_SCHEMAS}. "
            f"A regression in single_tenant mode is creating per-tenant schemas."
        )

    @pytest.mark.asyncio
    async def test_no_non_fixture_per_tenant_roles(self):
        """No geolens_reader_t_* roles exist beyond the two init-test-db.sh fixtures."""
        from app.core.config import settings

        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        sa.text(
                            "SELECT rolname FROM pg_roles "
                            "WHERE rolname LIKE 'geolens\\_reader\\_t\\_%'"
                        )
                    )
                ).fetchall()
        finally:
            await engine.dispose()

        found_roles = {row[0] for row in rows}
        unexpected = found_roles - self._FIXTURE_ROLES
        assert not unexpected, (
            f"DP single_tenant byte-identical FAIL (f): non-fixture per-tenant roles "
            f"found in the test DB: {unexpected}. "
            f"Only the two init-test-db.sh fixtures are expected: {self._FIXTURE_ROLES}. "
            f"A regression in single_tenant mode is creating per-tenant roles."
        )


# ---------------------------------------------------------------------------
# (g) GUC is unset in a default single_tenant session
# ---------------------------------------------------------------------------


class TestGucUnsetInSingleTenantDataPlane:
    """(g): app.current_tenant GUC is never set in a default single_tenant session.

    Mirrors the Phase 1208-05 guard (test_iso_single_tenant_byte_identical.py)
    for the data-plane additions: no new hook or code path in Phase 1209
    should be setting the tenant GUC in single_tenant mode.
    """

    @pytest.mark.asyncio
    async def test_guc_unset_in_default_single_tenant_session(self, monkeypatch):
        """current_setting('app.current_tenant', true) is NULL in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.core.config import settings

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

        assert guc_val is None or guc_val == "", (
            f"DP byte-identical FAIL (g): app.current_tenant GUC is set to "
            f"{guc_val!r} in a default single_tenant session. "
            f"The data-plane Phase 1209 changes must not set the tenant GUC in "
            f"single_tenant mode — this would break Community/Enterprise deploys."
        )


# ---------------------------------------------------------------------------
# (h) Tile-path binder is a no-op in single_tenant
# ---------------------------------------------------------------------------


class TestTilePathBinderNoopInSingleTenant:
    """(h): set_tenant_role_for_tile_request is a no-op in single_tenant.

    Mirrors test_dp02_read_path_binding.py TestSetTenantRoleSingleTenantNoOp
    as an additional byte-identical guard: the binder must not issue ANY SQL
    in single_tenant mode, even with a non-None tenant_id.
    """

    @pytest.mark.asyncio
    async def test_binder_noop_in_single_tenant_any_uuid(self, monkeypatch):
        """set_tenant_role_for_tile_request issues zero SQL in single_tenant."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.processing.tiles.pool import set_tenant_role_for_tile_request

        mock_conn = AsyncMock()
        await set_tenant_role_for_tile_request(mock_conn, _TENANT_A)
        mock_conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_binder_noop_in_single_tenant_none_tenant_id(self, monkeypatch):
        """set_tenant_role_for_tile_request is a no-op with None tenant_id."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.processing.tiles.pool import set_tenant_role_for_tile_request

        mock_conn = AsyncMock()
        await set_tenant_role_for_tile_request(mock_conn, None)
        mock_conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# (i) Sandbox executor uses geolens_readonly in single_tenant
# ---------------------------------------------------------------------------


class TestSandboxRoleIsSingleTenantReader:
    """(i): execute_safe uses 'geolens_reader' (not per-tenant role) in single_tenant.

    CR-04 (Phase 1209): the fallback role is geolens_reader (guaranteed by
    migration 0007 / init-db.sh) rather than geolens_readonly (only in
    0001_baseline which may be squashed).

    This is the data-plane analogue of the Phase 1208-05 guard: confirms the
    sandbox executor did not accidentally activate multi_tenant role selection
    in single_tenant mode.
    """

    @pytest.mark.asyncio
    async def test_execute_safe_uses_geolens_reader_in_single_tenant(self, monkeypatch):
        """In single_tenant, execute_safe issues SET LOCAL ROLE geolens_reader."""
        monkeypatch.setattr(
            "app.platform.sandbox.executor.is_multi_tenant", lambda: False
        )

        executed_stmts: list[str] = []

        async def _mock_execute(stmt, *args, **kwargs):
            executed_stmts.append(str(stmt))
            result = MagicMock()
            result.keys.return_value = []
            result.fetchall.return_value = []
            return result

        mock_txn_cm = MagicMock()
        mock_txn_cm.__aenter__ = AsyncMock(return_value=None)
        mock_txn_cm.__aexit__ = AsyncMock(return_value=False)

        mock_conn = AsyncMock()
        mock_conn.execute.side_effect = _mock_execute
        mock_conn.begin = MagicMock(return_value=mock_txn_cm)

        mock_connect_cm = MagicMock()
        mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_connect_cm.__aexit__ = AsyncMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_connect_cm

        import app.core.db as db_module
        from unittest.mock import patch

        with patch.object(db_module, "engine", mock_engine):
            from app.platform.sandbox.executor import execute_safe

            await execute_safe(MagicMock(), "SELECT 1")

        role_stmts = [s for s in executed_stmts if "SET LOCAL ROLE" in s]
        # CR-04: fallback is now geolens_reader (not geolens_readonly)
        assert any(s.strip().endswith("geolens_reader") for s in role_stmts), (
            f"DP byte-identical FAIL (i): expected SET LOCAL ROLE geolens_reader "
            f"in single_tenant; got: {role_stmts}"
        )
        # Must NOT use a per-tenant role in single_tenant
        per_tenant_role_stmts = [s for s in role_stmts if "geolens_reader_t_" in s]
        assert not per_tenant_role_stmts, (
            f"DP byte-identical FAIL (i): per-tenant role appeared in SET LOCAL ROLE "
            f"in single_tenant mode: {per_tenant_role_stmts}. "
            f"The data-plane role selection must be inert in single_tenant."
        )
