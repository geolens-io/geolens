"""The tile-pool acquisition carries a bound, so an exhausted pool sheds a tile
request with 429 instead of queueing it for as long as the caller waits."""

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


class _RecordingPool:
    """Records the bound the handler asks for, then answers as a full pool."""

    def __init__(self) -> None:
        self.timeout: float | None = None

    def acquire(self, *, timeout: float | None = None):
        self.timeout = timeout
        return self

    async def __aenter__(self):
        raise TimeoutError

    async def __aexit__(self, *_exc_info) -> bool:
        return False


async def _serve_one_tile() -> None:
    await tiles_router._acquire_and_serve_tile(
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
    )


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
                await asyncio.wait_for(_serve_one_tile(), timeout=5)
    finally:
        await pool.close()

    assert raised.value.status_code == 429
    assert raised.value.headers == {"Retry-After": "2"}


async def test_the_handler_asks_for_the_configured_bound(monkeypatch):
    """The wait budget is the handler's, not asyncpg's unbounded default."""
    pool = _RecordingPool()
    monkeypatch.setattr(tiles_router, "get_tile_pool", lambda: pool)

    with pytest.raises(HTTPException) as raised:
        await _serve_one_tile()

    assert pool.timeout == TILE_POOL_ACQUIRE_TIMEOUT_SECONDS
    assert raised.value.status_code == 429


async def test_the_command_timeout_is_a_separate_bound(monkeypatch):
    """Each command gets its own budget; the wait budget is not derived from it."""
    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(pool_module, "_tile_pool", None)
    monkeypatch.setattr(pool_module.asyncpg, "create_pool", _capture)
    monkeypatch.setattr(pool_module, "_parse_dsn", lambda: "postgresql://tiles/db")
    monkeypatch.setattr(pool_module, "_get_ssl_arg", lambda: None)

    await pool_module.init_tile_pool()

    assert captured["command_timeout"] == TILE_POOL_COMMAND_TIMEOUT_SECONDS
