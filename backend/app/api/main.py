# ruff: noqa: E402
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog

# Must run before FastAPI/Starlette imports (gh #101); shared with worker for
# the /tmp tmpfs issue during COG conversion.
from app.core.config import KNOWN_PUBLIC_CREDENTIALS, settings
from app.core.pointcloud import POINTCLOUD_MEDIA_TYPE
from app.core.runtime.gdal_env import configure_gdal_s3_env
from app.core.runtime.staging import redirect_tempfile_to_staging

redirect_tempfile_to_staging(settings.upload_staging_dir)
# Before any GDAL/rasterio import — /vsis3/ reads need the custom
# S3 endpoint derived into AWS_* env, and subprocesses inherit os.environ.
configure_gdal_s3_env(settings)

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.api.openapi_contract import _iter_api_routes, install_standards_aware_openapi
from app.observability.metrics import (
    init_metrics,
    shutdown_worker_metrics,
    sweep_dead_worker_metrics,
)

# don't reimport settings/async_session/engine at module scope —
# tests rebind app.core.db, and a snapshot import would hit the dev DB.
from app.core.async_io import run_in_thread_draining
from app.core.db.tenant_session import tenant_job_context
from app.core.logging_config import setup_logging
from app.core.tenancy import is_multi_tenant
from app.api.no_compress_paths import NoCompressionByPathMiddleware
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
from app.modules.auth.seeding import seed_bootstrap_identity
from app.platform.ratelimit import emit_startup_notices, limiter
from app.processing.ingest.tasks import task_app
from app.api.middleware.body_limit import RequestBodyLimitMiddleware
from app.api.middleware.cors import DynamicCORSMiddleware
from app.api.middleware.credential_scrub import CredentialScrubASGIMiddleware
from app.api.middleware.logging import RequestLoggingMiddleware, safe_access_log_path
from app.api.middleware.rate_limit import GlobalRateLimitMiddleware
from app.api.middleware.security import SecurityHeadersMiddleware
from app.api.middleware.tenant_context import TenantContextMiddleware
from app.standards.ogc.desktop import (
    DesktopEntryGateMiddleware,
    DesktopEntryRewriteMiddleware,
)
from app.processing.tiles.pool import close_tile_pool, init_tile_pool
from app.processing.tiles.router import _titiler_client
from app.standards.ogc.utils import standards_api_path
from slowapi.errors import RateLimitExceeded

# Configure structured logging before app creation so lifespan logs are structured
setup_logging(
    json_logs=settings.log_json,
    log_level=settings.log_level,
)
structlog.contextvars.bind_contextvars(service="api")

logger = structlog.stdlib.get_logger(__name__)


