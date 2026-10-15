"""Relationship, source-health, validation and record child writes re-check
the caller under the dataset's catalog rows.

Each test lets the handler's guard pass, commits a change to the caller's
standing from a second session straight after it, and lets the request run on.
The write must be refused with the guard's 403 or 404 and leave nothing behind.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.catalog.datasets.domain import service as dataset_service
from app.modules.catalog.datasets.api import router_data, router_health
from app.modules.catalog.datasets.api import router_metadata
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    DatasetRelationship,
    Record,
    RecordContact,
    RecordTranslation,
)
from app.modules.catalog.records import router as records_router
from app.modules.catalog.sources.origin_probe import HEALTHY, OriginProbeResult
from app.platform.extensions import get_catalog_port
from tests.factories import create_dataset
from tests.test_source_health_1222 import _stac_dataset

from tests.write_recheck_races import (  # noqa: F401 - people is a fixture
    _commit,
    _demote_to_viewer,
    _then,
    _transfer_dataset,
    people,
)

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_init_tile_pool_for_tests")]

_JOIN_COLUMNS = [{"name": "ref_id", "type": "integer"}]


async def _related_pair(
    session: AsyncSession, owner_id: uuid.UUID
) -> tuple[Dataset, Dataset]:
    source = await create_dataset(
        session, created_by=owner_id, column_info=_JOIN_COLUMNS
    )
    target = await create_dataset(
        session, created_by=owner_id, column_info=_JOIN_COLUMNS
    )
    return source, target


def _relationship_body(target: Dataset) -> dict:
    return {
        "target_dataset_id": str(target.record_id),
        "source_column": "ref_id",
        "target_column": "gid",
    }


async def test_relationship_create_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    source, target = await _related_pair(test_db_session, owner_id)
    source_id, source_record_id = source.id, source.record_id

    monkeypatch.setattr(
        router_metadata,
        "check_dataset_write_access",
        _then(
            router_metadata.check_dataset_write_access,
            _transfer_dataset(source_id, people["target"]),
        ),
    )
    resp = await client.post(
        f"/datasets/{source_id}/relationships/",
        json=_relationship_body(target),
        headers=owner_headers,
    )

    assert resp.status_code == 403, resp.text
    assert not await test_db_session.scalar(
        select(DatasetRelationship.id).where(
            DatasetRelationship.source_dataset_id == source_record_id
        )
    )


async def test_relationship_delete_is_refused_after_a_role_downgrade(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    source, target = await _related_pair(test_db_session, owner_id)
    created = await client.post(
        f"/datasets/{source.id}/relationships/",
        json=_relationship_body(target),
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    relationship_id = uuid.UUID(created.json()["id"])

    monkeypatch.setattr(
        router_metadata,
        "check_dataset_write_access",
        _then(router_metadata.check_dataset_write_access, _demote_to_viewer(owner_id)),
    )
    resp = await client.delete(
        f"/datasets/relationships/{relationship_id}/", headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    assert await test_db_session.scalar(
        select(DatasetRelationship.id).where(DatasetRelationship.id == relationship_id)
    )


async def test_join_column_repair_is_skipped_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    source, target = await _related_pair(test_db_session, owner_id)
    for dataset in (source, target):
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{dataset.table_name} "
                "(gid integer PRIMARY KEY, ref_id integer)"
            )
        )
    await test_db_session.execute(
        text(f"INSERT INTO data.{source.table_name} (gid, ref_id) VALUES (1, 1)")
    )
    test_db_session.add(
        AttributeMetadata(dataset_id=source.id, field_name="ref_id", is_current=True)
    )
    await test_db_session.commit()
    created = await client.post(
        f"/datasets/{source.id}/relationships/",
        json=_relationship_body(target),
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    await test_db_session.execute(
        text(f"ALTER TABLE data.{source.table_name} DROP COLUMN ref_id")
    )
    await test_db_session.commit()

    # Only the repair's own guard calls this on the read path.
    monkeypatch.setattr(
        router_metadata,
        "check_dataset_write_access",
        _then(
            router_metadata.check_dataset_write_access,
            _transfer_dataset(source.id, people["target"]),
        ),
    )
    resp = await client.get(
        f"/datasets/{source.id}/features/1/related/{created.json()['id']}/",
        headers=owner_headers,
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "relationship_column_missing"
    assert await test_db_session.scalar(
        select(AttributeMetadata.is_current).where(
            AttributeMetadata.dataset_id == source.id,
            AttributeMetadata.field_name == "ref_id",
        )
    )


async def test_source_health_verdict_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    dataset = await _stac_dataset(test_db_session, created_by=owner_id)
    dataset_id = dataset.id

    async def healthy(asset_uri, item_href) -> OriginProbeResult:
        return OriginProbeResult(HEALTHY, None, contacted=True)

    monkeypatch.setattr(router_health, "_probe_stac_targets", healthy)
    monkeypatch.setattr(
        router_health,
        "check_dataset_write_access",
        _then(
            router_health.check_dataset_write_access,
            _transfer_dataset(dataset_id, people["target"]),
        ),
    )
    resp = await client.post(
        f"/datasets/{dataset_id}/source-health/", headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    health = await test_db_session.scalar(
        select(Dataset.source_health).where(Dataset.id == dataset_id)
    )
    assert health is None


async def test_forced_validation_refresh_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    dataset_id = dataset.id
    stored = {"score": 10}
    await _commit(
        update(Dataset).where(Dataset.id == dataset_id).values(quality_detail=stored)
    )
    port_cls = type(get_catalog_port())

    async def fresh_score(self, *args, **kwargs) -> dict:
        return {"score": 99}

    monkeypatch.setattr(port_cls, "compute_quality_score", fresh_score)
    monkeypatch.setattr(
        router_data,
        "check_dataset_write_access",
        _then(
            router_data.check_dataset_write_access,
            _transfer_dataset(dataset_id, people["target"]),
        ),
    )
    resp = await client.get(
        f"/datasets/{dataset_id}/validate/?refresh=true", headers=owner_headers
    )

    assert resp.status_code == 403, resp.text
    async with db_module.async_session() as session:
        quality = await session.scalar(
            select(Dataset.quality_detail).where(Dataset.id == dataset_id)
        )
    assert quality == stored


async def test_record_contact_create_is_refused_after_a_transfer(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    dataset_id, record_id = dataset.id, dataset.record_id

    monkeypatch.setattr(
        records_router,
        "_check_record_ownership",
        _then(
            records_router._check_record_ownership,
            _transfer_dataset(dataset_id, people["target"]),
        ),
    )
    resp = await client.post(
        f"/records/{record_id}/contacts/",
        json={"role": "owner", "name": "Late writer"},
        headers=owner_headers,
    )

    assert resp.status_code == 403, resp.text
    assert not await test_db_session.scalar(
        select(RecordContact.id).where(RecordContact.record_id == record_id)
    )


async def test_record_translation_upsert_is_refused_after_a_role_downgrade(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    record_id = dataset.record_id

    monkeypatch.setattr(
        records_router,
        "_check_record_ownership",
        _then(records_router._check_record_ownership, _demote_to_viewer(owner_id)),
    )
    resp = await client.put(
        f"/records/{record_id}/translations/fr/",
        json={"title": "Titre"},
        headers=owner_headers,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Missing permission: edit_metadata"
    assert not await test_db_session.scalar(
        select(RecordTranslation.id).where(RecordTranslation.record_id == record_id)
    )


async def test_opposing_relationship_creates_both_land(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_headers, owner_id = people["owner"]
    first, second = await _related_pair(test_db_session, owner_id)
    original = dataset_service.create_relationship
    arrived = asyncio.Event()
    waiting = 0

    # Each create waits here, holding its locks, until the other arrives or a
    # short wait runs out, so both reach the insert holding what they took.
    async def meet_then_create(*args, **kwargs):
        nonlocal waiting
        waiting += 1
        if waiting == 2:
            arrived.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(arrived.wait(), timeout=0.5)
        return await original(*args, **kwargs)

    monkeypatch.setattr(dataset_service, "create_relationship", meet_then_create)
    responses = await asyncio.gather(
        client.post(
            f"/datasets/{first.id}/relationships/",
            json=_relationship_body(second),
            headers=owner_headers,
        ),
        client.post(
            f"/datasets/{second.id}/relationships/",
            json=_relationship_body(first),
            headers=owner_headers,
        ),
    )

    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]


async def test_a_readers_first_validation_fill_does_not_wait_on_the_record(
    client: AsyncClient,
    test_db_session: AsyncSession,
    people: dict,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fill writes the datasets row alone, so a held records row leaves it be."""
    _, owner_id = people["owner"]
    dataset = await create_dataset(test_db_session, created_by=owner_id)
    dataset_id, record_id = dataset.id, dataset.record_id
    port_cls = type(get_catalog_port())

    async def fresh_score(self, *args, **kwargs) -> dict:
        return {"score": 99}

    monkeypatch.setattr(port_cls, "compute_quality_score", fresh_score)
    async with db_module.async_session() as holder:
        await holder.execute(
            select(Record.id).where(Record.id == record_id).with_for_update()
        )
        resp = await asyncio.wait_for(
            client.get(f"/datasets/{dataset_id}/validate/"), timeout=10
        )
        await holder.rollback()

    assert resp.status_code == 200, resp.text
    async with db_module.async_session() as session:
        quality = await session.scalar(
            select(Dataset.quality_detail).where(Dataset.id == dataset_id)
        )
    assert quality == {"score": 99}
