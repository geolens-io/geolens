"""Vector and cluster misses share a fail-fast budget; cache hits bypass it."""

import asyncio
import uuid
from datetime import datetime, timezone
from threading import BoundedSemaphore
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from app.processing.tiles import admission
from app.processing.tiles import router as tiles


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
    monkeypatch.setattr(admission, "_render_slots", BoundedSemaphore(1))
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


@pytest.mark.parametrize("first,second", [("", "clusters/"), ("clusters/", "")])
async def test_mixed_misses_shed_before_catalog_probe_and_cache_hits_still_serve(
    serving, monkeypatch, first, second
):
    client, probe, cache = serving
    entered, release = asyncio.Event(), asyncio.Event()

    async def render(**kwargs):
        entered.set()
        await release.wait()
        return Response(status_code=204)

    monkeypatch.setattr(tiles, "_acquire_and_serve_tile", render)
    task = asyncio.create_task(client.get(f"/tiles/{first}data.roads/0/0/0.pbf"))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        response = await asyncio.wait_for(
            client.get(
                f"/tiles/{second}data.roads/0/0/0.pbf",
                headers={"Origin": "https://viewer.example"},
            ),
            1,
        )
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
        await task
    cache.get.return_value = None
    assert (await client.get(f"/tiles/{second}data.roads/0/0/0.pbf")).status_code == 204


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
    await asyncio.wait_for(waiting.wait(), 1)
    try:
        assert not api_connections.locked()
        response = await asyncio.wait_for(
            client.get(
                f"/tiles/{other_prefix}data.roads/0/0/0.pbf",
                headers={"X-Test-Tenant": other_tenant},
            ),
            1,
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
            1,
        )
    ).status_code == 204
    assert not waiting_quota.locked()


async def test_shared_capacity_rejection_returns_the_tenant_permit():
    quota = asyncio.Semaphore(1)
    slots = admission._render_slots
    held = 0
    try:
        while slots.acquire(blocking=False):
            held += 1
        with pytest.raises(tiles.HTTPException) as raised:
            async with admission.tile_render_slot(quota):
                pytest.fail("render entered a full budget")
        assert raised.value.status_code == 429
        assert not quota.locked()
    finally:
        for _ in range(held):
            slots.release()
