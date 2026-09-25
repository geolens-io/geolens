"""A service re-upload settles its verdicts and failures through the settlement seam."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.db as db_module
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.catalog_locks import CATALOG_LOCK_CONFLICT_CODE
from app.platform.dataset_origin import set_dataset_origin
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import create_pending_run
from app.platform.refresh.verification import (
    canonical_service_source_binding_fingerprint,
)
from app.processing.ingest.tasks_reupload import reupload_service
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_WFS = "https://services.example.test/wfs"
_BINDING = {"service_type": "wfs", "url": _WFS, "layer_id": "roads"}

# What each test's candidates left behind: (record id, job id, live table).
_created: list[tuple[uuid.UUID, uuid.UUID, str]] = []


async def _candidate(
    session, *, refresh: bool, run: bool = True, origin_url: str = _WFS
) -> tuple[Dataset, IngestJob, uuid.UUID]:
    """A service dataset holding 'original', and a queued re-upload of it."""
    admin_id = await get_user_id(session, "admin")
    live = f"publication_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(
        session, created_by=admin_id, table_name=live, source_format="wfs"
    )
    set_dataset_origin(
        dataset, "service", uri=origin_url, **{**_BINDING, "url": origin_url}
    )
    await session.execute(
        sa.text(
            f'CREATE TABLE data."{live}" '
            "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
        )
    )
    await session.execute(
        sa.text(f"INSERT INTO data.\"{live}\" (name) VALUES ('original')")
    )
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        source_filename="roads",
        source_url=_WFS,
        source_layer="roads",
        created_by=admin_id,
        user_metadata={"reupload": True, "service_type": "WFS", "refresh": refresh},
    )
    session.add(job)
    await session.flush()
    if run:
        await create_pending_run(
            session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="manual",
            triggered_by=admin_id,
            ingest_job_id=job.id,
            feature_count_before=1,
        )
    await session.commit()
    await session.refresh(job)
    _created.append((dataset.record_id, job.id, live))
    return dataset, job, admin_id


def _fetch(expected_feature_count: int | None, during=None):
    """Stand in for the service fetch: one staged row, and the source's own count."""

    async def _fake(*, staging_table: str, schema: str, on_spawn, **kwargs):
        on_spawn()
        async with db_module.async_session() as session:
            await session.execute(
                sa.text(
                    f'CREATE TABLE "{schema}"."{staging_table}" '
                    "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
                )
            )
            await session.execute(
                sa.text(
                    f'INSERT INTO "{schema}"."{staging_table}" (name) '
                    "VALUES ('candidate')"
                )
            )
            await session.commit()
        if during is not None:
            await during()
        return expected_feature_count, None

    return _fake


async def _reupload(
    dataset: Dataset,
    job: IngestJob,
    admin_id: uuid.UUID,
    *,
    expected: int | None = 1,
    during=None,
    token: str | None = None,
    credential_ref: str | None = None,
    patches: tuple = (),
) -> None:
    with ExitStack() as stack:
        stack.enter_context(
            patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock())
        )
        stack.enter_context(
            patch(
                "app.processing.ingest.tasks_reupload._fetch_service_layer_with_paging_guard",
                new=_fetch(expected, during),
            )
        )
        for extra in patches:
            stack.enter_context(extra)
        await reupload_service.func(
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            source_url=_WFS,
            source_layer="roads",
            user_id=str(admin_id),
            attempt_id=str(job.attempt_id),
            token=token,
            credential_ref=credential_ref,
        )


async def _job(job_id: uuid.UUID) -> IngestJob:
    async with db_module.async_session() as session:
        return await session.get(IngestJob, job_id)


async def _run(job_id: uuid.UUID) -> DatasetRefreshRun | None:
    async with db_module.async_session() as session:
        return await session.scalar(
            select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job_id)
        )


async def _live(dataset: Dataset) -> str:
    async with db_module.async_session() as session:
        return await session.scalar(
            sa.text(f'SELECT name FROM data."{dataset.table_name}"')
        )


