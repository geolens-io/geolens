"""A raster tile request's ``v`` re-reads the dataset at most once a second.

The raster metadata cache used to look entries up under the request's ``v``
and store them under the row's version, so a ``v`` the row had not reached,
or one it had moved past, missed on every request and ran the joined raster
query each time. Raster now shares the vector path's snapshot: one per
dataset, re-read when a request names a newer version, at most once per
interval, with concurrent requests waiting on that one read.
"""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text

from app.processing.tiles import router as tile_router

from tests.factories import get_user_id
from tests.test_perf002_raster_meta_cache import (
    _create_public_raster,
    _swap_raster_pointer,
)

# Newer than any row reaches, so every request carrying it asks for a re-read.
_UNREACHED_VERSION = "9999999999"


async def _public_raster(session):
    return await _create_public_raster(
        session, created_by=await get_user_id(session, "admin")
    )


@contextlib.contextmanager
def _counting_raster_reads(dataset_id: uuid.UUID):
    """Count the raster metadata reads for ``dataset_id`` that reach the database."""
    import app.core.db as db_module

    reads: list[str] = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        if "raster_assets" in statement and str(dataset_id) in str(parameters):
            reads.append(statement)

    engine = db_module.engine.sync_engine
    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield reads
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def _age_raster_claim(dataset_id: uuid.UUID) -> None:
    """Put the dataset's last forced re-read past its interval."""
    key = str(dataset_id)
    with tile_router._raster_meta_cache_lock:
        claimed_at = tile_router._raster_forced_rereads[key]
        tile_router._raster_forced_rereads[key] = (
            claimed_at - tile_router._FORCED_REREAD_INTERVAL
        )


def _forget(dataset_id: uuid.UUID) -> None:
    with tile_router._raster_meta_cache_lock:
        tile_router._raster_meta_cache.pop(str(dataset_id), None)


async def _auth_check(
    client: AsyncClient,
    dataset_id: uuid.UUID,
    version: str | None = None,
    headers: dict | None = None,
):
    params = {"dataset_id": str(dataset_id)}
    if version is not None:
        params["v"] = version
    return await client.get(
        "/tiles/raster-auth-check/", params=params, headers=headers or {}
    )


async def _meta_for_request(dataset_id: uuid.UUID, version: str):
    """Resolve raster metadata as a tile request does, on a session of its own."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        return await tile_router._resolve_raster_meta(session, dataset_id, version)


async def test_an_unreached_v_re_reads_the_row_once_per_interval(
    client: AsyncClient, test_db_session
):
    dataset = await _public_raster(test_db_session)
    try:
        assert (await _auth_check(client, dataset.id)).status_code == 200
        with _counting_raster_reads(dataset.id) as reads:
            for _ in range(20):
                resp = await _auth_check(client, dataset.id, _UNREACHED_VERSION)
                assert resp.status_code == 200, resp.text
                assert resp.headers["X-GeoLens-Cache-Status"] == "private"
            assert len(reads) == 1

            _age_raster_claim(dataset.id)
            for _ in range(20):
                await _auth_check(client, dataset.id, _UNREACHED_VERSION)
            assert len(reads) == 2
    finally:
        _forget(dataset.id)


async def test_a_v_the_row_has_moved_past_is_served_without_re_reading(
    client: AsyncClient, test_db_session
):
    dataset = await _public_raster(test_db_session)
    try:
        await _auth_check(client, dataset.id)
        new_uri = await _swap_raster_pointer(test_db_session, dataset.id)
        caught_up = await _auth_check(client, dataset.id, "2")
        assert new_uri in caught_up.headers["X-GeoLens-Asset-OpenPath"]

        with _counting_raster_reads(dataset.id) as reads:
            for _ in range(20):
                behind = await _auth_check(client, dataset.id, "1")
                assert behind.status_code == 200, behind.text
                assert new_uri in behind.headers["X-GeoLens-Asset-OpenPath"]
                assert behind.headers["X-GeoLens-Cache-Status"] == "private"
        assert reads == []
    finally:
        _forget(dataset.id)


async def test_concurrent_requests_after_a_replace_share_one_read(test_db_session):
    dataset = await _public_raster(test_db_session)
    try:
        await _meta_for_request(dataset.id, "1")
        new_uri = await _swap_raster_pointer(test_db_session, dataset.id)
        with _counting_raster_reads(dataset.id) as reads:
            metas = await asyncio.wait_for(
                asyncio.gather(*(_meta_for_request(dataset.id, "2") for _ in range(5))),
                timeout=10,
            )
        assert [meta.tile_cache_version for meta in metas] == [2] * 5
        assert {meta.asset_uri for meta in metas} == {new_uri}
        assert len(reads) == 1
    finally:
        _forget(dataset.id)


async def test_a_cancelled_claimant_s_read_is_taken_over(test_db_session):
    """A request waiting on a cancelled claimant's read makes the read itself."""
    import app.core.db as db_module

    dataset = await _public_raster(test_db_session)
    entered, release = asyncio.Event(), asyncio.Event()
    started: list[str] = []

    async def request_meta():
        async with db_module.async_session() as session:
            execute = session.execute

            # Holds each read open, so the cancel lands while one is in flight.
            async def read_once_released(*args, **kwargs):
                started.append("read")
                entered.set()
                await release.wait()
                return await execute(*args, **kwargs)

            session.execute = read_once_released
            return await tile_router._resolve_raster_meta(session, dataset.id, "2")

    try:
        await _meta_for_request(dataset.id, "1")
        await _swap_raster_pointer(test_db_session, dataset.id)
        with _counting_raster_reads(dataset.id) as reads:
            claimant = asyncio.create_task(request_meta())
            await asyncio.wait_for(entered.wait(), timeout=5)
            waiting = [asyncio.create_task(request_meta()) for _ in range(4)]
            await asyncio.sleep(0)
            claimant.cancel()
            release.set()
            metas = await asyncio.wait_for(asyncio.gather(*waiting), timeout=5)

        assert claimant.cancelled()
        assert [meta.tile_cache_version for meta in metas] == [2] * 4
        # The claimant's read never reached the database; one waiter's did.
        assert started == ["read", "read"]
        assert len(reads) == 1
    finally:
        _forget(dataset.id)


