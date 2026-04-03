"""Integration tests for re-upload API endpoints and schema diff service.

Tests cover: upload creates job, preview returns schema diff, commit queues task,
dataset identity preserved, versions endpoint, RBAC, 404/400 error cases,
current_version in response, and schema diff computation.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.datasets.models import Dataset, Record
from app.datasets.service import compute_schema_diff
from app.jobs.models import IngestJob
from app.services.security import SSRFError

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Reupload Test Dataset",
    visibility: str = "public",
) -> Dataset:
    """Insert a Record + Dataset pair directly into the DB."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="original.geojson",
        column_info=[
            {"name": "name", "type": "String"},
            {"name": "value", "type": "Integer"},
        ],
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Module-scoped mocks for file I/O and task deferral
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_reupload_task():
    """Prevent procrastinate task deferral in reupload tests."""
    with patch("app.datasets.router_reupload.reupload_file") as mock_task:
        # Default queue path
        mock_task.defer_async = AsyncMock(return_value=None)
        # Priority queue path (reupload_file.configure(...).defer_async(...))
        mock_task.configure.return_value.defer_async = AsyncMock(return_value=None)
        yield mock_task


@pytest.fixture(autouse=True)
def mock_reupload_file_save():
    """Mock file-save helper while still writing a real temp file for validation."""

    async def _fake_save(file, job_id: str) -> Path:
        staging_dir = Path("/tmp/fake_staging")
        staging_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "").suffix or ".bin"
        out_path = staging_dir / f"{job_id}{suffix}"

        content = await file.read()
        if not content:
            if suffix in {".geojson", ".json"}:
                content = b'{"type":"FeatureCollection","features":[]}'
            elif suffix == ".csv":
                content = b"id,name\n1,test\n"
            else:
                content = b"test"
        out_path.write_bytes(content)
        await file.seek(0)
        return out_path

    with patch(
        "app.datasets.router_reupload.save_upload_file", new_callable=AsyncMock
    ) as mock_save:
        mock_save.side_effect = _fake_save
        yield mock_save


@pytest.fixture(autouse=True)
def mock_ogrinfo_preview():
    """Mock ogrinfo preview to return predictable data."""
    with patch(
        "app.datasets.router_reupload.run_ogrinfo_preview", new_callable=AsyncMock
    ) as mock_preview:
        mock_preview.return_value = {
            "srid": 4326,
            "geometry_type": "Point",
            "layer_name": "test",
            "feature_count": 200,
            "columns": [
                {"name": "name", "type": "String"},
                {"name": "value", "type": "Real"},
                {"name": "new_col", "type": "String"},
            ],
            "sample_rows": [
                {"name": "Test", "value": 3.14, "new_col": "hello"},
            ],
        }
        yield mock_preview


# ---------------------------------------------------------------------------
# SC1: Upload creates job
# ---------------------------------------------------------------------------


