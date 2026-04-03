"""Integration tests for provenance attribution response contracts (PROV-01/02)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from app.auth.models import User
from app.datasets.models import Dataset, Record

from tests.factories import get_user_id


async def _create_actor_user(
    session,
    *,
    username_prefix: str,
) -> User:
    username = f"{username_prefix}_{uuid.uuid4().hex[:8]}"
    user = User(
        username=username,
        email=f"{username}@example.com",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _create_dataset(
    session,
    *,
    title: str,
    created_by: uuid.UUID | None,
    updated_by: uuid.UUID | None,
    created_at: datetime,
    updated_at: datetime,
) -> Dataset:
    record = Record(
        title=title,
        summary=f"Dataset for {title}",
        visibility="public",
        record_status="published",
        created_by=created_by,
        updated_by=updated_by,
        created_at=created_at,
        updated_at=updated_at,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="provenance.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _search_feature(
    client: AsyncClient,
    *,
    auth_header: dict,
    query: str,
    dataset_id: uuid.UUID,
) -> dict:
    resp = await client.get(
        "/search/datasets/",
        params={"q": query, "limit": 50},
        headers=auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    for feature in data["features"]:
        if feature["id"] == str(dataset_id):
            return feature
    raise AssertionError(
        f"Dataset {dataset_id} not found in search response for query: {query}"
    )


@pytest.mark.anyio
async def test_dataset_detail_resolves_actor_labels(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    editor_user = await _create_actor_user(
        test_db_session,
        username_prefix="prov_editor",
    )

    now = datetime.now(timezone.utc)
    dataset = await _create_dataset(
        test_db_session,
        title=f"Detail actor labels {uuid.uuid4().hex[:6]}",
        created_by=admin_id,
        updated_by=editor_user.id,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(hours=4),
    )

    resp = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["created_by_display"] == "admin"
    assert payload["last_edited_by_display"] == editor_user.username
    assert payload["last_edited_at"] is not None


@pytest.mark.anyio
async def test_dataset_detail_unknown_creator_and_never_edited(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    created_at = datetime.now(timezone.utc) - timedelta(days=1)
    dataset = await _create_dataset(
        test_db_session,
        title=f"Detail unknown creator {uuid.uuid4().hex[:6]}",
        created_by=None,
        updated_by=None,
        created_at=created_at,
        updated_at=created_at,
    )

    resp = await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["created_by"] is None
    assert payload["created_by_display"] == "Unknown"
    assert payload["last_edited_by_display"] is None
    assert payload["last_edited_at"] is None


@pytest.mark.anyio
async def test_search_records_include_updated_actor_display(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    editor_user = await _create_actor_user(
        test_db_session,
        username_prefix="search_editor",
    )

    token = uuid.uuid4().hex[:8]
    query = f"resolved provenance {token}"
    now = datetime.now(timezone.utc)
    dataset = await _create_dataset(
        test_db_session,
        title=query,
        created_by=admin_id,
        updated_by=editor_user.id,
        created_at=now - timedelta(days=3),
        updated_at=now - timedelta(hours=2),
    )

    feature = await _search_feature(
        client,
        auth_header=admin_auth_header,
        query=token,
        dataset_id=dataset.id,
    )
    props = feature["properties"]
    assert props["updated_by_display"] == editor_user.username
    assert props["never_edited"] is False


@pytest.mark.anyio
async def test_search_fallbacks_for_missing_editor_and_never_edited_state(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    now = datetime.now(timezone.utc)
    token = uuid.uuid4().hex[:8]

    system_dataset = await _create_dataset(
        test_db_session,
        title=f"system provenance {token}",
        created_by=admin_id,
        updated_by=None,
        created_at=now - timedelta(days=5),
        updated_at=now - timedelta(days=1),
    )
    never_dataset = await _create_dataset(
        test_db_session,
        title=f"never edited provenance {token}",
        created_by=admin_id,
        updated_by=None,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
    )

    system_feature = await _search_feature(
        client,
        auth_header=admin_auth_header,
        query=f"system {token}",
        dataset_id=system_dataset.id,
    )
    never_feature = await _search_feature(
        client,
        auth_header=admin_auth_header,
        query=f"never {token}",
        dataset_id=never_dataset.id,
    )

    system_props = system_feature["properties"]
    assert system_props["updated_by_display"] == "System"
    assert system_props["never_edited"] is False

    never_props = never_feature["properties"]
    assert never_props["updated_by_display"] is None
    assert never_props["never_edited"] is True
