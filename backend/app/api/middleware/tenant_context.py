"""Tenant-context middleware.

TSEAM-04 (Phase 1207-02): resolves a tenant signal (subdomain or JWT claim)
into a request-scoped context stored on ``request.state.tenant_id``.

**Single-tenant (default) behavior:** strict no-op. The middleware returns
immediately after a single boolean check — no state mutation, no DB lookup,
zero measurable per-request cost. This preserves the single_tenant
byte-identical guarantee (T-1207-08).

**Multi-tenant behavior (Phase 1207 surface only):** resolution-only.
  - Reads the first subdomain label from the ``Host`` header (e.g. ``acme``
    from ``acme.geolens.app``).
  - Alternatively reads a ``tenant_id`` or ``tid`` claim from a Bearer JWT
    if the Authorization header is present (no re-auth / no DB lookup — the
    token is decoded with ``verify_signature=False`` to read the claim only).
  - Resolves the signal to the tenant **UUID** (a subdomain slug is looked up
    against the core-owned ``catalog.tenants`` registry; a JWT claim that is
    already a UUID passes through) and stores it on
    ``request.state.tenant_id``, or ``None`` if unresolved.
  - Does NOT raise or return an HTTP error (enforcement is Phase 1208 RLS).

Slug→UUID resolution happens here (not in the GUC layer): the Phase 1208 RLS
GUC casts ``app.current_tenant::uuid`` and the per-tenant data-schema helpers
validate UUIDs, so ``current_tenant_var`` must carry a UUID — never a slug.
An unresolved slug yields ``None`` so RLS fail-closes the unscoped request.
"""

from __future__ import annotations

import base64
import json
import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant

logger = structlog.stdlib.get_logger(__name__)

# Regex for a safe subdomain label (alphanumeric + hyphens, 1-63 chars, no
# leading/trailing hyphens). This is the attacker-controlled input from the
# Host header — validate strictly (T-1207-05).
_SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?$")

# Known base domains where the first label is NOT a tenant slug.
# Expand as needed; the middleware treats an unrecognized Host as slug=None.
_BASE_DOMAIN_LABELS = frozenset({"www", "api", "app", "localhost"})


def _extract_subdomain(host: str) -> str | None:
    """Return the first subdomain label from a Host header value, or None.

    Only returns a label that looks like a valid slug and is not in the
    known-base-domain label set.  Port suffix is stripped first.
    """
    # Strip port if present
    hostname = host.split(":")[0].lower()
    parts = hostname.split(".")
    # Need at least three parts for a subdomain: <label>.<domain>.<tld>
    if len(parts) < 3:
        return None
    label = parts[0]
    if label in _BASE_DOMAIN_LABELS:
        return None
    if not _SUBDOMAIN_RE.match(label):
        return None
    return label


def _extract_jwt_tenant_claim(authorization: str) -> str | None:
    """Decode the JWT payload (without signature verification) and return
    the ``tenant_id`` or ``tid`` claim if present.

    This is a read-only, side-effect-free operation — no DB lookup, no
    auth enforcement (T-1207-05). If the token is malformed the claim is
    silently ignored.

    SECURITY (BA-25): in ``multi_tenant`` mode the caller uses this claim to set
    the RLS tenant GUC, so an attacker supplying an arbitrary unsigned ``tid``
    would scope RLS to that tenant. Dormant today (``single_tenant`` is the
    default and ``dispatch`` is a strict no-op there; ``multi_tenant`` needs the
    unshipped cloud overlay). BEFORE ``multi_tenant`` ships, derive the tenant
    from a signature-VERIFIED token (or re-verify tenant membership post-auth) —
    do NOT trust this unverified claim for RLS scoping.
    """
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        # JWT payload is base64url-encoded (no padding)
        payload_b64 = parts[1]
        # Add padding
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("tenant_id") or payload.get("tid") or None
    except (
        Exception
    ):  # broad: malformed JWT — base64/json errors are expected; no enforcement here
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
                text("SELECT id FROM catalog.tenants WHERE slug = :slug LIMIT 1"),
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

    In multi_tenant mode: resolves subdomain or JWT tenant claim (no
    enforcement, no DB lookup). Sets ``request.state.tenant_id`` to the
    resolved value or ``None``.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # TSEAM-04 fast path: single_tenant is the default and the vast
        # majority of deployments. One boolean check, zero state mutation.
        if not is_multi_tenant():
            return await call_next(request)

        # multi_tenant resolution path — resolution-only, no enforcement.
        tenant_signal: str | None = None

        # 1. Try subdomain from Host header (highest priority, cheapest).
        host = request.headers.get("host", "")
        if host:
            tenant_signal = _extract_subdomain(host)

        # 2. Fall back to JWT claim if no subdomain signal.
        if tenant_signal is None:
            auth_header = request.headers.get("authorization", "")
            if auth_header:
                tenant_signal = _extract_jwt_tenant_claim(auth_header)

        # Resolve the slug/claim to the tenant UUID BEFORE it reaches the RLS
        # GUC (cast ::uuid) or the data-schema helpers (UUID-validated). A raw
        # subdomain slug here would raise on the first scoped query instead of
        # scoping the request (Gap A — Codex review of PR #256).
        tenant_id = await _resolve_tenant_uuid(tenant_signal)

        request.state.tenant_id = tenant_id

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
