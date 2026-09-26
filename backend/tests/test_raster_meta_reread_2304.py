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
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text

from app.platform.cache.tile_cache import InMemoryTileCacheProvider
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
def _counting_statements(marker: str, param: str):
    """Record when each SELECT containing ``marker`` and naming ``param`` runs."""
    import app.core.db as db_module

    reads: list[float] = []

    def on_execute(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and marker in statement
            and param in str(parameters)
        ):
            reads.append(time.monotonic())

    engine = db_module.engine.sync_engine
    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield reads
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


def _counting_raster_reads(dataset_id: uuid.UUID):
    """Record when each raster metadata read for ``dataset_id`` runs."""
    return _counting_statements("raster_assets", str(dataset_id))


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


async def test_an_unreached_v_re_reads_the_row_at_most_once_per_interval(
    client: AsyncClient, test_db_session, monkeypatch
):
    """Each of these requests waits for a read of its own, an interval apart.

    No row reaches the version, and a read that started before a request
    arrived cannot answer it, so every request in the sequence needs the next
    interval's read.
    """
    interval = 0.2
    monkeypatch.setattr(tile_router, "_FORCED_REREAD_INTERVAL", interval)
    dataset = await _public_raster(test_db_session)
    try:
        assert (await _auth_check(client, dataset.id)).status_code == 200
        with _counting_raster_reads(dataset.id) as reads:
            for _ in range(4):
                resp = await _auth_check(client, dataset.id, _UNREACHED_VERSION)
                assert resp.status_code == 200, resp.text
                assert resp.headers["X-GeoLens-Cache-Status"] == "private"

        assert len(reads) == 4
        gaps = [later - earlier for earlier, later in zip(reads, reads[1:])]
        assert min(gaps) >= 0.8 * interval, gaps
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


async def _on_own_session(resolve, version):
    """Resolve as a tile request does, on a session it closes after."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        return await resolve(session, version)


@pytest.mark.parametrize("case", [_vector_case, _raster_case], ids=["vector", "raster"])
async def test_the_first_request_after_a_commit_is_not_served_a_speculative_read(
    test_db_session, case
):
    """A read forced for a version before it committed cannot answer for it after.

    The speculative request opens the interval while the row is still at the
    old version. The request naming the new version after the commit waits
    for the next read instead of taking the snapshot the first one left.
    """
    _, _, resolve, advance, forget = await case(test_db_session)
    try:
        await resolve(test_db_session)
        speculative = await _on_own_session(resolve, "2")
        await advance()
        after = await asyncio.wait_for(_on_own_session(resolve, "2"), timeout=5)

        assert speculative.tile_cache_version == 1
        assert after.tile_cache_version == 2
    finally:
        forget()


@pytest.mark.parametrize("case", [_vector_case, _raster_case], ids=["vector", "raster"])
async def test_a_read_that_began_before_the_commit_cannot_answer_after_it(
    test_db_session, case
):
    """The same rule while the old read is still running when the request arrives."""
    import app.core.db as db_module

    _, _, resolve, advance, forget = await case(test_db_session)
    queried, released, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def speculative_request():
        async with db_module.async_session() as session:
            execute = session.execute

            # The query sees the old row, then the read stays in flight.
            async def query_then_hold(*args, **kwargs):
                result = await execute(*args, **kwargs)
                queried.set()
                await released.wait()
                return result

            session.execute = query_then_hold
            return await resolve(session, "2")

    async def request_after_the_commit():
        async with db_module.async_session() as session:
            commit = session.commit

            # A waiter releases its connection just before it starts waiting.
            async def commit_then_signal():
                await commit()
                waiting.set()

            session.commit = commit_then_signal
            return await resolve(session, "2")

    try:
        await resolve(test_db_session)
        speculative = asyncio.create_task(speculative_request())
        await asyncio.wait_for(queried.wait(), timeout=5)
        await advance()
        after = asyncio.create_task(request_after_the_commit())
        await asyncio.wait_for(waiting.wait(), timeout=5)
        released.set()
        metas = await asyncio.wait_for(asyncio.gather(speculative, after), timeout=10)

        assert [meta.tile_cache_version for meta in metas] == [1, 2]
    finally:
        released.set()
        forget()


async def _vector_http_case(client, session, tmp_path):
    """A seeded public point dataset, served through the vector tile route."""
    from tests.test_tile_cache_content_key_2290 import _drop_table, _seed

    _, dataset, _ = await _seed(session, tmp_path)
    table = dataset.table_name

    async def fetch(version=None):
        params = {} if version is None else {"_v": version}
        resp = await client.get(f"/tiles/data.{table}/0/0/0.pbf", params=params)
        assert resp.status_code == 200, resp.text
        return resp.headers["cache-control"]

    async def cleanup():
        tile_router._evict_dataset_meta(table)
        await _drop_table(session, table)

    return fetch, _counting_statements("catalog.records", table), "no-store", cleanup


async def _raster_http_case(client, session, tmp_path):
    """A public raster, served through the auth check the raster proxy runs."""
    dataset = await _public_raster(session)

    async def fetch(version=None):
        resp = await _auth_check(client, dataset.id, version)
        assert resp.status_code == 200, resp.text
        return resp.headers["X-GeoLens-Cache-Status"]

    async def cleanup():
        _forget(dataset.id)

    return fetch, _counting_raster_reads(dataset.id), "private", cleanup


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
@pytest.mark.parametrize(
    "case", [_vector_http_case, _raster_http_case], ids=["vector", "raster"]
)
async def test_unreached_versions_asked_for_during_the_interval_share_one_read(
    client: AsyncClient, test_db_session, tmp_path, case
):
    """Concurrent requests for an unreached version wait out the interval together.

    Twenty arrive inside the interval a first such request opened. Each gets the
    old snapshot, sent uncacheable, within about an interval, and the row is
    read at most once per elapsed interval.
    """
    fetch, counting, uncacheable, cleanup = await case(
        client, test_db_session, tmp_path
    )
    interval = tile_router._FORCED_REREAD_INTERVAL

    async def timed_fetch():
        started = time.monotonic()
        header = await fetch(_UNREACHED_VERSION)
        return header, time.monotonic() - started

    try:
        with patch.object(
            tile_router, "get_tile_cache", return_value=InMemoryTileCacheProvider()
        ):
            await fetch()
            assert await fetch(_UNREACHED_VERSION) == uncacheable
            with counting as reads:
                started = time.monotonic()
                results = await asyncio.wait_for(
                    asyncio.gather(*(timed_fetch() for _ in range(20))), timeout=15
                )
                elapsed = time.monotonic() - started

        for header, took in results:
            assert header == uncacheable
            assert took < interval + 1.0, took
        assert len(reads) <= 1 + elapsed // interval, (len(reads), elapsed)
    finally:
        await cleanup()
