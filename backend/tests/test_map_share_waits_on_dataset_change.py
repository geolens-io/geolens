"""A map write that opens a map to more readers waits for a change to its
layers' datasets, so the change and the map's sharing are judged in one order.

The dataset side refuses a change that strands its owner's shared maps while
holding the catalog rows. A map made public, shared with a group or handed to
another owner meanwhile either waits for that change and sees it, or holds
the rows first and the change sees the shared map.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.core.db as db_module
import app.modules.catalog.ownership as ownership
import app.modules.catalog.maps.service_groups as service_groups
from app.modules.catalog.datasets.domain import service as dataset_service
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer
import app.modules.embed_tokens.router as embed_router
from app.modules.embed_tokens.models import EmbedToken
from tests.factories import create_dataset, create_user
from tests.test_dataset_delete_shared_maps import (
    _delete,
    _still_there,
    _vector_dataset,
)
from tests.test_dataset_group_grants import _new_group
from tests.test_dataset_narrowing_shared_maps import _map_using
from tests.test_embed_tokens import _cleanup_data_table

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


async def _until_blocked(holder, task: asyncio.Task) -> None:
    """Return once ``task`` waits on a lock ``holder`` holds; fail if it
    finishes first or never waits."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if task.done():
            pytest.fail("the request finished without waiting on the held rows")
        # The activity view is snapshotted once per transaction.
        await holder.execute(sa.text("SELECT pg_stat_clear_snapshot()"))
        if await holder.scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        ):
            return
        await asyncio.sleep(0.05)
    pytest.fail("the request never waited on the held rows")


async def _drain(tasks: list[asyncio.Task]) -> None:
    """Let started requests finish, cancelling any that outlast the wait, so
    a failed test leaves none running against its fixtures."""
    pending = [task for task in tasks if not task.done()]
    if pending:
        _, late = await asyncio.wait(pending, timeout=10)
        for task in late:
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
async def children():
    """Requests a test starts beside its own, drained at teardown."""
    tasks: list[asyncio.Task] = []
    yield tasks
    await _drain(tasks)


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
    client: AsyncClient, setup, test_db_session, children, write: str, change: str
):
    map_id, owner_id = setup["map"].id, setup["map"].created_by
    if write == "public":
        await _make_public(setup["dataset"])
    async with db_module.async_session() as holder:
        await _hold_dataset_change(holder, setup["dataset"], change)
        widening = asyncio.create_task(_widen(client, setup, write))
        children.append(widening)
        await _until_blocked(holder, widening)
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


def _hook_the_dataset_lock(monkeypatch, change, started: list[asyncio.Task]):
    """Once the map write holds its layers' datasets, start ``change`` and
    let the map write go on only when ``change`` waits on it."""
    real = service_groups.lock_layer_datasets

    async def locking(session, map_id):
        await real(session, map_id)
        if not started:
            started.append(asyncio.create_task(change()))
            await _until_blocked(session, started[0])

    monkeypatch.setattr(service_groups, "lock_layer_datasets", locking)


@pytest.mark.parametrize("change", ["delete", "restrict"])
async def test_a_dataset_change_behind_a_map_write_sees_the_shared_map(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    children,
    change: str,
):
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    table, expected = dataset.table_name, {"id": str(map_obj.id), "name": map_obj.name}

    async def change_dataset():
        if change == "delete":
            return await _delete(client, dataset, owner)
        return await client.patch(
            f"/datasets/{dataset.id}",
            json={"visibility": "private"},
            headers=owner,
        )

    _hook_the_dataset_lock(monkeypatch, change_dataset, children)
    try:
        shared = await client.put(
            f"/maps/{map_obj.id}", json={"visibility": "public"}, headers=owner
        )
        assert shared.status_code == 200, shared.text
        refused = await children[0]

        assert refused.status_code == 422, refused.text
        assert refused.json()["shared_maps"] == [expected]
        assert await _stored(test_db_session, map_obj.id) == (
            "public",
            uuid.UUID(str(owner_id)),
            1,
        )
    finally:
        await _drain(children)
        await _cleanup_data_table(test_db_session, table)


async def test_a_map_write_that_widens_nothing_takes_no_dataset_lock(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Narrowing a public map to internal, saving its visibility unchanged or
    making it private goes on while its dataset is being changed."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(str(owner_id)), visibility="internal"
    )
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "public")
    async with db_module.async_session() as holder:
        await _hold_dataset_change(holder, dataset, "narrowed")
        for visibility in ("internal", "internal", "private"):
            resp = await client.put(
                f"/maps/{map_obj.id}", json={"visibility": visibility}, headers=owner
            )
            assert resp.status_code == 200, resp.text
        await holder.rollback()


