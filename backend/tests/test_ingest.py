"""Integration tests for ingest endpoints (upload, register) and job status.

These tests run against a real database via httpx ASGITransport. Procrastinate
task deferral and file saving are mocked to avoid side effects.

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

from app.jobs.models import IngestJob
from tests.conftest import get_auth_header


# ---------------------------------------------------------------------------
# Module-scoped autouse mocks
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_ingest_task():
    """Prevent procrastinate task deferral in all ingest tests."""
    with patch("app.ingest.router.ingest_file") as mock_task:
        mock_task.defer_async = AsyncMock(return_value=None)
        yield mock_task


@pytest.fixture(autouse=True)
def mock_file_save(tmp_path: Path):
    """Save mocked uploads to a temp path so validation sees a real file."""
    with patch(
        "app.ingest.router.save_upload_file", new_callable=AsyncMock
    ) as mock_save:

        async def _save_to_temp(file, job_id: str) -> Path:
            dest = tmp_path / f"{job_id}_{file.filename}"
            dest.write_bytes(await file.read())
            await file.seek(0)
            return dest

        mock_save.side_effect = _save_to_temp
        yield mock_save


# ---------------------------------------------------------------------------
# Upload endpoint tests
# ---------------------------------------------------------------------------


class TestUpload:
    async def test_upload_requires_auth(self, client: AsyncClient):
        """POST /ingest/upload without token returns 401."""
        resp = await client.post(
            "/ingest/upload",
            files={
                "file": (
                    "test.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
        )
        assert resp.status_code == 401

    async def test_upload_requires_editor_or_admin(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /ingest/upload with viewer token returns 403."""
        resp = await client.post(
            "/ingest/upload",
            files={
                "file": (
                    "test.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/json",
                )
            },
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_upload_rejects_bad_extension(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /ingest/upload with a .txt file returns 400."""
        resp = await client.post(
            "/ingest/upload",
            files={"file": ("data.txt", b"some text content", "text/plain")},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"].lower()

    async def test_upload_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_ingest_task,
        mock_file_save,
        test_db_session,
    ):
        """POST /ingest/upload with valid file returns 201 with job_id."""
        geojson = b'{"type":"FeatureCollection","features":[]}'
        resp = await client.post(
            "/ingest/upload",
            files={"file": ("test.geojson", geojson, "application/json")},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"

        # Verify IngestJob record was created in DB
        job_id = uuid.UUID(data["job_id"])
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        assert job is not None
        assert job.status == "pending"


# ---------------------------------------------------------------------------
# CSV upload tests
# ---------------------------------------------------------------------------


class TestCsvUpload:
    async def test_csv_upload_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        mock_ingest_task,
        mock_file_save,
        test_db_session,
    ):
        """POST /ingest/upload with a valid CSV file returns 201 with job_id."""
        csv_content = b"id,name,value\n1,Alice,100\n2,Bob,200\n"
        resp = await client.post(
            "/ingest/upload",
            files={"file": ("data.csv", csv_content, "text/csv")},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "pending"

        # Verify IngestJob record was created in DB
        job_id = uuid.UUID(data["job_id"])
        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        assert job is not None
        assert job.status == "pending"


# ---------------------------------------------------------------------------
# Register endpoint tests
# ---------------------------------------------------------------------------


class TestRegister:
    async def test_register_requires_auth(self, client: AsyncClient):
        """POST /ingest/register without token returns 401."""
        resp = await client.post(
            "/ingest/register/",
            json={
                "table_name": "nonexistent",
                "title": "Test",
            },
        )
        assert resp.status_code == 401

    async def test_register_requires_editor_or_admin(
        self, client: AsyncClient, viewer_auth_header: dict
    ):
        """POST /ingest/register with viewer token returns 403."""
        resp = await client.post(
            "/ingest/register/",
            json={
                "table_name": "nonexistent",
                "title": "Test",
            },
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403

    async def test_register_nonexistent_table(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /ingest/register with a table_name that doesn't exist returns 400."""
        resp = await client.post(
            "/ingest/register/",
            json={
                "table_name": "totally_nonexistent_table_xyz",
                "title": "Bad Table",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "does not exist" in resp.json()["detail"].lower()

    async def test_register_table_rejects_sql_injection(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /ingest/register with SQL injection in table_name returns 400."""
        resp = await client.post(
            "/ingest/register/",
            json={
                "table_name": "test'; DROP TABLE data.users; --",
                "title": "Exploit",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "invalid table name" in resp.json()["detail"].lower()

    async def test_register_table_rejects_uppercase(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """POST /ingest/register with uppercase table_name returns 400."""
        resp = await client.post(
            "/ingest/register/",
            json={
                "table_name": "MyTable",
                "title": "Bad",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "invalid table name" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Job status endpoint tests
# ---------------------------------------------------------------------------


class TestJobStatus:
    async def test_job_status_requires_auth(self, client: AsyncClient):
        """GET /jobs/{id} without token returns 401."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/jobs/{fake_id}")
        assert resp.status_code == 401

    async def test_job_status_not_found(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """GET /jobs/{id} with auth for nonexistent job returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/jobs/{fake_id}", headers=admin_auth_header)
        assert resp.status_code == 404

    async def test_job_status_success(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /jobs/{id} returns correct status for a job owned by the user."""
        # Get admin user ID
        from app.auth.models import User

        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin_user = result.scalar_one()

        # Create an IngestJob directly in DB
        job = IngestJob(
            source_filename="test.geojson",
            file_path="/tmp/fake.geojson",
            created_by=admin_user.id,
            status="complete",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(job.id)
        assert data["status"] == "complete"

    async def test_job_status_forbidden_other_user(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Non-creator, non-admin user gets 403 on another user's job."""
        # Get admin user ID
        from app.auth.models import User

        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin_user = result.scalar_one()

        # Create a job as admin
        job = IngestJob(
            source_filename="admin_file.geojson",
            file_path="/tmp/fake.geojson",
            created_by=admin_user.id,
            status="pending",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        # Create an editor user and try to access admin's job
        unique = uuid.uuid4().hex[:8]
        username = f"editor_jobtest_{unique}"
        resp = await client.post(
            "/admin/users/",
            json={"username": username, "password": "testpass123", "role": "editor"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        editor_headers = await get_auth_header(client, username, "testpass123")
        resp = await client.get(f"/jobs/{job.id}", headers=editor_headers)
        assert resp.status_code == 403

    async def test_job_status_auto_fails_stale_pending(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """GET /jobs/{id} auto-fails a pending job older than 1 hour."""
        from datetime import datetime, timedelta, timezone

        from app.auth.models import User

        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin_user = result.scalar_one()

        job = IngestJob(
            source_filename="stale.geojson",
            file_path="/tmp/fake.geojson",
            created_by=admin_user.id,
            status="pending",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        # Backdate created_at to 2 hours ago
        job.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await test_db_session.commit()

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert "pending" in data["error_message"].lower()


class TestJobCleanup:
    async def test_cleanup_requires_admin(self, client: AsyncClient):
        """POST /jobs/cleanup/stale without auth returns 401."""
        resp = await client.post("/jobs/cleanup/stale/")
        assert resp.status_code == 401

    async def test_cleanup_stale_jobs(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """POST /jobs/cleanup/stale marks old pending jobs as failed."""
        from datetime import datetime, timedelta, timezone

        from app.auth.models import User

        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin_user = result.scalar_one()

        # Create a stale pending job (2 hours old)
        stale_job = IngestJob(
            source_filename="stale.geojson",
            created_by=admin_user.id,
            status="pending",
        )
        test_db_session.add(stale_job)
        await test_db_session.commit()
        await test_db_session.refresh(stale_job)

        stale_job.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await test_db_session.commit()

        # Create a fresh pending job (should NOT be cleaned up)
        fresh_job = IngestJob(
            source_filename="fresh.geojson",
            created_by=admin_user.id,
            status="pending",
        )
        test_db_session.add(fresh_job)
        await test_db_session.commit()
        await test_db_session.refresh(fresh_job)

        resp = await client.post("/jobs/cleanup/stale/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_failed"] >= 1

        # Verify stale job is failed
        await test_db_session.refresh(stale_job)
        assert stale_job.status == "failed"

        # Verify fresh job is still pending
        await test_db_session.refresh(fresh_job)
        assert fresh_job.status == "pending"


# ---------------------------------------------------------------------------
# Non-spatial CSV pipeline tests
# ---------------------------------------------------------------------------


class TestCsvNonSpatialPipeline:
    """End-to-end test for registering a non-spatial table and querying it."""

    @pytest.fixture(autouse=True)
    def mock_ingest_task(self):
        """No-op override -- register path does not defer tasks."""
        yield

    @pytest.fixture(autouse=True)
    def mock_file_save(self):
        """No-op override -- register path does not save files."""
        yield

    async def test_csv_non_spatial_full_pipeline(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Register a non-spatial table, verify record_type='table', query features."""
        from sqlalchemy import text

        table_name = "test_csv_nonspatial"

        try:
            # 1. Create non-spatial table in data schema (gid matches ogr2ogr default)
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table_name} ("
                    "  gid serial PRIMARY KEY,"
                    "  name text,"
                    "  value integer"
                    ")"
                )
            )
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table_name} (name, value) VALUES "
                    "('Alice', 100), ('Bob', 200)"
                )
            )
            await test_db_session.commit()

            # 2. Register via POST /ingest/register
            resp = await client.post(
                "/ingest/register/",
                json={"table_name": table_name, "title": "Test CSV Table"},
                headers=admin_auth_header,
            )
            assert resp.status_code == 201, resp.text
            dataset_id = resp.json()["dataset_id"]

            # 3. GET /datasets/{id} -- verify record_type and geometry_type
            resp = await client.get(
                f"/datasets/{dataset_id}",
                headers=admin_auth_header,
                follow_redirects=True,
            )
            assert resp.status_code == 200, (
                f"Expected 200, got {resp.status_code}: {resp.text}"
            )
            ds = resp.json()
            assert ds["record_type"] == "table"
            assert ds["geometry_type"] is None

            # 4. GET /datasets/{id}/features/ -- verify 2 rows returned
            resp = await client.get(
                f"/datasets/{dataset_id}/features/",
                headers=admin_auth_header,
            )
            assert resp.status_code == 200
            features = resp.json()
            assert features["numberMatched"] == 2
            names = {f["properties"]["name"] for f in features["features"]}
            assert names == {"Alice", "Bob"}

        finally:
            # Clean up the test table
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name} CASCADE")
            )
            await test_db_session.commit()

    async def _register_nonspatial_table(
        self, client, admin_auth_header, test_db_session, table_name, title="Test Table"
    ):
        """Helper: create a non-spatial table, register it, return (dataset_id, record_id)."""
        from sqlalchemy import text

        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                "  gid serial PRIMARY KEY,"
                "  name text,"
                "  value integer"
                ")"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (name, value) VALUES "
                "('Alice', 100), ('Bob', 200)"
            )
        )
        await test_db_session.commit()

        resp = await client.post(
            "/ingest/register/",
            json={"table_name": table_name, "title": title},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        dataset_id = resp.json()["dataset_id"]

        resp = await client.get(
            f"/datasets/{dataset_id}",
            headers=admin_auth_header,
            follow_redirects=True,
        )
        assert resp.status_code == 200
        record_id = resp.json()["record_id"]

        return dataset_id, record_id

    @pytest.mark.parametrize(
        "table_name,title",
        [
            ("test_csv_nonspatial_dists", "Test CSV Dists"),
            ("test_xlsx_nonspatial", "Test XLSX Table"),
        ],
    )
    async def test_non_spatial_distributions(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        table_name: str,
        title: str,
    ):
        """Non-spatial tables should produce only csv download + ogc_features distributions."""
        from sqlalchemy import text

        try:
            _, record_id = await self._register_nonspatial_table(
                client, admin_auth_header, test_db_session, table_name, title
            )

            resp = await client.get(
                f"/records/{record_id}/distributions/",
                headers=admin_auth_header,
            )
            assert resp.status_code == 200
            distributions = resp.json()["distributions"]

            dist_types = [
                (d["distribution_type"], d.get("format")) for d in distributions
            ]
            assert ("download", "csv") in dist_types
            assert ("ogc_features", "geojson") in dist_types
            assert len(distributions) == 2, (
                f"Expected 2 distributions, got {len(distributions)}: {dist_types}"
            )
            assert ("download", "gpkg") not in dist_types
            assert ("download", "geojson") not in dist_types
            assert ("download", "shp") not in dist_types
            assert ("vector_tiles", "pbf") not in dist_types

        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name} CASCADE")
            )
            await test_db_session.commit()

    async def test_non_spatial_ogc_items(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """OGC items endpoint returns features with geometry:null for non-spatial dataset."""
        from sqlalchemy import text

        table_name = "test_nonspatial_ogc"

        try:
            dataset_id, _ = await self._register_nonspatial_table(
                client,
                admin_auth_header,
                test_db_session,
                table_name,
                "Test OGC NonSpatial",
            )

            resp = await client.get(
                f"/collections/{dataset_id}/items",
                headers=admin_auth_header,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["numberMatched"] == 2
            for feature in data["features"]:
                assert feature["geometry"] is None

        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name} CASCADE")
            )
            await test_db_session.commit()


# ---------------------------------------------------------------------------
# ArcGIS column_info fallback test (260408-iny)
# ---------------------------------------------------------------------------


async def _get_admin_id_for_ingest(session):
    """Helper to get admin user id for Task 3 tests."""
    from tests.factories import get_user_id

    return await get_user_id(session, "admin")


@pytest.mark.anyio
async def test_arcgis_table_ingest_populates_column_info(test_db_session):
    """When ogr2ogr creates a table with no attribute columns (only gid),
    the ArcGIS fields fallback in _finalize_ingest should populate column_info
    from source_columns stored in user_metadata.

    Verifies _arcgis_type_to_column_type helper and the fallback branch.
    """
    import uuid as _uuid

    from sqlalchemy import text

    from app.datasets.models import Dataset
    from app.ingest.tasks import _arcgis_type_to_column_type, _finalize_ingest
    from app.jobs.models import IngestJob

    admin_id = await _get_admin_id_for_ingest(test_db_session)

    source_columns = [
        {"name": "Opportunity_Number", "type": "esriFieldTypeString"},
        {"name": "Federal_Agency", "type": "esriFieldTypeString"},
        {"name": "Category", "type": "esriFieldTypeString"},
        {"name": "Opening_Date", "type": "esriFieldTypeDate"},
        {"name": "FID2", "type": "esriFieldTypeOID"},
    ]
    user_metadata = {
        "service_type": "ArcGIS:FeatureServer",
        "layer_id": 0,
        "geometry_type": None,
        "source_columns": source_columns,
        "title": "ArcGIS Column Info Test",
        "visibility": "private",
    }

    job = IngestJob(
        source_filename="TestTable",
        source_url="https://example.arcgis.com/FeatureServer/0",
        source_layer="0",
        created_by=admin_id,
        status="running",
        user_metadata=user_metadata,
    )
    test_db_session.add(job)
    await test_db_session.flush()

    # Simulate Case 2: ogr2ogr created only the gid column (no attribute columns)
    table_name = f"tbl_arcgis_{_uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(f"CREATE TABLE IF NOT EXISTS data.{table_name} (gid serial PRIMARY KEY)")
    )
    await test_db_session.commit()

    try:
        await _finalize_ingest(
            session=test_db_session,
            job=job,
            table_name=table_name,
            user_id=str(admin_id),
            has_geometry=False,
            effective_srid=None,
            source_format="arcgis_featureserver",
            source_filename="TestTable",
            original_srid=None,
            user_metadata=user_metadata,
        )

        from sqlalchemy import select

        result = await test_db_session.execute(
            select(Dataset).where(Dataset.table_name == table_name)
        )
        dataset = result.scalar_one()

        assert dataset.column_info is not None
        assert len(dataset.column_info) == 5

        names = [c["name"] for c in dataset.column_info]
        assert "Opportunity_Number" in names
        assert "Federal_Agency" in names
        assert "Opening_Date" in names

        # Verify type mapping
        by_name = {c["name"]: c for c in dataset.column_info}
        assert by_name["Opportunity_Number"]["type"] == "text"
        assert by_name["Opening_Date"]["type"] == "timestamp without time zone"
        assert by_name["FID2"]["type"] == "integer"

        # Verify ordinal_position is sequential from 1
        assert by_name["Opportunity_Number"]["ordinal_position"] == 1
        assert by_name["FID2"]["ordinal_position"] == 5

        # Verify _arcgis_type_to_column_type helper directly
        assert _arcgis_type_to_column_type("esriFieldTypeString") == "text"
        assert _arcgis_type_to_column_type("esriFieldTypeInteger") == "integer"
        assert _arcgis_type_to_column_type("esriFieldTypeDouble") == "double precision"
        assert (
            _arcgis_type_to_column_type("esriFieldTypeDate")
            == "timestamp without time zone"
        )
        assert _arcgis_type_to_column_type("esriFieldTypeOID") == "integer"
        assert _arcgis_type_to_column_type("esriFieldTypeUnknown") == "text"  # fallback

    finally:
        await test_db_session.rollback()
        async with test_db_session.begin_nested():
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name} CASCADE")
            )
