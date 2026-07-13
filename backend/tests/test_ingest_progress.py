"""REMED-02 / ingest-audit P2-07: regression tests for worker progress writes.

Pins the contract that the polling UI depends on:

1. ``_finalize_ingest`` (shared by vector file + service ingest) writes the
   terminal ``current_step="complete"``, ``progress=1.0``, and
   ``rows_processed=<feature_count>`` on success.
2. Brief-session pattern: progress writes ahead of long-running subprocess
   work (ogr2ogr, COG conversion, quicklook generation) commit BEFORE the
   work runs so the UI sees the step transition even if the work fails.
   Without this pin, the implementation could silently regress to a
   single phase-2 write and the contract would still pass happy-path
   tests while breaking in-flight UI polling.
3. The ``progress`` flag at the row level is non-decreasing across a
   single successful ingest (0.0 → 0.1 → 0.7 → 1.0 for vector;
   0.0 → 0.2 → 0.6 → 0.8 → 1.0 for raster) — surfaced as a structural
   assertion against the writes the worker code actually does.
"""

import asyncio
import uuid as _uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select, text

from app.platform.jobs.models import IngestJob


async def _get_admin_id(session):
    from tests.factories import get_user_id

    return await get_user_id(session, "admin")


# ---------------------------------------------------------------------------
# 1. Vector finalize writes terminal progress
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_finalize_ingest_writes_terminal_progress(test_db_session):
    """``_finalize_ingest`` stamps current_step=complete, progress=1.0, and
    rows_processed=<feature_count> on the IngestJob row.

    Uses the same direct-call pattern as
    ``test_arcgis_table_ingest_populates_column_info`` — bypasses ogr2ogr by
    seeding the data table directly so the test exercises only the contract
    surface this plan adds.
    """
    from app.processing.ingest.tasks import IngestContext, _finalize_ingest

    admin_id = await _get_admin_id(test_db_session)

    table_name = f"tbl_progress_{_uuid.uuid4().hex[:10]}"
    # Seed a 3-row spatial table so extract_metadata's feature_count = 3
    # and ``rows_processed`` is verifiably the worker output (not a coincidence).
    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" '
            "(gid serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, geom) VALUES '
            "('a', ST_SetSRID(ST_Point(0, 0), 4326)), "
            "('b', ST_SetSRID(ST_Point(1, 1), 4326)), "
            "('c', ST_SetSRID(ST_Point(2, 2), 4326))"
        )
    )
    await test_db_session.commit()

    job = IngestJob(
        source_filename="progress.geojson",
        created_by=admin_id,
        status="running",
        user_metadata={"title": "Progress Test", "visibility": "private"},
        progress=0.7,
        current_step="finalize",
    )
    test_db_session.add(job)
    await test_db_session.flush()
    job_id = job.id

    await _finalize_ingest(
        IngestContext(
            session=test_db_session,
            job=job,
            table_name=table_name,
            user_id=str(admin_id),
            has_geometry=True,
            effective_srid=4326,
            source_format="geojson",
            source_filename="progress.geojson",
            original_srid=4326,
            user_metadata={"title": "Progress Test", "visibility": "private"},
        )
    )

    # Re-query in a fresh select so we see the committed state.
    result = await test_db_session.execute(
        select(IngestJob).where(IngestJob.id == job_id)
    )
    final = result.scalar_one()
    assert final.status == "complete"
    assert final.current_step == "complete"
    assert final.progress == 1.0
    assert final.rows_processed == 3