@pytest.mark.parametrize(
    ("path", "target"), [("status", "internal"), ("target-status", "draft")]
)
async def test_an_unpublish_behind_a_map_going_public_sees_it(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    children,
    path: str,
    target: str,
):
    """The publication-status routes ask about shared maps holding the
    dataset's rows, so an unpublish that waited on a map going public is
    refused once that map is public."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(str(owner_id)), visibility="public"
    )
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    dataset_id, expected = dataset.id, {"id": str(map_obj.id), "name": map_obj.name}

    async def unpublish():
        return await client.patch(
            f"/datasets/{dataset_id}/{path}/", json={"status": target}, headers=owner
        )

    _hook_the_dataset_lock(monkeypatch, unpublish, children)
    shared = await client.put(
        f"/maps/{map_obj.id}", json={"visibility": "public"}, headers=owner
    )
    assert shared.status_code == 200, shared.text
    refused = await children[0]

    assert refused.status_code == 422, refused.text
    assert refused.json()["action"] == "unpublish"
    assert refused.json()["shared_maps"] == [expected]
    test_db_session.expire_all()
    assert (
        await test_db_session.scalar(
            sa.select(Record.record_status)
            .join(Dataset, Dataset.record_id == Record.id)
            .where(Dataset.id == dataset_id)
        )
        == "published"
    )


async def test_a_map_made_internal_after_a_narrowing_keeps_the_hidden_layer(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """With no race at all, a map may go internal while a layer's dataset is
    private to its owner; the layer is hidden from the map's other readers."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    reader, _ = await create_user(client, admin_auth_header, "viewer")
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(str(owner_id)), visibility="internal"
    )
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    narrowed = await client.patch(
        f"/datasets/{dataset.id}", json={"visibility": "private"}, headers=owner
    )
    assert narrowed.status_code == 200, narrowed.text

    shared = await client.put(
        f"/maps/{map_obj.id}", json={"visibility": "internal"}, headers=owner
    )

    assert shared.status_code == 200, shared.text
    read = await client.get(f"/maps/{map_obj.id}", headers=reader)
    assert read.status_code == 200, read.text
    assert read.json()["layers"] == []


@pytest.mark.parametrize("prior", [None, "expired", "revoked"])
async def test_an_embed_token_mint_waits_for_a_delete_and_leaves_its_dataset_out(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    children,
    prior: str | None,
):
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    deleted, kept = [
        await create_dataset(
            test_db_session, created_by=uuid.UUID(str(owner_id)), visibility="public"
        )
        for _ in range(2)
    ]
    map_obj = await _map_using(test_db_session, deleted.id, owner_id, "public")
    map_id, kept_id = map_obj.id, kept.id
    test_db_session.add(MapLayer(map_id=map_id, dataset_id=kept_id, sort_order=1))
    await test_db_session.commit()
    mint_url = f"/maps/{map_id}/embed-tokens/"
    if prior is not None:
        first = await client.post(mint_url, json={}, headers=owner)
        assert first.status_code == 201, first.text
        await test_db_session.execute(
            sa.update(EmbedToken)
            .where(EmbedToken.map_id == map_id)
            .values(
                {"is_active": False}
                if prior == "revoked"
                else {"expires_at": sa.func.now() - sa.text("interval '1 day'")}
            )
        )
        await test_db_session.commit()

    async with db_module.async_session() as holder:
        await _hold_dataset_change(holder, deleted, "deleted")
        minting = asyncio.create_task(client.post(mint_url, json={}, headers=owner))
        children.append(minting)
        await _until_blocked(holder, minting)
        await holder.commit()
        minted = await minting

    assert minted.status_code == 201, minted.text
    assert minted.json()["scoped_dataset_ids"] == [str(kept_id)]


