"""Collection writes re-check the caller under the collection row lock.

Each test lets the handler's guard pass, commits a change to the caller's
standing from a second session straight after it, and lets the request run on.
The write must be refused with the guard's 403 and leave nothing behind.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.catalog.collections import router as collections_router
from app.modules.catalog.collections.models import Collection, CollectionDataset
from tests.factories import create_collection_via_api, create_dataset
from tests.write_recheck_races import (  # noqa: F401 - people is a fixture
    _commit,
    _deactivate,
    _demote_to_viewer,
    _then,
    people,
)

pytestmark = pytest.mark.anyio


def _transfer_collection(collection_id: uuid.UUID, owner_id: uuid.UUID):
    return (
        update(Collection)
        .where(Collection.id == collection_id)
        .values(created_by=owner_id)
    )


async def _owned_collection(
    client: AsyncClient, session: AsyncSession, owner: tuple
) -> tuple[uuid.UUID, uuid.UUID]:
    """A collection owned by ``owner`` holding one of their datasets."""
    owner_headers, owner_id = owner
    collection_id = uuid.UUID(
        (await create_collection_via_api(client, owner_headers))["id"]
    )
    dataset = await create_dataset(session, created_by=owner_id)
    added = await client.post(
        f"/catalog/collections/{collection_id}/datasets/",
        json={"dataset_ids": [str(dataset.id)]},
        headers=owner_headers,
    )
    assert added.status_code == 200, added.text
    return collection_id, dataset.id


async def _members(collection_id: uuid.UUID) -> int:
    async with db_module.async_session() as session:
        return await session.scalar(
            select(func.count())
            .select_from(CollectionDataset)
            .where(CollectionDataset.collection_id == collection_id)
        )


def _guard_then(monkeypatch: pytest.MonkeyPatch, statement) -> None:
    monkeypatch.setattr(
        collections_router,
        "check_collection_ownership",
        _then(collections_router.check_collection_ownership, statement),
    )


async def test_rename_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, _ = people["owner"]
    collection_id, _ = await _owned_collection(client, test_db_session, people["owner"])

    _guard_then(monkeypatch, _transfer_collection(collection_id, people["target"]))
    resp = await client.patch(
        f"/catalog/collections/{collection_id}",
        json={"name": "renamed"},
        headers=owner_headers,
    )

    assert resp.status_code == 403, resp.text
    async with db_module.async_session() as session:
        name = await session.scalar(
            select(Collection.name).where(Collection.id == collection_id)
        )
    assert name != "renamed"


async def test_adding_a_dataset_is_refused_after_a_role_downgrade(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    collection_id, _ = await _owned_collection(client, test_db_session, people["owner"])
    another = await create_dataset(test_db_session, created_by=owner_id)

    _guard_then(monkeypatch, _demote_to_viewer(owner_id))
    resp = await client.post(
        f"/catalog/collections/{collection_id}/datasets/",
        json={"dataset_ids": [str(another.id)]},
        headers=owner_headers,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Missing permission: manage_collections"
    assert await _members(collection_id) == 1


@pytest.mark.parametrize("whole", [True, False])
async def test_removal_is_refused_after_a_deactivation(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    whole: bool,
) -> None:
    owner_headers, owner_id = people["owner"]
    collection_id, dataset_id = await _owned_collection(
        client, test_db_session, people["owner"]
    )

    _guard_then(monkeypatch, _deactivate(owner_id))
    path = f"/catalog/collections/{collection_id}"
    if not whole:
        path += f"/datasets/{dataset_id}"
    resp = await client.delete(path, headers=owner_headers)

    assert resp.status_code == 403, resp.text
    assert await _members(collection_id) == 1
