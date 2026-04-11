import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from app.middleware.cors import DynamicCORSMiddleware
from sqlalchemy import func, select, text

from starlette.middleware.sessions import SessionMiddleware

from app.admin.router import router as admin_router
from app.audit.router import router as audit_router
from app.auth.models import Role, User, UserRole
from app.auth.providers.local import hash_password
from app.auth.router import limiter, router as auth_router
from app.config import settings
from app.cache import init_cache
from app.cache.provider import init_tile_cache
from app.metrics import init_metrics
from app.storage import init_storage
from app.database import async_session, engine
from app.datasets.router import router as datasets_router
from app.datasets.router_export import router as datasets_export_router
from app.datasets.router_vrt import router as datasets_vrt_router
from app.datasets.router_data import router as datasets_data_router
from app.datasets.router_metadata import router as datasets_metadata_router
from app.datasets.router_reupload import router as datasets_reupload_router
from app.records.router import router as records_router
from app.export.router import router as export_router
from app.ingest.router import router as ingest_router
from app.jobs.router import router as jobs_router
from app.logging_config import setup_logging
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.middleware.body_limit import RequestBodyLimitMiddleware
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.ogc.router import ogc_features_router, ogc_router
from app.collections.router import router as collections_crud_router
from app.ai.router import router as ai_router
from app.services.router import router as services_router
from app.layers.router import layers_router
from app.settings.models import AppSetting  # noqa: F401
from app.settings.router import router as settings_router
from app.maps.router import router as maps_router
from app.features.router import features_router
from app.runtime.staging import ensure_staging_ready
from app.auth.oauth.router import router as oauth_router
from app.config_ops.router import router as config_ops_router
from app.search.router import collections_router, search_router
from app.embed_tokens.admin_router import router as embed_tokens_admin_router
from app.embed_tokens.router import router as embed_tokens_router
from app.tiles.router import router as tiles_router
from app.tiles.pool import init_tile_pool, close_tile_pool
from app.stac.router import stac_router
from app.extensions import load_extensions, list_extensions, get_extension_routers
from app.edition import init_edition, get_edition
from app.ingest.tasks import task_app

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

            # Link to admin role
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
    # Startup: verify database connection
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))

    # Seed roles and initial admin
    await seed_roles()
    await seed_initial_admin()

    # Discover and load enterprise extensions (no-op if geolens-enterprise not installed)
    load_extensions()
    init_edition(list_extensions())
    edition_info = get_edition()
    logger.info(
        "Edition detected",
        edition=edition_info.edition,
        features=list(edition_info.features),
    )

    # Register enterprise routers dynamically (no-op if no extensions)
    for ext_router in get_extension_routers():
        app.include_router(ext_router)

    # Ensure staging paths exist and are writable before bootstrapping services.
    staging_root = ensure_staging_ready(settings.upload_staging_dir)
    ensure_staging_ready(staging_root / "exports")

    # Sweep orphaned export temp dirs from previous crashes
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

    # Initialize storage provider (local filesystem or S3)
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
            logger.info(
                "S3 connectivity verified",
                bucket=settings.s3_bucket,
                credential_source=cred_method,
                addressing_style=settings.s3_addressing_style,
            )
        except Exception as exc:
            logger.error(
                "S3 health check failed -- cannot start",
                error=str(exc),
                bucket=settings.s3_bucket,
                endpoint=settings.s3_endpoint_url,
                region=settings.s3_region,
            )
            raise RuntimeError(f"S3 health check failed: {exc}") from exc

    # AWS Marketplace metering (non-blocking)
    if settings.aws_marketplace_product_code:
        try:
            from app.marketplace import register_marketplace_usage

            register_marketplace_usage(settings, logger)
        except Exception as exc:
            logger.warning(
                "AWS Marketplace metering failed -- continuing without metering",
                error=str(exc),
                product_code=settings.aws_marketplace_product_code,
            )

    # Initialize cache provider (in-memory or Redis/Valkey)
    init_cache()

    # Initialize tile cache (Redis binary cache, only when redis_url is set)
    init_tile_cache()

    # Initialize dedicated tile connection pool
    await init_tile_pool()

    # Open procrastinate task app (allows API to defer async tasks)
    await task_app.open_async()

    # Start background pool metrics collector
    from app.metrics.pool import update_pool_metrics

    pool_metrics_task = asyncio.create_task(update_pool_metrics())

    yield

    # Shutdown pool metrics collector
    pool_metrics_task.cancel()

    # Close procrastinate task app
    await task_app.close_async()

    # Close tile connection pool
    await close_tile_pool()

    # Dispose engine
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

# Disable interactive docs when structured logging is enabled (production).
_is_production = settings.log_json

app = FastAPI(
    title="GeoLens API",
    version="1.0.0",
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

from app.ogc.errors import ProblemDetail, register_error_handlers  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

register_error_handlers(app)

app.state.limiter = limiter


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    # Use the shared ProblemDetail model for consistency with the rest of
    # the API's RFC 7807 error responses.
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

app.add_middleware(
    SessionMiddleware, secret_key=settings.jwt_secret_key.get_secret_value()
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    RequestBodyLimitMiddleware,
    max_bytes=settings.upload_max_size_mb * 1024 * 1024,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=256, compresslevel=4)

# CORS -- must be outermost middleware (added last = executes first)
# DynamicCORSMiddleware reads allowed origins from PersistentConfig (hot-reloadable).
# Always added (when origins is empty, passes through without adding headers).
app.add_middleware(DynamicCORSMiddleware)

app.include_router(ogc_router)  # OGC discovery -- must be first (root path)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(audit_router)
app.include_router(ingest_router)
# Register export BEFORE core (has /dcat/ that conflicts with /{dataset_id})
app.include_router(datasets_export_router)
app.include_router(datasets_router)
app.include_router(datasets_vrt_router)
app.include_router(datasets_data_router)
app.include_router(datasets_metadata_router)
app.include_router(datasets_reupload_router)
app.include_router(records_router)
app.include_router(features_router)
app.include_router(export_router)
app.include_router(jobs_router)
app.include_router(search_router)
app.include_router(collections_router)
app.include_router(collections_crud_router)
app.include_router(
    ogc_features_router
)  # Per-dataset OGC Features -- after /collections/datasets routes
app.include_router(maps_router)
app.include_router(ai_router)
app.include_router(services_router)
app.include_router(layers_router)
app.include_router(settings_router)
app.include_router(oauth_router)
app.include_router(config_ops_router)
app.include_router(embed_tokens_router)
app.include_router(embed_tokens_admin_router)
app.include_router(tiles_router)
app.include_router(stac_router)

from app.health.schemas import HealthResponse  # noqa: E402

# Prometheus instrumentation -- must happen before app starts (cannot add middleware in lifespan)
init_metrics(app)


@app.get("/health", response_model=HealthResponse)
@limiter.exempt
async def health():
    """Health check endpoint for ALB, Docker, and Nginx."""
    from app.health.service import check_health
    from fastapi.responses import JSONResponse

    result = await check_health()
    status_code = 200 if result["status"] == "healthy" else 503
    return JSONResponse(content=result, status_code=status_code)
