"""Delete local staged uploads that no ingest job can still use.

The local counterpart of ``reconcile_orphaned_staging_objects``. It starts
from the files directly in the upload staging directory, so it finds an
upload whose delete failed or never ran, such as a worker cleanup that
errored or an ingest killed after its complete commit.

That directory is not the upload system's alone. Operators stage manifest
seed files there, the local storage backend keeps its objects in
subdirectories, and other sweeps own their scratch. So a file is a candidate
only when its name has an upload writer's shape and an ``ingest_jobs`` row's
``file_path`` names it; a file no row names is never deleted, whatever its
name. A candidate goes once no row naming it can still read it.
"""

from __future__ import annotations

import bisect
import os
import re
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.platform.jobs.models import (
    PUBLISH_FOLLOWUPS_FIELD,
    IngestJob,
    needs_staged_input,
)

log = structlog.get_logger()

# `{job id}_{name}` from uploads, reuploads and URL imports, and
# `manifest_{hex}_{name}` from a manifest's copy of its source.
_UPLOAD_NAME = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|manifest_[0-9a-f]{32})_."
)

_MAX_CANDIDATES_PER_PASS = 20_000
_MAX_DELETES_PER_PASS = 200
# Files per row lookup; two spellings each stays far under the bind-parameter cap.
_LOOKUP_BATCH = 1000

# The name the next pass starts after, so a directory holding more candidates
# than one pass examines is covered in turn. It orders the work and decides
# nothing about what may be deleted.
_resume_after: str | None = None


@dataclass
class LocalStagingReconcileOutcome:
    """What one pass over the local staging directory saw and did."""

    # False when the pass declined.
    ran: bool = False
    candidates: int = 0
    uploads_deleted: int = 0
    delete_failures: int = 0
    # No row names the file, so nothing proves it is an upload.
    skipped_unnamed: int = 0
    # A row naming it can still read it, or ended within the age threshold.
    skipped_needed: int = 0
    # Gone, rewritten or no longer a regular file when its delete came.
    skipped_changed: int = 0


def _still_needed(cutoff: datetime):
    """Predicate: a row naming a staged upload can still read it, or ended too recently.

    The publish follow-ups archive and then delete the upload a published job
    names, so while its row carries their record the upload is theirs. The age
    term gives the job's own cleanup, and any reader holding the path, the
    threshold's head start.
    """
    return or_(
        needs_staged_input(),
        IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD].is_not(None),
        func.coalesce(IngestJob.completed_at, IngestJob.created_at) >= cutoff,
    )


def _spellings(roots: tuple[Path, ...], name: str) -> list[str]:
    """Each ``file_path`` a row may use for this file: under the root as configured, and resolved."""
    return [str(root / name) for root in roots]


def _old_upload_files(root: Path, cutoff_ts: float) -> list[str]:
    """This pass's share of the upload-shaped regular files in ``root`` older than the cutoff.

    Direct children only, since exports and the storage backend's objects live
    in subdirectories, and never through a symlink.
    """
    global _resume_after
    try:
        with os.scandir(root) as entries:
            names = sorted(e.name for e in entries if _UPLOAD_NAME.match(e.name))
    except FileNotFoundError:
        return []
    start = bisect.bisect_right(names, _resume_after) if _resume_after else 0
    ordered = names[start:] + names[:start]
    window = ordered[:_MAX_CANDIDATES_PER_PASS]
    _resume_after = window[-1] if len(window) < len(ordered) else None
    old: list[str] = []
    for name in window:
        try:
            info = os.lstat(root / name)
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode) and info.st_mtime < cutoff_ts:
            old.append(name)
    return old


