"""Integration tests for _ingest_vector_into_staging through both paths.

These tests require a real ogr2ogr binary and a running test PostGIS database.
They exercise the shared helper with real ogr2ogr + real PostGIS to verify
behavioral parity with the pre-refactor ingest_file and reupload_file paths.

Per D-07: integration tests complement the mock-based unit tests in
test_staging_pipeline.py. Mocks verify orchestration; real tests verify the
end-to-end pipeline actually works.

Requirements:
  - Docker database must be running (docker compose up db)
  - ogr2ogr binary available (runs in backend Docker image / CI)
"""

import json
import shutil
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.skipif(
        shutil.which("ogr2ogr") is None,
        reason="ogr2ogr binary not available on host (runs in backend Docker image / CI)",
    ),
    pytest.mark.requires_ogr2ogr,
]

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _table_id(prefix: str) -> str:
    """Generate a collision-safe table name for parallel test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create_test_geojson(tmp_path: Path) -> Path:
    """Create a tiny GeoJSON with 3 point features for integration testing."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-73.9857, 40.7484]},
                "properties": {"name": "Empire State", "height": 443},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-73.9680, 40.7614]},
                "properties": {"name": "Rockefeller", "height": 259},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-74.0445, 40.6892]},
                "properties": {"name": "Statue of Liberty", "height": 93},
            },
        ],
    }
    path = tmp_path / "test_points.geojson"
    path.write_text(json.dumps(geojson))
    return path


def _create_test_csv(tmp_path: Path) -> Path:
    """Create a tiny CSV with no geometry for non-spatial integration testing."""
    path = tmp_path / "test_data.csv"
    path.write_text("id,name,value\n1,alpha,100\n2,beta,200\n3,gamma,300\n")
    return path


# ---------------------------------------------------------------------------
# Helpers — inline session creation
# ---------------------------------------------------------------------------


async def _make_session():
    """Create a session directly in the caller's event loop.

    Using ``db_module.async_session()`` inside the test body (rather than via
    an async fixture) guarantees the underlying asyncpg connection is bound to
    the same event loop that runs the test, avoiding the "Future attached to a
    different loop" error seen with pytest-asyncio + asyncpg in CI.
    """
    import app.core.db as db_module

    return db_module.async_session()