@pytest.mark.parametrize(
    ("path", "target"), [("status", "internal"), ("target-status", "draft")]
)
async def test_an_unpublish_behind_a_dataset_share_judges_the_shared_dataset(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    children,
    path: str,
    target: str,
):
    """An unpublish loaded before a map share made its private dataset
    restricted judges the restricted dataset once it holds the rows."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    _, member_id = await create_user(client, admin_auth_header, "editor")
    group = await _new_group(client, admin_auth_header, [owner_id, member_id])
    dataset = await create_dataset(
        test_db_session, created_by=uuid.UUID(str(owner_id)), visibility="private"
    )
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    dataset_id, expected = dataset.id, {"id": str(map_obj.id), "name": map_obj.name}
    real = dataset_service.set_dataset_groups

    async def unpublish():
        return await client.patch(
            f"/datasets/{dataset_id}/{path}/", json={"status": target}, headers=owner
        )

    async def sharing(session, dataset, *args, **kwargs):
        result = await real(session, dataset, *args, **kwargs)
        children.append(asyncio.create_task(unpublish()))
        await _until_blocked(session, children[0])
        return result

    monkeypatch.setattr(dataset_service, "set_dataset_groups", sharing)
    shared = await client.put(
        f"/maps/{map_obj.id}/groups/",
        json={"group_ids": [group], "confirm": "share_datasets"},
        headers=owner,
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["shared_dataset_ids"] == [str(dataset_id)]
    refused = await children[0]

    assert refused.status_code == 422, refused.text
    assert refused.json()["shared_maps"] == [expected]


async def test_a_transfer_waits_for_a_change_to_its_terrain_source(
    client: AsyncClient, admin_auth_header: dict, test_db_session, children
):
    """A DEM bound only as terrain is read by the transfer's check, so the
    transfer waits for it too."""
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    _, heir_id = await create_user(client, admin_auth_header, "editor")
    dem = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(str(owner_id)),
        visibility="internal",
        record_type="raster_dataset",
    )
    map_obj = Map(
        name=f"Map {uuid.uuid4().hex[:6]}",
        visibility="private",
        created_by=uuid.UUID(str(owner_id)),
        terrain_config={"source_dataset_id": str(dem.id)},
    )
    test_db_session.add(map_obj)
    await test_db_session.commit()
    map_id = map_obj.id

    async with db_module.async_session() as holder:
        await _hold_dataset_change(holder, dem, "narrowed")
        transfer = asyncio.create_task(
            client.patch(
                f"/maps/{map_id}",
                json={"owner_id": str(heir_id)},
                headers=admin_auth_header,
            )
        )
        children.append(transfer)
        await _until_blocked(holder, transfer)
        await holder.commit()
        resp = await transfer

    assert resp.status_code == 422, resp.text
    assert str(dem.id) in resp.text


async def test_a_delete_behind_an_embed_token_mint_sees_the_token(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    children,
):
    """A delete that waited on a mint holding the map's datasets is refused
    by the token the mint committed."""
    owner, owner_id = await create_user(client, admin_auth_header, "editor")
    dataset = await _vector_dataset(test_db_session, owner_id)
    map_obj = await _map_using(test_db_session, dataset.id, owner_id, "private")
    table, expected = dataset.table_name, {"id": str(map_obj.id), "name": map_obj.name}
    real = embed_router.create_embed_token

    async def minting(session, *args, **kwargs):
        children.append(asyncio.create_task(_delete(client, dataset, owner)))
        await _until_blocked(session, children[0])
        return await real(session, *args, **kwargs)

    monkeypatch.setattr(embed_router, "create_embed_token", minting)
    try:
        minted = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=owner
        )
        assert minted.status_code == 201, minted.text
        refused = await children[0]

        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "dataset_in_shared_maps"
        assert refused.json()["shared_maps"] == [expected]
        assert await _still_there(test_db_session, dataset) == (True, 1, True)
    finally:
        await _drain(children)
        await _cleanup_data_table(test_db_session, table)


async def test_a_transfer_checks_the_terrain_source_committed_before_its_lock(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    """A terrain edit that commits after the transfer loaded the map but
    before it locked the row is what the new-owner check reads."""
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    _, heir_id = await create_user(client, admin_auth_header, "editor")
    dem = await create_dataset(
        test_db_session,
        created_by=uuid.UUID(str(owner_id)),
        visibility="private",
        record_type="raster_dataset",
    )
    map_obj = Map(
        name=f"Map {uuid.uuid4().hex[:6]}",
        visibility="private",
        created_by=uuid.UUID(str(owner_id)),
    )
    test_db_session.add(map_obj)
    await test_db_session.commit()
    map_id, dem_id = map_obj.id, dem.id
    real = ownership.lock_map_layers

    async def bind_terrain_first(session, locked_map_id):
        async with db_module.async_session() as other:
            await other.execute(
                sa.update(Map)
                .where(Map.id == locked_map_id)
                .values(terrain_config={"source_dataset_id": str(dem_id)})
            )
            await other.commit()
        await real(session, locked_map_id)

    monkeypatch.setattr(ownership, "lock_map_layers", bind_terrain_first)
    resp = await client.patch(
        f"/maps/{map_id}", json={"owner_id": str(heir_id)}, headers=admin_auth_header
    )

    assert resp.status_code == 422, resp.text
    assert str(dem_id) in resp.text
