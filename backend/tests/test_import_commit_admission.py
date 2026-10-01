"""An upload commit owns its job alone, and deletes the upload only when nothing else can read it."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import settings
from app.platform.jobs import ledger
from app.platform.jobs.models import IngestJob
from app.processing.ingest import router as ingest_router
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

_BODY = {"title": "Roads"}


async def _staged_upload(session) -> tuple[uuid.UUID, Path]:
    """A pending vector upload whose file is staged on local disk."""
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="roads.geojson",
        created_by=admin_id,
    )
    session.add(job)
    await session.flush()
    staged = Path(settings.upload_staging_dir) / f"{job.id}.geojson"
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text('{"type":"FeatureCollection","features":[]}')
    job.file_path = str(staged)
    await session.commit()
    return job.id, staged


def _claiming_defer(*, then_raise: bool):
    """A defer whose task a worker claims, optionally raising afterwards."""
    import app.core.db as db_module

    async def _defer(**kwargs) -> None:
        async with db_module.async_session() as worker:
            assert await ledger.claim(
                worker, uuid.UUID(kwargs["job_id"]), uuid.UUID(kwargs["attempt_id"])
            )
            await worker.commit()
        if then_raise:
            raise RuntimeError("connection dropped after the insert")

    return _defer


@contextmanager
def _ingest_task(side_effect):
    task = MagicMock()
    task.defer_async = AsyncMock(side_effect=side_effect)
    # A small vector file goes to the priority queue through `configure`.
    task.configure = MagicMock(return_value=task)
    with patch("app.processing.ingest.tasks.ingest_file", task):
        yield task


@contextmanager
def _read_before_the_first_commit():
    """The second request loaded the job while it was still an untouched pending upload."""
    real = ingest_router.get_job_or_404

    async def _stale(db, job_id, user):
        job = await real(db, job_id, user)
        set_committed_value(job, "status", "pending")
        set_committed_value(job, "user_metadata", None)
        return job

    with patch.object(ingest_router, "get_job_or_404", _stale):
        yield


async def _status(session, job_id: uuid.UUID) -> str:
    job = await session.get(IngestJob, job_id, populate_existing=True)
    return job.status


async def test_a_second_commit_of_a_claimed_upload_is_refused_and_keeps_its_file(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    job_id, staged = await _staged_upload(test_db_session)

    with _ingest_task(_claiming_defer(then_raise=False)):
        first = await client.post(
            f"/ingest/commit/{job_id}", json=_BODY, headers=admin_auth_header
        )
    assert first.status_code == 202, first.text

    with (
        _read_before_the_first_commit(),
        _ingest_task(RuntimeError("procrastinate unreachable")) as second_task,
    ):
        second = await client.post(
            f"/ingest/commit/{job_id}", json=_BODY, headers=admin_auth_header
        )

    assert second.status_code == 400, second.text
    second_task.defer_async.assert_not_awaited()
    assert staged.exists()
    assert await _status(test_db_session, job_id) == "running"


async def test_a_failed_dispatch_a_worker_already_claimed_keeps_its_file(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    job_id, staged = await _staged_upload(test_db_session)

    with _ingest_task(_claiming_defer(then_raise=True)):
        resp = await client.post(
            f"/ingest/commit/{job_id}", json=_BODY, headers=admin_auth_header
        )

    assert resp.status_code == 503, resp.text
    assert staged.exists()
    assert await _status(test_db_session, job_id) == "running"


async def test_a_failed_dispatch_nothing_claimed_deletes_its_file(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    job_id, staged = await _staged_upload(test_db_session)

    with _ingest_task(RuntimeError("procrastinate unreachable")):
        resp = await client.post(
            f"/ingest/commit/{job_id}", json=_BODY, headers=admin_auth_header
        )

    assert resp.status_code == 503, resp.text
    assert not staged.exists()
    assert await _status(test_db_session, job_id) == "failed"
