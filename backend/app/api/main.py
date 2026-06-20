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
from app.core.logging_config import setup_logging
from app.core.runtime.staging import ensure_staging_ready
from app.platform.extensions.bootstrap import bootstrap
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

    Gated on is_production so dev/test runs don't get the warning. SEC-005:
    previously gated on log_json (the de-facto production indicator); now uses
    the explicit settings.is_production.
    """
    if settings_obj.is_production and not settings_obj.cors_allowed_origins:
        log.warning(
            "cors_allowed_origins_unset",
            message=(
                "CORS_ALLOWED_ORIGINS is empty in production. "
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

    # MIG-02: fail closed if the DB's applied migration heads do not match the
    # heads this image's migration scripts declare (skew in EITHER direction —
    # DB behind = migrate service didn't run / empty DB; DB ahead = image
    # rolled back below the DB schema). Runs after the connectivity probe so a
    # transient DB outage retries above instead of surfacing here.
    from app.core.db.schema_skew import assert_schema_in_sync

    await assert_schema_in_sync()

    await seed_roles()
    await seed_initial_admin()

    # SEC-08 / M-72: surface unset CORS_ALLOWED_ORIGINS in production once.
    _warn_if_cors_unset(settings, logger)

    # WORK-01: shared bootstrap — extension load, enterprise-overlay-requested check,
    # edition init, extension router include, storage + S3 health probe, billing
    # on_startup dispatch, cache init. bootstrap() is the single source of truth
    # for this sequence; both API and worker delegate here to prevent drift.
    await bootstrap(app=app)

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
_FALLBACK_APP_VERSION = "1.3.0"


def _resolve_app_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("geolens-backend")
    except PackageNotFoundError:
        return _FALLBACK_APP_VERSION


app = FastAPI(
    title="GeoLens API",
    version=_resolve_app_version(),
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

init_metrics(app)


# Phase 1230 EVENT-04: health-alert cooldown state.
# Module-level so it persists across requests within a single API process.
# _last_health_alert_at: epoch-float of the most recent degraded alert sent.
# _last_health_status:   last observed status ("healthy" or "degraded"); a
#   transition back to "healthy" resets _last_health_alert_at so the NEXT
#   degraded event produces a fresh alert after recovery (T-1230-06).
_last_health_alert_at: float = 0.0
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
@app.get("/health", response_model=HealthResponse, tags=["Health"])
@limiter.limit("60/minute")
async def health(request: Request):
    """Health check endpoint for ALB, Docker, and Nginx."""
    import time

    from app.observability.health.service import check_health
    from fastapi.responses import JSONResponse

    result = await check_health()
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
            _last_health_alert_at = 0.0
        _last_health_status = current_status
        # Emit only if outside the cooldown window (de-dup, T-1230-06).
        if now - _last_health_alert_at >= _HEALTH_ALERT_COOLDOWN_SECS:
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
        _last_health_alert_at = 0.0

    return JSONResponse(
        content=result, status_code=status_code, background=health_alert_task
    )


__all__ = ["app", "health", "lifespan", "seed_initial_admin", "seed_roles"]
