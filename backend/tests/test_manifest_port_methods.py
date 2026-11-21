"""ProcessingPort methods the publish manifest uses for collections and attributes.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import AttributeMetadata
from app.platform.extensions.defaults import DefaultProcessingPort
from tests.factories import create_dataset, create_user

pytestmark = pytest.mark.anyio

port = DefaultProcessingPort()


async def _person(
    client: AsyncClient, session: AsyncSession, admin_headers: dict, role: str
) -> User:
    _, user_id = await create_user(client, admin_headers, role)
    return await session.get(User, uuid.UUID(user_id))


async def _collection(session: AsyncSession, name: str, owner: User) -> Collection:
    collection = Collection(name=name, created_by=owner.id)
    session.add(collection)
    await session.commit()
    return collection


async def _count(session: AsyncSession, name: str) -> int:
    return await session.scalar(
        select(func.count()).select_from(Collection).where(Collection.name == name)
    )


@pytest.fixture
async def people(client, test_db_session, admin_auth_header):
    return {
        "owner": await _person(client, test_db_session, admin_auth_header, "editor"),
        "other": await _person(client, test_db_session, admin_auth_header, "editor"),
        "viewer": await _person(client, test_db_session, admin_auth_header, "viewer"),
    }


async def test_resolve_by_id_for_the_owner(test_db_session, people):
    collection = await _collection(test_db_session, "by-id", people["owner"])

    result = await port.resolve_manifest_collection(
        test_db_session, {"id": str(collection.id)}, people["owner"], may_create=False
    )

    assert result == (collection.id, None)


async def test_resolve_by_existing_name_for_the_owner(test_db_session, people):
    collection = await _collection(test_db_session, "by-name", people["owner"])

    result = await port.resolve_manifest_collection(
        test_db_session, {"name": "by-name"}, people["owner"], may_create=False
    )

    assert result == (collection.id, None)


async def test_resolve_creates_a_missing_name_when_allowed(test_db_session, people):
    collection_id, code = await port.resolve_manifest_collection(
        test_db_session, {"name": "fresh"}, people["owner"], may_create=True
    )

    assert code is None
    created = await test_db_session.get(Collection, collection_id)
    assert created.name == "fresh"
    assert created.created_by == people["owner"].id


async def test_resolve_does_not_create_unless_asked(test_db_session, people):
    result = await port.resolve_manifest_collection(
        test_db_session, {"name": "never"}, people["owner"], may_create=False
    )

    assert result == (None, "A033")
    assert await _count(test_db_session, "never") == 0


async def test_resolve_does_not_create_without_manage_collections(
    test_db_session, people
):
    result = await port.resolve_manifest_collection(
        test_db_session, {"name": "viewer-made"}, people["viewer"], may_create=True
    )

    assert result == (None, "A033")
    assert await _count(test_db_session, "viewer-made") == 0


async def test_resolve_refuses_a_caller_without_manage_collections(
    test_db_session, people
):
    # The viewer owns the collection, so only the permission can refuse them.
    collection = await _collection(test_db_session, "viewer-owned", people["viewer"])

    result = await port.resolve_manifest_collection(
        test_db_session, {"id": str(collection.id)}, people["viewer"], may_create=True
    )

    assert result == (None, "A033")


async def test_resolve_refuses_a_caller_who_does_not_own_the_collection(
    test_db_session, people
):
    collection = await _collection(test_db_session, "not-yours", people["owner"])

    by_id = await port.resolve_manifest_collection(
        test_db_session, {"id": str(collection.id)}, people["other"], may_create=True
    )
    by_name = await port.resolve_manifest_collection(
        test_db_session, {"name": "not-yours"}, people["other"], may_create=True
    )

    assert by_id == by_name == (None, "A033")


async def test_resolve_refuses_an_unknown_id(test_db_session, people):
    result = await port.resolve_manifest_collection(
        test_db_session, {"id": str(uuid.uuid4())}, people["owner"], may_create=True
    )

    assert result == (None, "A033")


async def test_add_dataset_to_an_owned_collection(test_db_session, people):
    collection = await _collection(test_db_session, "add-ok", people["owner"])
    dataset = await create_dataset(test_db_session, created_by=people["owner"].id)

    code = await port.add_dataset_to_manifest_collection(
        test_db_session, collection.id, dataset.id, people["owner"]
    )

    assert code is None
    member = await test_db_session.scalar(
        select(CollectionDataset).where(CollectionDataset.dataset_id == dataset.id)
    )
    assert member.collection_id == collection.id
    assert member.added_by == people["owner"].id


async def test_add_dataset_refuses_a_caller_without_manage_collections(
    test_db_session, people
):
    collection = await _collection(test_db_session, "add-viewer", people["viewer"])
    dataset = await create_dataset(test_db_session, created_by=people["viewer"].id)

    code = await port.add_dataset_to_manifest_collection(
        test_db_session, collection.id, dataset.id, people["viewer"]
    )

    assert code == "A033"
    assert (
        await test_db_session.scalar(select(func.count(CollectionDataset.dataset_id)))
        == 0
    )


async def test_add_dataset_refuses_a_caller_who_does_not_own_the_collection(
    test_db_session, people
):
    collection = await _collection(test_db_session, "add-other", people["owner"])
    dataset = await create_dataset(test_db_session, created_by=people["other"].id)

    code = await port.add_dataset_to_manifest_collection(
        test_db_session, collection.id, dataset.id, people["other"]
    )

    assert code == "A033"
    assert (
        await test_db_session.scalar(select(func.count(CollectionDataset.dataset_id)))
        == 0
    )


async def test_add_dataset_refuses_a_missing_collection(test_db_session, people):
    dataset = await create_dataset(test_db_session, created_by=people["owner"].id)

    code = await port.add_dataset_to_manifest_collection(
        test_db_session, uuid.uuid4(), dataset.id, people["owner"]
    )

    assert code == "A033"


async def test_apply_attributes_saves_matches_and_reports_the_rest(
    test_db_session, people
):
    dataset = await create_dataset(
        test_db_session,
        created_by=people["owner"].id,
        column_info=[
            {"name": "pop_2020", "type": "integer", "source_name": "POP 2020"},
            {"name": "name", "type": "text", "source_name": "Name"},
        ],
    )
    for position, field in enumerate(("pop_2020", "name")):
        test_db_session.add(
            AttributeMetadata(
                dataset_id=dataset.id, field_name=field, ordinal_position=position
            )
        )
    await test_db_session.commit()

    unmatched = await port.apply_manifest_attributes(
        test_db_session,
        dataset.id,
        [
            {"source_name": "POP 2020", "title": "Population", "units": "people"},
            {"source_name": "Missing", "title": "Nope"},
        ],
        actor_id=people["owner"].id,
    )
    await test_db_session.commit()

    assert unmatched == ["Missing"]
    rows = {
        a.field_name: a
        for a in (
            await test_db_session.scalars(
                select(AttributeMetadata).where(
                    AttributeMetadata.dataset_id == dataset.id
                )
            )
        ).all()
    }
    await test_db_session.refresh(rows["pop_2020"])
    assert (rows["pop_2020"].title, rows["pop_2020"].units) == ("Population", "people")
    assert rows["pop_2020"].description is None
    assert rows["name"].title is None


async def test_manifest_maps_are_not_implemented_yet(test_db_session, people):
    with pytest.raises(NotImplementedError):
        await port.apply_manifest_maps(
            test_db_session, [], people["owner"], dry_run=True
        )
