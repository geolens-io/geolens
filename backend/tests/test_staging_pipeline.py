"""Unit tests for _ingest_vector_into_staging shared helper.

Tests verify the orchestration logic (call order, argument passing, branching)
using mocks. These do NOT require a real database — they test that the helper
calls the expected pipeline steps with the correct arguments.

Per D-06: mock-based unit tests verifying the helper's orchestration logic.
"""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_job():
    """Return a minimal job mock with user_metadata support."""
    job = MagicMock()
    job.user_metadata = {}
    return job


def _make_session():
    """Return an async-capable session mock that does NOT expose commit()."""
    session = AsyncMock()
    # Explicitly remove commit so tests can assert it is never called
    del session.commit
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIngestVectorIntoStaging:
    """Mock-based orchestration tests for _ingest_vector_into_staging."""

    @pytest.mark.asyncio
    async def test_calls_run_ogr2ogr_with_correct_args(self):
        """Test 1: run_ogr2ogr is called with target_table, db_conn_str, source_srid,
        geometry_type, and layer_name."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])  # no commit on spec
        job = _make_job()

        with (
            patch("app.ingest.tasks._ingest_vector_into_staging.__wrapped__", None,
                  create=True),
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn") as mock_conn,
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock) as mock_ogr,
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]) as _mock_rename,
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [], "geometry_type": "Point"}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": False}),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            result = await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.geojson",
                target_table="my_table",
                source_srid=4326,
                ogr_geometry_type="Point",
                has_geometry=True,
                effective_srid=4326,
                layer_name="layer1",
            )

        mock_ogr.assert_awaited_once_with(
            "/tmp/data.geojson",
            "my_table",
            "dbconn",
            source_srid=4326,
            geometry_type="Point",
            layer_name="layer1",
        )
        assert result.has_geometry is True

    @pytest.mark.asyncio
    async def test_rename_reserved_columns_appends_warning(self):
        """Test 2: rename_reserved_columns is called; warning appended when renames occur."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()
        renames = [{"original": "geom", "renamed": "geom_src"}]

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=renames) as mock_rename,
            patch("app.ingest.warnings.make_reserved_rename_warning",
                  return_value={"kind": "reserved_rename", "details": []}) as mock_warn,
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [], "geometry_type": "Point"}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": False}),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.shp",
                target_table="my_table",
                source_srid=None,
                ogr_geometry_type="Point",
                has_geometry=True,
                effective_srid=4326,
            )

        mock_rename.assert_awaited_once_with(session, "my_table")
        mock_warn.assert_called_once_with(renames)
        # Warning should be in job.user_metadata["warnings"]
        assert "warnings" in job.user_metadata
        assert len(job.user_metadata["warnings"]) == 1

    @pytest.mark.asyncio
    async def test_dbf_truncation_detection_for_zip(self):
        """Test 3: DBF truncation detection runs when file_path ends with .zip."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()
        preview_cols = [{"name": "longcolumn"}, {"name": "longcolu_1"}]

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.detect_dbf_truncation_collisions",
                  return_value=[{"truncated": "longcolu", "originals": ["longcolumn", "longcolu_1"]}]
                  ) as mock_dbf,
            patch("app.ingest.warnings.make_dbf_truncation_warning",
                  return_value={"kind": "dbf_truncation_collision", "details": []}) as mock_dbf_warn,
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [], "geometry_type": "Point"}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": False}),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.zip",
                target_table="my_table",
                source_srid=None,
                ogr_geometry_type="Point",
                has_geometry=True,
                effective_srid=4326,
                ogrinfo_columns=preview_cols,
            )

        mock_dbf.assert_called_once_with(preview_cols)
        mock_dbf_warn.assert_called_once()

    @pytest.mark.asyncio
    async def test_dbf_truncation_skipped_for_non_zip(self):
        """Test 4: DBF truncation detection is NOT called for non-.zip files."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.detect_dbf_truncation_collisions") as mock_dbf,
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [], "geometry_type": "Point"}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": False}),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.geojson",
                target_table="my_table",
                source_srid=None,
                ogr_geometry_type="Point",
                has_geometry=True,
                effective_srid=4326,
            )

        mock_dbf.assert_not_called()

    @pytest.mark.asyncio
    async def test_geometry_postprocessing_when_has_geometry_true(self):
        """Test 5: ensure_geom_column, clip_to_mercator_bounds, add_4326_column called
        with effective_srid when has_geometry=True."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True) as mock_ensure,
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock) as mock_clip,
            patch("app.ingest.metadata.add_4326_column",
                  new_callable=AsyncMock) as mock_4326,
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [], "geometry_type": "Point"}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": False}),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.geojson",
                target_table="my_table",
                source_srid=None,
                ogr_geometry_type="Point",
                has_geometry=True,
                effective_srid=2263,
            )

        mock_ensure.assert_awaited_once_with(session, "my_table")
        mock_clip.assert_awaited_once_with(session, "my_table")
        mock_4326.assert_awaited_once_with(session, "my_table", 2263)

    @pytest.mark.asyncio
    async def test_geometry_postprocessing_skipped_when_has_geometry_false(self):
        """Test 6: ensure_geom, clip, add_4326 are NOT called when has_geometry=False."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock) as mock_ensure,
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock) as mock_clip,
            patch("app.ingest.metadata.add_4326_column",
                  new_callable=AsyncMock) as mock_4326,
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [], "geometry_type": None}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": False}),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.csv",
                target_table="my_table",
                source_srid=None,
                ogr_geometry_type=None,
                has_geometry=False,
                effective_srid=4326,
            )

        mock_ensure.assert_not_called()
        mock_clip.assert_not_called()
        mock_4326.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_metadata_detect_3d_get_sample_values_called_in_order(self):
        """Test 7: extract_metadata, detect_3d_metadata, get_sample_values called in order."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()
        call_order = []

        async def _extract(*a, **kw):
            call_order.append("extract_metadata")
            return {"column_info": [{"name": "id"}], "geometry_type": "Point"}

        async def _detect_3d(*a, **kw):
            call_order.append("detect_3d_metadata")
            return {"is_3d": False}

        async def _sample(*a, **kw):
            call_order.append("get_sample_values")
            return {}

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata", side_effect=_extract),
            patch("app.ingest.metadata.detect_3d_metadata", side_effect=_detect_3d),
            patch("app.ingest.metadata.get_sample_values", side_effect=_sample),
        ):
            await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.geojson",
                target_table="my_table",
                source_srid=4326,
                ogr_geometry_type="Point",
                has_geometry=True,
                effective_srid=4326,
            )

        assert call_order == ["extract_metadata", "detect_3d_metadata", "get_sample_values"]

    @pytest.mark.asyncio
    async def test_promote_z_to_elev_and_refetch_column_info_when_3d(self):
        """Test 8: When 3D detected and promote_z_to_elev returns True,
        get_column_info is called to refresh column_info in metadata."""
        from app.ingest.tasks import _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()
        new_columns = [{"name": "id"}, {"name": "elev"}]

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [{"name": "id"}], "geometry_type": "Point Z"}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": True}),
            patch("app.ingest.metadata.promote_z_to_elev",
                  new_callable=AsyncMock, return_value=True) as mock_promote,
            patch("app.ingest.metadata.get_column_info",
                  new_callable=AsyncMock, return_value=new_columns) as mock_col_info,
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            result = await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.geojson",
                target_table="my_table",
                source_srid=4326,
                ogr_geometry_type="Point Z",
                has_geometry=True,
                effective_srid=4326,
            )

        mock_promote.assert_awaited_once_with(session, "my_table", "Point Z")
        mock_col_info.assert_awaited_once_with(session, "my_table")
        assert result.metadata["column_info"] == new_columns

    @pytest.mark.asyncio
    async def test_returns_staging_result_with_correct_fields(self):
        """Test 9: StagingResult is returned with metadata, sample_values, three_d dicts."""
        from app.ingest.tasks import StagingResult, _ingest_vector_into_staging

        session = AsyncMock(spec=[])
        job = _make_job()
        expected_meta = {"column_info": [], "geometry_type": "Polygon", "srid": 4326}
        expected_samples = {"name": ["Alice", "Bob"]}
        expected_3d = {"is_3d": False, "n_dims": 2}

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock, return_value=expected_meta),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value=expected_3d),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value=expected_samples),
        ):
            result = await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.geojson",
                target_table="my_table",
                source_srid=4326,
                ogr_geometry_type="Polygon",
                has_geometry=True,
                effective_srid=4326,
            )

        assert isinstance(result, StagingResult)
        assert result.metadata is expected_meta
        assert result.sample_values is expected_samples
        assert result.three_d is expected_3d
        assert result.has_geometry is True
        assert result.geometry_type == "Polygon"

    @pytest.mark.asyncio
    async def test_session_commit_never_called(self):
        """Test 10: session.commit() is never called inside the helper (D-10)."""
        from app.ingest.tasks import _ingest_vector_into_staging

        # Build a session that tracks all method calls
        session = AsyncMock()
        job = _make_job()

        with (
            patch("app.ingest.ogr.build_pg_conn_str", return_value="dbconn"),
            patch("app.ingest.ogr.run_ogr2ogr", new_callable=AsyncMock),
            patch("app.ingest.metadata.rename_reserved_columns",
                  new_callable=AsyncMock, return_value=[]),
            patch("app.ingest.metadata.ensure_geom_column",
                  new_callable=AsyncMock, return_value=True),
            patch("app.ingest.metadata.clip_to_mercator_bounds",
                  new_callable=AsyncMock),
            patch("app.ingest.metadata.add_4326_column", new_callable=AsyncMock),
            patch("app.ingest.metadata.grant_reader_access", new_callable=AsyncMock),
            patch("app.ingest.metadata.extract_metadata",
                  new_callable=AsyncMock,
                  return_value={"column_info": [], "geometry_type": "Point"}),
            patch("app.ingest.metadata.detect_3d_metadata",
                  new_callable=AsyncMock, return_value={"is_3d": False}),
            patch("app.ingest.metadata.get_sample_values",
                  new_callable=AsyncMock, return_value={}),
        ):
            await _ingest_vector_into_staging(
                session,
                job=job,
                file_path="/tmp/data.geojson",
                target_table="my_table",
                source_srid=4326,
                ogr_geometry_type="Point",
                has_geometry=True,
                effective_srid=4326,
            )

        session.commit.assert_not_called()