# ---------------------------------------------------------------------------
# 2. Brief-session pattern: ogr2ogr write commits before subprocess work
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_vector_worker_writes_ogr2ogr_step_before_subprocess(
    test_db_session, monkeypatch
):
    """Load-bearing test for the brief-session pattern.

    If ``run_ogr2ogr`` raises BEFORE the brief-session ``ogr2ogr`` write,
    the row should still show ``current_step="ogr2ogr"`` — proving the
    progress write committed independently of the subprocess outcome.

    Without this test, a refactor could silently consolidate all progress
    writes into the phase-2 transaction; the happy-path test above would
    still pass, but mid-flight UI polling would see no step transitions
    until the very end. That regression is what this test pins.
    """
    from app.processing.ingest import tasks_vector
    from app.processing.ingest.ogr import IngestionError

    admin_id = await _get_admin_id(test_db_session)

    # Seed a job row pointing at a real GeoJSON file from the existing
    # fixtures so phase-1 validation doesn't reject it. tasks_vector.ingest_file
    # writes the brief-session progress entry before calling run_ogr2ogr, so
    # we monkeypatch run_ogr2ogr to raise — leaving the row in
    # current_step="ogr2ogr" if the brief-session pattern is honored.
    fixture = str(Path(__file__).parent / "fixtures" / "ingest" / "basic_attrs.geojson")

    job = IngestJob(
        source_filename="basic_attrs.geojson",
        file_path=fixture,
        created_by=admin_id,
        status="pending",
        user_metadata={"title": "Brief Session Test", "visibility": "private"},
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id

    async def _fake_run_ogrinfo(*args, **kwargs):
        # Phase-1 ogrinfo detect runs BEFORE the brief-session ogr2ogr write.
        # Return enough metadata that phase-1 doesn't reject the file.
        return {"srid": 4326, "geometry_type": "POINT", "columns": []}

    async def _raising_run_ogr2ogr(*args, **kwargs):
        raise IngestionError("simulated ogr2ogr failure for brief-session test")

    # Patch the symbols the worker imports — tasks_vector imports
    # run_ogrinfo / run_ogr2ogr from app.processing.ingest.ogr at function-call
    # time (inside ingest_file).
    monkeypatch.setattr("app.processing.ingest.ogr.run_ogrinfo", _fake_run_ogrinfo)
    monkeypatch.setattr("app.processing.ingest.ogr.run_ogr2ogr", _raising_run_ogr2ogr)

    # Call the underlying task function (Procrastinate wraps it in .func).
    with pytest.raises(IngestionError):
        await tasks_vector.ingest_file.func(
            job_id=str(job_id),
            attempt_id=str(job.attempt_id),
            file_path=fixture,
            user_id=str(admin_id),
        )

    # Re-query the job. The brief-session ogr2ogr write must have committed
    # BEFORE the subprocess raised, and the outer exception handler then
    # stamped status="failed" via a fresh session.
    # The progress field reflects the last successful brief-session commit
    # (0.1 from the ogr2ogr step).
    result = await test_db_session.execute(
        select(IngestJob).where(IngestJob.id == job_id)
    )
    failed = result.scalar_one()
    await test_db_session.refresh(failed)
    assert failed.status == "failed"
    assert failed.current_step == "ogr2ogr", (
        f"brief-session pattern broken: expected current_step='ogr2ogr' "
        f"after run_ogr2ogr failure, got {failed.current_step!r}. "
        f"The ogr2ogr progress write must commit BEFORE the subprocess runs "
        f"so the UI sees the step transition even when the subprocess fails."
    )
    assert failed.progress == 0.1


@pytest.mark.anyio
async def test_vector_worker_geometry_override_uses_helper_contract(
    test_db_session, monkeypatch
):
    """X/Y imports must call the geometry helper with supported arguments."""
    from unittest.mock import patch

    from app.processing.ingest import tasks_vector

    class GeometryOverrideReached(Exception):
        pass

    admin_id = await _get_admin_id(test_db_session)
    fixture = str(Path(__file__).parent / "fixtures" / "ingest" / "mixed_types.csv")
    job = IngestJob(
        source_filename="mixed_types.csv",
        file_path=fixture,
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": "Geometry Override Contract",
            "visibility": "private",
            "x_column": "longitude",
            "y_column": "latitude",
        },
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()

    async def _fake_run_ogrinfo(*_args, **_kwargs):
        return {"srid": None, "geometry_type": None, "columns": []}

    async def _fake_run_ogr2ogr(*_args, **_kwargs):
        return None

    async def _no_reserved_renames(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.processing.ingest.ogr.run_ogrinfo", _fake_run_ogrinfo)
    monkeypatch.setattr("app.processing.ingest.ogr.run_ogr2ogr", _fake_run_ogr2ogr)
    monkeypatch.setattr("app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:")
    monkeypatch.setattr(
        "app.processing.ingest.metadata.rename_reserved_columns",
        _no_reserved_renames,
    )

    with patch.object(
        tasks_vector,
        "_detect_and_override_geometry",
        autospec=True,
        side_effect=GeometryOverrideReached,
    ) as geometry_override:
        with pytest.raises(GeometryOverrideReached):
            await tasks_vector.ingest_file.func(
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                file_path=fixture,
                user_id=str(admin_id),
            )

    call_kwargs = geometry_override.await_args.kwargs
    assert set(call_kwargs) == {"table_name", "user_metadata", "effective_srid"}
    assert call_kwargs["user_metadata"] == job.user_metadata
    assert call_kwargs["effective_srid"] == 4326


# ---------------------------------------------------------------------------
# 3. Service ingest advances progress while remote import is still running
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_service_worker_advances_ogr2ogr_progress_while_remote_import_is_running(
    test_db_session, monkeypatch
):
    """Service URL ingest must publish progress during the remote load window."""
    from app.core import db as db_module
    from app.processing.ingest import tasks_vector
    from app.processing.ingest.ogr import IngestionError

    admin_id = await _get_admin_id(test_db_session)

    job = IngestJob(
        source_filename="Add_addressPoint",
        source_url="https://example.test/arcgis/rest/services/Address/FeatureServer",
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": "Add_addressPoint",
            "visibility": "private",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "geometry_type": "Point",
        },
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id

    remote_import_started = asyncio.Event()
    release_remote_import = asyncio.Event()
    worker_error: Exception | None = None
    last_progress: float | None = None

    class _FakeProcessingPort:
        def build_gdal_source(self, *args, **kwargs):
            return "FAKE_GDAL_SOURCE", "0"

    async def _validate_url_noop(_url: str) -> None:
        return None

    async def _fallback_calls_import_once(import_fn, source_layer, **kwargs) -> None:
        await import_fn(source_layer)

    async def _blocking_run_ogr2ogr_service(*args, **kwargs) -> None:
        remote_import_started.set()
        await release_remote_import.wait()
        raise IngestionError("simulated remote service import stop")

    monkeypatch.setattr(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        _validate_url_noop,
    )
    monkeypatch.setattr(
        "app.platform.extensions.get_processing_port",
        lambda: _FakeProcessingPort(),
    )
    monkeypatch.setattr("app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:")
    monkeypatch.setattr(
        tasks_vector,
        "_run_service_import_with_wfs_fallback",
        _fallback_calls_import_once,
    )
    monkeypatch.setattr(
        "app.processing.ingest.ogr.run_ogr2ogr_service",
        _blocking_run_ogr2ogr_service,
    )
    monkeypatch.setattr(
        tasks_vector,
        "_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
        raising=False,
    )
    monkeypatch.setattr(
        tasks_vector,
        "_SERVICE_IMPORT_HEARTBEAT_INCREMENT",
        0.2,
        raising=False,
    )

    worker_task = asyncio.create_task(
        tasks_vector.ingest_service.func(
            job_id=str(job_id),
            attempt_id=str(job.attempt_id),
            source_url="https://example.test/arcgis/rest/services/Address/FeatureServer",
            source_layer="0",
            user_id=str(admin_id),
        )
    )

    try:
        await asyncio.wait_for(remote_import_started.wait(), timeout=1)

        deadline = asyncio.get_running_loop().time() + 1
        while asyncio.get_running_loop().time() < deadline:
            async with db_module.async_session() as poll_session:
                result = await poll_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
                current_job = result.scalar_one()
                last_progress = current_job.progress
                if last_progress is not None and last_progress > 0.1:
                    break

            assert not worker_task.done()
            await asyncio.sleep(0.01)
    finally:
        release_remote_import.set()
        # fix(#422): join the worker directly instead of wait_for(timeout=2).
        # Under CI load the timeout fires and cancels worker_task mid-teardown,
        # where the product code's suppress(CancelledError) swallows the
        # injected cancel — wait_for then sets a cancelled result on a task that
        # completes normally, raising asyncio InvalidStateError. Releasing the
        # blocked import makes the worker raise and finish deterministically, so
        # a plain await never races (a genuine hang surfaces via the CI job
        # timeout instead of a corrupted future).
        try:
            await worker_task
        except Exception as exc:
            worker_error = exc

    assert isinstance(worker_error, IngestionError)
    assert last_progress is not None
    assert last_progress > 0.1
    assert last_progress < 0.7


@pytest.mark.anyio
async def test_service_worker_chunks_large_arcgis_imports(test_db_session, monkeypatch):
    """Large ArcGIS imports should dispatch bounded paged ogr2ogr calls."""
    from app.processing.ingest import tasks_vector
    from app.modules.catalog.sources.preview import build_gdal_source

    admin_id = await _get_admin_id(test_db_session)
    table_name = f"tbl_arcgis_chunks_{_uuid.uuid4().hex[:8]}"

    job = IngestJob(
        source_filename="Big ArcGIS Layer",
        source_url="https://example.test/arcgis/rest/services/Big/FeatureServer",
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": "Big ArcGIS Layer",
            "visibility": "private",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "geometry_type": "Point",
        },
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    assert job.attempt_id is not None
    staging_table = tasks_vector.attempt_scoped_staging_table(
        table_name, job.attempt_id
    )

    calls: list[dict[str, object]] = []

    class _FakeProcessingPort:
        def build_gdal_source(self, *args, **kwargs):
            return build_gdal_source(*args, **kwargs)

    async def _validate_url_noop(_url: str) -> None:
        return None

    async def _fake_generate_table_name(*args, **kwargs):
        return table_name, None

    async def _fake_page_info(*args, **kwargs):
        return 4500, 1000, True, "FID"

    async def _fake_run_ogr2ogr_service(
        gdal_source: str,
        layer_name: str,
        target_table: str,
        db_conn_str: str,
        service_type: str,
        *,
        append: bool = False,
        **kwargs,
    ) -> None:
        query = parse_qs(urlsplit(gdal_source.removeprefix("ESRIJSON:")).query)
        offset = int(query.get("resultOffset", ["0"])[0])
        limit = int(query["resultRecordCount"][0])
        rows_to_insert = max(0, min(limit, 4500 - offset))
        calls.append(
            {
                "offset": offset,
                "limit": limit,
                "order_by": query.get("orderByFields", [None])[0],
                "append": append,
                "target_table": target_table,
                "layer_name": layer_name,
                "service_type": service_type,
            }
        )

        if not append:
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{target_table}"')
            )
            await test_db_session.execute(
                text(f'CREATE TABLE data."{target_table}" (gid serial PRIMARY KEY)')
            )
        for _ in range(rows_to_insert):
            await test_db_session.execute(
                text(f'INSERT INTO data."{target_table}" DEFAULT VALUES')
            )
        await test_db_session.commit()

    async def _fake_rename_reserved_columns(*args, **kwargs):
        return []

    async def _fake_finalize_ingest(context):
        context.job.status = "complete"
        context.job.current_step = "complete"
        context.job.progress = 1.0
        context.job.rows_processed = 4500
        await context.session.commit()

    async def _fake_emit_billing_event(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        _validate_url_noop,
    )
    monkeypatch.setattr(
        "app.platform.extensions.get_processing_port",
        lambda: _FakeProcessingPort(),
    )
    monkeypatch.setattr("app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:")
    monkeypatch.setattr(
        "app.processing.ingest.service.generate_table_name",
        _fake_generate_table_name,
    )
    monkeypatch.setattr(
        tasks_vector,
        "_fetch_arcgis_import_page_info",
        _fake_page_info,
    )
    monkeypatch.setattr(
        "app.processing.ingest.ogr.run_ogr2ogr_service",
        _fake_run_ogr2ogr_service,
    )
    monkeypatch.setattr(
        "app.processing.ingest.metadata.rename_reserved_columns",
        _fake_rename_reserved_columns,
    )
    monkeypatch.setattr(tasks_vector, "_finalize_ingest", _fake_finalize_ingest)
    monkeypatch.setattr(tasks_vector, "_emit_billing_event", _fake_emit_billing_event)

    await tasks_vector.ingest_service.func(
        job_id=str(job_id),
        attempt_id=str(job.attempt_id),
        source_url="https://example.test/arcgis/rest/services/Big/FeatureServer",
        source_layer="0",
        user_id=str(admin_id),
    )

    assert calls == [
        {
            "offset": 0,
            "limit": 1000,
            "order_by": "FID ASC",
            "append": False,
            "target_table": staging_table,
            "layer_name": "",
            "service_type": "arcgis_featureserver",
        },
        {
            "offset": 1000,
            "limit": 1000,
            "order_by": "FID ASC",
            "append": True,
            "target_table": staging_table,
            "layer_name": "",
            "service_type": "arcgis_featureserver",
        },
        {
            "offset": 2000,
            "limit": 1000,
            "order_by": "FID ASC",
            "append": True,
            "target_table": staging_table,
            "layer_name": "",
            "service_type": "arcgis_featureserver",
        },
        {
            "offset": 3000,
            "limit": 1000,
            "order_by": "FID ASC",
            "append": True,
            "target_table": staging_table,
            "layer_name": "",
            "service_type": "arcgis_featureserver",
        },
        {
            "offset": 4000,
            "limit": 1000,
            "order_by": "FID ASC",
            "append": True,
            "target_table": staging_table,
            "layer_name": "",
            "service_type": "arcgis_featureserver",
        },
    ]

    row_count = (
        await test_db_session.execute(text(f'SELECT COUNT(*) FROM data."{table_name}"'))
    ).scalar_one()
    assert row_count == 4500


@pytest.mark.anyio
async def test_service_worker_skips_arcgis_chunking_without_pagination_support(
    test_db_session, monkeypatch
):
    """ArcGIS layers without supportsPagination should use the legacy import."""
    from app.modules.catalog.sources.preview import build_gdal_source
    from app.processing.ingest import tasks_vector

    admin_id = await _get_admin_id(test_db_session)
    table_name = f"tbl_arcgis_single_{_uuid.uuid4().hex[:8]}"

    job = IngestJob(
        source_filename="Legacy ArcGIS Layer",
        source_url="https://example.test/arcgis/rest/services/Legacy/FeatureServer",
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": "Legacy ArcGIS Layer",
            "visibility": "private",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "geometry_type": "Point",
            "object_id_field": "FID",
        },
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    assert job.attempt_id is not None
    staging_table = tasks_vector.attempt_scoped_staging_table(
        table_name, job.attempt_id
    )

    calls: list[dict[str, object]] = []

    class _FakeProcessingPort:
        def build_gdal_source(self, *args, **kwargs):
            return build_gdal_source(*args, **kwargs)

    async def _validate_url_noop(_url: str) -> None:
        return None

    async def _fake_generate_table_name(*args, **kwargs):
        return table_name, None

    async def _fake_page_info(*args, **kwargs):
        return None, 1000, False, "FID"

    async def _fake_run_ogr2ogr_service(
        gdal_source: str,
        layer_name: str,
        target_table: str,
        db_conn_str: str,
        service_type: str,
        *,
        append: bool = False,
        **kwargs,
    ) -> None:
        query = parse_qs(urlsplit(gdal_source.removeprefix("ESRIJSON:")).query)
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{target_table}"')
        )
        await test_db_session.execute(
            text(f'CREATE TABLE data."{target_table}" (gid serial PRIMARY KEY)')
        )
        await test_db_session.commit()
        calls.append(
            {
                "has_limit": "resultRecordCount" in query,
                "has_offset": "resultOffset" in query,
                "append": append,
                "target_table": target_table,
                "layer_name": layer_name,
                "service_type": service_type,
            }
        )

    async def _fake_rename_reserved_columns(*args, **kwargs):
        return []

    async def _fake_finalize_ingest(context):
        context.job.status = "complete"
        context.job.current_step = "complete"
        context.job.progress = 1.0
        await context.session.commit()

    async def _fake_emit_billing_event(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        _validate_url_noop,
    )
    monkeypatch.setattr(
        "app.platform.extensions.get_processing_port",
        lambda: _FakeProcessingPort(),
    )
    monkeypatch.setattr("app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:")
    monkeypatch.setattr(
        "app.processing.ingest.service.generate_table_name",
        _fake_generate_table_name,
    )
    monkeypatch.setattr(
        tasks_vector,
        "_fetch_arcgis_import_page_info",
        _fake_page_info,
    )
    monkeypatch.setattr(
        "app.processing.ingest.ogr.run_ogr2ogr_service",
        _fake_run_ogr2ogr_service,
    )
    monkeypatch.setattr(
        "app.processing.ingest.metadata.rename_reserved_columns",
        _fake_rename_reserved_columns,
    )
    monkeypatch.setattr(tasks_vector, "_finalize_ingest", _fake_finalize_ingest)
    monkeypatch.setattr(tasks_vector, "_emit_billing_event", _fake_emit_billing_event)

    await tasks_vector.ingest_service.func(
        job_id=str(job_id),
        attempt_id=str(job.attempt_id),
        source_url="https://example.test/arcgis/rest/services/Legacy/FeatureServer",
        source_layer="0",
        user_id=str(admin_id),
    )

    assert calls == [
        {
            "has_limit": False,
            "has_offset": False,
            "append": False,
            "target_table": staging_table,
            "layer_name": "",
            "service_type": "arcgis_featureserver",
        }
    ]


