"""Tenant-context middleware.

TSEAM-04 (Phase 1207-02): resolves a tenant signal (subdomain or JWT claim)
into a request-scoped context stored on ``request.state.tenant_id``.

**Single-tenant (default) behavior:** strict no-op. The middleware returns
immediately after a single boolean check — no state mutation, no DB lookup,
zero measurable per-request cost. This preserves the single_tenant
byte-identical guarantee (T-1207-08).

**Multi-tenant behavior:** verified resolution.
  - Reads the first subdomain label from the ``Host`` header (e.g. ``acme``
    from ``acme.geolens.app``).
  - Alternatively reads a ``tid`` claim from a signature- and expiry-verified
    GeoLens Bearer JWT if the Authorization header is present.
  - Resolves the signal to the tenant **UUID** (a subdomain slug is looked up
    against the core-owned ``catalog.tenants`` registry; a JWT claim that is
    already a UUID passes through) and stores it on
    ``request.state.tenant_id``, or ``None`` if unresolved.
  - Rejects unresolved explicit tenant hosts and host/token tenant mismatches
    before a request reaches application code. A bearer token that is not a
    verified GeoLens JWT may proceed only after the Host has resolved a tenant;
    the normal auth dependency then gives the registered identity extension a
    chance to validate it. Requests carrying neither signal stay unscoped so
    tenant RLS fails closed.

Slug→UUID resolution happens here (not in the GUC layer): the Phase 1208 RLS
GUC casts ``app.current_tenant::uuid`` and the per-tenant data-schema helpers
validate UUIDs, so ``current_tenant_var`` must carry a UUID — never a slug.
An unresolved slug yields ``None`` so RLS fail-closes the unscoped request.
"""

from __future__ import annotations

import re
import uuid
from typing import NamedTuple
from urllib.parse import urlsplit

import jwt
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant

logger = structlog.stdlib.get_logger(__name__)

# Regex for a safe subdomain label (alphanumeric + hyphens, 1-63 chars, no
# leading/trailing hyphens). This is the attacker-controlled input from the
# Host header — validate strictly (T-1207-05).
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?$")

# Reserved labels below the configured base domain are service endpoints, not
# tenant slugs.
_BASE_DOMAIN_LABELS = frozenset({"www", "api", "app", "localhost"})


class _TenantHost(NamedTuple):
    trusted: bool
    signal: str | None


def _normalize_request_host(host: str) -> str | None:
    """Return a canonical hostname from one RFC Host value, or ``None``."""
    if not host or any(char in host for char in ("/", "\\", "@", ",", "\x00")):
        return None
    try:
        parsed = urlsplit(f"//{host}", allow_fragments=False)
        # Accessing .port also validates a malformed/non-numeric port.
        _ = parsed.port
    except ValueError:
        return None
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
    ):
        return None
    hostname = parsed.hostname.lower().rstrip(".")
    return hostname or None


def _validated_tenant_origin(request: Request, host: str) -> str | None:
    """Build an origin only from the Host value this middleware classified.

    The ASGI scheme is supplied by the trusted server/proxy configuration;
    forwarded host headers are deliberately not consulted here. The caller
    invokes this only after the host slug resolves to the request tenant.
    """
    try:
        parsed = urlsplit(f"//{host}", allow_fragments=False)
        port = parsed.port
    except ValueError:
        return None
    hostname = (parsed.hostname or "").lower().rstrip(".")
    scheme = str(request.scope.get("scheme", "")).lower()
    if not hostname or scheme not in {"http", "https"}:
        return None
    netloc = f"{hostname}:{port}" if port is not None else hostname
    return f"{scheme}://{netloc}"


