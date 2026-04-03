"""Integration tests for Settings OAuth CRUD and utility endpoints.

Tests cover: OAuth provider create/update/delete, settings reset,
detect embedding dims, tile config, and RBAC enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# OAuth provider CRUD
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_oauth_provider(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /settings/oauth-providers/ creates a provider and returns 201."""
    slug = f"test-provider-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/settings/oauth-providers/",
        json={
            "slug": slug,
            "display_name": "Test Provider",
            "provider_type": "oidc",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "authorize_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == slug
    assert data["display_name"] == "Test Provider"
    assert "id" in data


@pytest.mark.anyio
async def test_create_oauth_provider_non_admin_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """POST /settings/oauth-providers/ as viewer returns 403."""
    resp = await client.post(
        "/settings/oauth-providers/",
        json={
            "slug": "forbidden-provider",
            "display_name": "Forbidden",
            "client_id": "x",
            "client_secret": "x",
            "authorize_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
        },
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_create_oauth_provider_unauthenticated(client: AsyncClient):
    """POST /settings/oauth-providers/ without auth returns 401."""
    resp = await client.post(
        "/settings/oauth-providers/",
        json={
            "slug": "noauth-provider",
            "display_name": "NoAuth",
            "client_id": "x",
            "client_secret": "x",
            "authorize_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
        },
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_update_oauth_provider(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """PUT /settings/oauth-providers/{id} updates the provider."""
    slug = f"update-provider-{uuid.uuid4().hex[:8]}"
    create_resp = await client.post(
        "/settings/oauth-providers/",
        json={
            "slug": slug,
            "display_name": "Before Update",
            "provider_type": "oidc",
            "client_id": "cid",
            "client_secret": "csec",
            "authorize_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
        },
        headers=admin_auth_header,
    )
    assert create_resp.status_code == 201
    provider_id = create_resp.json()["id"]

    resp = await client.put(
        f"/settings/oauth-providers/{provider_id}",
        json={"display_name": "After Update"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "After Update"


@pytest.mark.anyio
async def test_update_oauth_provider_not_found(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """PUT /settings/oauth-providers/{random_uuid} returns 404."""
    resp = await client.put(
        f"/settings/oauth-providers/{uuid.uuid4()}",
        json={"display_name": "Ghost"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_update_oauth_provider_non_admin_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """PUT /settings/oauth-providers/{id} as viewer returns 403."""
    resp = await client.put(
        f"/settings/oauth-providers/{uuid.uuid4()}",
        json={"display_name": "Forbidden"},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_delete_oauth_provider(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /settings/oauth-providers/{id} removes the provider."""
    slug = f"delete-provider-{uuid.uuid4().hex[:8]}"
    create_resp = await client.post(
        "/settings/oauth-providers/",
        json={
            "slug": slug,
            "display_name": "To Delete",
            "provider_type": "oidc",
            "client_id": "cid",
            "client_secret": "csec",
            "authorize_url": "https://example.com/authorize",
            "token_url": "https://example.com/token",
            "userinfo_url": "https://example.com/userinfo",
        },
        headers=admin_auth_header,
    )
    assert create_resp.status_code == 201
    provider_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/settings/oauth-providers/{provider_id}",
        headers=admin_auth_header,
    )
    assert resp.status_code == 204

    # Verify gone - list should not contain it
    list_resp = await client.get(
        "/settings/oauth-providers/",
        headers=admin_auth_header,
    )
    provider_ids = [p["id"] for p in list_resp.json()]
    assert provider_id not in provider_ids


@pytest.mark.anyio
async def test_delete_oauth_provider_not_found(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /settings/oauth-providers/{random_uuid} returns 404."""
    resp = await client.delete(
        f"/settings/oauth-providers/{uuid.uuid4()}",
        headers=admin_auth_header,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_oauth_provider_non_admin_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """DELETE /settings/oauth-providers/{id} as viewer returns 403."""
    resp = await client.delete(
        f"/settings/oauth-providers/{uuid.uuid4()}",
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Settings reset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reset_settings(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /settings/reset/ resets specified keys and returns updated settings."""
    resp = await client.post(
        "/settings/reset/",
        json={"keys": ["basemaps"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tabs" in data
    assert "env_only" in data


@pytest.mark.anyio
async def test_reset_settings_unknown_key(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /settings/reset/ with unknown key returns 400."""
    resp = await client.post(
        "/settings/reset/",
        json={"keys": ["nonexistent_key_xyz"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400
    assert "Unknown" in resp.json()["detail"]


@pytest.mark.anyio
async def test_reset_settings_non_admin_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """POST /settings/reset/ as viewer returns 403."""
    resp = await client.post(
        "/settings/reset/",
        json={"keys": ["basemaps"]},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_reset_settings_unauthenticated(client: AsyncClient):
    """POST /settings/reset/ without auth returns 401."""
    resp = await client.post(
        "/settings/reset/",
        json={"keys": ["basemaps"]},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Detect embedding dims
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_detect_embedding_dims_non_admin_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """POST /settings/detect-embedding-dims/ as viewer returns 403."""
    resp = await client.post(
        "/settings/detect-embedding-dims/",
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_detect_embedding_dims_unauthenticated(client: AsyncClient):
    """POST /settings/detect-embedding-dims/ without auth returns 401."""
    resp = await client.post("/settings/detect-embedding-dims/")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tile config (public)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_tile_config(client: AsyncClient):
    """GET /settings/tile-config/ returns tile config (public, no auth)."""
    resp = await client.get("/settings/tile-config/")
    assert resp.status_code == 200
    data = resp.json()
    assert "public_app_url" in data
    assert "public_api_url" in data
    assert "public_base_url" in data
