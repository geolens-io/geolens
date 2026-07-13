"""DP-02: Read-path role binding + schema-qualified tile queries + dataset resolver (Phase 1209-03).

Tests
-----
Task 1 — Tile path binder + schema-qualified queries:
  T1A: set_tenant_role_for_tile_request is a no-op in single_tenant (no SQL issued).
  T1B: set_tenant_role_for_tile_request in multi_tenant issues SET LOCAL ROLE + SET LOCAL search_path
       and the live DB reflects the per-tenant role and schema.
  T1C: _build_tile_query renders schema-qualified FROM clause ("data_t_..._001"."table") in multi_tenant.
  T1D: _build_tile_query renders "data"."table" (no bare data.table) in single_tenant.
  T1E: _build_cluster_tile_query renders schema-qualified FROM clause in multi_tenant.
  T1F: _build_cluster_tile_query renders "data"."table" in single_tenant.
  T1G: No bare `data.{table_name}` f-string literal in service.py query builders.
  T1H: set_tenant_role_for_tile_request with tenant B's role cannot read data_t_{A}'s table
       (cross-tenant privilege denied at DB level).

Task 2 — Sandbox executor mode-aware role + dataset resolver:
  T2A: execute_safe uses geolens_readonly in single_tenant.
  T2B: execute_safe uses tenant_reader_role(tid) in multi_tenant when tid is set.
  T2C: execute_safe fails closed in multi_tenant when tid is None.
  T2D: _resolve_dataset_meta resolves the correct-tenant dataset and raises 404 for a
       mismatched-tenant table_name (even if the bare table_name matches).
  T2E: _dataset_cache does NOT return tenant A's meta for tenant B (tenant-prefixed key);
       same table_name with two different tenants produces two separate cache entries.
  T2F: _resolve_dataset_meta in single_tenant uses bare table_name cache key and no tenant filter.

Run:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_dp02_read_path_binding.py -x -q
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Hard-coded test UUIDs matching init-test-db.sh per-tenant fixture
_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"

_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"
_ROLE_A = "geolens_reader_t_00000000_0000_0000_0000_000000000001"
_ROLE_B = "geolens_reader_t_00000000_0000_0000_0000_000000000002"

_TABLE = "my_dataset"


async def _get_test_db_url() -> str:
    from app.core.config import settings

    return settings.test_database_url


# ---------------------------------------------------------------------------
# Task 1A: single_tenant no-op
# ---------------------------------------------------------------------------


class TestSetTenantRoleSingleTenantNoOp:
    """T1A: set_tenant_role_for_tile_request is a no-op in single_tenant."""

    @pytest.mark.asyncio
    async def test_binder_noop_in_single_tenant(self, monkeypatch):
        """In single_tenant, binder returns without executing any SQL."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.processing.tiles.pool import set_tenant_role_for_tile_request

        mock_conn = AsyncMock()
        await set_tenant_role_for_tile_request(mock_conn, _TENANT_A)
        mock_conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_binder_noop_when_tenant_id_none(self, monkeypatch):
        """In multi_tenant, binder is a no-op when tenant_id is None."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.processing.tiles.pool import set_tenant_role_for_tile_request

        mock_conn = AsyncMock()
        await set_tenant_role_for_tile_request(mock_conn, None)
        mock_conn.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# Task 1B: multi_tenant — live DB role+search_path assertion
# ---------------------------------------------------------------------------


class TestSetTenantRoleMultiTenantLive:
    """T1B: multi_tenant binder sets role + search_path on a live asyncpg connection."""

    @pytest.mark.asyncio
    async def test_role_and_search_path_set_within_transaction(self, monkeypatch):
        """After binder runs inside a txn, current_user == ROLE_A and search_path starts with SCHEMA_A."""
        import asyncpg

        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

        from app.processing.tiles.pool import set_tenant_role_for_tile_request

        db_url = await _get_test_db_url()
        # Convert sqlalchemy+asyncpg URL to bare asyncpg DSN
        dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

        conn = await asyncpg.connect(dsn)
        try:
            async with conn.transaction():
                await set_tenant_role_for_tile_request(conn, _TENANT_A)
                current_user = await conn.fetchval("SELECT current_user")
                search_path = await conn.fetchval("SHOW search_path")
                # Role must be the per-tenant reader role
                assert current_user == _ROLE_A, (
                    f"Expected {_ROLE_A!r} but got {current_user!r}"
                )
                # search_path must start with the per-tenant schema
                assert search_path.startswith(_SCHEMA_A), (
                    f"Expected search_path to start with {_SCHEMA_A!r}; got {search_path!r}"
                )
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# Task 1C/D/E/F: Schema-qualified tile query builders
# ---------------------------------------------------------------------------


class TestTileQuerySchemaQualification:
    """T1C-F: _build_tile_query and _build_cluster_tile_query emit schema-qualified FROM clauses."""

    def test_build_tile_query_schema_qualified_multi_tenant(self, monkeypatch):
        """T1C: _build_tile_query with SCHEMA_A qualifies FROM as "data_t_..._001"."my_dataset"."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.processing.tiles.service import _build_tile_query

        query = _build_tile_query(_TABLE, [], schema=_SCHEMA_A)
        expected = f'"{_SCHEMA_A}"."{_TABLE}"'
        assert expected in query, f"Expected {expected!r} in query but got:\n{query}"
        # No bare data.{table} literal
        assert f"data.{_TABLE}" not in query, (
            f"Found bare data.{{table}} literal in multi_tenant query:\n{query}"
        )

    def test_build_tile_query_schema_data_single_tenant(self, monkeypatch):
        """T1D: _build_tile_query with schema='data' qualifies FROM as "data"."my_dataset"."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.processing.tiles.service import _build_tile_query

        query = _build_tile_query(_TABLE, [], schema="data")
        expected = f'"data"."{_TABLE}"'
        assert expected in query, f"Expected {expected!r} in query but got:\n{query}"

    def test_build_cluster_tile_query_schema_qualified_multi_tenant(self, monkeypatch):
        """T1E: _build_cluster_tile_query with SCHEMA_A qualifies FROM as "data_t_..._001"."my_dataset"."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        from app.processing.tiles.service import _build_cluster_tile_query

        query = _build_cluster_tile_query(_TABLE, schema=_SCHEMA_A)
        expected = f'"{_SCHEMA_A}"."{_TABLE}"'
        assert expected in query, f"Expected {expected!r} in query but got:\n{query}"
        assert f"data.{_TABLE}" not in query, (
            f"Found bare data.{{table}} literal in multi_tenant cluster query:\n{query}"
        )

    def test_build_cluster_tile_query_schema_data_single_tenant(self, monkeypatch):
        """T1F: _build_cluster_tile_query with schema='data' qualifies FROM as "data"."my_dataset"."""
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
        from app.processing.tiles.service import _build_cluster_tile_query

        query = _build_cluster_tile_query(_TABLE, schema="data")
        expected = f'"data"."{_TABLE}"'
        assert expected in query, f"Expected {expected!r} in query but got:\n{query}"

    def test_no_bare_data_literal_in_get_tile_default(self, monkeypatch):
        """T1G (static): layer_name returned by get_tile uses schema-qualified form."""
        # get_tile should use schema=tenant_data_schema(tid) — no bare f"data.{table}"
        # We verify by asserting the SERVICE module no longer has the hardcoded form
        import inspect

        from app.processing.tiles import service as svc

        src = inspect.getsource(svc)
        # The old pattern was: layer_name = f"data.{table_name}" — must be gone
        assert 'f"data.{table_name}"' not in src, (
            'Found bare f"data.{table_name}" literal in service.py — must be removed'
        )


