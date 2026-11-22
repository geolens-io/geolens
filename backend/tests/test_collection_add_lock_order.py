"""Adding datasets to a collection takes the dataset rows before the collection
row, the order a manifest publish holds them in.

The publish holds its dataset row ``FOR UPDATE`` and then locks the
collection. An add that locked the collection first and then waited on the
dataset through the membership foreign key closed a cycle that PostgreSQL
broke by failing one side.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError

import app.core.db as db_module
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import Dataset
from tests.factories import create_collection_via_api, create_dataset
from tests.lock_wait import await_lock_wait_query

pytestmark = pytest.mark.anyio


async def test_add_waits_on_a_held_dataset_without_holding_the_collection(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    collection_id = uuid.UUID(
        (await create_collection_via_api(client, admin_auth_header))["id"]
    )
    dataset = await create_dataset(
        test_db_session, created_by=None, name=f"Held {uuid.uuid4().hex[:6]}"
    )

    async with db_module.async_session() as publish:
        await publish.execute(
            sa.select(Dataset.id).where(Dataset.id == dataset.id).with_for_update()
        )
        publish_pid = await publish.scalar(sa.text("SELECT pg_backend_pid()"))
        adding = asyncio.create_task(
            client.post(
                f"/catalog/collections/{collection_id}/datasets/",
                json={"dataset_ids": [str(dataset.id)]},
                headers=admin_auth_header,
            )
        )
        try:
            await await_lock_wait_query(blocked_by=publish_pid)
            try:
                await publish.execute(
                    sa.select(Collection.id)
                    .where(Collection.id == collection_id)
                    .with_for_update(key_share=True, nowait=True)
                )
            except DBAPIError:
                pytest.fail(
                    "the add held the collection row while it waited on the dataset"
                )
            publish.add(
                CollectionDataset(collection_id=collection_id, dataset_id=dataset.id)
            )
            await publish.commit()
        finally:
            # The add waits on the dataset row until this transaction ends.
            await publish.rollback()
            resp = await adding

    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 0
    async with db_module.async_session() as session:
        members = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CollectionDataset)
            .where(CollectionDataset.collection_id == collection_id)
        )
    assert members == 1
