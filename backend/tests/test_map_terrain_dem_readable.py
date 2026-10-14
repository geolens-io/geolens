"""A map save may bind terrain only to a DEM the caller can read.

Create and update refuse any other DEM, and a style import drops its binding.
A DEM that doesn't exist is handled the same way as one the caller can't read.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.maps.models import Map

from tests.factories import create_dataset, create_user, get_user_id


def _terrain(dem_id: object) -> dict:
    return {"enabled": True, "source_dataset_id": str(dem_id), "exaggeration": 1.0}


async def _saves(client: AsyncClient, header: dict, dem_id: object) -> list:
    """Status codes of a create, an update and an import naming ``dem_id``, and
    whether the imported map, read back, still has a terrain binding."""
    created = await client.post(
        "/maps/",
        json={"name": f"T {uuid.uuid4().hex[:6]}", "terrain_config": _terrain(dem_id)},
        headers=header,
    )
    blank = await client.post(
        "/maps/", json={"name": f"T {uuid.uuid4().hex[:6]}"}, headers=header
    )
    updated = await client.put(
        f"/maps/{blank.json()['id']}",
        json={"terrain_config": _terrain(dem_id)},
        headers=header,
    )
    imported = await client.post(
        "/maps/import",
        json={
            "version": 8,
            "sources": {},
            "layers": [],
            "metadata": {"geolens": {"terrain_config": _terrain(dem_id)}},
        },
        headers=header,
    )
    assert imported.status_code == 201, imported.text
    imported_id = imported.json()["map"]["id"]
    read = await client.get(f"/maps/{imported_id}", headers=header)
    return [
        created.status_code,
        updated.status_code,
        imported.json()["map"]["terrain_config"] is not None,
        read.json()["terrain_config"] is not None,
    ]


async def test_missing_and_unreadable_dem_are_handled_alike(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    editor, _ = await create_user(client, admin_auth_header, "editor")
    private_dem = await create_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )
    public_dem = await create_dataset(test_db_session, created_by=admin_id)

    assert await _saves(client, editor, uuid.uuid4()) == [403, 403, False, False]
    assert await _saves(client, editor, private_dem.id) == [403, 403, False, False]
    assert await _saves(client, editor, public_dem.id) == [201, 200, True, True]


async def test_resaving_the_stored_binding_is_not_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A map keeps saving after its DEM is deleted or hidden from the owner."""
    admin_id = await get_user_id(test_db_session, "admin")
    editor, _ = await create_user(client, admin_auth_header, "editor")
    dem = await create_dataset(test_db_session, created_by=admin_id)
    created = await client.post(
        "/maps/",
        json={"name": f"T {uuid.uuid4().hex[:6]}", "terrain_config": _terrain(dem.id)},
        headers=editor,
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]

    await test_db_session.execute(
        update(Record).where(Record.id == dem.record_id).values(visibility="private")
    )
    await test_db_session.commit()
    hidden = await client.put(
        f"/maps/{map_id}", json={"terrain_config": _terrain(dem.id)}, headers=editor
    )
    assert hidden.status_code == 200, hidden.text

    gone = uuid.uuid4()
    await test_db_session.execute(
        update(Map)
        .where(Map.id == uuid.UUID(map_id))
        .values(terrain_config=_terrain(gone))
    )
    await test_db_session.commit()
    deleted = await client.put(
        f"/maps/{map_id}",
        json={"name": "Renamed", "terrain_config": _terrain(gone)},
        headers=editor,
    )
    assert deleted.status_code == 200, deleted.text
