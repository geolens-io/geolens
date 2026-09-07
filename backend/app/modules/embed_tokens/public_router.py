"""Public embed-shell framing-policy endpoint (builder-audit #338 P0-02).

The ``/m/{token}`` shell is served statically by nginx, so its per-token
frame-ancestors CSP can't be set by the SPA -- it's injected via an
``auth_request`` subrequest to this endpoint, which returns both a full
``Content-Security-Policy`` header and an ``X-Embed-Frame-Ancestors``
header nginx copies onto the static response.

Always returns 200 (even for invalid/revoked/expired tokens) so
auth_request lets the shell load; an invalid token gets a fail-closed
``frame-ancestors 'none'`` instead.
"""

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import build_embed_frame_ancestors

router = APIRouter(prefix="/embed", tags=["Embed Tokens"])

# Base CSP for the embed shell -- mirrors the static-shell CSP nginx serves
# for /m/* (frontend/nginx.conf). X-Frame-Options is intentionally omitted
# here; SecurityHeadersMiddleware skips XFO when CSP is present.
_BASE_EMBED_CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
    "font-src 'self' data:; connect-src 'self' https: wss:; "
    "worker-src 'self' blob:; child-src 'self' blob:; object-src 'none'; "
    "base-uri 'self'"
)


@router.get("/frame-policy", include_in_schema=False)
async def embed_frame_policy(
    response: Response,
    token: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return the per-token frame-ancestors framing policy for the embed shell.

    builder-audit #338 P0-02. Always 200; the framing decision is carried in the
    ``Content-Security-Policy`` and ``X-Embed-Frame-Ancestors`` headers.
    """
    if not token:
        # Codex P1 (#338): no embed token present -- a plain share view or
        # public embed without domain locking. Framing stays open (matches
        # pre-P0-02 behavior); fail-closed 'none' is reserved for a token
        # that IS present but invalid/revoked/expired. Private data stays
        # protected at the tile layer (X-Embed-Token validation).
        frame_ancestors = ""
    else:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(EmbedToken).where(
                EmbedToken.token_hash == token_hash,
                EmbedToken.is_active.is_(True),
                EmbedToken.expires_at > now,
            )
        )
        tok = result.scalar_one_or_none()
        frame_ancestors = build_embed_frame_ancestors(
            is_valid=tok is not None,
            allowed_origins=tok.allowed_origins if tok is not None else None,
        )

    csp = (
        f"{_BASE_EMBED_CSP}; {frame_ancestors}" if frame_ancestors else _BASE_EMBED_CSP
    )
    response.headers["Content-Security-Policy"] = csp
    # Just the directive (possibly empty) for the nginx auth_request_set copy.
    response.headers["X-Embed-Frame-Ancestors"] = frame_ancestors
    response.status_code = 200
    return response
