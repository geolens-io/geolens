"""Map saves leave alone the layers and terrain DEM the caller can't read."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.maps import service_diff
from app.modules.catalog.maps.models import Map, MapLayer

from tests.factories import create_dataset, create_user, get_user_id


async def _map_with_hidden_middle_layer(
    client: AsyncClient, admin_auth_header: dict, session
) -> tuple[dict, str, dict[str, str], dict[str, uuid.UUID]]:
    """An editor's map with layers a, hidden, b, stacked in that order, and a
    terrain binding to the hidden layer's DEM. An admin then makes that
    dataset private, so the owner can no longer read it."""
    admin_id = await get_user_id(session, "admin")
    owner_header, _ = await create_user(client, admin_auth_header, "editor")
    datasets = {
        key: await create_dataset(session, created_by=admin_id)
        for key in ("a", "hidden", "b", "c")
    }
    created = await client.post(
        "/maps/", json={"name": f"Owner {uuid.uuid4().hex[:6]}"}, headers=owner_header
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    layer_ids = {}
    for sort_order, key in enumerate(("a", "hidden", "b")):
        added = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(datasets[key].id), "sort_order": sort_order},
            headers=owner_header,
        )
        assert added.status_code == 201, added.text
        layer_ids[key] = added.json()["id"]

    await session.execute(
        update(Map)
        .where(Map.id == uuid.UUID(map_id))
        .values(
            terrain_config={
                "enabled": True,
                "source_dataset_id": str(datasets["hidden"].id),
                "exaggeration": 1.0,
            }
        )
    )
    await session.execute(
        update(Record)
        .where(Record.id == datasets["hidden"].record_id)
        .values(visibility="private")
    )
    await session.commit()

    read = await client.get(f"/maps/{map_id}", headers=owner_header)
    assert [layer["id"] for layer in read.json()["layers"]] == [
        layer_ids["a"],
        layer_ids["b"],
    ]
    assert read.json()["terrain_config"] is None
    return (
        owner_header,
        map_id,
        layer_ids,
        {key: ds.id for key, ds in datasets.items()},
    )


async def _stored_stack(session, map_id: str) -> list[str]:
    session.expire_all()
    rows = await session.execute(
        select(MapLayer.id)
        .where(MapLayer.map_id == uuid.UUID(map_id))
        .order_by(MapLayer.sort_order, MapLayer.id)
    )
    return [str(layer_id) for layer_id in rows.scalars().all()]


async def _stored_terrain(session, map_id: str) -> dict | None:
    session.expire_all()
    return await session.scalar(
        select(Map.terrain_config).where(Map.id == uuid.UUID(map_id))
    )


def _layer_input(layer_id: str, dataset_id: uuid.UUID, sort_order: int) -> dict:
    return {"id": layer_id, "dataset_id": str(dataset_id), "sort_order": sort_order}


async def test_full_replace_keeps_hidden_layer_and_deletes_left_out_visible_one(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, map_id, ids, ds = await _map_with_hidden_middle_layer(
        client, admin_auth_header, test_db_session
    )

    swapped = await client.put(
        f"/maps/{map_id}",
        json={
            "layers": [
                _layer_input(ids["a"], ds["a"], 2),
                {"dataset_id": str(ds["c"]), "sort_order": 0},
                _layer_input(ids["b"], ds["b"], 1),
            ]
        },
        headers=owner,
    )
    assert swapped.status_code == 200, swapped.text
    assert ids["hidden"] not in {layer["id"] for layer in swapped.json()["layers"]}
    assert len(swapped.json()["layers"]) == 3
    assert swapped.json()["terrain_config"] is None
    stack = await _stored_stack(test_db_session, map_id)
    assert stack[1:] == [ids["hidden"], ids["b"], ids["a"]]
    ids["c"] = stack[0]

    dropped = await client.put(
        f"/maps/{map_id}",
        json={"layers": [_layer_input(ids["a"], ds["a"], 0)]},
        headers=owner,
    )
    assert dropped.status_code == 200, dropped.text
    assert await _stored_stack(test_db_session, map_id) == [ids["hidden"], ids["a"]]


async def test_full_replace_counts_hidden_layers_against_the_cap(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    owner, map_id, ids, ds = await _map_with_hidden_middle_layer(
        client, admin_auth_header, test_db_session
    )
    monkeypatch.setattr(service_diff, "_MAX_LAYERS_PER_MAP", 2)

    over = await client.put(
        f"/maps/{map_id}",
        json={
            "layers": [
                _layer_input(ids["a"], ds["a"], 0),
                _layer_input(ids["b"], ds["b"], 1),
            ]
        },
        headers=owner,
    )
    assert over.status_code == 400, over.text
    assert await _stored_stack(test_db_session, map_id) == [
        ids["a"],
        ids["hidden"],
        ids["b"],
    ]


async def test_public_map_full_replace_ignores_hidden_non_public_layer(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, map_id, ids, ds = await _map_with_hidden_middle_layer(
        client, admin_auth_header, test_db_session
    )
    await test_db_session.execute(
        update(Map).where(Map.id == uuid.UUID(map_id)).values(visibility="public")
    )
    await test_db_session.commit()

    saved = await client.put(
        f"/maps/{map_id}",
        json={
            "layers": [
                _layer_input(ids["b"], ds["b"], 0),
                _layer_input(ids["a"], ds["a"], 1),
            ]
        },
        headers=owner,
    )
    assert saved.status_code == 200, saved.text
    assert await _stored_stack(test_db_session, map_id) == [
        ids["b"],
        ids["hidden"],
        ids["a"],
    ]


async def test_save_naming_no_dem_keeps_hidden_terrain_binding(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, map_id, _, ds = await _map_with_hidden_middle_layer(
        client, admin_auth_header, test_db_session
    )
    stored = await _stored_terrain(test_db_session, map_id)

    for terrain in (None, {"enabled": False, "exaggeration": 2.0}):
        saved = await client.put(
            f"/maps/{map_id}",
            json={"name": "Renamed", "terrain_config": terrain},
            headers=owner,
        )
        assert saved.status_code == 200, saved.text
        assert await _stored_terrain(test_db_session, map_id) == stored

    history = await client.get(f"/maps/{map_id}/history", headers=owner)
    assert "map.terrain_update" not in {
        event["action"] for event in history.json()["events"]
    }

    rebound = {"enabled": True, "source_dataset_id": str(ds["a"]), "exaggeration": 1.5}
    replaced = await client.put(
        f"/maps/{map_id}", json={"terrain_config": rebound}, headers=owner
    )
    assert replaced.status_code == 200, replaced.text
    assert await _stored_terrain(test_db_session, map_id) == rebound


async def test_patch_order_keeps_hidden_layer_in_place(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, map_id, ids, _ = await _map_with_hidden_middle_layer(
        client, admin_auth_header, test_db_session
    )

    unchanged = await client.patch(
        f"/maps/{map_id}/layers",
        json={"order": [ids["a"], ids["b"]]},
        headers=owner,
    )
    assert unchanged.status_code == 200, unchanged.text
    assert await _stored_stack(test_db_session, map_id) == [
        ids["a"],
        ids["hidden"],
        ids["b"],
    ]

    swapped = await client.patch(
        f"/maps/{map_id}/layers",
        json={"order": [ids["hidden"], ids["b"], ids["a"]]},
        headers=owner,
    )
    assert swapped.status_code == 200, swapped.text
    assert await _stored_stack(test_db_session, map_id) == [
        ids["b"],
        ids["hidden"],
        ids["a"],
    ]


async def test_hidden_layer_rules_widen_nothing(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A non-owner still can't save, and the owner can still delete by id."""
    owner, map_id, ids, ds = await _map_with_hidden_middle_layer(
        client, admin_auth_header, test_db_session
    )
    other, _ = await create_user(client, admin_auth_header, "editor")

    put = await client.put(
        f"/maps/{map_id}",
        json={"layers": [_layer_input(ids["a"], ds["a"], 0)]},
        headers=other,
    )
    # The map is private, so a non-owner can't tell it exists.
    assert put.status_code == 404, put.text
    patch = await client.patch(
        f"/maps/{map_id}/layers", json={"order": [ids["b"], ids["a"]]}, headers=other
    )
    assert patch.status_code == 404, patch.text
    assert await _stored_stack(test_db_session, map_id) == [
        ids["a"],
        ids["hidden"],
        ids["b"],
    ]

    removed = await client.patch(
        f"/maps/{map_id}/layers", json={"removed": [ids["hidden"]]}, headers=owner
    )
    assert removed.status_code == 200, removed.text
    assert await _stored_stack(test_db_session, map_id) == [ids["a"], ids["b"]]
