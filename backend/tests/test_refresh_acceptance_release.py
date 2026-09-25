"""An accepted blocked refresh is acceptable again once its accepting run ends unpublished."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    claim_admitted_run_for_job,
    claim_run_for_job,
    create_pending_run,
    fail_claimed_admitted_refresh,
    record_refresh_failure,
    record_refresh_success,
    reject_pending_admitted_refresh,
    sweep_abandoned_refresh_runs,
)
from tests.factories import get_user_id
from tests.test_refresh_dispatch_rollback import _blocked_run, _consumed_by
from tests.test_service_refresh_1220 import (
    _dispatch_harness as _service_harness,
    _service_dataset,
)

pytestmark = pytest.mark.anyio


async def _accept(
    client: AsyncClient, headers: dict, dataset_id: uuid.UUID, blocked_id: uuid.UUID
):
    async with _service_harness():
        return await client.post(
            f"/datasets/{dataset_id}/refresh",
            json={"accept_blocked_run_id": str(blocked_id)},
            headers=headers,
        )


async def _accepted(
    client: AsyncClient, headers: dict, dataset_id: uuid.UUID, blocked_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """The job and run of a dispatch that consumed ``blocked_id``'s acceptance."""
    resp = await _accept(client, headers, dataset_id, blocked_id)
    assert resp.status_code == 202, resp.text
    return uuid.UUID(resp.json()["job_id"]), uuid.UUID(resp.json()["run_id"])


async def _cancel_through_the_endpoint(session, client, headers, job_id, run_id):
    resp = await client.post(f"/jobs/{job_id}/cancel", headers=headers)
    assert resp.status_code == 200, resp.text


async def _abandon_to_the_sweep(session, client, headers, job_id, run_id):
    await session.execute(
        update(DatasetRefreshRun)
        .where(DatasetRefreshRun.id == run_id)
        .values(started_at=datetime.now(timezone.utc) - timedelta(hours=2))
    )
    await session.commit()
    assert await sweep_abandoned_refresh_runs(session) >= 1
    await session.commit()


async def _fail_through_the_worker_sink(session, client, headers, job_id, run_id):
    assert await record_refresh_failure(
        session,
        ingest_job_id=job_id,
        error_code="service_refresh_failed",
        error_message="source unreachable",
    )
    await session.commit()


async def _admitted_run(session, dataset_id, blocked_id) -> tuple[uuid.UUID, uuid.UUID]:
    """A keyed accepting run and its job, holding ``blocked_id``'s acceptance."""
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        dataset_id=dataset_id,
        status="pending",
        source_filename="parcels",
        created_by=admin_id,
        user_metadata={"refresh": True, "dataset_id": str(dataset_id)},
    )
    session.add(job)
    await session.flush()
    key = uuid.uuid4()
    run = await create_pending_run(
        session,
        dataset_id=dataset_id,
        origin_kind="service",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=None,
        execution_key=key,
    )
    await router_refresh._consume_blocked_refresh_acceptance(
        session,
        dataset_id=dataset_id,
        blocked_run_id=blocked_id,
        new_run_id=run.id,
        fingerprint="fp",
    )
    job_id = job.id
    await session.commit()
    return job_id, key


