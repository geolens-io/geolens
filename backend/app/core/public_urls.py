"""Helpers for resolving public app/API URLs across deployment environments."""

from __future__ import annotations

import time
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.models import AppSetting
from app.core.tenancy import is_multi_tenant

PUBLIC_APP_URL_KEY = "public_app_url"
PUBLIC_API_URL_KEY = "public_api_url"
LEGACY_PUBLIC_API_URL_KEY = "public_base_url"

_DEFAULT_PUBLIC_APP_URL = "http://localhost:8080"
_DEFAULT_PUBLIC_API_URL = "http://localhost:8000"


class PublicUrlNotConfiguredError(RuntimeError):
    """Phase 268 H-27: raised when a caller asks for an external-use URL
    (e.g. OAuth redirect_uri) but neither PUBLIC_APP_URL nor PUBLIC_API_URL
    is configured. The request-origin fallback is unsafe for redirect_uri
    because the IdP receives whatever the attacker sets in
    ``X-Forwarded-Host`` / ``Origin`` / ``Referer``, enabling an
    auth-code-stealing attack against IdPs with permissive redirect-URI
    policies. Forcing explicit configuration closes that path."""


def normalize_public_url(url: str | None) -> str | None:
    if url is None:
        return None
    stripped = url.strip()
    if not stripped:
        return None
    return stripped.rstrip("/")


def append_api_suffix(app_url: str) -> str:
    parts = urlsplit(app_url)
    path = parts.path.rstrip("/")
    api_path = f"{path}/api" if path else "/api"
    return urlunsplit((parts.scheme, parts.netloc, api_path, "", ""))


def strip_api_suffix(api_url: str) -> str:
    parts = urlsplit(api_url)
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _configured_api_path() -> str:
    """Return the deployment-wide API path without reusing its fleet origin."""
    configured_api = normalize_public_url(
        settings.public_api_url
    ) or normalize_public_url(settings.public_base_url)
    if configured_api:
        return urlsplit(configured_api).path.rstrip("/")

    configured_app = normalize_public_url(settings.public_app_url)
    if configured_app:
        return urlsplit(append_api_suffix(configured_app)).path.rstrip("/")
    return ""


