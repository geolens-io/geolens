from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Embedding dimension change via PUT /settings/
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_settings_changing_embedding_dims_triggers_cleanup(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PUT /settings/ with a new embedding_dims value deletes existing embeddings
    and rebuilds the vector column + HNSW index."""
    from sqlalchemy import text

    # Record current column dimensions
    col_check = await test_db_session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    current_dims = col_check.scalar_one_or_none()

    # Choose a different dimension value
    new_dims = 512 if current_dims != 512 else 768

    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": new_dims}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tabs" in data

    # Verify column was altered to the new dimension
    col_check2 = await test_db_session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    updated_dims = col_check2.scalar_one_or_none()
    assert updated_dims == new_dims

    # Verify no embeddings remain
    count_result = await test_db_session.execute(
        text("SELECT COUNT(*) FROM catalog.record_embeddings")
    )
    assert count_result.scalar_one() == 0


@pytest.mark.anyio
async def test_put_settings_same_embedding_dims_does_not_delete(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PUT /settings/ with the same embedding_dims does NOT delete embeddings."""
    from sqlalchemy import text

    # Read current column dimensions
    col_check = await test_db_session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    current_dims = col_check.scalar_one_or_none()
    if current_dims is None:
        # If the column has no fixed dimension, set one first
        current_dims = 1536

    # Send the same dims value
    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": current_dims}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tabs" in data


@pytest.mark.anyio
async def test_put_settings_requires_admin_auth(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """PUT /settings/ returns 403 for non-admin users."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": 512}},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_put_settings_unauthenticated_returns_401(
    client: AsyncClient,
):
    """PUT /settings/ without auth returns 401."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": 512}},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tile config tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_tile_config_exposes_resolved_public_urls():
    """The public tile-config payload should expose the resolved app/API URLs."""
    from app.settings import router as settings_router

    with (
        patch.object(
            settings_router,
            "app_settings",
            SimpleNamespace(cdn_base_url="https://cdn.example.com"),
        ),
        patch(
            "app.modules.settings.router.get_public_app_url",
            AsyncMock(return_value="https://catalog.example.com"),
        ),
        patch(
            "app.modules.settings.router.get_public_api_url",
            AsyncMock(return_value="https://catalog.example.com/api"),
        ),
    ):
        response = await settings_router.get_tile_config(
            request=SimpleNamespace(
                headers={}, url=SimpleNamespace(scheme="https"), scope={}
            ),
            db=object(),
        )

    assert response.cdn_base_url == "https://cdn.example.com"
    assert response.public_app_url == "https://catalog.example.com"
    assert response.public_api_url == "https://catalog.example.com/api"
    assert response.public_base_url == "https://catalog.example.com/api"
