"""Tests for API key authentication and admin CRUD endpoints.

Verifies that:
- Admin can create, list, and revoke API keys
- API keys authenticate to both required-auth and optional-auth endpoints
- Invalid/revoked keys are properly handled
- API keys inherit user roles/permissions
"""

import uuid

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import _create_test_user, get_auth_header

ADMIN_USER = settings.geolens_admin_username
ADMIN_PASS = settings.geolens_admin_password.get_secret_value()


@pytest.mark.anyio
async def test_create_api_key(client: AsyncClient):
    """Admin creates API key for themselves. Assert 201, response has key/id/name."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Get admin user id
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Test Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "key" in data
    assert "id" in data
    assert data["name"] == "Test Key"
    assert len(data["key"]) > 20  # token_urlsafe(32) produces ~43 chars


@pytest.mark.anyio
async def test_api_key_authenticates_to_search(client: AsyncClient):
    """Create API key, use raw key in X-Api-Key header to call GET /search/datasets."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    # Create API key
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Search Key"},
        headers=admin_headers,
    )
    raw_key = resp.json()["key"]

    # Use API key to access authenticated endpoint
    search_resp = await client.get(
        "/search/datasets/",
        headers={"X-Api-Key": raw_key},
    )
    assert search_resp.status_code == 200


@pytest.mark.anyio
async def test_api_key_authenticates_to_collection_items(client: AsyncClient):
    """Use API key to call GET /collections/datasets/items. Assert 200."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Collection Key"},
        headers=admin_headers,
    )
    raw_key = resp.json()["key"]

    items_resp = await client.get(
        "/collections/datasets/items",
        headers={"X-Api-Key": raw_key},
    )
    assert items_resp.status_code == 200


@pytest.mark.anyio
async def test_invalid_api_key_returns_401(client: AsyncClient):
    """Call GET /auth/me/ with invalid X-Api-Key. Assert 401."""
    resp = await client.get(
        "/auth/me/",
        headers={"X-Api-Key": "invalid-key-value"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_revoked_api_key_returns_401(client: AsyncClient):
    """Create key, revoke via DELETE, then try to use it. Assert 401."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)
    me_resp = await client.get("/auth/me/", headers=admin_headers)
    admin_id = me_resp.json()["id"]

    # Create key
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Revoke Me"},
        headers=admin_headers,
    )
    data = resp.json()
    raw_key = data["key"]
    key_id = data["id"]

    # Revoke it
    del_resp = await client.delete(
        f"/admin/api-keys/{key_id}",
        headers=admin_headers,
    )
    assert del_resp.status_code == 204

    # Try using revoked key on authenticated endpoint
    search_resp = await client.get(
        "/auth/me/",
        headers={"X-Api-Key": raw_key},
    )
    assert search_resp.status_code == 401


@pytest.mark.anyio
async def test_invalid_api_key_falls_back_to_anonymous_on_optional_auth(
    client: AsyncClient,
):
    """Call GET /collections/datasets/items with invalid X-Api-Key (no JWT).

    Should return 200 (anonymous fallback, sees public datasets).
    """
    resp = await client.get(
        "/collections/datasets/items",
        headers={"X-Api-Key": "invalid-key-value"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_list_api_keys(client: AsyncClient):
    """Admin creates 2 keys, lists them. Assert both returned and raw key is NOT present."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a unique user to isolate key listing
    viewer_headers, viewer_id = await _create_test_user(client, admin_headers, "viewer")

    # Create 2 keys for that user
    key_names = set()
    for i in range(2):
        name = f"list-test-key-{uuid.uuid4().hex[:6]}"
        key_names.add(name)
        await client.post(
            "/admin/api-keys/",
            json={"user_id": viewer_id, "name": name},
            headers=admin_headers,
        )

    # List keys filtered by user
    list_resp = await client.get(
        f"/admin/api-keys/?user_id={viewer_id}",
        headers=admin_headers,
    )
    assert list_resp.status_code == 200
    data = list_resp.json()
    items = data["items"]
    assert "total" in data
    assert len(items) >= 2

    # Verify raw key is never in list response
    returned_names = set()
    for item in items:
        assert "key" not in item  # raw key must NOT be returned
        returned_names.add(item["name"])

    assert key_names.issubset(returned_names)


@pytest.mark.anyio
async def test_api_key_inherits_user_roles(client: AsyncClient):
    """Create a viewer user, create API key for viewer. Use API key to access endpoint."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a viewer user
    viewer_headers, viewer_id = await _create_test_user(client, admin_headers, "viewer")

    # Create API key for the viewer
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": viewer_id, "name": "Viewer API Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["key"]

    # Viewer can access search (requires authentication, viewer has access)
    search_resp = await client.get(
        "/search/datasets/",
        headers={"X-Api-Key": raw_key},
    )
    assert search_resp.status_code == 200

    # Viewer cannot access admin endpoints (requires admin role)
    admin_resp = await client.get(
        "/admin/users/",
        headers={"X-Api-Key": raw_key},
    )
    assert admin_resp.status_code == 403


# ---------------------------------------------------------------------------
# Self-service API key CRUD tests (/auth/api-keys/)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_self_service_list_api_keys(client: AsyncClient):
    """Authenticated user can list their own API keys via GET /auth/api-keys/."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    resp = await client.get("/auth/api-keys/", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)


@pytest.mark.anyio
async def test_self_service_create_api_key(client: AsyncClient):
    """Authenticated user can create an API key via POST /auth/api-keys/."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Self-Service Key"},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert "key" in data
    assert data["name"] == "Self-Service Key"
    assert len(data["key"]) > 20


@pytest.mark.anyio
async def test_self_service_delete_own_api_key(client: AsyncClient):
    """Authenticated user can delete their own API key via DELETE /auth/api-keys/{id}."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a key
    create_resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Delete Me Self"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    key_id = create_resp.json()["id"]

    # Delete it
    del_resp = await client.delete(
        f"/auth/api-keys/{key_id}",
        headers=admin_headers,
    )
    assert del_resp.status_code == 204


@pytest.mark.anyio
async def test_self_service_list_api_keys_unauthenticated(client: AsyncClient):
    """GET /auth/api-keys/ without authentication returns 401."""
    resp = await client.get("/auth/api-keys/")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_self_service_cannot_delete_another_users_key(client: AsyncClient):
    """User cannot delete another user's API key (returns 404)."""
    admin_headers = await get_auth_header(client, ADMIN_USER, ADMIN_PASS)

    # Create a second user
    viewer_headers, viewer_id = await _create_test_user(client, admin_headers, "viewer")

    # Admin creates a key for themselves via self-service
    create_resp = await client.post(
        "/auth/api-keys/",
        json={"name": "Admin Only Key"},
        headers=admin_headers,
    )
    assert create_resp.status_code == 201
    admin_key_id = create_resp.json()["id"]

    # Viewer tries to delete admin's key
    del_resp = await client.delete(
        f"/auth/api-keys/{admin_key_id}",
        headers=viewer_headers,
    )
    # The endpoint filters by current_user.id, so another user's key is "not found"
    assert del_resp.status_code == 404
