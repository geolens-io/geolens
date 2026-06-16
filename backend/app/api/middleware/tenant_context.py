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
  - Sets ``request.state.tenant_id`` to the resolved slug/claim string, or
    ``None`` if neither signal is present.
  - Does NOT raise or return an HTTP error (enforcement is Phase 1208 RLS).

Mapping a subdomain slug to a tenant UUID via the database is deferred to
Phase 1208's session GUC layer when the cloud overlay is present.
"""

from __future__ import annotations

import base64
import json
import re

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
        tenant_id: str | None = None

        # 1. Try subdomain from Host header (highest priority, cheapest).
        host = request.headers.get("host", "")
        if host:
            tenant_id = _extract_subdomain(host)

        # 2. Fall back to JWT claim if no subdomain signal.
        if tenant_id is None:
            auth_header = request.headers.get("authorization", "")
            if auth_header:
                tenant_id = _extract_jwt_tenant_claim(auth_header)

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
