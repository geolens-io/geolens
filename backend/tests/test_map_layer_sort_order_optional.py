"""A layer that leaves ``sort_order`` out is placed by the server.

The generated SDK models send ``null`` or nothing for an unset field, so a
missing draw order must mean "after the other layers" on POST and PATCH and
"the layer's position in the list" on a full save, while an explicit value,
zero included, is stored as sent.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.schemas import MapLayerInput

from tests.factories import create_dataset, get_user_id


async def _map_with_dataset(client: AsyncClient, headers: dict, session):
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=admin_id)
    resp = await client.post(
        "/maps/", json={"name": f"Order {uuid.uuid4().hex[:6]}"}, headers=headers
    )
    assert resp.status_code == 201
    return resp.json()["id"], str(dataset.id)


async def _orders(session, map_id: str) -> list[int]:
    session.expire_all()
    rows = await session.execute(
        select(MapLayer.sort_order)
        .where(MapLayer.map_id == uuid.UUID(map_id))
        .order_by(MapLayer.sort_order, MapLayer.id)
    )
    return list(rows.scalars().all())


def test_the_schema_leaves_an_unset_order_unset():
    layer = MapLayerInput(dataset_id=uuid.uuid4())
    assert layer.sort_order is None
    assert "sort_order" not in layer.model_dump(exclude_none=True)


def test_an_arcgis_import_still_returns_every_layer_with_an_order():
    from app.modules.catalog.maps.schemas_import_arcgis import (
        ArcgisWebmapImportResponse,
    )

    schema = ArcgisWebmapImportResponse.model_json_schema()
    name = schema["properties"]["layers"]["items"]["$ref"].rsplit("/", 1)[-1]
    layer = schema["$defs"][name]
    assert layer["properties"]["sort_order"]["type"] == "integer"
    assert "sort_order" in layer["required"]


@pytest.mark.anyio
async def test_post_with_a_null_order_appends(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    map_id, dataset_id = await _map_with_dataset(
        client, admin_auth_header, test_db_session
    )
    for _ in range(2):
        resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": dataset_id, "sort_order": None},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

    assert await _orders(test_db_session, map_id) == [0, 1]


@pytest.mark.anyio
async def test_patch_added_with_a_null_order_appends(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    map_id, dataset_id = await _map_with_dataset(
        client, admin_auth_header, test_db_session
    )
    await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": dataset_id},
        headers=admin_auth_header,
    )
    resp = await client.patch(
        f"/maps/{map_id}/layers",
        json={"added": [{"dataset_id": dataset_id, "sort_order": None}]},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert await _orders(test_db_session, map_id) == [0, 1]


@pytest.mark.anyio
async def test_put_without_orders_uses_list_position(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    map_id, dataset_id = await _map_with_dataset(
        client, admin_auth_header, test_db_session
    )
    resp = await client.put(
        f"/maps/{map_id}",
        json={"layers": [{"dataset_id": dataset_id} for _ in range(3)]},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert await _orders(test_db_session, map_id) == [0, 1, 2]


@pytest.mark.anyio
async def test_an_explicit_zero_is_still_honored(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    map_id, dataset_id = await _map_with_dataset(
        client, admin_auth_header, test_db_session
    )
    resp = await client.put(
        f"/maps/{map_id}",
        json={
            "layers": [
                {"dataset_id": dataset_id, "sort_order": 5},
                {"dataset_id": dataset_id, "sort_order": 0},
            ]
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert await _orders(test_db_session, map_id) == [0, 5]

    appended = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": dataset_id, "sort_order": 0},
        headers=admin_auth_header,
    )
    assert appended.status_code == 201
    assert await _orders(test_db_session, map_id) == [0, 0, 5]
