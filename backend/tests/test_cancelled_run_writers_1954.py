"""The two writers of the `cancelled` run status (#1954, ADR-002 4d).

The sweep's guard comment claimed the status is never a stop signal while
the module beside it wrote one for an explicit user cancel. The resolution
is that `cancelled` carries both meanings and `error_code` tells them apart,
so the sweep's proof obligation binds only its own writer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    ABANDONED_ERROR_CODE,
    ABANDONED_RUN_CUTOFF_SECONDS,
    USER_CANCELLED_ERROR_CODE,
    cancel_active_run_for_job,
    create_pending_run,
    sweep_abandoned_refresh_runs,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _seed(session):
    user_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session, created_by=user_id, name=f"cancel-{uuid.uuid4().hex[:8]}"
    )
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        source_filename="parcels.gpkg",
        created_by=user_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=user_id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
    )
    await session.commit()
    return dataset, job, run


class TestBothWritersAreDistinguishableByErrorCode:
    async def test_a_user_cancel_is_a_stop_signal_and_says_so(
        self, test_db_session
    ) -> None:
        _, job, run = await _seed(test_db_session)

        assert await cancel_active_run_for_job(test_db_session, job.id) == run.id
        await test_db_session.commit()
        await test_db_session.refresh(run)

        assert run.status == "cancelled"
        assert run.error_code == USER_CANCELLED_ERROR_CODE
        assert run.finished_at is not None

    async def test_the_sweep_writes_only_its_own_bookkeeping_code(
        self, test_db_session
    ) -> None:
        """The sweep's proofs hold: no live task, and the job is `pending`."""
        _, job, run = await _seed(test_db_session)
        run.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=ABANDONED_RUN_CUTOFF_SECONDS + 60
        )
        await test_db_session.commit()

        assert await sweep_abandoned_refresh_runs(test_db_session) == 1
        await test_db_session.commit()
        await test_db_session.refresh(run)

        assert run.status == "cancelled"
        assert run.error_code == ABANDONED_ERROR_CODE
        assert run.error_code != USER_CANCELLED_ERROR_CODE

    async def test_the_sweep_leaves_a_users_cancel_alone(self, test_db_session) -> None:
        """`cancelled` is terminal for both, so neither writer overwrites the
        other's row and `error_code` stays the way to read them apart."""
        _, job, run = await _seed(test_db_session)
        await cancel_active_run_for_job(test_db_session, job.id)
        run.started_at = datetime.now(timezone.utc) - timedelta(
            seconds=ABANDONED_RUN_CUTOFF_SECONDS + 60
        )
        await test_db_session.commit()

        assert await sweep_abandoned_refresh_runs(test_db_session) == 0
        await test_db_session.commit()

        stored = (
            await test_db_session.execute(
                select(DatasetRefreshRun).where(DatasetRefreshRun.id == run.id)
            )
        ).scalar_one()
        assert stored.error_code == USER_CANCELLED_ERROR_CODE


class TestTheGuardCommentMatchesTheModule:
    """The comment is load-bearing: it is the argument for the sweep's two
    proofs, and a reader who finds it contradicted has no rule at all."""

    def test_the_sweep_no_longer_claims_the_status_is_never_a_stop_signal(
        self,
    ) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "platform"
            / "refresh"
            / "service.py"
        ).read_text()

        assert "never a stop signal" not in source
        assert "told apart by `error_code`" in source
