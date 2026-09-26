"""The retention purge keeps an unarchived original's job and staged upload."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
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
