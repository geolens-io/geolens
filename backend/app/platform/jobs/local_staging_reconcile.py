"""Delete local staged uploads that no ingest job can still use.

The local counterpart of ``reconcile_orphaned_staging_objects``. It starts
from the files directly in the upload staging directory, so it finds an
upload whose delete failed or never ran, such as a worker cleanup that
errored, an ingest killed after its complete commit, or an upload request
that died between writing the file and binding it to its job.

That directory is not the upload system's alone. Operators stage manifest
seed files there, the local storage backend keeps its objects in
subdirectories, and other sweeps own their scratch. So a file is a candidate
only when its name has an upload writer's shape and a row ties it to a job:
an ``ingest_jobs`` row's ``file_path`` names it, or it is a ``{job id}_``
file whose job's row exists but never recorded a path. Every writer of a
``{job id}_`` name commits that job's row before the first byte. A file whose
job has no row is kept: an operator's seed can carry the same shape, and
nothing records which seed a manifest is copying. A candidate goes once
neither its job's row nor any row naming it can still use it.

Every API worker runs the sweeper, so the pass takes a transaction-scoped
advisory lock keyed on the staging root and returns at once when another
process holds it: no two processes scan or delete at the same time. Each pass
reads every name in the root without a stat, since directory order gives no
stable place to resume, and a heap keeps only this pass's window of names in
memory; only those are stat'ed and looked up.
"""

from __future__ import annotations

import heapq
import os
import re
import stat
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

import structlog
from sqlalchemy import and_, func, not_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.platform.jobs.models import (
    IngestJob,
    needs_staged_input,
    owed_publish_record,
)

log = structlog.get_logger()

# `{job id}_{name}` from uploads, reuploads, URL imports, manifest copies and
# `resolve_file_path`'s downloads, and `manifest_{hex}_{name}`, the name
# earlier versions gave a manifest's copy of its source.
_UPLOAD_NAME = re.compile(
    r"^(?:(?P<job>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"|manifest_[0-9a-f]{32})_.",
    re.DOTALL,
)

_MAX_CANDIDATES_PER_PASS = 20_000
_MAX_DELETES_PER_PASS = 200
# Files per row lookup; two spellings each stays far under the bind-parameter cap.
_LOOKUP_BATCH = 1000

# The name the next pass starts after, so a directory holding more candidates
# than one pass examines is covered in turn. It orders the work and decides
# nothing about what may be deleted.
_resume_after: str | None = None


class _Verdict(Enum):
    UNIDENTIFIED = "unidentified"
    NEEDED = "needed"
    UNNEEDED = "unneeded"


@dataclass
class LocalStagingReconcileOutcome:
    """What one pass over the local staging directory saw and did."""

    # False when the pass declined, or another process held the pass's lock.
    ran: bool = False
    candidates: int = 0
    uploads_deleted: int = 0
    delete_failures: int = 0
    # Nothing ties the file to a job, so nothing proves it is an upload.
    skipped_unidentified: int = 0
    # Its job's row or a row naming it can still use it, or ended too recently.
    skipped_needed: int = 0
    # Gone, rewritten or no longer a regular file when its delete came.
    skipped_changed: int = 0

    def skipped(self, verdict: _Verdict) -> None:
        if verdict is _Verdict.UNIDENTIFIED:
            self.skipped_unidentified += 1
        else:
            self.skipped_needed += 1


def _still_needed(cutoff: datetime):
    """Predicate: a row can still use the staged upload, or ended too recently.

    A failed job retries only from the path its row names, so one that never
    bound a path can't read the file. The publish follow-ups archive and then
    delete the upload a published job names, so while its row carries their
    record the upload is theirs. The age term gives the job's own cleanup, and
    any reader holding the path, the threshold's head start.
    """
    unbound_failure = and_(
        IngestJob.status == "failed",
        func.coalesce(IngestJob.file_path, "") == "",
    )
    return or_(
        and_(needs_staged_input(), not_(unbound_failure)),
        owed_publish_record().is_not(None),
        func.coalesce(IngestJob.completed_at, IngestJob.created_at) >= cutoff,
    )


def _spellings(roots: tuple[Path, ...], name: str) -> list[str]:
    """Each ``file_path`` a row may use for this file: under the root as configured, and resolved."""
    return [str(root / name) for root in roots]


def _owner_id(name: str) -> uuid.UUID | None:
    """The job a ``{job id}_`` file was written for; None for a manifest copy."""
    match = _UPLOAD_NAME.match(name)
    job = match.group("job") if match else None
    return uuid.UUID(job) if job else None


def _upload_names(root: Path) -> Iterator[str]:
    with os.scandir(root) as entries:
        for entry in entries:
            if _UPLOAD_NAME.match(entry.name):
                yield entry.name