# ---------------------------------------------------------------------------
# Task 1H: Cross-tenant tile read denied at privilege layer
# ---------------------------------------------------------------------------


class TestCrossTenantTileReadDenied:
    """T1H: Tenant B's role cannot SELECT from a table in Tenant A's schema."""

    @pytest.mark.asyncio
    async def test_tenant_b_role_denied_on_tenant_a_schema(self, monkeypatch):
        """Tenant B's reader role cannot SELECT from data_t_{A}.probe — privilege denied."""
        import asyncpg

        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

        db_url = await _get_test_db_url()
        dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

        conn = await asyncpg.connect(dsn)
        try:
            async with conn.transaction():
                # Create a probe table in SCHEMA_A (as superuser)
                await conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {_SCHEMA_A}.dp02_probe (id int)"
                )
                # Switch to ROLE_B (tenant B's reader)
                await conn.execute(f"SET LOCAL ROLE {_ROLE_B}")
                # Attempt to SELECT from tenant A's table
                with pytest.raises(
                    asyncpg.exceptions.InsufficientPrivilegeError,
                    match="permission denied",
                ):
                    await conn.fetchval(
                        f"SELECT id FROM {_SCHEMA_A}.dp02_probe LIMIT 1"
                    )
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# Task 2A-C: Sandbox executor mode-aware role selection
# ---------------------------------------------------------------------------


