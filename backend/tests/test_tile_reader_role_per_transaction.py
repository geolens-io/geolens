"""Single-tenant tile requests run as geolens_reader only inside their own transaction."""

from __future__ import annotations

from types import SimpleNamespace

import asyncpg
import pytest

from app.core.config import settings
from app.processing.tiles import pool as pool_module
from app.processing.tiles.pool import set_tenant_role_for_tile_request


@pytest.fixture
async def one_connection_tile_pool(monkeypatch):
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: False)
    monkeypatch.setattr(
        pool_module,
        "settings",
        SimpleNamespace(
            tile_database_url=settings.test_database_url,
            tile_database_url_override=None,
            database_connect_args={},
            tile_pool_min_size=1,
            tile_pool_max_size=1,
            db_use_external_pooler=False,
        ),
    )
    pool = await pool_module.init_tile_pool()
    try:
        yield pool
    finally:
        await pool_module.close_tile_pool()


async def _identity(conn: asyncpg.Connection) -> tuple[str, str]:
    row = await conn.fetchrow("SELECT session_user, current_user")
    return row[0], row[1]


async def test_reader_role_never_outlives_the_tile_transaction(
    one_connection_tile_pool,
):
    # A transaction-mode pooler hands the server connection to the next
    # client between transactions, so any role left outside one leaks.
    for _ in range(2):
        async with one_connection_tile_pool.acquire() as conn:
            login, effective = await _identity(conn)
            assert effective == login

            async with conn.transaction():
                await set_tenant_role_for_tile_request(conn, None)
                _, effective = await _identity(conn)
                assert effective == "geolens_reader"

            login, effective = await _identity(conn)
            assert effective == login


class _RefusedRoleConnection:
    """Delegates to a real connection but asks for a role that doesn't exist."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self.statements: list[str] = []

    async def execute(self, query: str, *args):
        self.statements.append(query)
        query = query.replace("geolens_reader", "geolens_tile_role_missing")
        return await self._conn.execute(query, *args)


async def test_refused_reader_role_keeps_the_tile_transaction_usable(
    one_connection_tile_pool,
):
    async with one_connection_tile_pool.acquire() as conn:
        async with conn.transaction():
            proxy = _RefusedRoleConnection(conn)
            await set_tenant_role_for_tile_request(proxy, None)

            assert any("SET LOCAL ROLE geolens_reader" in s for s in proxy.statements)
            login, effective = await _identity(conn)
            assert effective == login
            assert await conn.fetchval("SELECT 1") == 1
