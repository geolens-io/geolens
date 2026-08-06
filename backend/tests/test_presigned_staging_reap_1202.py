"""#1202 review r5: the presigned staging key must be swept at job end.

A completed presigned upload points ``file_path`` at a frozen copy, which
leaves ``user_metadata["s3_key"]`` as the only reference to the key the
client can still write through its unexpired PUT URL. Both staging reapers
now sweep it, and this file pins the decision policy plus the reaper that is
directly callable.

The decision policy is tested as a pure helper rather than by driving
ogr2ogr, matching ``test_ingest_staging_cleanup_gap018.py`` — the sibling
file that pins ``_should_unlink_staging`` for the same reason.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from rasterio.crs import CRS

from app.platform.jobs.models import owned_presigned_staging_key


pytestmark = pytest.mark.anyio


class TestOwnedPresignedStagingKey:
    """Which staging key a reaping job is allowed to delete."""

    def test_a_completed_presigned_job_owns_its_staging_key(self):
        job_id = uuid.uuid4()
        assert (
            owned_presigned_staging_key(
                job_id,
                {"presigned": True, "s3_key": f"staging/{job_id}/roads.geojson"},
                f"staging/{job_id}/frozen/roads.geojson",
            )
            == f"staging/{job_id}/roads.geojson"
        )

    def test_a_fan_out_child_does_not_own_the_inherited_parent_key(self):
        """The case that decided the design.

        ``create_fan_out_jobs`` clones the parent's ``user_metadata``
        wholesale, so every child carries the PARENT's ``s3_key``. Sweeping on
        "differs from file_path" alone would delete the shared original out
        from under siblings that still need it — the breakage the
        ``is_fan_out_child`` default-true guard exists to prevent. Ownership
        is the key's own prefix, so a child declines it.
        """
        parent_id = uuid.uuid4()
        child_id = uuid.uuid4()
        assert (
            owned_presigned_staging_key(
                child_id,
                {
                    "s3_key": f"staging/{parent_id}/multi.gpkg",
                    "fan_out_parent_id": str(parent_id),
                },
                f"staging/{parent_id}/multi.gpkg",
            )
            is None
        )

    def test_the_still_bound_staging_key_is_not_swept(self):
        """A job whose file_path IS the staging key still needs it."""
        job_id = uuid.uuid4()
        key = f"staging/{job_id}/roads.geojson"
        assert owned_presigned_staging_key(job_id, {"s3_key": key}, key) is None

    def test_a_job_with_no_presigned_metadata_sweeps_nothing(self):
        job_id = uuid.uuid4()
        assert owned_presigned_staging_key(job_id, None, "/local/path.geojson") is None
        assert owned_presigned_staging_key(job_id, {}, "/local/path.geojson") is None

    def test_a_non_string_key_is_refused_rather_than_formatted(self):
        """Metadata is user-influenced JSONB; a non-string must not reach the
        provider as a stringified value."""
        job_id = uuid.uuid4()
        assert owned_presigned_staging_key(job_id, {"s3_key": 17}, None) is None
        assert owned_presigned_staging_key(job_id, {"s3_key": None}, None) is None

    def test_an_arbitrary_same_bucket_key_is_refused(self):
        """Manifest sources can put arbitrary keys in this column. Only a key
        under THIS job's staging prefix is ours to delete."""
        job_id = uuid.uuid4()
        assert (
            owned_presigned_staging_key(
                job_id, {"s3_key": "customer-data/quarterly.gpkg"}, None
            )
            is None
        )


async def test_stale_purge_reaps_the_presigned_staging_object():
    """The jobs/router reaper, run for real.

    The purge deletes ``file_path`` for every purged row; the staging key it
    never reached is what a post-completion re-PUT recreates.
    """
    from app.platform.jobs import router as jobs_router

    job_id = uuid.uuid4()
    staging_key = f"staging/{job_id}/roads.geojson"
    frozen_key = f"staging/{job_id}/frozen/roads.geojson"

    storage = AsyncMock()
    outcome = jobs_router.StaleCleanupOutcome(
        pending_failed=0,
        running_failed=0,
        vrt_assets_recovered=0,
        vrt_generations_failed=0,
        terminal_jobs_purged=1,
        staged_paths_considered=1,
        local_files_reaped=0,
        storage_objects_reaped=0,
        staged_paths_skipped=0,
        staged_cleanup_failures=0,
        _staged_paths=(frozen_key,),
        _staged_presigned_keys=(staging_key,),
    )

    with patch("app.platform.storage.get_storage", return_value=storage):
        reaped = await jobs_router._reap_committed_staged_paths(outcome)

    deleted = {call.args[0] for call in storage.delete.await_args_list}
    assert deleted == {frozen_key, staging_key}, deleted
    assert reaped.storage_objects_reaped == 2
    assert reaped.staged_cleanup_failures == 0


