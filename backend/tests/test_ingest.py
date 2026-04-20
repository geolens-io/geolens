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

from app.modules.auth.models import User
from app.platform.jobs.models import IngestJob
from tests.conftest import get_auth_header


# ---------------------------------------------------------------------------
# Module-scoped autouse mocks
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_ingest_task():
    """Prevent procrastinate task deferral in all ingest tests.

    The router now delegates all task routing (ingest_file / ingest_raster
    / ingest_service) to ``queue_ingest_job`` in the service layer (post-
    impl audit KISS-9). Mock that single entry point so every commit_import
    path becomes a no-op.
    """
    with patch(
        "app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock
    ) as mock_task:
        yield mock_task


@pytest.fixture(autouse=True)
def mock_file_save(tmp_path: Path):
    """Save mocked uploads to a temp path so validation sees a real file."""
    with patch(
        "app.processing.ingest.router.save_upload_file", new_callable=AsyncMock
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
        from app.modules.auth.models import User

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
        from app.modules.auth.models import User

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

        from app.modules.auth.models import User

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

        from app.modules.auth.models import User

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

    from app.modules.catalog.datasets.domain.models import Dataset
    from app.processing.ingest.tasks import (
        IngestContext,
        _arcgis_type_to_column_type,
        _finalize_ingest,
    )
    from app.platform.jobs.models import IngestJob

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
            IngestContext(
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


# ---------------------------------------------------------------------------
# K1 — ingest_file phase helpers (_detect_and_override_geometry, _archive_original_file)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_detect_and_override_geometry_returns_none_when_no_override(
    test_db_session,
):
    """Empty user_metadata → helper is a no-op returning None (KISS-2)."""
    from app.processing.ingest.tasks import _detect_and_override_geometry

    geom_type = await _detect_and_override_geometry(
        test_db_session,
        table_name="ignored",
        user_metadata={},
    )
    assert geom_type is None


@pytest.mark.anyio
async def test_detect_and_override_geometry_x_y_constructs_point(test_db_session):
    """x_column + y_column metadata triggers construct_point_geometry."""
    import uuid as _uuid

    from sqlalchemy import text

    from app.processing.ingest.tasks import _detect_and_override_geometry

    table_name = f"tst_xygeom_{_uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "  gid SERIAL PRIMARY KEY,"
            "  lon DOUBLE PRECISION,"
            "  lat DOUBLE PRECISION"
            ")"
        )
    )
    await test_db_session.execute(
        text(f"INSERT INTO data.{table_name} (lon, lat) VALUES (2.35, 48.85)")
    )
    await test_db_session.commit()

    try:
        geom_type = await _detect_and_override_geometry(
            test_db_session,
            table_name=table_name,
            user_metadata={"x_column": "lon", "y_column": "lat"},
        )
        assert geom_type == "Point"

        # Verify a geom column was actually created and populated.
        col_check = await test_db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='data' AND table_name=:t AND column_name='geom'"
            ).bindparams(t=table_name)
        )
        assert col_check.scalar_one_or_none() == "geom"

        geom_check = await test_db_session.execute(
            text(f"SELECT ST_AsText(geom) FROM data.{table_name} WHERE gid=1")
        )
        wkt = geom_check.scalar_one()
        assert wkt.startswith("POINT(")
    finally:
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{table_name} CASCADE")
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_detect_and_override_geometry_uppercase_column_names_lowered(
    test_db_session,
):
    """ogr2ogr lowercases column names; helper must match regardless of input case."""
    import uuid as _uuid

    from sqlalchemy import text

    from app.processing.ingest.tasks import _detect_and_override_geometry

    table_name = f"tst_xyupper_{_uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "  gid SERIAL PRIMARY KEY,"
            "  lon DOUBLE PRECISION,"
            "  lat DOUBLE PRECISION"
            ")"
        )
    )
    await test_db_session.execute(
        text(f"INSERT INTO data.{table_name} (lon, lat) VALUES (-0.13, 51.51)")
    )
    await test_db_session.commit()

    try:
        # Uppercase input — helper lowercases before querying.
        geom_type = await _detect_and_override_geometry(
            test_db_session,
            table_name=table_name,
            user_metadata={"x_column": "LON", "y_column": "LAT"},
        )
        assert geom_type == "Point"
    finally:
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{table_name} CASCADE")
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_detect_and_override_geometry_wkt_column_detects_type(test_db_session):
    """geom_column metadata triggers construct_wkt_geometry and re-detects type."""
    import uuid as _uuid

    from sqlalchemy import text

    from app.processing.ingest.tasks import _detect_and_override_geometry

    table_name = f"tst_wktgeom_{_uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "  gid SERIAL PRIMARY KEY,"
            "  wkt_field TEXT"
            ")"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table_name} (wkt_field) "
            "VALUES ('LINESTRING(0 0, 1 1, 2 2)')"
        )
    )
    await test_db_session.commit()

    try:
        geom_type = await _detect_and_override_geometry(
            test_db_session,
            table_name=table_name,
            user_metadata={"geom_column": "wkt_field"},
        )
        # Re-detected from the constructed column — PostGIS GeometryType()
        # returns the uppercase short form (LINESTRING/POLYGON/etc).
        assert geom_type == "LINESTRING"
    finally:
        await test_db_session.execute(
            text(f"DROP TABLE IF EXISTS data.{table_name} CASCADE")
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_detect_and_override_geometry_empty_strings_treated_as_absent(
    test_db_session,
):
    """Empty strings must not trigger the override path — they mean 'not set'."""
    from app.processing.ingest.tasks import _detect_and_override_geometry

    geom_type = await _detect_and_override_geometry(
        test_db_session,
        table_name="ignored",
        user_metadata={"x_column": "", "y_column": "", "geom_column": ""},
    )
    assert geom_type is None


# ---------------------------------------------------------------------------
# _archive_original_file tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_archive_original_file_success_leaves_user_metadata_untouched(
    tmp_path, monkeypatch
):
    """Happy path: storage.put succeeds, job.user_metadata is NOT mutated."""
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.processing.ingest.tasks import _archive_original_file

    # Create a real file to upload.
    upload_file = tmp_path / "roads.geojson"
    upload_file.write_text('{"type":"FeatureCollection","features":[]}')

    put_calls = []

    mock_storage = AsyncMock()
    mock_storage.put = AsyncMock(side_effect=lambda key, fobj: put_calls.append(key))

    monkeypatch.setattr(
        "app.processing.ingest.tasks_common.get_storage", lambda: mock_storage
    )

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    job = MagicMock()
    job.user_metadata = {"title": "Roads", "summary": "test"}

    dataset_id = _uuid.uuid4()

    await _archive_original_file(
        mock_session,
        job=job,
        dataset_id=dataset_id,
        file_path=str(upload_file),
    )

    # Storage.put called with expected key format
    assert len(put_calls) == 1
    assert put_calls[0] == f"originals/{dataset_id}/roads.geojson"

    # user_metadata untouched on success
    assert job.user_metadata == {"title": "Roads", "summary": "test"}
    assert "archive_failed" not in job.user_metadata