@pytest.fixture(autouse=True)
def quiet():
    """Keep the caches, the embedding and notifications off the network."""
    sent = AsyncMock()
    with (
        patch(
            "app.processing.ingest.publication.invalidate_catalog_cache",
            new=AsyncMock(),
        ),
        patch(
            "app.processing.ingest.publication.invalidate_tile_cache_for_table",
            new=AsyncMock(),
        ),
        patch("app.processing.embeddings.helpers.defer_embedding", new=AsyncMock()),
        patch("app.platform.notifications.events.emit_event_safe", new=sent),
    ):
        yield sent


@pytest.fixture(autouse=True)
async def _remove_candidates(test_db_session):
    """Delete each candidate's job and record, which cascades to its dataset and runs."""
    yield
    async with db_module.async_session() as cleanup:
        while _created:
            record_id, job_id, live = _created.pop()
            await cleanup.execute(
                sa.text("DELETE FROM catalog.ingest_jobs WHERE id = :id"),
                {"id": job_id},
            )
            await cleanup.execute(
                sa.text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
            )
            await cleanup.execute(
                sa.text(f'DROP TABLE IF EXISTS data."{live}" CASCADE')
            )
        await cleanup.commit()


def _sent(quiet: AsyncMock) -> list[str]:
    return [call.kwargs["event_key"] for call in quiet.await_args_list]


async def test_manual_service_reupload_publishes_without_a_refresh_run(
    test_db_session,
):
    """A re-upload with no refresh run publishes and completes its job."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=False, run=False)

    await _reupload(dataset, job, admin_id)

    assert (await _job(job.id)).status == "complete"
    assert await _live(dataset) == "candidate"
    async with db_module.async_session() as session:
        assert (await session.get(Dataset, dataset.id)).current_version == 2


async def test_rejected_refresh_settles_without_swapping_live_data(
    test_db_session, quiet
):
    """A count mismatch rejects the refresh, keeps the live data and notifies."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)

    await _reupload(dataset, job, admin_id, expected=2)

    assert (await _job(job.id)).status == "failed"
    run = await _run(job.id)
    assert (run.status, run.error_code) == ("failed", "source_count_mismatch")
    assert await _live(dataset) == "original"
    assert _sent(quiet) == ["ingest_failed"]


async def test_verified_refresh_publishes_and_settles_its_run(test_db_session):
    """A refresh whose count matches publishes and completes its run."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)

    await _reupload(dataset, job, admin_id, expected=1)

    assert (await _run(job.id)).status == "succeeded"
    assert await _live(dataset) == "candidate"


async def test_a_published_refresh_stores_the_diff_taken_under_the_lock(
    test_db_session,
):
    """A published run's diff compares the staged data with the values stored at the lock."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)
    from app.processing.ingest import catalog_projection

    real_scored = catalog_projection.scored

    async def _edit_then_score(*args, **kwargs):
        # A feature edit commits after verification's diff was taken.
        async with db_module.async_session() as editor:
            await editor.execute(
                sa.text("UPDATE catalog.datasets SET feature_count = 7 WHERE id = :id"),
                {"id": dataset.id},
            )
            await editor.commit()
        return await real_scored(*args, **kwargs)

    await _reupload(
        dataset,
        job,
        admin_id,
        patches=(patch.object(catalog_projection, "scored", _edit_then_score),),
    )

    run = await _run(job.id)
    assert run.status == "succeeded"
    assert (run.schema_diff["row_count_old"], run.schema_diff["row_count_new"]) == (
        7,
        1,
    )


async def test_blocked_refresh_keeps_live_data_and_settles_its_run(
    test_db_session, quiet
):
    """A refresh with no source count waits for review and sends nothing."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)

    await _reupload(dataset, job, admin_id, expected=None)

    assert (await _run(job.id)).status == "blocked"
    assert "Review the detected changes" in ((await _job(job.id)).error_message or "")
    assert await _live(dataset) == "original"
    assert _sent(quiet) == []


async def test_a_blocked_verdict_settles_blocked_when_its_cache_purge_fails(
    test_db_session,
):
    """A cache purge that fails after the blocked commit is logged, not raised."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)

    await _reupload(
        dataset,
        job,
        admin_id,
        expected=None,
        patches=(
            patch(
                "app.processing.ingest.publication.invalidate_catalog_cache",
                new=AsyncMock(side_effect=RuntimeError("cache unavailable")),
            ),
        ),
    )

    assert (await _run(job.id)).status == "blocked"


