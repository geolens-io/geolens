"""The public-map dataset check counts only the datasets the caller can read."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select, update

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer

from tests.factories import create_dataset, create_user, get_user_id


async def _map_with_hidden_layer(
    client: AsyncClient, admin_auth_header: dict, session
) -> tuple[dict, str, str, uuid.UUID]:
    """An editor's map with a layer on a public dataset and one on a dataset an
    admin then makes private. Returns the owner's header, the map id, the
    hidden dataset's title and a spare public dataset's id."""
    admin_id = await get_user_id(session, "admin")
    owner_header, _ = await create_user(client, admin_auth_header, "editor")
    hidden_title = f"Hidden {uuid.uuid4().hex[:8]}"
    shown = await create_dataset(session, created_by=admin_id)
    hidden = await create_dataset(session, created_by=admin_id, name=hidden_title)
    spare = await create_dataset(session, created_by=admin_id)
    created = await client.post(
        "/maps/", json={"name": f"Owner {uuid.uuid4().hex[:6]}"}, headers=owner_header
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    for ds in (shown, hidden):
        added = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(ds.id)},
            headers=owner_header,
        )
        assert added.status_code == 201, added.text
    await session.execute(
        update(Record).where(Record.id == hidden.record_id).values(visibility="private")
    )
    await session.commit()
    return owner_header, map_id, hidden_title, spare.id


async def _make_public(session, map_id: str) -> None:
    await session.execute(
        update(Map).where(Map.id == uuid.UUID(map_id)).values(visibility="public")
    )
    await session.commit()


async def _stored_layer_count(session, map_id: str) -> int:
    session.expire_all()
    rows = await session.execute(
        select(MapLayer.id).where(MapLayer.map_id == uuid.UUID(map_id))
    )
    return len(rows.scalars().all())


async def test_owner_can_publish_a_map_with_a_layer_they_cannot_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, map_id, hidden_title, _ = await _map_with_hidden_layer(
        client, admin_auth_header, test_db_session
    )

    check = await client.get(f"/maps/{map_id}/visibility-check/", headers=owner)
    assert check.status_code == 200, check.text
    assert check.json() == {"non_public_datasets": [], "has_non_public": False}

    published = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=owner
    )
    assert published.status_code == 200, published.text
    assert hidden_title not in published.text
    assert published.json()["visibility"] == "public"
    assert await _stored_layer_count(test_db_session, map_id) == 2


async def test_public_map_layer_adds_skip_a_layer_the_owner_cannot_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, map_id, hidden_title, spare_id = await _map_with_hidden_layer(
        client, admin_auth_header, test_db_session
    )
    await _make_public(test_db_session, map_id)

    posted = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(spare_id)}, headers=owner
    )
    assert posted.status_code == 201, posted.text
    assert hidden_title not in posted.text

    patched = await client.patch(
        f"/maps/{map_id}/layers",
        json={"added": [{"dataset_id": str(spare_id)}]},
        headers=owner,
    )
    assert patched.status_code == 200, patched.text
    assert hidden_title not in patched.text
    assert await _stored_layer_count(test_db_session, map_id) == 4


async def test_public_map_check_still_counts_datasets_the_caller_can_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The owner's own private dataset still blocks publishing, and an admin,
    who can read the hidden dataset, is still refused and told its name."""
    owner, map_id, hidden_title, _ = await _map_with_hidden_layer(
        client, admin_auth_header, test_db_session
    )
    owner_id = (await client.get("/auth/me", headers=owner)).json()["id"]
    own_title = f"Own {uuid.uuid4().hex[:8]}"
    own = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(owner_id),
        name=own_title,
        visibility="private",
    )
    added = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(own.id)}, headers=owner
    )
    assert added.status_code == 201, added.text

    refused = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=owner
    )
    assert refused.status_code == 400, refused.text
    assert own_title in refused.text
    assert hidden_title not in refused.text

    as_admin = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=admin_auth_header
    )
    assert as_admin.status_code == 400, as_admin.text
    assert hidden_title in as_admin.text


async def test_a_public_draft_layer_blocks_publishing_the_map(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    draft_title = f"Draft {uuid.uuid4().hex[:8]}"
    draft = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(owner_id),
        name=draft_title,
        record_status="draft",
    )
    await test_db_session.commit()
    created = await client.post(
        "/maps/", json={"name": f"Owner {uuid.uuid4().hex[:6]}"}, headers=owner
    )
    map_id = created.json()["id"]
    added = await client.post(
        f"/maps/{map_id}/layers", json={"dataset_id": str(draft.id)}, headers=owner
    )
    assert added.status_code == 201, added.text

    check = await client.get(f"/maps/{map_id}/visibility-check/", headers=owner)
    assert check.json()["non_public_datasets"] == [draft_title]
    refused = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=owner
    )
    assert refused.status_code == 400, refused.text
    assert draft_title in refused.text


async def _layer_rows(session, map_id: str) -> list[tuple]:
    """(layer id, dataset id, table name, title) for each stored layer."""
    session.expire_all()
    rows = await session.execute(
        select(MapLayer.id, Dataset.id, Dataset.table_name, Record.title)
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id == uuid.UUID(map_id))
    )
    return [tuple(str(value) for value in row) for row in rows.all()]


async def test_publish_that_also_replaces_layers_keeps_the_hidden_layer(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    owner, map_id, hidden_title, _ = await _map_with_hidden_layer(
        client, admin_auth_header, test_db_session
    )
    shown = next(
        row
        for row in await _layer_rows(test_db_session, map_id)
        if row[3] != hidden_title
    )

    published = await client.put(
        f"/maps/{map_id}",
        json={
            "visibility": "public",
            "layers": [{"id": shown[0], "dataset_id": shown[1], "sort_order": 0}],
        },
        headers=owner,
    )
    assert published.status_code == 200, published.text
    assert hidden_title not in published.text
    assert await _stored_layer_count(test_db_session, map_id) == 2


async def test_published_map_shows_no_trace_of_the_hidden_layer(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Anonymous reads and the gallery count leave out the layer the owner
    can't read once the owner publishes the map."""
    owner, map_id, hidden_title, _ = await _map_with_hidden_layer(
        client, admin_auth_header, test_db_session
    )
    hidden = next(
        row
        for row in await _layer_rows(test_db_session, map_id)
        if row[3] == hidden_title
    )
    published = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=owner
    )
    assert published.status_code == 200, published.text

    for path in (f"/maps/{map_id}", f"/maps/{map_id}/style.json"):
        read = await client.get(path)
        assert read.status_code == 200, (path, read.text)
        for trace in hidden:
            assert trace not in read.text, (path, trace)

    name = published.json()["name"]
    for header, expected in (({}, 1), (owner, 1), (admin_auth_header, 2)):
        listed = await client.get("/maps/", params={"search": name}, headers=header)
        assert listed.status_code == 200, listed.text
        assert [m["layer_count"] for m in listed.json()["maps"]] == [expected]
