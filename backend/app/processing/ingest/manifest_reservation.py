"""What one manifest key currently holds, and the reservation that claims it.

fix(#1814): the apply loop used to insert its ``IngestJob`` row only after the
entry's source had been downloaded, so the check that answers "is this key
busy" and the row that makes the answer true were separated by a network
fetch. Everything that has to agree on that question lives in this module: the
key lock, the in-flight read, the staleness rule, and the two fenced exits from
the downloading stage.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import (
    stale_pending_clauses,
    stale_pending_unbound_values,
)

# `user_metadata` key naming the pre-queue stage a manifest job is in. Present
# only while the row is a reservation; `bind_reservation_to_staged_source`
# removes it, so a queued manifest job carries the same metadata shape it
# always did.
MANIFEST_STAGE_METADATA_KEY = "manifest_stage"
MANIFEST_STAGE_DOWNLOADING = "downloading"

# Reported on a reservation whose apply never came back to stage its source.
# Only reached when the row was stamped as dispatch-attempted, which a
# reservation never is; the shared settlement below picks the abandoned wording
# for every real one. It is passed anyway so the two branches cannot disagree
# about which message belongs to which state.
STALE_RESERVATION_MESSAGE = "Stale: manifest source was never staged"

# Returned to the caller whose reservation was settled by someone else while
# its download ran. Names no id: the row this attempt owned is terminal, and
# the row that replaced it belongs to a different request.
RESERVATION_LOST_MESSAGE = (
    "Manifest dataset apply lost its reservation while the source was being "
    "staged; re-apply the manifest."
)


def downloading_stage_marker() -> dict[str, str]:
    """The metadata a reservation carries between its insert and its staging."""
    return {MANIFEST_STAGE_METADATA_KEY: MANIFEST_STAGE_DOWNLOADING}


async def lock_manifest_key(db: AsyncSession, key: str) -> None:
    """Serialize check-and-reserve for one manifest key.

    fix(#1814): a transaction-scoped lock, so it is released by the commit that
    makes the reservation visible and by the rollback the apply loop runs on a
    rejected entry. The caller must end its transaction before any network I/O
    and before moving on to the next entry: two manifests listing the same two
    keys in opposite order would otherwise deadlock on each other.

    Blocking rather than ``try``: the section it guards is bounded by database
    work alone, and a waiter that gave up would have to answer the same
    question with a weaker read.
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


async def expire_stale_manifest_reservations(
    db: AsyncSession, key: str, *, now: datetime | None = None
) -> int:
    """Settle reservations for ``key`` whose apply never came back. Returns the count.

    fix(#1814): an API process that dies between the reservation commit and the
    staging bind leaves a `pending` row that would block the key until the
    background sweep reached it. This is the same rule, narrowed to one key and
    run under that key's lock, so the sweep and the in-flight check cannot
    disagree about which rows are still live: the predicates and the written
    columns both come from ``jobs/sweep.py`` rather than being restated here.

    Settling rather than ignoring is what makes
    ``bind_reservation_to_staged_source``'s fence sufficient. A merely slow
    attempt whose reservation is expired here finds its row no longer pending
    and drops its download instead of queueing on top of the reservation that
    replaced it.
    """
    now = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(IngestJob)
        .where(
            *stale_pending_clauses(now, completion_bound=False),
            IngestJob.user_metadata["manifest_key"].astext == key,
            IngestJob.user_metadata[MANIFEST_STAGE_METADATA_KEY].astext
            == MANIFEST_STAGE_DOWNLOADING,
        )
        .values(**stale_pending_unbound_values(now, message=STALE_RESERVATION_MESSAGE))
    )
    return result.rowcount or 0


async def bind_reservation_to_staged_source(
    db: AsyncSession, job: IngestJob, *, file_path: str
) -> bool:
    """Fenced downloading -> staged transition. False means the row is not ours.

    fix(#1814): the reservation must still be pending, under the attempt this
    apply reserved, and still in the downloading stage. Anything else means a
    cancel, a sweep, or a later apply's staleness settlement already owns the
    row's terminal state, and this attempt's bytes belong to nobody.
    """
    metadata = {
        name: value
        for name, value in (job.user_metadata or {}).items()
        if name != MANIFEST_STAGE_METADATA_KEY
    }
    result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job.id,
            (
                IngestJob.attempt_id == job.attempt_id
                if job.attempt_id is not None
                else IngestJob.attempt_id.is_(None)
            ),
            IngestJob.status == "pending",
            IngestJob.user_metadata[MANIFEST_STAGE_METADATA_KEY].astext
            == MANIFEST_STAGE_DOWNLOADING,
        )
        .values(file_path=file_path, user_metadata=metadata)
    )
    if not result.rowcount:
        return False
    job.file_path = file_path
    job.user_metadata = metadata
    return True