def _classify_tenant_host(host: str) -> _TenantHost:
    """Classify a Host against explicit service hosts and tenant base suffix.

    A foreign or malformed host is *untrusted*, not an unscoped host. This
    distinction prevents a forged Host from falling through to JWT-only tenant
    resolution or from scoping anonymous/API-key/refresh requests.
    """
    hostname = _normalize_request_host(host)
    if hostname is None:
        return _TenantHost(False, None)

    if hostname in settings.tenant_trusted_hosts_list:
        return _TenantHost(True, None)

    base_domain = settings.tenant_base_domain
    if base_domain is None:
        return _TenantHost(False, None)
    if hostname == base_domain:
        return _TenantHost(True, None)

    suffix = f".{base_domain}"
    if not hostname.endswith(suffix):
        return _TenantHost(False, None)

    label = hostname[: -len(suffix)]
    if (
        "." in label
        or label in _BASE_DOMAIN_LABELS
        or _SUBDOMAIN_RE.fullmatch(label) is None
    ):
        # Reserved service labels are trusted non-tenant endpoints. Any other
        # malformed/multi-level prefix is rejected rather than silently ignored.
        if label in _BASE_DOMAIN_LABELS:
            return _TenantHost(True, None)
        return _TenantHost(False, None)
    return _TenantHost(True, label)


def _extract_subdomain(host: str) -> str | None:
    """Return a tenant slug only from an explicitly trusted Host suffix."""
    classified = _classify_tenant_host(host)
    return classified.signal if classified.trusted else None


def _extract_jwt_tenant_claim(authorization: str) -> str | None:
    """Return the tenant UUID from a verified GeoLens access token.

    The value feeds the RLS tenant GUC, so decoding without verification is
    never safe here. Signature, expiry, and required access-token claims are
    validated before ``tid`` is accepted. User activity and token-version
    checks remain in the normal authentication dependency after RLS has been
    scoped; a token that fails this cryptographic pre-auth step leaves the
    request unscoped and therefore fails closed under tenant RLS.
    """
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat", "jti", "token_version"]},
        )
        tenant_id = uuid.UUID(str(payload["tid"]))
        uuid.UUID(str(payload["sub"]))
        token_version = payload["token_version"]
        if not isinstance(token_version, int) or isinstance(token_version, bool):
            return None
        return str(tenant_id)
    except (jwt.PyJWTError, KeyError, ValueError, AttributeError, TypeError):
        return None


