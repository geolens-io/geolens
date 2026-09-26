"""The purge keeps the job and upload of a published original that never archived."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import fail_stale_jobs
from tests.factories import create_dataset, get_user_id


@pytest.mark.parametrize(
    "archive_failed", [True, False], ids=["unarchived", "archived"]
)
async def test_the_purge_keeps_an_unarchived_original_and_its_upload(
    test_db_session, tmp_path, monkeypatch, archive_failed
):
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
    user_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=user_id, name="Unarchived original"
    )
    upload = tmp_path / "replacement.geojson"
    upload.write_text("{}")
    shared_upload = tmp_path / "layers.gpkg"
    shared_upload.write_text("{}")

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=90)
    metadata = {"archive_failed": True} if archive_failed else None
    rows = {
        # A replacement, superseded by the dataset's latest job below.
        "replacement": IngestJob(
            dataset_id=dataset.id,
            status="complete",
            created_at=old,
            completed_at=old,
            file_path=str(upload),
            user_metadata=metadata,
        ),
        # A fan-out parent and one of its layers, which name the same upload.
        "layer": IngestJob(
            dataset_id=dataset.id,
            status="complete",
            created_at=old,
            completed_at=old,
            file_path=str(shared_upload),
            user_metadata=metadata,
        ),
        "parent": IngestJob(
            dataset_id=None,
            status="fanned_out",
            created_at=old,
            completed_at=old,
            file_path=str(shared_upload),
        ),
        "latest": IngestJob(
            dataset_id=dataset.id,
            status="complete",
            created_at=now - timedelta(days=1),
        ),
    }
    test_db_session.add_all(rows.values())
    await test_db_session.commit()
    ids = {name: row.id for name, row in rows.items()}

    await fail_stale_jobs(test_db_session)

    remaining = set(
        (
            await test_db_session.execute(
                select(IngestJob.id).where(IngestJob.id.in_(ids.values()))
            )
        ).scalars()
    )
    assert ids["latest"] in remaining
    assert ids["parent"] not in remaining
    assert (ids["replacement"] in remaining) is archive_failed
    assert upload.exists() is archive_failed
    assert (ids["layer"] in remaining) is archive_failed
    assert shared_upload.exists() is archive_failed, (
        "the purged parent's path is also the kept layer's only copy"
        if archive_failed
        else "an archived upload goes with its purged rows"
    )


@pytest.mark.parametrize(
    ("status", "delete_dataset"),
    [("complete", True), ("failed", False)],
    ids=["dataset_deleted", "failed"],
)
async def test_the_purge_takes_a_flagged_job_with_no_live_version(
    test_db_session, tmp_path, monkeypatch, status, delete_dataset
):
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 30)
    user_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=user_id, name="No live version"
    )
    upload = tmp_path / "unarchived.geojson"
    upload.write_text("{}")
    old = datetime.now(timezone.utc) - timedelta(days=90)
    job = IngestJob(
        dataset_id=dataset.id,
        status=status,
        created_at=old,
        completed_at=old,
        file_path=str(upload),
        user_metadata={"archive_failed": True},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id = job.id
    if delete_dataset:
        await test_db_session.execute(delete(Dataset).where(Dataset.id == dataset.id))
        await test_db_session.commit()

    await fail_stale_jobs(test_db_session)

    kept = await test_db_session.scalar(
        select(IngestJob.id).where(IngestJob.id == job_id)
    )
    assert kept is None
    assert not upload.exists()