def _unlink_if_unchanged(path: Path, cutoff_ts: float) -> bool:
    """Unlink ``path`` if it is still an old regular file; False when it changed or went.

    Raises the ``OSError`` of an unlink that failed for any other reason.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_mtime >= cutoff_ts:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


async def _needed_by_path(
    db: AsyncSession, roots: tuple[Path, ...], names: list[str], cutoff: datetime
) -> dict[str, bool]:
    """Whether some row naming each path still needs it; a path no row names is absent."""
    paths = [path for name in names for path in _spellings(roots, name)]
    rows = await db.execute(
        select(IngestJob.file_path, func.bool_or(_still_needed(cutoff)))
        .where(IngestJob.file_path.in_(paths))
        .group_by(IngestJob.file_path)
    )
    return dict(rows.tuples().all())


async def _row_still_needs(
    db: AsyncSession, roots: tuple[Path, ...], name: str, cutoff: datetime
) -> bool:
    """A fresh read, just before the delete, so a row committed since the batch lookup counts."""
    result = await db.execute(
        select(IngestJob.id)
        .where(IngestJob.file_path.in_(_spellings(roots, name)), _still_needed(cutoff))
        .limit(1)
    )
    return result.first() is not None


async def reconcile_orphaned_local_uploads(
    db: AsyncSession, *, now: datetime | None = None
) -> LocalStagingReconcileOutcome:
    """Delete the staged uploads in the local staging directory that no job can still use.

    Read-only against ``db``, which it never commits or rolls back. Declines in
    multi-tenant mode, where row-level security hides other tenants' rows and
    their uploads would look unneeded. Never raises: a failure leaves the rest
    for the next pass.
    """
    from app.core.tenancy import is_multi_tenant

    if is_multi_tenant():
        return LocalStagingReconcileOutcome()
    outcome = LocalStagingReconcileOutcome(ran=True)
    try:
        await _reconcile(db, now=now or datetime.now(timezone.utc), outcome=outcome)
    except Exception:  # broad: best-effort pass, never fails its caller
        log.warning("Local staged upload reconciliation failed", exc_info=True)
    if outcome.uploads_deleted or outcome.delete_failures:
        log.info("Reconciled local staged uploads", **asdict(outcome))
    return outcome


async def _reconcile(
    db: AsyncSession, *, now: datetime, outcome: LocalStagingReconcileOutcome
) -> None:
    global _resume_after
    root = Path(settings.upload_staging_dir)
    roots = tuple(dict.fromkeys((root, root.resolve())))
    cutoff = now - timedelta(seconds=settings.staging_orphan_min_age_seconds)
    names = await run_in_thread_draining(_old_upload_files, root, cutoff.timestamp())
    outcome.candidates = len(names)

    unneeded: list[str] = []
    for start in range(0, len(names), _LOOKUP_BATCH):
        batch = names[start : start + _LOOKUP_BATCH]
        needed_by_path = await _needed_by_path(db, roots, batch, cutoff)
        for name in batch:
            verdicts = [
                needed_by_path[path]
                for path in _spellings(roots, name)
                if path in needed_by_path
            ]
            if not verdicts:
                outcome.skipped_unnamed += 1
            elif any(verdicts):
                outcome.skipped_needed += 1
            else:
                unneeded.append(name)

    for index, name in enumerate(unneeded):
        if outcome.uploads_deleted + outcome.delete_failures >= _MAX_DELETES_PER_PASS:
            _resume_after = unneeded[index - 1]
            log.info(
                "Local staged upload reconciliation stopped at its per-pass budget",
                **asdict(outcome),
            )
            return
        # Outside the try below: a database error ends the pass instead of
        # letting it delete without the recheck.
        if await _row_still_needs(db, roots, name, cutoff):
            outcome.skipped_needed += 1
            continue
        try:
            deleted = await run_in_thread_draining(
                _unlink_if_unchanged, root / name, cutoff.timestamp()
            )
        except OSError as exc:
            outcome.delete_failures += 1
            log.warning(
                "Failed to delete a staged upload no ingest job still needs",
                file_name=name,
                error_type=type(exc).__name__,
            )
            continue
        if not deleted:
            outcome.skipped_changed += 1
            continue
        outcome.uploads_deleted += 1
        log.warning("Deleted a staged upload no ingest job still needs", file_name=name)
