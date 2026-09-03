# ruff: noqa: E402
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import structlog

# Must run BEFORE FastAPI/Starlette imports — see redirect_tempfile_to_staging
# docstring. Originally added inline for gh #101 (260508-rr5), now shared with
# the worker (which had the same /tmp tmpfs problem during COG conversion).
from app.core.config import settings
from app.core.runtime.gdal_env import configure_gdal_s3_env
from app.core.runtime.staging import redirect_tempfile_to_staging

redirect_tempfile_to_staging(settings.upload_staging_dir)
# fix(#579): before any GDAL/rasterio import — /vsis3/ reads need the custom
# S3 endpoint derived into AWS_* env, and subprocesses inherit os.environ.
configure_gdal_s3_env(settings)

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.observability.metrics import (
    init_metrics,
    shutdown_worker_metrics,
    sweep_dead_worker_metrics,
)

# settings already imported above for the tempdir override — do NOT reimport
# fix(#909): async_session/engine are late-bound inside each function that
# uses them. A module-scope `from app.core.db import ...` snapshots the
# dev-DB objects before the test fixture rebinds app.core.db, so lifespan
# seed functions in tests would silently hit the dev database.
from app.core.async_io import run_in_thread_draining
from app.core.db.tenant_session import tenant_job_context
from app.core.logging_config import setup_logging
from app.core.tenancy import is_multi_tenant
from app.api.no_compress_export import NoCompressionForExportMiddleware
from app.core.runtime.staging import (
    EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
    ensure_staging_ready,
    sweep_orphaned_exports,
    sweep_orphaned_write_scratch_occasionally,
    sweep_stale_gdal_header_files,
)
from app.platform.extensions.bootstrap import (
    assert_enterprise_ports_resolved,
    bootstrap,
)
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.providers.local import hash_password
from app.platform.ratelimit import limiter
from app.processing.ingest.tasks import task_app
from app.api.middleware.body_limit import RequestBodyLimitMiddleware
from app.api.middleware.cors import DynamicCORSMiddleware
from app.api.middleware.logging import RequestLoggingMiddleware, safe_access_log_path
from app.api.middleware.security import SecurityHeadersMiddleware
from app.api.middleware.tenant_context import TenantContextMiddleware
from app.processing.tiles.pool import close_tile_pool, init_tile_pool
from app.processing.tiles.router import _titiler_client
from app.standards.ogc.utils import standards_api_path
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import slowapi.middleware as slowapi_middleware_module

# Configure structured logging before app creation so lifespan logs are structured
setup_logging(
    json_logs=settings.log_json,
    log_level=settings.log_level,
    production=settings.is_production,
)
structlog.contextvars.bind_contextvars(service="api")

logger = structlog.stdlib.get_logger(__name__)

# Arbitrary stable key for the boot-time seed advisory lock (pg_advisory_xact_lock).
# Serializes seed_roles + seed_initial_admin so concurrent uvicorn workers don't
# race the SELECT-then-INSERT on a fresh DB. Any constant works; it only needs to
# be unique among advisory locks we take (conftest uses a different key).
_SEED_LOCK_KEY = 0x6C656E73  # "lens"

# Default roles to seed if they don't exist
DEFAULT_ROLES = [
    {"name": "admin", "description": "Full system access"},
    {"name": "editor", "description": "Can create and edit datasets"},
    {"name": "viewer", "description": "Read-only access to permitted datasets"},
]


async def seed_roles() -> None:
    """Ensure default roles exist in the database (defensive safety net).

    Concurrency-safe (see _SEED_LOCK_KEY): runs in the lifespan before
    seed_initial_admin, so under `uvicorn --workers N` two workers on a fresh DB
    would otherwise both SELECT-miss and both INSERT, colliding on the roles.name
    unique constraint and crashing the loser's startup *before* the admin-seed
    lock is ever reached.
    """
    from app.core.db import async_session  # fix(#909): late-bind for tests

    async with async_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK_KEY}
        )
        for role_data in DEFAULT_ROLES:
            result = await session.execute(
                # Select the scalar id, not the Role entity. Role.users uses
                # select-in loading, and materializing a Role would therefore
                # issue an unscoped catalog.users query during hosted startup.
                # The runtime role is correctly subject to FORCE RLS, so that
                # accidental query fails closed when no request tenant exists.
                select(Role.id).where(Role.name == role_data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(**role_data))
                logger.info("Seeded role: %s", role_data["name"])
        await session.commit()


def _warn_if_cors_unset(settings_obj, log) -> None:
    """SEC-08 / M-72: warn loudly when CORS_ALLOWED_ORIGINS is unset in
    production. Anonymous standards and catalog search reads remain
    browser-accessible, while credentialed application routes require an
    explicit origin allowlist.

    Gated on is_production so dev/test runs don't get the warning. SEC-005:
    previously gated on log_json (the de-facto production indicator); now uses
    the explicit settings.is_production.
    """
    if settings_obj.is_production and not settings_obj.cors_allowed_origins:
        log.warning(
            "cors_allowed_origins_unset",
            message=(
                "CORS_ALLOWED_ORIGINS is empty in production. "
                "Anonymous standards and catalog search reads allow any "
                "browser origin, but "
                "credentialed application CORS is disabled. Set "
                "CORS_ALLOWED_ORIGINS=<comma-separated origins> to enable it."
            ),
        )


async def seed_initial_admin() -> None:
    """Create an initial admin user if no users exist.

    Uses GEOLENS_ADMIN_USERNAME and GEOLENS_ADMIN_PASSWORD from settings
    (configurable via environment variables).

    Concurrency-safe: prod runs `uvicorn --workers N`, so every worker runs the
    lifespan and races the count-check + INSERT on a fresh DB. Without
    serialization two workers both see count==0 and both INSERT → one hits
    `UniqueViolationError` on uq_users_username_global → the admin row never
    commits → admin login 401 on every fresh self-hosted install. An
    xact-scoped advisory lock makes exactly one worker seed; the rest see
    count>0 and no-op. The lock releases when the session's transaction ends.
    """
    from app.core.db import async_session  # fix(#909): late-bind for tests

    async with async_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK_KEY}
        )
        result = await session.execute(select(func.count()).select_from(User))
        user_count = result.scalar() or 0

        if user_count == 0:
            admin_user = User(
                username=settings.geolens_admin_username,
                password_hash=hash_password(
                    settings.geolens_admin_password.get_secret_value()
                ),
                is_active=True,
            )
            session.add(admin_user)
            await session.flush()

            role_result = await session.execute(
                select(Role.id).where(Role.name == "admin")
            )
            admin_role_id = role_result.scalar_one()
            session.add(UserRole(user_id=admin_user.id, role_id=admin_role_id))

            await session.commit()
            logger.info(
                "Initial admin user created: %s", settings.geolens_admin_username
            )


async def seed_bootstrap_identity() -> None:
    """Seed global RBAC roles and, only for single-tenant installs, an admin.

    A multi-tenant admin must be created through the Cloud signup transaction,
    after that transaction provisions and binds its tenant.  A global NULL-
    tenant user is both unusable and rejected by FORCE RLS.
    """
    await seed_roles()
    if is_multi_tenant():
        logger.info("Skipping global initial-admin seed in multi-tenant mode")
        return
    await seed_initial_admin()


