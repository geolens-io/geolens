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
from sqlalchemy import select, text

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.runtime.staging import ensure_staging_ready, redirect_tempfile_to_staging

# Redirect stdlib tempfile to the staging volume BEFORE any task module is
# imported. Otherwise the COG conversion sanity check in tasks_raster
# (`shutil.disk_usage(tempfile.mkdtemp()).free`) reads the worker's small
# `/tmp` tmpfs and rejects rasters that would fit fine on the multi-GB
# staging volume. Mirrors the same redirect in `app.api.main`.
redirect_tempfile_to_staging(settings.upload_staging_dir)

# Configure structured logging with service label
setup_logging(json_logs=settings.log_json, log_level=settings.log_level)
structlog.contextvars.bind_contextvars(service="worker")
log = structlog.get_logger()


# Stable app-unique integer used for the PostgreSQL advisory lock that
# prevents concurrent stale-job recovery across multiple worker processes.
RECOVERY_LOCK_KEY = 224_001


# ING-04 (P2-04): exports temp-dir sweep age threshold. Only entries
# whose mtime is older than this many seconds are deleted on worker
# startup. In-flight large exports younger than 1 hour survive a
# rolling worker restart; truly orphaned crash-residue gets cleaned.
# Matches the 1-hour window used by the worker stale-job recovery
# (`JOB_TIMEOUT_SECONDS` in router.py) so a 6-minute COG export that
# survives a rolling restart at the job layer also keeps its on-disk
# staging artifact.
EXPORTS_SWEEP_AGE_SECONDS = 3600  # 1 hour


def _sweep_orphaned_exports(
    exports_dir: Path,
    *,
    age_threshold_seconds: int = EXPORTS_SWEEP_AGE_SECONDS,
) -> tuple[int, int]:
    """Sweep orphaned export temp entries older than ``age_threshold_seconds``.

    ING-04 (P2-04): entries whose ``stat.st_mtime`` is within the last
    ``age_threshold_seconds`` are skipped (and logged) so an in-flight
    large export does not get truncated by a worker restart. Entries
    older than the threshold are removed (``shutil.rmtree`` for
    directories, ``Path.unlink`` for files).

    Args:
        exports_dir: The ``<staging>/exports/`` directory to sweep. A
            missing directory is treated as a no-op (no error raised).
        age_threshold_seconds: Skip entries newer than this many seconds.
            Defaults to ``EXPORTS_SWEEP_AGE_SECONDS`` (1 hour).

    Returns:
        ``(deleted_count, skipped_count)``.
    """
    import shutil

    if not exports_dir.exists():
        return (0, 0)

    entries = list(exports_dir.iterdir())
    if not entries:
        return (0, 0)

    now_ts = datetime.now(timezone.utc).timestamp()
    deleted_count = 0
    skipped_count = 0
    for item in entries:
        try:
            item_mtime = item.stat().st_mtime
        except FileNotFoundError:
            # Raced with another worker / external cleanup — treat as already-gone.
            continue
        age_seconds = now_ts - item_mtime
        if age_seconds < age_threshold_seconds:
            log.info(
                "sweep_skipped_recent_export",
                path=str(item),
                age_seconds=round(age_seconds, 1),
                threshold_seconds=age_threshold_seconds,
            )
            skipped_count += 1
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
        deleted_count += 1

    if deleted_count or skipped_count:
        log.info(
            "exports_sweep_complete",
            deleted=deleted_count,
            skipped=skipped_count,
        )
    return (deleted_count, skipped_count)