async def _hold_dataset_row(dataset_id: uuid.UUID, ready: asyncio.Event) -> None:
    """Hold the dataset row from a second session for three seconds, then commit."""
    async with db_module.async_session() as holder:
        try:
            await holder.execute(
                select(Dataset.id)
                .where(Dataset.id == dataset_id)
                .with_for_update(read=True, key_share=True)
            )
            ready.set()
            await asyncio.sleep(3)
        finally:
            await holder.commit()


@pytest.mark.parametrize(
    ("expected", "run_status", "run_code"),
    [(None, "blocked", "review_required"), (2, "failed", "source_count_mismatch")],
    ids=["blocked", "rejected"],
)
async def test_a_held_back_verdict_waits_out_a_held_dataset_row(
    test_db_session, expected, run_status, run_code
):
    """A 3 s hold on the dataset row is waited out, and the run ends with its own verdict."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)
    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_dataset_row(dataset.id, ready))
    try:
        await ready.wait()
        await _reupload(dataset, job, admin_id, expected=expected)
    finally:
        await holder

    run = await _run(job.id)
    assert (run.status, run.error_code) == (run_status, run_code)
    assert run.error_code != CATALOG_LOCK_CONFLICT_CODE


@pytest.mark.parametrize("moved", ["cancelled", "superseded"])
async def test_an_attempt_that_lost_its_job_is_fenced_before_its_swap(
    test_db_session, quiet, moved: str
):
    """A job cancelled or re-attempted during the fetch keeps its live data."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=False)
    values = (
        {"status": "cancelled"}
        if moved == "cancelled"
        else {"attempt_id": uuid.uuid4()}
    )

    async def _move() -> None:
        async with db_module.async_session() as session:
            await session.execute(
                sa.update(IngestJob).where(IngestJob.id == job.id).values(**values)
            )
            await session.commit()

    # A cancel misses at the job hold, a new attempt at the job's reload.
    with pytest.raises(Exception):
        await _reupload(dataset, job, admin_id, during=_move)

    assert await _live(dataset) == "original"
    if moved == "cancelled":
        assert (await _job(job.id)).status == "cancelled"
    assert _sent(quiet) == []


@pytest.mark.parametrize(("cancelled", "redeemed"), [(True, 0), (False, 1)])
async def test_only_an_attempt_that_claims_its_job_redeems_the_credential(
    test_db_session, cancelled: bool, redeemed: int
):
    """A job cancelled before the claim redeems nothing; a claimable one redeems once."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=False, run=False)
    if cancelled:
        await test_db_session.execute(
            sa.update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(status="cancelled")
        )
        await test_db_session.commit()
    redeem = AsyncMock(return_value="secret")

    await _reupload(
        dataset,
        job,
        admin_id,
        credential_ref="c" * 32,
        patches=(
            patch(
                "app.processing.ingest.tasks_reupload.resolve_worker_credential",
                new=redeem,
            ),
        ),
    )

    assert redeem.await_count == redeemed
    assert await _live(dataset) == ("original" if cancelled else "candidate")


async def test_source_rebind_is_fenced_through_settlement_before_swap(
    test_db_session,
):
    """A rebind after the refresh started is refused under the catalog rows."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)
    run = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job.id)
    )
    run.source_binding_fingerprint = canonical_service_source_binding_fingerprint(
        _BINDING
    )
    set_dataset_origin(
        dataset,
        "service",
        uri="https://services.example.test/rebound",
        **{**_BINDING, "url": "https://services.example.test/rebound"},
    )
    await test_db_session.commit()

    with pytest.raises(Exception, match="source changed"):
        await _reupload(dataset, job, admin_id, expected=1)

    assert await _live(dataset) == "original"
    assert (await _run(job.id)).error_code == "source_changed"


