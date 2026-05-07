"""Procrastinate defer-async orphan guard (Theme H).

Callers of ``task.defer_async(...)`` in the route/service layer commit
DB state (pending ``IngestJob``, VRT ``regenerating`` status, etc.)
*before* dispatching the background task. If the Procrastinate queue is
unreachable, the exception propagates out, the already-committed state
leaks as an orphan, and the client sees a generic 500.

For ``IngestJob`` rows, stale-cleanup picks the orphan up after 60
minutes. For VRT asset state (``status="regenerating"``) there is **no**
cleanup sweep — a Procrastinate outage leaves the VRT permanently stuck
until an operator manually resets the status. This gap is what Theme H
in ``docs-internal/audits/post-impl-20260410-HANDOFF-REMAINING.md``
tracks.

This module provides a generic guard that wraps the defer call in a
try/except and invokes a caller-supplied rollback closure to revert the
committed state before re-raising as HTTP 503. Each site supplies its
own rollback because the exact state to revert differs:

- Reupload paths: mark the ``IngestJob`` row failed.
- VRT regeneration paths: revert ``vrt_asset.status`` /
  ``current_generation_id`` to their pre-mutation values AND mark the
  associated ``IngestJob`` / ``VrtGeneration`` failed.

The original RESILIENCE-2 fix (``create_vrt_job`` /
``queue_ingest_job``) used an ingest-local ``_defer_with_orphan_guard``
helper that hard-coded the IngestJob rollback. This module generalizes
that pattern so the non-ingest callers (``datasets/router_reupload.py``
and ``datasets/router_vrt.py``) can reuse it without depending on the
ingest service module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob

logger = structlog.get_logger()


DeferCallable = Callable[[], Awaitable[Any]]
"""0-arg async callable that invokes ``task.defer_async(...)``."""

RollbackCallable = Callable[[BaseException], Awaitable[None]]
"""Async callable that reverts committed DB state after a defer failure.

Receives the defer exception so the rollback can embed its details in
error messages (matches the ``f"Failed to queue ...: {exc}"`` format the
pre-existing regression tests assert on). Must *not* commit the session
— ``defer_with_orphan_guard`` commits after invoking the rollback.
"""


async def defer_with_orphan_guard(
    defer_call: DeferCallable,
    *,
    rollback: RollbackCallable,
    db: AsyncSession,
) -> None:
    """Run a ``defer_async`` call with rollback-on-failure semantics.

    On success: no-op wrapper around ``defer_call``.

    On failure:
        1. Invoke ``rollback(defer_exc)`` to revert committed state.
        2. Commit the rollback on ``db``.
        3. If the rollback itself raises, log the rollback error plus
           the original defer error (so operators see both) but still
           re-raise the 503 below so the client retries.
        4. Raise ``HTTPException 503`` chained from the defer error.

    Args:
        defer_call: 0-arg async closure that calls ``task.defer_async``.
        rollback: async closure that reverts committed state. Receives
            the defer exception for error-message embedding.
        db: session used to commit the rollback.

    Raises:
        HTTPException 503: always, when ``defer_call`` raises.
    """
    try:
        await defer_call()
    except Exception as defer_exc:  # broad: defer_async can throw various job-runner errors; orphan-guard handles all
        try:
            await rollback(defer_exc)
            await db.commit()
        except Exception:  # broad: rollback itself can fail with DB errors; log both, still surface 503 to client
            # Rollback itself failed — log the rollback error plus the
            # defer context so operators can diagnose both. Still raise
            # 503 so the client retry flow stays consistent.
            logger.exception(
                "Orphan-guard rollback failed after defer error",
                defer_error=str(defer_exc),
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue unavailable, please retry",
        ) from defer_exc


def make_ingest_job_failed_rollback(
    job: IngestJob,
    *,
    message_prefix: str = "Failed to queue ingest task",
) -> RollbackCallable:
    """Build a rollback closure that marks an ``IngestJob`` failed.

    Convenience for the common case where the only committed state to
    revert is a pending ``IngestJob`` row (reupload, vanilla ingest).
    The returned closure captures ``job`` and mutates it in-place when
    invoked — the caller is responsible for supplying ``job`` bound to
    the same session that will commit the rollback.

    The ``message_prefix`` is embedded before the defer exception string
    so ``job.error_message`` reads like
    ``"Failed to queue ingest task: <exc>"``. This format matches the
    existing ``test_queue_ingest_job_*`` regression tests.
    """

    async def _rollback(defer_exc: BaseException) -> None:
        job.status = "failed"
        job.error_message = f"{message_prefix}: {defer_exc}"
        job.completed_at = datetime.now(timezone.utc)

    return _rollback
