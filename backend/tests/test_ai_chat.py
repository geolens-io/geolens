"""Tests for AI chat layer validation (_validate_chat_layers).

Covers: map ownership, dataset access filtering, and authoritative
table name overwriting.
"""

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.processing.ai.router import _validate_chat_layers
from app.processing.ai.schemas import ChatMapLayer
from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.maps.models import Map
from app.platform.extensions.defaults import DefaultProcessingPort

from tests.factories import create_dataset

_default_port = DefaultProcessingPort()


async def _get_user(session, username: str) -> User:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one()


async def _create_map(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Test Map",
    visibility: str = "private",
) -> Map:
    """Create a minimal Map."""
    map_obj = Map(name=name, created_by=created_by, visibility=visibility)
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
        await _validate_chat_layers(session, admin, fake_map_id, [], port=_default_port)

    assert exc_info.value.status_code == 404


async def _create_other_user(session) -> User:
    """Create a fresh non-admin user that owns nothing."""
    other_user = User(
        username=f"other_{uuid.uuid4().hex[:8]}",
        password_hash="unused",
        is_active=True,
    )
    session.add(other_user)
    await session.flush()
    await session.commit()
    await session.refresh(other_user)
    return other_user


@pytest.mark.anyio
async def test_validate_rejects_non_viewer_of_private_map(
    client: AsyncClient,
    test_db_session,
):
    """Returns 404 (no existence oracle) when the user cannot view a private map.

    AI chat is gated on VIEW access, not ownership: a non-owner of a *private*
    map cannot view it, so it is indistinguishable from a missing map (404).
    """
    session = test_db_session
    admin = await _get_user(session, settings.geolens_admin_username)
    map_obj = await _create_map(session, created_by=admin.id, visibility="private")
    other_user = await _create_other_user(session)

    with pytest.raises(HTTPException) as exc_info:
        await _validate_chat_layers(
            session, other_user, str(map_obj.id), [], port=_default_port
        )

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_validate_allows_viewer_of_public_map_read_only(
    client: AsyncClient,
    test_db_session,
):
    """A non-owner who can VIEW a public map is allowed, but read-only (can_edit=False).

    This is the builder-audit follow-up: anyone who can view a map may ask the
    AI questions about it; only the owner/admin may use the AI to edit. can_edit
    selects the read-only vs full tool set downstream.
    """
    session = test_db_session
    admin = await _get_user(session, settings.geolens_admin_username)
    map_obj = await _create_map(session, created_by=admin.id, visibility="public")
    other_user = await _create_other_user(session)

    validated, _basemap, can_edit = await _validate_chat_layers(
        session, other_user, str(map_obj.id), [], port=_default_port
    )

    assert validated == []
    assert can_edit is False


@pytest.mark.anyio
async def test_validate_owner_can_edit(
    client: AsyncClient,
    test_db_session,
):
    """The map owner gets can_edit=True (full AI tool set)."""
    session = test_db_session
    admin = await _get_user(session, settings.geolens_admin_username)
    map_obj = await _create_map(session, created_by=admin.id, visibility="private")

    _validated, _basemap, can_edit = await _validate_chat_layers(
        session, admin, str(map_obj.id), [], port=_default_port
    )

    assert can_edit is True


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
    validated, _basemap, _can_edit = await _validate_chat_layers(
        session, admin, str(map_obj.id), [layer], port=_default_port
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
    validated, _basemap, _can_edit = await _validate_chat_layers(
        session, viewer, str(viewer_map.id), [layer], port=_default_port
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
    from app.processing.ai import router as ai_router

    fake_result = {
        "map_id": str(uuid.uuid4()),
        "map_name": "Generated Map",
        "explanation": "Created a map of parks",
        "datasets_used": ["parks"],
    }

    async def mock_generate(*args, **kwargs):
        return fake_result

    # Patch both the module-level import in the router AND the availability check
    monkeypatch.setattr(ai_router, "generate_map_from_prompt", mock_generate)
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
    from app.processing.ai import router as ai_router

    async def unavailable(_db):
        raise HTTPException(
            status_code=503,
            detail="Selected LLM provider API key not configured",
        )

    monkeypatch.setattr(ai_router, "_check_ai_available", unavailable)

    resp = await client.post(
        "/ai/generate-map/",
        json={"prompt": "Show me parks in NYC"},
        headers=admin_auth_header,
    )
    # Without API keys configured, _check_ai_available returns 503
    assert resp.status_code == 503
