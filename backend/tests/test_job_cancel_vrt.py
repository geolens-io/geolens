"""Cancelling a ``vrt_regenerate`` job reconciles the VRT state it dispatched.

fix(#1709 review P1). VRT dispatch (regenerate/add-source/remove-source)
commits a ``pending`` VrtGeneration and flips the RasterAsset to
``regenerating`` BEFORE deferring the job, and the asset's ``regenerating``
status is exactly what 409-blocks every later regeneration and source
mutation (``router_vrt.py``'s status guard). The worker unwinds that state
only through its ``except Exception`` handler, which a cancelled job never
reaches: a queued job's claim fails and the task exits early, and a
delivered abort raises CancelledError, a BaseException that handler cannot
see. Without endpoint-side reconciliation, a cancelled regeneration stays
blocked until ``sweep_stale_vrt_assets``'s JOB_TIMEOUT_SECONDS cutoff.

The cancel endpoint therefore reconciles in the SAME transaction as its job
CAS, with the sweep's own semantics: generation ``pending|running`` ->
``failed`` ("Cancelled by user"; the vrt_generations CHECK has no
``cancelled`` literal and this feature ships no migration), asset restored
``ready`` only under the sweep's ``_READY_WORTHY_SQL`` proof, else
``failed`` — either branch clears ``current_generation_id`` so the 409
block lifts immediately. Every write is a guarded CAS, so a worker that
finished first (fence winner) keeps its terminal state untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.platform.jobs.heartbeat import require_ingest_job_update
from app.platform.jobs.models import IngestJob
from app.platform.jobs.router import _reconcile_cancelled_vrt_regeneration
from app.processing.raster.models import RasterAsset, VrtGeneration, VrtSourceLink
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _seed_vrt_regeneration(
    session,
    *,
    job_status: str = "pending",
    generation_status: str = "pending",
    prior_failed_attempt: bool = False,
):
    """VRT dataset + source link + regenerating asset + generation + job,
    exactly the state the three dispatch sites commit before deferring."""
    now = datetime.now(timezone.utc)
    admin_id = await get_user_id(session, "admin")
    # source_format stays a CHECK-allowed value; a real VRT dataset's
    # format identity lives in record_type + the RasterAsset's vrt_type.
    vrt = await create_dataset(
        session,
        created_by=admin_id,
        record_type="vrt_dataset",
        source_format="geotiff",
        source_filename="mosaic.vrt",
    )
    source = await create_dataset(session, created_by=admin_id)
    session.add(
        VrtSourceLink(vrt_dataset_id=vrt.id, source_dataset_id=source.id, position=0)
    )

    if prior_failed_attempt:
        # A previous attempt a worker actually ran (heartbeat_at set) that
        # failed — the fact _PRIOR_ATTEMPT_WAS_READY_SQL keys the degraded
        # branch on.
        session.add(
            VrtGeneration(
                vrt_dataset_id=vrt.id,
                status="failed",
                started_at=now - timedelta(hours=2),
                heartbeat_at=now - timedelta(hours=2),
                completed_at=now - timedelta(hours=2),
                triggered_by=str(admin_id),
            )
        )

    generation = VrtGeneration(
        vrt_dataset_id=vrt.id,
        status=generation_status,
        started_at=now,
        heartbeat_at=now if generation_status == "running" else None,
        source_count=1,
        triggered_by=str(admin_id),
    )
    session.add(generation)
    await session.flush()

    asset = RasterAsset(
        dataset_id=vrt.id,
        asset_uri=f"rasters/{vrt.id}/generations/{uuid.uuid4()}/source.vrt",
        vrt_type="mosaic",
        status="regenerating",
        current_generation_id=generation.id,
        # The published composition: exactly the current link set, which is
        # what makes the attempt composition-preserving (_READY_WORTHY_SQL).
        built_from={str(source.id): f"rasters/{source.id}/cog.tif"},
    )
    session.add(asset)

    job = IngestJob(
        dataset_id=vrt.id,
        status=job_status,
        attempt_id=uuid.uuid4(),
        source_filename="vrt_regenerate",
        file_path="",
        created_by=admin_id,
        started_at=now if job_status == "running" else None,
        heartbeat_at=now if job_status == "running" else None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await session.refresh(generation)
    await session.refresh(asset)
    return vrt, asset, generation, job


async def test_cancel_of_queued_vrt_regenerate_restores_ready_immediately(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The pure-damage case the review named: no worker ever ran, so nothing
    but the 1-hour sweep would ever release the 409 block. The cancel
    transaction itself restores ``ready`` (composition provably preserved,
    prior attempt not failed) and fails the pending generation."""
    _vrt, asset, generation, job = await _seed_vrt_regeneration(test_db_session)

    resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text

    await test_db_session.refresh(job)
    await test_db_session.refresh(generation)
    await test_db_session.refresh(asset)
    assert job.status == "cancelled"
    assert generation.status == "failed"
    assert generation.error_message == "Cancelled by user"
    assert generation.completed_at is not None
    # The 409 guard in router_vrt.py reads exactly this status — 'ready'
    # (pointer cleared) means regeneration and source mutations are
    # admissible again the moment the cancel returns, not an hour later.
    assert asset.status == "ready"
    assert asset.current_generation_id is None


