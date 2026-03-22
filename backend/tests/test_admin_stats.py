"""Integration tests for admin catalog statistics endpoint.

Tests cover: stat field types and values (total_datasets, recent_additions,
total_storage_bytes, datasets_by_geometry_type, datasets_by_visibility),
and authorization enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Stats content tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stats_returns_total_datasets(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /admin/stats returns total_datasets as a non-negative integer."""
    resp = await client.get("/admin/stats", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_datasets" in data
    assert isinstance(data["total_datasets"], int)
    assert data["total_datasets"] >= 0


@pytest.mark.anyio
async def test_stats_returns_recent_additions(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """recent_additions is <= total_datasets."""
    resp = await client.get("/admin/stats", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "recent_additions" in data
    assert isinstance(data["recent_additions"], int)
    assert data["recent_additions"] <= data["total_datasets"]


@pytest.mark.anyio
async def test_stats_returns_storage(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """total_storage_bytes is an integer or None."""
    resp = await client.get("/admin/stats", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_storage_bytes" in data
    assert data["total_storage_bytes"] is None or isinstance(
        data["total_storage_bytes"], int
    )


@pytest.mark.anyio
async def test_stats_returns_geometry_breakdown(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """datasets_by_geometry_type is a dict."""
    resp = await client.get("/admin/stats", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "datasets_by_geometry_type" in data
    assert isinstance(data["datasets_by_geometry_type"], dict)


@pytest.mark.anyio
async def test_stats_returns_visibility_breakdown(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """datasets_by_visibility is a dict."""
    resp = await client.get("/admin/stats", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "datasets_by_visibility" in data
    assert isinstance(data["datasets_by_visibility"], dict)


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stats_viewer_forbidden(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """Viewer cannot access stats (403)."""
    resp = await client.get("/admin/stats", headers=viewer_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_stats_unauthenticated_returns_401(
    client: AsyncClient,
):
    """Unauthenticated request to stats returns 401."""
    resp = await client.get("/admin/stats")
    assert resp.status_code == 401