def _warn_if_cors_unset(settings_obj, log) -> None:
    """Warn when CORS_ALLOWED_ORIGINS is unset in prod.

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


def _session_secret(settings_obj) -> str:
    """Session cookie key: the dedicated key, else JWT_SECRET_KEY unchanged."""
    return (
        settings_obj.session_secret_key or settings_obj.jwt_secret_key
    ).get_secret_value()


_TILE_KEY_REFUSAL = (
    "GeoLens 1.33.0, not before 2027-02-10, will refuse to start with it. "
    "Set a new value of at least 32 characters (`openssl rand -hex 32`), the "
    "same on every API replica. Signed tile URLs issued under the old key stop "
    "verifying until the page reloads them."
)


def _warn_on_weak_signing_keys(settings_obj, log) -> None:
    """Production startup warnings for the session and tile signing keys.

    An unset SESSION_SECRET_KEY shares the JWT secret. A configured
    TILE_SIGNING_SECRET that is short, known-public or equal to the JWT secret
    still boots; the short and known-public cases name the release that will
    refuse them. Unset TILE_SIGNING_SECRET warns in signing.py.
    """
    if not settings_obj.is_production:
        return
    if settings_obj.session_secret_key is None:
        log.warning(
            "session_secret_key_unset",
            message=(
                "SESSION_SECRET_KEY is unset in production; the session cookie "
                "is signed with JWT_SECRET_KEY. Set it to a separate secret "
                "(openssl rand -hex 32), the same on every API replica."
            ),
        )
    tile = settings_obj.tile_signing_secret
    if tile is not None:
        raw = tile.get_secret_value()
        if len(raw) < 32:
            log.warning(
                "tile_signing_secret_weak",
                message=(
                    "TILE_SIGNING_SECRET is shorter than 32 characters. "
                    f"{_TILE_KEY_REFUSAL}"
                ),
            )
        if raw in KNOWN_PUBLIC_CREDENTIALS:
            log.warning(
                "tile_signing_secret_weak",
                message=(
                    f"TILE_SIGNING_SECRET is a known-public value. {_TILE_KEY_REFUSAL}"
                ),
            )
        if raw == settings_obj.jwt_secret_key.get_secret_value():
            log.warning(
                "tile_signing_secret_weak",
                message=(
                    "TILE_SIGNING_SECRET equals JWT_SECRET_KEY, so it does not "
                    "separate the two. Replace it with `openssl rand -hex 32`."
                ),
            )


async def sweep_stale_jobs_once(
    *, detailed: bool = False
) -> tuple[int, int] | dict[str, int]:
    """Run one stale-ingest sweep without an unscoped hosted-mode query.

    Single-tenant keeps the one-session path. Hosted mode reads the tenant
    registry, then runs each tenant under ``tenant_job_context`` so FORCE RLS
    scopes ``ingest_jobs`` access. A broken tenant doesn't block the rest.
    """
    from app.core.db import async_session  # late-bind for tests
    from app.platform.jobs.router import fail_stale_jobs
    from app.platform.jobs.sweep import purge_terminal_job_tokens

    # Purge once per pass, not per tenant — procrastinate_jobs has
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

    Also reclaims orphaned atomic-write scratch files across the
    whole staging root (``LocalStorageProvider.put``'s ``<name>.<hex>.tmp``
    left behind by a mid-write kill), not just ``exports/``.
    """
    scratch = sweep_orphaned_write_scratch_occasionally(
        Path(settings.upload_staging_dir),
        age_threshold_seconds=EXPORTS_PERIODIC_SWEEP_AGE_SECONDS,
    )
    if scratch:
        logger.info("orphaned_write_scratch_swept", removed=scratch)
    # Reclaim GDAL bearer-header tempfiles a SIGKILL/OOM left on
    # the container tmpfs (gdal_header_dir()). Uses the boot-time 1-hour age,
    # not the wider export threshold — a header lives for one ogr2ogr run.
    gdal_headers = sweep_stale_gdal_header_files()
    if gdal_headers:
        logger.info("stale_gdal_header_files_swept", removed=gdal_headers)
    return sweep_orphaned_exports(
        exports_dir, age_threshold_seconds=EXPORTS_PERIODIC_SWEEP_AGE_SECONDS
    )


async def _sweep_orphaned_exports_and_log(exports_dir: Path, log) -> None:
    """Sweep exports/ in a worker thread; log only when something was removed.

    Split out to keep ``lifespan`` under the McCabe gate. Uses
    ``EXPORTS_PERIODIC_SWEEP_AGE_SECONDS``, not the boot-time default: this runs
    continuously on a short cadence and needs a wider safety margin before
    treating a directory as abandoned. Runs via ``run_in_thread_draining`` so
    ``shutil.rmtree`` doesn't stall request handling and a graceful shutdown
    waits for an in-flight rmtree instead of abandoning it mid-write.
    """
    deleted, _ = await run_in_thread_draining(
        _sweep_orphaned_exports_periodic, exports_dir
    )
    if deleted:
        log.info("Swept orphaned exports", deleted=deleted)