async def _resolve_tenant_uuid(tenant_signal: str | None) -> str | None:
    """Resolve a tenant signal (subdomain slug or JWT claim) to a tenant UUID.

    The Phase 1208 RLS GUC is cast to ``::uuid`` and the per-tenant data-schema
    helpers validate UUIDs, so ``current_tenant_var`` must hold a UUID string,
    never a slug (Gap A — Codex review of PR #256).

    - A signal that already parses as a UUID (the cloud JWT stamps ``tid`` as
      the tenant UUID) is returned unchanged — no DB hit.
    - A subdomain slug is resolved against the core-owned ``catalog.tenants``
      registry (NOT one of the RLS-protected tenant-shared tables, so the
      lookup needs no tenant context). Returns the UUID string, or ``None``
      when the slug matches no tenant.

    Resilient by design: any DB error resolves to ``None`` (logged) rather than
    500-ing the request — enforcement is RLS, not this middleware.
    """
    if tenant_signal is None:
        return None

    # Already a UUID (e.g. cloud JWT ``tid`` claim) → use as-is, no DB hit.
    try:
        return str(uuid.UUID(tenant_signal))
    except (ValueError, AttributeError, TypeError):
        pass  # not a UUID → treat as a subdomain slug and resolve via the DB

    try:
        from sqlalchemy import text

        from app.core.db import async_session

        async with async_session() as session:
            # Bound param (T-1208-01); catalog.tenants has no RLS (registry).
            resolved = await session.scalar(
                text("SELECT id FROM catalog.tenants WHERE slug = :slug"),
                {"slug": tenant_signal},
            )
        return str(resolved) if resolved is not None else None
    except Exception:  # broad: a resolution failure must not 500 the request
        logger.warning(
            "tenant slug resolution failed; running request unscoped",
            slug=tenant_signal,
            exc_info=True,
        )
        return None


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Resolve a tenant signal into ``request.state.tenant_id``.

    In single_tenant mode (default): strict no-op — returns immediately
    after a single ``is_multi_tenant()`` check.

    In multi_tenant mode: resolves a public subdomain or a verified JWT tenant
    claim. Sets ``request.state.tenant_id`` to the resolved value or ``None``.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # TSEAM-04 fast path: single_tenant is the default and the vast
        # majority of deployments. One boolean check, zero state mutation.
        if not is_multi_tenant():
            return await call_next(request)

        # Resolve host and verified bearer signals independently. A host may
        # scope anonymous/API-key/refresh requests, while an access token is
        # accepted only when its signed tenant binding agrees with that host.
        raw_host_values = [
            value.decode("latin-1")
            for name, value in request.scope.get("headers", [])
            if name.lower() == b"host"
        ]
        if len(raw_host_values) != 1:
            return JSONResponse(
                {"detail": "Exactly one trusted Host header is required"},
                status_code=400,
            )
        classified_host = _classify_tenant_host(raw_host_values[0])
        if not classified_host.trusted:
            logger.warning("Rejected untrusted tenant Host")
            return JSONResponse(
                {"detail": "Host is not trusted for tenant routing"},
                status_code=400,
            )
        host_signal = classified_host.signal

        auth_header = request.headers.get("authorization", "")
        bearer_present = auth_header.lower().startswith("bearer ")
        jwt_signal = _extract_jwt_tenant_claim(auth_header) if bearer_present else None

        host_tenant_id = (
            await _resolve_tenant_uuid(host_signal) if host_signal is not None else None
        )
        if host_signal is not None and host_tenant_id is None:
            return JSONResponse(
                {"detail": "Tenant host could not be resolved"},
                status_code=403,
            )
        # Alternate identity backends validate their opaque/externally signed
        # bearer tokens in the normal auth dependency, after the Host-derived
        # tenant context has scoped the DB session. Without a resolved tenant
        # Host, only a locally verified JWT may establish the tenant boundary.
        if bearer_present and jwt_signal is None and host_tenant_id is None:
            return JSONResponse(
                {"detail": "Bearer token is invalid or not tenant-bound"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        jwt_tenant_id = (
            await _resolve_tenant_uuid(jwt_signal) if jwt_signal is not None else None
        )
        if (
            host_tenant_id is not None
            and jwt_tenant_id is not None
            and host_tenant_id != jwt_tenant_id
        ):
            logger.warning(
                "Tenant host and bearer token disagree",
                host_tenant_id=host_tenant_id,
                token_tenant_id=jwt_tenant_id,
            )
            return JSONResponse(
                {"detail": "Tenant host does not match bearer token"},
                status_code=403,
            )

        tenant_id = host_tenant_id or jwt_tenant_id

        request.state.tenant_id = tenant_id
        request.state.tenant_public_origin = (
            _validated_tenant_origin(request, raw_host_values[0])
            if host_tenant_id is not None
            else None
        )
        if host_tenant_id is not None and request.state.tenant_public_origin is None:
            return JSONResponse(
                {"detail": "Tenant host could not form a trusted public origin"},
                status_code=400,
            )

        if tenant_id is not None:
            logger.debug("Tenant context resolved", tenant_id=tenant_id)

        # ISO-01 (Phase 1208-01): bridge request.state.tenant_id → current_tenant_var
        # so the after_begin hook on the engine can read the tenant id when the
        # request handler opens a DB session (get_db or raw async_session).
        # Use a token for reset so the var never bleeds across requests (T-1208-03).
        token = current_tenant_var.set(tenant_id)
        try:
            return await call_next(request)
        finally:
            current_tenant_var.reset(token)
