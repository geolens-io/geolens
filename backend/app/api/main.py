import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.observability.metrics import init_metrics
from app.platform.cache import init_cache
from app.platform.cache.provider import init_tile_cache
from app.core.config import settings
from app.core.db import async_session, engine
from app.core.logging_config import setup_logging
from app.core.runtime.staging import ensure_staging_ready
from app.core.edition import get_edition, init_edition
from app.platform.extensions import (
    get_billing_extensions,
    get_extension_routers,
    list_extensions,
    load_extensions,
)
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.providers.local import hash_password
from app.modules.auth.router import limiter
from app.processing.ingest.tasks import task_app
from app.api.middleware.body_limit import RequestBodyLimitMiddleware
from app.api.middleware.cors import DynamicCORSMiddleware
from app.api.middleware.logging import RequestLoggingMiddleware
from app.api.middleware.security import SecurityHeadersMiddleware
from app.platform.storage import init_storage
from app.processing.tiles.pool import close_tile_pool, init_tile_pool
from app.processing.tiles.router import _titiler_client
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Configure structured logging before app creation so lifespan logs are structured
setup_logging(json_logs=settings.log_json, log_level=settings.log_level)
structlog.contextvars.bind_contextvars(service="api")

logger = structlog.stdlib.get_logger(__name__)

# Default roles to seed if they don't exist
DEFAULT_ROLES = [
    {"name": "admin", "description": "Full system access"},
    {"name": "editor", "description": "Can create and edit datasets"},
    {"name": "viewer", "description": "Read-only access to permitted datasets"},
]


