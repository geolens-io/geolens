"""Integration tests for admin user delete and embedding backfill endpoints.

Tests cover:
  - DELETE /admin/users/{id} — removes user, cascades API keys, self-delete guard,
    auth enforcement, 404 for missing user
  - POST /admin/backfill-embeddings/ — admin trigger with force, auth enforcement

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import _create_test_user


# ---------------------------------------------------------------------------
# DELETE /admin/users/{id}
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_user_removes_user(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} hard-deletes the user and returns 204."""
    # Create a user to delete
    _, user_id = await _create_test_user(client, admin_auth_header, "viewer")

    # Verify user exists
    resp = await client.get(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 200

    # Delete user
    resp = await client.delete(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 204

    # Verify user is gone
    resp = await client.get(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_user_cascades_api_keys(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} also removes the user's API keys."""
    # Create a user
    _, user_id = await _create_test_user(client, admin_auth_header, "editor")

    # Create an API key for this user
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": user_id, "name": "test-key"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201

    # Verify API key exists
    resp = await client.get(
        f"/admin/api-keys/?user_id={user_id}", headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # Delete user
    resp = await client.delete(f"/admin/users/{user_id}", headers=admin_auth_header)
    assert resp.status_code == 204

    # Verify API keys are gone
    resp = await client.get(
        f"/admin/api-keys/?user_id={user_id}", headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.anyio
async def test_delete_user_cannot_delete_self(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} returns 400 when admin tries to delete themselves."""
    # Get current admin user ID
    resp = await client.get("/auth/me/", headers=admin_auth_header)
    assert resp.status_code == 200
    admin_id = resp.json()["id"]

    # Try to self-delete
    resp = await client.delete(f"/admin/users/{admin_id}", headers=admin_auth_header)
    assert resp.status_code == 400
    assert "cannot delete" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_delete_user_forbidden_for_non_admin(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """DELETE /admin/users/{id} returns 403 for viewer role."""
    fake_id = str(uuid.uuid4())
    resp = await client.delete(f"/admin/users/{fake_id}", headers=viewer_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_delete_user_404_for_nonexistent(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /admin/users/{id} returns 404 for a non-existent user ID."""
    fake_id = str(uuid.uuid4())
    resp = await client.delete(f"/admin/users/{fake_id}", headers=admin_auth_header)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /admin/backfill-embeddings/
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_backfill_embeddings_force_admin(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /admin/backfill-embeddings/?force=true returns 200 for admin."""
    resp = await client.post(
        "/admin/backfill-embeddings/?force=true",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "processed" in data
    assert "created" in data
    assert "errors" in data


@pytest.mark.anyio
async def test_backfill_embeddings_forbidden_for_non_admin(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """POST /admin/backfill-embeddings/ returns 403 for non-admin."""
    resp = await client.post(
        "/admin/backfill-embeddings/?force=true",
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_backfill_embeddings_without_force(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /admin/backfill-embeddings/ (no force) returns 200 with counts."""
    resp = await client.post(
        "/admin/backfill-embeddings/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "processed" in data
    assert "created" in data
    assert "skipped" in data
    assert "errors" in data


# ---------------------------------------------------------------------------
# POST /admin/users/ — 409 conflict for duplicate username
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_user_duplicate_username_returns_409(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """Creating a user with an existing username returns 409."""
    # First creation should succeed
    username = f"dup_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": "testpass123", "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201

    # Duplicate should return 409
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": "otherpass456", "role": "viewer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 409
    assert "already" in resp.json()["detail"].lower() or "exists" in resp.json()["detail"].lower()
