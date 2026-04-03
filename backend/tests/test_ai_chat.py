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
from app.datasets.models import Dataset
from app.maps.models import Map

from tests.factories import create_dataset


async def _get_user(session, username: str) -> User:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one()


async def _create_map(session, *, created_by: uuid.UUID, name: str = "Test Map") -> Map:
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
    dataset = await create_dataset(
        session,
        created_by=admin.id,
        name="Authoritative Dataset",
        table_name=f"auth_table_{uuid.uuid4().hex[:8]}",
    )

    layer = _make_chat_layer(dataset, table_name_override="fake_injected_table")
    validated = await _validate_chat_layers(session, admin, str(map_obj.id), [layer])

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

    private_ds = await create_dataset(
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

    viewer_map = await _create_map(session, created_by=viewer.id, name="Viewer Map")

    layer = _make_chat_layer(private_ds)
    validated = await _validate_chat_layers(
        session, viewer, str(viewer_map.id), [layer]
    )

    assert len(validated) == 0


# ---------------------------------------------------------------------------
# POST /ai/generate-map/ endpoint tests
# ---------------------------------------------------------------------------


async def _noop_check(*args, **kwargs):
    """No-op replacement for _check_ai_available in tests."""
    pass


@pytest.mark.anyio
async def test_generate_map_success(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch,
):
    """POST /ai/generate-map/ returns a map when LLM succeeds."""
    from app.ai import router as ai_router
    from app.ai import service as ai_service

    fake_result = {
        "map_id": str(uuid.uuid4()),
        "map_name": "Generated Map",
        "explanation": "Created a map of parks",
        "datasets_used": ["parks"],
    }

    async def mock_generate(*args, **kwargs):
        return fake_result

    monkeypatch.setattr(ai_service, "generate_map_from_prompt", mock_generate)
    monkeypatch.setattr(ai_router, "_check_ai_available", _noop_check)

    resp = await client.post(
        "/ai/generate-map/",
        json={"prompt": "Show me parks in NYC"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["map_name"] == "Generated Map"
    assert data["explanation"] == "Created a map of parks"
    assert data["datasets_used"] == ["parks"]


@pytest.mark.anyio
async def test_generate_map_unauthenticated(client: AsyncClient):
    """POST /ai/generate-map/ without auth returns 401."""
    resp = await client.post(
        "/ai/generate-map/",
        json={"prompt": "Show me parks"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_generate_map_llm_unavailable(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch,
):
    """POST /ai/generate-map/ returns 503 when LLM is not configured."""
    resp = await client.post(
        "/ai/generate-map/",
        json={"prompt": "Show me parks in NYC"},
        headers=admin_auth_header,
    )
    # Without API keys configured, _check_ai_available returns 503
    assert resp.status_code == 503