async def test_a_failed_staging_sweep_is_counted_not_raised():
    """Same error posture as the existing cleanup: never raise, just count."""
    from app.platform.jobs import router as jobs_router

    job_id = uuid.uuid4()
    storage = AsyncMock()
    storage.delete.side_effect = RuntimeError("provider down")
    outcome = jobs_router.StaleCleanupOutcome(
        pending_failed=0,
        running_failed=0,
        vrt_assets_recovered=0,
        vrt_generations_failed=0,
        terminal_jobs_purged=1,
        staged_paths_considered=0,
        local_files_reaped=0,
        storage_objects_reaped=0,
        staged_paths_skipped=0,
        staged_cleanup_failures=0,
        _staged_presigned_keys=(f"staging/{job_id}/roads.geojson",),
    )

    with patch("app.platform.storage.get_storage", return_value=storage):
        reaped = await jobs_router._reap_committed_staged_paths(outcome)

    assert reaped.staged_cleanup_failures == 1
    assert reaped.storage_objects_reaped == 0


class TestReapPresignedStagingObject:
    """The shared sweep both task tails call.

    Exercised against a real ``LocalStorageProvider`` rather than by driving
    ogr2ogr/GDAL, matching ``test_raster_ingest_orphan_cleanup_gap017.py`` —
    the sibling file that tests the other cleanup in the same ``finally``.
    """

    async def test_the_owned_key_is_deleted(self, tmp_path, monkeypatch):
        from app.platform.storage.local import LocalStorageProvider
        from app.processing.ingest.tasks_common import reap_presigned_staging_object

        storage = LocalStorageProvider(str(tmp_path))
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )
        job_id = uuid.uuid4()
        key = f"staging/{job_id}/roads.geojson"
        await storage.put(key, b"staged-bytes")
        assert await storage.exists(key), "precondition: object staged"

        await reap_presigned_staging_object(str(job_id), key, final_status="complete")

        assert not await storage.exists(key)

    async def test_none_is_a_no_op_rather_than_a_delete(self, tmp_path, monkeypatch):
        """A job with nothing of its own to sweep must not reach the provider.

        This is the fan-out child's path: ``owned_presigned_staging_key``
        returns None for the inherited parent key, and that None must stay a
        no-op all the way down.
        """
        from app.processing.ingest.tasks_common import reap_presigned_staging_object

        storage = AsyncMock()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        await reap_presigned_staging_object("job-1", None, final_status="complete")

        storage.delete.assert_not_awaited()

    async def test_a_non_terminal_status_never_sweeps(self, monkeypatch):
        """fix(#1207): the guard moved into this helper from three identical
        copies in the task tails. A non-terminal exit — job or dataset missing,
        heartbeat claim lost — may be re-claimed by another attempt that still
        needs the staging bytes."""
        from app.processing.ingest.tasks_common import reap_presigned_staging_object

        storage = AsyncMock()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        await reap_presigned_staging_object(
            "job-1", "staging/job-1/roads.geojson", final_status="pending"
        )

        storage.delete.assert_not_awaited()

    async def test_a_provider_failure_never_escapes(self, monkeypatch):
        """The tail runs in a `finally` after the job is committed. Raising
        here would turn a completed ingest into a task failure."""
        from app.processing.ingest.tasks_common import reap_presigned_staging_object

        storage = AsyncMock()
        storage.delete.side_effect = RuntimeError("provider down")
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        await reap_presigned_staging_object(
            "job-1", "staging/job-1/roads.geojson", final_status="complete"
        )

        storage.delete.assert_awaited_once()


