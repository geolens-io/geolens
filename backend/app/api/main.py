# ruff: noqa: E402
import asyncio
from contextlib import asynccontextmanager

import structlog

# Must run BEFORE FastAPI/Starlette imports — see redirect_tempfile_to_staging
# docstring. Originally added inline for gh #101 (260508-rr5), now shared with
# the worker (which had the same /tmp tmpfs problem during COG conversion).
from app.core.config import settings
from app.core.runtime.staging import redirect_tempfile_to_staging

redirect_tempfile_to_staging(settings.upload_staging_dir)

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.observability.metrics import init_metrics
from app.platform.cache.provider import init_tile_cache

# settings already imported above for the tempdir override — do NOT reimport
from app.core.db import async_session, engine
from app.core.db.tenant_session import tenant_job_context
from app.core.logging_config import setup_logging
from app.core.tenancy import is_multi_tenant
from app.core.runtime.staging import ensure_staging_ready, sweep_orphaned_exports
from app.platform.extensions.bootstrap import (
    assert_enterprise_ports_resolved,
    bootstrap,
)
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.providers.local import hash_password
from app.modules.auth.router import limiter
from app.processing.ingest.tasks import task_app
from app.api.middleware.body_limit import RequestBodyLimitMiddleware
from app.api.middleware.cors import DynamicCORSMiddleware
from app.api.middleware.logging import RequestLoggingMiddleware
from app.api.middleware.security import SecurityHeadersMiddleware
from app.api.middleware.tenant_context import TenantContextMiddleware
from app.processing.tiles.pool import close_tile_pool, init_tile_pool
from app.processing.tiles.router import _titiler_client
from app.standards.ogc.utils import standards_api_path
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Configure structured logging before app creation so lifespan logs are structured
setup_logging(json_logs=settings.log_json, log_level=settings.log_level)
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
    production. Anonymous standards reads remain browser-accessible, while
    credentialed application routes require an explicit origin allowlist.

    Gated on is_production so dev/test runs don't get the warning. SEC-005:
    previously gated on log_json (the de-facto production indicator); now uses
    the explicit settings.is_production.
    """
    if settings_obj.is_production and not settings_obj.cors_allowed_origins:
        log.warning(
            "cors_allowed_origins_unset",
            message=(
                "CORS_ALLOWED_ORIGINS is empty in production. "
                "Anonymous standards reads allow any browser origin, but "
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
    from app.platform.jobs.router import fail_stale_jobs

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


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    init_tile_cache()
    await init_tile_pool()
    await task_app.open_async()

    from app.observability.metrics.pool import update_pool_metrics

    pool_metrics_task = asyncio.create_task(update_pool_metrics())

    async def _stale_jobs_sweeper() -> None:
        """Periodically fail jobs whose worker crashed mid-run.

        Without this, an IngestJob row can sit in 'running' forever if no
        client polls it after the worker dies — the on-poll fail-fast logic
        in get_job_status only catches it when a user revisits the page.
        """
        sweeper_log = structlog.stdlib.get_logger("stale_jobs_sweeper")
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                pending_failed, running_failed = await sweep_stale_jobs_once()
                if pending_failed or running_failed:
                    sweeper_log.info(
                        "Failed stale jobs",
                        pending_failed=pending_failed,
                        running_failed=running_failed,
                    )
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
    stale_jobs_task.cancel()
    rate_limit_warmer_task.cancel()
    await task_app.close_async()
    await close_tile_pool()
    await _titiler_client.aclose()
    await engine.dispose()


_DESCRIPTION = """\
## Overview

GeoLens is a self-hosted spatial data catalog that ingests vector files
(GeoPackage, Shapefile, GeoJSON, CSV), stores them in PostGIS, and exposes
them through a standards-compliant OGC API.

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
| **API Key query param** | `?api_key=<key>` |

Priority: header API key > query param API key > JWT > anonymous.

### GDAL / ogr2ogr with API Key

```bash
# List collections (including private ones accessible to your key)
ogrinfo "OAPIF:{your-server}/api/?api_key=YOUR_KEY"

# Download a private collection
ogr2ogr -f GPKG out.gpkg "OAPIF:{your-server}/api/?api_key=YOUR_KEY" {collection-id}
```

### QGIS with API Key

