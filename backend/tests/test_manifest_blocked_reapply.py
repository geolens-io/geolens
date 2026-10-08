"""Applying an entry again while its last replacement is held for review."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)
from tests.factories import create_dataset
from tests.test_manifest_reapply_publication import (
    _admin,
    _entry,
    _http_request,
    _request,
    _reupload_task,
    _run_worker,
    _stage_fixture,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr"),
    pytest.mark.requires_ogr2ogr,
]

_KEY = "roads-held"


def _resurveyed(*, title: str = "Resurveyed roads", dry_run: bool = False):
    request = _request(_entry(_KEY, title=title, intent="published"))
    return request.model_copy(update={"dry_run": dry_run})


@dataclass(frozen=True)
class _Held:
    user: User
    dataset_id: uuid.UUID
    job_id: uuid.UUID
    run_id: uuid.UUID


async def _held_apply(session) -> _Held:
    """A manifest update that dropped a column and is now held for review."""
    _stage_fixture()
    user = await _admin(session)
    table = f"manifest_held_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session,
        created_by=user.id,
        name="Roads",
        table_name=table,
        record_type="vector_dataset",
        geometry_type="POINT",
        feature_count=1,
        column_info=[
            {"name": "name", "type": "text"},
            {"name": "legacy", "type": "text"},
        ],
    )
    await session.execute(
        text(
            f'CREATE TABLE "data"."{table}" (gid serial PRIMARY KEY, '
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326), "
            "name text, legacy text)"
        )
    )
    original = _request(_entry(_KEY, title="Roads", intent="published")).datasets[0]
    prepared = await classify_manifest_source(original.sources[0])
    session.add(
        IngestJob(
            dataset_id=dataset.id,
            source_filename=prepared.source_filename,
            file_path=prepared.file_path,
            created_by=user.id,
            status="complete",
            completed_at=datetime.now(timezone.utc),
            user_metadata=manifest_job_metadata(
                original, prepared, fingerprint=manifest_dataset_fingerprint(original)
            ),
        )
    )
    await session.commit()

    with _reupload_task() as task:
        response = await apply_manifest(session, _resurveyed(), user, _http_request())
    assert response.results[0].action == "update"
    await _run_worker(task)
    run = (
        await session.execute(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.ingest_job_id == response.results[0].job_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert run.status == "blocked"
    return _Held(user, dataset.id, response.results[0].job_id, run.id)


async def _job_count(session) -> int:
    rows = await session.execute(
        select(IngestJob.id).where(
            IngestJob.user_metadata["manifest_key"].astext == _KEY
        )
    )
    return len(rows.all())


async def test_reapplying_an_unchanged_held_entry_reports_it_blocked(
    test_db_session, clean_tables
):
    held = await _held_apply(test_db_session)
    jobs_before = await _job_count(test_db_session)

    for dry_run in (True, False):
        with _reupload_task() as task:
            response = await apply_manifest(
                test_db_session,
                _resurveyed(dry_run=dry_run),
                held.user,
                _http_request(),
            )
        [result] = response.results
        assert result.action == "blocked", result.message
        assert (result.job_id, result.dataset_id, result.run_id) == (
            held.job_id,
            held.dataset_id,
            held.run_id,
        )
        assert result.review_reasons == ["destructive_schema_change"]
        assert str(held.run_id) in result.message
        assert response.accepted
        task.defer_async.assert_not_awaited()

    assert await _job_count(test_db_session) == jobs_before


async def test_a_changed_entry_is_queued_past_the_hold(test_db_session, clean_tables):
    held = await _held_apply(test_db_session)
    jobs_before = await _job_count(test_db_session)

    with _reupload_task() as task:
        response = await apply_manifest(
            test_db_session,
            _resurveyed(title="Roads, second survey"),
            held.user,
            _http_request(),
        )

    [result] = response.results
    assert result.action == "update", result.message
    assert result.job_id not in (None, held.job_id)
    assert result.run_id is None
    task.defer_async.assert_awaited_once()
    assert await _job_count(test_db_session) == jobs_before + 1


@pytest.mark.parametrize("why", ["acceptance_spent", "data_replaced", "upload_gone"])
async def test_a_hold_that_can_no_longer_be_accepted_does_not_block(
    test_db_session, clean_tables, why
):
    held = await _held_apply(test_db_session)
    if why == "acceptance_spent":
        run = await test_db_session.get(DatasetRefreshRun, held.run_id)
        run.verification = {
            **run.verification,
            "acceptance_consumed_by_run_id": str(uuid.uuid4()),
        }
    elif why == "upload_gone":
        job = await test_db_session.get(IngestJob, held.job_id)
        staged = Path(job.file_path)
        assert staged.name.startswith(f"{held.job_id}_") and staged.exists()
        staged.unlink()
    else:
        await test_db_session.execute(
            update(Dataset)
            .where(Dataset.id == held.dataset_id)
            .values(current_version=Dataset.current_version + 1)
        )
    await test_db_session.commit()

    with _reupload_task() as task:
        response = await apply_manifest(
            test_db_session, _resurveyed(), held.user, _http_request()
        )

    [result] = response.results
    assert result.action == "update", result.message
    task.defer_async.assert_awaited_once()


async def test_another_user_learns_nothing_about_the_hold(
    client: AsyncClient, editor_auth_header: dict, test_db_session, clean_tables
):
    held = await _held_apply(test_db_session)
    me = await client.get("/auth/me/", headers=editor_auth_header)
    editor = SimpleNamespace(id=uuid.UUID(me.json()["id"]))

    for dry_run in (True, False):
        with _reupload_task() as task:
            response = await apply_manifest(
                test_db_session,
                _resurveyed(dry_run=dry_run),
                editor,
                _http_request(),
            )
        [result] = response.results
        assert result.action == "error"
        assert (result.job_id, result.dataset_id, result.run_id) == (None, None, None)
        assert result.review_reasons == []
        assert str(held.run_id) not in result.message
        task.defer_async.assert_not_awaited()