def install_api_query_deadline() -> None:
    """Put the API's statement deadline on the engine this process uses.

    On the engine, not one dependency — handlers open sessions
    directly via ``async_session()`` in 20+ modules, so binding it in
    ``get_db`` would leave those with no deadline. Called at import
    (covers transactions before lifespan runs) and again from the
    lifespan (idempotent; covers a rebound test engine, which is also why
    the engine is late-bound).

    The worker never imports this module, so its engine keeps no
    deadline on purpose — it runs single statements for minutes.
    """
    from app.core.db import engine
    from app.core.statement_timeout import install_api_statement_timeout

    install_api_statement_timeout(engine)


install_api_query_deadline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.db import engine  # late-bind for tests

    # Idempotent re-install; covers a test fixture that rebound the engine.
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

    # Fail closed on migration-head skew in EITHER direction (DB
    # behind = migrate didn't run; DB ahead = image rolled back below schema).
    # Runs after the connectivity probe so a transient outage retries above.
    from app.core.db.schema_skew import assert_schema_in_sync

    await assert_schema_in_sync()

    await seed_bootstrap_identity()

    # Surface unset CORS_ALLOWED_ORIGINS in production once.
    _warn_if_cors_unset(settings, logger)
    _warn_on_weak_signing_keys(settings, logger)

    # The rate-limit storage decision is made at import, before
    # setup_logging() above, so its notices are queued rather than logged
    # there and flushed here into the configured stream.
    emit_startup_notices()

    # Shared bootstrap (extension load, overlay check, edition init, storage/S3
    # probe, billing on_startup, cache init); the worker delegates to it too.
    await bootstrap(app=app)

    # Same affirmative port assertion the worker runs, so both entrypoints fail
    # closed together: a license-key activation with a missing overlay would
    # otherwise crash the worker while the API kept serving on community ports.
    # No-op in community/single-tenant.
    assert_enterprise_ports_resolved()

    staging_root = ensure_staging_ready(settings.upload_staging_dir)
    exports_dir = ensure_staging_ready(staging_root / "exports")

    # Two Uvicorn workers share one staging volume, so an
    # unconditional sweep could truncate an export a sibling is still
    # writing. Share the worker's age-aware sweeper instead.
    sweep_orphaned_exports(exports_dir)
    # Reclaim GDAL bearer-header tempfiles orphaned by a crash
    # before this boot, from the container tmpfs (not staging_root) — this
    # covers a process death that didn't take the container with it.
    sweep_stale_gdal_header_files()

    await init_tile_pool()
    await task_app.open_async()

    from app.observability.metrics.memory import update_memory_metrics
    from app.observability.metrics.pool import update_pool_metrics
    from app.observability.metrics.refresh import update_refresh_metrics

    pool_metrics_task = asyncio.create_task(update_pool_metrics())
    # Observed HERE, not in the worker — the worker serves no
    # /metrics endpoint. Gauges derive from catalog.dataset_refresh_runs in
    # livemostrecent mode, so every uvicorn worker reports one answer.
    refresh_metrics_task = asyncio.create_task(update_refresh_metrics())
    # per-worker RSS gauge + log watermark so an OOM-bound worker
    # is visible in normal logs before the kernel kills it.
    memory_metrics_task = asyncio.create_task(update_memory_metrics())
    # Reap gauge_live*.db files left by a sibling worker
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
                # Interval is the credential module's — the
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
        """slowapi's sync accessors read a per-process cache that
        set()/reset() seeds for 30s on the ONE worker that wrote it — admin
        changes never propagate fleet-wide. Re-resolve from the DB (get()
        warms the cache) on every worker, below _CACHE_TTL. The log level
        has the same single-process side effect, so it is re-applied here.
        """
        from app.core.db import async_session
        from app.core.persistent_config import (
            BASEMAP_PROXY_RATE_LIMIT,
            GLOBAL_RATE_LIMIT,
            LOGIN_RATE_LIMIT,
            SEMANTIC_SEARCH_RATE_LIMIT,
            sync_log_level,
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
                    await sync_log_level(session)
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
    # Drop this worker's multiprocess metric files so a
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

GeoLens supports four authentication methods. Public datasets are accessible
without credentials; private/restricted datasets require one of:

| Method | Usage |
|--------|-------|
| **API Key header** | `X-Api-Key: <key>` |
| **JWT Bearer token** | `Authorization: Bearer <token>` |
| **API Key as a Basic password** | `Authorization: Basic base64(<any username>:<key>)` |
| **API Key query param** (deprecated) | `?api_key=<key>` |

Priority: header API key > Basic API key > query param API key > JWT > anonymous.

**HTTP Basic carries an API key, never an account password**, and like the
query parameter it authenticates `GET`, `HEAD` and `OPTIONS` only, since a
browser that saved the login replays it on cross-site requests. On any other
method, or when the header is malformed, the login is a credential that cannot
be resolved (see below). It is meant for desktop GIS clients that send a saved
login only after a Basic challenge: point them at `{your-server}/api/desktop`.
It serves the OGC API again (the landing page, conformance, the collections
and their items, and an OpenAPI document of those routes) to signed-in callers
only, answering `401` with `WWW-Authenticate: Basic` to any request without a
working credential, public collections included. Its links stay under
`/api/desktop`, so a client that saves the address keeps being challenged.

**The `?api_key=` query parameter is deprecated, and it authenticates reads
only.** A key sent in the URL is recorded by server access logs and by any
proxy or CDN that terminates TLS in front of GeoLens, so it authenticates
`GET`, `HEAD` and `OPTIONS` and nothing else. On any other method the key is
ignored and the request is answered as if no credential had been sent. Prefer the `X-Api-Key` header, which carries reads
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

# Docs exposure (and the Secure session cookie below) are gated on the
# explicit ENVIRONMENT setting, not the LOG_JSON log-format flag. is_production
# falls back to LOG_JSON when ENVIRONMENT is unset (backward compatibility).
_is_production = settings.is_production


# Read from the installed backend distribution metadata so
# `make version-check` can enforce that all version sites agree. The fallback
# below covers a source checkout with no `uv pip install -e .`; `make bump`
# rewrites it.
_FALLBACK_APP_VERSION = "1.31.0"


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
    # FastAPI adds the root path to ``servers`` only when serving
    # /openapi.json, so app.openapi() (the committed snapshot) would omit it.
    servers=[{"url": "/api"}],
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
    # redirect_slashes=False — with the default True, a
    # trailing-slash 307's Location header leaks the in-container
    # ``api:8000`` hostname to external callers. Trailing-slash routes
    # instead register a no-slash alias via stacked decorators
    # (``include_in_schema=False``), so both shapes resolve identically.
    redirect_slashes=False,
    lifespan=lifespan,
)