@pytest.mark.anyio
async def test_archive_original_file_failure_marks_user_metadata(tmp_path, monkeypatch):
    """Storage failure → job.user_metadata['archive_failed']=True + error recorded."""
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.processing.ingest.tasks import _archive_original_file

    upload_file = tmp_path / "cities.csv"
    upload_file.write_text("name,lat,lng\nParis,48.85,2.35\n")

    mock_storage = AsyncMock()
    mock_storage.put = AsyncMock(side_effect=RuntimeError("S3 unreachable"))

    monkeypatch.setattr(
        "app.processing.ingest.tasks_common.get_storage", lambda: mock_storage
    )

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    job = MagicMock()
    job.user_metadata = {"title": "Cities"}

    dataset_id = _uuid.uuid4()

    # Must NOT raise — archive is best-effort.
    await _archive_original_file(
        mock_session,
        job=job,
        dataset_id=dataset_id,
        file_path=str(upload_file),
    )

    assert job.user_metadata["archive_failed"] is True
    assert "S3 unreachable" in job.user_metadata["archive_error"]
    assert job.user_metadata["title"] == "Cities"  # preserved
    mock_session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_archive_original_file_commit_failure_does_not_raise(
    tmp_path, monkeypatch
):
    """RESILIENCE-1 regression: commit failure after archive failure must not raise.

    Before fix: if storage.put raised AND then session.commit raised (e.g. a
    transient pooler drop), the unguarded commit propagated out of the helper
    and flipped the already-successful ingest into a 'failed' job via the
    outer task try/except. The dataset was already committed, so Procrastinate
    would re-run the whole pipeline on retry and produce duplicate datasets.

    After fix: the metadata commit is in its own try/except so commit failures
    are logged and dropped — the dataset stays successful.
    """
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.processing.ingest.tasks import _archive_original_file

    upload_file = tmp_path / "fragile.geojson"
    upload_file.write_text('{"type":"FeatureCollection","features":[]}')

    mock_storage = AsyncMock()
    mock_storage.put = AsyncMock(side_effect=RuntimeError("S3 unreachable"))
    monkeypatch.setattr(
        "app.processing.ingest.tasks_common.get_storage", lambda: mock_storage
    )

    mock_session = AsyncMock()
    # Commit fails — simulate a pooler drop or deadlock.
    mock_session.commit = AsyncMock(side_effect=RuntimeError("pooler dropped"))
    mock_session.rollback = AsyncMock()

    job = MagicMock()
    job.user_metadata = {"title": "Fragile"}
    dataset_id = _uuid.uuid4()

    # Must NOT raise — both the archive put AND the metadata commit failed.
    await _archive_original_file(
        mock_session,
        job=job,
        dataset_id=dataset_id,
        file_path=str(upload_file),
    )

    # user_metadata was updated in memory even though the commit didn't persist.
    assert job.user_metadata["archive_failed"] is True
    assert "S3 unreachable" in job.user_metadata["archive_error"]
    # Rollback was called so the session is clean for the caller.
    mock_session.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_archive_original_file_failure_truncates_long_error(
    tmp_path, monkeypatch
):
    """Very long error messages are truncated to 500 chars to avoid JSONB bloat."""
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.processing.ingest.tasks import _archive_original_file

    upload_file = tmp_path / "big.shp.zip"
    upload_file.write_bytes(b"PK\x03\x04")  # fake zip header

    long_error = "X" * 2000  # way over 500 char limit

    mock_storage = AsyncMock()
    mock_storage.put = AsyncMock(side_effect=RuntimeError(long_error))

    monkeypatch.setattr(
        "app.processing.ingest.tasks_common.get_storage", lambda: mock_storage
    )

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    job = MagicMock()
    job.user_metadata = None  # test the None branch too

    await _archive_original_file(
        mock_session,
        job=job,
        dataset_id=_uuid.uuid4(),
        file_path=str(upload_file),
    )

    assert job.user_metadata is not None
    assert job.user_metadata["archive_failed"] is True
    assert len(job.user_metadata["archive_error"]) == 500


