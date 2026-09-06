"""The tile-pool acquisition is bounded by the pool's own command timeout, so
an exhausted pool sheds a tile request with 429 instead of queueing it."""

import asyncio

import asyncpg
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.config import settings
from app.processing.tiles import pool as pool_module
from app.processing.tiles import router as tiles_router
from app.processing.tiles.pool import (
    TILE_POOL_ACQUIRE_TIMEOUT_SECONDS,
    TILE_POOL_COMMAND_TIMEOUT_SECONDS,
)


def _bare_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


async def _never_runs(pool, conn) -> bytes | None:
    raise AssertionError("the query ran despite an exhausted pool")


async def test_an_exhausted_pool_sheds_the_request_with_429(monkeypatch):
    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=1,
        max_size=1,
        command_timeout=TILE_POOL_COMMAND_TIMEOUT_SECONDS,
    )
    monkeypatch.setattr(pool_module, "_tile_pool", pool)
    monkeypatch.setattr(tiles_router, "TILE_POOL_ACQUIRE_TIMEOUT_SECONDS", 0.25)

    try:
        async with pool.acquire():
            # The outer bound makes an unbounded acquire fail here rather than
            # hang the suite.
            with pytest.raises(HTTPException) as raised:
                await asyncio.wait_for(
                    tiles_router._acquire_and_serve_tile(
                        request=_bare_request(),
                        table_name="backpressure_probe",
                        z=0,
                        x=0,
                        y=0,
                        tid=None,
                        schema="data",
                        query_callable=_never_runs,
                        tile_cache=None,
                        cache_key="backpressure_probe",
                        cache_ttl=60,
                        base_headers={},
                    ),
                    timeout=5,
                )
    finally:
        await pool.close()

    assert raised.value.status_code == 429
    assert raised.value.headers == {"Retry-After": "2"}


async def test_the_acquire_bound_is_the_pools_command_timeout(monkeypatch):
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(pool_module, "_tile_pool", None)
    monkeypatch.setattr(pool_module.asyncpg, "create_pool", _capture)
    monkeypatch.setattr(pool_module, "_parse_dsn", lambda: "postgresql://tiles/db")
    monkeypatch.setattr(pool_module, "_get_ssl_arg", lambda: None)

    await pool_module.init_tile_pool()

    assert captured["command_timeout"] == TILE_POOL_ACQUIRE_TIMEOUT_SECONDS