def _window(root: Path) -> list[str]:
    """This pass's share of the upload-shaped names, in name order from the resume point.

    Bounded in memory: the directory is read once for the names after the
    resume point and, when those fall short, again for the wrap.
    """
    global _resume_after
    resume = _resume_after
    window = heapq.nsmallest(
        _MAX_CANDIDATES_PER_PASS,
        (name for name in _upload_names(root) if resume is None or name > resume),
    )
    if resume is not None and len(window) < _MAX_CANDIDATES_PER_PASS:
        window += heapq.nsmallest(
            _MAX_CANDIDATES_PER_PASS - len(window),
            (name for name in _upload_names(root) if name <= resume),
        )
    full = len(window) == _MAX_CANDIDATES_PER_PASS
    _resume_after = window[-1] if full else None
    return window


def _old_upload_files(root: Path, cutoff_ts: float) -> list[str]:
    """The upload-shaped regular files in this pass's window older than the cutoff.

    Direct children only, since exports and the storage backend's objects live
    in subdirectories, and never through a symlink.
    """
    try:
        window = _window(root)
    except FileNotFoundError:
        return []
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


async def _verdicts(
    db: AsyncSession, roots: tuple[Path, ...], names: list[str], cutoff: datetime
) -> dict[str, _Verdict]:
    """Whether each file is tied to a job and, if so, whether any row can still use it.

    The rows that count are every row naming the file and the row of the job
    its name carries. Each call reads afresh.
    """
    paths = [path for name in names for path in _spellings(roots, name)]
    needed_by_path = dict(
        (
            await db.execute(
                select(IngestJob.file_path, func.bool_or(_still_needed(cutoff)))
                .where(IngestJob.file_path.in_(paths))
                .group_by(IngestJob.file_path)
            )
        )
        .tuples()
        .all()
    )
    owner_ids = {owner for name in names if (owner := _owner_id(name))}
    owners = {}
    if owner_ids:
        owners = {
            row.id: row
            for row in await db.execute(
                select(
                    IngestJob.id,
                    IngestJob.file_path,
                    _still_needed(cutoff).label("needed"),
                ).where(IngestJob.id.in_(owner_ids))
            )
        }

    verdicts: dict[str, _Verdict] = {}
    for name in names:
        naming = [
            needed_by_path[path]
            for path in _spellings(roots, name)
            if path in needed_by_path
        ]
        owner = owners.get(_owner_id(name))
        # A `{job id}_` file whose job's row never bound a path.
        unbound = owner is not None and not owner.file_path
        if not (naming or unbound):
            verdicts[name] = _Verdict.UNIDENTIFIED
        elif any(naming) or (owner is not None and owner.needed):
            verdicts[name] = _Verdict.NEEDED
        else:
            verdicts[name] = _Verdict.UNNEEDED
    return verdicts


def _lock_key(root: Path) -> str:
    return f"staging-orphan-reconcile:local:{root.resolve()}"


async def reconcile_orphaned_local_uploads(
    db: AsyncSession, *, now: datetime | None = None
) -> LocalStagingReconcileOutcome:
    """Delete the staged uploads in the local staging directory that no job can still use.

    Only reads through ``db``, inside a savepoint, so a database error rolls
    back just this pass and leaves ``db``'s transaction usable. The advisory
    lock lives on its own session and ends with it, so a dying process
    releases it. Declines when another process holds that lock, and in
    multi-tenant mode, where row-level security hides other tenants' rows and
    their uploads would look unneeded. Never raises: a failure leaves the rest
    for the next pass.
    """
    from app.core.db import async_session  # late-bound so a test engine applies
    from app.core.tenancy import is_multi_tenant

    outcome = LocalStagingReconcileOutcome()
    if is_multi_tenant():
        return outcome
    try:
        async with async_session() as lock_session:
            locked = await lock_session.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": _lock_key(Path(settings.upload_staging_dir))},
            )
            if not locked.scalar():
                return outcome
            outcome.ran = True
            async with db.begin_nested():
                await _reconcile(
                    db, now=now or datetime.now(timezone.utc), outcome=outcome
                )
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
        for name, verdict in (await _verdicts(db, roots, batch, cutoff)).items():
            if verdict is _Verdict.UNNEEDED:
                unneeded.append(name)
            else:
                outcome.skipped(verdict)

    for index, name in enumerate(unneeded):
        if outcome.uploads_deleted + outcome.delete_failures >= _MAX_DELETES_PER_PASS:
            _resume_after = unneeded[index - 1]
            log.info(
                "Local staged upload reconciliation stopped at its per-pass budget",
                **asdict(outcome),
            )
            return
        # A fresh read, so a row committed or deleted since the batch lookup
        # counts. Outside the try below: a database error ends the pass
        # instead of letting it delete without the recheck.
        verdict = (await _verdicts(db, roots, [name], cutoff))[name]
        if verdict is not _Verdict.UNNEEDED:
            outcome.skipped(verdict)
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
