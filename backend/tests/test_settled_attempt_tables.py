"""The stale sweep drops a settled attempt's staging table and no other table."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.attempt_tables import reap_settled_attempt_tables
from app.platform.jobs.heartbeat import (
    attempt_scoped_staging_table,
    previous_version_table,
)
from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS
from tests.factories import create_dataset, get_user_id
from tests.stale_settlers import STALE_SETTLERS

pytestmark = pytest.mark.anyio


def _base() -> str:
    return f"orphan_{uuid.uuid4().hex[:8]}"


async def _job(session: AsyncSession, status: str, **columns) -> IngestJob:
    job = IngestJob(
        status=status,
        source_filename="orphan.geojson",
        attempt_id=uuid.uuid4(),
        **columns,
    )
    session.add(job)
    await session.commit()
    return job


async def _table(session: AsyncSession, name: str) -> str:
    await session.execute(text(f'CREATE TABLE data."{name}" (gid serial, name text)'))
    await session.execute(text(f"INSERT INTO data.\"{name}\" (name) VALUES ('a')"))
    await session.commit()
    return name


async def _exists(session: AsyncSession, name: str) -> bool:
    found = await session.scalar(
        text("SELECT to_regclass(:name)"), {"name": f'data."{name}"'}
    )
    await session.commit()
    return found is not None


async def _drop(session: AsyncSession, *names: str) -> None:
    for name in names:
        await session.execute(text(f'DROP TABLE IF EXISTS data."{name}" CASCADE'))
    await session.commit()


@STALE_SETTLERS
async def test_a_lost_workers_staging_table_goes_with_its_settlement(
    test_db_session, settle
) -> None:
    """A worker killed mid-copy leaves a table the pass that settles it drops."""
    job = await _job(
        test_db_session,
        "running",
        started_at=datetime.now(timezone.utc)
        - timedelta(seconds=JOB_TIMEOUT_SECONDS + 60),
    )
    staging = await _table(
        test_db_session, attempt_scoped_staging_table(_base(), job.attempt_id)
    )

    await settle(test_db_session)

    await test_db_session.refresh(job)
    assert (job.status, job.error_code) == ("failed", "worker_lost")
    assert not await _exists(test_db_session, staging)


@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_a_settled_attempts_table_is_dropped(test_db_session, status) -> None:
    job = await _job(test_db_session, status)
    staging = await _table(
        test_db_session, attempt_scoped_staging_table(_base(), job.attempt_id)
    )

    assert await reap_settled_attempt_tables() >= 1

    assert not await _exists(test_db_session, staging)


@pytest.mark.parametrize("status", ["pending", "running", "complete", "fanned_out"])
async def test_a_table_whose_attempt_is_not_settled_stays(
    test_db_session, status
) -> None:
    job = await _job(test_db_session, status, heartbeat_at=datetime.now(timezone.utc))
    staging = await _table(
        test_db_session, attempt_scoped_staging_table(_base(), job.attempt_id)
    )

    await reap_settled_attempt_tables()

    assert await _exists(test_db_session, staging)
    await _drop(test_db_session, staging)


async def test_a_table_whose_attempt_no_job_names_stays(test_db_session) -> None:
    """A retried job's earlier attempt, or a purged job's, proves no owner."""
    await _job(test_db_session, "failed")
    staging = await _table(
        test_db_session, attempt_scoped_staging_table(_base(), uuid.uuid4())
    )

    await reap_settled_attempt_tables()

    assert await _exists(test_db_session, staging)
    await _drop(test_db_session, staging)


async def test_live_and_previous_version_tables_stay(test_db_session) -> None:
    """A dataset's own table survives even under a settled attempt's name."""
    admin_id = await get_user_id(test_db_session, "admin")
    job = await _job(test_db_session, "failed")
    claimed = attempt_scoped_staging_table(_base(), job.attempt_id)
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, name=claimed, table_name=claimed
    )
    live = await _table(test_db_session, claimed)
    previous = await _table(
        test_db_session, previous_version_table(_base(), dataset.id)
    )

    await reap_settled_attempt_tables()

    assert await _exists(test_db_session, live)
    assert await _exists(test_db_session, previous)
    await _drop(test_db_session, live, previous)


async def test_a_table_something_depends_on_stays(test_db_session) -> None:
    job = await _job(test_db_session, "failed")
    staging = await _table(
        test_db_session, attempt_scoped_staging_table(_base(), job.attempt_id)
    )
    view = f"{_base()}_view"
    await test_db_session.execute(
        text(f'CREATE VIEW data."{view}" AS SELECT * FROM data."{staging}"')
    )
    await test_db_session.commit()

    await reap_settled_attempt_tables()

    assert await _exists(test_db_session, staging)
    await test_db_session.execute(text(f'DROP VIEW data."{view}"'))
    await _drop(test_db_session, staging)


async def test_a_job_row_someone_holds_keeps_its_table(test_db_session) -> None:
    """A row a retry or another pass holds is left for a later pass."""
    from app.core.db import async_session

    job = await _job(test_db_session, "failed")
    staging = await _table(
        test_db_session, attempt_scoped_staging_table(_base(), job.attempt_id)
    )

    async with async_session() as holder:
        await holder.execute(
            text("SELECT 1 FROM catalog.ingest_jobs WHERE id = :id FOR UPDATE"),
            {"id": job.id},
        )
        await reap_settled_attempt_tables()
        await holder.rollback()

    assert await _exists(test_db_session, staging)
    assert await reap_settled_attempt_tables() >= 1
    assert not await _exists(test_db_session, staging)


async def test_tables_that_cannot_be_dropped_do_not_starve_the_rest(
    test_db_session, monkeypatch
) -> None:
    """Each pass starts after the name the last one reached."""
    from app.platform.jobs import attempt_tables

    monkeypatch.setattr(attempt_tables, "_TABLES_PER_PASS", 1)
    blocked_job = await _job(test_db_session, "failed")
    blocked = await _table(
        test_db_session,
        attempt_scoped_staging_table(
            f"a0_{uuid.uuid4().hex[:8]}", blocked_job.attempt_id
        ),
    )
    view = f"{_base()}_view"
    await test_db_session.execute(
        text(f'CREATE VIEW data."{view}" AS SELECT * FROM data."{blocked}"')
    )
    free_job = await _job(test_db_session, "failed")
    free = await _table(
        test_db_session,
        attempt_scoped_staging_table(f"a1_{uuid.uuid4().hex[:8]}", free_job.attempt_id),
    )

    for _ in range(10):
        await reap_settled_attempt_tables()
        if not await _exists(test_db_session, free):
            break

    assert not await _exists(test_db_session, free)
    assert await _exists(test_db_session, blocked)
    await test_db_session.execute(text(f'DROP VIEW data."{view}"'))
    await _drop(test_db_session, blocked)


async def test_the_retention_purge_keeps_a_row_whose_table_remains(
    test_db_session, monkeypatch
) -> None:
    """The row is the only proof of the table's owner, so it outlives the table."""
    from app.core.config import settings
    from app.platform.jobs.sweep import fail_stale_jobs

    monkeypatch.setattr(settings, "ingest_jobs_retention_days", 1)
    old = datetime.now(timezone.utc) - timedelta(days=30)
    kept = await _job(test_db_session, "failed", completed_at=old, created_at=old)
    purged = await _job(test_db_session, "failed", completed_at=old, created_at=old)
    staging = await _table(
        test_db_session, attempt_scoped_staging_table(_base(), kept.attempt_id)
    )
    view = f"{_base()}_view"
    await test_db_session.execute(
        text(f'CREATE VIEW data."{view}" AS SELECT * FROM data."{staging}"')
    )
    await test_db_session.commit()
    kept_id, purged_id = kept.id, purged.id

    await fail_stale_jobs(test_db_session)

    test_db_session.expire_all()
    assert await test_db_session.get(IngestJob, kept_id) is not None
    assert await test_db_session.get(IngestJob, purged_id) is None
    assert await _exists(test_db_session, staging)
    await test_db_session.execute(text(f'DROP VIEW data."{view}"'))
    await _drop(test_db_session, staging)