def join_public_url(base_url: str, path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    normalized = normalize_public_url(base_url)
    if normalized is None:
        raise ValueError(
            f"Cannot join public URL: base_url={base_url!r} is not a valid URL"
        )
    return normalized + path


def _is_env_only() -> bool:
    return settings.env_only_config


def _request_origin(request: Request | None) -> str | None:
    """Derive the public origin from request headers.

    SEC-05 / M-67: when ``CORS_ALLOWED_ORIGINS`` is configured (non-empty),
    the resulting origin MUST be in that allowlist. This prevents an
    attacker who controls ``X-Forwarded-Host`` (e.g., behind a permissive
    reverse proxy) from steering URL generation to attacker.com.

    When ``CORS_ALLOWED_ORIGINS`` is empty (local dev, no proxy), the
    function returns the request-derived origin unchanged — dev workflows
    (Vite proxy, localhost-only) keep working without configuration.
    """
    if request is None:
        return None

    candidate: str | None = None

    origin = normalize_public_url(request.headers.get("origin"))
    if origin:
        candidate = origin
    else:
        referer = normalize_public_url(request.headers.get("referer"))
        if referer:
            parsed = urlsplit(referer)
            if parsed.scheme and parsed.netloc:
                candidate = f"{parsed.scheme}://{parsed.netloc}"

    if candidate is None:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        if not host:
            return None
        candidate = f"{scheme}://{host}"

    # SEC-05: enforce CORS allowlist when configured.
    allowlist = settings.cors_origins_list
    if allowlist:
        # normalize_public_url strips trailing slash; do the same on the
        # allowlist entries for case-insensitive byte-equality.
        normalized_allowlist = {
            (normalize_public_url(entry) or "").lower() for entry in allowlist
        }
        if (candidate or "").lower() not in normalized_allowlist:
            return None

    return candidate


def resolve_public_api_url(
    app_url: str | None,
    api_url: str | None,
    legacy_api_url: str | None,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    """Resolve the public API URL.

    Phase 268 H-27: when ``for_external_use=True``, the request-origin
    fallback is disabled. Such a URL is handed to a third party (e.g. an
    IdP as the OAuth redirect_uri) where an attacker-controlled origin
    enables auth-code theft. Caller MUST configure ``PUBLIC_APP_URL`` /
    ``PUBLIC_API_URL`` for OAuth flows; otherwise this raises
    ``PublicUrlNotConfiguredError``.
    """
    normalized_api = normalize_public_url(api_url) or normalize_public_url(
        legacy_api_url
    )
    if normalized_api:
        return normalized_api

    normalized_app = normalize_public_url(app_url)
    if normalized_app:
        return append_api_suffix(normalized_app)

    if for_external_use:
        raise PublicUrlNotConfiguredError(
            "OAuth and other external-use flows require an explicit "
            "PUBLIC_APP_URL or PUBLIC_API_URL setting. Falling back to "
            "request-derived origin is unsafe — an attacker who controls "
            "X-Forwarded-Host can hijack the OAuth redirect_uri."
        )

    request_origin = _request_origin(request)
    if request_origin:
        assert request is not None
        root_path = request.scope.get("root_path", "").rstrip("/")
        if root_path:
            return request_origin + root_path
        return request_origin

    if request is not None:
        scheme = request.url.scheme
        host = request.url.netloc
        if host:
            hostname = host.split(":")[0] if ":" in host else host
            if hostname not in ("api", "backend"):
                return f"{scheme}://{host}"

    return _DEFAULT_PUBLIC_API_URL


def resolve_public_app_url(
    app_url: str | None,
    api_url: str | None,
    legacy_api_url: str | None,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    """Resolve the public app URL. See :func:`resolve_public_api_url` for
    the H-27 ``for_external_use`` semantics — same rules apply."""
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

    if for_external_use:
        raise PublicUrlNotConfiguredError(
            "OAuth and other external-use flows require an explicit "
            "PUBLIC_APP_URL or PUBLIC_API_URL setting. Falling back to "
            "request-derived origin is unsafe — an attacker who controls "
            "X-Forwarded-Host can hijack the OAuth redirect_uri."
        )

    request_origin = _request_origin(request)
    if request_origin:
        return request_origin

    if normalized_api:
        return normalized_api

    if request is not None:
        scheme = request.url.scheme
        host = request.url.netloc
        if host:
            hostname = host.split(":")[0] if ":" in host else host
            if hostname not in ("api", "backend"):
                return f"{scheme}://{host}"

    return _DEFAULT_PUBLIC_APP_URL


def get_env_public_api_url(request: Request | None = None) -> str:
    return resolve_public_api_url(
        settings.public_app_url,
        settings.public_api_url,
        settings.public_base_url,
        request=request,
    )


_PUBLIC_URL_CACHE: tuple[float, dict[str, str | None]] | None = None
_PUBLIC_URL_CACHE_TTL = 60  # seconds

# BUG-025: the three keys whose AppSetting rows feed _PUBLIC_URL_CACHE. A write
# to any of them must invalidate the cache (see invalidate_public_url_cache).
PUBLIC_URL_KEYS = frozenset(
    {PUBLIC_APP_URL_KEY, PUBLIC_API_URL_KEY, LEGACY_PUBLIC_API_URL_KEY}
)


def invalidate_public_url_cache() -> None:
    """Clear the public-URL override cache.

    BUG-025: ``_PUBLIC_URL_CACHE`` is a 60s module-global memoization of the
    public_app_url / public_api_url / public_base_url AppSetting rows. The
    ``config:`` cache invalidated by ``PersistentConfig.set``/``reset`` is a
    SEPARATE layer; without clearing this one too, a settings write keeps
    returning the OLD public URL (in the PUT response, /settings/tile-config,
    OGC self-links, share links) for up to ``_PUBLIC_URL_CACHE_TTL`` per
    process. PersistentConfig.set/reset call this when one of
    ``PUBLIC_URL_KEYS`` is written.
    """
    global _PUBLIC_URL_CACHE
    _PUBLIC_URL_CACHE = None


async def _load_public_url_overrides(db: AsyncSession) -> dict[str, str | None]:
    global _PUBLIC_URL_CACHE
    now = time.monotonic()
    if _PUBLIC_URL_CACHE is not None:
        ts, cached = _PUBLIC_URL_CACHE
        if now - ts < _PUBLIC_URL_CACHE_TTL:
            return cached

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
    _PUBLIC_URL_CACHE = (now, overrides)
    return overrides


async def get_public_urls(
    db: AsyncSession,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> tuple[str, str]:
    """Resolve (app_url, api_url) tuple. See :func:`resolve_public_api_url`
    for H-27 ``for_external_use`` semantics."""
    if is_multi_tenant() and request is not None:
        tenant_id = getattr(request.state, "tenant_id", None)
        tenant_origin = normalize_public_url(
            getattr(request.state, "tenant_public_origin", None)
        )
        if tenant_id is not None:
            if tenant_origin is None:
                raise PublicUrlNotConfiguredError(
                    "Hosted tenant URLs require a middleware-validated tenant host; "
                    "the fleet-wide PUBLIC_APP_URL / PUBLIC_API_URL cannot represent "
                    "a tenant-specific callback or resource link."
                )
            root_path = str(request.scope.get("root_path", "")).rstrip("/")
            api_path = root_path or _configured_api_path()
            if api_path and (
                not api_path.startswith("/") or "\\" in api_path or "//" in api_path
            ):
                raise PublicUrlNotConfiguredError(
                    "The configured public API path is not a safe absolute path"
                )
            api_url = f"{tenant_origin}{api_path}" if api_path else tenant_origin
            return tenant_origin, api_url
        if for_external_use:
            raise PublicUrlNotConfiguredError(
                "Hosted external-use URLs require a resolved tenant host."
            )

    overrides = {} if _is_env_only() else await _load_public_url_overrides(db)

    app_url = resolve_public_app_url(
        overrides.get(PUBLIC_APP_URL_KEY, settings.public_app_url),
        overrides.get(PUBLIC_API_URL_KEY, settings.public_api_url),
        overrides.get(LEGACY_PUBLIC_API_URL_KEY, settings.public_base_url),
        request=request,
        for_external_use=for_external_use,
    )
    api_url = resolve_public_api_url(
        overrides.get(PUBLIC_APP_URL_KEY, settings.public_app_url),
        overrides.get(PUBLIC_API_URL_KEY, settings.public_api_url),
        overrides.get(LEGACY_PUBLIC_API_URL_KEY, settings.public_base_url),
        request=request,
        for_external_use=for_external_use,
    )
    return app_url, api_url


async def get_public_app_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    app_url, _ = await get_public_urls(
        db, request=request, for_external_use=for_external_use
    )
    return app_url


async def get_dataset_service_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> str:
    # Alias kept for future divergence (e.g. dedicated dataset service URL).
    return await get_public_app_url(db, request=request)


async def get_public_api_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    _, api_url = await get_public_urls(
        db, request=request, for_external_use=for_external_use
    )
    return api_url