async def _make_job(session, *, filename="test_points.geojson"):
    from app.platform.jobs.models import IngestJob

    job = IngestJob(source_filename=filename, status="running", user_metadata={})
    session.add(job)
    await session.flush()
    return job


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStagingPipelineIntegration:
    """Integration tests exercising _ingest_vector_into_staging with real ogr2ogr."""

    async def test_ingest_path_spatial_geojson(self, tmp_path):
        """Spatial GeoJSON loads through the helper with correct metadata and geom_4326."""
        from app.processing.ingest.ogr import run_ogrinfo
        from app.processing.ingest.tasks import _ingest_vector_into_staging

        file_path = str(_create_test_geojson(tmp_path))
        table_name = _table_id("test_staging")

        info = await run_ogrinfo(file_path)

        async with await _make_session() as session:
            job = await _make_job(session)
            try:
                staging = await _ingest_vector_into_staging(
                    session,
                    job=job,
                    file_path=file_path,
                    target_table=table_name,
                    source_srid=info.get("srid") or 4326,
                    ogr_geometry_type=info.get("geometry_type"),
                    has_geometry=True,
                    effective_srid=4326,
                )

                # --- StagingResult assertions ---
                assert staging.has_geometry is True
                assert staging.geometry_type is not None
                assert staging.metadata["feature_count"] == 3
                assert staging.metadata["geometry_type"] is not None

                col_names = {c["name"] for c in staging.metadata["column_info"]}
                assert "name" in col_names, (
                    f"'name' missing from column_info: {col_names}"
                )
                assert "height" in col_names, (
                    f"'height' missing from column_info: {col_names}"
                )
                assert staging.sample_values  # non-empty dict

                # --- Database assertions ---
                row_count = await session.execute(
                    text(f'SELECT count(*) FROM data."{table_name}"')
                )
                assert row_count.scalar() == 3

                geom_col = await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='data' AND table_name=:t "
                        "AND column_name='geom_4326'"
                    ).bindparams(t=table_name)
                )
                assert geom_col.scalar() == "geom_4326", (
                    "geom_4326 column missing — add_4326_column did not run"
                )

            finally:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
                )
                await session.commit()

    async def test_reupload_path_staging_table(self, tmp_path):
        """Staging table (reupload pattern) is created with correct data."""
        from app.processing.ingest.ogr import run_ogrinfo
        from app.processing.ingest.tasks import _ingest_vector_into_staging

        file_path = str(_create_test_geojson(tmp_path))
        # Reupload-style: staging suffix appended to a base name
        base_name = _table_id("test_reup")
        table_name = f"{base_name}_staging"

        info = await run_ogrinfo(file_path)

        async with await _make_session() as session:
            job = await _make_job(session)
            try:
                staging = await _ingest_vector_into_staging(
                    session,
                    job=job,
                    file_path=file_path,
                    target_table=table_name,
                    source_srid=info.get("srid") or 4326,
                    ogr_geometry_type=info.get("geometry_type"),
                    has_geometry=True,
                    effective_srid=4326,
                )

                # --- StagingResult assertions ---
                assert staging.has_geometry is True
                assert staging.metadata["feature_count"] == 3

                col_names = {c["name"] for c in staging.metadata["column_info"]}
                assert "name" in col_names
                assert "height" in col_names

                # --- Database assertions ---
                row_count = await session.execute(
                    text(f'SELECT count(*) FROM data."{table_name}"')
                )
                assert row_count.scalar() == 3, (
                    f"Expected 3 rows in staging table {table_name!r}"
                )

                # Verify the staging table can be renamed (simulating _apply_reupload_swap)
                final_name = f"{base_name}_final"
                await session.execute(
                    text(f'ALTER TABLE data."{table_name}" RENAME TO "{final_name}"')
                )
                renamed_count = await session.execute(
                    text(f'SELECT count(*) FROM data."{final_name}"')
                )
                assert renamed_count.scalar() == 3

            finally:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
                )
                await session.execute(
                    text(f'DROP TABLE IF EXISTS data."{base_name}_final" CASCADE')
                )
                await session.commit()

    async def test_nonspatial_csv_path(self, tmp_path):
        """Non-spatial CSV loads without geometry columns."""
        from app.processing.ingest.ogr import run_ogrinfo
        from app.processing.ingest.tasks import _ingest_vector_into_staging

        file_path = str(_create_test_csv(tmp_path))
        table_name = _table_id("test_nonspatial")

        _info = await run_ogrinfo(file_path)  # verify ogr2ogr can read the file

        async with await _make_session() as session:
            job = await _make_job(session, filename="test_data.csv")
            try:
                staging = await _ingest_vector_into_staging(
                    session,
                    job=job,
                    file_path=file_path,
                    target_table=table_name,
                    source_srid=None,
                    ogr_geometry_type=None,
                    has_geometry=False,
                    effective_srid=4326,
                )

                # --- StagingResult assertions ---
                assert staging.has_geometry is False
                assert staging.metadata["geometry_type"] is None
                assert staging.metadata["feature_count"] == 3

                col_names = {c["name"] for c in staging.metadata["column_info"]}
                assert "name" in col_names, (
                    f"'name' missing from column_info: {col_names}"
                )
                assert "value" in col_names, (
                    f"'value' missing from column_info: {col_names}"
                )

                # --- Database assertions: NO geom_4326 column ---
                row_count = await session.execute(
                    text(f'SELECT count(*) FROM data."{table_name}"')
                )
                assert row_count.scalar() == 3

                geom_col = await session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='data' AND table_name=:t "
                        "AND column_name='geom_4326'"
                    ).bindparams(t=table_name)
                )
                assert geom_col.scalar() is None, (
                    "geom_4326 column present for non-spatial data — unexpected"
                )

            finally:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
                )
                await session.commit()