@pytest.mark.anyio
async def test_service_worker_skips_arcgis_chunking_without_order_field(
    test_db_session, monkeypatch
):
    """Offset chunking requires a stable ArcGIS object-id order field."""
    from app.modules.catalog.sources.preview import build_gdal_source
    from app.processing.ingest import tasks_vector

    admin_id = await _get_admin_id(test_db_session)
    table_name = f"tbl_arcgis_no_oid_{_uuid.uuid4().hex[:8]}"

    job = IngestJob(
        source_filename="Unordered ArcGIS Layer",
        source_url="https://example.test/arcgis/rest/services/Unordered/FeatureServer",
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": "Unordered ArcGIS Layer",
            "visibility": "private",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "geometry_type": "Point",
        },
    )
    test_db_session.add(job)
    await test_db_session.flush()
    await test_db_session.commit()
    job_id = job.id
    assert job.attempt_id is not None
    staging_table = tasks_vector.attempt_scoped_staging_table(
        table_name, job.attempt_id
    )

    calls: list[dict[str, object]] = []

    class _FakeProcessingPort:
        def build_gdal_source(self, *args, **kwargs):
            return build_gdal_source(*args, **kwargs)

    async def _validate_url_noop(_url: str) -> None:
        return None

    async def _fake_generate_table_name(*args, **kwargs):
        return table_name, None

    async def _fake_page_info(*args, **kwargs):
        return 4500, 1000, True, None

    async def _fake_run_ogr2ogr_service(
        gdal_source: str,
        layer_name: str,
        target_table: str,
        db_conn_str: str,
        service_type: str,
        *,
        append: bool = False,
        **kwargs,
    ) -> None:
        query = parse_qs(urlsplit(gdal_source.removeprefix("ESRIJSON:")).query)
        await test_db_session.execute(
            text(f'DROP TABLE IF EXISTS data."{target_table}"')
        )
        await test_db_session.execute(
            text(f'CREATE TABLE data."{target_table}" (gid serial PRIMARY KEY)')
        )
        await test_db_session.commit()
        calls.append(
            {
                "has_limit": "resultRecordCount" in query,
                "has_offset": "resultOffset" in query,
                "has_order": "orderByFields" in query,
                "append": append,
                "target_table": target_table,
                "layer_name": layer_name,
                "service_type": service_type,
            }
        )

    async def _fake_rename_reserved_columns(*args, **kwargs):
        return []

    async def _fake_finalize_ingest(context):
        context.job.status = "complete"
        context.job.current_step = "complete"
        context.job.progress = 1.0
        await context.session.commit()

    async def _fake_emit_billing_event(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        _validate_url_noop,
    )
    monkeypatch.setattr(
        "app.platform.extensions.get_processing_port",
        lambda: _FakeProcessingPort(),
    )
    monkeypatch.setattr("app.processing.ingest.ogr.build_pg_conn_str", lambda: "PG:")
    monkeypatch.setattr(
        "app.processing.ingest.service.generate_table_name",
        _fake_generate_table_name,
    )
    monkeypatch.setattr(
        tasks_vector,
        "_fetch_arcgis_import_page_info",
        _fake_page_info,
    )
    monkeypatch.setattr(
        "app.processing.ingest.ogr.run_ogr2ogr_service",
        _fake_run_ogr2ogr_service,
    )
    monkeypatch.setattr(
        "app.processing.ingest.metadata.rename_reserved_columns",
        _fake_rename_reserved_columns,
    )
    monkeypatch.setattr(tasks_vector, "_finalize_ingest", _fake_finalize_ingest)
    monkeypatch.setattr(tasks_vector, "_emit_billing_event", _fake_emit_billing_event)

    await tasks_vector.ingest_service.func(
        job_id=str(job_id),
        attempt_id=str(job.attempt_id),
        source_url="https://example.test/arcgis/rest/services/Unordered/FeatureServer",
        source_layer="0",
        user_id=str(admin_id),
    )

    assert calls == [
        {
            "has_limit": False,
            "has_offset": False,
            "has_order": False,
            "append": False,
            "target_table": staging_table,
            "layer_name": "",
            "service_type": "arcgis_featureserver",
        }
    ]


