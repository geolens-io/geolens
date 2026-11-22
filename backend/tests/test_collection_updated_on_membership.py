"""A collection's ``updated_at`` moves when its member list changes: a dataset
added or removed through the API, added by a publish manifest, or deleted out
of it, the last just after the delete commits. Every write stamps the time of
the write, never earlier than the stored value.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.core.db as db_module
from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.collections import service as collections_service
from app.modules.catalog.collections.service import add_datasets_to_collection
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.extensions.defaults import DefaultProcessingPort
from tests.factories import create_collection_via_api, create_dataset, create_user
from tests.lock_wait import await_lock_wait_query

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_init_tile_pool_for_tests")]

# A time no request in the test can stamp, so "moved" never depends on the clock.
_PINNED = datetime(2000, 1, 1, tzinfo=timezone.utc)


async def _collection(client: AsyncClient, headers: dict) -> uuid.UUID:
    return uuid.UUID((await create_collection_via_api(client, headers))["id"])


async def _pin(*collection_ids: uuid.UUID) -> None:
    """Set the collections' ``updated_at`` to ``_PINNED``, committed."""
    async with db_module.async_session() as session:
        await session.execute(
            sa.text(
                "UPDATE catalog.collections SET updated_at = :at "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"at": _PINNED, "ids": list(collection_ids)},
        )
        await session.commit()


async def _times(collection_id: uuid.UUID) -> tuple[datetime, datetime]:
    """The committed ``(created_at, updated_at)`` of a collection."""
    async with db_module.async_session() as session:
        row = (
            await session.execute(
                sa.select(Collection.created_at, Collection.updated_at).where(
                    Collection.id == collection_id
                )
            )
        ).one()
    return row.created_at, row.updated_at


async def _members(collection_id: uuid.UUID) -> set[uuid.UUID]:
    async with db_module.async_session() as session:
        return set(
            await session.scalars(
                sa.select(CollectionDataset.dataset_id).where(
                    CollectionDataset.collection_id == collection_id
                )
            )
        )