def test_both_task_tails_sweep_through_the_shared_helper():
    """Neither ingest path may grow its own copy of the sweep.

    The raster tail was added a round after the vector one precisely because
    the two had drifted; this catches a third path arriving without the sweep,
    or either call being deleted outright.

    KNOWN BLIND SPOT, stated so nobody mistakes this for reachability: it
    greps the module source, so a call that is PRESENT but UNREACHABLE passes.
    Measured — disabling the raster sweep with `if False:` left this test
    green. ``test_failed_raster_ingest_sweeps_its_presigned_staging_object``
    is the one that fails in that case, and it is the one to trust.
    """
    import inspect

    from app.processing.ingest import tasks_raster, tasks_vector

    for module in (tasks_vector, tasks_raster):
        source = inspect.getsource(module)
        assert "reap_presigned_staging_object(" in source, (
            f"{module.__name__} does not sweep the presigned staging key"
        )
        assert "owned_presigned_staging_key(" in source, (
            f"{module.__name__} does not resolve staging-key ownership"
        )


def _geotiff_bytes(*, crs=None) -> bytes:
    """Minimal in-memory GeoTIFF. Mirrors the copy in test_raster_ingest.py."""
    import io

    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds

    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": 32,
        "height": 32,
        "count": 1,
        "transform": from_bounds(-180, -90, 180, 90, 32, 32),
    }
    if crs is not None:
        profile["crs"] = crs
    buf = io.BytesIO()
    with MemoryFile() as mem:
        with mem.open(**profile) as ds:
            ds.write(np.zeros((32, 32), dtype="uint8"), 1)
        buf.write(mem.read())
    return buf.getvalue()