async def test_settlement_failure_scrubs_credential_before_durable_writes(
    test_db_session,
):
    """A failure carrying the credential stores neither on the job nor on the run."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)
    secret = "settlement-only-secret"

    async def _fail_write(*args, **kwargs):
        raise RuntimeError(f"database failure echoed {secret}")

    with pytest.raises(RuntimeError):
        await _reupload(
            dataset,
            job,
            admin_id,
            token=secret,
            patches=(
                patch(
                    "app.processing.ingest.tasks_reupload._write_reupload_catalog",
                    new=_fail_write,
                ),
            ),
        )

    failed_job, failed_run = await _job(job.id), await _run(job.id)
    assert (failed_job.status, failed_run.status) == ("failed", "failed")
    assert await _live(dataset) == "original"
    assert secret not in (failed_job.error_message or "")
    assert secret not in (failed_run.error_message or "")


async def test_commit_failure_rolls_back_swap_and_records_durable_failure(
    test_db_session,
):
    """A publishing commit that fails leaves the live data and records the failure."""
    dataset, job, admin_id = await _candidate(test_db_session, refresh=True)
    real_commit = AsyncSession.commit
    status = select(IngestJob.status).where(IngestJob.id == job.id)
    failed = []

    async def _commit(session, *args, **kwargs):
        if not failed and (await session.execute(status)).scalar() == "complete":
            failed.append(True)
            # The server aborts the commit, so the probe reads it as not landed.
            await session.rollback()
            raise ConnectionResetError("commit unavailable")
        return await real_commit(session, *args, **kwargs)

    with pytest.raises(ConnectionResetError):
        await _reupload(
            dataset,
            job,
            admin_id,
            patches=(patch.object(AsyncSession, "commit", _commit),),
        )

    assert ((await _job(job.id)).status, (await _run(job.id)).status) == (
        "failed",
        "failed",
    )
    assert await _live(dataset) == "original"
    async with db_module.async_session() as session:
        assert (await session.get(Dataset, dataset.id)).current_version == 1


@pytest.mark.parametrize(
    ("stored_url", "stamped"),
    [(_WFS, True), ("https://services.example.test/stored", False)],
    ids=["matching", "different"],
)
async def test_a_failed_service_fetch_dates_the_contact_only_for_its_own_origin(
    test_db_session, stored_url: str, stamped: bool
):
    """A failure after the fetch contacted the origin stamps it only while the dataset is bound there."""
    dataset, job, admin_id = await _candidate(
        test_db_session, refresh=False, run=False, origin_url=stored_url
    )

    async def _fail_write(*args, **kwargs):
        raise RuntimeError("swap failed")

    with pytest.raises(RuntimeError, match="swap failed"):
        await _reupload(
            dataset,
            job,
            admin_id,
            patches=(
                patch(
                    "app.processing.ingest.tasks_reupload._write_reupload_catalog",
                    new=_fail_write,
                ),
            ),
        )

    async with db_module.async_session() as session:
        checked = (await session.get(Dataset, dataset.id)).last_checked_at
    assert (checked is not None) is stamped


async def test_a_failure_after_a_rebind_leaves_the_new_binding_undated(
    test_db_session,
):
    """An attempt whose dataset is rebound during its fetch does not date the new binding's contact."""
    dataset, job, admin_id = await _candidate(
        test_db_session, refresh=False, run=False, origin_url=_WFS
    )

    async def _rebind_to_an_upload() -> None:
        async with db_module.async_session() as session:
            await session.execute(
                sa.text(
                    "UPDATE catalog.datasets SET origin_uri = NULL, "
                    "origin_ref = CAST(:ref AS jsonb), source_format = 'gpkg' "
                    "WHERE id = :id"
                ),
                {"ref": '{"kind": "upload"}', "id": dataset.id},
            )
            await session.commit()

    async def _fail_write(*args, **kwargs):
        raise RuntimeError("swap failed")

    with pytest.raises(RuntimeError, match="swap failed"):
        await _reupload(
            dataset,
            job,
            admin_id,
            during=_rebind_to_an_upload,
            patches=(
                patch(
                    "app.processing.ingest.tasks_reupload._write_reupload_catalog",
                    new=_fail_write,
                ),
            ),
        )

    async with db_module.async_session() as session:
        assert (await session.get(Dataset, dataset.id)).last_checked_at is None