async def seed_roles() -> None:
    """Ensure default roles exist in the database (defensive safety net)."""
    async with async_session() as session:
        for role_data in DEFAULT_ROLES:
            result = await session.execute(
                select(Role).where(Role.name == role_data["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(Role(**role_data))
                logger.info("Seeded role: %s", role_data["name"])
        await session.commit()


def _warn_if_cors_unset(settings_obj, log) -> None:
    """SEC-08 / M-72: warn loudly when CORS_ALLOWED_ORIGINS is unset in
    production. DynamicCORSMiddleware will still respond (no breakage),
    but the operator likely INTENDED to lock down origins and forgot.

    Gated on log_json so dev/test runs don't get the warning. log_json is
    the same production indicator used at line 407 for `_is_production`.
    """
    if settings_obj.log_json and not settings_obj.cors_allowed_origins:
        log.warning(
            "cors_allowed_origins_unset",
            message=(
                "CORS_ALLOWED_ORIGINS is empty in production (LOG_JSON=true). "
                "All origins will pass the request-origin check; this is "
                "likely a misconfiguration. Set "
                "CORS_ALLOWED_ORIGINS=<comma-separated origins> to restrict."
            ),
        )


async def seed_initial_admin() -> None:
    """Create an initial admin user if no users exist.

    Uses GEOLENS_ADMIN_USERNAME and GEOLENS_ADMIN_PASSWORD from settings
    (configurable via environment variables).
    """
    async with async_session() as session:
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
                select(Role).where(Role.name == "admin")
            )
            admin_role = role_result.scalar_one()
            session.add(UserRole(user_id=admin_user.id, role_id=admin_role.id))

            await session.commit()
            logger.info(
                "Initial admin user created: %s", settings.geolens_admin_username
            )


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

    await seed_roles()
    await seed_initial_admin()

    # SEC-08 / M-72: surface unset CORS_ALLOWED_ORIGINS in production once.
    _warn_if_cors_unset(settings, logger)

    load_extensions()
    init_edition(list_extensions())
    edition_info = get_edition()
    logger.info(
        "Edition detected",
        edition=edition_info.edition,
        features=list(edition_info.features),
    )

    for ext_router in get_extension_routers():
        app.include_router(ext_router)

    staging_root = ensure_staging_ready(settings.upload_staging_dir)
    ensure_staging_ready(staging_root / "exports")

    import shutil

    exports_dir = staging_root / "exports"
    if exports_dir.exists():
        orphaned = list(exports_dir.iterdir())
        if orphaned:
            for item in orphaned:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            logger.info("Cleaned orphaned export temp files", count=len(orphaned))

    init_storage()

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
            logger.info(
                "S3 connectivity verified",
                bucket=settings.s3_bucket,
                credential_source=cred_method,
                addressing_style=settings.s3_addressing_style,
            )
        except Exception as exc:  # broad: S3/MinIO SDK can throw varied connection/auth/region errors; fail-fast on boot
            logger.exception(
                "S3 health check failed -- cannot start",
                error=str(exc),
                bucket=settings.s3_bucket,
                endpoint=settings.s3_endpoint,
                region=settings.s3_region,
            )
            raise RuntimeError(f"S3 health check failed: {exc}") from exc

    # Phase 223 BILLING-04 / D-10: generic BillingExtension dispatch.
    # Community: DefaultBillingExtension.on_startup is a no-op (D-07).
    # Enterprise overlay (geolens-enterprise) registers MarketplaceBillingExtension
    # which reads AWS_MARKETPLACE_PRODUCT_CODE itself (D-13 — env-var gate lives
    # in the overlay, not in core).
    #
    # asyncio.wait_for(timeout=10.0) caps each extension at 10s — preserves
    # today's behavior of capping the boto3 register_usage call (which retries
    # 3x with ~60s timeouts) so an unreachable billing API doesn't block
    # container startup for ~3 minutes. Per-extension try/except (D-12)
    # ensures one failing extension does not poison the iteration.
    for ext in get_billing_extensions():
        try:
            await asyncio.wait_for(ext.on_startup(app), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "BillingExtension.on_startup timed out -- continuing without billing",
                extension=type(ext).__name__,
                timeout_seconds=10.0,
            )
        except Exception as exc:  # broad: extension startup hooks can throw provider-specific errors; isolate per-extension
            logger.warning(
                "BillingExtension.on_startup failed -- continuing without billing",
                extension=type(ext).__name__,
                error=str(exc),
            )

    init_cache()
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
        from app.core.db import async_session
        from app.platform.jobs.router import fail_stale_jobs

        sweeper_log = structlog.stdlib.get_logger("stale_jobs_sweeper")
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                async with async_session() as session:
                    pending_failed, running_failed = await fail_stale_jobs(session)
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

    yield

    pool_metrics_task.cancel()
    stale_jobs_task.cancel()
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

_is_production = settings.log_json

app = FastAPI(
    title="GeoLens API",
    version="1.0.2",
    summary="PostGIS-native geospatial data catalog with OGC API Features compliance",
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
    lifespan=lifespan,
)

from app.observability.health.schemas import HealthResponse  # noqa: E402
from app.standards.ogc.errors import ProblemDetail, register_error_handlers  # noqa: E402

register_error_handlers(app)

app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content=ProblemDetail(
            title="Too Many Requests",
            status=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc.detail),
        ).model_dump(),
        media_type="application/problem+json",
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# SEC-02 / M-64: gate https_only on the production indicator. Local-dev and
# test runs use log_json=False (no TLS terminator), so https_only=True would
# cause SessionMiddleware to silently strip the cookie. Production sets
# LOG_JSON=true (json-logging deploy config) so https_only=True flows through
# unchanged. _is_production at line 407 uses the same signal.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.jwt_secret_key.get_secret_value(),
    https_only=settings.log_json,
)
app.add_middleware(RequestLoggingMiddleware)
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

init_metrics(app)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
@limiter.exempt
async def health():
    """Health check endpoint for ALB, Docker, and Nginx."""
    from app.observability.health.service import check_health
    from fastapi.responses import JSONResponse

    result = await check_health()
    status_code = 200 if result["status"] == "healthy" else 503
    return JSONResponse(content=result, status_code=status_code)


__all__ = ["app", "health", "lifespan", "seed_initial_admin", "seed_roles"]