async def recover_stale_jobs() -> None:
    """Mark stale jobs as failed using an advisory lock + started_at threshold.

    IA-P0-04 (Phase 1067, option b): heartbeat column dropped. Stale detection
    relies on ``started_at < now - JOB_TIMEOUT_SECONDS`` (1 hour), matching
    the steady-state ``fail_stale_jobs`` sweep that runs every 5 minutes from
    the lifespan task ``_stale_jobs_sweeper``.

    This handles two cases:
    1. Worker was killed while processing a job (status='running' AND
       started_at older than 1 hour) — newly-started workers reclaim them
       on startup via this advisory-locked recovery path.
    2. Job was created but never queued — e.g., the HTTP request that
       would have called defer_async() got a 502 (status='pending' with
       no corresponding procrastinate task, older than 1 hour).

    An advisory lock prevents multiple workers from running recovery
    concurrently on startup (e.g., rolling restart). A worker that fails to
    acquire the lock skips recovery — another worker already holds it.

    **Rolling-deploy behavior:** Running jobs that started less than 1 hour
    ago are NOT marked stale, so a 6-minute ingest survives a rolling worker
    restart. The previous heartbeat-based logic was effectively broken
    (the column was declared but never written, so every job looked
    heartbeat-less + 5min-old after deploy and got force-killed); option (b)
    restores actively-running ingests by leaning on the existing 1h timeout.

    Each recovered job is logged individually with its job_id.
    """
    from app.core.db import async_session
    from app.platform.jobs.models import IngestJob
    from app.platform.jobs.router import JOB_TIMEOUT_SECONDS

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=JOB_TIMEOUT_SECONDS)
    pending_cutoff = now - timedelta(hours=1)

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

        # Recover running jobs whose started_at is older than 1 hour.
        # Mirrors fail_stale_jobs (router.py:39) which the lifespan
        # sweeper runs every 5 minutes for the same purpose. The advisory
        # lock ensures startup recovery and the sweeper don't collide.
        stale_result = await session.execute(
            select(IngestJob).where(
                IngestJob.status == "running",
                IngestJob.started_at < stale_cutoff,
            )
        )
        stale_jobs = list(stale_result.scalars())
        for job in stale_jobs:
            job.status = "failed"
            job.error_message = (
                f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
            )
            job.completed_at = now
            log.warning(
                "Recovered stale running job",
                job_id=str(job.id),
                started_at=str(job.started_at),
            )

        # Recover orphaned pending jobs (never queued)
        orphaned_result = await session.execute(
            select(IngestJob).where(
                IngestJob.status == "pending",
                IngestJob.created_at < pending_cutoff,
            )
        )
        orphaned_jobs = list(orphaned_result.scalars())
        for job in orphaned_jobs:
            job.status = "failed"
            job.error_message = "Stale: job was pending for over 1 hour (never queued)"
            job.completed_at = now
            log.warning(
                "Recovered orphaned pending job",
                job_id=str(job.id),
            )

        await session.commit()
        total = len(stale_jobs) + len(orphaned_jobs)
        if total:
            log.info(
                "Stale job recovery complete",
                running_recovered=len(stale_jobs),
                pending_recovered=len(orphaned_jobs),
            )


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
    """Worker entrypoint: recovery, init, health server, metrics, worker loop."""
    # Import all ORM models so the SQLAlchemy mapper registry is complete
    # before any task or relationship tries to resolve string references.
    import app.modules.auth.models  # noqa: F401
    import app.modules.audit.models  # noqa: F401
    import app.modules.catalog.datasets.domain.models  # noqa: F401
    import app.processing.embeddings.models  # noqa: F401

    from app.observability.metrics.jobs import update_job_metrics
    from app.platform.cache import init_cache
    from app.processing.ingest.tasks import task_app
    from app.platform.storage import init_storage

    # 1. Recover stale jobs from previous crash
    await recover_stale_jobs()

    # 2. Ensure staging directories exist
    ensure_staging_ready(settings.upload_staging_dir)
    ensure_staging_ready(Path(settings.upload_staging_dir) / "exports")

    # Sweep orphaned export temp dirs from previous crashes.
    # ING-04 (P2-04): only delete entries older than EXPORTS_SWEEP_AGE_SECONDS
    # (1 hour). In-flight exports started shortly before a rolling worker
    # restart survive the sweep — a 10-minute COG export is no longer
    # truncated mid-download because the new worker process happened to
    # boot during the export's stream phase.
    exports_dir = Path(settings.upload_staging_dir) / "exports"
    _sweep_orphaned_exports(exports_dir)

    # 3. Initialize providers
    init_storage()

    # Verify S3 connectivity and log credential source
    if settings.storage_provider == "s3":
        from app.platform.storage import get_storage

        storage = get_storage()
        try:
            await storage.health_check()
            import boto3 as _boto3

            _session = _boto3.Session()
            _creds = _session.get_credentials()
            cred_method = _creds.method if _creds else "unknown"
            if settings.s3_access_key_id:
                cred_method = "explicit-keys"
            log.info(
                "S3 connectivity verified",
                bucket=settings.s3_bucket,
                credential_source=cred_method,
                addressing_style=settings.s3_addressing_style,
            )
        except Exception as exc:  # broad: S3/MinIO SDK can throw varied connection/auth errors; fail-fast on worker boot
            log.error("S3 health check failed -- cannot start", error=str(exc))
            raise RuntimeError(f"S3 health check failed: {exc}") from exc

    init_cache()

    # 4. Start health server as background task
    health_task = asyncio.create_task(run_health_server())

    # 5. Start job metrics collector as background task
    metrics_task = asyncio.create_task(update_job_metrics())

    try:
        # 6. Run Procrastinate worker
        shutdown_timeout = settings.worker_shutdown_timeout
        async with task_app.open_async():
            await task_app.run_worker_async(
                queues=["priority", "ingest", "raster"],
                listen_notify=not settings.db_use_external_pooler,
                install_signal_handlers=True,
                delete_jobs="successful",
                shutdown_graceful_timeout=shutdown_timeout,
            )
    finally:
        # 7. Clean up background tasks after worker exits
        metrics_task.cancel()
        health_task.cancel()
        try:
            await asyncio.gather(metrics_task, health_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
