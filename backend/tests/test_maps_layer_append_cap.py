"""Appending a layer honours the per-map layer limit that full saves enforce.

Full replacement, layer diffs and style imports all refuse a map past
``_MAX_LAYERS_PER_MAP``. A map grown past it through repeated appends could then
not be saved from the builder until its owner deleted the excess, so the append
route has to refuse the layer that would cross the line, under a row lock so
that two appends at the boundary cannot both pass.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select, text

from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.schemas import _MAX_LAYERS_PER_MAP

from tests.factories import create_dataset, get_user_id


async def _map_with_layers(
    client: AsyncClient, headers: dict, session, count: int
) -> tuple[str, uuid.UUID]:
    """A map holding ``count`` layers of one dataset, plus that dataset's id."""
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    resp = await client.post(
        "/maps/", json={"name": f"Cap {uuid.uuid4().hex[:6]}"}, headers=headers
    )
    assert resp.status_code == 201
    map_id = resp.json()["id"]
    session.add_all(
        MapLayer(
            map_id=uuid.UUID(map_id),
            dataset_id=dataset.id,
            sort_order=position,
            layer_type="vector_geolens",
        )
        for position in range(count)
    )
    await session.commit()
    return map_id, dataset.id


async def _layer_count(session, map_id: str) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(MapLayer)
            .where(MapLayer.map_id == uuid.UUID(map_id))
        )
    ).scalar_one()


async def _append(client: AsyncClient, headers: dict, map_id: str, dataset_id):
    return await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(dataset_id)},
        headers=headers,
    )


@pytest.mark.anyio
async def test_the_layer_past_the_limit_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    map_id, dataset_id = await _map_with_layers(
        client, admin_auth_header, test_db_session, _MAX_LAYERS_PER_MAP - 1
    )

    last_allowed = await _append(client, admin_auth_header, map_id, dataset_id)
    refused = await _append(client, admin_auth_header, map_id, dataset_id)

    assert last_allowed.status_code == 201
    assert refused.status_code == 422
    assert str(_MAX_LAYERS_PER_MAP) in refused.json()["detail"]
    assert await _layer_count(test_db_session, map_id) == _MAX_LAYERS_PER_MAP


