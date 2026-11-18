"""A map write that opens a map to more readers waits for a change to its
layers' datasets, so the change and the map's sharing are judged in one order.

The dataset side refuses a change that strands its owner's shared maps while
holding the catalog rows. A map made public, shared with a group or handed to
another owner meanwhile either waits for that change and sees it, or holds
the rows first and the change sees the shared map.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.core.db as db_module
import app.modules.catalog.maps.service_groups as service_groups
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer
from tests.factories import create_dataset, create_user
from tests.test_dataset_delete_shared_maps import _delete, _vector_dataset
from tests.test_dataset_group_grants import _new_group
from tests.test_dataset_narrowing_shared_maps import _map_using
from tests.test_embed_tokens import _cleanup_data_table
from tests.test_map_group_sharing import _blocked_or_done

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")


async def _stored(session, map_id) -> tuple[str, uuid.UUID, int]:
    """The map's visibility, owner and layer count as committed."""
    session.expire_all()
    visibility, owner = (
        await session.execute(
            sa.select(Map.visibility, Map.created_by).where(Map.id == map_id)
        )
    ).one()
    layers = await session.scalar(
        sa.select(sa.func.count())
        .select_from(MapLayer)
        .where(MapLayer.map_id == map_id)
    )
    return visibility, owner, layers


async def _hold_dataset_change(holder, dataset, change: str) -> None:
    """Take the dataset's catalog rows as the dataset side does, then make
    ``change`` without committing it."""
    await holder.execute(
        sa.select(Dataset.id).where(Dataset.id == dataset.id).with_for_update()
    )
    await holder.execute(
        sa.select(Record.id).where(Record.id == dataset.record_id).with_for_update()
    )
    if change == "deleted":
        await holder.execute(sa.delete(Record).where(Record.id == dataset.record_id))
    else:
        await holder.execute(
            sa.update(Record)
            .where(Record.id == dataset.record_id)
            .values(visibility="private")
        )


@pytest.fixture
async def setup(client: AsyncClient, admin_auth_header: dict, test_db_session):
    """An editor's private map showing their internal dataset, a group the
    editor shares with a second editor, and a third editor to hand it to."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    _, member_id = await create_user(client, admin_auth_header, "editor")
    _, heir_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(str(owner_id)),
        name=f"Shared {uuid.uuid4().hex[:6]}",
        visibility="internal",
    )
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    return {
        "owner": owner,
        "admin": admin_auth_header,
        "dataset": dataset,
        "map": map_obj,
        "group": await _new_group(client, admin_auth_header, [owner_id, member_id]),
        "heir": uuid.UUID(str(heir_id)),
    }


async def _widen(client: AsyncClient, setup, write: str):
    map_id = setup["map"].id
    if write == "public":
        return await client.put(
            f"/maps/{map_id}", json={"visibility": "public"}, headers=setup["owner"]
        )
    if write.startswith("groups"):
        path = "/groups/" if write == "groups/" else "/groups"
        return await client.put(
            f"/maps/{map_id}{path}",
            json={"group_ids": [setup["group"]]},
            headers=setup["owner"],
        )
    return await client.patch(
        f"/maps/{map_id}",
        json={"owner_id": str(setup["heir"])},
        headers=setup["admin"],
    )


async def _make_public(dataset) -> None:
    async with db_module.async_session() as other:
        await other.execute(
            sa.update(Record)
            .where(Record.id == dataset.record_id)
            .values(visibility="public")
        )
        await other.commit()


# What each write answers once a narrowed dataset is no longer readable by the
# map's new audience: its existing refusal for that case.
_REFUSED = {
    "public": (400, "Cannot set visibility to public"),
    "groups/": (409, "layers_hidden_from_groups"),
    "groups": (409, "layers_hidden_from_groups"),
    "transfer": (422, "The new owner cannot read every dataset"),
}


@pytest.mark.parametrize("write", list(_REFUSED))
@pytest.mark.parametrize("change", ["narrowed", "deleted"])
async def test_a_map_write_waits_for_the_dataset_change_and_sees_it(
    client: AsyncClient, setup, test_db_session, write: str, change: str
):
    map_id, owner_id = setup["map"].id, setup["map"].created_by
    if write == "public":
        await _make_public(setup["dataset"])
    async with db_module.async_session() as holder:
        await _hold_dataset_change(holder, setup["dataset"], change)
        widening = asyncio.create_task(_widen(client, setup, write))
        await _blocked_or_done(holder, widening)

        assert not widening.done(), "the map write did not wait for the dataset"
        await holder.commit()
        resp = await widening

    if change == "deleted":
        assert resp.status_code == 200, resp.text
        visibility, owner, layers = await _stored(test_db_session, map_id)
        assert layers == 0
        assert (visibility, owner) != ("private", owner_id)
    else:
        status_code, marker = _REFUSED[write]
        assert resp.status_code == status_code, resp.text
        assert marker in resp.text
        assert await _stored(test_db_session, map_id) == ("private", owner_id, 1)


def _hook_the_dataset_lock(monkeypatch, change):
    """Once the map write holds its layers' datasets, start ``change`` and
    let the map write go on only when ``change`` waits on it."""
    real = service_groups.lock_layer_datasets
    started: list[asyncio.Task] = []

    async def locking(session, map_id):
        await real(session, map_id)
        if not started:
            started.append(asyncio.create_task(change()))
            await _blocked_or_done(session, started[0])

    monkeypatch.setattr(service_groups, "lock_layer_datasets", locking)
    return started


@pytest.mark.parametrize("change", ["delete", "restrict", "unpublish"])
async def test_a_dataset_change_behind_a_map_write_sees_the_shared_map(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    change: str,
):
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    table, expected = dataset.table_name, {"id": str(map_obj.id), "name": map_obj.name}

    async def change_dataset():
        if change == "delete":
            return await _delete(client, dataset, owner)
        if change == "restrict":
            return await client.patch(
                f"/datasets/{dataset.id}",
                json={"visibility": "private"},
                headers=owner,
            )
        return await client.patch(
            f"/datasets/{dataset.id}/status/",
            json={"status": "internal"},
            headers=owner,
        )

    started = _hook_the_dataset_lock(monkeypatch, change_dataset)
    try:
        shared = await client.put(
            f"/maps/{map_obj.id}", json={"visibility": "public"}, headers=owner
        )
        assert shared.status_code == 200, shared.text
        refused = await started[0]

        assert refused.status_code == 422, refused.text
        assert refused.json()["shared_maps"] == [expected]
        assert await _stored(test_db_session, map_obj.id) == (
            "public",
            uuid.UUID(str(owner_id)),
            1,
        )
    finally:
        await _cleanup_data_table(test_db_session, table)


async def test_a_map_write_that_widens_nothing_takes_no_dataset_lock(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Saving a map's visibility unchanged, or making it private, goes on
    while its dataset is being changed."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(str(owner_id)), visibility="internal"
    )
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "internal")
    async with db_module.async_session() as holder:
        await _hold_dataset_change(holder, dataset, "narrowed")
        for visibility in ("internal", "private"):
            resp = await client.put(
                f"/maps/{map_obj.id}", json={"visibility": visibility}, headers=owner
            )
            assert resp.status_code == 200, resp.text
        await holder.rollback()