async def _add(
    client: AsyncClient, headers: dict, collection_id: uuid.UUID, *datasets: Dataset
) -> int:
    resp = await client.post(
        f"/catalog/collections/{collection_id}/datasets/",
        json={"dataset_ids": [str(d.id) for d in datasets]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["added"]


async def _delete(client: AsyncClient, headers: dict, dataset: Dataset):
    return await client.request(
        "DELETE",
        f"/datasets/{dataset.id}",
        json={"confirm_title": dataset.record.title},
        headers=headers,
    )


@pytest.fixture
async def dataset(test_db_session) -> Dataset:
    return await create_dataset(
        test_db_session, created_by=None, name=f"Member {uuid.uuid4().hex[:6]}"
    )


async def test_adding_a_dataset_moves_updated_at(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    collection_id = await _collection(client, admin_auth_header)
    created_at, _ = await _times(collection_id)
    await _pin(collection_id)

    assert await _add(client, admin_auth_header, collection_id, dataset) == 1

    created, updated = await _times(collection_id)
    assert created == created_at
    assert updated > _PINNED


async def test_adding_a_member_again_leaves_updated_at(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    collection_id = await _collection(client, admin_auth_header)
    await _add(client, admin_auth_header, collection_id, dataset)
    await _pin(collection_id)

    assert await _add(client, admin_auth_header, collection_id, dataset) == 0

    assert (await _times(collection_id))[1] == _PINNED


async def test_removing_a_member_moves_updated_at(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    collection_id = await _collection(client, admin_auth_header)
    await _add(client, admin_auth_header, collection_id, dataset)
    created_at, _ = await _times(collection_id)
    await _pin(collection_id)

    resp = await client.delete(
        f"/catalog/collections/{collection_id}/datasets/{dataset.id}",
        headers=admin_auth_header,
    )

    assert resp.status_code == 204, resp.text
    created, updated = await _times(collection_id)
    assert created == created_at
    assert updated > _PINNED


async def test_removing_a_non_member_leaves_updated_at(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    collection_id = await _collection(client, admin_auth_header)
    await _pin(collection_id)

    resp = await client.delete(
        f"/catalog/collections/{collection_id}/datasets/{dataset.id}",
        headers=admin_auth_header,
    )

    assert resp.status_code == 404, resp.text
    assert (await _times(collection_id))[1] == _PINNED


async def test_a_manifest_add_moves_updated_at(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    owner = await test_db_session.get(User, uuid.UUID(owner_id))
    collection = Collection(
        name=f"Manifest {uuid.uuid4().hex[:6]}", created_by=owner.id
    )
    test_db_session.add(collection)
    await test_db_session.commit()
    member = await create_dataset(test_db_session, created_by=owner.id)
    await _pin(collection.id)

    code = await DefaultProcessingPort().add_dataset_to_manifest_collection(
        test_db_session, collection.id, member.id, owner
    )
    await test_db_session.commit()

    assert code is None
    assert await _members(collection.id) == {member.id}
    assert (await _times(collection.id))[1] > _PINNED


async def test_deleting_a_member_moves_each_of_its_collections(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    first = await _collection(client, admin_auth_header)
    second = await _collection(client, admin_auth_header)
    unrelated = await _collection(client, admin_auth_header)
    for collection_id in (first, second):
        await _add(client, admin_auth_header, collection_id, dataset)
    created_at = {c: (await _times(c))[0] for c in (first, second)}
    await _pin(first, second, unrelated)

    resp = await _delete(client, admin_auth_header, dataset)

    assert resp.status_code == 204, resp.text
    for collection_id in (first, second):
        created, updated = await _times(collection_id)
        assert created == created_at[collection_id]
        assert updated > _PINNED
        assert await _members(collection_id) == set()
    assert (await _times(unrelated))[1] == _PINNED


async def test_a_bulk_delete_of_a_member_moves_its_collection(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    collection_id = await _collection(client, admin_auth_header)
    await _add(client, admin_auth_header, collection_id, dataset)
    await _pin(collection_id)

    resp = await client.post(
        "/datasets/bulk-delete/",
        json={
            "datasets": [
                {"dataset_id": str(dataset.id), "confirm_title": dataset.record.title}
            ]
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == 1, resp.text
    assert (await _times(collection_id))[1] > _PINNED


async def test_deleting_a_dataset_in_no_collection_touches_none(
    client: AsyncClient, admin_auth_header: dict, dataset, test_db_session
) -> None:
    other = await create_dataset(test_db_session, created_by=None)
    collection_id = await _collection(client, admin_auth_header)
    await _add(client, admin_auth_header, collection_id, other)
    await _pin(collection_id)

    resp = await _delete(client, admin_auth_header, dataset)

    assert resp.status_code == 204, resp.text
    assert (await _times(collection_id))[1] == _PINNED
    assert await _members(collection_id) == {other.id}


async def _hold_collection(holder, collection_id: uuid.UUID) -> int:
    """Take the collection row as a membership write does; returns the pid."""
    await holder.execute(
        sa.select(Collection.id)
        .where(Collection.id == collection_id)
        .with_for_update(key_share=True)
    )
    return await holder.scalar(sa.text("SELECT pg_backend_pid()"))


async def _dataset_exists(dataset_id: uuid.UUID) -> bool:
    async with db_module.async_session() as session:
        return await session.get(Dataset, dataset_id) is not None


async def test_a_delete_behind_a_collection_held_past_its_answer_leaves_its_time(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    """The collection stays held until the delete has answered, so only the
    stamp's own bound ends its wait: the delete has landed, and the held
    collection keeps its time."""
    collection_id = await _collection(client, admin_auth_header)
    await _add(client, admin_auth_header, collection_id, dataset)
    await _pin(collection_id)

    async with db_module.async_session() as holder:
        await _hold_collection(holder, collection_id)
        resp = await _delete(client, admin_auth_header, dataset)
        assert holder.in_transaction()
        await holder.rollback()

    assert resp.status_code == 204, resp.text
    assert not await _dataset_exists(dataset.id)
    assert await _members(collection_id) == set()
    assert (await _times(collection_id))[1] == _PINNED


async def test_a_delete_stamps_a_held_collection_once_it_is_released(
    client: AsyncClient, admin_auth_header: dict, dataset, monkeypatch
) -> None:
    """The stamp waits on the held collection after the delete committed,
    and moves its time once the holder lets go."""
    # Longer than any release below can take, so the stamp always outwaits it.
    monkeypatch.setattr(collections_service, "_MEMBER_DELETE_STAMP_BUDGET_S", 60.0)
    collection_id = await _collection(client, admin_auth_header)
    await _add(client, admin_auth_header, collection_id, dataset)
    await _pin(collection_id)

    async with db_module.async_session() as holder:
        holder_pid = await _hold_collection(holder, collection_id)
        deleting = asyncio.create_task(_delete(client, admin_auth_header, dataset))
        try:
            waiting_on = await await_lock_wait_query(blocked_by=holder_pid)
            gone_while_waiting = not await _dataset_exists(dataset.id)
        finally:
            await holder.rollback()
            resp = await deleting

    assert "UPDATE catalog.collections" in waiting_on, waiting_on
    assert gone_while_waiting
    assert resp.status_code == 204, resp.text
    assert (await _times(collection_id))[1] > _PINNED


async def test_a_delete_spends_one_wait_budget_across_its_collections(
    client: AsyncClient, admin_auth_header: dict, dataset, monkeypatch
) -> None:
    """Two held collections share the delete's stamp budget: the first wait
    spends it, the second is tried at once, and the delete still answers."""
    monkeypatch.setattr(collections_service, "_MEMBER_DELETE_STAMP_BUDGET_S", 0.3)
    waits: list[str] = []
    real_lock = collections_service.bounded_row_lock

    async def recording_lock(session, statement, **kwargs):
        if "lock_timeout" in kwargs:
            waits.append(kwargs["lock_timeout"])
        return await real_lock(session, statement, **kwargs)

    first = await _collection(client, admin_auth_header)
    second = await _collection(client, admin_auth_header)
    for collection_id in (first, second):
        await _add(client, admin_auth_header, collection_id, dataset)
    await _pin(first, second)
    monkeypatch.setattr(collections_service, "bounded_row_lock", recording_lock)

    async with db_module.async_session() as holder:
        await _hold_collection(holder, first)
        await _hold_collection(holder, second)
        resp = await _delete(client, admin_auth_header, dataset)
        await holder.rollback()

    assert resp.status_code == 204, resp.text
    assert not await _dataset_exists(dataset.id)
    assert len(waits) == 2, waits
    budget_ms = [int(w.removesuffix("ms")) for w in waits]
    assert budget_ms[0] <= 300
    # The first wait spent the budget, so the second isn't given another one.
    assert budget_ms[1] < 300 - 100, waits
    assert (await _times(first))[1] == _PINNED
    assert (await _times(second))[1] == _PINNED


async def _listed_times(client: AsyncClient, headers: dict) -> dict[str, str]:
    resp = await client.get("/catalog/collections/?limit=100", headers=headers)
    assert resp.status_code == 200, resp.text
    return {c["id"]: c["updated_at"] for c in resp.json()["collections"]}


@pytest.mark.parametrize("route", ["single", "bulk"])
async def test_a_list_cached_while_the_stamp_waits_shows_the_stamp_after_the_delete(
    client: AsyncClient, admin_auth_header: dict, dataset, monkeypatch, route: str
) -> None:
    """A collections list read between the delete's commit and its stamp
    caches the old time; the delete clears it again once it has stamped."""
    monkeypatch.setattr(collections_service, "_MEMBER_DELETE_STAMP_BUDGET_S", 60.0)
    collection_id = await _collection(client, admin_auth_header)
    await _add(client, admin_auth_header, collection_id, dataset)
    await _pin(collection_id)
    if route == "single":
        request = _delete(client, admin_auth_header, dataset)
    else:
        request = client.post(
            "/datasets/bulk-delete/",
            json={
                "datasets": [
                    {
                        "dataset_id": str(dataset.id),
                        "confirm_title": dataset.record.title,
                    }
                ]
            },
            headers=admin_auth_header,
        )

    async with db_module.async_session() as holder:
        holder_pid = await _hold_collection(holder, collection_id)
        deleting = asyncio.create_task(request)
        try:
            await await_lock_wait_query(blocked_by=holder_pid)
            during = await _listed_times(client, admin_auth_header)
        finally:
            await holder.rollback()
            resp = await deleting

    assert resp.status_code in (200, 204), resp.text
    stored = (await _times(collection_id))[1]
    assert stored > _PINNED
    assert datetime.fromisoformat(during[str(collection_id)]) == _PINNED
    after = await _listed_times(client, admin_auth_header)
    assert datetime.fromisoformat(after[str(collection_id)]) == stored


async def _owned_collection(session, owner: User) -> uuid.UUID:
    collection = Collection(
        name=f"Manifest {uuid.uuid4().hex[:6]}", created_by=owner.id
    )
    session.add(collection)
    await session.commit()
    return collection.id


async def test_a_manifest_add_begun_before_a_rename_stamps_no_earlier_than_it(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A publish whose transaction began before a rename committed still
    leaves the collection dated no earlier than the rename."""
    _, owner_id = await create_user(client, admin_auth_header, "editor")
    owner = await test_db_session.get(User, uuid.UUID(owner_id))
    collection_id = await _owned_collection(test_db_session, owner)
    member = await create_dataset(test_db_session, created_by=owner.id)

    async with db_module.async_session() as publish:
        started = await publish.scalar(sa.text("SELECT now()"))
        publisher = await publish.get(User, owner.id)
        renamed = await client.patch(
            f"/catalog/collections/{collection_id}",
            json={"name": f"Renamed {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        assert renamed.status_code == 200, renamed.text
        _, renamed_at = await _times(collection_id)
        code = await DefaultProcessingPort().add_dataset_to_manifest_collection(
            publish, collection_id, member.id, publisher
        )
        await publish.commit()

    assert code is None
    assert renamed_at > started
    assert (await _times(collection_id))[1] >= renamed_at


async def test_a_rename_that_waited_on_a_membership_change_stamps_no_earlier_than_it(
    client: AsyncClient, admin_auth_header: dict, dataset
) -> None:
    """A rename whose transaction began before a membership change committed
    leaves the collection dated no earlier than that change."""
    collection_id = await _collection(client, admin_auth_header)

    async with db_module.async_session() as adder:
        adder_pid = await _hold_collection(adder, collection_id)
        renaming = asyncio.create_task(
            client.patch(
                f"/catalog/collections/{collection_id}",
                json={"name": f"Renamed {uuid.uuid4().hex[:6]}"},
                headers=admin_auth_header,
            )
        )
        try:
            await await_lock_wait_query(blocked_by=adder_pid)
            await add_datasets_to_collection(adder, collection_id, [dataset.id], None)
            stamped = await adder.scalar(
                sa.select(Collection.updated_at).where(Collection.id == collection_id)
            )
            await adder.commit()
        finally:
            await adder.rollback()
            renamed = await renaming

    assert renamed.status_code == 200, renamed.text
    assert (await _times(collection_id))[1] >= stamped