async def sweep_stale_jobs_once(
    *, detailed: bool = False
) -> tuple[int, int] | dict[str, int]:
    """Run one stale-ingest sweep without issuing an unscoped hosted query.

    Single-tenant mode preserves the historical one-session, one-call path.
    Hosted mode reads the unprotected tenant registry, then gives every tenant
    a fresh transaction under ``tenant_job_context`` so FORCE RLS scopes all
    ``ingest_jobs`` reads and writes. Recovery is best-effort per tenant: one
    broken tenant must not prevent the remaining tenants from being swept.
    """
    from app.core.db import async_session  # fix(#909): late-bind for tests
    from app.platform.jobs.router import fail_stale_jobs
    from app.platform.jobs.sweep import purge_terminal_job_tokens

    # fix(#1746 codex r1): once per PASS, not once per tenant.
    # `catalog.procrastinate_jobs` is shared queue infrastructure with no
    # tenant column, so this belongs to the sweep rather than to any tenant —
    # inside the loop below it would repeat one unscoped UPDATE tenants-many
    # times every cadence, per API process. A bare session on purpose: the
    # statement is tenant-agnostic and needs no GUC, exactly like the tenant
    # registry read below. Best-effort like the per-tenant branch — a purge
    # that cannot run must not cost the sweep that can.
    try:
        async with async_session() as purge_session:
            await purge_terminal_job_tokens(purge_session)
    except Exception as exc:  # broad: the sweep proceeds without the purge
        logger.warning(
            "Terminal-row job token purge failed",
            error=str(exc),
            exc_info=True,
        )

    if not is_multi_tenant():
        async with async_session() as session:
            if detailed:
                outcome = await fail_stale_jobs(session, detailed=True)
                return outcome.as_dict()
            return await fail_stale_jobs(session)

    async with async_session() as registry_session:
        tenant_ids = list(
            (
                await registry_session.execute(
                    text("SELECT id FROM catalog.tenants ORDER BY id")
                )
            ).scalars()
        )

    pending_total = 0
    running_total = 0
    detail_totals: dict[str, int] = dict.fromkeys(
        (
            "pending_failed",
            "running_failed",
            "total_cleaned",
            "vrt_assets_recovered",
            "vrt_generations_failed",
            "terminal_jobs_purged",
            "staged_paths_considered",
            "local_files_reaped",
            "storage_objects_reaped",
            "staged_paths_skipped",
            "staged_cleanup_failures",
            "total_affected",
        ),
        0,
    )
    for tenant_id in tenant_ids:
        try:
            with tenant_job_context(str(tenant_id)):
                async with async_session() as session:
                    if detailed:
                        outcome = await fail_stale_jobs(session, detailed=True)
                    else:
                        pending_failed, running_failed = await fail_stale_jobs(session)
            if detailed:
                for key, value in outcome.as_dict().items():
                    detail_totals[key] = detail_totals.get(key, 0) + value
            else:
                pending_total += pending_failed
                running_total += running_failed
        except Exception as exc:  # broad: fleet sweep continues tenant-by-tenant
            logger.warning(
                "Stale jobs sweep failed for tenant",
                tenant_id=str(tenant_id),
                error=str(exc),
                exc_info=True,
            )
    if detailed:
        return detail_totals
    return pending_total, running_total


def _sweep_orphaned_exports_periodic(exports_dir: Path) -> tuple[int, int]:
    """Thin positional-only wrapper around ``sweep_orphaned_exports`` binding
    the periodic threshold, so it can be handed to ``run_in_thread_draining``
    (which forwards ``*args`` only — ``age_threshold_seconds`` is keyword-only
    on the wrapped function).

    fix(#1532 review r7): it also reclaims atomic-write scratch files, over the
    whole staging root rather than just ``exports/``.
    ``LocalStorageProvider.put`` writes through ``<name>.<hex>.tmp`` and renames,
    so a process killed mid-write leaves one behind under whatever prefix it was
    writing — COGs, originals, VRTs, map assets. This sweeper is the right home
    because it already walks the staging tree on a schedule and, unlike anything
    storage-backed, needs no ``init_storage`` to run. It rides this loop's 300 s
    cadence but keeps its own (fix(#1532 review r14)): the exports pass below
    scans one directory, the scratch pass walks everything stored.
    """
    scratch = sweep_orphaned_write_scratch_occasionally(
        Path(settings.upload_staging_dir),
        age_threshold_seconds=EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
    )
    if scratch:
        logger.info("orphaned_write_scratch_swept", removed=scratch)
    # fix(#1746): reclaim GDAL bearer-header tempfiles a SIGKILL/OOM left
    # behind (see sweep_stale_gdal_header_files docstring). Rides this same
    # periodic cadence; the default 1-hour age matches EXPORTS_SWEEP_AGE_SECONDS
    # (boot-time), not the wider periodic export threshold, since a header file
    # is only ever alive for a single ogr2ogr subprocess run, not an
    # in-flight multi-hour export.
    # fix(#1746 codex r2): defaults to the container tmpfs now, not the
    # staging volume — see gdal_header_dir(). No argument because the sweep
    # reclaims rather than provisions: a container that has never written a
    # header has no directory and nothing to reclaim.
    gdal_headers = sweep_stale_gdal_header_files()
    if gdal_headers:
        logger.info("stale_gdal_header_files_swept", removed=gdal_headers)
    return sweep_orphaned_exports(
        exports_dir, age_threshold_seconds=EXPORTS_PERIODIC_SWEEP_AGE_SECONDS
    )


async def _sweep_orphaned_exports_and_log(exports_dir: Path, log) -> None:
    """Sweep exports/ in a worker thread and log only when something was
    actually removed — mirrors the pending_failed/running_failed and
    renewed-credentials branches in ``_stale_jobs_sweeper``, which stay quiet
    on a no-op cycle.

    Split out of that loop body so this one extra branch does not push
    ``lifespan``'s McCabe complexity over its gate.

    fix(#1435 codex round 1): uses ``EXPORTS_PERIODIC_SWEEP_AGE_SECONDS``, not
    the boot-time callers' default — this runs continuously on a short
    cadence rather than only at a restart, so it needs a wider safety margin
    (see that constant's docstring in ``staging.py``) before treating an
    export directory as abandoned rather than merely slow.

    fix(#1435 codex round 5): runs via ``run_in_thread_draining`` rather than
    inline. ``sweep_orphaned_exports`` does synchronous directory traversal
    and ``shutil.rmtree``; unlike the two boot-time callers, which run before
    the event loop is serving traffic, this one runs on a live server every
    few minutes, so calling it inline would stall request handling for the
    duration — worst case exactly when a crash left large or many-file
    residue, since that is what gives the sweep real work to do. Draining
    (rather than a bare ``asyncio.to_thread``) means a cancellation
    (graceful shutdown) waits for an in-flight ``rmtree`` to finish instead
    of abandoning a background thread still mutating the filesystem.
    """
    deleted, _ = await run_in_thread_draining(
        _sweep_orphaned_exports_periodic, exports_dir
    )
    if deleted:
        log.info("Swept orphaned exports", deleted=deleted)


def install_api_query_deadline() -> None:
    """Put the API's statement deadline on the engine this process uses.

    fix(#1778 codex r2): on the engine rather than on one dependency. Handlers
    open request-scoped sessions directly through ``async_session()`` in more
    than twenty modules -- ``GET /stac/collections`` runs three aggregates that
    way -- so binding it inside ``get_db`` left every one of those pinning a
    pool slot with no deadline.

    Called at import of this module, not from the lifespan, because
    ``do_connect`` only fires for connections opened after it is registered and
    the pool must not have connected first. Called AGAIN from the lifespan so a
    test fixture that has rebound ``app.core.db.engine`` to the test engine
    gets it too; the installer is idempotent.

    The engine is late-bound per fix(#909) -- the client fixture reassigns
    ``db_module.engine``, and a module-scope binding here would snapshot the
    dev engine past that patch.

    The worker entrypoint never imports this module, so its engine keeps no
    deadline. That is the point: it runs single statements for minutes while
    building a spatial index over a freshly ingested table.
    """
    from app.core.db import engine
    from app.core.statement_timeout import install_api_statement_timeout

    install_api_statement_timeout(engine)