# ---------------------------------------------------------------------------
# queue_ingest_job orphan-guard (RESILIENCE-2 extension)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_queue_ingest_job_file_defer_failure_marks_job_failed(tmp_path):
    """Procrastinate outage during file ingest defer → job marked failed + 503."""
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from app.processing.ingest.service import queue_ingest_job

    # Real file on disk so queue_ingest_job's size probe runs.
    upload_file = tmp_path / "cities.geojson"
    upload_file.write_text('{"type":"FeatureCollection","features":[]}')

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    job = MagicMock()
    job.id = _uuid.uuid4()
    job.source_url = None
    job.file_path = str(upload_file)
    job.user_metadata = None
    job.status = "pending"
    job.error_message = None
    job.completed_at = None

    failing_defer = AsyncMock(side_effect=RuntimeError("procrastinate unreachable"))

    with patch("app.processing.ingest.tasks.ingest_file") as mock_task:
        # Small file path routes to configure("priority").defer_async
        priority_task = MagicMock()
        priority_task.defer_async = failing_defer
        mock_task.configure.return_value = priority_task
        mock_task.defer_async = failing_defer

        with pytest.raises(HTTPException) as exc_info:
            await queue_ingest_job(job, "user-id", db=mock_db)

    assert exc_info.value.status_code == 503
    assert job.status == "failed"
    assert job.error_message is not None
    assert "procrastinate unreachable" in job.error_message
    assert job.completed_at is not None
    mock_db.commit.assert_awaited()


