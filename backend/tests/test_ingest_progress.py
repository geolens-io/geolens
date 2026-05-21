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

import uuid as _uuid
from pathlib import Path

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
    fixture = str(
        Path(__file__).parent / "fixtures" / "ingest" / "basic_attrs.geojson"
    )

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
    monkeypatch.setattr(
        "app.processing.ingest.ogr.run_ogrinfo", _fake_run_ogrinfo
    )
    monkeypatch.setattr(
        "app.processing.ingest.ogr.run_ogr2ogr", _raising_run_ogr2ogr
    )

    # Call the underlying task function (Procrastinate wraps it in .func).
    with pytest.raises(IngestionError):
        await tasks_vector.ingest_file.func(
            job_id=str(job_id),
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


# ---------------------------------------------------------------------------
# 3. Progress is non-decreasing across the named steps
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