async def test_failed_raster_ingest_sweeps_its_presigned_staging_object(
    test_db_session, tmp_path, monkeypatch
) -> None:
    """The raster tail, driven for real rather than asserted structurally.

    A structural "does the module mention the helper" check cannot fail when
    the call is present but unreachable — disabling the sweep left it green.
    This runs ``ingest_raster`` to its terminal ``finally`` (via the CRS
    failure, the cheapest deterministic one) and asserts the object is gone.
    """
    from sqlalchemy import select

    from app.modules.auth.models import User
    from app.platform.jobs.models import IngestJob
    from app.platform.storage.local import LocalStorageProvider
    from app.processing.ingest.tasks_raster import ingest_raster

    bucket = tmp_path / "bucket"
    bucket.mkdir()
    storage = LocalStorageProvider(str(bucket))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    raster = tmp_path / "dem.tif"
    raster.write_bytes(_geotiff_bytes(crs=None))

    admin = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()

    job = IngestJob(
        source_filename="dem.tif",
        # What a presigned completion leaves: bound to the FROZEN copy, with
        # the client-writable staging key surviving only in metadata.
        file_path=str(raster),
        created_by=admin.id,
        status="pending",
        user_metadata={"file_type": "raster", "presigned": True},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    staging_key = f"staging/{job.id}/dem.tif"
    job.user_metadata = {**job.user_metadata, "s3_key": staging_key}
    await test_db_session.commit()

    await storage.put(staging_key, b"the-client-uploaded-bytes")
    assert await storage.exists(staging_key), "precondition: staging object present"

    with pytest.raises(ValueError, match="Provide a CRS override"):
        await ingest_raster.func(
            job_id=str(job.id),
            file_path=str(raster),
            user_id=str(admin.id),
            attempt_id=str(job.attempt_id),
        )

    assert not await storage.exists(staging_key), (
        "a failed raster ingest left its presigned staging object behind; "
        "nothing else reaps it (the stale purge exempts latest-complete)"
    )


async def test_validation_failure_still_sweeps_the_presigned_staging_object(
    test_db_session, tmp_path, monkeypatch
) -> None:
    """fix(#1202 review r7): the early return, not the happy path.

    ``_validate_upload_file_safety`` failing returns from the phase-1 session
    block before the phase-2 snapshot. The staging-key capture used to live in
    that snapshot, so this path reached the terminal ``finally`` with the key
    still None and left the object behind. Reachable without any attacker:
    lowering the size limit between completion and worker pickup fails a job
    whose bytes are already in the bucket.
    """
    from sqlalchemy import select

    from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
    from app.modules.auth.models import User
    from app.platform.jobs.models import IngestJob
    from app.platform.storage.local import LocalStorageProvider
    from app.processing.ingest.tasks_raster import ingest_raster

    bucket = tmp_path / "bucket"
    bucket.mkdir()
    storage = LocalStorageProvider(str(bucket))
    monkeypatch.setattr(
        "app.platform.storage.get_storage", lambda: storage, raising=True
    )

    raster = tmp_path / "dem.tif"
    raster.write_bytes(_geotiff_bytes(crs=CRS.from_epsg(4326)))

    admin = (
        await test_db_session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()

    job = IngestJob(
        source_filename="dem.tif",
        file_path=str(raster),
        created_by=admin.id,
        status="pending",
        user_metadata={"file_type": "raster", "presigned": True},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    staging_key = f"staging/{job.id}/dem.tif"
    job.user_metadata = {**job.user_metadata, "s3_key": staging_key}
    await test_db_session.commit()

    await storage.put(staging_key, b"the-client-uploaded-bytes")
    assert await storage.exists(staging_key), "precondition: staging object present"

    # The operator lowered the cap after this job's bytes landed. Validation
    # now fails on size, taking the early return out of the phase-1 block.
    with patch.object(UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=0)):
        await ingest_raster.func(
            job_id=str(job.id),
            file_path=str(raster),
            user_id=str(admin.id),
            attempt_id=str(job.attempt_id),
        )

    await test_db_session.refresh(job)
    assert job.status == "failed", "precondition: took the validation-failure path"
    assert "exceeds the maximum" in (job.error_message or "")
    assert not await storage.exists(staging_key), (
        "the validation-failure early return skipped the staging sweep"
    )


class TestPostExpirySweep:
    """fix(#1202 review r8): the backstop that outlives the PUT URL.

    Both other sweeps are event-triggered and a fast ingest fires both while
    the URL is still valid, so a re-PUT after them recreates an object nothing
    later reaps — the successful job is latest-complete-exempt from the purge
    forever. This pass runs once per job, after the URL can no longer be used.
    """

    @staticmethod
    def _outcome(**overrides):
        from app.platform.jobs.router import StaleCleanupOutcome

        base = dict(
            pending_failed=0,
            running_failed=0,
            vrt_assets_recovered=0,
            vrt_generations_failed=0,
            terminal_jobs_purged=0,
            staged_paths_considered=0,
            local_files_reaped=0,
            storage_objects_reaped=0,
            staged_paths_skipped=0,
            staged_cleanup_failures=0,
        )
        base.update(overrides)
        return StaleCleanupOutcome(**base)

    async def _make_job(self, test_db_session, *, age_seconds: int, status="complete"):
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select, update

        from app.modules.auth.models import User
        from app.platform.jobs.models import IngestJob

        admin = (
            await test_db_session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        job = IngestJob(
            source_filename="roads.geojson",
            created_by=admin.id,
            status=status,
            user_metadata={"presigned": True},
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)

        staging_key = f"staging/{job.id}/roads.geojson"
        # created_at is server-defaulted, so age it explicitly rather than
        # relying on wall-clock drift.
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(
                file_path=f"staging/{job.id}/frozen/roads.geojson",
                user_metadata={"presigned": True, "s3_key": staging_key},
                created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
            )
        )
        await test_db_session.commit()
        return job, staging_key

    async def test_a_recreated_object_past_the_deadline_is_swept_once(
        self, test_db_session, monkeypatch
    ) -> None:
        from sqlalchemy import select

        from app.platform.jobs import router as jobs_router
        from app.platform.jobs.models import IngestJob

        job, staging_key = await self._make_job(test_db_session, age_seconds=10_000)
        storage = AsyncMock()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        first = await jobs_router._sweep_expired_presigned_staging(
            test_db_session, self._outcome()
        )

        assert {c.args[0] for c in storage.delete.await_args_list} == {staging_key}
        assert first.storage_objects_reaped == 1
        refreshed = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == job.id)
            )
        ).scalar_one()
        await test_db_session.refresh(refreshed)
        assert refreshed.user_metadata["s3_key_reaped"] is True
        # The key itself survives in metadata — the marker is what stops the
        # re-sweep, not deleting the record of which key it was.
        assert refreshed.user_metadata["s3_key"] == staging_key

    async def test_a_second_pass_costs_no_storage_call(
        self, test_db_session, monkeypatch
    ) -> None:
        """Without the marker, latest-complete rows would cost a delete on
        every purge run for the rest of the deployment's life."""
        from app.platform.jobs import router as jobs_router

        await self._make_job(test_db_session, age_seconds=10_000)
        storage = AsyncMock()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        await jobs_router._sweep_expired_presigned_staging(
            test_db_session, self._outcome()
        )
        storage.delete.reset_mock()

        second = await jobs_router._sweep_expired_presigned_staging(
            test_db_session, self._outcome()
        )

        storage.delete.assert_not_awaited()
        assert second.storage_objects_reaped == 0

    async def test_a_job_inside_the_url_window_is_left_alone(
        self, test_db_session, monkeypatch
    ) -> None:
        """The URL may still be in legitimate use; sweeping here would delete
        bytes a retry needs."""
        from app.platform.jobs import router as jobs_router

        await self._make_job(test_db_session, age_seconds=60)
        storage = AsyncMock()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        await jobs_router._sweep_expired_presigned_staging(
            test_db_session, self._outcome()
        )

        storage.delete.assert_not_awaited()

    async def test_a_failed_delete_is_not_marked_done(
        self, test_db_session, monkeypatch
    ) -> None:
        """Marking a failed delete as done is the one outcome that leaks the
        object permanently, so the marker is withheld and a later pass retries.
        """
        from sqlalchemy import select

        from app.platform.jobs import router as jobs_router
        from app.platform.jobs.models import IngestJob

        job, _key = await self._make_job(test_db_session, age_seconds=10_000)
        storage = AsyncMock()
        storage.delete.side_effect = RuntimeError("provider down")
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        result = await jobs_router._sweep_expired_presigned_staging(
            test_db_session, self._outcome()
        )

        assert result.staged_cleanup_failures == 1
        assert result.storage_objects_reaped == 0
        refreshed = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == job.id)
            )
        ).scalar_one()
        await test_db_session.refresh(refreshed)
        assert "s3_key_reaped" not in (refreshed.user_metadata or {})

    async def test_a_timeout_lowering_restart_no_longer_orphans_the_recreated_object(
        self, test_db_session, monkeypatch
    ) -> None:
        """#1236 repro. An operator lowers ``pending_job_timeout_seconds`` and
        restarts while a PUT URL signed under the OLD, longer setting is still
        live. The ordinary pass derives its window from the CURRENT setting,
        so it reaps and marks the row early; a re-PUT through the still-valid
        URL then recreates the object. Before this fix the marker exempted
        the row from every later pass, orphaning the recreated object
        forever. Reproduced across two "runs" against the same row —
        ``pending_job_timeout_seconds`` changes between them, standing in for
        the restart, and the second run's ``now=`` stands in for wall-clock
        time actually passing — rather than an actual process restart.

        Assertions key off this test's OWN ``staging_key`` and job row rather
        than the aggregate ``StaleCleanupOutcome`` counts or an exact set of
        every ``storage.delete`` call: per the isolation note above
        ``test_db_session``, this file's test database is NOT rolled back
        between tests, and the final ``now=`` jump is deliberately beyond
        ``MAX_PRESIGNED_URL_LIFETIME_SECONDS`` — comfortably old enough to
        also re-sweep unrelated already-reaped rows left behind by sibling
        tests earlier in the same run.
        """
        from datetime import timedelta, timezone

        from sqlalchemy import select

        from app.core.config import MAX_PRESIGNED_URL_LIFETIME_SECONDS, settings
        from app.platform.jobs import router as jobs_router
        from app.platform.jobs.models import IngestJob

        # "Run 1": job created while pending_job_timeout_seconds was the
        # 3600s default. A URL signed near creation is legitimately live
        # until the job turns 3600s old.
        job, staging_key = await self._make_job(test_db_session, age_seconds=1500)
        storage = AsyncMock()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        async def _row() -> IngestJob:
            return (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job.id)
                )
            ).scalar_one()

        # "Run 2" / the restart: the operator lowers the setting to 120s.
        # post_expiry_sweep_after_seconds() is now 120 + 900 = 1020, well
        # under this job's age of 1500 — even though its URL, minted under
        # the pre-restart 3600s setting, will not expire until age 3600.
        with patch.object(settings, "pending_job_timeout_seconds", 120):
            await jobs_router._sweep_expired_presigned_staging(
                test_db_session, self._outcome()
            )

        assert staging_key in {c.args[0] for c in storage.delete.await_args_list}
        reaped_row = await _row()
        assert reaped_row.user_metadata["s3_key_reaped"] is True
        assert "s3_key_reaped_final" not in reaped_row.user_metadata

        # The client's still-valid pre-restart URL recreates the object.
        storage.delete.reset_mock()

        # A pass run shortly after must NOT re-check this row yet — the
        # re-check cost is bounded to once, not paid on every pass.
        await jobs_router._sweep_expired_presigned_staging(
            test_db_session, self._outcome()
        )
        assert staging_key not in {c.args[0] for c in storage.delete.await_args_list}

        # Once MAX_PRESIGNED_URL_LIFETIME_SECONDS have elapsed since
        # creation — the latest moment ANY URL for this job, signed under
        # ANY setting the deployment ever ran, can still be live — the
        # re-check pass fires and sweeps the recreated object for good.
        # `reaped_row.created_at` is read fresh from the row the ordinary
        # pass backdated — `job` itself still holds the pre-backdate value
        # from before `_make_job`'s follow-up UPDATE.
        created_at = reaped_row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        recheck_now = created_at + timedelta(
            seconds=MAX_PRESIGNED_URL_LIFETIME_SECONDS + 1
        )
        storage.delete.reset_mock()
        await jobs_router._sweep_expired_presigned_staging(
            test_db_session, self._outcome(), now=recheck_now
        )

        assert staging_key in {c.args[0] for c in storage.delete.await_args_list}
        final_row = await _row()
        assert final_row.user_metadata["s3_key_reaped_final"] is True

        # And it is now excluded for good — a later pass costs no further
        # delete call against THIS key, however much more time passes.
        storage.delete.reset_mock()
        await jobs_router._sweep_expired_presigned_staging(
            test_db_session,
            self._outcome(),
            now=recheck_now + timedelta(seconds=1),
        )
        assert staging_key not in {c.args[0] for c in storage.delete.await_args_list}


