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
# imported, or the COG sanity check in tasks_raster reads the worker's small
# `/tmp` tmpfs and rejects rasters that fit fine on the staging volume.
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

    Running workers renew ``heartbeat_at``; recovery falls back to
    ``started_at`` for pre-migration rows and only fails jobs whose liveness
    signal is older than ``JOB_TIMEOUT_SECONDS``.

    Handles two cases: (1) a worker killed mid-job, reclaimed on the next
    worker's startup; (2) a job created but never queued (e.g. the defer
    request got a 502), pending with no procrastinate task.

    An advisory lock keeps recovery single-flight across a rolling restart;
    a worker that fails to acquire it skips recovery.
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
        # pg_try_advisory_xact_lock releases automatically when the
        # transaction ends, so no explicit unlock is needed.
        lock_result = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": RECOVERY_LOCK_KEY},
        )
        if not lock_result.scalar():
            log.info("Stale job recovery skipped — another worker holds the lock")
            return

        # Mirrors fail_stale_jobs (router.py:39), which the lifespan sweeper
        # runs every 5 minutes for the same purpose; the advisory lock keeps
        # startup recovery and the sweeper from colliding.
        #
        # fix(#1778): candidate set read via its own `FOR UPDATE SKIP
        # LOCKED` subquery, mirroring fail_stale_jobs's fix for the same race
        # — a `lock_timeout` on this set-based UPDATE would abort the WHOLE
        # batch on one busy row instead of skipping just that row.
        stale_candidates = (
            select(IngestJob.id)
            .where(
                IngestJob.status == "running",
                func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                < stale_cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        stale_result = await session.execute(
            update(IngestJob)
            .where(IngestJob.id.in_(stale_candidates))
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
            # RETURNING refreshes these in production; the explicit
            # assignment also keeps lightweight session doubles representative.
            job.status = "failed"
            job.error_message = (
                f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
            )
            job.completed_at = now
            log.warning(
                "Recovered stale running job",
                job_id=str(job.id),
            )
            # fix(#1556): the fourth actor that can settle an embedding
            # backfill row (#1550 taught the other three). Matters most
            # after a hard kill, when this startup pass reaches the row
            # before any later sweep would. No-op for every other job kind.
            await audit_settled_embedding_backfill(
                session,
                job_id=job.id,
                user_metadata=job.user_metadata,
                created_by=job.created_by,
                error_code="worker_lost",
            )

        # fix(#1235): recover orphaned pending jobs (never queued) through
        # the shared clauses — this site was missing both the live-queue
        # predicate (#724) and the bound/unbound split (#1234).
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
            # fix(#1556): must reproduce the CASE the database just
            # evaluated, not a constant — a flat `job.status = "failed"`
            # here would push `failed` back over the `cancelled` the UPDATE wrote.
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
            # fix(#1556): the other half. A backfill whose dispatch never
            # landed is `pending` with no queue row — the unique index
            # counts it, holding the single active-backfill slot while its
            # trail still reads `requested`.
            await audit_settled_embedding_backfill(
                session,
                job_id=job.id,
                user_metadata=job.user_metadata,
                created_by=job.created_by,
                error_code="never_started",
            )

        # GAP-002: sweep VRT assets stuck `regenerating` past the timeout,
        # using the same stale_cutoff as the running-jobs sweep above.
        from app.platform.jobs.router import (
            _reap_stale_generation_storage,
            _reap_unadopted_analysis_outputs,
            reap_unpublished_storage_keys,
            sweep_stale_vrt_assets,
            unadopted_analysis_tables_from_metadata,
            unpublished_storage_keys_from_metadata,
        )

        (
            vrt_assets_recovered,
            vrt_gens_failed,
            stale_generation_storage_keys,
        ) = await sweep_stale_vrt_assets(session, stale_cutoff)

        await session.commit()
        # fix(#1322): reap only after the commit above lands — deleting
        # before ownership-restoring reconciliation is durable can orphan a
        # 'ready' asset against bytes a rolled-back commit never freed.
        await _reap_stale_generation_storage(stale_generation_storage_keys)
        # fix(#1778): the same treatment for a killed raster
        # ingest/replace's pre-commit objects, through the shared reaper
        # (survivor check + tenant resolution) so this pass can't delete a
        # key a live row still names. Matters more than the periodic sweep:
        # an OOM-killed worker's restart runs this before any lifespan sweeper.
        await reap_unpublished_storage_keys(
            tuple(
                key
                for job in stale_jobs
                for key in unpublished_storage_keys_from_metadata(job.user_metadata)
            )
        )
        # fix(#1778): the analysis peer, same pass/ordering.
        # (job, table) pairs so a drop can refuse a table the job it's
        # reaping didn't create; ALL names a row records, since it
        # accumulates across attempts.
        await _reap_unadopted_analysis_outputs(
            tuple(
                (job.id, name)
                for job in stale_jobs
                for name in unadopted_analysis_tables_from_metadata(job.user_metadata)
            )
        )
        total = len(stale_jobs) + len(orphaned_jobs)
        if total or vrt_assets_recovered:
            log.info(
                "Stale job recovery complete",
                running_recovered=len(stale_jobs),
                pending_recovered=len(orphaned_jobs),
                vrt_assets_recovered=vrt_assets_recovered,
                vrt_gens_failed=vrt_gens_failed,
            )


# fix(#624): a worker killed mid-job leaves its queue row in `doing` forever.
# Procrastinate 3.x tracks worker heartbeats, so "this worker is gone" is a
# fact we can read rather than a timeout to guess at — the window is
# deliberately generous, since waiting costs a stale metric but being wrong
# fails live work. Covers the final heartbeat interval (10s default) plus
# the unregister that follows the graceful wait.
_STALLED_SHUTDOWN_MARGIN_SECONDS = 60


def stalled_worker_seconds() -> int:
    """Heartbeat silence after which a worker counts as dead.

    Floored at ``JOB_TIMEOUT_SECONDS`` (60 min) — the same threshold the
    ingest_jobs reaper above already calls stale.

    fix(#624): this sweep is global, so a threshold derived from THIS
    process's config would let a general worker fail a split-queue raster
    worker's live job. Past the hour the reaper has already failed the
    user-facing ingest_jobs row, so failing the queue row too is consistent
    — no fleet-wide config coordination needed.

    fix(#624): still maxed against the local graceful window, since
    procrastinate cancels the heartbeat side task BEFORE waiting
    ``shutdown_graceful_timeout``, so a longer configured window would
    otherwise get its own long jobs swept out from under it.
    """
    from app.platform.jobs.router import JOB_TIMEOUT_SECONDS

    return max(
        JOB_TIMEOUT_SECONDS,
        settings.worker_shutdown_timeout + _STALLED_SHUTDOWN_MARGIN_SECONDS,
    )


# fix(#624): a startup-only sweep is always one restart behind — under
# `restart: unless-stopped` a crashed worker is back in seconds while its
# last heartbeat is still fresh, so the startup pass skips the row it
# exists to reap. Sweeping on an interval fails a stranded job ~1 cycle
# after it goes stale.
STALLED_QUEUE_SWEEP_INTERVAL_SECONDS = 60


async def _ingest_jobs_still_leasing(jobs: list) -> set[str]:
    """Of ``jobs``, the ingest_jobs ids whose row is provably still working.

    fix(#624): the worker heartbeat and the ingest task's own lease are
    INDEPENDENT signals — ``Worker._shutdown`` cancels the heartbeat before
    waiting out ``shutdown_graceful_timeout``, while
    ``maintain_ingest_job_heartbeat`` keeps renewing the lease. So a silent
    worker doesn't imply dead work; trust the row's own fresh lease over any
    timeout. The threshold is the backstop for jobs with no lease to read
    (non-ingest tasks carry no ``job_id``).

    fix(#624): grouped by tenant, since ``ingest_jobs`` is FORCE-RLS
    scoped — an un-tenanted SELECT sees nothing and every hosted lease would
    read as dead, the exact failure this guard exists to prevent.
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


async def _purge_stalled_queue_row_tokens(job_ids: list) -> None:
    """Drop the service tokens of the rows this sweep just failed. Never raises.

    fix(#1755 item 12): a crashed worker never reaches
    ``purge_token_on_failure``, so this transition is the first moment its
    token is provably dead weight. Without it the row waits for
    ``purge_terminal_job_tokens``, a whole API sweeper cadence later.
    """
    if not job_ids:
        return
    from app.core.db import async_session
    from app.platform.jobs.sweep import purge_queue_row_args

    try:
        async with async_session() as session:
            await purge_queue_row_args(session, job_ids)
    except Exception:  # broad: the periodic backstop still covers these rows
        log.warning(
            "Stalled queue token purge failed", job_count=len(job_ids), exc_info=True
        )


async def fail_stalled_queue_jobs() -> int:
    """Fail procrastinate rows whose worker died mid-job. Returns the count.

    The ingest_jobs reaper above gives the user a verdict, but never
    transitions the queue row, so queue depth counted phantom in-flight
    work, accumulating per worker kill. Fail rather than requeue: ingest
    tasks are not idempotency-audited.

    Caller must hold an open connector. Runs once per process, not once per
    tenant — procrastinate's queue tables aren't RLS-partitioned.
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
    failed_ids: list = []
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
        # fix(#1778): a second terminal-failed-row site, so it needs
        # its own increment — after the await, matching the wrapper's
        # ordering, since this path calls `finish_job_by_id_async` directly.
        # fix(#1778): `getattr`, not `job.queue` — an attribute read
        # outside count_failed_job's guard would abort the rest of the
        # sweep mid-loop; metrics bookkeeping must never stop a sweep.
        count_failed_job(getattr(job, "queue", None))
        failed += 1
        failed_ids.append(job.id)
        log.warning(
            "Failed stalled queue job — its worker stopped heartbeating",
            procrastinate_job_id=job.id,
            task_name=job.task_name,
        )
    await _purge_stalled_queue_row_tokens(failed_ids)
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

    fix(#1778): the completed/failed counters used to be derived from a
    ``GROUP BY status`` poll over ``procrastinate_jobs``, but this worker
    runs ``delete_jobs="successful"``, so no ``succeeded`` row (or its
    cascade-deleted events) ever survives for the poll to see. The only
    place the transition is observable is inside the process that performs
    it — ``purge_expired_terminal_jobs`` broke the failed-delta arithmetic
    the same way (r1).

    fix(#1778): hangs off the JOB MANAGER, not worker middleware —
    Procrastinate runs middleware before ``_persist_job_status``, so it
    would count a completion whose terminal row was never written. Wrapping
    ``finish_job`` counts strictly after the row lands, and leaves both
    counters untouched on exception.

    Wrapping ``finish_job`` also avoids re-deriving Procrastinate's own
    outcome: a retry goes through ``retry_job`` instead (not a failure), and
    an abort is counted as neither.

    Idempotent via a sentinel on the manager, so a re-entrant call can't
    stack wrappers and double count.
    """
    from procrastinate.jobs import Status

    manager = task_app.job_manager
    # `is True`, not truthiness — a test double/proxy answering every
    # attribute would otherwise report itself already installed.
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
            # Reading the job/status must not undo a persisted outcome.
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

    fix(#1778): the single place the failed counter moves, so the
    manager wrapper and the stalled-job sweep cannot drift apart.
    """
    try:
        from app.observability.metrics.jobs import jobs_failed_total

        jobs_failed_total.labels(queue=queue or "default").inc()
    except Exception:  # broad: a metrics failure must never change an outcome
        log.warning("Failed to count a failed job", exc_info=True)


# fix(#1778): six hours is well under the shortest sensible
# INGEST_JOBS_RETENTION_DAYS and keeps the delete's cost off the hot path.
TERMINAL_JOB_PURGE_INTERVAL_SECONDS = 6 * 3600


async def purge_expired_terminal_jobs() -> None:
    """Age out failed, cancelled and aborted queue rows and their events.

    fix(#1778): nothing deleted these before. ``delete_old_jobs`` was never
    called, and only successful jobs cleared themselves
    (``delete_jobs="successful"`` plus cascade-deleted events); every
    failure/cancellation/abort left rows forever, and the mirror row aged
    out on ``INGEST_JOBS_RETENTION_DAYS`` separately, leaving them
    unattributable.

    Keyed to the same ``INGEST_JOBS_RETENTION_DAYS`` so the queue row and
    its mirror age out together. 0 disables it.

    One unfiltered call, not one per queue: the vendored query joins
    ``procrastinate_jobs``/``procrastinate_events`` as an inline view BEFORE
    the status/age predicate, so N per-queue calls would pay for the join N times.

    Caller must hold an open connector.
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

    # MIG-02: fail closed if the schema heads are skewed from this image's
    # migration scripts. The worker doesn't run migrations itself
    # (depends_on: migrate); mirrors the API lifespan guard.
    from app.core.db.schema_skew import assert_schema_in_sync

    await assert_schema_in_sync()

    # 1. Ensure staging directories exist
    ensure_staging_ready(settings.upload_staging_dir)
    ensure_staging_ready(Path(settings.upload_staging_dir) / "exports")

    # ING-04 (P2-04): sweep orphaned export temp dirs from previous crashes,
    # only entries older than EXPORTS_SWEEP_AGE_SECONDS (1 hour) — in-flight
    # exports survive a rolling restart instead of being truncated mid-download.
    exports_dir = Path(settings.upload_staging_dir) / "exports"
    sweep_orphaned_exports(exports_dir)

    # fix(#1746): reclaim GDAL bearer-header tempfiles a
    # SIGKILL/OOM left on the container tmpfs (not the staging volume — see
    # gdal_header_dir()); boot-time is the only hook, no periodic sweep loop here.
    sweep_stale_gdal_header_files()

    # 2. WORK-01: shared bootstrap (extensions, edition, storage, cache).
    # bootstrap(app=None) = worker mode, skipping router/billing (need a
    # FastAPI app). Runs before run_worker_async so all single-slot ports
    # are resolved before any task uses them — closes the split-brain bug
    # where the worker ran community ports on licensed deployments.
    from app.platform.extensions.bootstrap import (
        bootstrap,
        assert_enterprise_ports_resolved,
    )

    await bootstrap(app=None)

    # WORK-02: under GEOLENS_EDITION=enterprise every single-slot port must
    # be non-Default; fails loud rather than silently running community ports.
    assert_enterprise_ports_resolved()

    # 3. fix(#507): recover only after bootstrap applies tenancy RLS —
    # earlier, an unqualified startup sweep could cross tenants.
    await recover_stale_jobs()

    # 4. Start health server as background task
    health_task = asyncio.create_task(run_health_server())

    # 5. Start job metrics collector as background task
    metrics_task = asyncio.create_task(update_job_metrics())

    # fix(#1778): the same two collectors the API lifespan starts, missing
    # here despite this process hosting GDAL/OGR at a 4 GB mem_limit — an
    # OOM kill left only dmesg, no gauge (#643). Also covers
    # GeoLensDbPoolSaturated, which can't fire for the worker's own engine.
    memory_metrics_task = asyncio.create_task(update_memory_metrics())
    pool_metrics_task = asyncio.create_task(update_pool_metrics())

    # fix(#1277): the worker hosts credential renewal too, since this
    # process's liveness gates the CLAIM — an API-only sweeper left a
    # healthy worker unable to claim a credential the API's downtime
    # expired. EXPIRE is idempotent, so the two hosts overlapping is cheap.
    credential_renewal_task = asyncio.create_task(renew_credentials_periodically())

    try:
        # 6. Run Procrastinate worker
        shutdown_timeout = settings.worker_shutdown_timeout
        # fix(#448): concurrency defaulted to 1, so one long COG conversion
        # head-of-line-blocked every queued upload. Both knobs are
        # env-configurable; a second worker can pin WORKER_QUEUES=raster.
        queues = [q.strip() for q in settings.worker_queues.split(",") if q.strip()]
        # fix(#1812): "ingest-auth-v2" is consumer-only this release; an override
        # that omits it strands what a v1.18.0/1.18.1 API queued there (RUNBOOK 10).
        if "ingest-auth-v2" not in queues:
            log.warning(
                "worker_queue_missing_drain_queue",
                configured_queues=queues,
                missing_queue="ingest-auth-v2",
                message=(
                    "This worker does not list ingest-auth-v2, so a credentialed "
                    "import a v1.18.0 or v1.18.1 API queued there stays todo. Add "
                    "the queue to WORKER_QUEUES until the count in RUNBOOK 10 is 0."
                ),
            )
        async with task_app.open_async():
            # fix(#1778): the only place a job outcome is observable, since
            # delete_jobs="successful" removes a row before any poll sees
            # it. Installed after the connector opens, before the worker
            # starts, so no job can finish outside the wrapper.
            install_job_outcome_counters(task_app)
            # fix(#624): inside the connector context and before the worker
            # registers, so this process's own heartbeat can never be in the
            # window it sweeps. Clears rows stranded before it existed; the
            # loop below owns rows that go stale while it runs.
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
                    # fix(#624): MUST match the sweep's own window.
                    # worker_id is ON DELETE SET NULL, and
                    # select_stalled_jobs_by_heartbeat treats a NULL
                    # worker_id as stalled OUTRIGHT — at the 30s default, a
                    # merely-stalled live worker gets pruned and its
                    # in-flight jobs fail despite our cushion. Equal windows
                    # mean NULL worker_id can only be a genuinely dead worker.
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
