"""Integration tests for admin catalog statistics endpoint.

Tests cover: stat field types and values (total_datasets, recent_additions,
total_storage_bytes, datasets_by_geometry_type, datasets_by_visibility),
and authorization enforcement.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

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
    resp = await client.get("/admin/stats/", headers=admin_auth_header)
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
    resp = await client.get("/admin/stats/", headers=admin_auth_header)
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
    """A migrated healthy deployment returns an exact integer storage total."""
    resp = await client.get("/admin/stats/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "total_storage_bytes" in data
    assert isinstance(data["total_storage_bytes"], int)


@pytest.mark.anyio
async def test_hosted_storage_query_separates_catalog_and_tenant_data_roles(
    monkeypatch,
):
    """Catalog discovery and physical size lookup must be separate statements."""
    import app.core.tenancy as tenancy
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.modules.admin.service import _get_total_storage_bytes
    from app.modules.catalog.datasets.domain.models import Dataset

    tenant_id = str(uuid.uuid4())
    monkeypatch.setattr(tenancy, "is_multi_tenant", lambda: True)
    expected_schema = tenant_data_schema(tenant_id)

    catalog_result = MagicMock()
    catalog_result.scalars.return_value.all.return_value = ["roads"]
    storage_result = MagicMock()
    storage_result.scalar_one.return_value = 4096

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[catalog_result, storage_result])
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=nested)
    nested.__aexit__ = AsyncMock(return_value=False)
    db.begin_nested.return_value = nested

    token = current_tenant_var.set(tenant_id)
    try:
        total = await _get_total_storage_bytes(db, Dataset)
    finally:
        current_tenant_var.reset(token)

    assert total == 4096
    assert db.execute.await_count == 2
    catalog_statement = db.execute.await_args_list[0].args[0]
    storage_statement = db.execute.await_args_list[1].args[0]
    catalog_sql = str(catalog_statement)
    storage_sql = str(storage_statement)
    assert "catalog.datasets" in catalog_sql
    assert expected_schema not in catalog_sql
    assert "catalog.datasets" not in storage_sql
    assert "unnest" in storage_sql
    assert storage_statement.compile().params == {
        "schema": expected_schema,
        "table_names": ["roads"],
    }


@pytest.mark.anyio
async def test_stats_returns_geometry_breakdown(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """datasets_by_geometry_type is a dict."""
    resp = await client.get("/admin/stats/", headers=admin_auth_header)
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
    resp = await client.get("/admin/stats/", headers=admin_auth_header)
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
    resp = await client.get("/admin/stats/", headers=viewer_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_stats_unauthenticated_returns_401(
    client: AsyncClient,
):
    """Unauthenticated request to stats returns 401."""
    resp = await client.get("/admin/stats/")
    assert resp.status_code == 401