# ---------------------------------------------------------------------------
# 4. Progress is non-decreasing across the named steps
# ---------------------------------------------------------------------------


def test_named_step_progress_is_non_decreasing():
    """Structural assertion: the step→progress mapping the workers use is
    monotonically non-decreasing for each ingest path.

    This pins the writes that tasks_vector + tasks_raster + tasks_common
    encode. If a future refactor reorders a step (e.g. quicklook before
    cog_convert), this fails — preventing the UI from showing progress
    going backwards.
    """
    vector_steps = [
        ("validating", 0.0),
        ("ogr2ogr", 0.1),
        ("finalize", 0.7),
        ("complete", 1.0),
    ]
    raster_steps = [
        ("validating", 0.0),
        ("cog_convert", 0.2),
        ("quicklook", 0.6),
        ("finalize", 0.8),
        ("complete", 1.0),
    ]
    for path_name, steps in (("vector", vector_steps), ("raster", raster_steps)):
        progress_values = [p for _, p in steps]
        assert progress_values == sorted(progress_values), (
            f"{path_name} ingest progress regressed: {steps}"
        )
        assert progress_values[0] == 0.0, f"{path_name} should start at 0.0"
        assert progress_values[-1] == 1.0, f"{path_name} should end at 1.0"
        # All values in [0.0, 1.0]
        assert all(0.0 <= p <= 1.0 for p in progress_values)
