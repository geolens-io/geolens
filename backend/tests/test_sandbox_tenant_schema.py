"""Tenant-schema binding regressions for the AI SQL sandbox."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db.tenant_session import current_tenant_var
from app.platform.sandbox.schemas import SandboxError


_TENANT_A = "00000000-0000-0000-0000-000000000001"
_TENANT_B = "00000000-0000-0000-0000-000000000002"
_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"
_ROLE_A = "geolens_reader_t_00000000_0000_0000_0000_000000000001"
_ROLE_B = "geolens_reader_t_00000000_0000_0000_0000_000000000002"


def _mock_engine(executed: list[str], *, fail_role: str | None = None) -> MagicMock:
    async def _execute(stmt, *args, **kwargs):
        rendered = str(stmt)
        executed.append(rendered)
        if fail_role is not None and rendered == f"SET LOCAL ROLE {fail_role}":
            raise RuntimeError("role binding denied")
        result = MagicMock()
        result.keys.return_value = []
        result.fetchall.return_value = []
        return result

    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=False)

    conn = AsyncMock()
    conn.execute.side_effect = _execute
    conn.begin = MagicMock(return_value=transaction)

    connection = MagicMock()
    connection.__aenter__ = AsyncMock(return_value=conn)
    connection.__aexit__ = AsyncMock(return_value=False)

    engine = MagicMock()
    engine.connect.return_value = connection
    return engine


def test_schema_rewrite_preserves_pgvector_cosine_operator():
    """fix(#557): the rewrite re-renders the parsed AST, and sqlglot mis-parses
    pgvector ``<=>`` as NullSafeEQ. Without the sentinel guard the schema rewrite
    silently turns cosine nearest-neighbor ranking into ``IS NOT DISTINCT FROM``,
    returning the wrong rows in multi-tenant. The operator must survive and the
    logical ``data`` schema must still be translated."""
    from app.platform.sandbox.executor import _rewrite_logical_data_schema

    sql = (
        "SELECT name, embedding <=> '[1,2,3]'::vector AS distance "
        "FROM data.records ORDER BY distance LIMIT 10"
    )
    rewritten = _rewrite_logical_data_schema(sql, _SCHEMA_A)

    assert "<=>" in rewritten
    assert "IS NOT DISTINCT FROM" not in rewritten
    assert f'"{_SCHEMA_A}".records' in rewritten
    assert "data.records" not in rewritten


def test_schema_rewrite_preserves_l2_and_cosine_together():
    """Both advertised distance operators survive the rewrite: ``<->`` already
    round-trips, ``<=>`` is protected by the sentinel swap."""
    from app.platform.sandbox.executor import _rewrite_logical_data_schema

    sql = (
        "SELECT id, embedding <=> '[1]'::vector AS cos "
        "FROM data.t ORDER BY embedding <-> '[2]'::vector LIMIT 5"
    )
    rewritten = _rewrite_logical_data_schema(sql, _SCHEMA_A)

    assert rewritten.count("<=>") == 1
    assert rewritten.count("<->") == 1
    assert "IS NOT DISTINCT FROM" not in rewritten
    assert f'"{_SCHEMA_A}".t' in rewritten


@pytest.mark.asyncio
async def test_multi_tenant_rewrites_only_logical_data_schema(monkeypatch):
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    executed: list[str] = []
    import app.core.db as db_module
    from app.platform.sandbox.executor import execute_safe

    token = current_tenant_var.set(_TENANT_A)
    try:
        with patch.object(db_module, "engine", _mock_engine(executed)):
            await execute_safe(
                MagicMock(),
                "SELECT data.alpha.id FROM data.alpha "
                "JOIN data.beta ON data.beta.id = data.alpha.id "
                "WHERE data.alpha.note = 'data.alpha'",
            )
    finally:
        current_tenant_var.reset(token)

    query = next(
        statement for statement in executed if statement.startswith("SELECT *")
    )
    assert f'"{_SCHEMA_A}".alpha' in query
    assert f'"{_SCHEMA_A}".beta' in query
    assert f'"{_SCHEMA_A}".alpha.id' in query
    assert f'"{_SCHEMA_A}".beta.id' in query
    assert "FROM data.alpha" not in query
    assert "JOIN data.beta" not in query
    assert "data.alpha.id" not in query
    assert "data.beta.id" not in query
    assert "'data.alpha'" in query


@pytest.mark.asyncio
async def test_multi_tenant_role_binding_failure_is_fatal(monkeypatch):
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    executed: list[str] = []
    import app.core.db as db_module
    from app.platform.sandbox.executor import execute_safe

    token = current_tenant_var.set(_TENANT_A)
    try:
        with patch.object(
            db_module,
            "engine",
            _mock_engine(executed, fail_role=_ROLE_A),
        ):
            with pytest.raises(SandboxError) as exc_info:
                await execute_safe(MagicMock(), "SELECT id FROM data.alpha")
    finally:
        current_tenant_var.reset(token)

    assert exc_info.value.category == "query_failed"
    assert f"SET LOCAL ROLE {_ROLE_A}" in executed
    assert not any(statement.startswith("SELECT *") for statement in executed)


_requires_test_db = pytest.mark.skipif(
    not os.environ.get("POSTGRES_HOST"),
    reason="Requires test DB (set POSTGRES_HOST in .env.test)",
)


@pytest.mark.asyncio
@_requires_test_db
async def test_logical_data_query_reads_only_active_tenant_schema(monkeypatch):
    """The same logical query resolves to different physical tenant tables."""
    monkeypatch.setattr("app.platform.sandbox.executor.is_multi_tenant", lambda: True)
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)

    from app.core.config import settings
    from app.platform.sandbox.executor import execute_safe

    table = f"sandbox_tenant_{uuid.uuid4().hex[:12]}"
    engine = create_async_engine(settings.test_database_url, poolclass=NullPool)
    import app.core.db as db_module

    try:
        async with engine.begin() as conn:
            for schema, role, marker in (
                (_SCHEMA_A, _ROLE_A, "tenant-a"),
                (_SCHEMA_B, _ROLE_B, "tenant-b"),
            ):
                await conn.execute(
                    sa.text(f'CREATE TABLE {schema}."{table}" (marker text NOT NULL)')
                )
                await conn.execute(
                    sa.text(
                        f'INSERT INTO {schema}."{table}" (marker) VALUES (:marker)'
                    ),
                    {"marker": marker},
                )
                await conn.execute(
                    sa.text(f'GRANT SELECT ON {schema}."{table}" TO {role}')
                )

        observed: dict[str, str] = {}
        with patch.object(db_module, "engine", engine):
            for tenant_id in (_TENANT_A, _TENANT_B):
                token = current_tenant_var.set(tenant_id)
                try:
                    result = await execute_safe(
                        MagicMock(),
                        f'SELECT data."{table}".marker FROM data."{table}"',
                    )
                finally:
                    current_tenant_var.reset(token)
                observed[tenant_id] = result.rows[0][0]

        assert observed == {_TENANT_A: "tenant-a", _TENANT_B: "tenant-b"}
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f'DROP TABLE IF EXISTS {_SCHEMA_A}."{table}"'))
            await conn.execute(sa.text(f'DROP TABLE IF EXISTS {_SCHEMA_B}."{table}"'))
        await engine.dispose()
