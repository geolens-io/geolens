"""Integration tests for the export endpoint.

These tests run against a real app but mock the export_dataset service
function (which calls ogr2ogr) to avoid needing actual PostGIS data tables.
The router layer is tested end-to-end: auth, visibility, validation, audit.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import os
import shutil
import tempfile
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record
from app.export.ogr import FORMAT_MAP


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
    geometry_type: str | None = "MultiPolygon",
    feature_count: int = 42,
    description: str | None = "A test dataset",
    column_info: list[dict] | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB."""
    if table_name is None:
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
    if column_info is None:
        column_info = [
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "pop", "type": "integer"},
        ]
    record = Record(
        title=name,
        summary=description,
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
        column_info=column_info,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Mock fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_export_service(monkeypatch):
    """Mock export_dataset in the router module.

    Creates a temp directory with a dummy file and patches the import
    so the router returns a FileResponse without calling ogr2ogr.
    The mock dynamically returns format-appropriate media types.
    """
    temp_dir = tempfile.mkdtemp(prefix="test_export_")

    async def _fake_export(
        table_name,
        dataset_name,
        format_key,
        *,
        target_srs=None,
        bbox=None,
        where=None,
        column_info=None,
    ):
        # Replicate the real format validation
        if format_key not in FORMAT_MAP:
            raise ValueError(f"Unsupported export format: {format_key}")

        fmt = FORMAT_MAP[format_key]
        ext = fmt["ext"]
        media = fmt["media"]

        if format_key == "shp":
            filename = f"{dataset_name}.zip"
            ext = ".zip"
        else:
            filename = f"{dataset_name}{ext}"

        file_path = os.path.join(temp_dir, filename)
        with open(file_path, "wb") as f:
            f.write(b"mock export data")

        return file_path, filename, media

    monkeypatch.setattr("app.export.router.export_dataset", _fake_export)

    yield _fake_export

    # Cleanup temp dir if it still exists (BackgroundTask may have removed it)
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestExportAuth:
    @pytest.mark.anyio
    async def test_export_requires_auth(self, client: AsyncClient):
        """GET /datasets/{uuid}/export without token returns 401."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/datasets/{fake_id}/export")
        assert resp.status_code == 401

    @pytest.mark.anyio
    async def test_export_dataset_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /datasets/{random_uuid}/export with admin token returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"/datasets/{fake_id}/export", headers=admin_auth_header
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Visibility tests
# ---------------------------------------------------------------------------


class TestExportVisibility:
    @pytest.mark.anyio
    async def test_export_private_dataset_hidden_from_viewer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Private dataset owned by admin: viewer gets 404, admin gets 200."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
            name="PrivateExportDS",
        )

        # Viewer cannot export
        resp = await client.get(f"/datasets/{ds.id}/export", headers=viewer_auth_header)
        assert resp.status_code == 404

        # Admin can export
        resp = await client.get(f"/datasets/{ds.id}/export", headers=admin_auth_header)
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_export_public_dataset_accessible(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """Public dataset: viewer can export (200)."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="PublicExportDS",
        )

        resp = await client.get(f"/datasets/{ds.id}/export", headers=viewer_auth_header)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestExportValidation:
    @pytest.mark.anyio
    async def test_export_invalid_format(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with format=xyz returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="FmtTestDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "xyz"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422  # FastAPI enum validation

    @pytest.mark.anyio
    async def test_export_invalid_bbox_too_few_values(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with bbox=1,2,3 returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="BboxTestDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"bbox": "1,2,3"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_export_invalid_bbox_bounds(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with bbox=10,10,5,5 (minx > maxx) returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="BboxBoundsDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"bbox": "10,10,5,5"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_export_invalid_target_crs(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with target_crs=invalid returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="CrsTestDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"target_crs": "invalid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400

    @pytest.mark.anyio
    async def test_export_non_spatial_dataset_spatial_format(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Non-spatial dataset with format=gpkg returns 400."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="NonSpatialDS",
            geometry_type=None,
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "gpkg"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "non-spatial" in resp.json()["detail"].lower()

    @pytest.mark.anyio
    async def test_export_non_spatial_dataset_csv_allowed(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Non-spatial dataset with format=csv returns 200."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="NonSpatialCsvDS",
            geometry_type=None,
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "csv"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Format tests
# ---------------------------------------------------------------------------


class TestExportFormats:
    @pytest.mark.anyio
    async def test_export_default_format_gpkg(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request without format param returns 200 with geopackage Content-Type."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="DefaultFmtDS"
        )
        resp = await client.get(f"/datasets/{ds.id}/export", headers=admin_auth_header)
        assert resp.status_code == 200
        assert "geopackage" in resp.headers["content-type"]

    @pytest.mark.anyio
    async def test_export_format_geojson(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with format=geojson returns 200."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="GeojsonDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert "geo+json" in resp.headers["content-type"]

    @pytest.mark.anyio
    async def test_export_format_shp(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with format=shp returns 200 with application/zip Content-Type."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id, name="ShpDS")
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "shp"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert "zip" in resp.headers["content-type"]

    @pytest.mark.anyio
    async def test_export_format_csv(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with format=csv returns 200 with text/csv Content-Type."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(test_db_session, created_by=admin_id, name="CsvDS")
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "csv"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Audit tests
# ---------------------------------------------------------------------------


class TestExportAudit:
    @pytest.mark.anyio
    async def test_export_creates_audit_log(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Export creates an audit log entry with action=dataset.export."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="AuditExportDS"
        )

        # Export the dataset
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "geojson"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

        # Query audit logs
        resp = await client.get(
            "/admin/audit-logs/",
            params={"action": "dataset.export"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

        # Find our specific dataset in the logs
        matching = [log for log in data["logs"] if log["resource_id"] == str(ds.id)]
        assert len(matching) >= 1
        log_entry = matching[0]
        assert log_entry["action"] == "dataset.export"
        assert log_entry["details"]["format"] == "geojson"


# ---------------------------------------------------------------------------
# Parameter pass-through tests
# ---------------------------------------------------------------------------


class TestExportParameters:
    @pytest.mark.anyio
    async def test_export_with_target_crs(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with target_crs=EPSG:3857 returns 200."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="CrsParamDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"target_crs": "EPSG:3857"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_export_with_bbox(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with valid bbox returns 200."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="BboxParamDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"bbox": "-74.1,40.6,-73.9,40.8"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_export_with_where(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with where=pop > 1000 returns 200."""
        admin_id = await _get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="WhereParamDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"where": "pop > 1000"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
