"""Integration tests for saved searches (SRCH-08): CRUD with ownership enforcement.

Tests verify: create, list, load, delete, cross-user isolation, and
unauthenticated access rejection for the /search/saved endpoints.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (saved_searches table)
"""

import pytest
from httpx import AsyncClient

from tests.conftest import _create_test_user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_saved_search(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """POST /search/saved creates a saved search and returns it."""
    resp = await client.post(
        "/search/saved/",
        json={
            "name": "My Search",
            "params": {"q": "rivers", "geometry_type": "LineString"},
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["name"] == "My Search"
    assert data["params"]["q"] == "rivers"
    assert data["params"]["geometry_type"] == "LineString"


@pytest.mark.anyio
async def test_list_saved_searches(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /search/saved returns all saved searches for the user, newest first."""
    # Create two saved searches
    await client.post(
        "/search/saved/",
        json={"name": "First Search", "params": {"q": "parks"}},
        headers=admin_auth_header,
    )
    resp2 = await client.post(
        "/search/saved/",
        json={"name": "Second Search", "params": {"q": "lakes"}},
        headers=admin_auth_header,
    )
    assert resp2.status_code == 201

    resp = await client.get("/search/saved/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    names = [s["name"] for s in data["searches"]]
    assert "First Search" in names
    assert "Second Search" in names

    # Verify ordered by updated_at desc (newest first)
    timestamps = [s["updated_at"] for s in data["searches"]]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.anyio
async def test_load_saved_search(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /search/saved/{id} returns the saved search with correct params."""
    create_resp = await client.post(
        "/search/saved/",
        json={"name": "Load Test", "params": {"q": "bridges", "srid": 4326}},
        headers=admin_auth_header,
    )
    assert create_resp.status_code == 201
    search_id = create_resp.json()["id"]

    resp = await client.get(
        f"/search/saved/{search_id}",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == search_id
    assert data["name"] == "Load Test"
    assert data["params"]["q"] == "bridges"
    assert data["params"]["srid"] == 4326


@pytest.mark.anyio
async def test_delete_saved_search(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """DELETE /search/saved/{id} removes the search, and it no longer appears in list."""
    create_resp = await client.post(
        "/search/saved/",
        json={"name": "To Delete", "params": {"q": "temp"}},
        headers=admin_auth_header,
    )
    assert create_resp.status_code == 201
    search_id = create_resp.json()["id"]

    # Delete it
    del_resp = await client.delete(
        f"/search/saved/{search_id}",
        headers=admin_auth_header,
    )
    assert del_resp.status_code == 204

    # Verify it is gone
    get_resp = await client.get(
        f"/search/saved/{search_id}",
        headers=admin_auth_header,
    )
    assert get_resp.status_code == 404


@pytest.mark.anyio
async def test_cannot_access_other_users_saved_search(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """User B cannot GET or DELETE a saved search owned by User A."""
    # Create a saved search as admin (User A)
    create_resp = await client.post(
        "/search/saved/",
        json={"name": "Admin Only", "params": {"q": "secret"}},
        headers=admin_auth_header,
    )
    assert create_resp.status_code == 201
    search_id = create_resp.json()["id"]

    # Create User B (editor)
    editor_headers, _ = await _create_test_user(client, admin_auth_header, "editor")

    # User B cannot GET it
    get_resp = await client.get(
        f"/search/saved/{search_id}",
        headers=editor_headers,
    )
    assert get_resp.status_code == 404

    # User B cannot DELETE it
    del_resp = await client.delete(
        f"/search/saved/{search_id}",
        headers=editor_headers,
    )
    assert del_resp.status_code == 404


@pytest.mark.anyio
async def test_create_saved_search_unauthenticated(
    client: AsyncClient,
):
    """POST /search/saved without auth returns 401."""
    resp = await client.post(
        "/search/saved/",
        json={"name": "No Auth", "params": {"q": "test"}},
    )
    assert resp.status_code == 401