class TestReuploadUpload:
    async def test_reupload_upload_creates_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /datasets/{id}/reupload returns 201 with job_id."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "update.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"
        assert data["message"] == "File uploaded for re-upload preview"

    async def test_reupload_invalid_dataset_returns_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ):
        """POST /datasets/{random_uuid}/reupload returns 404."""
        resp = await client.post(
            f"/datasets/{uuid.uuid4()}/reupload",
            files={
                "file": (
                    "update.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_reupload_invalid_file_extension_returns_400(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """POST /datasets/{id}/reupload with a .txt file returns 400."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={"file": ("data.txt", b"some text content", "text/plain")},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"].lower()

    async def test_reupload_requires_admin_or_editor(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Viewer role gets 403 on POST /datasets/{id}/reupload."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "update.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# SC3: Preview returns schema diff
# ---------------------------------------------------------------------------


class TestReuploadPreview:
    async def test_reupload_preview_returns_schema_diff(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Upload file then POST preview returns schema_diff with diff fields."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        # Upload
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "update.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # Preview
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/preview",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "columns" in data
        assert "crs" in data
        assert "feature_count" in data
        assert "schema_diff" in data

        diff = data["schema_diff"]
        assert "columns_added" in diff
        assert "columns_removed" in diff
        assert "type_changes" in diff
        assert "row_count_delta" in diff

        # Our mock returns: new has "new_col" (added), old has "value" as Integer but new is Real (type change)
        added_names = [c["name"] for c in diff["columns_added"]]
        assert "new_col" in added_names

        type_change_names = [c["name"] for c in diff["type_changes"]]
        assert "value" in type_change_names


# ---------------------------------------------------------------------------
# Service re-upload preview parity + safety
# ---------------------------------------------------------------------------


class TestServiceReuploadPreview:
    async def test_service_reupload_preview_returns_parity_response_and_dataset_bound_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        with (
            patch(
                "app.datasets.router_reupload.build_gdal_source"
            ) as mock_build_source,
            patch(
                "app.datasets.router_reupload.run_service_preview",
                new_callable=AsyncMock,
            ) as mock_run_preview,
        ):
            mock_build_source.return_value = ("WFS:https://example.com/wfs", "roads")
            mock_run_preview.return_value = {
                "srid": 4326,
                "geometry_type": "Point",
                "layer_name": "roads",
                "feature_count": 120,
                "columns": [
                    {"name": "name", "type": "String"},
                    {"name": "value", "type": "Real"},
                    {"name": "new_col", "type": "String"},
                ],
                "sample_rows": [{"name": "Main St", "value": 1.5, "new_col": "A"}],
            }

            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json={
                    "url": "https://example.com/wfs",
                    "service_type": "WFS 2.0.0",
                    "layer_name": "roads",
                    "layer_title": "Roads Layer",
                    "layer_id": None,
                    "token": "secret-token",
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "schema_diff" in data
        assert "columns" in data
        assert "feature_count" in data
        assert "sample_rows" in data
        assert "layer_name" in data
        assert data["source_filename"] == "Roads Layer"
        assert data["layer_name"] == "roads"
        assert data["feature_count"] == 120

        diff = data["schema_diff"]
        assert "columns_added" in diff
        assert "columns_removed" in diff
        assert "type_changes" in diff
        assert "row_count_old" in diff
        assert "row_count_new" in diff
        assert "row_count_delta" in diff
        assert any(col["name"] == "new_col" for col in diff["columns_added"])
        assert any(change["name"] == "value" for change in diff["type_changes"])

        mock_build_source.assert_called_once_with(
            "WFS 2.0.0",
            "https://example.com/wfs",
            "roads",
            None,
            token="secret-token",
            order_field=None,
            result_limit=5,
        )
        mock_run_preview.assert_awaited_once_with(
            "WFS:https://example.com/wfs",
            "roads",
            token="secret-token",
        )

        job_id = uuid.UUID(data["job_id"])
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == job_id)
        )
        job = result.scalar_one()

        assert job.dataset_id == dataset.id
        assert job.source_url == "https://example.com/wfs"
        assert job.source_layer == "roads"
        assert job.source_filename == "Roads Layer"
        assert job.user_metadata["reupload"] is True
        assert job.user_metadata["dataset_id"] == str(dataset.id)
        assert job.user_metadata["service_type"] == "WFS 2.0.0"
        assert job.user_metadata["source_type"] == "service_url"
        assert "token" not in job.user_metadata
        assert "secret-token" not in str(job.user_metadata)

    async def test_service_reupload_preview_ssrf_blocked_returns_400_without_remote_calls(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)
        blocked_url = "http://127.0.0.1/internal"

        with (
            patch(
                "app.datasets.router_reupload.validate_url_for_ssrf",
                side_effect=SSRFError(
                    "URLs targeting private/internal networks are not allowed"
                ),
            ) as mock_ssrf,
            patch(
                "app.datasets.router_reupload.build_gdal_source"
            ) as mock_build_source,
            patch(
                "app.datasets.router_reupload.run_service_preview",
                new_callable=AsyncMock,
            ) as mock_run_preview,
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/service/preview",
                json={
                    "url": blocked_url,
                    "service_type": "WFS 2.0.0",
                    "layer_name": "roads",
                    "layer_title": "Roads Layer",
                    "token": "secret-token",
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"].lower()
        mock_ssrf.assert_called_once_with(blocked_url)
        mock_build_source.assert_not_called()
        mock_run_preview.assert_not_awaited()

        result = await test_db_session.execute(
            select(IngestJob).where(
                IngestJob.dataset_id == dataset.id,
                IngestJob.source_url == blocked_url,
            )
        )
        assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# SC2: Commit queues task
# ---------------------------------------------------------------------------


class TestReuploadCommit:
    async def test_reupload_commit_queues_task(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_reupload_task,
    ):
        """Upload file then POST commit returns 'Re-upload queued'."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        # Upload
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "update.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # Commit
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/commit",
            json={},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert data["message"] == "Re-upload queued"

        # Verify task was deferred via priority queue for small files
        mock_reupload_task.configure.assert_called_once_with(queue="priority")
        mock_reupload_task.configure.return_value.defer_async.assert_called_once()
        call_kwargs = mock_reupload_task.configure.return_value.defer_async.call_args
        assert call_kwargs.kwargs["dataset_id"] == str(dataset.id)
        assert call_kwargs.kwargs["job_id"] == job_id


# ---------------------------------------------------------------------------
# SC1: Dataset identity preserved (endpoint-level test)
# ---------------------------------------------------------------------------


class TestReuploadPreservesIdentity:
    async def test_reupload_preserves_dataset_identity(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """Full flow: upload, commit. Verify dataset ID/table_name/name are unchanged."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Identity Preservation Test",
        )
        original_id = str(dataset.id)
        original_table_name = dataset.table_name
        original_name = dataset.record.title
        original_description = dataset.record.summary

        # Upload
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload",
            files={
                "file": (
                    "new_data.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        job_id = resp.json()["job_id"]

        # Commit (task is mocked, so no actual swap happens)
        resp = await client.post(
            f"/datasets/{dataset.id}/reupload/{job_id}/commit",
            json={},
            headers=admin_auth_header,
        )
        assert resp.status_code == 202

        # Verify dataset identity unchanged via GET endpoint
        resp = await client.get(
            f"/datasets/{original_id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == original_id
        assert data["table_name"] == original_table_name
        assert data["title"] == original_name
        assert data["summary"] == original_description


# ---------------------------------------------------------------------------
# SC4: Versions endpoint
# ---------------------------------------------------------------------------


class TestVersionsEndpoint:
    async def test_versions_endpoint_returns_history(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """After inserting a version record, GET /datasets/{id}/versions returns it."""
        from app.collections.models import DatasetVersion

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        # Manually insert a version record
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=1,
            source_filename="original.geojson",
            source_format="geojson",
            feature_count=100,
            srid=4326,
            geometry_type="MultiPolygon",
            file_hash="abc123",
            uploaded_by=admin_id,
        )
        test_db_session.add(version)
        await test_db_session.commit()

        resp = await client.get(
            f"/datasets/{dataset.id}/versions/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "versions" in data
        assert "total" in data
        assert data["total"] >= 1

        v = data["versions"][0]
        assert v["version_number"] == 1
        assert v["source_filename"] == "original.geojson"
        assert v["feature_count"] == 100
        assert v["uploaded_by"] == str(admin_id)

    async def test_versions_endpoint_empty_dataset(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GET /datasets/{id}/versions for dataset with no versions returns empty list."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        resp = await client.get(
            f"/datasets/{dataset.id}/versions/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["versions"] == []


# ---------------------------------------------------------------------------
# DatasetResponse includes current_version
# ---------------------------------------------------------------------------


class TestCurrentVersionInResponse:
    async def test_dataset_response_includes_current_version(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        """GET /datasets/{id} response includes current_version field."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)

        resp = await client.get(
            f"/datasets/{dataset.id}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "current_version" in data
        assert data["current_version"] == 1


# ---------------------------------------------------------------------------
# Schema diff pure function test
# ---------------------------------------------------------------------------


class TestSchemaDiffComputation:
    def test_schema_diff_computation(self):
        """Unit test: compute_schema_diff with known inputs returns correct diff."""
        old_cols = [
            {"name": "id", "type": "Integer"},
            {"name": "name", "type": "String"},
            {"name": "old_only", "type": "Real"},
        ]
        new_cols = [
            {"name": "id", "type": "Integer"},
            {"name": "name", "type": "Real"},  # type change
            {"name": "new_only", "type": "String"},  # added
        ]

        result = compute_schema_diff(old_cols, new_cols, 100, 150)

        assert result["columns_added"] == [{"name": "new_only", "type": "String"}]
        assert result["columns_removed"] == [{"name": "old_only", "type": "Real"}]
        assert result["type_changes"] == [
            {"name": "name", "old_type": "String", "new_type": "Real"}
        ]
        assert result["row_count_old"] == 100
        assert result["row_count_new"] == 150
        assert result["row_count_delta"] == 50

    def test_schema_diff_no_changes(self):
        """Identical schemas produce empty diff."""
        cols = [{"name": "a", "type": "Integer"}]
        result = compute_schema_diff(cols, cols, 10, 10)
        assert result["columns_added"] == []
        assert result["columns_removed"] == []
        assert result["type_changes"] == []
        assert result["row_count_delta"] == 0

    def test_schema_diff_null_counts(self):
        """Null feature counts handled gracefully."""
        result = compute_schema_diff([], [], None, None)
        assert result["row_count_old"] is None
        assert result["row_count_new"] is None
        assert result["row_count_delta"] == 0

    def test_schema_diff_case_insensitive(self):
        """Column matching is case-insensitive (ogr2ogr lowercases on import)."""
        old_cols = [{"name": "label12", "type": "character varying"}]
        new_cols = [{"name": "LABEL12", "type": "String"}]
        result = compute_schema_diff(old_cols, new_cols, 10, 10)
        assert result["columns_added"] == []
        assert result["columns_removed"] == []
        assert result["type_changes"] == []


class TestStagingTableName:
    """Staging table names must fit PostgreSQL's 63-char identifier limit."""

    def test_short_name_gets_staging_suffix(self):
        name = "roads"
        staging = f"{name[:54]}_staging"
        assert staging == "roads_staging"
        assert len(staging) <= 63

    def test_long_name_truncated_before_suffix(self):
        name = "computed_change_in_land_use_and_land_cover_from_2012_to_2015"
        assert len(name) == 60
        staging = f"{name[:54]}_staging"
        assert len(staging) == 62
        assert staging.endswith("_staging")
        assert len(staging) <= 63

    def test_max_length_name(self):
        name = "a" * 63
        staging = f"{name[:54]}_staging"
        assert len(staging) == 62
        assert staging == "a" * 54 + "_staging"
