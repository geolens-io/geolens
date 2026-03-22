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