@pytest.mark.anyio
async def test_two_appends_at_the_boundary_admit_exactly_one(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    map_id, dataset_id = await _map_with_layers(
        client, admin_auth_header, test_db_session, _MAX_LAYERS_PER_MAP - 1
    )

    responses = await asyncio.gather(
        _append(client, admin_auth_header, map_id, dataset_id),
        _append(client, admin_auth_header, map_id, dataset_id),
    )

    assert sorted(resp.status_code for resp in responses) == [201, 422]
    assert await _layer_count(test_db_session, map_id) == _MAX_LAYERS_PER_MAP


@pytest.mark.anyio
async def test_a_map_over_the_limit_can_still_shed_layers(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    map_id, dataset_id = await _map_with_layers(
        client, admin_auth_header, test_db_session, _MAX_LAYERS_PER_MAP + 1
    )
    layer_ids = (
        (
            await test_db_session.execute(
                select(MapLayer.id)
                .where(MapLayer.map_id == uuid.UUID(map_id))
                .order_by(MapLayer.sort_order)
                .limit(2)
            )
        )
        .scalars()
        .all()
    )

    first_delete = await client.delete(
        f"/maps/{map_id}/layers/{layer_ids[0]}", headers=admin_auth_header
    )
    at_the_limit = await _append(client, admin_auth_header, map_id, dataset_id)
    second_delete = await client.delete(
        f"/maps/{map_id}/layers/{layer_ids[1]}", headers=admin_auth_header
    )
    below_the_limit = await _append(client, admin_auth_header, map_id, dataset_id)

    assert first_delete.status_code == 204
    assert at_the_limit.status_code == 422
    assert second_delete.status_code == 204
    assert below_the_limit.status_code == 201


async def _wait_for_a_blocked_writer(session) -> None:
    """Block until another backend is waiting on a lock this session holds."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        blocked = (
            await session.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
                )
            )
        ).scalar_one()
        if blocked:
            return
        await asyncio.sleep(0.1)
    pytest.fail("the layer writer never reached the locked dataset")


async def _race_an_append_against_a_parked_writer(
    client: AsyncClient,
    headers: dict,
    session,
    monkeypatch,
    *,
    map_id: str,
    appended_dataset_id,
    parked_dataset_id,
    write: Callable[[], Awaitable[Response]],
) -> tuple[Response, Response]:
    """Park ``write`` on a locked dataset, run an append beside it, then release.

    Row-locking the dataset the writer is about to add makes its foreign-key
    check wait, so the writer has counted the map's layers by the time the
    append starts. A serialized append waits for the writer to commit; an
    unserialized one commits first and the writer inserts on a stale count.
    """
    monkeypatch.setattr(
        "app.modules.catalog.maps.service_layers._LAYER_LOCK_TIMEOUT", "30s"
    )
    await session.execute(
        select(Dataset.id).where(Dataset.id == parked_dataset_id).with_for_update()
    )
    writer = asyncio.create_task(write())
    try:
        await _wait_for_a_blocked_writer(session)
        append = asyncio.create_task(
            _append(client, headers, map_id, appended_dataset_id)
        )
        await asyncio.wait({append}, timeout=1.0)
    finally:
        await session.rollback()
    writer_resp, append_resp = await asyncio.gather(writer, append)
    return writer_resp, append_resp


@pytest.mark.anyio
async def test_a_layer_diff_and_an_append_at_the_boundary_admit_exactly_one(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    map_id, dataset_id = await _map_with_layers(
        client, admin_auth_header, test_db_session, _MAX_LAYERS_PER_MAP - 1
    )
    admin_id = await get_user_id(test_db_session, "admin")
    parked = await create_dataset(test_db_session, created_by=admin_id)

    writer_resp, append_resp = await _race_an_append_against_a_parked_writer(
        client,
        admin_auth_header,
        test_db_session,
        monkeypatch,
        map_id=map_id,
        appended_dataset_id=dataset_id,
        parked_dataset_id=parked.id,
        write=lambda: client.patch(
            f"/maps/{map_id}/layers",
            json={"added": [{"dataset_id": str(parked.id)}]},
            headers=admin_auth_header,
        ),
    )

    assert writer_resp.status_code == 200
    assert append_resp.status_code == 422
    assert await _layer_count(test_db_session, map_id) == _MAX_LAYERS_PER_MAP


@pytest.mark.anyio
async def test_a_full_save_and_an_append_at_the_boundary_admit_exactly_one(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    map_id, dataset_id = await _map_with_layers(
        client, admin_auth_header, test_db_session, _MAX_LAYERS_PER_MAP - 1
    )
    admin_id = await get_user_id(test_db_session, "admin")
    parked = await create_dataset(test_db_session, created_by=admin_id)
    existing_ids = (
        (
            await test_db_session.execute(
                select(MapLayer.id)
                .where(MapLayer.map_id == uuid.UUID(map_id))
                .order_by(MapLayer.sort_order)
            )
        )
        .scalars()
        .all()
    )
    layers = [
        {"id": str(layer_id), "dataset_id": str(dataset_id)}
        for layer_id in existing_ids
    ] + [{"dataset_id": str(parked.id)}]

    writer_resp, append_resp = await _race_an_append_against_a_parked_writer(
        client,
        admin_auth_header,
        test_db_session,
        monkeypatch,
        map_id=map_id,
        appended_dataset_id=dataset_id,
        parked_dataset_id=parked.id,
        write=lambda: client.put(
            f"/maps/{map_id}", json={"layers": layers}, headers=admin_auth_header
        ),
    )

    assert writer_resp.status_code == 200
    assert append_resp.status_code == 422
    assert await _layer_count(test_db_session, map_id) == _MAX_LAYERS_PER_MAP
