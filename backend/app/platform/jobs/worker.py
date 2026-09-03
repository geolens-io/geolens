"""Standalone Procrastinate worker module.

Runs the worker loop with a co-located health server, job metrics collector,
stale job recovery, and graceful shutdown via Procrastinate's native
shutdown_graceful_timeout parameter.

Usage:
    python -m app.worker
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
import uvicorn
from sqlalchemy import func, select, text, update

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.runtime.gdal_env import configure_gdal_s3_env
from app.core.runtime.staging import (
    ensure_staging_ready,
    redirect_tempfile_to_staging,
    sweep_orphaned_exports,
    sweep_stale_gdal_header_files,
)

# Redirect stdlib tempfile to the staging volume BEFORE any task module is
# imported. Otherwise the COG conversion sanity check in tasks_raster
# (`shutil.disk_usage(tempfile.mkdtemp()).free`) reads the worker's small
# `/tmp` tmpfs and rejects rasters that would fit fine on the multi-GB
# staging volume. Mirrors the same redirect in `app.api.main`.
redirect_tempfile_to_staging(settings.upload_staging_dir)

# fix(#579): before any GDAL/rasterio use — /vsis3/ reads need the custom
# S3 endpoint derived into AWS_* env, and GDAL subprocesses inherit os.environ.
configure_gdal_s3_env(settings)

# Configure structured logging with service label
setup_logging(
    json_logs=settings.log_json,
    log_level=settings.log_level,
    production=settings.is_production,
)
structlog.contextvars.bind_contextvars(service="worker")
log = structlog.get_logger()


# Stable app-unique integer used for the PostgreSQL advisory lock that
# prevents concurrent stale-job recovery across multiple worker processes.
RECOVERY_LOCK_KEY = 224_001


async def _recover_stale_jobs_for_current_scope() -> None:
    """Mark stale jobs as failed using an advisory lock + heartbeat lease.

    Running workers renew ``heartbeat_at``. Recovery falls back to
    ``started_at`` for pre-migration rows and only fails jobs whose most recent
    liveness signal is older than ``JOB_TIMEOUT_SECONDS``.

    This handles two cases:
    1. Worker was killed while processing a job (status='running' AND its
       heartbeat lease is older than 1 hour) — newly-started workers reclaim them
       on startup via this advisory-locked recovery path.
    2. Job was created but never queued — e.g., the HTTP request that
       would have called defer_async() got a 502 (status='pending' with
       no corresponding procrastinate task, older than 1 hour).

    An advisory lock prevents multiple workers from running recovery
    concurrently on startup (e.g., rolling restart). A worker that fails to
    acquire the lock skips recovery — another worker already holds it.

    **Rolling-deploy behavior:** A worker that is still renewing its lease is
    not marked stale regardless of total runtime. Pre-migration jobs retain the
    one-hour ``started_at`` fallback.

    Each recovered job is logged individually with its job_id.
    """
    from app.core.db import async_session
    from app.platform.jobs.models import IngestJob
    from app.platform.jobs.router import (
        JOB_TIMEOUT_SECONDS,
        audit_settled_embedding_backfill,
    )

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=JOB_TIMEOUT_SECONDS)

    async with async_session() as session:
        # Advisory lock: only one worker runs recovery at a time.
        # pg_try_advisory_xact_lock is released automatically when the
        # transaction ends, so no explicit unlock is needed.
        lock_result = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": RECOVERY_LOCK_KEY},
        )
        if not lock_result.scalar():
            log.info("Stale job recovery skipped — another worker holds the lock")
            return

        # Recover running jobs whose most recent liveness signal is older than
        # one hour. Pre-migration jobs fall back to started_at.
        # Mirrors fail_stale_jobs (router.py:39) which the lifespan
        # sweeper runs every 5 minutes for the same purpose. The advisory
        # lock ensures startup recovery and the sweeper don't collide.
        stale_result = await session.execute(
            update(IngestJob)
            .where(
                IngestJob.status == "running",
                func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                < stale_cutoff,
            )
            .values(
                status="failed",
                error_message=(
                    f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
                ),
                completed_at=now,
            )
            .returning(IngestJob)
        )
        stale_jobs = list(stale_result.scalars())
        for job in stale_jobs:
            # SQLAlchemy RETURNING refreshes these values in production; the
            # explicit assignments also keep lightweight session doubles
            # representative of the atomic database transition.
            job.status = "failed"
            job.error_message = (
                f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
            )
            job.completed_at = now
            log.warning(
                "Recovered stale running job",
                job_id=str(job.id),
            )
            # fix(#1556): this pass is the FOURTH actor that can settle an
            # embedding backfill row, and #1550 taught only three of them
            # (the worker's own exits, the status poll, the lifespan sweep)
            # to close the audit trail. It is also the one that matters most
            # for the case the trail exists for: after a hard kill the row is
            # usually reached by the restarted worker's startup pass, not by
            # the 5-minute lifespan sweep, and once this pass has made the row
            # terminal no later sweep will look at it again. Emitted on this
            # session so the status change and the entry commit as one, the
            # same rule `fail_stale_jobs` follows. A no-op for every other
            # kind of job.
            await audit_settled_embedding_backfill(
                session,
                job_id=job.id,
                user_metadata=job.user_metadata,
                created_by=job.created_by,
                error_code="worker_lost",
            )

        # Recover orphaned pending jobs (never queued).
        # fix(#1235 review r2): through the shared clauses, which this site
        # never had — it was missing BOTH the live-queue predicate (#724, so
        # it could fail a job whose task was merely waiting) and the
        # bound/unbound split (#1234, so it could fail a completion mid-commit
        # every time a worker booted).
        from app.platform.jobs.router import (
            ABANDONED_UPLOAD_MESSAGE,
            STALE_PENDING_UNBOUND_MESSAGE,
            is_abandoned_upload,
            stale_pending_clauses,
            stale_pending_unbound_values,
        )

        orphaned_result = await session.execute(
            update(IngestJob)
            .where(*stale_pending_clauses(now, completion_bound=False))
            .values(
                **stale_pending_unbound_values(
                    now, message=STALE_PENDING_UNBOUND_MESSAGE
                )
            )
            .returning(IngestJob)
        )
        orphaned_jobs = list(orphaned_result.scalars())
        for job in orphaned_jobs:
            # fix(#1556): the mirror has to reproduce the CASE the database
            # just evaluated, not a constant. These assignments exist to keep
            # lightweight session doubles representative (see the running half
            # above), but they are writes to a persistent instance either way —
            # a flat `job.status = "failed"` here would mark the object dirty
            # and push `failed` back over the `cancelled` the UPDATE wrote.
            abandoned = is_abandoned_upload(job.user_metadata)
            job.status = "cancelled" if abandoned else "failed"
            job.error_message = (
                ABANDONED_UPLOAD_MESSAGE if abandoned else STALE_PENDING_UNBOUND_MESSAGE
            )
            job.completed_at = now
            log.warning(
                "Recovered orphaned pending job",
                job_id=str(job.id),
                status=job.status,
            )
            # fix(#1556): the other half, same reason. A backfill whose
            # dispatch never landed is `pending` with no queue row, which is
            # exactly what this clause reaps — and the unique index counts
            # pending, so the row is holding the single active-backfill slot
            # while its trail still reads `requested`.
            await audit_settled_embedding_backfill(
                session,
                job_id=job.id,
                user_metadata=job.user_metadata,
                created_by=job.created_by,
                error_code="never_started",
            )

        # GAP-002: sweep VRT assets stuck in status='regenerating' past the timeout.
        # Uses the same stale_cutoff as the running-jobs sweep so the window is
        # consistent — mirrors the fail_stale_jobs periodic sweep.
        from app.platform.jobs.router import (
            _reap_stale_generation_storage,
            sweep_stale_vrt_assets,
        )

        (
            vrt_assets_recovered,
            vrt_gens_failed,
            stale_generation_storage_keys,
        ) = await sweep_stale_vrt_assets(session, stale_cutoff)

        await session.commit()
        # fix(#1322 review): reap only after the commit above lands — deleting
        # a dead attempt's storage objects before the reconciliation that
        # restored ownership is durable can orphan a 'ready' asset against
        # bytes a rolled-back commit never actually freed for deletion.
        await _reap_stale_generation_storage(stale_generation_storage_keys)
        total = len(stale_jobs) + len(orphaned_jobs)
        if total or vrt_assets_recovered:
            log.info(
                "Stale job recovery complete",
                running_recovered=len(stale_jobs),
                pending_recovered=len(orphaned_jobs),
                vrt_assets_recovered=vrt_assets_recovered,
                vrt_gens_failed=vrt_gens_failed,
            )


# fix(#624): a worker killed mid-job leaves its queue row in `doing` forever —
# the demo carried one from 2026-06-29 for three weeks. Procrastinate 3.x tracks
# worker heartbeats, so "this worker is gone" is a fact we can read rather than a
# timeout we have to guess at. The cost of waiting is a stale metric; the cost of
# being wrong is failing live work — so the window is deliberately generous.
#
# Cushion over the graceful-shutdown window: covers the final heartbeat interval
# (10s by default) plus the unregister that follows the graceful wait.
_STALLED_SHUTDOWN_MARGIN_SECONDS = 60


def stalled_worker_seconds() -> int:
    """Heartbeat silence after which a worker counts as dead.

    Floored at ``JOB_TIMEOUT_SECONDS`` — the same 60 minutes the ingest_jobs
    reaper above already calls stale.

    fix(#624 codex P1 r4): this sweep is global — no queue filter, and the prune
    touches every worker row — so a threshold derived from THIS process's config
    would let a general worker fail a split-queue raster worker's live job.
    ``WORKER_QUEUES`` exists precisely so those pools run with different settings,
    and nothing in procrastinate's schema exposes another worker's shutdown
    window to read. The hour dissolves that rather than papering over it: no
    plausible graceful window reaches it, and past it the reaper has already
    failed the user-facing ingest_jobs row — so failing the queue row is the
    CONSISTENT verdict, which was the point of this sweep to begin with. That
    also means no fleet-wide config coordination is required for correctness.

    Still maxed against the local graceful window (fix(#624 codex P2 r3)):
    procrastinate cancels the heartbeat side task BEFORE waiting
    ``shutdown_graceful_timeout`` (``Worker._shutdown``), so an operator who sets
    a window longer than an hour on this process would otherwise have its own
    long jobs swept out from under a shutdown it explicitly configured.
    """
    from app.platform.jobs.router import JOB_TIMEOUT_SECONDS

    return max(
        JOB_TIMEOUT_SECONDS,
        settings.worker_shutdown_timeout + _STALLED_SHUTDOWN_MARGIN_SECONDS,
    )


# fix(#624 codex P2): a startup-only sweep is always one restart behind. Under
# `restart: unless-stopped` (and Kubernetes) a crashed worker is back in seconds,
# while the dead worker's last heartbeat is still fresh — so the startup pass
# skips the very row it exists to reap, and nothing looks again. Sweeping on an
# interval means a job stranded mid-run is failed ~1 cycle after it goes stale.
STALLED_QUEUE_SWEEP_INTERVAL_SECONDS = 60


async def _ingest_jobs_still_leasing(jobs: list) -> set[str]:
    """Of ``jobs``, the ingest_jobs ids whose row is provably still working.

    fix(#624 codex P2 r5): procrastinate's worker heartbeat and the ingest task's
    own lease are INDEPENDENT signals. ``Worker._shutdown`` cancels the worker
    heartbeat and only then waits out ``shutdown_graceful_timeout``, while
    ``maintain_ingest_job_heartbeat`` keeps renewing the ingest_jobs lease for
    the whole window. So a silent worker does not imply dead work, and in a
    split-queue fleet whose raster pool configures a shutdown longer than our
    threshold, a timeout alone would fail a job that is still running.

    Trust the work's own liveness signal over any timeout: a row that is
    ``running`` on a fresh lease is alive, and no window arithmetic overrides
    that. The threshold remains the backstop for jobs with no lease to read —
    non-ingest tasks such as embeddings carry no ``job_id``.

    fix(#624 codex P2 r6): grouped by tenant. In hosted mode ``ingest_jobs`` is
    FORCE-RLS scoped by ``app.current_tenant``, so an un-tenanted SELECT sees
    nothing and every hosted lease would read as dead — the exact live-work
    failure this guard exists to prevent. ``defer_async_with_tenant`` threads
    ``tenant_id`` into the job kwargs (see ``tenant_task``), so each group runs
    under its own context; single-tenant jobs carry no tenant_id and
    ``tenant_job_context`` is a hard no-op there anyway.
    """
    import uuid as uuid_mod

    # tenant_id (None in single-tenant) -> ingest_jobs ids deferred under it.
    by_tenant: dict[str | None, set[uuid_mod.UUID]] = {}
    for job in jobs:
        # NB: the DB column is `args`, but Job.from_row maps it to `task_kwargs`.
        kwargs = getattr(job, "task_kwargs", None)
        if not isinstance(kwargs, dict):
            continue
        raw = kwargs.get("job_id")
        if not raw:
            continue
        try:
            job_uuid = uuid_mod.UUID(str(raw))
        except ValueError:  # not an ingest task's job_id — no lease to read
            continue
        tenant = kwargs.get("tenant_id")
        by_tenant.setdefault(str(tenant) if tenant else None, set()).add(job_uuid)
    if not by_tenant:
        return set()

    from app.core.db.tenant_session import tenant_job_context

    alive: set[str] = set()
    for tenant_id, ids in by_tenant.items():
        try:
            if tenant_id is None:
                alive |= await _leasing_ingest_job_ids(ids)
            else:
                with tenant_job_context(tenant_id):
                    alive |= await _leasing_ingest_job_ids(ids)
        except Exception:  # broad: one tenant's lookup must not strand the rest
            # Liveness unknown → treat as alive. An unreaped row is a stale
            # metric; a wrongly reaped one is lost work.
            log.warning(
                "Lease lookup failed — leaving those queue jobs alone this cycle",
                tenant_id=tenant_id,
                exc_info=True,
            )
            alive |= {str(i) for i in ids}
    return alive


async def _leasing_ingest_job_ids(ids: set) -> set[str]:
    """Ids among ``ids`` whose ingest_jobs row is ``running`` on a fresh lease."""
    from app.core.db import async_session
    from app.platform.jobs.models import IngestJob
    from app.platform.jobs.router import JOB_TIMEOUT_SECONDS

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=JOB_TIMEOUT_SECONDS)
    async with async_session() as session:
        rows = await session.execute(
            select(IngestJob.id).where(
                IngestJob.id.in_(ids),
                IngestJob.status == "running",
                func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at) >= cutoff,
            )
        )
        return {str(row[0]) for row in rows.all()}


async def fail_stalled_queue_jobs() -> int:
    """Fail procrastinate rows whose worker died mid-job. Returns the count.

    The ingest_jobs reaper above already gives the USER a verdict ("Stale:
    running for over 60 minutes"), but nothing ever transitioned the queue row,
    so queue depth and admin views counted phantom in-flight work — one more per
    worker kill, accumulating forever.

    Fail rather than requeue: ingest tasks are not idempotency-audited, and
    failing matches the verdict the user already got.

    Caller must hold an open connector (``task_app.open_async()``). Runs once per
    process rather than once per tenant — procrastinate's queue tables are shared
    infrastructure, not RLS-partitioned like ingest_jobs.
    """
    from procrastinate.jobs import Status

    from app.processing.ingest.tasks import task_app

    manager = task_app.job_manager
    # One value for both calls in this sweep AND for run_worker_async's
    # stalled_worker_timeout — see that call site for why they must agree.
    seconds = stalled_worker_seconds()
    stalled = list(await manager.get_stalled_jobs(seconds_since_heartbeat=seconds))
    alive = await _ingest_jobs_still_leasing(stalled)
    failed = 0
    for job in stalled:
        if job.id is None:  # unpersisted job — nothing to transition
            continue
        kwargs = job.task_kwargs if isinstance(job.task_kwargs, dict) else {}
        if str(kwargs.get("job_id")) in alive:
            log.info(
                "Skipping stalled queue job — its ingest job is still leasing",
                procrastinate_job_id=job.id,
                ingest_job_id=str(kwargs.get("job_id")),
            )
            continue
        await manager.finish_job_by_id_async(
            job_id=job.id, status=Status.FAILED, delete_job=False
        )
        # fix(#1778 codex r1): the second site that writes a terminal failed
        # row. The metrics poll used to see it on its next pass; a transition
        # count has to be told. fix(#1778 codex r2): after the await, so a
        # persistence failure raises above this line and counts nothing --
        # matching the manager wrapper's ordering. This path calls
        # `finish_job_by_id_async` directly and so never passes through that
        # wrapper, which is why the increment is written out here.
        #
        # fix(#1778 codex r5): `getattr`, not `job.queue`. count_failed_job
        # guards the registry call, but the attribute read happened at the call
        # site and outside that guard, so a job object without the attribute
        # raised here -- mid-loop, after some rows had already been failed, and
        # aborting the rest of the sweep. Metrics bookkeeping must never be the
        # thing that stops a sweep; an unlabelled failure counts as "default".
        count_failed_job(getattr(job, "queue", None))
        failed += 1
        log.warning(
            "Failed stalled queue job — its worker stopped heartbeating",
            procrastinate_job_id=job.id,
            task_name=job.task_name,
        )
    # Drop the dead workers' rows too, so the heartbeat table doesn't grow one
    # tombstone per killed worker.
    pruned = await manager.prune_stalled_workers(seconds_since_heartbeat=seconds)
    if failed or pruned:
        log.info(
            "Stalled queue sweep complete",
            jobs_failed=failed,
            jobs_skipped_alive=len(stalled) - failed,
            workers_pruned=len(pruned),
        )
    return failed


async def _sweep_stalled_queue_safely() -> None:
    """Run one sweep; never let a failure block startup or kill the loop."""
    try:
        await fail_stalled_queue_jobs()
    except Exception:  # broad: best-effort housekeeping, never fatal to the worker
        log.warning("Stalled queue sweep failed", exc_info=True)


async def run_stalled_queue_sweeps() -> None:
    """Sweep stalled queue rows on an interval for the life of the worker.

    Sleeps first: the caller runs the startup pass itself, and re-sweeping
    immediately would find nothing new.
    """
    while True:
        await asyncio.sleep(STALLED_QUEUE_SWEEP_INTERVAL_SECONDS)
        await _sweep_stalled_queue_safely()


async def _registered_tenant_ids_for_recovery() -> list[str]:
    """Read the global tenant registry without touching an RLS child table."""
    from app.core.db import async_session

    async with async_session() as session:
        result = await session.execute(
            text("SELECT id FROM catalog.tenants ORDER BY id")
        )
        return [str(tenant_id) for tenant_id in result.scalars()]


async def recover_stale_jobs() -> None:
    """Recover stale jobs once globally or once per hosted tenant.

    The historical single-tenant path remains one direct recovery call. In
    hosted mode ``ingest_jobs`` is FORCE-RLS protected, so each recovery must
    run with an active tenant GUC. A failure is isolated to that tenant and is
    logged before recovery continues for the rest of the fleet.
    """
    from app.core.db.tenant_session import tenant_job_context
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        await _recover_stale_jobs_for_current_scope()
        return

    for tenant_id in await _registered_tenant_ids_for_recovery():
        try:
            with tenant_job_context(tenant_id):
                await _recover_stale_jobs_for_current_scope()
        except Exception as exc:  # broad: startup recovery continues per tenant
            log.warning(
                "Stale job recovery failed for tenant",
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=True,
            )


_OUTCOME_COUNTERS_ATTR = "_geolens_job_outcome_counters_installed"


def install_job_outcome_counters(task_app) -> None:
    """Count a job's outcome once its terminal row is written, not before.

    fix(#1778): ``geolens_jobs_completed_total`` used to be derived from a
    ``SELECT status, COUNT(*) ... GROUP BY status`` over
    ``catalog.procrastinate_jobs``. It could never move, because this worker
    runs with ``delete_jobs="successful"``: ``procrastinate_finish_job_v1``
    deletes the row while it is still ``doing``, so no ``succeeded`` row is
    ever written for the poll to see. The events the trigger writes are
    cascade-deleted with it, so they are not a source either. The only place
    the transition is observable is inside the process that performs it.

    fix(#1778 codex r1): ``geolens_jobs_failed_total`` is counted here too, and
    the poll's ``failed`` delta is gone. That delta was snapshot arithmetic
    over a row count, and ``purge_expired_terminal_jobs`` makes a queue's
    failed group shrink, so ``_prev_counts`` kept the pre-purge figure and the
    next burst produced a non-positive delta the counter never saw --
    ``GeoLensJobFailures`` with it.

    fix(#1778 codex r2): and it hangs off the JOB MANAGER, not off a worker
    middleware. Procrastinate runs worker middleware inside
    ``Worker._process_job``'s ``try``, which is before ``_persist_job_status``,
    so a middleware that counted there reported a completion for a job whose
    terminal row had not been written and might never be -- and the failure
    branch had the same ordering. ``_persist_job_status`` reaches the database
    through ``job_manager.finish_job``, so wrapping that method counts strictly
    after the row lands, and an exception on the way through leaves both
    counters untouched.

    Wrapping ``finish_job`` also removes the need to re-derive Procrastinate's
    own outcome decision. A retry goes through ``retry_job`` instead and never
    arrives here, so a retried attempt is not a failure; an abort arrives with
    ``Status.ABORTED`` and is counted as neither. The status is the one
    Procrastinate computed, not one this module inferred.

    Idempotent via a sentinel on the manager, mirroring the other install
    helpers, so a re-entrant call cannot stack wrappers and double count.
    """
    from procrastinate.jobs import Status

    manager = task_app.job_manager
    # `is True`, not truthiness: the sentinel is one this function sets, and an
    # object that answers every attribute (a test double, a proxy) would
    # otherwise report itself already installed and silently count nothing.
    if getattr(manager, _OUTCOME_COUNTERS_ATTR, False) is True:
        return
    original_finish_job = manager.finish_job

    async def _finish_job_and_count(*args, **kwargs):
        await original_finish_job(*args, **kwargs)
        # Only after the await: a persistence failure raises above this line
        # and neither counter moves.
        try:
            job = kwargs.get("job") if "job" in kwargs else (args[0] if args else None)
            status = (
                kwargs.get("status")
                if "status" in kwargs
                else (args[1] if len(args) > 1 else None)
            )
            queue = getattr(job, "queue", None)
            if status == Status.SUCCEEDED:
                count_completed_job(queue)
            elif status == Status.FAILED:
                count_failed_job(queue)
        except Exception:  # broad: the terminal row is already written
            # Reading the job or the status must not undo a persisted outcome.
            # The count_* helpers guard the registry call; this guards
            # everything before it.
            log.warning("Failed to count a job outcome", exc_info=True)

    manager.finish_job = _finish_job_and_count
    setattr(manager, _OUTCOME_COUNTERS_ATTR, True)


def count_completed_job(queue: str | None) -> None:
    """Record one completed job on *queue*.

    Never let a metrics failure change a job's outcome: a Prometheus registry
    problem costs a log line rather than a re-run of a finished ingest.
    """
    try:
        from app.observability.metrics.jobs import jobs_completed_total

        jobs_completed_total.labels(queue=queue or "default").inc()
    except Exception:  # broad: a metrics failure must never change an outcome
        log.warning("Failed to count a completed job", exc_info=True)


def count_failed_job(queue: str | None) -> None:
    """Record one terminal failure on *queue*.

    fix(#1778 codex r1): the single place the failed counter moves, so the
    manager wrapper and the stalled-job sweep cannot drift apart.
    """
    try:
        from app.observability.metrics.jobs import jobs_failed_total

        jobs_failed_total.labels(queue=queue or "default").inc()
    except Exception:  # broad: a metrics failure must never change an outcome
        log.warning("Failed to count a failed job", exc_info=True)


# fix(#1778): how often to age out terminal queue rows. Six hours is a long way
# under the shortest sensible INGEST_JOBS_RETENTION_DAYS and keeps the delete's
# cost off the hot path; the window itself is the retention setting, not this.
TERMINAL_JOB_PURGE_INTERVAL_SECONDS = 6 * 3600


async def purge_expired_terminal_jobs() -> None:
    """Age out failed, cancelled and aborted queue rows and their events.

    fix(#1778): nothing in the repository ever deleted these. Procrastinate's
    ``delete_old_jobs`` is never called, there is no pg_cron, no CronJob, no
    scheduled workflow and no periodic Procrastinate task, and
    ``POST /jobs/cleanup/stale/`` sweeps only the ``ingest_jobs`` MIRROR. So a
    successful job left nothing behind (``delete_jobs="successful"`` plus the
    ON DELETE CASCADE on the events fkey) while every failure, cancellation and
    abort left one job row plus three event rows forever. Meanwhile
    ``INGEST_JOBS_RETENTION_DAYS`` deleted the mirror row after 30 days, so
    what remained was also unattributable.

    The clearest sign it was an oversight rather than a decision is inside
    ``fail_stalled_queue_jobs``: it writes a permanent FAILED row and then,
    eight lines later, prunes ``procrastinate_workers`` so the heartbeat table
    "doesn't grow one tombstone per killed worker".

    Keyed to the same ``INGEST_JOBS_RETENTION_DAYS`` the mirror uses, so the
    queue row and the row that explains it age out together. 0 disables it,
    matching the mirror sweep.

    One unfiltered call rather than one per queue: the vendored query builds
    ``SELECT DISTINCT ON (job.id) job.*, event.at FROM procrastinate_jobs job
    JOIN procrastinate_events event ...`` as an inline view BEFORE applying the
    status and age predicate, so the join and sort happen whatever the queue
    filter is -- N per-queue calls would pay for it N times.

    Caller must hold an open connector (``task_app.open_async()``).
    """
    from app.processing.ingest.tasks import task_app

    days = settings.ingest_jobs_retention_days
    if days <= 0:
        return
    await task_app.job_manager.delete_old_jobs(
        nb_hours=days * 24,
        include_failed=True,
        include_cancelled=True,
        include_aborted=True,
    )
    log.info("Purged expired terminal queue jobs", retention_days=days)


async def _purge_terminal_jobs_safely() -> None:
    """Run one purge; never let a failure kill the loop or block startup."""
    try:
        await purge_expired_terminal_jobs()
    except Exception:  # broad: best-effort housekeeping, never fatal to the worker
        log.warning("Terminal queue job purge failed", exc_info=True)


async def run_terminal_job_purges() -> None:
    """Purge terminal queue rows on an interval for the life of the worker.

    Sleeps first, like ``run_stalled_queue_sweeps``: the caller runs the
    startup pass itself.
    """
    while True:
        await asyncio.sleep(TERMINAL_JOB_PURGE_INTERVAL_SECONDS)
        await _purge_terminal_jobs_safely()


async def run_health_server() -> None:
    """Run the worker health server on port 8001."""
    config = uvicorn.Config(
        "app.observability.health.worker:app",
        host="0.0.0.0",
        port=8001,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    """Worker entrypoint: init, recovery, health server, metrics, worker loop."""
    # Import all ORM models so the SQLAlchemy mapper registry is complete
    # before any task or relationship tries to resolve string references.
    import app.modules.auth.models  # noqa: F401
    import app.modules.audit.models  # noqa: F401
    import app.modules.catalog.datasets.domain.models  # noqa: F401
    import app.processing.embeddings.models  # noqa: F401

    from app.observability.metrics.jobs import update_job_metrics
    from app.observability.metrics.memory import update_memory_metrics
    from app.observability.metrics.pool import update_pool_metrics
    from app.platform.refresh.credentials import renew_credentials_periodically
    from app.processing.ingest.tasks import task_app

    # MIG-02: fail closed before touching the DB if the schema heads are skewed
    # from this image's migration scripts. The worker does not run migrations
    # itself (depends_on: migrate); this guard refuses to start a worker whose
    # image disagrees with the DB schema (in either direction), mirroring the
    # API lifespan guard so the two entrypoints cannot drift.
    from app.core.db.schema_skew import assert_schema_in_sync

    await assert_schema_in_sync()

    # 1. Ensure staging directories exist
    ensure_staging_ready(settings.upload_staging_dir)
    ensure_staging_ready(Path(settings.upload_staging_dir) / "exports")

    # Sweep orphaned export temp dirs from previous crashes.
    # ING-04 (P2-04): only delete entries older than EXPORTS_SWEEP_AGE_SECONDS
    # (1 hour). In-flight exports started shortly before a rolling worker
    # restart survive the sweep — a 10-minute COG export is no longer
    # truncated mid-download because the new worker process happened to
    # boot during the export's stream phase.
    exports_dir = Path(settings.upload_staging_dir) / "exports"
    sweep_orphaned_exports(exports_dir)

    # fix(#1746): reclaim GDAL bearer-header tempfiles a SIGKILL/OOM left
    # behind on a previous ogr2ogr run (see sweep_stale_gdal_header_files
    # docstring). The worker has no periodic sweep loop, unlike the API, so
    # boot-time is the only hook here — matches how sweep_orphaned_exports
    # itself is only swept at worker boot, not on a cadence.
    # fix(#1746 codex r2): the container tmpfs, not the staging volume — see
    # gdal_header_dir(); staging is backed up every cycle and /tmp is not.
    sweep_stale_gdal_header_files()

    # 2. WORK-01: shared bootstrap — load extensions (overlay), check enterprise
    # overlay requested, init edition, init storage + S3 health probe, init cache.
    # bootstrap(app=None) = worker mode: skips router include and billing dispatch
    # (both require a FastAPI app object). Runs BEFORE run_worker_async so all
    # single-slot ports (ProcessingPort, CatalogPort, etc.) are resolved by the
    # time any task tries to use them — closing the enterprise split-brain bug
    # where the worker silently ran community ports on licensed deployments.
    from app.platform.extensions.bootstrap import (
        bootstrap,
        assert_enterprise_ports_resolved,
    )

    await bootstrap(app=None)

    # WORK-02: affirmative post-bootstrap assertion — under GEOLENS_EDITION=enterprise
    # every expected single-slot port must be a non-Default implementation.
    # Fails loud (RuntimeError) rather than silently running community ports.
    assert_enterprise_ports_resolved()

    # 3. fix(#507): recover only after bootstrap has applied tenancy RLS.
    # Tenant-scoped recovery relies on FORCE RLS and the tenant GUC; running it
    # before bootstrap could let an unqualified startup sweep cross tenants.
    await recover_stale_jobs()

    # 4. Start health server as background task
    health_task = asyncio.create_task(run_health_server())

    # 5. Start job metrics collector as background task
    metrics_task = asyncio.create_task(update_job_metrics())

    # fix(#1778): the same two collectors the API lifespan starts. This process
    # is the one that most needs them -- it hosts GDAL/OGR and gets a 4 GB
    # mem_limit against the API's 2 GB precisely because a large raster ingest
    # is memory-hungry -- and it had neither. An OOM-killed worker left exactly
    # the symptom #643 was filed for: nothing in `docker logs`, no gauge, only
    # dmesg. update_memory_metrics also WARNs on crossing the watermark, so
    # runaway growth is diagnosable without a Prometheus scrape.
    #
    # The worker runs its own engine and pool, so GeoLensDbPoolSaturated
    # (infra/monitoring/alerts.yml) could never fire for it either. Both loops
    # are no-ops off Linux and neither needs multiprocess mode.
    memory_metrics_task = asyncio.create_task(update_memory_metrics())
    pool_metrics_task = asyncio.create_task(update_pool_metrics())

    # fix(#1277 review round 4): the worker hosts credential renewal too. The
    # process whose liveness gates the CLAIM is this one, so renewing here
    # keeps a queued handoff alive exactly while a claim is still possible —
    # the API sweeper alone left a healthy worker unable to claim a credential
    # the API's own downtime had expired. Same helper, and EXPIRE is
    # idempotent, so the two hosts overlapping costs one round trip.
    credential_renewal_task = asyncio.create_task(renew_credentials_periodically())

    try:
        # 6. Run Procrastinate worker
        shutdown_timeout = settings.worker_shutdown_timeout
        # fix(#448): concurrency was implicitly 1 (Procrastinate default), so a
        # single long COG conversion head-of-line-blocked every queued upload
        # across all three queues. Both knobs are env-configurable; a second
        # worker service can pin WORKER_QUEUES=raster on multi-core hosts.
        queues = [q.strip() for q in settings.worker_queues.split(",") if q.strip()]
        async with task_app.open_async():
            # fix(#1778): the only place a job outcome is observable --
            # delete_jobs="successful" removes a succeeded row (and its events,
            # by cascade) before any poll can see it, and the failed count is a
            # transition too now that terminal rows are purged. Installed
            # before the worker starts and after the connector is open, so no
            # job can finish outside the wrapper. See
            # install_job_outcome_counters.
            install_job_outcome_counters(task_app)
            # fix(#624): inside the connector context (it needs an open pool) and
            # before the worker registers itself, so this process's own heartbeat
            # can never be in the window it sweeps. This pass clears rows stranded
            # before this process existed; the loop below owns the ones that go
            # stale while it runs.
            await _sweep_stalled_queue_safely()
            # fix(#1778): early, before the jobs-by-events join this query
            # builds has a large table to sort.
            await _purge_terminal_jobs_safely()
            sweep_task = asyncio.create_task(run_stalled_queue_sweeps())
            purge_task = asyncio.create_task(run_terminal_job_purges())
            try:
                await task_app.run_worker_async(
                    queues=queues,
                    concurrency=settings.worker_concurrency,
                    listen_notify=not settings.db_use_external_pooler,
                    install_signal_handlers=True,
                    delete_jobs="successful",
                    shutdown_graceful_timeout=shutdown_timeout,
                    # fix(#624 codex P1): MUST match the sweep's own window.
                    # Procrastinate's Worker.run() prunes workers silent for
                    # longer than this. procrastinate_jobs.worker_id is ON DELETE
                    # SET NULL, and select_stalled_jobs_by_heartbeat treats a
                    # `doing` job with a NULL worker_id as stalled OUTRIGHT — no
                    # heartbeat comparison, because there is no longer a heartbeat
                    # to compare. So at the 30s default, a live worker that merely
                    # stalls (DB blip, long GC) gets pruned by another worker's
                    # startup, its in-flight jobs go worker_id=NULL, and the sweep
                    # fails them as stalled despite our cushion. Equal windows mean
                    # a NULL worker_id can only mean a genuinely dead worker.
                    stalled_worker_timeout=stalled_worker_seconds(),
                )
            finally:
                # Cancel inside the connector context — a sweep mid-query when
                # the pool closes would raise on the way out.
                sweep_task.cancel()
                purge_task.cancel()
                await asyncio.gather(sweep_task, purge_task, return_exceptions=True)
    finally:
        # 7. Clean up background tasks after worker exits
        metrics_task.cancel()
        memory_metrics_task.cancel()
        pool_metrics_task.cancel()
        credential_renewal_task.cancel()
        health_task.cancel()
        try:
            await asyncio.gather(
                metrics_task,
                memory_metrics_task,
                pool_metrics_task,
                credential_renewal_task,
                health_task,
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