class TestAcceptanceComesBack:
    @pytest.mark.parametrize(
        "end_run",
        [
            _cancel_through_the_endpoint,
            _abandon_to_the_sweep,
            _fail_through_the_worker_sink,
        ],
        ids=["cancel-endpoint", "abandoned-run-sweep", "record-refresh-failure"],
    )
    async def test_an_accepting_run_that_ends_unpublished_gives_it_back(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, end_run
    ):
        """A cancelled or failed accepting run makes its blocked run acceptable again."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset_id = dataset.id
        blocked_id = await _blocked_run(test_db_session, dataset_id)
        job_id, run_id = await _accepted(
            client, admin_auth_header, dataset_id, blocked_id
        )
        assert await _consumed_by(test_db_session, blocked_id) == str(run_id)

        await end_run(test_db_session, client, admin_auth_header, job_id, run_id)

        assert await _consumed_by(test_db_session, blocked_id) is None
        again = await _accept(client, admin_auth_header, dataset_id, blocked_id)
        assert again.status_code == 202, again.text

    @pytest.mark.parametrize("path", ["rejected", "failed-after-claim"])
    async def test_an_admitted_run_that_fails_gives_it_back(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        path: str,
    ):
        """The keyed-admission failure writers release an acceptance too."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset_id = dataset.id
        blocked_id = await _blocked_run(test_db_session, dataset_id)
        job_id, key = await _admitted_run(test_db_session, dataset_id, blocked_id)

        if path == "rejected":
            assert await reject_pending_admitted_refresh(
                test_db_session,
                ingest_job_id=job_id,
                execution_key=key,
                error_code="scheduled_claim_expired",
                error_message="Scheduled refresh was not claimed before its deadline.",
            )
        else:
            assert await claim_admitted_run_for_job(
                test_db_session, job_id, execution_key=key
            )
            await test_db_session.commit()
            assert await fail_claimed_admitted_refresh(
                test_db_session,
                ingest_job_id=job_id,
                execution_key=key,
                error_code="credential_unavailable",
                error_message="The service credential could not be resolved.",
            )
        await test_db_session.commit()

        assert await _consumed_by(test_db_session, blocked_id) is None
        again = await _accept(client, admin_auth_header, dataset_id, blocked_id)
        assert again.status_code == 202, again.text


class TestAcceptanceStaysConsumed:
    async def test_a_succeeded_accepting_run_keeps_it(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """A run that published leaves its blocked run consumed."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset_id = dataset.id
        blocked_id = await _blocked_run(test_db_session, dataset_id)
        job_id, run_id = await _accepted(
            client, admin_auth_header, dataset_id, blocked_id
        )

        assert await claim_run_for_job(test_db_session, job_id) == run_id
        assert await record_refresh_success(
            test_db_session,
            ingest_job_id=job_id,
            dataset=await test_db_session.get(Dataset, dataset_id),
            dataset_version_id=None,
            feature_count_after=1,
            schema_diff=None,
            contacted_origin=False,
        )
        await test_db_session.commit()

        assert await _consumed_by(test_db_session, blocked_id) == str(run_id)
        again = await _accept(client, admin_auth_header, dataset_id, blocked_id)
        assert again.status_code == 422, again.text

    async def test_ending_one_run_leaves_other_acceptances_alone(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Only the blocked run the ended run accepted comes back."""
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _service_dataset(test_db_session, created_by=admin_id)
        dataset_id = dataset.id
        other = await _service_dataset(test_db_session, created_by=admin_id)
        other_id = other.id
        blocked_id = await _blocked_run(test_db_session, dataset_id)
        spent_id = await _blocked_run(test_db_session, dataset_id)
        other_blocked_id = await _blocked_run(test_db_session, other_id)
        spent_by = uuid.uuid4()
        await test_db_session.execute(
            update(DatasetRefreshRun)
            .where(DatasetRefreshRun.id == spent_id)
            .values(
                verification={
                    "review_fingerprint": "fp",
                    "acceptance_consumed_by_run_id": str(spent_by),
                }
            )
        )
        await test_db_session.commit()
        job_id, run_id = await _accepted(
            client, admin_auth_header, dataset_id, blocked_id
        )
        _other_job, other_run_id = await _accepted(
            client, admin_auth_header, other_id, other_blocked_id
        )

        await _cancel_through_the_endpoint(
            test_db_session, client, admin_auth_header, job_id, run_id
        )

        assert await _consumed_by(test_db_session, blocked_id) is None
        assert await _consumed_by(test_db_session, spent_id) == str(spent_by)
        assert await _consumed_by(test_db_session, other_blocked_id) == str(
            other_run_id
        )
