# ruff: noqa: E402
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import structlog

# Must run before FastAPI/Starlette imports (gh #101); shared with worker for
# the /tmp tmpfs issue during COG conversion.
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

# fix(#909): don't reimport settings/async_session/engine at module scope —
# tests rebind app.core.db, and a snapshot import would hit the dev DB.
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
from app.platform.ratelimit import emit_startup_notices, limiter
from app.processing.ingest.tasks import task_app
from app.api.middleware.body_limit import RequestBodyLimitMiddleware
from app.api.middleware.cors import DynamicCORSMiddleware
from app.api.middleware.credential_scrub import CredentialScrubASGIMiddleware
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

# Advisory-lock key for boot-time seeding (pg_advisory_xact_lock); serializes
# seed_roles + seed_initial_admin so concurrent uvicorn workers don't race the
# SELECT-then-INSERT on a fresh DB. Any constant works; must be unique.
_SEED_LOCK_KEY = 0x6C656E73  # "lens"

DEFAULT_ROLES = [
    {"name": "admin", "description": "Full system access"},
    {"name": "editor", "description": "Can create and edit datasets"},
    {"name": "viewer", "description": "Read-only access to permitted datasets"},
]


async def seed_roles() -> None:
    """Ensure default roles exist in the database (defensive safety net).

    Concurrency-safe via _SEED_LOCK_KEY: without it, concurrent uvicorn
    workers on a fresh DB would race SELECT-then-INSERT on roles.name.
    """
    from app.core.db import async_session  # fix(#909): late-bind for tests

    async with async_session() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SEED_LOCK_KEY}
        )
        for role_data in DEFAULT_ROLES:
            result = await session.execute(
                # Select the scalar id, not the Role entity: Role.users
                # select-in loading would issue an unscoped catalog.users
                # query, which fails closed under FORCE RLS with no tenant.
                select(Role.id).where(Role.name == role_data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(**role_data))
                logger.info("Seeded role: %s", role_data["name"])
        await session.commit()


def _warn_if_cors_unset(settings_obj, log) -> None:
    """SEC-08/M-72/SEC-005: warn when CORS_ALLOWED_ORIGINS is unset in prod.

    Anonymous standards/catalog reads stay browser-accessible regardless;
    credentialed routes need an explicit origin allowlist. Gated on
    is_production, not log_json.
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
    """Create an initial admin user if none exist.

    Uses GEOLENS_ADMIN_USERNAME/_PASSWORD from settings. Concurrency-safe via
    the xact-scoped advisory lock: without it, concurrent uvicorn workers on
    a fresh DB would race the INSERT and the loser's UniqueViolationError
    would leave admin login 401 on every fresh install.
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
    """Seed global RBAC roles and, for single-tenant installs only, an admin.

    Multi-tenant admins are created via the Cloud signup transaction after
    tenant provisioning; a global NULL-tenant user is rejected by FORCE RLS.
    """
    await seed_roles()
    if is_multi_tenant():
        logger.info("Skipping global initial-admin seed in multi-tenant mode")
        return
    await seed_initial_admin()


async def sweep_stale_jobs_once(
    *, detailed: bool = False
) -> tuple[int, int] | dict[str, int]:
    """Run one stale-ingest sweep without an unscoped hosted-mode query.

    Single-tenant keeps the one-session path. Hosted mode reads the tenant
    registry, then runs each tenant under ``tenant_job_context`` so FORCE RLS
    scopes ``ingest_jobs`` access. A broken tenant doesn't block the rest.
    """
    from app.core.db import async_session  # fix(#909): late-bind for tests
    from app.platform.jobs.router import fail_stale_jobs
    from app.platform.jobs.sweep import purge_terminal_job_tokens

    # fix(#1746): purge once per pass, not per tenant — procrastinate_jobs has
    # no tenant column. Bare session is intentional (tenant-agnostic, no GUC);
    # best-effort like the per-tenant sweep below.
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
    """Positional-only wrapper around ``sweep_orphaned_exports`` binding the
    periodic threshold, for ``run_in_thread_draining`` (``*args``-only).

    fix(#1532): also reclaims orphaned atomic-write scratch files across the
    whole staging root (``LocalStorageProvider.put``'s ``<name>.<hex>.tmp``
    left behind by a mid-write kill), not just ``exports/``.
    """
    scratch = sweep_orphaned_write_scratch_occasionally(
        Path(settings.upload_staging_dir),
        age_threshold_seconds=EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
    )
    if scratch:
        logger.info("orphaned_write_scratch_swept", removed=scratch)
    # fix(#1746): reclaim GDAL bearer-header tempfiles a SIGKILL/OOM left on
    # the container tmpfs (gdal_header_dir()). Uses the boot-time 1-hour age,
    # not the wider export threshold — a header lives for one ogr2ogr run.
    gdal_headers = sweep_stale_gdal_header_files()
    if gdal_headers:
        logger.info("stale_gdal_header_files_swept", removed=gdal_headers)
    return sweep_orphaned_exports(
        exports_dir, age_threshold_seconds=EXPORTS_PERIODIC_SWEEP_AGE_SECONDS
    )


async def _sweep_orphaned_exports_and_log(exports_dir: Path, log) -> None:
    """Sweep exports/ in a worker thread; log only when something was removed
    (quiet on a no-op cycle, like the sibling branches in
    ``_stale_jobs_sweeper``). Split out so this branch doesn't push
    ``lifespan``'s McCabe complexity over its gate.

    fix(#1435): uses ``EXPORTS_PERIODIC_SWEEP_AGE_SECONDS``, not the
    boot-time callers' default — this runs continuously on a short cadence,
    so it needs a wider safety margin before treating a directory as
    abandoned. Runs via ``run_in_thread_draining``, not inline and not a bare
    ``asyncio.to_thread``: this runs on a live server, so inline would stall
    request handling during ``shutil.rmtree``; draining lets a graceful
    shutdown wait for an in-flight rmtree instead of abandoning it mid-write.
    """
    deleted, _ = await run_in_thread_draining(
        _sweep_orphaned_exports_periodic, exports_dir
    )
    if deleted:
        log.info("Swept orphaned exports", deleted=deleted)


def install_api_query_deadline() -> None:
    """Put the API's statement deadline on the engine this process uses.

    fix(#1778): on the engine, not one dependency — handlers open sessions
    directly via ``async_session()`` in 20+ modules, so binding it in
    ``get_db`` would leave those with no deadline. Called at import
    (covers transactions before lifespan runs) and again from the
    lifespan (idempotent; covers a rebound test engine). Engine is
    late-bound per fix(#909) for the same reason.

    The worker never imports this module, so its engine keeps no
    deadline on purpose — it runs single statements for minutes.
    """
    from app.core.db import engine
    from app.core.statement_timeout import install_api_statement_timeout

    install_api_statement_timeout(engine)


install_api_query_deadline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.db import engine  # fix(#909): late-bind for tests

    # fix(#1778): idempotent re-install against `app.core.db.engine` now —
    # covers a test fixture that rebound it since import time.
    install_api_query_deadline()

    for attempt in range(1, 4):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            break
        except Exception as exc:  # broad: DB probe — retries any connect error up to 3x
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

    # MIG-02: fail closed on migration-head skew in EITHER direction (DB
    # behind = migrate didn't run; DB ahead = image rolled back below schema).
    # Runs after the connectivity probe so a transient outage retries above.
    from app.core.db.schema_skew import assert_schema_in_sync

    await assert_schema_in_sync()

    await seed_bootstrap_identity()

    # SEC-08 / M-72: surface unset CORS_ALLOWED_ORIGINS in production once.
    _warn_if_cors_unset(settings, logger)

    # fix(#2018): the rate-limit storage decision is made at import, before
    # setup_logging() above, so its notices are queued rather than logged
    # there and flushed here into the configured stream.
    emit_startup_notices()

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

    # fix(#435): two Uvicorn workers share one staging volume, so an
    # unconditional sweep could truncate an export a sibling is still
    # writing. Share the worker's age-aware sweeper instead.
    sweep_orphaned_exports(exports_dir)
    # fix(#1746): reclaim GDAL bearer-header tempfiles orphaned by a crash
    # before this boot, from the container tmpfs (not staging_root) — this
    # covers a process death that didn't take the container with it.
    sweep_stale_gdal_header_files()

    await init_tile_pool()
    await task_app.open_async()

    from app.observability.metrics.memory import update_memory_metrics
    from app.observability.metrics.pool import update_pool_metrics
    from app.observability.metrics.refresh import update_refresh_metrics

    pool_metrics_task = asyncio.create_task(update_pool_metrics())
    # feat(#1268): observed HERE, not in the worker — the worker serves no
    # /metrics endpoint. Gauges derive from catalog.dataset_refresh_runs in
    # livemostrecent mode, so every uvicorn worker reports one answer.
    refresh_metrics_task = asyncio.create_task(update_refresh_metrics())
    # fix(#643): per-worker RSS gauge + log watermark so an OOM-bound worker
    # is visible in normal logs before the kernel kills it.
    memory_metrics_task = asyncio.create_task(update_memory_metrics())
    # fix(#1240, #651): reap gauge_live*.db files left by a sibling worker
    # that was OOM/SIGKILLed rather than shut down — shutdown_worker_metrics
    # below never runs for that case.
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
                # feat(#1277): interval is the credential module's — the
                # renewal TTL derives from it (three cycles), so one skipped
                # pass can't expire a still-queued credential.
                await asyncio.sleep(CREDENTIAL_RENEWAL_INTERVAL_SECONDS)
                pending_failed, running_failed = await sweep_stale_jobs_once()
                if pending_failed or running_failed:
                    sweeper_log.info(
                        "Failed stale jobs",
                        pending_failed=pending_failed,
                        running_failed=running_failed,
                    )
                # Re-arm credentials still waiting for a worker; also hosted
                # in the WORKER (renew_credentials_periodically) — EXPIRE is
                # idempotent so both running the same cycle is free.
                renewed = await renew_queued_credentials_once()
                if renewed:
                    sweeper_log.debug("Renewed queued credentials", count=renewed)
                # Reclaims exports/ residue from a hard process death;
                # idempotent/age-thresholded so safe every cycle. Threaded
                # here (loop is live) vs. synchronous at the boot-time callers.
                await _sweep_orphaned_exports_and_log(exports_dir, sweeper_log)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # broad: sweeper loop must survive to keep running
                sweeper_log.warning(
                    "Stale jobs sweeper iteration failed",
                    error=str(exc),
                    exc_info=True,
                )

    stale_jobs_task = asyncio.create_task(_stale_jobs_sweeper())

    async def _rate_limit_warmer() -> None:
        """fix(#430): slowapi's sync accessors read a per-process cache that
        set()/reset() seeds for 30s on the ONE worker that wrote it — admin
        changes never propagate fleet-wide. Re-resolve from the DB (get()
        warms the cache) on every worker, below _CACHE_TTL.
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

`GET /api/conformance` is the machine-readable list and the one a client
should read. This is the same set in prose:

* OGC API Common 1.0 -- Core, Landing Page, JSON
* OGC API Features Part 1 -- Core, GeoJSON
* OGC API Features Part 3 -- Queryables, Filter, Features Filter
* CQL2 1.0 -- CQL2-Text, CQL2-JSON, Basic CQL2, advanced comparison
  operators, basic spatial functions
* OGC API Records Part 1 -- Record Core, core query parameters, sorting, JSON

The OAS 3.0 classes of Common and Features Part 1 are NOT claimed: this
server publishes its API document as OpenAPI 3.1.

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

**The `?api_key=` query parameter is deprecated, and it authenticates reads
only.** A key sent in the URL is recorded by server access logs and any proxy
in between, so it authenticates `GET`, `HEAD` and `OPTIONS` and nothing else.
On any other method the key is ignored and the request is answered as if no
credential had been sent. Prefer the `X-Api-Key` header, which carries reads
and writes alike; keep the query parameter only for clients that cannot send
headers (e.g. XYZ tile URLs in desktop GIS tools).

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


# REL-03: version is read from the installed backend distribution metadata
# (backend/pyproject.toml [project].version) rather than a hand-maintained
# literal, so `make version-check` can enforce that all version sites agree.
#
# Fallback below covers running from a source checkout with no `uv pip
# install -e .` (no metadata to read); keep it in lockstep with
# pyproject.toml — `make bump` rewrites it.
_FALLBACK_APP_VERSION = "1.19.1"


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
    # ROUTE-01: redirect_slashes=False — with the default True, a
    # trailing-slash 307's Location header leaks the in-container
    # ``api:8000`` hostname to external callers. Trailing-slash routes
    # instead register a no-slash alias via stacked decorators
    # (``include_in_schema=False``), so both shapes resolve identically.
    redirect_slashes=False,
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
    # fix(#315): advertise the retry window (exc.limit.limit.get_expiry()).
    # fix(#1778): must stay a plain def, not a coroutine — slowapi's
    # SlowAPIMiddleware runs inside a sync BaseHTTPMiddleware dispatch and
    # silently swaps a coroutine handler for its own handler, which returns
    # a bare {"error": ...} with no Retry-After (unparseable by SDK/CLI/
    # apiFetch). Only @limiter.limit-decorated routes take this path;
    # nothing here awaits, so one sync def serves both.
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

from app.core.db.sqlstate import (  # noqa: E402
    is_lock_conflict,
    is_operational,
    sqlstate,
)
from app.platform.catalog_locks import (  # noqa: E402
    CATALOG_LOCK_CONFLICT_CODE,
    CatalogLockConflict,
    catalog_timeout_installed,
)
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
    # fix(#430): reserve_storage_bytes raises a plain exception in the worker;
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


def _catalog_lock_conflict_response(request: Request, message: str) -> JSONResponse:
    """The one 409 body for a contended catalog row."""
    logger.info(
        "catalog row lock conflict",
        path=safe_access_log_path(request.url.path),
    )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=ProblemDetail(
            title="Catalog entry is busy",
            status=status.HTTP_409_CONFLICT,
            # Keyed, because this is the ONLY shape a contended row produces
            # and a client cannot match on a title.
            detail={"code": CATALOG_LOCK_CONFLICT_CODE, "message": message},
        ).model_dump(),
        media_type="application/problem+json",
    )


async def _catalog_lock_conflict_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Map a contended catalog row to 409, from wherever it was reached.

    Safe to retry: the acquisition rolled its transaction back first.
    """
    return _catalog_lock_conflict_response(request, str(exc))


async def _database_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Map an operational database failure to a 503 (fix(#435)).

    Connection loss, timeout, cancellation, and serialization failures used to
    be caught per-handler and reported as domain data, hiding infrastructure
    incidents; handlers now re-raise what they can't legitimately answer.
    Non-operational errors (integrity/syntax/access) keep their 500 path.

    fix(#1847): a lock conflict raised post-acquisition, while this request's
    catalog lock timeout is installed, is answered 409 like one at acquisition.

    Detail is deliberately generic; SQLSTATE and statement go to the log.
    """
    if is_lock_conflict(exc) and catalog_timeout_installed.get():
        return _catalog_lock_conflict_response(
            request, "Another operation is updating this dataset's catalog entry."
        )
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
app.add_exception_handler(CatalogLockConflict, _catalog_lock_conflict_handler)
app.add_exception_handler(DBAPIError, _database_error_handler)

# fix(#1770): registered FIRST so it ends up INNERMOST (add_middleware
# prepends; closest to the router). Must be a plain ASGI callable, not
# BaseHTTPMiddleware — that spawns a separate task, so a route handler's
# ContextVar (credential-secret registry, core/service_tokens.py) never
# propagates back out. This is the only layer sharing the handler's task,
# so the only place an unhandled exception can be scrubbed before anything
# outside that task reads it. See this middleware's own docstring.
app.add_middleware(CredentialScrubASGIMiddleware)

# SEC-02/M-64/SEC-005: gate https_only on the production indicator — dev/test
# have no TLS terminator, so https_only=True would silently strip the
# session cookie. Same settings.is_production used for docs gating above.
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
    """slowapi <= 0.1.10 scans ``app.routes`` for a matching route with an
    ``endpoint``; fastapi 0.140 keeps included-router routes nested, so the
    scan finds nothing and GLOBAL rate limiting silently stops enforcing
    (per-route ``@limiter.limit`` is unaffected). Resolve misses through the
    flattened route contexts instead. Guarded by
    tests/test_middleware.py::test_rate_limiting."""
    handler = _slowapi_find_route_handler(routes, scope)
    if handler is not None:
        return handler
    from fastapi.routing import iter_route_contexts

    # Route regexes never include the ASGI root_path; starlette's own
    # matching strips it too (starlette._utils.get_route_path — mirrored
    # here to avoid the private import). Without this, ROOT_PATH
    # deployments would silently lose the global rate limit again (#747).
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
# SEC-17/L-63: mount order matters — add_middleware PREPENDS, so later calls
# wrap OUTER and run LAST on the response. SecurityHeaders must run before
# GZip compresses, so: 1) SecurityHeadersMiddleware (added first, inner,
# runs first on response) 2) GZipMiddleware (added second, outer, runs
# second). Pinned by tests/test_phase_273_middleware_order.py.
app.add_middleware(SecurityHeadersMiddleware)
# fix(#1540): image/tiff joins starlette's default exclusions (avif/gif/
# jpeg/png/webp) — a CORRECTNESS fix, not just a CPU one. This middleware
# compresses a 200 but skips a 206, so a COG's strong ETag would identify
# gzip bytes on the full download but raw bytes on a range: a client
# resuming the encoded representation could splice raw bytes at encoded
# offsets and assemble a corrupt file. Excluding the type restores the
# invariant without variant-specific validators.
app.add_middleware(
    GZipMiddleware,
    minimum_size=256,
    compresslevel=4,
    exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES + ("image/tiff",),
)
# fix(#1532): export route excluded by PATH, not media type — excluding
# `application/geo+json`/`text/csv` app-wide also stopped compressing
# feature GeoJSON and admin/audit CSV, a straight bandwidth regression for
# endpoints that never serve a range. `image/tiff` stays a type exclusion
# since the COG download is its only producer.
#
# Implemented by dropping gzip from Accept-Encoding before GZipMiddleware
# reads it (the documented opt-out) rather than `Content-Encoding: identity`,
# which RFC 9110 defines for Accept-Encoding, not Content-Encoding. Added
# AFTER the middleware above so it wraps it (starlette runs the most
# recently added outermost).
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
    """ROUTE-01: register a hidden no-slash alias for every trailing-slash
    route in the app.

    With ``redirect_slashes=False`` at the app level, a trailing-slash-
    only route silently 404s without it. Clones each such route to a
    no-slash equivalent with the same handler/response model, hidden
    from OpenAPI — the trailing-slash form stays documented. Runs once
    at app construction; a method+path collision (an existing manual
    stacked-decorator alias) is skipped so explicit registrations win.
    """
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

        # Skip if a no-slash sibling is already registered for this method.
        for method in route.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            if (method, no_slash) in existing_paths:
                continue
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
        # Clear the cached OpenAPI spec so the next /openapi.json rebuilds.
        target_app.openapi_schema = None


def _register_standards_head_routes(target_app: FastAPI) -> None:
    """fix(#1470): serve HEAD wherever the CORS preflight says we do.

    ``DynamicCORSMiddleware`` advertises HEAD on standards preflights, but
    FastAPI's ``APIRoute`` doesn't add HEAD alongside GET the way
    starlette's ``Route`` does, so these routes 405'd on HEAD despite the
    preflight promising it. Derived here (not ~48 per-router decorators)
    so the answering set can't drift from the advertised set — both read
    ``standards_api_path``. fix(#1596)'s catalog search routes don't need
    HEAD: that surface advertises ``GET, OPTIONS`` only.

    Runs after ``_add_trailing_slash_aliases``, and registers a route
    rather than mutating ``route.methods`` (a copy on ``RouteContext``,
    so an in-place mutation wouldn't reach the matcher).
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
        "description": (
            "Legacy API-key query parameter, accepted on GET/HEAD/OPTIONS "
            "only; ignored on any other method. Prefer X-Api-Key."
        ),
    }

    # ``get_optional_user_no_security_schema`` stays credential-aware at
    # runtime without stamping auth onto generated clients; only the normal
    # optional dependencies gain security alternatives here.
    #
    # fix(#1518): both optional dependencies belong in this set — they differ
    # in what an unresolvable credential does (401 vs anonymous), not in
    # whether the operation accepts one, and the published contract is the
    # latter.
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
    """Publish the #1518 401 on every operation that can raise it.

    ``get_optional_user`` refuses a supplied-but-unresolvable credential,
    so a 401 is now normal on routes documented as anonymous-only; SDK
    error unions need it or a typed client can't represent it.

    Targets all three optional dependencies — one more than
    ``_normalize_security_contract`` — since ``get_optional_user_fail_open``
    defers to its own handlers, and ``get_optional_user_no_security_schema``
    answers identically to ``get_optional_user`` despite being excluded
    from the security-marker set (fix(#430)). Only writes ``responses``,
    never ``security``, so it can't stamp an auth requirement back on.
    Pinned by ``test_no_security_schema_ops_get_401_without_security``.
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

    fix(#1666): ``SearchQueryParams`` reaches ``collection_items`` via
    ``Depends()``, and two fields don't survive — ``keywords`` reads as a
    GET JSON body, and ``cql2_filter_lang``'s alias ``filter-lang`` can't
    be named by pydantic's synthesized ``__init__``. Copies the correct
    definitions from ``search_datasets_endpoint`` rather than restating
    them (a hand-written mirror drifts); ``collection_items`` can't use
    that form itself since its five OGC parameters collapse a query
    model to one scalar.

    Deliberate asymmetry: still BINDS the legacy GET body at runtime,
    just doesn't advertise it — a malformed body gets a 400 the contract
    doesn't describe. Sending none, as every correct client does, is fine.
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

    Checked, not popped unconditionally: a route may declare
    ``HTTPValidationError`` in ``responses=``, and dropping a still-
    referenced component breaks SDK generation with a dangling ``$ref``.

    fix(#1666): excludes only the candidate from the search, not both —
    ``HTTPValidationError`` holds the sole ``$ref`` to
    ``ValidationError``, so excluding both would delete a schema a
    surviving operation still points at. Container checked before leaf,
    so dropping it makes the leaf unreferenced next pass; reversed, the
    leaf would be held alive by a container about to go.
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


# Phase 1230 EVENT-04: health-alert cooldown state, module-level so it
# persists across requests in one API process.
# _last_health_alert_at: monotonic() of the last degraded alert, or None if
#   none sent since boot/recovery. None (not 0.0) means "alert immediately"
#   — monotonic() is seconds-since-boot, so a 0.0 sentinel would suppress
#   the first alert during the process's first 5 minutes.
# _last_health_status: last observed status; a transition back to
#   "healthy" resets _last_health_alert_at so recovery gets a fresh alert.
_last_health_alert_at: float | None = None
_last_health_status: str = "healthy"
# Cooldown window: emit at most one health alert per 5 minutes (T-1230-06
# low-noise requirement).  Docker healthcheck polls every 10 s → at most
# one alert per 30 polls while the system remains degraded.
_HEALTH_ALERT_COOLDOWN_SECS: float = 300.0


# fix(#1778): liveness, split out from readiness. `/health` 503s if the
# DB, object store, or cache is down — but the cache path survives a
# Valkey outage (in-memory fallback behind a circuit breaker), so a
# dependency the API serves fine still marked the container unhealthy,
# restart-looping `frontend: depends_on: api: service_healthy`.
#
# This answers only "the process is up" (mirrors worker's split in
# observability/health/worker.py); `include_in_schema=False` since it's
# infrastructure, not API surface. Exempt from the limiter (unlike
# `/health`, GAP-016): a kubelet probing every second is already at that
# cap, and a 429'd liveness probe gets the pod killed.
@app.get("/health/live", include_in_schema=False, tags=["Health"])
@limiter.exempt
async def health_live(request: Request):
    """Liveness probe: process is up, no dependency checks."""
    return {"status": "ok"}


# GAP-016: /health is rate-limited (60/min per IP), not exempt, to bound
# abuse of this unauthenticated, dependency-probing endpoint. Generous on
# purpose: Docker's healthcheck polls every 10s (~6/min) plus a small LB
# constant, so legitimate infra never trips it. Response omits raw
# provider exception strings (`check_health(include_errors=False)`) so
# anonymous callers never see DB/S3/cache internals. Kept as a comment,
# not a docstring, so this stays out of the public OpenAPI description.
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
    # fix(#441): report version + build commit so a deployment can be
    # verified over HTTP (prod disables /docs). GEOLENS_BUILD_SHA is
    # stamped by publish.yml; local/source builds report null.
    import os

    result["version"] = app.version
    result["build"] = os.environ.get("GEOLENS_BUILD_SHA") or None
    status_code = 200 if result["status"] == "healthy" else 503

    # Phase 1230 EVENT-04: emit a health-alert when degraded and the toggle
    # is on, cooldown-deduped so repeated unhealthy polls don't spam admin
    # (T-1230-06). Runs as a BackgroundTask so the response returns FIRST
    # and is never delayed by a slow notification channel (WR-01) — the
    # emit is also fail-safe (never raises).
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