@pytest.mark.anyio
async def test_queue_ingest_job_service_defer_failure_marks_job_failed():
    """Procrastinate outage during service ingest defer → job marked failed + 503."""
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from app.processing.ingest.service import queue_ingest_job

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    job = MagicMock()
    job.id = _uuid.uuid4()
    job.source_url = "https://example.com/services/arcgis/0"
    job.source_layer = "parcels"
    job.file_path = None
    job.user_metadata = None
    job.status = "pending"
    job.error_message = None
    job.completed_at = None

    failing_defer = AsyncMock(side_effect=RuntimeError("queue down"))

    with patch(
        "app.processing.ingest.tasks.ingest_service",
        defer_async=failing_defer,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await queue_ingest_job(job, "user-id", db=mock_db)

    assert exc_info.value.status_code == 503
    assert job.status == "failed"
    assert "queue down" in job.error_message


@pytest.mark.anyio
async def test_queue_ingest_job_raster_defer_failure_marks_job_failed(tmp_path):
    """Procrastinate outage during raster ingest defer → job marked failed + 503."""
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi import HTTPException

    from app.processing.ingest.service import queue_ingest_job

    raster_file = tmp_path / "dem.tif"
    raster_file.write_bytes(b"fake-raster")

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()

    job = MagicMock()
    job.id = _uuid.uuid4()
    job.source_url = None
    job.file_path = str(raster_file)
    job.user_metadata = {"file_type": "raster"}
    job.status = "pending"
    job.error_message = None
    job.completed_at = None

    failing_defer = AsyncMock(side_effect=RuntimeError("raster queue dead"))

    with patch(
        "app.processing.ingest.tasks.ingest_raster",
        defer_async=failing_defer,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await queue_ingest_job(job, "user-id", db=mock_db)

    assert exc_info.value.status_code == 503
    assert job.status == "failed"
    assert "raster queue dead" in job.error_message


class TestCommitImportDispatch:
    """Direct router coverage for POST /ingest/commit/{job_id} (Phase 220,
    INGEST-K6-02). Before this phase, the endpoint had zero direct tests."""

    async def test_vector_job_commits_with_vector_body(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        mock_ingest_task,  # explicit to make the assertion visible
    ) -> None:
        """Vector job + vector body -> 202 + queue_ingest_job called."""
        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin = result.scalar_one()

        job = IngestJob(
            source_filename="roads.geojson",
            file_path="/tmp/fake.geojson",
            created_by=admin.id,
            status="pending",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={
                "title": "Roads",
                "summary": "Street centerlines",
                "srid_override": 4326,
                "x_column": "lon",
                "y_column": "lat",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["job_id"] == str(job.id)
        assert data["status"] == "pending"
        assert mock_ingest_task.await_count == 1

    async def test_raster_job_commits_with_raster_body(
        self, client, admin_auth_header, test_db_session, mock_ingest_task
    ) -> None:
        """Raster job + raster body -> 202 + queue_ingest_job called."""
        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin = result.scalar_one()

        job = IngestJob(
            source_filename="dem.tif",
            file_path="/tmp/fake.tif",
            created_by=admin.id,
            status="pending",
            user_metadata={"file_type": "raster"},  # the raster discriminator
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={
                "title": "Elevation",
                "compression": "LZW",
                "resampling": "bilinear",
                "srid_override": 3857,
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 202, resp.text
        assert mock_ingest_task.await_count == 1
        # Verify raster-only fields made it into user_metadata
        await test_db_session.refresh(job)
        assert job.user_metadata["compression"] == "LZW"
        assert job.user_metadata["resampling"] == "bilinear"

    async def test_service_job_commits_with_service_body(
        self, client, admin_auth_header, test_db_session, mock_ingest_task
    ) -> None:
        """Service job + service body -> 202 + queue_ingest_job called with token kwarg."""
        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin = result.scalar_one()

        job = IngestJob(
            source_filename="TestLayer",
            source_url="https://example.arcgis.com/FeatureServer/0",  # service discriminator
            source_layer="0",
            created_by=admin.id,
            status="pending",
            user_metadata={
                "service_type": "ArcGIS:FeatureServer",
                "layer_id": 0,
            },
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={
                "title": "Federal Grants",
                "summary": "Opportunities",
                "token": "bearer-abc",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 202, resp.text
        assert mock_ingest_task.await_count == 1
        # Token must be forwarded via kwarg, not persisted to metadata
        call_kwargs = mock_ingest_task.await_args.kwargs
        assert call_kwargs["token"] == "bearer-abc"
        await test_db_session.refresh(job)
        assert "token" not in (job.user_metadata or {})

    async def test_vector_job_with_kitchen_sink_body_silently_ignores_extras(
        self, client, admin_auth_header, test_db_session, mock_ingest_task
    ) -> None:
        """Vector job + kitchen-sink body (mixed vector/raster/service fields) -> 202.

        Regression test for D-02: the frontend may send irrelevant fields
        and the server must silently ignore them, not 422.
        """
        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin = result.scalar_one()

        job = IngestJob(
            source_filename="mixed.geojson",
            file_path="/tmp/fake.geojson",
            created_by=admin.id,
            status="pending",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={
                "title": "Mixed",
                # vector-applicable
                "x_column": "lon",
                "y_column": "lat",
                # raster-only (should be dropped)
                "compression": "LZW",
                "resampling": "bilinear",
                "nodata_override": -9999,
                # service-only (should be dropped from metadata)
                "token": "leaked-token",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 202, resp.text
        assert mock_ingest_task.await_count == 1

        # queue_ingest_job was called with token=None (not "leaked-token")
        # because vector subclass has no token field and nothing set it.
        call_kwargs = mock_ingest_task.await_args.kwargs
        assert call_kwargs.get("token") is None

        # user_metadata does NOT contain the raster-only fields or token
        await test_db_session.refresh(job)
        meta = job.user_metadata or {}
        assert "compression" not in meta
        assert "resampling" not in meta
        assert "nodata_override" not in meta
        assert "token" not in meta
        assert meta["x_column"] == "lon"
        assert meta["y_column"] == "lat"

    async def test_commit_missing_title_returns_422(
        self, client, admin_auth_header, test_db_session, mock_ingest_task
    ) -> None:
        """Missing required 'title' returns 422 via the project's Problem
        Details handler.

        The project overrides FastAPI's default RequestValidationError handler
        in ``app/ogc/errors.py`` to produce an RFC 7807 Problem Details envelope
        (``title``, ``status``, ``detail``). Using ``RequestValidationError``
        (not ``HTTPException(422)``) in the handler refactor ensures the
        envelope shape is consistent with every other 422 in the API — which
        is the whole point of Pitfall 2.
        """
        result = await test_db_session.execute(
            select(User).where(User.username == "admin")
        )
        admin = result.scalar_one()

        job = IngestJob(
            source_filename="f.geojson",
            file_path="/tmp/fake.geojson",
            created_by=admin.id,
            status="pending",
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        resp = await client.post(
            f"/ingest/commit/{job.id}",
            json={"summary": "no title"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        body = resp.json()
        # Project envelope: RFC 7807 Problem Details with flat ``detail`` string
        assert body["title"] == "Validation Error"
        assert body["status"] == 422
        assert "title" in body["detail"]  # e.g. "body.title: Field required"
        assert "Field required" in body["detail"] or "required" in body["detail"]
        assert mock_ingest_task.await_count == 0
