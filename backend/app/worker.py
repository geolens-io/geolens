"""Standalone Procrastinate worker module.

Runs the worker loop with a co-located health server, job metrics collector,
stale job recovery, and graceful shutdown via Procrastinate's native
shutdown_graceful_timeout parameter.

Usage:
    python -m app.worker
"""

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog
import uvicorn
from sqlalchemy import select

from app.config import settings
from app.logging_config import setup_logging
from app.runtime.staging import ensure_staging_ready

# Configure structured logging with service label
setup_logging(json_logs=settings.log_json, log_level=settings.log_level)
structlog.contextvars.bind_contextvars(service="worker")
log = structlog.get_logger()


async def recover_stale_jobs() -> None:
    """Mark any jobs left in 'running' state as failed.

    This handles the case where the previous worker was killed while
    processing a job. Each recovered job is logged individually with
    its job_id for traceability.
    """
    from app.database import async_session
    from app.jobs.models import IngestJob

    async with async_session() as session:
        result = await session.execute(
            select(IngestJob).where(IngestJob.status == "running")
        )
        stale_jobs = list(result.scalars())
        for job in stale_jobs:
            job.status = "failed"
            job.error_message = "Stale: worker restarted while job was running"
            job.completed_at = datetime.now(timezone.utc)
            log.warning(
                "Recovered stale running job",
                job_id=str(job.id),
            )
        await session.commit()
        if stale_jobs:
            log.info(
                "Stale job recovery complete",
                recovered_count=len(stale_jobs),
            )


async def run_health_server() -> None:
    """Run the worker health server on port 8001."""
    config = uvicorn.Config(
        "app.worker_health:app",
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
    import app.auth.models  # noqa: F401
    import app.audit.models  # noqa: F401
    import app.datasets.models  # noqa: F401
    import app.embeddings.models  # noqa: F401

    from app.cache import init_cache
    from app.ingest.tasks import task_app
    from app.metrics.jobs import update_job_metrics
    from app.storage import init_storage

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
        from app.storage import get_storage

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
