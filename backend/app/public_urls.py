"""Helpers for resolving public app/API URLs across deployment environments.

# Resolution order
# ----------------
# Public URLs (used in OGC self-links, share links, OAuth redirects, etc.)
# are resolved with this precedence, highest priority first:
#
#   1. Admin-set value in `catalog.app_settings` (`public_app_url` /
#      `public_api_url` keys) — admins can override at runtime via the UI
#   2. Legacy `public_base_url` setting (deprecated alias for `public_api_url`)
#   3. Environment variable: `PUBLIC_APP_URL` / `PUBLIC_API_URL`
#   4. Request-derived URL (Host header from current request, if available)
#   5. Hardcoded localhost defaults (development only)
#
# # Why this matters
# Anything stored in the database (share tokens, embed snippets, OGC link
# hrefs) needs an absolute URL that's reachable from outside the container.
# The container has no idea what its public hostname is, so we have to be
# told via env var or admin setting. Request-derived URLs are a fallback for
# the OGC links emitted in the same response (those CAN trust the current
# Host header), but stored URLs MUST come from settings.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.settings.models import AppSetting

PUBLIC_APP_URL_KEY = "public_app_url"
PUBLIC_API_URL_KEY = "public_api_url"
LEGACY_PUBLIC_API_URL_KEY = "public_base_url"

_DEFAULT_PUBLIC_APP_URL = "http://localhost:8080"
_DEFAULT_PUBLIC_API_URL = "http://localhost:8000"


def normalize_public_url(url: str | None) -> str | None:
    """Normalize a configured public URL and strip trailing slashes."""
    if url is None:
        return None
    stripped = url.strip()
    if not stripped:
        return None
    return stripped.rstrip("/")


def append_api_suffix(app_url: str) -> str:
    """Append /api to an app URL while preserving any existing path prefix."""
    parts = urlsplit(app_url)
    path = parts.path.rstrip("/")
    api_path = f"{path}/api" if path else "/api"
    return urlunsplit((parts.scheme, parts.netloc, api_path, "", ""))


def strip_api_suffix(api_url: str) -> str:
    """Remove a terminal /api segment from an API URL if present."""
    parts = urlsplit(api_url)
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def join_public_url(base_url: str, path: str) -> str:
    """Join an absolute public base URL with an API-relative path."""
    if not path.startswith("/"):
        path = "/" + path
    return normalize_public_url(base_url) + path


def _is_env_only() -> bool:
    return os.environ.get("ENV_ONLY_CONFIG", "").lower() in ("true", "1", "yes")


def _request_origin(request: Request | None) -> str | None:
    if request is None:
        return None

    origin = normalize_public_url(request.headers.get("origin"))
    if origin:
        return origin

    referer = normalize_public_url(request.headers.get("referer"))
    if referer:
        parsed = urlsplit(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    if not host:
        return None
    return f"{scheme}://{host}"


def resolve_public_api_url(
    app_url: str | None,
    api_url: str | None,
    legacy_api_url: str | None,
    *,
    request: Request | None = None,
) -> str:
    """Resolve the externally reachable API base URL."""
    normalized_api = normalize_public_url(api_url) or normalize_public_url(
        legacy_api_url
    )
    if normalized_api:
        return normalized_api

    normalized_app = normalize_public_url(app_url)
    if normalized_app:
        return append_api_suffix(normalized_app)

    request_origin = _request_origin(request)
    if request_origin:
        root_path = request.scope.get("root_path", "").rstrip("/")
        if root_path:
            return request_origin + root_path
        return request_origin

    # Last resort: derive from request URL itself (avoids leaking Docker-internal hostnames)
    if request is not None:
        scheme = request.url.scheme
        host = request.url.netloc
        if host:
            hostname = host.split(":")[0] if ":" in host else host
            # Filter out Docker-internal service names (e.g., api:8000, backend:8000)
            if hostname not in ("api", "backend"):
                return f"{scheme}://{host}"

    return _DEFAULT_PUBLIC_API_URL


def resolve_public_app_url(
    app_url: str | None,
    api_url: str | None,
    legacy_api_url: str | None,
    *,
    request: Request | None = None,
) -> str:
    """Resolve the externally reachable app URL."""
    normalized_app = normalize_public_url(app_url)
    if normalized_app:
        return normalized_app

    normalized_api = normalize_public_url(api_url) or normalize_public_url(
        legacy_api_url
    )
    if normalized_api:
        stripped = strip_api_suffix(normalized_api)
        if stripped != normalized_api:
            return stripped

    request_origin = _request_origin(request)
    if request_origin:
        return request_origin

    if normalized_api:
        return normalized_api

    # Last resort: derive from request URL itself (avoids leaking Docker-internal hostnames)
    if request is not None:
        scheme = request.url.scheme
        host = request.url.netloc
        if host:
            hostname = host.split(":")[0] if ":" in host else host
            if hostname not in ("api", "backend"):
                return f"{scheme}://{host}"

    return _DEFAULT_PUBLIC_APP_URL


def get_env_public_api_url(request: Request | None = None) -> str:
    """Resolve the API URL from environment settings only."""
    return resolve_public_api_url(
        settings.public_app_url,
        settings.public_api_url,
        settings.public_base_url,
        request=request,
    )


async def _load_public_url_overrides(db: AsyncSession) -> dict[str, str | None]:
    result = await db.execute(
        select(AppSetting.key, AppSetting.value).where(
            AppSetting.key.in_(
                (
                    PUBLIC_APP_URL_KEY,
                    PUBLIC_API_URL_KEY,
                    LEGACY_PUBLIC_API_URL_KEY,
                )
            )
        )
    )
    overrides: dict[str, str | None] = {}
    for key, value in result.all():
        if isinstance(value, dict) and "v" in value:
            overrides[key] = value["v"]
        else:
            overrides[key] = value
    return overrides


async def get_public_urls(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> tuple[str, str]:
    """Resolve both app and API URLs with DB overrides and env fallbacks."""
    overrides = {} if _is_env_only() else await _load_public_url_overrides(db)

    app_url = resolve_public_app_url(
        overrides.get(PUBLIC_APP_URL_KEY, settings.public_app_url),
        overrides.get(PUBLIC_API_URL_KEY, settings.public_api_url),
        overrides.get(LEGACY_PUBLIC_API_URL_KEY, settings.public_base_url),
        request=request,
    )
    api_url = resolve_public_api_url(
        overrides.get(PUBLIC_APP_URL_KEY, settings.public_app_url),
        overrides.get(PUBLIC_API_URL_KEY, settings.public_api_url),
        overrides.get(LEGACY_PUBLIC_API_URL_KEY, settings.public_base_url),
        request=request,
    )
    return app_url, api_url


async def get_public_app_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> str:
    app_url, _ = await get_public_urls(db, request=request)
    return app_url


async def get_dataset_service_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> str:
    """Return the public app URL for constructing dataset tile/service connect URLs.

    Thin wrapper over get_public_app_url that gives dataset-specific call sites
    a purpose-named function, per the API audit recommendation (L4).
    """
    return await get_public_app_url(db, request=request)


async def get_public_api_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> str:
    _, api_url = await get_public_urls(db, request=request)
    return api_url
