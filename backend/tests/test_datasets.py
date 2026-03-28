"""Integration tests for dataset CRUD and visibility endpoints.

These tests run against a real database via httpx ASGITransport. Dataset
records are inserted directly into the DB to test endpoint behavior
without going through the full ingest flow.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record
from app.maps.models import Map, MapLayer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    """Look up a user's ID by username."""
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Test Dataset",
    table_name: str | None = None,
    visibility: str = "public",
    srid: int = 4326,
    geometry_type: str = "MultiPolygon",
    feature_count: int = 42,
    description: str | None = "A test dataset",
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB."""
    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description,
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=feature_count,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# List datasets tests
# ---------------------------------------------------------------------------


class TestListDatasets:
    async def test_list_datasets_requires_auth(self, client: AsyncClient):
        """GET /datasets/ without token returns 401."""
        resp = await client.get("/datasets/")
        assert resp.status_code == 401

    async def test_list_datasets_empty(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/ returns a list (may be empty) with total field."""
        resp = await client.get("/datasets/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "datasets" in data
        assert "total" in data
        assert isinstance(data["datasets"], list)

    async def test_list_datasets_visibility_public(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Public dataset is visible to both admin and viewer."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Public DS",
        )

        # Admin can see it
        resp = await client.get("/datasets/", headers=admin_auth_header)
        assert resp.status_code == 200
        admin_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) in admin_ids

        # Viewer can see it
        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        viewer_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) in viewer_ids

    async def test_list_datasets_visibility_private(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Private dataset owned by admin is hidden from viewer."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="Private DS",
        )

        # Admin can see it
        resp = await client.get("/datasets/", headers=admin_auth_header)
        assert resp.status_code == 200
        admin_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) in admin_ids

        # Viewer cannot see it
        resp = await client.get("/datasets/", headers=viewer_auth_header)
        assert resp.status_code == 200
        viewer_ids = [d["id"] for d in resp.json()["datasets"]]
        assert str(ds.id) not in viewer_ids


# ---------------------------------------------------------------------------
# Get single dataset tests
# ---------------------------------------------------------------------------


class TestGetDataset:
    async def test_get_dataset_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/{id} for nonexistent ID returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/datasets/{fake_id}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_get_dataset_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GET /datasets/{id} returns correct fields for an existing dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Get Test DS",
            srid=4326,
            geometry_type="Point",
            feature_count=10,
        )

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(ds.id)
        assert data["title"] == "Get Test DS"
        assert data["srid"] == 4326
        assert data["geometry_type"] == "Point"
        assert data["feature_count"] == 10
        assert data["visibility"] == "public"


# ---------------------------------------------------------------------------
# Update metadata tests
# ---------------------------------------------------------------------------


