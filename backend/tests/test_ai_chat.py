"""Tests for AI chat layer validation (_validate_chat_layers).

Covers: map ownership, dataset access filtering, and authoritative
table name overwriting.
"""

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.ai.router import _validate_chat_layers
from app.ai.schemas import ChatMapLayer
from app.auth.models import User
from app.config import settings
from app.datasets.models import Dataset, Record
from app.maps.models import Map


async def _get_user(session, username: str) -> User:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one()


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    table_name: str,
    visibility: str = "public",
    geometry_type: str = "MultiPolygon",
) -> Dataset:
    """Create a minimal Record + Dataset pair."""
    record = Record(
        title=name,
        summary=f"Test dataset {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=geometry_type,
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_map(
    session, *, created_by: uuid.UUID, name: str = "Test Map"
) -> Map:
    """Create a minimal Map."""
    map_obj = Map(name=name, created_by=created_by)
    session.add(map_obj)
    await session.flush()
    await session.commit()
    await session.refresh(map_obj)
    return map_obj


def _make_chat_layer(
    dataset: Dataset, *, table_name_override: str | None = None
) -> ChatMapLayer:
    """Build a ChatMapLayer from a Dataset, optionally overriding the table name."""
    return ChatMapLayer(
        id=str(uuid.uuid4()),
        name=f"Layer for {dataset.table_name}",
        dataset_id=str(dataset.id),
        dataset_table_name=table_name_override or dataset.table_name,
        geometry_type=dataset.geometry_type,
    )


@pytest.mark.anyio
async def test_validate_rejects_invalid_map_id(
    client: AsyncClient,
    test_db_session,
):
    """Returns 404 for a non-existent map."""
    session = test_db_session
    admin = await _get_user(session, settings.geolens_admin_username)
    fake_map_id = str(uuid.uuid4())

    with pytest.raises(HTTPException) as exc_info:
        await _validate_chat_layers(session, admin, fake_map_id, [])

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_validate_rejects_non_owner(
    client: AsyncClient,
    test_db_session,
):
    """Returns 403 when user doesn't own the map."""
    session = test_db_session
    admin = await _get_user(session, settings.geolens_admin_username)

    map_obj = await _create_map(session, created_by=admin.id)

    other_user = User(
        username=f"other_{uuid.uuid4().hex[:8]}",
        password_hash="unused",
        is_active=True,
    )
    session.add(other_user)
    await session.flush()
    await session.commit()
    await session.refresh(other_user)

    with pytest.raises(HTTPException) as exc_info:
        await _validate_chat_layers(session, other_user, str(map_obj.id), [])

    assert exc_info.value.status_code == 403


@pytest.mark.anyio
async def test_validate_overwrites_client_table_name(
    client: AsyncClient,
    test_db_session,
):
    """Overwrites client-supplied dataset_table_name with authoritative DB value."""
    session = test_db_session
    admin = await _get_user(session, settings.geolens_admin_username)

    map_obj = await _create_map(session, created_by=admin.id)
    dataset = await _create_dataset(
        session,
        created_by=admin.id,
        name="Authoritative Dataset",
        table_name=f"auth_table_{uuid.uuid4().hex[:8]}",
    )

    layer = _make_chat_layer(dataset, table_name_override="fake_injected_table")
    validated = await _validate_chat_layers(
        session, admin, str(map_obj.id), [layer]
    )

    assert len(validated) == 1
    assert validated[0].dataset_table_name == dataset.table_name


@pytest.mark.anyio
async def test_validate_filters_inaccessible_dataset(
    client: AsyncClient,
    test_db_session,
):
    """Filters out layers referencing private datasets the user cannot access."""
    session = test_db_session
    admin = await _get_user(session, settings.geolens_admin_username)

    private_ds = await _create_dataset(
        session,
        created_by=admin.id,
        name="Private Dataset",
        table_name=f"priv_{uuid.uuid4().hex[:8]}",
        visibility="private",
    )

    viewer = User(
        username=f"viewer_{uuid.uuid4().hex[:8]}",
        password_hash="unused",
        is_active=True,
    )
    session.add(viewer)
    await session.flush()
    await session.commit()
    await session.refresh(viewer)

    viewer_map = await _create_map(
        session, created_by=viewer.id, name="Viewer Map"
    )

    layer = _make_chat_layer(private_ds)
    validated = await _validate_chat_layers(
        session, viewer, str(viewer_map.id), [layer]
    )

    assert len(validated) == 0
