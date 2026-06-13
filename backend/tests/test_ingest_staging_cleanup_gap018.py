"""GAP-018 regression: fan-out child S3 downloads must be cleaned from staging.

Background
----------
In S3 mode each ingest job resolves its OWN local copy of the source via
``resolve_file_path(file_path, job_id)`` -> ``{job_id}_{name}`` (so
``file_path != original_file_path``). That copy is private to the job. The
fan-out close-gate guard (GPKG-03) skipped the local unlink for ANY fan-out
child to avoid deleting the SHARED local-staging file that siblings read.

GAP-018: the guard was too broad — it also skipped cleanup of the per-child S3
download, leaking it on disk for every fan-out child layer.

These tests pin the cleanup-decision policy via the pure helper
``_should_unlink_staging`` so the policy is unit-testable without driving the
full ogr2ogr pipeline.
"""

from app.processing.ingest.tasks_vector import _should_unlink_staging


class TestShouldUnlinkStaging:
    def test_fan_out_child_s3_download_is_unlinked(self):
        """GAP-018: a fan-out child's PRIVATE S3 download must be unlinked.

        file_path differs from original_file_path (resolve_file_path produced a
        per-child {job_id}_{name} copy), so it is safe to remove even though the
        job is a fan-out child.
        """
        assert (
            _should_unlink_staging(
                file_path="/staging/childjob_roads.gpkg",
                original_file_path="s3://bucket/uploads/multi.gpkg",
                final_status="complete",
                is_fan_out_child=True,
            )
            is True
        )

    def test_fan_out_child_s3_download_unlinked_on_failure_too(self):
        """A failed fan-out child's per-child S3 copy is still removed (S3 is truth)."""
        assert (
            _should_unlink_staging(
                file_path="/staging/childjob_roads.gpkg",
                original_file_path="s3://bucket/uploads/multi.gpkg",
                final_status="failed",
                is_fan_out_child=True,
            )
            is True
        )

    def test_fan_out_child_shared_local_file_is_preserved(self):
        """The SHARED local-staging file of a fan-out child must NOT be unlinked.

        file_path == original_file_path means no per-child download happened;
        siblings read the same file, so deleting it would break them
        (GPKG-03 FileNotFoundError). Retained for the staging retention policy.
        """
        assert (
            _should_unlink_staging(
                file_path="/staging/upload_multi.gpkg",
                original_file_path="/staging/upload_multi.gpkg",
                final_status="complete",
                is_fan_out_child=True,
            )
            is False
        )

    def test_non_fan_out_local_upload_unlinked_on_success(self):
        """Plain single-layer local upload: unlink on success."""
        assert (
            _should_unlink_staging(
                file_path="/staging/upload_city.gpkg",
                original_file_path="/staging/upload_city.gpkg",
                final_status="complete",
                is_fan_out_child=False,
            )
            is True
        )

    def test_non_fan_out_local_upload_kept_on_failure(self):
        """Plain local upload on failure is KEPT for retry (S3 is not the source)."""
        assert (
            _should_unlink_staging(
                file_path="/staging/upload_city.gpkg",
                original_file_path="/staging/upload_city.gpkg",
                final_status="failed",
                is_fan_out_child=False,
            )
            is False
        )

    def test_non_fan_out_s3_download_unlinked_on_failure(self):
        """Non-fan-out S3 download is unlinked even on failure (pre-existing behavior)."""
        assert (
            _should_unlink_staging(
                file_path="/staging/job_city.gpkg",
                original_file_path="s3://bucket/uploads/city.gpkg",
                final_status="failed",
                is_fan_out_child=False,
            )
            is True
        )