class TestUpdateMetadata:
    async def test_update_metadata_requires_editor(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} with viewer token returns 403."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Viewer Patch Test",
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"title": "Should Not Change"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_update_metadata_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} updates user-editable fields, preserves auto-extracted."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Original Name",
            description="Original description",
            srid=4326,
            geometry_type="MultiPolygon",
            feature_count=42,
        )

        # Patch title and summary
        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={
                "title": "Updated Name",
                "summary": "Updated description",
                "theme_category": ["updated", "test"],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()

        # User-editable fields updated
        assert data["title"] == "Updated Name"
        assert data["summary"] == "Updated description"
        assert data["theme_category"] == ["updated", "test"]

        # Auto-extracted fields preserved
        assert data["srid"] == 4326
        assert data["geometry_type"] == "MultiPolygon"
        assert data["feature_count"] == 42

    async def test_restrict_dataset_blocked_when_used_in_public_map(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} with visibility=restricted returns 422 when used in a public map."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Public In Map DS",
        )

        # Create a public map with this dataset as a layer
        map_obj = Map(
            name="Public Map With DS",
            visibility="public",
            created_by=admin_id,
        )
        test_db_session.add(map_obj)
        await test_db_session.flush()

        layer = MapLayer(
            map_id=map_obj.id,
            dataset_id=ds.id,
            sort_order=0,
        )
        test_db_session.add(layer)
        await test_db_session.commit()

        # Attempt to restrict dataset visibility
        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "restricted"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "Public Map With DS" in resp.json()["detail"]

    async def test_restrict_dataset_allowed_when_no_public_maps(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """PATCH /datasets/{id} with visibility=restricted succeeds when not in any public map."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Unreferenced DS",
        )

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"visibility": "restricted"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "restricted"


# ---------------------------------------------------------------------------
# Anonymous access tests
# ---------------------------------------------------------------------------


class TestAnonymousAccess:
    """Verify anonymous (no auth) users can access public resources."""

    async def test_anon_get_public_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id} returns 200 for public+published dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Public DS",
        )
        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Anon Public DS"

    async def test_anon_get_private_dataset_returns_404(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id} returns 404 for private dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="Anon Private DS",
        )
        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 404

    async def test_anon_search_returns_public_only(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /search/datasets returns only public+published datasets."""
        admin_id = await _get_user_id(test_db_session, "admin")
        pub = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Search Public",
        )
        priv = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="Search Private",
        )
        resp = await client.get("/search/datasets/")
        assert resp.status_code == 200
        ids = [f["id"] for f in resp.json()["features"]]
        assert str(pub.id) in ids
        assert str(priv.id) not in ids

    async def test_anon_search_facets(self, client: AsyncClient):
        """Anonymous GET /search/facets returns 200."""
        resp = await client.get("/search/facets/")
        assert resp.status_code == 200

    async def test_anon_get_dataset_rows_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/rows returns 200 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Rows DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/rows")
        # 200 or 404 (no data table), but NOT 401
        assert resp.status_code != 401

    async def test_anon_get_restricted_dataset_returns_404(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id} returns 404 for restricted dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="restricted",
            name="Anon Restricted DS",
        )
        resp = await client.get(f"/datasets/{ds.id}")
        assert resp.status_code == 404

    async def test_anon_get_attributes_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/attributes/ returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Attrs DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/attributes/")
        assert resp.status_code != 401

    async def test_anon_get_validate_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/validate/ returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Validate DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/validate/")
        assert resp.status_code != 401

    async def test_anon_get_versions_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/versions returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon Versions DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/versions")
        assert resp.status_code != 401

    async def test_anon_get_history_public(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous GET /datasets/{id}/history returns non-401 for public dataset."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="Anon History DS",
        )
        resp = await client.get(f"/datasets/{ds.id}/history")
        assert resp.status_code != 401

    async def test_anon_collections_list(self, client: AsyncClient):
        """Anonymous GET /catalog/collections/ returns 200."""
        resp = await client.get("/catalog/collections/")
        assert resp.status_code == 200

    async def test_anon_protected_routes_return_401(self, client: AsyncClient):
        """Anonymous access to protected endpoints returns 401."""
        # Settings (admin-only)
        resp = await client.get("/settings/all/")
        assert resp.status_code == 401

        # Import (editor-only)
        resp = await client.post("/ingest/upload/")
        assert resp.status_code in (401, 422)  # 422 if missing body, but auth checked first

        # Admin users
        resp = await client.get("/admin/users/")
        assert resp.status_code == 401


class TestDatasetSubRouterRouting:
    """Verify all dataset sub-router paths resolve (not 404 from route registration)."""

    async def test_dcat_catalog_not_captured_by_dataset_id(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/dcat/ resolves to DCAT catalog, not /{dataset_id} with 'dcat'."""
        resp = await client.get("/datasets/dcat/", headers=admin_auth_header)
        # Should be 200 (DCAT catalog), not 422 (invalid UUID) or 404
        assert resp.status_code == 200

    async def test_subrouter_paths_resolve(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Sub-router paths return valid responses (not 404 from missing registration)."""
        fake_id = str(uuid.uuid4())
        routes = [
            ("GET", f"/datasets/{fake_id}/versions"),
            ("GET", f"/datasets/{fake_id}/rows"),
            ("GET", f"/datasets/{fake_id}/validate/"),
            ("GET", f"/datasets/{fake_id}/related/"),
            ("GET", f"/datasets/{fake_id}/maps/"),
            ("GET", f"/datasets/{fake_id}/vrt-sources/"),
            ("GET", f"/datasets/{fake_id}/attributes/"),
        ]
        for method, path in routes:
            resp = await client.request(method, path, headers=admin_auth_header)
            # 404 with "not found" detail = dataset doesn't exist (route resolved correctly)
            # 404 without detail = route not registered (would be a regression)
            assert resp.status_code in (200, 404), f"{method} {path} returned {resp.status_code}"
            if resp.status_code == 404:
                assert "not found" in resp.json().get("detail", "").lower(), (
                    f"{method} {path}: 404 but no 'not found' detail — route may not be registered"
                )
