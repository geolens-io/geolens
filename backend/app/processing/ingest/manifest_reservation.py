"""Whether a manifest key is busy, and the reservation that claims it.

fix(#1814): the key lock, the in-flight read, the staleness rule and the fenced
exits from the downloading stage all answer that one question, so they agree by
living together rather than by being kept in step.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS

# fix(#1814): the pre-queue stage a manifest job is in. This module's exits
# clear it; a row the running sweep or worker recovery settles keeps it, which
# is inert because the in-flight read filters on status.
MANIFEST_STAGE_METADATA_KEY = "manifest_stage"
MANIFEST_STAGE_DOWNLOADING = "downloading"

# fix(#1814): what the running sweep would have written, when a later apply
# reaches the row first.
STALE_RESERVATION_MESSAGE = "Stale: manifest source was never staged"

# fix(#1814): names no id. The row this attempt owned is terminal, and the row
# that replaced it belongs to a different request.
RESERVATION_LOST_MESSAGE = (
    "Manifest dataset apply lost its reservation while the source was being "
    "staged; re-apply the manifest."
)


def downloading_stage_marker() -> dict[str, str]:
    """The metadata a reservation carries between its insert and its staging."""
    return {MANIFEST_STAGE_METADATA_KEY: MANIFEST_STAGE_DOWNLOADING}


async def lock_manifest_key(db: AsyncSession, key: str) -> None:
    """Serialize check-and-reserve for one manifest key.

    Transaction-scoped, and blocking: the section it guards is bounded by
    database work alone. The caller must end its transaction before any network
    I/O and before the next entry, or two manifests naming the same two keys in
    opposite order deadlock on each other (fix(#1814)).
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"manifest_apply:{key}"},
    )


async def latest_in_flight_manifest_job(db: AsyncSession, key: str) -> IngestJob | None:
    """The newest queued, running, or reserved job for ``key``, if any."""
    result = await db.execute(
        select(IngestJob)
        .where(
            IngestJob.status.in_(["pending", "running"]),
            IngestJob.user_metadata["manifest_key"].astext == key,
        )
        .order_by(desc(IngestJob.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _reservation_lease_clauses(now: datetime, key: str) -> tuple:
    """Every predicate that identifies an abandoned reservation for ``key``.

    fix(#1814): the running sweep's own predicate (`jobs/sweep.py`,
    `status='running'` past ``coalesce(heartbeat_at, started_at)`` plus
    ``JOB_TIMEOUT_SECONDS``), narrowed to one key's downloading stage, so the
    sweep and the in-flight check cannot disagree about which rows are live.
    """
    return (
        IngestJob.status == "running",
        func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
        < now - timedelta(seconds=JOB_TIMEOUT_SECONDS),
        IngestJob.user_metadata["manifest_key"].astext == key,
        IngestJob.user_metadata[MANIFEST_STAGE_METADATA_KEY].astext
        == MANIFEST_STAGE_DOWNLOADING,
    )


def _without_stage_marker():
    """The row's metadata with the downloading marker removed, as SQL.

    Written as a JSONB key removal rather than from the instance, because both
    callers may hold an expired one (fix(#1814)).
    """
    return IngestJob.user_metadata.op("-", return_type=JSONB)(
        MANIFEST_STAGE_METADATA_KEY
    )


async def expire_stale_manifest_reservations(
    db: AsyncSession, key: str, *, now: datetime | None = None
) -> int:
    """Settle reservations for ``key`` whose apply never came back. Returns the count.

    fix(#1814): settling rather than ignoring is what lets
    ``bind_reservation_to_staged_source``'s fence catch a slow attempt whose
    reservation was replaced, instead of letting it queue on top.
    """
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(IngestJob)
        .where(*_reservation_lease_clauses(now, key))
        .values(
            status="failed",
            error_message=STALE_RESERVATION_MESSAGE,
            completed_at=now,
            user_metadata=_without_stage_marker(),
        )
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def bind_reservation_to_staged_source(
    db: AsyncSession, job: IngestJob, *, file_path: str, now: datetime | None = None
) -> bool:
    """Fenced downloading -> staged transition. False means the row is not ours.

    fix(#1814): ``staged_at`` is stamped in the same statement, so the pending
    sweep measures from staging rather than from a creation that predates the
    download. Anything but running under this attempt means another owner.
    """
    now = now or datetime.now(timezone.utc)
    # Snapshotted before the statement: a values() clause carrying a SQL
    # expression cannot be evaluated in Python, so the ORM would otherwise
    # expire this attribute and the mirror below would lazy-load it.
    metadata = {
        name: value
        for name, value in (job.user_metadata or {}).items()
        if name != MANIFEST_STAGE_METADATA_KEY
    }
    metadata["staged_at"] = now.isoformat()
    result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job.id,
            (
                IngestJob.attempt_id == job.attempt_id
                if job.attempt_id is not None
                else IngestJob.attempt_id.is_(None)
            ),
            IngestJob.status == "running",
            IngestJob.user_metadata[MANIFEST_STAGE_METADATA_KEY].astext
            == MANIFEST_STAGE_DOWNLOADING,
        )
        .values(
            status="pending",
            file_path=file_path,
            user_metadata=_without_stage_marker().op("||", return_type=JSONB)(
                func.jsonb_build_object("staged_at", now.isoformat())
            ),
        )
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        return False
    # fix(#1814): `set_committed_value`, not assignment. The instance has
    # to describe the row, but a dirty attribute would have the caller's own
    # commit flush a second, unfenced ORM update over the fenced one above.
    set_committed_value(job, "status", "pending")
    set_committed_value(job, "file_path", file_path)
    set_committed_value(job, "user_metadata", metadata)
    return True


async def release_manifest_reservation(
    db: AsyncSession, job: IngestJob, message: str, *, now: datetime | None = None
) -> bool:
    """Fenced running -> failed for a reservation that never staged its source.

    fix(#1814): the shared ``settle_ingest_job_failed`` fences on ``pending``,
    which a reservation is not until it binds, so the lease has its own exit. The
    trap: ``user_metadata`` is not mirrored, because reading it after the reset is
    a lazy load.
    """
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job.id,
            (
                IngestJob.attempt_id == job.attempt_id
                if job.attempt_id is not None
                else IngestJob.attempt_id.is_(None)
            ),
            IngestJob.status == "running",
            IngestJob.user_metadata[MANIFEST_STAGE_METADATA_KEY].astext
            == MANIFEST_STAGE_DOWNLOADING,
        )
        .values(
            status="failed",
            error_message=message,
            completed_at=now,
            user_metadata=_without_stage_marker(),
        )
        .execution_options(synchronize_session=False)
    )
    if not result.rowcount:
        return False
    set_committed_value(job, "status", "failed")
    set_committed_value(job, "error_message", message)
    set_committed_value(job, "completed_at", now)
    return True


async def staged_source_is_referenced(
    db: AsyncSession, job_id: uuid.UUID, *, file_path: str
) -> bool:
    """Does the committed row point at these staged bytes?

    fix(#1814): a commit can be durable in PostgreSQL and still raise on the
    acknowledgement, so the row decides. A read that fails answers True: orphaned
    bytes are reclaimable, bytes a durable row points at are not.
    """
    try:
        row = (
            await db.execute(select(IngestJob.file_path).where(IngestJob.id == job_id))
        ).one_or_none()
    except Exception:  # broad: an unreadable row is the ambiguous case
        return True
    return row is not None and row.file_path == file_path