from app.observability.health.schemas import HealthResponse  # noqa: E402
from app.standards.ogc.errors import (  # noqa: E402
    ProblemDetail,
    UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
    UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
    register_error_handlers,
)

register_error_handlers(app)

app.state.limiter = limiter


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # Advertise the retry window (exc.limit.limit.get_expiry()).
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
    # reserve_dataset_slot raises a plain exception so the worker
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
    # reserve_storage_bytes raises a plain exception in the worker;
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


def _catalog_lock_conflict_response(
    request: Request,
    message: str,
    detail: str | dict[str, str] | None = None,
) -> JSONResponse:
    """The 409 for a contended row: top-level ``code`` ``catalog_lock_conflict``
    on every route, beside the ``detail`` that route has always answered."""
    logger.info(
        "catalog row lock conflict",
        path=safe_access_log_path(request.url.path),
    )
    if detail is None:
        title = "Catalog entry is busy"
        detail = {"code": CATALOG_LOCK_CONFLICT_CODE, "message": message}
    else:
        # A route's released detail, under the title its HTTPException had.
        title = "Conflict"
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content=ProblemDetail(
            title=title,
            status=status.HTTP_409_CONFLICT,
            detail=detail,
            code=CATALOG_LOCK_CONFLICT_CODE,
        ).model_dump(),
        media_type="application/problem+json",
    )