def _make_sandbox_engine_mock(executed_stmts: list[str]):
    """Build a minimal mock engine for execute_safe tests.

    SQLAlchemy's async engine uses:
      ``async with engine.connect() as conn:``   (async CM)
      ``async with conn.begin():``               (async CM — conn.begin() is sync, returns async CM)
      ``await conn.execute(stmt)``               (awaitable)

    asyncpg.Connection.begin() is a SYNC method that returns a Transaction (async CM).
    SQLAlchemy AsyncConnection.begin() works the same way.
    We must NOT use AsyncMock for .begin() or it becomes a coroutine instead.
    """

    async def _mock_execute(stmt, *args, **kwargs):
        executed_stmts.append(str(stmt))
        result = MagicMock()
        result.keys.return_value = []
        result.fetchall.return_value = []
        return result

    # async context manager for conn.begin()
    mock_txn_cm = MagicMock()
    mock_txn_cm.__aenter__ = AsyncMock(return_value=None)
    mock_txn_cm.__aexit__ = AsyncMock(return_value=False)

    # conn — AsyncMock so await conn.execute() works; begin() is a plain MagicMock
    mock_conn = AsyncMock()
    mock_conn.execute.side_effect = _mock_execute
    mock_conn.begin = MagicMock(
        return_value=mock_txn_cm
    )  # sync method, returns async CM

    # async context manager for engine.connect()
    mock_connect_cm = MagicMock()
    mock_connect_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_connect_cm.__aexit__ = AsyncMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_connect_cm
    return mock_engine


class TestSandboxRoleSelection:
    """T2A-C: execute_safe selects role based on tenancy mode + tenant_id."""

    @pytest.mark.asyncio
    async def test_single_tenant_uses_geolens_reader(self, monkeypatch):
        """T2A: In single_tenant, execute_safe issues SET LOCAL ROLE geolens_reader.

        CR-04 (Phase 1209): fallback role is geolens_reader (guaranteed by
        migration 0007) rather than geolens_readonly (only in 0001_baseline).
        """
        # Patch at the executor module binding, not the source module
        monkeypatch.setattr(
            "app.platform.sandbox.executor.is_multi_tenant", lambda: False
        )

        executed_stmts: list[str] = []
        import app.core.db as db_module

        with patch.object(
            db_module, "engine", _make_sandbox_engine_mock(executed_stmts)
        ):
            from app.platform.sandbox.executor import execute_safe

            await execute_safe(MagicMock(), "SELECT 1")

        role_stmts = [s for s in executed_stmts if "SET LOCAL ROLE" in s]
        # CR-04: single_tenant uses geolens_reader (exact suffix match, not a prefix
        # of geolens_reader_t_*)
        assert any(s.strip().endswith("geolens_reader") for s in role_stmts), (
            f"Expected SET LOCAL ROLE geolens_reader; got: {role_stmts}"
        )

    @pytest.mark.asyncio
    async def test_multi_tenant_uses_tenant_reader_role(self, monkeypatch):
        """T2B: In multi_tenant with tid set, execute_safe uses tenant_reader_role(tid)."""
        # Patch both executor's binding AND source (tenant_reader_role does lazy import)
        monkeypatch.setattr(
            "app.platform.sandbox.executor.is_multi_tenant", lambda: True
        )
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(_TENANT_A)
        try:
            executed_stmts: list[str] = []
            import app.core.db as db_module

            with patch.object(
                db_module, "engine", _make_sandbox_engine_mock(executed_stmts)
            ):
                from app.platform.sandbox.executor import execute_safe

                await execute_safe(MagicMock(), "SELECT 1")

            role_stmts = [s for s in executed_stmts if "SET LOCAL ROLE" in s]
            assert any(_ROLE_A in s for s in role_stmts), (
                f"Expected SET LOCAL ROLE {_ROLE_A}; got: {role_stmts}"
            )
        finally:
            current_tenant_var.reset(token)

    @pytest.mark.asyncio
    async def test_multi_tenant_none_tid_fails_closed(self, monkeypatch):
        """T2C: In multi_tenant with tid=None, execute_safe rejects the query."""
        monkeypatch.setattr(
            "app.platform.sandbox.executor.is_multi_tenant", lambda: True
        )

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(None)
        try:
            executed_stmts: list[str] = []
            import app.core.db as db_module

            with patch.object(
                db_module, "engine", _make_sandbox_engine_mock(executed_stmts)
            ):
                from app.platform.sandbox.executor import execute_safe
                from app.platform.sandbox.schemas import SandboxError

                with pytest.raises(SandboxError) as exc_info:
                    await execute_safe(MagicMock(), "SELECT 1")

            assert exc_info.value.category == "query_failed"
            assert executed_stmts == []
        finally:
            current_tenant_var.reset(token)