install_api_query_deadline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.db import engine  # fix(#909): late-bind for tests

    # fix(#1778 codex r2): again, against whatever `app.core.db.engine` is NOW.
    # Import time covers the real process; this covers a test fixture that has
    # rebound the attribute to the test engine since. Idempotent.
    install_api_query_deadline()

    for attempt in range(1, 4):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            break
        except Exception as exc:  # broad: boot DB connectivity probe — any asyncpg/sqlalchemy/network error retries up to 3x
            if attempt < 3:
                logger.warning(
                    "Database not ready, retrying",
                    attempt=attempt,
                    error=str(exc),
                )
                await asyncio.sleep(2)
            else:
                logger.exception(
                    "Database health check failed after 3 attempts",
                    error=str(exc),
                )
                raise

    # MIG-02: fail closed if the DB's applied migration heads do not match the
    # heads this image's migration scripts declare (skew in EITHER direction —
    # DB behind = migrate service didn't run / empty DB; DB ahead = image
    # rolled back below the DB schema). Runs after the connectivity probe so a
    # transient DB outage retries above instead of surfacing here.
    from app.core.db.schema_skew import assert_schema_in_sync

    await assert_schema_in_sync()

    await seed_bootstrap_identity()

    # SEC-08 / M-72: surface unset CORS_ALLOWED_ORIGINS in production once.
    _warn_if_cors_unset(settings, logger)

    # WORK-01: shared bootstrap — extension load, enterprise-overlay-requested check,
    # edition init, extension router include, storage + S3 health probe, billing
    # on_startup dispatch, cache init. bootstrap() is the single source of truth
    # for this sequence; both API and worker delegate here to prevent drift.
    await bootstrap(app=app)

    # WORK-02: run the same affirmative port assertion the worker runs
    # (worker.py) so both entrypoints fail closed together. Without it, a
    # license-key activation with a missing overlay would crash the worker while
    # the API kept serving on Default community ports — the API-up/worker-down
    # split-brain WORK-01 exists to prevent. No-op in community/single-tenant.
    assert_enterprise_ports_resolved()

    staging_root = ensure_staging_ready(settings.upload_staging_dir)
    exports_dir = ensure_staging_ready(staging_root / "exports")

    # fix(#435): this used to delete every entry unconditionally. Production runs
    # two Uvicorn workers over one staging volume, so a restarting worker could
    # truncate an export a surviving sibling was still writing or streaming. Share
    # the worker's age-aware sweeper instead.
    sweep_orphaned_exports(exports_dir)
    # fix(#1746): reclaim GDAL bearer-header tempfiles orphaned by a crash
    # before this boot (see sweep_stale_gdal_header_files docstring).
    # fix(#1746 codex r2): from the container tmpfs, NOT staging_root. A
    # container restart normally empties /tmp on its own; this covers the case
    # where the process died without the container going with it.
    sweep_stale_gdal_header_files()

    await init_tile_pool()
    await task_app.open_async()

    from app.observability.metrics.memory import update_memory_metrics
    from app.observability.metrics.pool import update_pool_metrics
    from app.observability.metrics.refresh import update_refresh_metrics

    pool_metrics_task = asyncio.create_task(update_pool_metrics())
    # feat(#1268): the refresh lifecycle is observed HERE rather than in the
    # worker that executes it — the worker serves no /metrics endpoint. The
    # gauges are derived from catalog.dataset_refresh_runs and published in
    # livemostrecent mode, so every uvicorn worker running this same loop
    # reports one answer instead of N summed ones.
    refresh_metrics_task = asyncio.create_task(update_refresh_metrics())
    # fix(#643): per-worker RSS gauge + log watermark so an OOM-bound worker
    # is visible in normal logs before the kernel kills it.
    memory_metrics_task = asyncio.create_task(update_memory_metrics())
    # fix(#1240, #651 review round 2): reap gauge_live*.db files left by a
    # sibling worker that was OOM-killed/SIGKILLed rather than shut down
    # gracefully -- shutdown_worker_metrics() below never runs for that case.
    metrics_sweep_task = asyncio.create_task(sweep_dead_worker_metrics())

    async def _stale_jobs_sweeper() -> None:
        """Periodically fail jobs whose worker crashed mid-run.

        Without this, an IngestJob row can sit in 'running' forever if no
        client polls it after the worker dies — the on-poll fail-fast logic
        in get_job_status only catches it when a user revisits the page.
        """
        from app.platform.refresh.credentials import (
            CREDENTIAL_RENEWAL_INTERVAL_SECONDS,
            renew_queued_credentials_once,
        )

        sweeper_log = structlog.stdlib.get_logger("stale_jobs_sweeper")
        while True:
            try:
                # feat(#1277 review round 2): the interval is the credential
                # module's, because the refresh credential TTL is derived from
                # it — three cycles, so a single skipped pass cannot expire a
                # credential whose task is still queued. One constant, owned
                # where the arithmetic that depends on it lives, rather than a
                # 300 here and a mirror there.
                await asyncio.sleep(CREDENTIAL_RENEWAL_INTERVAL_SECONDS)
                pending_failed, running_failed = await sweep_stale_jobs_once()
                if pending_failed or running_failed:
                    sweeper_log.info(
                        "Failed stale jobs",
                        pending_failed=pending_failed,
                        running_failed=running_failed,
                    )
                # Re-arm credentials whose dispatch is still waiting for
                # a worker. Tenant-scoped, and hosted in the WORKER too — see
                # renew_credentials_periodically for why one host was not
                # enough. EXPIRE is idempotent, so both running in the same
                # cycle is free.
                renewed = await renew_queued_credentials_once()
                if renewed:
                    sweeper_log.debug("Renewed queued credentials", count=renewed)
                # exports/ residue from a hard process death (SIGKILL, OOM) used
                # to sit until the next restart — sweep_orphaned_exports only
                # ran once at boot (above) and once at worker boot (worker.py).
                # It is idempotent and age-thresholded, so it is safe to run on
                # every sweeper cycle too. The two boot-time callers deliberately
                # stay synchronous — boot wants the sweep done before the app
                # serves traffic, and nothing else contends for the loop yet;
                # this caller threads it because it runs while the loop is live.
                await _sweep_orphaned_exports_and_log(exports_dir, sweeper_log)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # broad: sweeper-loop must survive any DB/transient error to keep running
                sweeper_log.warning(
                    "Stale jobs sweeper iteration failed",
                    error=str(exc),
                    exc_info=True,
                )

    stale_jobs_task = asyncio.create_task(_stale_jobs_sweeper())

    async def _rate_limit_warmer() -> None:
        """fix(#430 BA-03): the slowapi sync accessors only read a per-process cache that
        set()/reset() seed for 30s on the ONE worker that handled the write. No
        request path re-resolves them, so the four runtime-tunable limits revert to
        their hardcoded defaults after the TTL and admin changes never propagate
        fleet-wide. Periodically re-resolve them from the DB (get() warms the sync
        cache) on every worker, at an interval below _CACHE_TTL.
        """
        from app.core.db import async_session
        from app.core.persistent_config import (
            BASEMAP_PROXY_RATE_LIMIT,
            GLOBAL_RATE_LIMIT,
            LOGIN_RATE_LIMIT,
            SEMANTIC_SEARCH_RATE_LIMIT,
        )

        warmer_log = structlog.stdlib.get_logger("rate_limit_warmer")
        configs = (
            LOGIN_RATE_LIMIT,
            GLOBAL_RATE_LIMIT,
            SEMANTIC_SEARCH_RATE_LIMIT,
            BASEMAP_PROXY_RATE_LIMIT,
        )
        while True:
            try:
                async with async_session() as session:
                    for cfg in configs:
                        await cfg.get(session)
            except asyncio.CancelledError:
                raise
            except (
                Exception
            ) as exc:  # broad: warmer must survive any transient DB error
                warmer_log.warning(
                    "Rate limit warmer iteration failed",
                    error=str(exc),
                    exc_info=True,
                )
            await asyncio.sleep(
                15
            )  # < _CACHE_TTL (30s) so the sync cache never expires to default

    rate_limit_warmer_task = asyncio.create_task(_rate_limit_warmer())

    yield

    pool_metrics_task.cancel()
    memory_metrics_task.cancel()
    refresh_metrics_task.cancel()
    metrics_sweep_task.cancel()
    stale_jobs_task.cancel()
    rate_limit_warmer_task.cancel()
    await task_app.close_async()
    await close_tile_pool()
    await _titiler_client.aclose()
    await engine.dispose()
    # fix(#1240, #651): drop this worker's multiprocess metric files so a
    # respawn under UVICORN_MAX_REQUESTS recycling doesn't leave a stale
    # series behind for the next scrape to keep summing.
    shutdown_worker_metrics()


_DESCRIPTION = """\
## Overview

GeoLens is a self-hosted spatial data catalog that ingests vector files
(GeoPackage, Shapefile, GeoJSON, CSV), stores them in PostGIS, and exposes
them through OGC API endpoints.

## OGC Conformance Classes

* OGC API Common 1.0 -- Core, Landing Page, JSON, OAS 3.0
* OGC API Features Part 1 -- Core, GeoJSON, OAS 3.0
* OGC API Features Part 3 -- Filtering (CQL2-Text, CQL2-JSON)

## QGIS Quick-start

1. **Layer > Add Layer > WFS / OGC API Features**
2. URL: `{your-server}/api/`
3. GeoLens advertises collections automatically.

## GDAL / ogr2ogr Quick-start

```bash
# List collections
ogrinfo OAPIF:{your-server}/api/

# Download a collection to GeoPackage
ogr2ogr -f GPKG output.gpkg OAPIF:{your-server}/api/ {collection-id}
```

## Authentication

GeoLens supports three authentication methods. Public datasets are accessible
without credentials; private/restricted datasets require one of:

| Method | Usage |
|--------|-------|
| **API Key header** | `X-Api-Key: <key>` |
| **JWT Bearer token** | `Authorization: Bearer <token>` |
| **API Key query param** (deprecated) | `?api_key=<key>` |

Priority: header API key > query param API key > JWT > anonymous.

**The `?api_key=` query parameter is deprecated.** A key sent in the URL is
recorded by server access logs and any proxy in between. Prefer the
`X-Api-Key` header; keep the query parameter only for clients that cannot
send headers (e.g. XYZ tile URLs in desktop GIS tools).

API keys may carry an optional expiry (`expires_at` at mint time). Expired
keys stop authenticating, and keys are also invalidated by security events
on the owner's account (password change or role change). Logging out of the
web UI does not affect API keys.

### What a rejected credential looks like

Send no credential and you are served anonymously: public datasets come
back, private ones do not.

Send a credential that cannot be resolved (expired, revoked, or mistyped)
and every endpoint that reads credentials answers `401`, including the ones
that also serve anonymous callers. It is never quietly ignored. A `200`
carrying only the public subset would look exactly like a catalog holding
nothing more, so a client whose key died overnight would go on working
against a smaller view of the data and never be told. The `401` is also the
signal a client needs to refresh and retry.

Three cases sit outside that rule.

`POST /auth/logout` accepts a dead access token so a stale session can still
be cleared, and falls back to the refresh credential. It still answers `401`
when nothing you present resolves.

A request that something other than your identity already authorized is
served, and the dead credential is ignored: a valid `X-Embed-Token`, or a
valid signed tile template (`sig`, `exp`, `scope`). Each authorizes one
specific resource on its own, so an embed viewer carrying a stale browser
session still renders. An invalid or absent capability puts the request back
under the rule above, so a junk `X-Embed-Token` cannot be used to suppress
the `401`.

`GET /maps/shared/{token}` answers `404` for an unknown share link and `410`
for a revoked one whatever you send. No credential could have made that link
work, and reporting the credential instead would hide the answer you can act
on.

A few endpoints read no credential at all, such as the landing page and the
conformance declaration, and answer `200` either way.

### GDAL / ogr2ogr with API Key

```bash
# List collections (including private ones accessible to your key)
ogrinfo --config GDAL_HTTP_HEADERS "X-Api-Key: YOUR_KEY" "OAPIF:{your-server}/api/"

# Download a private collection
ogr2ogr -f GPKG out.gpkg --config GDAL_HTTP_HEADERS "X-Api-Key: YOUR_KEY" "OAPIF:{your-server}/api/" {collection-id}
```

### QGIS with API Key

In the WFS / OGC API Features connection dialog, append `?api_key=YOUR_KEY`
to the server URL (the connection dialog cannot send custom headers; this is
the main remaining use of the deprecated query parameter).
"""

