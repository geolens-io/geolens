"""Integration tests for layer creation API.

Tests cover: basic creation, columns, admin/editor/viewer RBAC,
invalid geometry types, invalid column names/types, searchability,
and all 6 geometry types.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _cleanup_layer(
    client: AsyncClient, headers: dict, dataset_id: str, title: str
):
    """Delete a created layer via the datasets API."""
    await client.request(
        "DELETE",
        f"/datasets/{dataset_id}",
        json={"confirm_title": title},
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Basic creation
# ---------------------------------------------------------------------------


class TestCreateLayerBasic:
    async def test_create_layer_basic(
        self, client: AsyncClient, editor_auth_header: dict, admin_auth_header: dict
    ):
        """POST /layers/ as editor creates an empty layer."""
        resp = await client.post(
            "/layers/",
            json={"title": "Test Points", "geometry_type": "Point"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["title"] == "Test Points"
        assert "table_name" in data
        assert data["geometry_type"] == "POINT"
        assert data["visibility"] == "private"
        assert data["feature_count"] == 0

        # Cleanup
        await _cleanup_layer(client, admin_auth_header, data["id"], data["title"])

    async def test_create_layer_with_columns(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /layers/ with columns creates attribute columns on the table."""
        resp = await client.post(
            "/layers/",
            json={
                "title": "Survey Layer",
                "geometry_type": "Polygon",
                "columns": [
                    {"name": "status", "type": "text"},
                    {"name": "area_sqm", "type": "real"},
                ],
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        # Verify columns exist on the dataset
        ds_resp = await client.get(
            f"/datasets/{data['id']}",
            headers=admin_auth_header,
        )
        assert ds_resp.status_code == 200
        ds_data = ds_resp.json()
        column_names = [c["name"] for c in (ds_data.get("column_info") or [])]
        assert "status" in column_names
        assert "area_sqm" in column_names

        # Cleanup
        await _cleanup_layer(client, admin_auth_header, data["id"], data["title"])

    async def test_create_layer_admin(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /layers/ as admin succeeds."""
        resp = await client.post(
            "/layers/",
            json={"title": "Admin Layer", "geometry_type": "LineString"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        # Cleanup
        await _cleanup_layer(client, admin_auth_header, data["id"], data["title"])


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------


class TestCreateLayerRBAC:
    async def test_create_layer_viewer_forbidden(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /layers/ as viewer returns 403."""
        resp = await client.post(
            "/layers/",
            json={"title": "Viewer Layer", "geometry_type": "Point"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_create_layer_no_auth(self, client: AsyncClient):
        """POST /layers/ without auth returns 401."""
        resp = await client.post(
            "/layers/",
            json={"title": "No Auth Layer", "geometry_type": "Point"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestCreateLayerValidation:
    async def test_create_layer_invalid_geometry_type(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /layers/ with invalid geometry type returns 422."""
        resp = await client.post(
            "/layers/",
            json={"title": "Bad Geom", "geometry_type": "Circle"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 422

    async def test_create_layer_invalid_column_name_reserved(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /layers/ with reserved column name returns 422."""
        resp = await client.post(
            "/layers/",
            json={
                "title": "Bad Col",
                "geometry_type": "Point",
                "columns": [{"name": "gid", "type": "text"}],
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 422

    async def test_create_layer_invalid_column_name_uppercase(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /layers/ with uppercase column name returns 422."""
        resp = await client.post(
            "/layers/",
            json={
                "title": "Bad Col Upper",
                "geometry_type": "Point",
                "columns": [{"name": "MyColumn", "type": "text"}],
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 422

    async def test_create_layer_invalid_column_type(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """POST /layers/ with disallowed column type returns 422."""
        resp = await client.post(
            "/layers/",
            json={
                "title": "Bad Type",
                "geometry_type": "Point",
                "columns": [{"name": "foo", "type": "jsonb"}],
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Searchability
# ---------------------------------------------------------------------------


class TestCreateLayerSearchable:
    async def test_create_layer_is_searchable(
        self, client: AsyncClient, editor_auth_header: dict, admin_auth_header: dict
    ):
        """Created layer appears in search results."""
        unique_name = f"Searchable Layer {uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/layers/",
            json={"title": unique_name, "geometry_type": "Point"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        # Search for the layer
        search_resp = await client.get(
            "/search/datasets",
            params={"q": unique_name},
            headers=editor_auth_header,
        )
        assert search_resp.status_code == 200
        search_data = search_resp.json()
        found_ids = [f["id"] for f in search_data.get("features", [])]
        assert data["id"] in found_ids

        # Cleanup
        await _cleanup_layer(client, admin_auth_header, data["id"], unique_name)


# ---------------------------------------------------------------------------
# All geometry types
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Column CRUD - Add Column
# ---------------------------------------------------------------------------


class TestAddColumn:
    async def _create_layer(self, client, headers):
        """Helper: create a layer and return its id + name."""
        resp = await client.post(
            "/layers/",
            json={
                "title": "Col Test Layer",
                "geometry_type": "Point",
                "columns": [{"name": "existing_col", "type": "text"}],
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        return data["id"], data["title"]

    # Column add/drop tests removed — those endpoints are now on the
    # datasets router at /datasets/{id}/columns/ (see test_datasets.py)


# ---------------------------------------------------------------------------
# All geometry types
# ---------------------------------------------------------------------------


class TestCreateLayerAllGeometryTypes:
    @pytest.mark.parametrize(
        "geometry_type",
        [
            "Point",
            "MultiPoint",
            "LineString",
            "MultiLineString",
            "Polygon",
            "MultiPolygon",
        ],
    )
    async def test_create_layer_geometry_type(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        admin_auth_header: dict,
        geometry_type: str,
    ):
        """Each valid geometry type creates a layer successfully."""
        name = f"Test {geometry_type} {uuid.uuid4().hex[:6]}"
        resp = await client.post(
            "/layers/",
            json={"title": name, "geometry_type": geometry_type},
            headers=editor_auth_header,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["geometry_type"] == geometry_type.upper()

        # Cleanup
        await _cleanup_layer(client, admin_auth_header, data["id"], name)
