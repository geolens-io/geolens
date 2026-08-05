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

import uuid
from unittest.mock import AsyncMock, patch

import pytest

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

        await reap_presigned_staging_object(str(job_id), key)

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

        await reap_presigned_staging_object("job-1", None)

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

        await reap_presigned_staging_object("job-1", "staging/job-1/roads.geojson")

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
