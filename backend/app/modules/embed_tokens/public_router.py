"""Public embed-shell framing-policy endpoint (builder-audit P0-02).

The ``/m/{token}`` embed HTML shell is served statically by the edge (nginx),
so its per-token ``Content-Security-Policy: frame-ancestors`` directive cannot
be set by the React SPA — it must be injected at the document response. This
endpoint validates the token and returns the frame-ancestors directive both as:

  * a full ``Content-Security-Policy`` response header (directly testable, and
    correct when the API is hit without the edge in front), and
  * an ``X-Embed-Frame-Ancestors`` header that the nginx ``auth_request`` wiring
    copies onto the static HTML response via ``auth_request_set``.

The endpoint ALWAYS returns 200 (even for an invalid/revoked/expired token) so
the ``auth_request`` subrequest allows the shell to load; an invalid token gets
a fail-closed ``frame-ancestors 'none'`` so the shell cannot be framed anywhere.
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

# Base CSP for the embed shell — mirrors the static-shell CSP the edge serves
# for /m/* (see frontend/nginx.conf). The per-token frame-ancestors directive is
# appended below; X-Frame-Options is intentionally NOT set so it is omitted for
# the embed route only (SecurityHeadersMiddleware skips XFO when CSP is present).
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

    builder-audit P0-02. Always 200; the framing decision is carried in the
    ``Content-Security-Policy`` and ``X-Embed-Frame-Ancestors`` headers.
    """
    tok: EmbedToken | None = None
    if token:
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
