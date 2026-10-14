"""Map save responses list only the layers and terrain DEM the caller can read."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.maps.models import Map, MapLayer

from tests.factories import create_dataset, create_user, get_user_id


async def test_save_responses_hide_layers_the_owner_can_no_longer_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The owner's PUT and PATCH responses drop a layer and terrain binding
    whose dataset went private, as GET does, and both stay stored."""
    admin_id = await get_user_id(test_db_session, "admin")
    owner_header, _ = await create_user(client, admin_auth_header, "editor")
    kept_ds = await create_dataset(test_db_session, created_by=admin_id)
    revoked_ds = await create_dataset(test_db_session, created_by=admin_id)
    added_ds = await create_dataset(test_db_session, created_by=admin_id)

    created = await client.post(
        "/maps/", json={"name": f"Owner {uuid.uuid4().hex[:6]}"}, headers=owner_header
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    layer_ids = {}
    for ds in (kept_ds, revoked_ds):
        added = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=owner_header,
        )
        assert added.status_code == 201, added.text
        layer_ids[ds.id] = added.json()["id"]

    terrain = {"enabled": True, "source_dataset_id": str(revoked_ds.id)}
    await test_db_session.execute(
        update(Map).where(Map.id == uuid.UUID(map_id)).values(terrain_config=terrain)
    )
    await test_db_session.execute(
        update(Record)
        .where(Record.id == revoked_ds.record_id)
        .values(visibility="private")
    )
    await test_db_session.commit()

    read = await client.get(f"/maps/{map_id}", headers=owner_header)
    assert [layer["dataset_id"] for layer in read.json()["layers"]] == [str(kept_ds.id)]
    assert read.json()["terrain_config"] is None

    renamed = await client.put(
        f"/maps/{map_id}", json={"name": "Renamed"}, headers=owner_header
    )
    assert renamed.status_code == 200, renamed.text
    assert [layer["dataset_id"] for layer in renamed.json()["layers"]] == [
        str(kept_ds.id)
    ]
    assert renamed.json()["terrain_config"] is None

    patched = await client.patch(
        f"/maps/{map_id}/layers",
        json={
            "added": [{"dataset_id": str(added_ds.id)}],
            "updated": [{"id": layer_ids[kept_ds.id], "opacity": 0.5}],
        },
        headers=owner_header,
    )
    assert patched.status_code == 200, patched.text
    assert sorted(layer["dataset_id"] for layer in patched.json()["layers"]) == sorted(
        [str(kept_ds.id), str(added_ds.id)]
    )
    assert patched.json()["terrain_config"] is None

    stored = (
        (
            await test_db_session.execute(
                select(MapLayer.id).where(MapLayer.map_id == uuid.UUID(map_id))
            )
        )
        .scalars()
        .all()
    )
    assert str(layer_ids[revoked_ds.id]) in {str(layer_id) for layer_id in stored}
    assert len(stored) == 3
    stored_terrain = await test_db_session.scalar(
        select(Map.terrain_config).where(Map.id == uuid.UUID(map_id))
    )
    assert stored_terrain == terrain
