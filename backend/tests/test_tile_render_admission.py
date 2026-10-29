"""Vector and cluster misses share a briefly queued budget; cache hits bypass it."""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from app.processing.tiles import admission
from app.processing.tiles import router as tiles

# Time bounds here are hang guards: CI load can stretch any wait severalfold.
_HANG_GUARD = 30  # seconds
_SHORT_WAIT = 0.3  # seconds; only ever asserted as a lower bound


@pytest.fixture
async def serving(monkeypatch):
    meta = tiles._DatasetMeta(
        dataset_id=uuid.uuid4(),
        record_id=uuid.uuid4(),
        table_name="roads",
        visibility="public",
        record_status="published",
        created_by=uuid.uuid4(),
        record_type="vector_dataset",
        geometry_type="Point",
        column_info=[],
        tile_cache_ttl=60,
        tile_columns=None,
        publication_version=1,
        tile_cache_version=1,
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(admission, "_vector_renders", admission._RenderBudget(1))
    monkeypatch.setattr(admission, "_SLOT_WAIT_SECONDS", _HANG_GUARD)
    monkeypatch.setattr(
        tiles, "_resolve_dataset_meta_for_serving", AsyncMock(return_value=meta)
    )
    monkeypatch.setattr(
        tiles, "_authorize_vector_tile_request", AsyncMock(return_value="public")
    )
    monkeypatch.setattr(tiles, "_get_tile_serving_controls", lambda _: (None, None))
    monkeypatch.setattr(tiles, "_require_tile_tenant_context", lambda: None)
    monkeypatch.setattr(tiles, "_check_cold_rehydrate", AsyncMock(return_value=None))
    probe = AsyncMock()
    monkeypatch.setattr(tiles, "_assert_dataset_still_registered", probe)
    cache = AsyncMock()
    cache.get.return_value = None
    monkeypatch.setattr(tiles, "get_tile_cache", lambda: cache)
    app = FastAPI()
    app.include_router(tiles.router)
    app.dependency_overrides[tiles.get_db] = lambda: AsyncMock()
    app.dependency_overrides[tiles.get_optional_user_fail_open] = lambda: None
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, probe, cache


@pytest.fixture
def held_slot(serving, monkeypatch):
    """Renders block until ``release`` is set; ``rolled_back`` counts requests at admission."""
    client, _, _ = serving
    entered, release = asyncio.Event(), asyncio.Event()
    rolled_back: list[asyncio.Event] = []
    resolve_meta = tiles._resolve_dataset_meta_for_serving

    async def resolve(request, table_name, db, user):
        reached = asyncio.Event()
        rolled_back.append(reached)
        db.rollback.side_effect = reached.set
        return await resolve_meta(request, table_name, db, user)

    async def render(**kwargs):
        entered.set()
        await release.wait()
        return Response(status_code=204)

    monkeypatch.setattr(tiles, "_resolve_dataset_meta_for_serving", resolve)
    monkeypatch.setattr(tiles, "_acquire_and_serve_tile", render)

    async def start(path: str) -> asyncio.Task:
        """Send a miss and return once it has reached admission."""
        sent = len(rolled_back)
        task = asyncio.create_task(client.get(path))
        async with asyncio.timeout(_HANG_GUARD):
            while len(rolled_back) == sent:
                await asyncio.sleep(0)
            await rolled_back[sent].wait()
        # Long enough for an immediate rejection to finish.
        await asyncio.sleep(0.05)
        return task

    return start, entered, release


async def _first_render_holds_the_slot(start, entered, path):
    task = await start(path)
    await asyncio.wait_for(entered.wait(), _HANG_GUARD)
    return task


@pytest.mark.parametrize("first,second", [("", "clusters/"), ("clusters/", "")])
async def test_a_miss_waits_for_a_free_slot_without_holding_an_api_connection(
    serving, held_slot, monkeypatch, first, second
):
    _, probe, _ = serving
    start, entered, release = held_slot
    api_connections = asyncio.Semaphore(1)
    resolve = tiles._resolve_dataset_meta_for_serving

    async def resolve_holding_a_connection(request, table_name, db, user):
        await api_connections.acquire()
        meta = await resolve(request, table_name, db, user)
        marked_reached = db.rollback.side_effect

        def give_back():
            api_connections.release()
            marked_reached()

        db.rollback.side_effect = give_back
        return meta

    monkeypatch.setattr(
        tiles, "_resolve_dataset_meta_for_serving", resolve_holding_a_connection
    )
    holder = await _first_render_holds_the_slot(
        start, entered, f"/tiles/{first}data.roads/0/0/0.pbf"
    )
    waiter = await start(f"/tiles/{second}data.roads/0/0/0.pbf")
    try:
        assert not waiter.done()
        assert not api_connections.locked()
        assert probe.await_count == 1
    finally:
        release.set()
    assert (await asyncio.wait_for(holder, _HANG_GUARD)).status_code == 204
    assert (await asyncio.wait_for(waiter, _HANG_GUARD)).status_code == 204
    assert probe.await_count == 2


@pytest.mark.parametrize("first,second", [("", "clusters/"), ("clusters/", "")])
async def test_a_miss_that_outwaits_the_queue_sheds_before_catalog_probe(
    serving, held_slot, monkeypatch, first, second
):
    client, probe, cache = serving
    start, entered, release = held_slot
    monkeypatch.setattr(admission, "_SLOT_WAIT_SECONDS", _SHORT_WAIT)
    holder = await _first_render_holds_the_slot(
        start, entered, f"/tiles/{first}data.roads/0/0/0.pbf"
    )
    try:
        began = time.monotonic()
        response = await asyncio.wait_for(
            client.get(
                f"/tiles/{second}data.roads/0/0/0.pbf",
                headers={"Origin": "https://viewer.example"},
            ),
            _HANG_GUARD,
        )
        assert time.monotonic() - began >= _SHORT_WAIT * 0.9
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "2"
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert response.headers["Access-Control-Expose-Headers"] == "Retry-After"
        assert response.headers["Cache-Control"] == "no-store"
        assert probe.await_count == 1
        cache.get.return_value = b""
        assert (
            await client.get(f"/tiles/{second}data.roads/0/0/0.pbf")
        ).status_code == 204
        assert probe.await_count == 1
    finally:
        release.set()
        await holder
    cache.get.return_value = None
    assert (await client.get(f"/tiles/{second}data.roads/0/0/0.pbf")).status_code == 204


async def test_misses_beyond_the_waiter_cap_shed_at_once(
    serving, held_slot, monkeypatch
):
    client, _, _ = serving
    start, entered, release = held_slot
    monkeypatch.setattr(admission._vector_renders, "max_waiters", 1)
    holder = await _first_render_holds_the_slot(
        start, entered, "/tiles/data.roads/0/0/0.pbf"
    )
    waiter = await start("/tiles/clusters/data.roads/0/0/0.pbf")
    try:
        assert not waiter.done()
        response = await asyncio.wait_for(
            client.get("/tiles/data.roads/0/0/0.pbf"), _HANG_GUARD
        )
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "2"
        assert not waiter.done()
    finally:
        release.set()
    assert (await asyncio.wait_for(holder, _HANG_GUARD)).status_code == 204
    assert (await asyncio.wait_for(waiter, _HANG_GUARD)).status_code == 204


async def test_a_cancelled_waiter_returns_only_what_it_took(
    serving, held_slot, monkeypatch
):
    client, _, _ = serving
    start, entered, release = held_slot
    quota = asyncio.Semaphore(2)
    monkeypatch.setattr(tiles, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tiles, "_get_tile_serving_controls", lambda _: (quota, None))
    monkeypatch.setattr(admission._vector_renders, "max_waiters", 1)
    holder = await _first_render_holds_the_slot(
        start, entered, "/tiles/data.roads/0/0/0.pbf"
    )
    waiter = await start("/tiles/clusters/data.roads/0/0/0.pbf")
    try:
        assert not waiter.done()
        assert quota.locked()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        # The waiter's tenant permit and queue place come back; the holder's
        # render slot does not, so the next miss queues and then sheds.
        assert not quota.locked()
        monkeypatch.setattr(admission, "_SLOT_WAIT_SECONDS", _SHORT_WAIT)
        began = time.monotonic()
        response = await asyncio.wait_for(
            client.get("/tiles/data.roads/0/0/0.pbf"), _HANG_GUARD
        )
        assert time.monotonic() - began >= _SHORT_WAIT * 0.9
        assert response.status_code == 429
    finally:
        release.set()
    assert (await asyncio.wait_for(holder, _HANG_GUARD)).status_code == 204
    assert (await client.get("/tiles/data.roads/0/0/0.pbf")).status_code == 204
    assert not admission._vector_renders.slots.locked()
    assert not quota.locked()


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_render_slot_is_released_when_work_fails(serving, monkeypatch, failure):
    client, probe, _ = serving
    quota = asyncio.Semaphore(1)
    monkeypatch.setattr(tiles, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tiles, "_get_tile_serving_controls", lambda _: (quota, None))
    probe.side_effect = failure
    with pytest.raises(failure):
        await client.get("/tiles/data.roads/0/0/0.pbf")
    assert not quota.locked()
    probe.side_effect = None
    monkeypatch.setattr(
        tiles,
        "_acquire_and_serve_tile",
        AsyncMock(return_value=Response(status_code=204)),
    )
    assert (await client.get("/tiles/clusters/data.roads/0/0/0.pbf")).status_code == 204


@pytest.mark.parametrize(
    "waiting_prefix,other_prefix", [("", "clusters/"), ("clusters/", "")]
)
async def test_waiting_tenant_does_not_reserve_another_tenants_capacity(
    serving, monkeypatch, waiting_prefix, other_prefix
):
    from contextvars import ContextVar
    from types import SimpleNamespace

    client, probe, _ = serving
    waiting_tenant, other_tenant = str(uuid.uuid4()), str(uuid.uuid4())
    request_tenant = ContextVar("request_tenant")
    waiting_quota = asyncio.Semaphore(0)
    other_quota = asyncio.Semaphore(1)
    waiting = asyncio.Event()
    api_connections = asyncio.Semaphore(1)
    resolve_meta = tiles._resolve_dataset_meta_for_serving

    async def acquire_waiting_quota():
        waiting.set()
        return await waiting_quota.acquire()

    async def resolve(request, table_name, db, user):
        request_tenant.set(request.headers["X-Test-Tenant"])
        await api_connections.acquire()
        released = False

        async def release_connection():
            nonlocal released
            if not released:
                api_connections.release()
                released = True

        db.rollback.side_effect = release_connection
        return await resolve_meta(request, table_name, db, user)

    waiting_limiter = SimpleNamespace(
        acquire=acquire_waiting_quota, release=waiting_quota.release
    )
    monkeypatch.setattr(tiles, "_resolve_dataset_meta_for_serving", resolve)
    monkeypatch.setattr(tiles, "_require_tile_tenant_context", request_tenant.get)
    monkeypatch.setattr(tiles, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(
        tiles,
        "_get_tile_serving_controls",
        lambda tenant: (
            waiting_limiter if tenant == waiting_tenant else other_quota,
            None,
        ),
    )
    monkeypatch.setattr(
        tiles,
        "_acquire_and_serve_tile",
        AsyncMock(return_value=Response(status_code=204)),
    )
    task = asyncio.create_task(
        client.get(
            f"/tiles/{waiting_prefix}data.roads/0/0/0.pbf",
            headers={"X-Test-Tenant": waiting_tenant},
        )
    )
    await asyncio.wait_for(waiting.wait(), _HANG_GUARD)
    try:
        assert not api_connections.locked()
        response = await asyncio.wait_for(
            client.get(
                f"/tiles/{other_prefix}data.roads/0/0/0.pbf",
                headers={"X-Test-Tenant": other_tenant},
            ),
            _HANG_GUARD,
        )
        assert response.status_code == 204
        assert probe.await_count == 1
        assert not other_quota.locked()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert waiting_quota.locked()
    waiting_quota.release()
    assert (
        await asyncio.wait_for(
            client.get(
                f"/tiles/{waiting_prefix}data.roads/0/0/0.pbf",
                headers={"X-Test-Tenant": waiting_tenant},
            ),
            _HANG_GUARD,
        )
    ).status_code == 204
    assert not waiting_quota.locked()


@pytest.mark.parametrize("max_waiters", [0, 1])
async def test_shared_capacity_rejection_returns_the_tenant_permit(
    monkeypatch, max_waiters
):
    quota = asyncio.Semaphore(1)
    budget = admission._RenderBudget(1)
    budget.max_waiters = max_waiters
    await budget.slots.acquire()
    monkeypatch.setattr(admission, "_vector_renders", budget)
    monkeypatch.setattr(admission, "_SLOT_WAIT_SECONDS", 0.01)
    with pytest.raises(tiles.HTTPException) as raised:
        async with admission.tile_render_slot(quota):
            pytest.fail("render entered a full budget")
    assert raised.value.status_code == 429
    assert not quota.locked()
    assert budget.waiters == 0
    budget.slots.release()
