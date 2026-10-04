"""Disposal of a task's local copy, frozen upload and owned presigned key."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.processing.ingest.tasks_common import cleanup_step
from app.processing.ingest.tasks_staging import (
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
)

if TYPE_CHECKING:
    from app.processing.ingest.publication import PublicationCommit


def _replacement_status(publication: "PublicationCommit | None", failed: bool) -> str:
    from app.processing.ingest.publication import PublicationCommit

    if publication is PublicationCommit.ACKNOWLEDGED:
        return "complete"
    return "failed" if failed else "pending"


@dataclass(frozen=True, slots=True)
class UploadedSource:
    """The paths a task read and the presigned key it alone owns.

    A different local path is a private download. ``shared`` protects a
    fan-out child's original path; an unknown owner is treated as shared.
    Release isolates deletion failures and leaves durable archive recovery
    to publication follow-ups.
    """

    job_id: str
    original_path: str
    local_path: str
    owned_presigned_key: str | None
    shared: bool = False

    async def release_import(
        self, *, final_status: str, archive_confirmed: bool
    ) -> None:
        """Retain retryable input and any published original still owed an archive."""
        await self._release(
            task="ingest_file",
            final_status=final_status,
            unlink=self.local_path != self.original_path
            or (not self.shared and final_status == "complete" and archive_confirmed),
            reap_source=archive_confirmed,
            replayable=True,
        )

    async def release_file_replacement(
        self,
        *,
        publication: "PublicationCommit | None",
        failed: bool,
        refused: bool,
        held: bool = False,
    ) -> None:
        """Discard private downloads and refused input; leave published originals to follow-ups.

        A ``held`` upload outlives its failed job, for a person to accept. The
        client-writable presigned key still goes: the upload is read from the
        frozen copy.
        """
        final_status = _replacement_status(publication, failed)
        await self._release(
            task="reupload_file",
            final_status=final_status,
            unlink=refused or self.local_path != self.original_path,
            reap_source=final_status == "failed" and (refused or not held),
            replayable=False,
        )

    async def release_raster_replacement(
        self,
        *,
        publication: "PublicationCommit | None",
        failed: bool,
        original_preserved: bool,
    ) -> None:
        """Retain diagnostic input until an acknowledged COG or archive preserves it."""
        final_status = _replacement_status(publication, failed)
        await self._release(
            task="reupload_raster",
            final_status=final_status,
            unlink=self.local_path != self.original_path
            or (final_status == "complete" and original_preserved),
            reap_source=original_preserved,
            replayable=True,
            presigned_first=True,
        )

    async def _release(
        self,
        *,
        task: str,
        final_status: str,
        unlink: bool,
        reap_source: bool,
        replayable: bool,
        presigned_first: bool = False,
    ) -> None:
        async with cleanup_step(f"{task} local file", job_id=self.job_id):
            if unlink:
                Path(self.local_path).unlink(missing_ok=True)
        if presigned_first:
            await self._release_presigned(task, final_status)
        async with cleanup_step(f"{task} downloaded source", job_id=self.job_id):
            if reap_source:
                await reap_downloaded_staging_source(
                    self.job_id,
                    original_file_path=self.original_path,
                    final_status=final_status,
                    failed_source_replayable=replayable,
                    is_fan_out_child=self.shared,
                )
        if not presigned_first:
            await self._release_presigned(task, final_status)

    async def _release_presigned(self, task: str, final_status: str) -> None:
        async with cleanup_step(f"{task} presigned staging object", job_id=self.job_id):
            await reap_presigned_staging_object(
                self.job_id, self.owned_presigned_key, final_status=final_status
            )