_OPENAPI_TAGS = [
    {
        "name": "OGC Features",
        "description": (
            "OGC API Features endpoints: landing page, conformance, collections, "
            "and items. Compatible with QGIS, GDAL/ogr2ogr, and other OGC clients."
        ),
    },
    {
        "name": "Datasets",
        "description": (
            "Dataset management: upload, ingestion, CRUD, re-upload, versioning, "
            "export, and row/column access."
        ),
    },
    {
        "name": "Features",
        "description": "Per-dataset GeoJSON feature access and editing (CRUD).",
    },
    {
        "name": "Search",
        "description": (
            "Full-text, spatial, and faceted dataset search with CQL2 filtering."
        ),
    },
    {
        "name": "Auth",
        "description": "Authentication: login, registration, API keys, and user profile.",
    },
    {
        "name": "Admin",
        "description": (
            "Administration: user management, catalog stats, site settings, "
            "jobs, and audit logs."
        ),
    },
    {
        "name": "Records",
        "description": "Record sub-resources: contacts, keywords, and distributions.",
    },
    {
        "name": "Maps",
        "description": "Saved map configurations, layers, AI styling, and sharing.",
    },
    {
        "name": "Config Ops",
        "description": "Configuration export, import, dry-run, and connectivity validation.",
    },
    {
        "name": "Admin Embed Tokens",
        "description": "Admin management of embed tokens across all maps.",
    },
    {
        "name": "Embed Tokens",
        "description": "Per-map embed token CRUD for iframe tile access.",
    },
    {
        "name": "Tiles",
        "description": "Vector and raster tile serving with HMAC-signed access tokens.",
    },
    {
        "name": "STAC",
        "description": "SpatioTemporal Asset Catalog API for published raster datasets.",
    },
    {
        "name": "Datasets - Export",
        "description": "DCAT JSON-LD catalog export and COG download.",
    },
    {
        "name": "Datasets - Data",
        "description": "Row access, validation, related datasets, and publication status.",
    },
    {
        "name": "Datasets - Metadata",
        "description": "Attribute metadata, column stats, and FK relationships.",
    },
    {
        "name": "Datasets - Reupload",
        "description": "Dataset re-upload with schema diff and atomic swap.",
    },
    {
        "name": "Datasets - VRT",
        "description": "VRT raster mosaic creation and management.",
    },
]

# SEC-005: docs exposure (and the Secure session cookie below) are gated on the
# explicit ENVIRONMENT setting, not the LOG_JSON log-format flag. is_production
# falls back to LOG_JSON when ENVIRONMENT is unset (backward compatibility).
_is_production = settings.is_production


# REL-03: single version source of truth. The app version is derived from the
# installed backend distribution metadata (backend/pyproject.toml [project].version,
# distribution name "geolens-backend") instead of a hand-maintained literal that
# silently drifts from pyproject/openapi/SDKs. `make version-check` enforces that
# all version sites agree; this is the runtime arm of that contract.
#
# Fallback: when the package is not installed as a distribution (e.g. running
# from a source checkout with PYTHONPATH but no `uv pip install -e .`), there is
# no metadata to read. We fall back to the current published line so import never
# crashes. Keep this fallback in lockstep with backend/pyproject.toml — it is one
# of the sites `make bump` rewrites.
_FALLBACK_APP_VERSION = "1.17.0"


def _resolve_app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("geolens-backend")
    except PackageNotFoundError:
        return _FALLBACK_APP_VERSION


app = FastAPI(
    title="GeoLens API",
    version=_resolve_app_version(),
    summary="PostGIS-native geospatial data catalog with OGC API Features and Records support",
    description=_DESCRIPTION,
    root_path="/api",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_tags=_OPENAPI_TAGS,
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0",
    },
    contact={
        "name": "GeoLens",
        "url": "https://github.com/geolens-io/geolens",
    },
    terms_of_service="https://github.com/geolens-io/geolens/blob/main/LICENSE",
    # === Routing config ===
    # ROUTE-01 (Phase 1092): redirect_slashes=False at the app level.
    #
    # Security: with redirect_slashes=True (the default), trailing-slash
    # callers receive a 307 whose Location header carries the relative URL
    # of the canonical form. Behind docker-compose the request Host
    # resolves to the in-container ``api:8000`` hostname, leaking that
    # internal name to external curl / SDK callers.
    #
    # All trailing-slash-only routes register a no-slash alias via
    # stacked decorators (see backend/app/modules/auth/router.py,
    # settings/router.py, admin/router.py, etc. — every router under
    # backend/app/modules/ that uses the trailing-slash form). The
    # canonical decorator stays in OpenAPI; the alias is hidden via
    # ``include_in_schema=False``. This means BOTH URL shapes resolve to
    # the same handler with the same status code, and no Location header
    # is ever produced for the routing dispatch.
    #
    # See .planning/phases/1092-routing-infra-hygiene/1092-CONTEXT.md for
    # the (c) hybrid rationale. The Phase 280 catalog/maps/router.py
    # precedent (v13.14-followup `32d1d2e7`) established the stacked-
    # decorator pattern this app-level flag now relies on across all
    # affected routes.
    redirect_slashes=False,
    # === End routing config ===
    lifespan=lifespan,
)

from app.observability.health.schemas import HealthResponse  # noqa: E402
from app.standards.ogc.errors import (  # noqa: E402
    DATABASE_UNAVAILABLE_RESPONSE,
    INTERNAL_SERVER_ERROR_RESPONSE,
    ProblemDetail,
    RATE_LIMIT_RESPONSE,
    UNRESOLVABLE_CREDENTIAL_RESPONSE,
    register_error_handlers,
)

register_error_handlers(app)

app.state.limiter = limiter


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # fix(#315): advertise the retry window (exc.limit.limit.get_expiry(), seconds).
    #
    # fix(#1778): a plain def, not a coroutine, and it must stay one. slowapi's
    # SlowAPIMiddleware enforces the GLOBAL default limit inside a synchronous
    # BaseHTTPMiddleware dispatch and resolves this handler through
    # `sync_check_limits`, which silently swaps a coroutine handler for
    # slowapi's own `_rate_limit_exceeded_handler` ("cannot execute
    # asynchronous code in a synchronous middleware"). That fallback returns a
    # bare {"error": ...} in application/json with no Retry-After, because the
    # Limiter is not built with headers_enabled. Only routes carrying an
    # explicit @limiter.limit decorator take the exception-handler path
    # instead, which is why every test of this contract passed while the
    # majority of routes -- the undecorated ones -- answered a rate-limit
    # rejection with a shape no SDK, CLI or apiFetch caller can parse. Nothing
    # here awaits, so a sync handler serves both paths identically; Starlette
    # runs it in a threadpool on the exception-handler path.
    headers = {}
    try:
        headers["Retry-After"] = str(int(exc.limit.limit.get_expiry()))
    except Exception:  # broad: never let the optional Retry-After lookup 500 a 429
        pass
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=ProblemDetail(
            title="Too Many Requests",
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc.detail),
        ).model_dump(),
        media_type="application/problem+json",
        headers=headers,
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)