# ---------------------------------------------------------------------------
# Task 2D-F: Dataset resolver tenant_id filter + cache key isolation
# ---------------------------------------------------------------------------


class TestResolverTenantFilter:
    """T2D-F: _resolve_dataset_meta filters by tenant_id with tenant-prefixed cache key."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        """Clear _dataset_cache before and after each test."""
        # Import and clear the module-level cache
        from app.processing.tiles import router as tile_router

        with tile_router._dataset_cache_lock:
            tile_router._dataset_cache.clear()

        yield

        with tile_router._dataset_cache_lock:
            tile_router._dataset_cache.clear()

    @pytest.mark.asyncio
    async def test_resolver_returns_correct_tenant_dataset(self, monkeypatch):
        """T2D(a): With current_tenant_var=A, resolver returns tenant A's dataset row."""
        monkeypatch.setattr("app.processing.tiles.router.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(_TENANT_A)
        try:
            # Build a mock DatasetORM row for tenant A
            tid_a = uuid.UUID(_TENANT_A)
            mock_record = MagicMock()
            mock_record.visibility = "public"
            mock_record.record_status = "published"
            mock_record.created_by = uuid.uuid4()
            mock_record.record_type = "vector_dataset"

            mock_dataset = MagicMock()
            mock_dataset.id = uuid.uuid4()
            mock_dataset.record_id = uuid.uuid4()
            mock_dataset.table_name = _TABLE
            mock_dataset.tenant_id = tid_a
            mock_dataset.record = mock_record
            mock_dataset.geometry_type = "POINT"
            mock_dataset.column_info = []
            mock_dataset.tile_cache_ttl = None
            mock_dataset.tile_columns = None

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_dataset

            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result

            from app.processing.tiles.router import _resolve_dataset_meta

            meta = await _resolve_dataset_meta(_TABLE, mock_db)
            assert meta.table_name == _TABLE
            # Verify the execute was called with a WHERE including tenant_id
            call_args = mock_db.execute.call_args
            stmt = call_args[0][0]
            # The stmt should contain a tenant_id filter
            stmt_str = str(stmt)
            assert "tenant_id" in stmt_str, (
                f"Expected tenant_id in WHERE clause; got: {stmt_str}"
            )
        finally:
            current_tenant_var.reset(token)

    @pytest.mark.asyncio
    async def test_resolver_404_for_mismatched_tenant(self, monkeypatch):
        """T2D(b): With current_tenant_var=B, resolver raises 404 for tenant A's table_name."""
        from fastapi import HTTPException

        monkeypatch.setattr("app.processing.tiles.router.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var

        # Set tenant to B — then simulate DB returning None (dataset belongs to A)
        token = current_tenant_var.set(_TENANT_B)
        try:
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = (
                None  # tenant B doesn't own this table
            )

            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result

            from app.processing.tiles.router import _resolve_dataset_meta

            with pytest.raises(HTTPException) as exc_info:
                await _resolve_dataset_meta(_TABLE, mock_db)
            assert exc_info.value.status_code == 404
        finally:
            current_tenant_var.reset(token)

    @pytest.mark.asyncio
    async def test_cache_key_is_tenant_prefixed_in_multi_tenant(self, monkeypatch):
        """T2E: Same table_name but different tenants produce separate cache entries."""
        monkeypatch.setattr("app.processing.tiles.router.is_multi_tenant", lambda: True)

        from app.core.db.tenant_session import current_tenant_var
        from app.processing.tiles import router as tile_router

        def _make_mock_dataset(tid_str: str):
            mock_record = MagicMock()
            mock_record.visibility = "public"
            mock_record.record_status = "published"
            mock_record.created_by = uuid.uuid4()
            mock_record.record_type = "vector_dataset"

            mock_dataset = MagicMock()
            mock_dataset.id = uuid.uuid4()
            mock_dataset.record_id = uuid.uuid4()
            mock_dataset.table_name = _TABLE
            mock_dataset.tenant_id = uuid.UUID(tid_str)
            mock_dataset.record = mock_record
            mock_dataset.geometry_type = "POINT"
            mock_dataset.column_info = []
            mock_dataset.tile_cache_ttl = None
            mock_dataset.tile_columns = None
            return mock_dataset

        # Resolve for tenant A
        token_a = current_tenant_var.set(_TENANT_A)
        try:
            mock_result_a = MagicMock()
            mock_result_a.scalar_one_or_none.return_value = _make_mock_dataset(
                _TENANT_A
            )
            mock_db_a = AsyncMock()
            mock_db_a.execute.return_value = mock_result_a

            from app.processing.tiles.router import _resolve_dataset_meta

            meta_a = await _resolve_dataset_meta(_TABLE, mock_db_a)
        finally:
            current_tenant_var.reset(token_a)

        # Resolve for tenant B
        token_b = current_tenant_var.set(_TENANT_B)
        try:
            mock_result_b = MagicMock()
            mock_result_b.scalar_one_or_none.return_value = _make_mock_dataset(
                _TENANT_B
            )
            mock_db_b = AsyncMock()
            mock_db_b.execute.return_value = mock_result_b

            meta_b = await _resolve_dataset_meta(_TABLE, mock_db_b)
        finally:
            current_tenant_var.reset(token_b)

        # Both should be present under distinct keys
        with tile_router._dataset_cache_lock:
            cache_keys = list(tile_router._dataset_cache.keys())

        assert f"{_TENANT_A}:{_TABLE}" in cache_keys, (
            f"Expected key {_TENANT_A}:{_TABLE!r} in cache; got: {cache_keys}"
        )
        assert f"{_TENANT_B}:{_TABLE}" in cache_keys, (
            f"Expected key {_TENANT_B}:{_TABLE!r} in cache; got: {cache_keys}"
        )
        # The two metas must be different objects
        assert meta_a is not meta_b

    @pytest.mark.asyncio
    async def test_resolver_single_tenant_bare_key_no_filter(self, monkeypatch):
        """T2F: In single_tenant, resolver uses bare table_name cache key and no tenant_id filter."""
        monkeypatch.setattr(
            "app.processing.tiles.router.is_multi_tenant", lambda: False
        )

        from app.processing.tiles import router as tile_router

        mock_record = MagicMock()
        mock_record.visibility = "public"
        mock_record.record_status = "published"
        mock_record.created_by = uuid.uuid4()
        mock_record.record_type = "vector_dataset"

        mock_dataset = MagicMock()
        mock_dataset.id = uuid.uuid4()
        mock_dataset.record_id = uuid.uuid4()
        mock_dataset.table_name = _TABLE
        mock_dataset.tenant_id = None
        mock_dataset.record = mock_record
        mock_dataset.geometry_type = "POINT"
        mock_dataset.column_info = []
        mock_dataset.tile_cache_ttl = None
        mock_dataset.tile_columns = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_dataset

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result

        from app.processing.tiles.router import _resolve_dataset_meta

        await _resolve_dataset_meta(_TABLE, mock_db)

        # In single_tenant, cache key must be bare table_name (no tenant prefix)
        with tile_router._dataset_cache_lock:
            cache_keys = list(tile_router._dataset_cache.keys())

        assert _TABLE in cache_keys, (
            f"Expected bare key {_TABLE!r} in single_tenant cache; got: {cache_keys}"
        )
        # Ensure no tenant-prefixed key exists
        assert not any(":" in k for k in cache_keys), (
            f"Found tenant-prefixed key in single_tenant cache: {cache_keys}"
        )