class _Titiler:
    async def get(self, _url):
        return SimpleNamespace(
            status_code=200, content=b"png", headers={"content-type": "image/png"}
        )


@pytest.mark.parametrize(
    "version,cache_control",
    [
        (None, "public, max-age=3600"),
        ("1", "public, max-age=3600"),
        ("0", "private, no-store"),
    ],
    ids=["no-v", "v-equal", "v-older"],
)
async def test_a_v_not_newer_than_the_row_keeps_todays_headers(
    client: AsyncClient, test_db_session, version, cache_control
):
    dataset = await _public_raster(test_db_session)
    path = f"/tiles/raster-proxy/{dataset.id}/0/0/0.png"
    try:
        with patch.object(tile_router, "_titiler_client", _Titiler()):
            resp = await client.get(
                path, params={} if version is None else {"v": version}
            )
        assert resp.status_code == 200, resp.text
        assert resp.headers["cache-control"] == cache_control
    finally:
        _forget(dataset.id)


async def test_an_authenticated_forced_re_read_completes_on_a_one_connection_pool(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """Bearer resolution holds the request's only connection for the whole request."""
    import app.core.db as db_module
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.main import app
    from app.core.config import settings
    from app.core.dependencies import get_db

    dataset = await _public_raster(test_db_session)
    one_connection = create_async_engine(
        settings.test_database_url, pool_size=1, max_overflow=0, pool_timeout=2
    )
    sessions = async_sessionmaker(one_connection, expire_on_commit=False)

    async def get_db_on_one_connection():
        async with sessions() as session:
            yield session

    try:
        await _auth_check(client, dataset.id, "1")
        new_uri = await _swap_raster_pointer(test_db_session, dataset.id)
        monkeypatch.setitem(app.dependency_overrides, get_db, get_db_on_one_connection)
        monkeypatch.setattr(db_module, "async_session", sessions)
        resp = await asyncio.wait_for(
            _auth_check(client, dataset.id, "2", headers=admin_auth_header),
            timeout=15,
        )

        assert resp.status_code == 200, resp.text
        assert new_uri in resp.headers["X-GeoLens-Asset-OpenPath"]
        assert resp.headers["X-GeoLens-Cache-Status"] == "public"
    finally:
        await one_connection.dispose()
        _forget(dataset.id)


async def _vector_case(session):
    """A registered vector dataset, how to resolve it, and how to advance it."""
    from tests.test_tile_cache_content_key_2290 import (
        _bump_tile_cache_version,
        _registered_dataset,
    )

    dataset = await _registered_dataset(session)
    table = dataset.table_name

    async def resolve(db, version=None):
        return await tile_router._resolve_dataset_meta(table, db, version)

    async def advance():
        await _bump_tile_cache_version(session, dataset.id)

    def forget():
        tile_router._evict_dataset_meta(table)

    return table, tile_router._rereads_in_flight, resolve, advance, forget


async def _raster_case(session):
    """A public raster, how to resolve it, and how to replace it."""
    dataset = await _public_raster(session)

    async def resolve(db, version=None):
        return await tile_router._resolve_raster_meta(db, dataset.id, version)

    async def advance():
        await _swap_raster_pointer(session, dataset.id)

    def forget():
        _forget(dataset.id)

    return (
        str(dataset.id),
        tile_router._raster_rereads_in_flight,
        resolve,
        advance,
        forget,
    )


async def _claimed(in_flight: dict, key: str) -> None:
    while key not in in_flight:
        await asyncio.sleep(0.01)


@pytest.mark.parametrize("case", [_vector_case, _raster_case], ids=["vector", "raster"])
async def test_a_waiter_holding_the_only_connection_lets_the_claimant_read(
    test_db_session, case
):
    """An authenticated waiter must not sit on the connection its claimant needs.

    The waiter's identity lookup has taken the pool's only connection when an
    anonymous request, holding none, claims the re-read and needs one to run it.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings

    key, in_flight, resolve, advance, forget = await case(test_db_session)
    one_connection = create_async_engine(
        settings.test_database_url, pool_size=1, max_overflow=0, pool_timeout=2
    )
    sessions = async_sessionmaker(one_connection, expire_on_commit=False)
    waiter_session, claimant_session = sessions(), sessions()
    try:
        await resolve(test_db_session)
        await advance()
        await waiter_session.execute(text("SELECT 1"))

        claimant = asyncio.create_task(resolve(claimant_session, "2"))
        await asyncio.wait_for(_claimed(in_flight, key), timeout=5)
        waiter = asyncio.create_task(resolve(waiter_session, "2"))
        metas = await asyncio.wait_for(asyncio.gather(claimant, waiter), timeout=10)

        assert [meta.tile_cache_version for meta in metas] == [2, 2]
    finally:
        await waiter_session.close()
        await claimant_session.close()
        await one_connection.dispose()
        forget()