from sqlalchemy.exc import DBAPIError  # noqa: E402

from app.core.db.sqlstate import is_operational, sqlstate  # noqa: E402
from app.modules.quota.service import (  # noqa: E402
    DatasetQuotaExceededError,
    StorageQuotaExceededError,
)


async def _dataset_quota_handler(
    request: Request, exc: DatasetQuotaExceededError
) -> JSONResponse:
    # fix(#302): reserve_dataset_slot raises a plain exception so the worker
    # can use it too; API-side callers (e.g. empty-layer creation) get a 422
    # matching the check_upload_quota contract.
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=ProblemDetail(
            title="Dataset quota exceeded",
            status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ).model_dump(),
        media_type="application/problem+json",
    )


async def _storage_quota_handler(
    request: Request, exc: StorageQuotaExceededError
) -> JSONResponse:
    # fix(#430 BA-23): reserve_storage_bytes raises a plain exception in the worker;
    # API-side callers get a 413 matching the check_upload_quota byte-cap contract.
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        content=ProblemDetail(
            title="Storage quota exceeded",
            status=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ).model_dump(),
        media_type="application/problem+json",
    )


async def _database_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Map an operational database failure to a 503 (fix(#435)).

    Connection loss, statement timeout, cancellation, and serialization failures used
    to be caught per-handler and reported as domain data — a dataset with zero rows,
    say — which hid ingest corruption and infrastructure incidents from users and from
    health monitoring. Handlers now re-raise what they cannot legitimately answer.

    Non-operational errors (integrity violations, syntax and access errors) are
    re-raised so they keep their existing 500 path; calling a unique-constraint
    collision "database unavailable" would just invite a retry loop.

    The detail is deliberately generic: the SQLSTATE and statement go to the log.
    """
    if not is_operational(exc):
        raise exc
    logger.exception(
        "Operational database error",
        # fix(#1778): the path can be /api/maps/shared/{token}; the access-log
        # line for the same request has been redacted since #821 and this one
        # was not, so a 503 here published a replayable share capability.
        path=safe_access_log_path(request.url.path),
        sqlstate=sqlstate(exc),
    )
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ProblemDetail(
            title="Database unavailable",
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The database could not serve this request. Please retry.",
        ).model_dump(),
        media_type="application/problem+json",
    )


app.add_exception_handler(DatasetQuotaExceededError, _dataset_quota_handler)
app.add_exception_handler(StorageQuotaExceededError, _storage_quota_handler)
app.add_exception_handler(DBAPIError, _database_error_handler)

# SEC-02 / M-64 / SEC-005: gate https_only on the production indicator. Local-dev
# and test runs use the development posture (no TLS terminator), so
# https_only=True would cause SessionMiddleware to silently strip the cookie.
# Production (ENVIRONMENT=production, or legacy LOG_JSON=true) sets
# https_only=True. Same settings.is_production used for docs gating above.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret_key.get_secret_value(),
    https_only=settings.is_production,
)
app.add_middleware(RequestLoggingMiddleware)
# TSEAM-04 (Phase 1207-02): resolve tenant context after request logging so
# the tenant_id is available to all route handlers.  In single_tenant mode
# (default) this is a strict no-op (single boolean check, no state mutation).
app.add_middleware(TenantContextMiddleware)


def _find_route_handler_with_lazy_includes(routes, scope):
    """slowapi <= 0.1.10 resolves the handler by scanning ``app.routes`` for a
    matching route with an ``endpoint``. fastapi 0.140 keeps included-router
    routes nested (lazy ``include_router``), so that scan finds nothing and the
    middleware silently stops enforcing the GLOBAL default rate limit
    (per-route ``@limiter.limit`` decorators are unaffected). Until a slowapi
    release understands the nested table, resolve misses through the flattened
    route contexts, whose ``path_regex``/``methods`` carry the effective full
    path. Guarded by tests/test_middleware.py::test_rate_limiting."""
    handler = _slowapi_find_route_handler(routes, scope)
    if handler is not None:
        return handler
    from fastapi.routing import iter_route_contexts

    # Route regexes never include the ASGI root_path, and starlette's own
    # matching strips it (starlette._utils.get_route_path — mirrored here to
    # avoid the private import). Without this, rewrite-less deployments that
    # keep the /api prefix via ROOT_PATH would silently lose the global
    # default rate limit again (Codex P2 on #747).
    path = scope.get("path", "")
    root_path = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        stripped = path[len(root_path) :]
        if not stripped or stripped.startswith("/"):
            path = stripped
    method = scope.get("method", "")
    for ctx in iter_route_contexts(list(routes)):
        path_regex = getattr(ctx, "path_regex", None)
        if path_regex is None or not path_regex.match(path):
            continue
        # Registration order matches starlette routing order, so the first
        # method-compatible hit is the route that would handle the request.
        if ctx.methods and method not in ctx.methods:
            continue
        if ctx.endpoint is not None:
            return ctx.endpoint
    return None


_slowapi_find_route_handler = slowapi_middleware_module._find_route_handler
slowapi_middleware_module._find_route_handler = _find_route_handler_with_lazy_includes
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.upload_max_size_mb * 1024 * 1024,
)
# SEC-17 / L-63: middleware mount order is significant.
# add_middleware PREPENDS to the chain — later calls wrap as the OUTER layer.
# On the RESPONSE path, OUTER runs LAST. We need SecurityHeadersMiddleware to
# run FIRST on the response (so headers are added BEFORE compression), then
# GZipMiddleware to compress, so the order is:
#   1. SecurityHeadersMiddleware (added FIRST → INNER → runs FIRST on response)
#   2. GZipMiddleware            (added SECOND → OUTER → runs SECOND on response)
# Pinned by tests/test_phase_273_middleware_order.py — do not flip without
# updating that regression test.
app.add_middleware(SecurityHeadersMiddleware)
# fix(#1540 review P2): image/tiff joins starlette's default exclusions, which
# already cover avif/gif/jpeg/png/webp and simply predate anyone serving TIFF.
#
# Not a CPU optimization, though it is that too — a COG is internally compressed
# already, so DEFLATE over a multi-GB one buys close to nothing. It is a
# CORRECTNESS fix for the strong ETag the COG download route publishes. A strong
# validator must identify one representation including its content coding, and
# this middleware compresses a 200 while skipping a 206 by design
# (`self.partial_response = status == 206`). One ETag therefore named two
# different byte streams: gzip bytes on the full download, raw bytes on every
# range. A client resuming the encoded representation could have its validator
# accepted and splice raw bytes at encoded offsets — doing everything right and
# still assembling a corrupt file. Excluding the type restores the invariant
# without variant-specific validators, which would need their own HEAD metadata
# and Vary story.
app.add_middleware(
    GZipMiddleware,
    minimum_size=256,
    compresslevel=4,
    exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES + ("image/tiff",),
)
# fix(#1532 review r11): the export route is excluded by PATH, not by media
# type. Excluding `application/geo+json` and `text/csv` app-wide — which is what
# r9 did — also stopped compressing feature GeoJSON and the admin and audit CSV
# streams, endpoints that serve one representation and never a range, so the
# safety bought nothing there and the bandwidth was a straight regression.
#
# `image/tiff` stays a media-type exclusion because it is the right shape for
# THAT case: the COG download is the only producer of it, so the type and the
# route are the same set.
#
# Implemented by dropping gzip from the request's Accept-Encoding before
# GZipMiddleware reads it, which is the documented way to opt a request out —
# the alternative, a `Content-Encoding: identity` on the responses, puts a token
# on the wire that RFC 9110 defines for Accept-Encoding rather than for
# Content-Encoding. Added AFTER the middleware above so it wraps it: starlette
# runs the most recently added outermost.
app.add_middleware(NoCompressionForExportMiddleware)
app.add_middleware(DynamicCORSMiddleware)

app.include_router(api_router)


def _iter_api_routes(target_app: FastAPI) -> list:
    """Every APIRoute on the app as a ``RouteContext``, including ones nested
    in lazily-included routers — fastapi 0.140 stopped flattening
    ``include_router`` into ``app.routes``, so a plain
    ``isinstance(route, APIRoute)`` scan over ``app.routes`` silently sees
    almost nothing. Consumers must read the effective full path from
    ``ctx.path``/``ctx.path_format`` (``ctx.route.path`` lacks the parent
    router prefix for nested includes) and route attributes from
    ``ctx.route``."""
    from fastapi.routing import APIRoute, iter_route_contexts

    return [
        ctx
        for ctx in iter_route_contexts(target_app.routes)
        if isinstance(ctx.route, APIRoute)
    ]


def _clone_api_route(
    target_app: FastAPI,
    route,
    *,
    path: str,
    methods: list[str],
    name_suffix: str,
) -> None:
    """Re-register an existing APIRoute at *path* for *methods*.

    Both derived-route passes below register a copy of a canonical route
    rather than editing it, so every attribute a handler's behaviour depends
    on has to be carried across. Spelled once here: a kwarg dropped from this
    list is a silent behaviour difference between the canonical route and its
    copy, and that is not a difference either caller wants.

    Hidden from OpenAPI. A derived route documents nothing the canonical one
    does not, and publishing it would churn every generated SDK.
    """
    target_app.add_api_route(
        path=path,
        endpoint=route.endpoint,
        response_model=route.response_model,
        status_code=route.status_code,
        tags=route.tags,
        dependencies=route.dependencies,
        summary=route.summary,
        description=route.description,
        response_description=route.response_description,
        responses=route.responses,
        deprecated=route.deprecated,
        methods=methods,
        operation_id=None,  # MUST differ from canonical for uniqueness;
        # FastAPI auto-generates when None.
        response_model_include=route.response_model_include,
        response_model_exclude=route.response_model_exclude,
        response_model_by_alias=route.response_model_by_alias,
        response_model_exclude_unset=route.response_model_exclude_unset,
        response_model_exclude_defaults=route.response_model_exclude_defaults,
        response_model_exclude_none=route.response_model_exclude_none,
        include_in_schema=False,
        response_class=route.response_class,
        name=f"{route.name}__{name_suffix}" if route.name else None,
        openapi_extra=route.openapi_extra,
        generate_unique_id_function=route.generate_unique_id_function,
    )


def _add_trailing_slash_aliases(target_app: FastAPI) -> None:
    """ROUTE-01 (Phase 1092 review CR-01): register a hidden no-slash alias
    for every trailing-slash route in the app.

    With ``redirect_slashes=False`` at the app level, routes registered
    ONLY with a trailing slash silently 404 when called without it.
    Pre-sweep this affected ~100 routes. The 13 routers under
    ``backend/app/modules/`` got explicit stacked-decorator aliases on
    ~28 high-traffic routes (see CR-01 sweep commit). This function
    closes the remaining ~72 routes (datasets/api/router_metadata,
    catalog/records, processing/ai, processing/ingest,
    platform/config_ops, etc.) without further per-file edits.

    For every existing trailing-slash APIRoute, register an equivalent
    no-slash route that calls the same endpoint function with the same
    response model, dependencies, and status code. The alias is hidden
    from OpenAPI via ``include_in_schema=False`` — the canonical
    trailing-slash form stays the documented surface.

    Future trailing-slash routes added to the app are picked up
    automatically — this hook runs once on app construction, after all
    routers have been included. Adding the same route twice (once
    manually via stacked decorator, once via this function) is
    structurally safe because we check ``existing_paths`` before
    registering.

    Method+path collisions (alias would shadow an existing no-slash
    registration) are skipped, preserving the explicit registration as
    canonical. This means the 28 manual stacked-decorator aliases from
    the CR-01 sweep remain authoritative — this function only adds
    aliases for routes that lack one.
    """

    # Snapshot existing (method, path) pairs to avoid double-registration.
    existing_paths: set[tuple[str, str]] = set()
    for ctx in _iter_api_routes(target_app):
        for method in ctx.route.methods:
            existing_paths.add((method, ctx.path))

    added = 0
    for ctx in _iter_api_routes(target_app):
        route = ctx.route
        if not ctx.path.endswith("/") or ctx.path == "/":
            continue
        no_slash = ctx.path.rstrip("/")

        # Skip if ANY method already has a no-slash sibling registered
        # (i.e. a manual stacked decorator already covers this surface).
        # We check method-by-method below.
        for method in route.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            if (method, no_slash) in existing_paths:
                continue
            # Register the alias. Inherit response_model, dependencies,
            # status_code, etc. from the canonical route — APIRoute
            # exposes these directly.
            _clone_api_route(
                target_app,
                route,
                path=no_slash,
                methods=[method],
                name_suffix="no_slash_alias",
            )
            existing_paths.add((method, no_slash))
            added += 1

    if added > 0:
        # Re-build the FastAPI route table cache by clearing any cached
        # OpenAPI spec — the next /openapi.json request rebuilds from
        # the current app.routes state.
        target_app.openapi_schema = None


def _register_standards_head_routes(target_app: FastAPI) -> None:
    """fix(#1470): serve HEAD wherever the CORS preflight says we do.

    ``DynamicCORSMiddleware._set_public_cors_headers`` answers a preflight on
    the anonymous standards surface with
    ``Access-Control-Allow-Methods: GET, HEAD, POST, OPTIONS``, and
    ``_anonymous_public_methods`` accepts ``HEAD`` as a requested method for
    that surface — but FastAPI's ``APIRoute`` does not add HEAD alongside GET the
    way starlette's plain ``Route`` does, so every one of these routes
    answered ``405 allow: GET``. A browser client that trusts the preflight
    was told HEAD was fine and then refused. HEAD-probing a landing page or a
    collection before fetching it is ordinary OGC client behaviour.

    Derived here rather than by editing ~48 decorators across five routers.
    Both surfaces read the same ``standards_api_path`` classifier, so the set
    that answers HEAD and the set advertised as answering it cannot drift —
    which is the actual bug, not the missing routes.

    fix(#1596) gave the anonymous wildcard a second surface, the catalog search
    routes, which this pass does not cover. That does not reopen the drift: the
    middleware advertises ``GET, OPTIONS`` there, matching the GET-only routes,
    rather than being extended to promise a HEAD nothing registers.

    Runs after ``_add_trailing_slash_aliases`` so the no-slash aliases are
    covered too. Registering a route rather than adding to
    ``route.methods``: fastapi 0.140 keeps included-router routes nested and
    matches through ``RouteContext``, whose ``methods`` is a COPY of the
    route's, so an in-place mutation would leave the matcher answering 405.
    """
    existing: set[tuple[str, str]] = set()
    for ctx in _iter_api_routes(target_app):
        for method in ctx.route.methods:
            existing.add((method, ctx.path))

    added = 0
    for ctx in _iter_api_routes(target_app):
        if "GET" not in ctx.route.methods or ("HEAD", ctx.path) in existing:
            continue
        if standards_api_path(ctx.path) is None:
            continue
        _clone_api_route(
            target_app,
            ctx.route,
            path=ctx.path,
            methods=["HEAD"],
            name_suffix="head",
        )
        existing.add(("HEAD", ctx.path))
        added += 1

    if added > 0:
        target_app.openapi_schema = None


_add_trailing_slash_aliases(app)
_register_standards_head_routes(app)


# OGC API Common requires malformed standards-path parameters to use 400.  The
# runtime RequestValidationError handler applies that contract; normalize the
# generated description too so machine clients are not told to expect FastAPI's
# native 422 response on OGC/STAC/DCAT operations.
_fastapi_openapi = app.openapi


def _dependency_uses(dependant, targets: set[object]) -> bool:
    """Return whether a FastAPI dependency tree calls one of ``targets``."""
    if dependant.call in targets:
        return True
    return any(_dependency_uses(child, targets) for child in dependant.dependencies)


def _route_operation(schema: dict, ctx, method: str) -> dict | None:
    """Resolve a route context to its generated OpenAPI operation."""
    return schema.get("paths", {}).get(ctx.path_format, {}).get(method.lower())


def _normalize_security_contract(schema: dict) -> None:
    """Publish every runtime credential form and anonymous-capable alternative."""

    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_fail_open,
    )

    security_schemes = schema.setdefault("components", {}).setdefault(
        "securitySchemes", {}
    )
    security_schemes["ApiKeyHeader"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Api-Key",
        "description": "GeoLens API key. Preferred API-key transport.",
    }
    security_schemes["ApiKeyQuery"] = {
        "type": "apiKey",
        "in": "query",
        "name": "api_key",
        "description": "Legacy API-key query parameter; prefer X-Api-Key.",
    }

    # ``get_optional_user_no_security_schema`` deliberately keeps public STAC
    # operations credential-aware at runtime without stamping authentication
    # onto their generated clients. Only the normal optional dependencies
    # should gain the anonymous-or-credential security alternatives here.
    #
    # fix(#1518): both optional dependencies belong in this set. They differ in
    # what an unresolvable credential does (401 vs anonymous), not in whether
    # the operation accepts one, and the published contract is the latter — a
    # fail-open handler left out of this set would lose its ``{}`` anonymous
    # alternative and be documented as requiring authentication.
    optional_targets = {get_optional_user, get_optional_user_fail_open}
    credential_alternatives = [
        {"OAuth2PasswordBearer": []},
        {"ApiKeyHeader": []},
        {"ApiKeyQuery": []},
    ]

    for ctx in _iter_api_routes(app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        optional_auth = _dependency_uses(route.dependant, optional_targets)
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is None:
                continue
            existing = operation.get("security", [])
            has_bearer = any("OAuth2PasswordBearer" in item for item in existing)
            if not optional_auth and not has_bearer:
                continue

            preserved = [
                item
                for item in existing
                if not any(
                    key in item
                    for key in ("OAuth2PasswordBearer", "ApiKeyHeader", "ApiKeyQuery")
                )
            ]
            operation["security"] = (
                ([{}] if optional_auth else []) + credential_alternatives + preserved
            )


def _document_rate_limits(schema: dict) -> None:
    """Attach the runtime SlowAPI 429 contract to every non-exempt operation."""

    for ctx in _iter_api_routes(app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        endpoint_name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        # The limiter has a global default, so undecorated routes are limited too.
        # Only explicit @limiter.exempt handlers bypass the middleware contract.
        if endpoint_name in limiter._exempt_routes:
            continue
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is not None:
                operation.setdefault("responses", {}).setdefault(
                    "429", RATE_LIMIT_RESPONSE
                )


def _document_unresolvable_credential_401(schema: dict) -> None:
    """Publish the #1518 401 on every operation that can now raise it.

    ``get_optional_user`` refuses a supplied-but-unresolvable credential, so a
    401 is normal runtime behaviour on routes that were previously documented as
    only ever answering anonymously. Generated SDK error unions are built from
    these response blocks, so an undocumented 401 is one a typed client cannot
    represent (codex P2 on #1524). #1518 asked for the docs to state what an
    unresolvable credential does; the ``info.description`` prose is the human
    half and this is the half the SDKs consume.

    All THREE optional dependencies are targeted, which is one more than
    ``_normalize_security_contract`` uses:

    - ``get_optional_user`` raises it directly.
    - ``get_optional_user_fail_open`` defers rather than waives — its CAPABILITY
      handlers call ``reject_unresolvable_credentials`` themselves, and the
      RECOVERY one (logout) raises its own 401, so both can answer 401.
    - ``get_optional_user_no_security_schema`` delegates to
      ``get_optional_user`` and answers identically. It is EXCLUDED from the
      security-marker set on purpose (fix(#430): no bearer markers on genuinely
      public STAC operations), and it belongs here anyway. A 401 *response* is
      not a security *requirement*: this function only writes into
      ``responses``, never into ``security``, so documenting the status cannot
      stamp an auth block back onto those operations.
      ``test_no_security_schema_ops_get_401_without_security`` pins that.
    """

    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_fail_open,
        get_optional_user_no_security_schema,
    )

    credential_aware = {
        get_optional_user,
        get_optional_user_fail_open,
        get_optional_user_no_security_schema,
    }

    for ctx in _iter_api_routes(app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        if not _dependency_uses(route.dependant, credential_aware):
            continue
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is None:
                continue
            # setdefault: a route that already documents its own 401 with a
            # more specific description keeps it.
            operation.setdefault("responses", {}).setdefault(
                "401", UNRESOLVABLE_CREDENTIAL_RESPONSE
            )


def _document_global_failures(schema: dict) -> None:
    """Document exception handlers that apply outside individual routers."""

    from app.core.dependencies import get_db

    for ctx in _iter_api_routes(app):
        route = ctx.route
        if not route.include_in_schema:
            continue
        uses_database = _dependency_uses(route.dependant, {get_db})
        for method in route.methods or ():
            operation = _route_operation(schema, ctx, method)
            if operation is None:
                continue
            responses = operation.setdefault("responses", {})
            responses.setdefault("500", INTERNAL_SERVER_ERROR_RESPONSE)
            if uses_database:
                responses.setdefault("503", DATABASE_UNAVAILABLE_RESPONSE)


def _repair_depends_bound_query_model(schema: dict) -> None:
    """Publish the query parameters a ``Depends()``-bound model fails to declare.

    fix(#1666): ``SearchQueryParams`` reaches ``collection_items`` through
    ``Depends()``, and two of its fields do not survive that binding.
    ``keywords`` is a ``list[str]``, which FastAPI reads as a JSON request body
    — on a GET. ``cql2_filter_lang`` carries the alias ``filter-lang``, which
    pydantic's synthesized ``__init__`` cannot name, so the contract advertises
    the field name instead. Either way a generated client sends something the
    handler never reads and is silently unfiltered.

    ``search_datasets_endpoint`` takes the same model as
    ``Annotated[SearchQueryParams, Query()]``, which declares both correctly, so
    the repair COPIES those definitions rather than restating them — a
    hand-written mirror of a model's parameters is the thing that drifts.
    ``collection_items`` cannot use that form itself: FastAPI expands a query
    model only when it is the operation's ONLY query-parameter source, and
    alongside this route's five OGC parameters it collapses to one scalar.

    One asymmetry this leaves, deliberately: the operation still BINDS the
    legacy GET body at runtime, because that is inseparable from ``Depends()``.
    Removing it from the published contract is the point — a request body on a
    GET should be sunset, not advertised — but it means a caller that sends a
    malformed JSON body sees a validation 400 the contract does not describe.
    Sending no body, which is every correct client, is unaffected.
    """
    paths = schema.get("paths", {})
    donor = paths.get("/search/datasets/", {}).get("get")
    target = paths.get("/collections/datasets/items", {}).get("get")
    if donor is None or target is None:
        return

    donated = {
        parameter["name"]: parameter
        for parameter in donor.get("parameters", [])
        if parameter.get("name") in {"keywords", "filter-lang"}
    }
    if len(donated) != 2:
        # The donor stopped declaring them correctly; leave the target alone
        # rather than publishing a half-repaired contract.
        return

    parameters = [
        parameter
        for parameter in target.get("parameters", [])
        if parameter.get("name") not in {"cql2_filter_lang", *donated}
    ]
    parameters.extend(donated.values())
    target["parameters"] = parameters

    # The phantom body this defect produces. Only drop the one the model caused.
    body = target.get("requestBody", {})
    body_schema = body.get("content", {}).get("application/json", {}).get("schema", {})
    if body_schema.get("title") == "Keywords":
        target.pop("requestBody", None)


def _normalize_validation_error_contract(schema: dict) -> None:
    """Publish the RFC 7807 body every validation failure actually returns.

    fix(#1666): FastAPI stamps ``422 -> HTTPValidationError`` (an
    ``application/json`` body of ``{detail: [{loc, msg, type}, ...]}``) on every
    operation with request validation. The ``RequestValidationError`` handler in
    ``standards/ogc/errors.py`` overrides that at runtime with a problem+json
    ``ProblemDetail`` whose ``detail`` is flattened to one string, so both the
    media type and the body shape were wrong — and generated clients inherit
    both. The standards-path loop below already applies the same correction
    under the OGC status rule; this covers every other operation.
    """
    validation_response = {
        "description": "Validation error",
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetail"}
            }
        },
    }
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "head"}:
                continue
            responses = operation.get("responses", {})
            if "422" in responses:
                responses["422"] = dict(validation_response)


def _drop_unreferenced_validation_models(schema: dict) -> None:
    """Drop FastAPI's validation models once nothing references them.

    Checked rather than popped unconditionally: a route is free to name
    ``HTTPValidationError`` in an explicit ``responses=`` block, and removing a
    component that is still referenced leaves a dangling ``$ref`` that breaks
    SDK generation instead of tidying it.

    fix(#1666 codex P2): the search excludes only the candidate, never both
    targets. ``HTTPValidationError`` holds the sole ``$ref`` to
    ``ValidationError``, so hiding it while deciding ``ValidationError`` reads
    the container's own reference as absent — and a run where an operation kept
    ``HTTPValidationError`` alive would then delete the schema it points at.

    Order matters with it: the container is considered before the leaf, so
    dropping the container in the first pass makes the leaf unreferenced in the
    second and both go. Reversed, the leaf would be held alive by a container
    that is itself about to be removed.
    """
    schemas = schema.get("components", {}).get("schemas", {})
    for name in ("HTTPValidationError", "ValidationError"):
        others = json.dumps(
            {
                **{k: v for k, v in schema.items() if k != "components"},
                "schemas": {k: v for k, v in schemas.items() if k != name},
            }
        )
        if f"#/components/schemas/{name}" not in others:
            schemas.pop(name, None)


def _standards_aware_openapi() -> dict:
    schema = _fastapi_openapi()
    if schema.get("x-geolens-standards-errors") == "400-problem-details":
        return schema

    # Error responses reference ProblemDetail explicitly under the RFC 7807
    # media type. Register the component here rather than using FastAPI's
    # ``responses={..., "model": ...}`` shortcut, which also advertises an
    # application/json body that the runtime never returns.
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas["ProblemDetail"] = ProblemDetail.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )

    # SSE is framed text at the HTTP layer, while each ``data`` field carries
    # one of these JSON payloads. The streaming operations reference the DTOs
    # through a vendor extension, so register them explicitly without falsely
    # advertising the whole response as application/json.
    from app.processing.ai.schemas import (
        SSEActionsEvent,
        SSEChatDoneEvent,
        SSEErrorEvent,
        SSEMapDoneEvent,
        SSETokenEvent,
        SSEToolResultEvent,
        SSEToolStartEvent,
    )

    for event_model in (
        SSEActionsEvent,
        SSEChatDoneEvent,
        SSEErrorEvent,
        SSEMapDoneEvent,
        SSETokenEvent,
        SSEToolResultEvent,
        SSEToolStartEvent,
    ):
        event_schema = event_model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        for definition_name, definition in event_schema.pop("$defs", {}).items():
            schemas.setdefault(definition_name, definition)
        schemas[event_model.__name__] = event_schema

    _normalize_security_contract(schema)
    _document_unresolvable_credential_401(schema)
    _document_rate_limits(schema)
    _document_global_failures(schema)
    _normalize_validation_error_contract(schema)
    _repair_depends_bound_query_model(schema)

    for path, path_item in schema.get("paths", {}).items():
        if standards_api_path(path) is None:
            continue
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            responses = operation.setdefault("responses", {})
            responses.pop("422", None)
            responses.setdefault(
                "400",
                {
                    "description": "Bad request — invalid standards parameters",
                    "content": {
                        "application/problem+json": {
                            "schema": {"$ref": "#/components/schemas/ProblemDetail"}
                        }
                    },
                },
            )

            if path == "/collections/datasets/items" and method == "get":
                for parameter in operation.get("parameters", []):
                    if parameter.get("name") in {"type", "ids", "externalIds"}:
                        # OGC API Records 1.0 requirements 24/30/32 specify
                        # comma-separated form arrays (explode=false).
                        parameter["style"] = "form"
                        parameter["explode"] = False

    _drop_unreferenced_validation_models(schema)

    schema["x-geolens-standards-errors"] = "400-problem-details"
    app.openapi_schema = schema
    return schema


app.openapi = _standards_aware_openapi  # type: ignore[method-assign]

init_metrics(app)


# Phase 1230 EVENT-04: health-alert cooldown state.
# Module-level so it persists across requests within a single API process.
# _last_health_alert_at: time.monotonic() of the most recent degraded alert
#   sent, or None if no alert has been sent since boot/recovery. None means
#   "alert immediately" — a 0.0 sentinel was wrong because monotonic() is
#   seconds-since-boot, so `now - 0.0 >= COOLDOWN` suppressed the very first
#   alert during the first 5 minutes of process uptime (exactly when a DB is
#   most likely down after a deploy).
# _last_health_status:   last observed status ("healthy" or "degraded"); a
#   transition back to "healthy" resets _last_health_alert_at so the NEXT
#   degraded event produces a fresh alert after recovery (T-1230-06).
_last_health_alert_at: float | None = None
_last_health_status: str = "healthy"
# Cooldown window: emit at most one health alert per 5 minutes (T-1230-06
# low-noise requirement).  Docker healthcheck polls every 10 s → at most
# one alert per 30 polls while the system remains degraded.
_HEALTH_ALERT_COOLDOWN_SECS: float = 300.0


# fix(#1778): liveness, split out from readiness. `/health` probes the database,
# the object store AND the cache, and 503s if any of them is down -- but the
# cache path is explicitly engineered to survive a Valkey outage (it falls back
# to an in-memory cache behind a circuit breaker), so a dependency the API can
# serve straight through still marked the container unhealthy. That is the
# Docker healthcheck AND the gate on `frontend: depends_on: api:
# service_healthy`, so a restart during a Valkey or MinIO outage left the whole
# UI down because the cache was down; under an orchestrator with an HTTP
# liveness probe on `/health` the pod is killed and restarted in a loop while
# the API is perfectly able to serve catalog reads.
#
# `/health` keeps its meaning (readiness: every dependency answered). This route
# answers only "the process is up and the event loop is turning", mirroring the
# worker's own split in observability/health/worker.py, and is what the
# container healthcheck and any liveness probe should target.
#
# `include_in_schema=False` for the same reason the worker's probes are absent
# from the contract: it is infrastructure surface, not API surface, and no SDK
# or CLI caller has a use for it.
#
# Exempt from the limiter rather than capped at 60/min like `/health`: a
# kubelet probing every second from one source address is already at that cap
# before any other traffic, and a liveness probe that answers 429 gets the pod
# killed. GAP-016 capped `/health` because it probes dependencies on every
# call; this handler touches nothing and allocates one dict.
@app.get("/health/live", include_in_schema=False, tags=["Health"])
@limiter.exempt
async def health_live(request: Request):
    """Liveness probe: process is up, no dependency checks."""
    return {"status": "ok"}


# GAP-016: /health is rate-limited (60/min per IP) rather than fully exempt, to
# bound abuse of this unauthenticated, dependency-probing endpoint. The limit is
# deliberately generous: the Docker container healthcheck polls every 10s
# (~6/min) and a reverse proxy/LB adds only a small constant on top, so
# legitimate infra never trips it. The response also omits raw provider exception
# strings (`check_health` defaults to `include_errors=False`) so anonymous callers
# never see DB/S3/cache internals — those are logged server-side and exposed only
# on the authenticated admin view. (Kept as a comment, not a docstring, so the
# rationale + finding ID stay out of the public OpenAPI description.)
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    responses={
        503: {
            "description": "Health probes completed but one or more providers are degraded",
            "model": HealthResponse,
        }
    },
)
@limiter.limit("60/minute")
async def health(request: Request):
    """Health check endpoint for ALB, Docker, and Nginx."""
    import time

    from app.observability.health.service import check_health
    from fastapi.responses import JSONResponse

    result = await check_health()
    # fix(#441): report the running version + build commit so a deployment can
    # be verified over HTTP (production disables /docs, which was the only
    # surface exposing the version). GEOLENS_BUILD_SHA is stamped into release
    # images by publish.yml; local and source builds report null.
    import os

    result["version"] = app.version
    result["build"] = os.environ.get("GEOLENS_BUILD_SHA") or None
    status_code = 200 if result["status"] == "healthy" else 503

    # Phase 1230 EVENT-04: emit a health-alert notification when the result is
    # degraded and the per-event toggle is on, with cooldown de-duplication so
    # repeated unhealthy polls do not spam the admin (T-1230-06 low-noise).
    # The emit runs as a Starlette BackgroundTask so the /health response is
    # returned FIRST and is never delayed by a slow/unreachable notification
    # channel (WR-01) — Docker/ALB healthchecks have short timeouts and must not
    # flap during an SMTP outage. The emit is also fail-safe (never raises).
    from starlette.background import BackgroundTask

    global _last_health_alert_at, _last_health_status  # noqa: PLW0603
    current_status = result.get("status", "healthy")
    now = time.monotonic()
    health_alert_task: BackgroundTask | None = None
    if current_status != "healthy":
        # Determine the failing component(s) for the notification body.
        providers: dict = result.get("providers", {})
        failing = [
            name
            for name, info in providers.items()
            if isinstance(info, dict) and info.get("status") != "ok"
        ]
        component = failing[0] if failing else "unknown"
        # Reset cooldown when the system recovers between degraded windows.
        if _last_health_status == "healthy":
            _last_health_alert_at = None
        _last_health_status = current_status
        # Emit only if outside the cooldown window (de-dup, T-1230-06).
        # None => no alert sent since boot/recovery → fire immediately.
        if (
            _last_health_alert_at is None
            or now - _last_health_alert_at >= _HEALTH_ALERT_COOLDOWN_SECS
        ):
            _last_health_alert_at = now
            # Lazy import per Phase 214 discipline.
            from app.platform.notifications.events import (  # LAZY
                build_event_notification,
                emit_event_safe,
            )

            _component = component
            health_alert_task = BackgroundTask(
                emit_event_safe,
                event_key="health_alert",
                build=lambda: build_event_notification(
                    "health_alert",
                    subject=f"GeoLens health degraded: {_component}",
                    body=(
                        f"The GeoLens health check reported a degraded status.\n\n"
                        f"Failing component: {_component}"
                    ),
                    extra={"component": _component, "status": current_status},
                ),
            )
    else:
        # System is healthy: reset status so a future recurrence re-alerts.
        _last_health_status = "healthy"
        _last_health_alert_at = None

    return JSONResponse(
        content=result, status_code=status_code, background=health_alert_task
    )


__all__ = [
    "app",
    "health",
    "lifespan",
    "seed_bootstrap_identity",
    "seed_initial_admin",
    "seed_roles",
]