async def _catalog_lock_conflict_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Map a contended catalog row to 409, from wherever it was reached.

    Safe to retry: the acquisition rolled its transaction back first.
    """
    return _catalog_lock_conflict_response(
        request, str(exc), getattr(exc, "detail", None)
    )


async def _database_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Map an operational database failure to a 503.

    Connection loss, timeout, cancellation, and serialization failures are not
    domain data: handlers re-raise what they can't legitimately answer, so
    infrastructure incidents surface instead of being hidden.
    Non-operational errors (integrity/syntax/access) keep their 500 path.

    A lock conflict raised post-acquisition, while this request's
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
        # The path can be /api/maps/shared/{token}; the access-log
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

# Registered FIRST so it ends up INNERMOST (add_middleware prepends; closest
# to the router). Must be a plain ASGI callable, not BaseHTTPMiddleware —
# that spawns a separate task, so a route handler's ContextVar
# (credential-secret registry, core/service_tokens.py) never propagates back
# out. Innermost, it scrubs an unhandled exception before any layer reads it.
app.add_middleware(CredentialScrubASGIMiddleware)
app.add_middleware(DesktopEntryGateMiddleware)

# Gate https_only on the production indicator — dev/test
# have no TLS terminator, so https_only=True would silently strip the
# session cookie. Same settings.is_production used for docs gating above.
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret(settings),
    https_only=settings.is_production,
)
app.add_middleware(RequestLoggingMiddleware)
# Resolve tenant context after request logging so
# the tenant_id is available to all route handlers.  In single_tenant mode
# (default) this is a strict no-op (single boolean check, no state mutation).
app.add_middleware(TenantContextMiddleware)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(DesktopEntryRewriteMiddleware)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.upload_max_size_mb * 1024 * 1024,
)
# Mount order matters — add_middleware PREPENDS, so later calls
# wrap OUTER and run LAST on the response. SecurityHeaders must run before
# GZip compresses, so: 1) SecurityHeadersMiddleware (added first, inner,
# runs first on response) 2) GZipMiddleware (added second, outer, runs
# second). Pinned by tests/test_phase_273_middleware_order.py.
app.add_middleware(SecurityHeadersMiddleware)
# The COG and COPC media types join starlette's default exclusions (avif/gif/
# jpeg/png/webp), and each is produced only by its byte route. This middleware
# compresses a 200 but skips a 206, so a strong ETag would identify gzip bytes
# on the full download but raw bytes on a range: a client resuming the encoded
# representation could splice raw bytes at encoded offsets and assemble a
# corrupt file. Excluding the types keeps one representation per ETag.
app.add_middleware(
    GZipMiddleware,
    minimum_size=256,
    compresslevel=4,
    exclude_content_types=DEFAULT_EXCLUDED_CONTENT_TYPES
    + ("image/tiff", POINTCLOUD_MEDIA_TYPE),
)
# The export download and the 3D Tiles files are excluded by path: their media
# types also come from routes that serve one representation and gain from gzip.
# Added after GZipMiddleware so it runs first and strips gzip from the
# Accept-Encoding that GZipMiddleware reads.
app.add_middleware(NoCompressionByPathMiddleware)
app.add_middleware(DynamicCORSMiddleware)

app.include_router(api_router)


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
    """Register a hidden no-slash alias for every trailing-slash
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
    """Serve HEAD wherever the CORS preflight says we do.

    ``DynamicCORSMiddleware`` advertises HEAD on standards preflights, but
    FastAPI's ``APIRoute`` doesn't add HEAD alongside GET the way
    starlette's ``Route`` does, so these routes 405'd on HEAD despite the
    preflight promising it. Derived here (not ~48 per-router decorators)
    so the answering set can't drift from the advertised set — both read
    ``standards_api_path``. The catalog search routes don't need
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


def _unresolvable_credential_capability_responses() -> dict:
    """Map each capability-accepting handler to the 401 naming what it accepts."""
    from app.modules.catalog.datasets.api.router_aggregate import aggregate_endpoint
    from app.modules.catalog.datasets.api.router_data import get_dataset_rows_endpoint
    from app.modules.catalog.features.router import get_features_geojson_z_endpoint
    from app.modules.catalog.maps.router_sharing import get_shared_map_endpoint
    from app.processing.tiles.router import (
        cluster_tile_endpoint,
        get_tile_tokens_batch,
        raster_auth_check,
        raster_tile_proxy,
        tile_endpoint,
    )

    # Vector/raster tile serving verifies both X-Embed-Token and a signed
    # template (sig, exp, scope); the batch token mint and the other
    # capability handlers check X-Embed-Token only.
    return {
        aggregate_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_dataset_rows_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_features_geojson_z_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_shared_map_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        get_tile_tokens_batch: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_EMBED_TOKEN,
        tile_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
        cluster_tile_endpoint: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
        raster_tile_proxy: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
        raster_auth_check: UNRESOLVABLE_CREDENTIAL_RESPONSE_WITH_CAPABILITY,
    }


_add_trailing_slash_aliases(app)
_register_standards_head_routes(app)
install_standards_aware_openapi(app, _unresolvable_credential_capability_responses)

init_metrics(app)


# Liveness, split out from readiness. `/health` 503s if the
# DB, object store, or cache is down — but the cache path survives a
# Valkey outage (in-memory fallback behind a circuit breaker), so a
# dependency the API serves fine still marked the container unhealthy,
# restart-looping `frontend: depends_on: api: service_healthy`.
#
# This answers only "the process is up" (mirrors worker's split in
# observability/health/worker.py); `include_in_schema=False` since it's
# infrastructure, not API surface. Exempt from the limiter (unlike
# `/health`): a kubelet probing every second is already at that
# cap, and a 429'd liveness probe gets the pod killed.
@app.get("/health/live", include_in_schema=False, tags=["Health"])
@limiter.exempt
async def health_live(request: Request):
    """Liveness probe: process is up, no dependency checks."""
    return {"status": "ok"}


# /health is rate-limited (60/min per IP), not exempt, to bound
# abuse of this unauthenticated, dependency-probing endpoint. Generous on
# purpose: Docker's healthcheck polls every 10s (~6/min) plus a small LB
# constant, so legitimate infra never trips it. Response omits raw
# provider exception strings (`check_health(include_errors=False)`) so
# anonymous callers never see DB/S3/cache internals. Kept as a comment,
# not a docstring, so this stays out of the public OpenAPI description.
@app.head("/health", include_in_schema=False)
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
    summary="Check service health",
)
@limiter.limit("60/minute")
async def health(request: Request):
    """Health check endpoint for ALB, Docker, and Nginx."""
    from app.observability.health.service import (
        begin_health_probe,
        check_health,
        health_alert_after,
    )
    from fastapi.responses import JSONResponse

    seq = begin_health_probe()
    result = await check_health()
    # Report version + build commit so a deployment can be
    # verified over HTTP (prod disables /docs). GEOLENS_BUILD_SHA is
    # stamped by publish.yml; local/source builds report null.
    import os

    result["version"] = app.version
    result["build"] = os.environ.get("GEOLENS_BUILD_SHA") or None
    status_code = 200 if result["status"] == "healthy" else 503
    return JSONResponse(
        content=result,
        status_code=status_code,
        background=await health_alert_after(seq, result),
    )


__all__ = [
    "app",
    "health",
    "lifespan",
]
