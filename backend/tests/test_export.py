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
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.export.ogr import FORMAT_MAP

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    record_type: str = "vector_dataset",
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
        record_type=record_type,
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

    monkeypatch.setattr("app.processing.export.router.export_dataset", _fake_export)

    yield _fake_export

    # Cleanup temp dir if it still exists (BackgroundTask may have removed it)
    if os.path.isdir(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestExportAuth:
    @pytest.mark.anyio
    async def test_export_anonymous_missing_dataset_returns_404(
        self, client: AsyncClient
    ):
        """EXP-01: export no longer requires authentication — anonymous callers
        may export public+published datasets (matching the OGC/tiles contract).
        An anonymous request for a non-existent dataset therefore resolves to a
        normal 404 (dataset not found), NOT a 401. Anonymous denial of
        private/restricted/unpublished data and the public+published allow path
        are covered by test_export_access.py (EXP-02)."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/datasets/{fake_id}/export")
        assert resp.status_code == 404

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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="PublicExportDS",
        )

        resp = await client.get(f"/datasets/{ds.id}/export", headers=viewer_auth_header)
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_export_authed_delegates_to_permission_extension(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """Authed export enforces the 'export' capability through the permission
        extension (same path as require_permission), not just the raw role
        matrix, so a custom PermissionExtension that denies export is honored
        even when the matrix grants it. Regression for the Codex review of
        export/router.py:92."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            name="ExtGateDS",
        )

        # Baseline: the default extension grants the viewer export (matrix-backed).
        resp_ok = await client.get(
            f"/datasets/{ds.id}/export", headers=viewer_auth_header
        )
        assert resp_ok.status_code == 200

        # A custom PermissionExtension that denies 'export' must be honored → 403,
        # even though the persisted role matrix still grants it.
        class _DenyExt:
            async def check_permission(self, *args, **kwargs):
                return False

        monkeypatch.setattr(
            "app.processing.export.router.get_permission_extension",
            lambda: _DenyExt(),
        )
        resp_denied = await client.get(
            f"/datasets/{ds.id}/export", headers=viewer_auth_header
        )
        assert resp_denied.status_code == 403
        assert "export" in resp_denied.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestExportValidation:
    @pytest.mark.anyio
    async def test_export_invalid_format(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request with format=xyz returns 400."""
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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

    @pytest.mark.anyio
    async def test_export_table_dataset_csv_allowed(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A legitimate non-spatial TABLE dataset (record_type='table',
        geometry_type=None) is a real CSV-exportable table and must NOT be
        blocked by the raster/VRT record_type guard. Regression for the guard
        keying on record_type (not geometry_type)."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="TableCsvDS",
            geometry_type=None,
            record_type="table",
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "csv"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_export_raster_dataset_csv_returns_400_not_500(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """E2: a raster dataset (record_type='raster_dataset', geometry_type
        None, synthetic table_name with no backing table) requesting format=csv
        must return a clean 400 — NOT a raw 500 from ogr2ogr hitting a
        nonexistent table."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="RasterCsvDS",
            geometry_type=None,
            record_type="raster_dataset",
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "csv"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "raster" in resp.json()["detail"].lower()

    @pytest.mark.anyio
    async def test_export_vrt_dataset_csv_returns_400(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """E2: a VRT dataset (record_type='vrt_dataset') is likewise blocked
        from tabular export with a 400."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="VrtCsvDS",
            geometry_type=None,
            record_type="vrt_dataset",
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "csv"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "raster" in resp.json()["detail"].lower()

    @pytest.mark.anyio
    async def test_export_raster_dataset_gpkg_returns_400(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """E2: the raster guard fires before the geometry/format gate, so a
        spatial format (gpkg) on a raster dataset also returns the raster 400
        (not the generic non-spatial 400)."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="RasterGpkgDS",
            geometry_type=None,
            record_type="raster_dataset",
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"format": "gpkg"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
        assert "raster" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Format tests
# ---------------------------------------------------------------------------


class TestExportFormats:
    @pytest.mark.anyio
    async def test_export_default_format_gpkg(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Request without format param returns 200 with geopackage Content-Type."""
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
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
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session, created_by=admin_id, name="WhereParamDS"
        )
        resp = await client.get(
            f"/datasets/{ds.id}/export",
            params={"where": "pop > 1000"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Feature-cap tests — fix(#430 BA-08), codex r8
# ---------------------------------------------------------------------------


class TestExportFeatureCap:
    """The 5M export cap must gate on what the filter SELECTS, not on whether a
    filter is merely present: where=1=1 passes the AST validator (Literal EQ
    Literal, no identifiers) and previously bypassed the cap entirely.

    Tests lower _MAX_EXPORT_FEATURES to 2 and use a real 3-row data table so
    the bounded filtered COUNT runs for real.
    """

    @pytest.fixture
    async def capped_dataset(self, test_db_session, monkeypatch):
        """Real 3-row point table + Dataset row, with the cap lowered to 2."""
        from sqlalchemy import text

        from app.processing.export import router as export_router

        monkeypatch.setattr(export_router, "_MAX_EXPORT_FEATURES", 2)

        table_name = f"exp_cap_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} "
                "(gid serial PRIMARY KEY, pop integer, "
                "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (pop, geom, geom_4326) VALUES "
                "(10, ST_SetSRID(ST_MakePoint(0, 0), 4326), "
                " ST_SetSRID(ST_MakePoint(0, 0), 4326)), "
                "(20, ST_SetSRID(ST_MakePoint(1, 1), 4326), "
                " ST_SetSRID(ST_MakePoint(1, 1), 4326)), "
                "(30, ST_SetSRID(ST_MakePoint(2, 2), 4326), "
                " ST_SetSRID(ST_MakePoint(2, 2), 4326))"
            )
        )
        await test_db_session.commit()

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="CappedExportDS",
            table_name=table_name,
            geometry_type="Point",
            feature_count=3,
            column_info=[
                {"name": "gid", "type": "integer"},
                {"name": "pop", "type": "integer"},
            ],
        )
        yield ds
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
        await test_db_session.commit()

    @pytest.mark.anyio
    async def test_unfiltered_oversized_export_413(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """No filter + feature_count over the cap → 413 without touching the
        data table (no real table exists for this dataset)."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="OversizedDS",
            feature_count=5_000_001,
        )
        resp = await client.get(f"/datasets/{ds.id}/export", headers=admin_auth_header)
        assert resp.status_code == 413
        assert "unfiltered-export limit" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_tautological_where_still_413(
        self, client: AsyncClient, admin_auth_header: dict, capped_dataset
    ):
        """where=1=1 selects every row, so an oversized dataset must still 413.
        This is the codex r8 bypass regression."""
        resp = await client.get(
            f"/datasets/{capped_dataset.id}/export",
            params={"where": "1=1"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 413
        assert "still selects" in resp.json()["detail"]

    @pytest.mark.anyio
    async def test_broad_bbox_still_413(
        self, client: AsyncClient, admin_auth_header: dict, capped_dataset
    ):
        """A bbox covering every feature must not bypass the cap either."""
        resp = await client.get(
            f"/datasets/{capped_dataset.id}/export",
            params={"bbox": "-10,-10,10,10"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 413

    @pytest.mark.anyio
    async def test_selective_where_passes(
        self, client: AsyncClient, admin_auth_header: dict, capped_dataset
    ):
        """A where selecting 1 of 3 rows is under the cap of 2 → 200."""
        resp = await client.get(
            f"/datasets/{capped_dataset.id}/export",
            params={"where": "pop > 25"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_selective_bbox_passes(
        self, client: AsyncClient, admin_auth_header: dict, capped_dataset
    ):
        """A bbox covering 1 of 3 points is under the cap of 2 → 200."""
        resp = await client.get(
            f"/datasets/{capped_dataset.id}/export",
            params={"bbox": "0.5,0.5,1.5,1.5"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_oversized_invalid_where_400(
        self, client: AsyncClient, admin_auth_header: dict, capped_dataset
    ):
        """The count path validates the where fragment BEFORE interpolating it
        into SQL: a disallowed construct is a 400, never executed."""
        resp = await client.get(
            f"/datasets/{capped_dataset.id}/export",
            params={"where": "pg_sleep(1) IS NOT NULL"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400