async def test_cancel_keeps_failed_when_ready_is_not_provable(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Degraded branch, same rule as the sweep: an asset whose prior real
    attempt failed must not be promoted to 'ready' by a cancel — but the
    pointer still clears, so the dataset is unblocked either way."""
    _vrt, asset, generation, job = await _seed_vrt_regeneration(
        test_db_session,
        job_status="running",
        generation_status="running",
        prior_failed_attempt=True,
    )

    resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text

    await test_db_session.refresh(generation)
    await test_db_session.refresh(asset)
    assert generation.status == "failed"
    assert generation.error_message == "Cancelled by user"
    assert asset.status == "failed"
    assert asset.current_generation_id is None


async def test_cancel_blocked_by_publish_lock_leaves_worker_state_intact(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The fence-wins serialization for VRT: the worker's publish transaction
    holds the job-row lock (fenced update through commit), so the cancel
    409s without writing anything — VRT state included — and the worker's
    terminal publish stands untouched."""
    _vrt, asset, generation, job = await _seed_vrt_regeneration(
        test_db_session, job_status="running", generation_status="running"
    )
    now = datetime.now(timezone.utc)

    # The publish transaction's first fenced write; hold it open across the
    # cancel request, as regenerate_vrt's phase-2 does through its commit.
    await require_ingest_job_update(
        test_db_session,
        job.id,
        job.attempt_id,
        values={"heartbeat_at": now},
    )

    resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "job_finishing"

    # The worker commits its publish: generation completed, asset ready,
    # job complete — all in the transaction that held the lock.
    generation.status = "completed"
    generation.completed_at = now
    asset.status = "ready"
    asset.current_generation_id = None
    await require_ingest_job_update(
        test_db_session,
        job.id,
        job.attempt_id,
        values={"status": "complete", "completed_at": now},
    )
    await test_db_session.commit()

    await test_db_session.refresh(generation)
    await test_db_session.refresh(asset)
    await test_db_session.refresh(job)
    assert generation.status == "completed"
    assert generation.error_message is None
    assert asset.status == "ready"
    assert job.status == "complete"

    # A retried cancel now reports the honest outcome and still writes nothing.
    retry = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "job_already_finished"
    await test_db_session.refresh(generation)
    assert generation.status == "completed"


class TestReconcileGuards:
    """The helper's CAS guards, driven directly: it must no-op — never
    clobber — whenever another actor's record already stands."""

    async def test_noop_when_asset_is_not_regenerating(self, test_db_session):
        _vrt, asset, generation, _job = await _seed_vrt_regeneration(test_db_session)
        # The worker's failure handler already reconciled: asset failed,
        # pointer cleared, generation failed with ITS message.
        pointer = asset.current_generation_id
        asset.status = "failed"
        asset.current_generation_id = None
        generation.status = "failed"
        generation.error_message = "GDAL exploded"
        await test_db_session.commit()

        await _reconcile_cancelled_vrt_regeneration(
            test_db_session, asset.dataset_id, datetime.now(timezone.utc)
        )
        await test_db_session.commit()
        await test_db_session.refresh(generation)
        await test_db_session.refresh(asset)
        assert generation.error_message == "GDAL exploded"
        assert asset.status == "failed"
        assert pointer is not None  # the seed really had one to strand

    async def test_noop_when_pointed_generation_is_terminal(self, test_db_session):
        """A zombie pointer at a completed generation belongs to the sweep,
        not the cancel — the completed record must never be overwritten."""
        _vrt, asset, generation, _job = await _seed_vrt_regeneration(test_db_session)
        generation.status = "completed"
        generation.completed_at = datetime.now(timezone.utc)
        await test_db_session.commit()

        await _reconcile_cancelled_vrt_regeneration(
            test_db_session, asset.dataset_id, datetime.now(timezone.utc)
        )
        await test_db_session.commit()
        await test_db_session.refresh(generation)
        await test_db_session.refresh(asset)
        assert generation.status == "completed"
        assert generation.error_message is None
        # The asset stays for whichever actor legitimately owns it.
        assert asset.status == "regenerating"
        assert asset.current_generation_id == generation.id
