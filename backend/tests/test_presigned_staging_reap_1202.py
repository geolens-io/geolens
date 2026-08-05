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
