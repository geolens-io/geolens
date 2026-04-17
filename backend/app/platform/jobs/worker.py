"""Standalone Procrastinate worker module.

Runs the worker loop with a co-located health server, job metrics collector,
stale job recovery, and graceful shutdown via Procrastinate's native
shutdown_graceful_timeout parameter.

Usage:
    python -m app.worker
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
import uvicorn
from sqlalchemy import and_, or_, select, text

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.core.runtime.staging import ensure_staging_ready

# Configure structured logging with service label
setup_logging(json_logs=settings.log_json, log_level=settings.log_level)
structlog.contextvars.bind_contextvars(service="worker")
log = structlog.get_logger()


# Stable app-unique integer used for the PostgreSQL advisory lock that
# prevents concurrent stale-job recovery across multiple worker processes.
RECOVERY_LOCK_KEY = 224_001


async def recover_stale_jobs() -> None:
    """Mark stale jobs as failed using an advisory lock + heartbeat check.

    This handles two cases:
    1. Worker was killed while processing a job (status='running', no recent
       heartbeat) — detected via last_heartbeat_at age threshold.
    2. Job was created but never queued — e.g., the HTTP request that
       would have called defer_async() got a 502 (status='pending'
       with no corresponding procrastinate task, older than 1 hour)

    An advisory lock prevents multiple workers from running recovery
    concurrently on startup (e.g., rolling restart). A worker that fails to
    acquire the lock skips recovery — another worker already holds it.

    Jobs with a recent heartbeat are NOT marked as stale, so an actively
    running job on another worker instance survives a rolling restart.

    Each recovered job is logged individually with its job_id for
    traceability.
    """
    from app.core.db import async_session
    from app.platform.jobs.models import IngestJob

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=5)
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

        # Recover running jobs whose heartbeat is older than 5 minutes.
        # Jobs with no heartbeat AND created more than 5 minutes ago are
        # also considered stale (covers the pre-heartbeat code path).
        stale_result = await session.execute(
            select(IngestJob).where(
                IngestJob.status == "running",
                or_(
                    IngestJob.last_heartbeat_at < stale_cutoff,
                    and_(
                        IngestJob.last_heartbeat_at.is_(None),
                        IngestJob.created_at < stale_cutoff,
                    ),
                ),
            )
        )
        stale_jobs = list(stale_result.scalars())
        for job in stale_jobs:
            job.status = "failed"
            job.error_message = "Stale: worker restarted while job was running"
            job.completed_at = now
            log.warning(
                "Recovered stale running job",
                job_id=str(job.id),
                last_heartbeat=str(job.last_heartbeat_at),
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

    # Sweep orphaned export temp dirs from previous crashes
    import shutil

    exports_dir = Path(settings.upload_staging_dir) / "exports"
    if exports_dir.exists():
        orphaned = list(exports_dir.iterdir())
        if orphaned:
            for item in orphaned:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            log.info("Cleaned orphaned export temp files", count=len(orphaned))

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
        except Exception as exc:
            log.error("S3 health check failed -- cannot start", error=str(exc))
            raise RuntimeError(f"S3 health check failed: {exc}") from exc

    init_cache()

    # 4. Start health server as background task
    health_task = asyncio.create_task(run_health_server())

    # 5. Start job metrics collector as background task
    metrics_task = asyncio.create_task(update_job_metrics())

    try:
        # 6. Run Procrastinate worker
        shutdown_timeout = int(os.environ.get("WORKER_SHUTDOWN_TIMEOUT", "30"))
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