In the WFS / OGC API Features connection dialog, append `?api_key=YOUR_KEY`
to the server URL.
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
        "name": "config-ops",
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
_FALLBACK_APP_VERSION = "1.4.7"


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
    register_error_handlers,
)

register_error_handlers(app)

app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # fix(#315): advertise the retry window (exc.limit.limit.get_expiry(), seconds).
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
        path=request.url.path,
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
app.add_middleware(GZipMiddleware, minimum_size=256, compresslevel=4)
app.add_middleware(DynamicCORSMiddleware)

app.include_router(api_router)


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
    from fastapi.routing import APIRoute

    # Snapshot existing (method, path) pairs to avoid double-registration.
    existing_paths: set[tuple[str, str]] = set()
    for route in target_app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            existing_paths.add((method, route.path))

    added = 0
    for route in list(target_app.routes):
        if not isinstance(route, APIRoute):
            continue
        if not route.path.endswith("/") or route.path == "/":
            continue
        no_slash = route.path.rstrip("/")

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
            target_app.add_api_route(
                path=no_slash,
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
                methods=[method],
                operation_id=None,  # MUST differ from canonical for
                # uniqueness; FastAPI auto-generates
                # when None.
                response_model_include=route.response_model_include,
                response_model_exclude=route.response_model_exclude,
                response_model_by_alias=route.response_model_by_alias,
                response_model_exclude_unset=route.response_model_exclude_unset,
                response_model_exclude_defaults=route.response_model_exclude_defaults,
                response_model_exclude_none=route.response_model_exclude_none,
                include_in_schema=False,  # ROUTE-01: hide aliases from OpenAPI
                response_class=route.response_class,
                name=f"{route.name}__no_slash_alias" if route.name else None,
                openapi_extra=route.openapi_extra,
                generate_unique_id_function=route.generate_unique_id_function,
            )
            existing_paths.add((method, no_slash))
            added += 1

    if added > 0:
        # Re-build the FastAPI route table cache by clearing any cached
        # OpenAPI spec — the next /openapi.json request rebuilds from
        # the current app.routes state.
        target_app.openapi_schema = None


_add_trailing_slash_aliases(app)


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


def _route_operation(schema: dict, route, method: str) -> dict | None:
    """Resolve an APIRoute to its generated OpenAPI operation."""
    return schema.get("paths", {}).get(route.path_format, {}).get(method.lower())


def _normalize_security_contract(schema: dict) -> None:
    """Publish every runtime credential form and anonymous-capable alternative."""
    from fastapi.routing import APIRoute

    from app.modules.auth.dependencies import get_optional_user

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
    # onto their generated clients. Only the normal optional dependency should
    # gain the anonymous-or-credential security alternatives here.
    optional_targets = {get_optional_user}
    credential_alternatives = [
        {"OAuth2PasswordBearer": []},
        {"ApiKeyHeader": []},
        {"ApiKeyQuery": []},
    ]

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        optional_auth = _dependency_uses(route.dependant, optional_targets)
        for method in route.methods or ():
            operation = _route_operation(schema, route, method)
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
    from fastapi.routing import APIRoute

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        endpoint_name = f"{route.endpoint.__module__}.{route.endpoint.__name__}"
        # The limiter has a global default, so undecorated routes are limited too.
        # Only explicit @limiter.exempt handlers bypass the middleware contract.
        if endpoint_name in limiter._exempt_routes:
            continue
        for method in route.methods or ():
            operation = _route_operation(schema, route, method)
            if operation is not None:
                operation.setdefault("responses", {}).setdefault(
                    "429", RATE_LIMIT_RESPONSE
                )


def _document_global_failures(schema: dict) -> None:
    """Document exception handlers that apply outside individual routers."""
    from fastapi.routing import APIRoute

    from app.core.dependencies import get_db

    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.include_in_schema:
            continue
        uses_database = _dependency_uses(route.dependant, {get_db})
        for method in route.methods or ():
            operation = _route_operation(schema, route, method)
            if operation is None:
                continue
            responses = operation.setdefault("responses", {})
            responses.setdefault("500", INTERNAL_SERVER_ERROR_RESPONSE)
            if uses_database:
                responses.setdefault("503", DATABASE_UNAVAILABLE_RESPONSE)


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
    _document_rate_limits(schema)
    _document_global_failures(schema)

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