class TestFailedSourceRetention:
    """fix(#1213 review r6): whether a FAILED job's source may be reaped is a
    property of the CALLER, not of the helper.

    `_retry_capability` refuses reupload, service-auth and analysis jobs; an
    ordinary failed import with a `staging/` file_path is retryable exactly
    when the object still exists. Reaping it there is what makes the retry the
    endpoint advertises impossible, and the stale purge is the designed
    eventual owner ("failed keeps it for /jobs/{id}/retry").
    """

    @staticmethod
    async def _reap(monkeypatch, *, final_status: str, replayable: bool):
        from app.processing.ingest.tasks_common import (
            reap_downloaded_staging_source,
        )

        storage = AsyncMock()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )
        await reap_downloaded_staging_source(
            "job-1",
            original_file_path="staging/job-1/frozen/roads.geojson",
            final_status=final_status,
            failed_source_replayable=replayable,
        )
        return storage

    async def test_an_ordinary_import_retains_its_source_on_failure(
        self, monkeypatch
    ) -> None:
        """The retry endpoint promises a replay while the object exists."""
        storage = await self._reap(monkeypatch, final_status="failed", replayable=True)
        storage.delete.assert_not_awaited()

    async def test_a_reupload_still_reaps_on_failure(self, monkeypatch) -> None:
        """_retry_capability refuses these outright, so nothing else ever will."""
        storage = await self._reap(monkeypatch, final_status="failed", replayable=False)
        storage.delete.assert_awaited_once()

    async def test_success_reaps_for_both_kinds(self, monkeypatch) -> None:
        """Retention is about the RETRY, which only exists for failed jobs."""
        for replayable in (True, False):
            storage = await self._reap(
                monkeypatch, final_status="complete", replayable=replayable
            )
            storage.delete.assert_awaited_once()


