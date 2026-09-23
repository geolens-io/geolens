"""Publication settlement outcomes are exercised through its command interface."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.heartbeat import attempt_scoped_staging_table
from app.platform.jobs.models import IngestJob
from app.platform.refresh.service import claim_run_for_job, create_pending_run
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.verification import (
    canonical_service_source_binding_fingerprint,
)
from app.platform.dataset_origin import set_dataset_origin
from app.processing.ingest.publication import (
    PublicationOutcome,
    PublicationPostCommitFailure,
    PublicationSettlementCommand,
    PublicationSettlementFailure,
    settle_publication,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


def _metadata() -> dict:
    return {
        "srid": 4326,
        "geometry_type": "Point",
        "feature_count": 1,
        "extent_wkt": None,
        "column_info": [{"name": "name", "type": "character varying"}],
    }


async def _prepared_candidate(session, *, refresh: bool):
    admin_id = await get_user_id(session, "admin")
    live = f"publication_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(session, created_by=admin_id, table_name=live)
    attempt_id = uuid.uuid4()
    staging = attempt_scoped_staging_table(live, attempt_id)
    for table, row in ((live, "original"), (staging, "candidate")):
        await session.execute(
            sa.text(
                f'CREATE TABLE data."{table}" '
                "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
            )
        )
        await session.execute(
            sa.text(f'INSERT INTO data."{table}" (name) VALUES (:row)'), {"row": row}
        )
    job = IngestJob(
        dataset_id=dataset.id,
        status="running",
        attempt_id=attempt_id,
        started_at=datetime.now(timezone.utc),
        heartbeat_at=datetime.now(timezone.utc),
        source_filename="roads",
        created_by=admin_id,
        user_metadata={"refresh": refresh},
    )
    session.add(job)
    await session.commit()
    if refresh:
        run = await create_pending_run(
            session,
            dataset_id=dataset.id,
            origin_kind="service",
            trigger="manual",
            triggered_by=admin_id,
            ingest_job_id=job.id,
            feature_count_before=1,
        )
        await session.commit()
        assert await claim_run_for_job(session, job.id) == run.id
        await session.commit()
    loaded = (
        await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset.id)
        )
    ).scalar_one()
    return loaded, job, staging, admin_id


def _command(session, dataset, job, staging, admin_id, *, refresh: bool):
    source_binding = {
        "service_type": "wfs",
        "url": "https://services.example.test/wfs",
        "layer_id": "roads",
    }
    return PublicationSettlementCommand(
        session=session,
        dataset=dataset,
        dataset_id=dataset.id,
        job_id=job.id,
        attempt_id=job.attempt_id,
        staging_table=staging,
        metadata=_metadata(),
        sample_values={},
        user_id=str(admin_id),
        source_filename="roads",
        source_format="wfs",
        original_srid=4326,
        source_url="https://services.example.test/wfs",
        origin_ref={**source_binding, "auth_required": None},
        schema_diff={"row_count_old": 1, "row_count_new": 1},
        source_binding=source_binding,
        is_refresh=refresh,
        expected_feature_count=2 if refresh else None,
        content_digest="candidate-digest",
        staged_geometry_type="Point",
        staged_srid=4326,
        staged_coordinate_dimension=2,
        accepted_fingerprint=None,
        accepted_run_id=None,
        origin_binding=None,
        failure_contacted_origin=False,
    )


async def test_manual_service_reupload_publishes_without_a_refresh_run(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=False
    )
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_catalog_cache",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_tile_cache_for_table",
        AsyncMock(),
    )

    outcome = await settle_publication(
        _command(test_db_session, dataset, job, staging, admin_id, refresh=False)
    )

    assert outcome is PublicationOutcome.PUBLISHED
    assert (await test_db_session.get(IngestJob, job.id)).status == "complete"
    assert (await test_db_session.get(Dataset, dataset.id)).current_version == 2


async def test_rejected_refresh_settles_without_swapping_live_data(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=True
    )
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_catalog_cache",
        AsyncMock(),
    )

    outcome = await settle_publication(
        _command(test_db_session, dataset, job, staging, admin_id, refresh=True)
    )

    assert outcome is PublicationOutcome.REJECTED
    assert (await test_db_session.get(IngestJob, job.id)).status == "failed"
    name = await test_db_session.scalar(
        sa.text(f'SELECT name FROM data."{dataset.table_name}"')
    )
    assert name == "original"


async def test_verified_refresh_publishes_and_settles_its_run(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=True
    )
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_catalog_cache", AsyncMock()
    )
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_tile_cache_for_table",
        AsyncMock(),
    )

    outcome = await settle_publication(
        replace(
            _command(test_db_session, dataset, job, staging, admin_id, refresh=True),
            expected_feature_count=1,
        )
    )

    assert outcome is PublicationOutcome.PUBLISHED
    run = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job.id)
    )
    assert run.status == "succeeded"


async def test_blocked_refresh_keeps_live_data_and_settles_its_run(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=True
    )
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_catalog_cache", AsyncMock()
    )

    outcome = await settle_publication(
        replace(
            _command(test_db_session, dataset, job, staging, admin_id, refresh=True),
            expected_feature_count=None,
        )
    )

    assert outcome is PublicationOutcome.BLOCKED
    run = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job.id)
    )
    assert run.status == "blocked"


async def test_blocked_cache_failure_keeps_blocked_diagnostic(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=True
    )
    job_id = job.id
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_catalog_cache",
        AsyncMock(side_effect=RuntimeError("cache unavailable")),
    )

    with pytest.raises(PublicationPostCommitFailure, match="blocked"):
        await settle_publication(
            replace(
                _command(
                    test_db_session, dataset, job, staging, admin_id, refresh=True
                ),
                expected_feature_count=None,
            )
        )

    test_db_session.expire_all()
    run = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job_id)
    )
    assert run.status == "blocked"


async def test_post_commit_cache_failure_keeps_the_published_job_complete(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=False
    )
    dataset_id, job_id = dataset.id, job.id
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_catalog_cache",
        AsyncMock(side_effect=RuntimeError("cache unavailable")),
    )

    with pytest.raises(PublicationPostCommitFailure, match="cache invalidation"):
        await settle_publication(
            _command(test_db_session, dataset, job, staging, admin_id, refresh=False)
        )

    test_db_session.expire_all()
    assert (await test_db_session.get(IngestJob, job_id)).status == "complete"
    assert (await test_db_session.get(Dataset, dataset_id)).current_version == 2


async def test_cancelled_attempt_is_fenced_before_its_swap(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=False
    )
    job_id, live_table = job.id, dataset.table_name
    await test_db_session.execute(
        sa.update(IngestJob).where(IngestJob.id == job_id).values(status="cancelled")
    )
    await test_db_session.commit()
    monkeypatch.setattr(
        "app.processing.ingest.publication.invalidate_catalog_cache", AsyncMock()
    )

    with pytest.raises(PublicationSettlementFailure):
        await settle_publication(
            _command(test_db_session, dataset, job, staging, admin_id, refresh=False)
        )

    name = await test_db_session.scalar(
        sa.text(f'SELECT name FROM data."{live_table}"')
    )
    assert name == "original"
    assert (await test_db_session.get(IngestJob, job_id)).status == "cancelled"


async def test_superseded_attempt_is_fenced_before_its_swap(test_db_session):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=False
    )
    command = _command(test_db_session, dataset, job, staging, admin_id, refresh=False)
    job_id, live_table = job.id, dataset.table_name
    await test_db_session.execute(
        sa.update(IngestJob)
        .where(IngestJob.id == job_id)
        .values(attempt_id=uuid.uuid4())
    )
    await test_db_session.commit()

    with pytest.raises(PublicationSettlementFailure):
        await settle_publication(command)

    name = await test_db_session.scalar(
        sa.text(f'SELECT name FROM data."{live_table}"')
    )
    assert name == "original"


async def test_source_rebind_is_fenced_through_settlement_before_swap(
    test_db_session,
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=True
    )
    dataset_id = dataset.id
    live_table = dataset.table_name
    source_binding = {
        "service_type": "wfs",
        "url": "https://services.example.test/wfs",
        "layer_id": "roads",
    }
    set_dataset_origin(
        dataset,
        "service",
        uri=source_binding["url"],
        **source_binding,
    )
    run = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job.id)
    )
    run.source_binding_fingerprint = canonical_service_source_binding_fingerprint(
        source_binding
    )
    await test_db_session.commit()
    set_dataset_origin(
        dataset,
        "service",
        uri="https://services.example.test/rebound",
        service_type="wfs",
        url="https://services.example.test/rebound",
        layer_id="roads",
    )
    await test_db_session.commit()
    dataset = (
        await test_db_session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()

    with pytest.raises(PublicationSettlementFailure):
        await settle_publication(
            replace(
                _command(
                    test_db_session, dataset, job, staging, admin_id, refresh=True
                ),
                expected_feature_count=1,
            )
        )

    live_name = await test_db_session.scalar(
        sa.text(f'SELECT name FROM data."{live_table}"')
    )
    assert live_name == "original"


async def test_settlement_failure_scrubs_credential_before_durable_writes(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=True
    )
    job_id, live_table = job.id, dataset.table_name
    secret = "settlement-only-secret"

    async def fail_swap(*args, **kwargs):
        raise RuntimeError(f"database failure echoed {secret}")

    monkeypatch.setattr(
        "app.processing.ingest.publication._apply_reupload_swap", fail_swap
    )
    with pytest.raises(PublicationSettlementFailure):
        await settle_publication(
            replace(
                _command(
                    test_db_session, dataset, job, staging, admin_id, refresh=True
                ),
                expected_feature_count=1,
                credential_for_error_scrubbing=secret,
            )
        )

    test_db_session.expire_all()
    failed_job = await test_db_session.get(IngestJob, job_id)
    failed_run = await test_db_session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job_id)
    )
    live_name = await test_db_session.scalar(
        sa.text(f'SELECT name FROM data."{live_table}"')
    )
    assert failed_job.status == "failed"
    assert failed_run.status == "failed"
    assert live_name == "original"
    assert secret not in (failed_job.error_message or "")
    assert secret not in (failed_run.error_message or "")


async def test_different_service_failure_does_not_stamp_stored_origin(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=False
    )
    dataset_id = dataset.id
    set_dataset_origin(
        dataset,
        "service",
        uri="https://services.example.test/stored",
        service_type="wfs",
        url="https://services.example.test/stored",
        layer_id="roads",
    )
    bound = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)
    await test_db_session.commit()
    dataset = (
        await test_db_session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()

    async def fail_swap(*args, **kwargs):
        raise RuntimeError("swap failed")

    monkeypatch.setattr(
        "app.processing.ingest.publication._apply_reupload_swap", fail_swap
    )
    with pytest.raises(PublicationSettlementFailure):
        await settle_publication(
            replace(
                _command(
                    test_db_session, dataset, job, staging, admin_id, refresh=False
                ),
                failure_contacted_origin=False,
                origin_binding=bound,
            )
        )

    test_db_session.expire_all()
    assert (await test_db_session.get(Dataset, dataset_id)).last_checked_at is None


async def test_matching_service_failure_stamps_contact_without_a_refresh_run(
    test_db_session, monkeypatch
):
    dataset, job, staging, admin_id = await _prepared_candidate(
        test_db_session, refresh=False
    )
    dataset_id = dataset.id
    set_dataset_origin(
        dataset,
        "service",
        uri="https://services.example.test/wfs",
        service_type="wfs",
        url="https://services.example.test/wfs",
        layer_id="roads",
    )
    bound = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)
    await test_db_session.commit()
    dataset = (
        await test_db_session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()

    async def fail_swap(*args, **kwargs):
        raise RuntimeError("swap failed")

    monkeypatch.setattr(
        "app.processing.ingest.publication._apply_reupload_swap", fail_swap
    )
    with pytest.raises(PublicationSettlementFailure):
        await settle_publication(
            replace(
                _command(
                    test_db_session, dataset, job, staging, admin_id, refresh=False
                ),
                origin_binding=bound,
                failure_contacted_origin=True,
            )
        )

    test_db_session.expire_all()
    assert (await test_db_session.get(Dataset, dataset_id)).last_checked_at is not None