class TestTerminalCleanupDrainsThroughCancellation:
    """fix(#1213 review r6): both tails call the source reap BEFORE the
    presigned-key sweep, so a CancelledError escaping the first skips the
    second — and that second one deletes the key a client may still hold an
    unexpired PUT URL for. Same pattern r5 restored in _cleanup_presigned_object.
    """

    async def test_a_cancelled_source_delete_does_not_escape(self, monkeypatch) -> None:
        from app.processing.ingest.tasks_common import (
            reap_downloaded_staging_source,
        )

        storage = AsyncMock()
        storage.delete.side_effect = asyncio.CancelledError()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        # Must not raise: the caller has a second sweep to run after this.
        await reap_downloaded_staging_source(
            "job-1",
            original_file_path="staging/job-1/frozen/roads.geojson",
            final_status="complete",
            failed_source_replayable=True,
        )

        storage.delete.assert_awaited_once()

    async def test_a_cancelled_presigned_sweep_does_not_escape(
        self, monkeypatch
    ) -> None:
        from app.processing.ingest.tasks_common import (
            reap_presigned_staging_object,
        )

        storage = AsyncMock()
        storage.delete.side_effect = asyncio.CancelledError()
        monkeypatch.setattr(
            "app.platform.storage.get_storage", lambda: storage, raising=True
        )

        await reap_presigned_staging_object(
            "job-1", "staging/job-1/roads.geojson", final_status="complete"
        )

        storage.delete.assert_awaited_once()
