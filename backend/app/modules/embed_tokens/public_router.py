"""Public embed-shell framing-policy endpoint.

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
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import build_embed_frame_ancestors
from app.platform.service_endpoints import MAX_QUERY_FIELDS

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


def embed_token_from_query(query: str) -> str | None:
    """Return the ``et`` value the viewer page reads from a raw query string.

    ``parse_qsl`` decodes names and splits on ``&`` only, as the browser's
    ``URLSearchParams`` does. Returns ``""`` when there is no ``et``, and
    ``None`` when the query names ``et`` more than once or in another case,
    or has more than ``MAX_QUERY_FIELDS`` fields: the page takes the first
    ``et``, so any second reading must not decide the framing policy.
    """
    try:
        qs = parse_qsl(query, keep_blank_values=True, max_num_fields=MAX_QUERY_FIELDS)
    except ValueError:
        return None
    values = [(name, value) for name, value in qs if name.lower() == "et"]
    if len(values) > 1 or any(name != "et" for name, _ in values):
        return None
    return values[0][1] if values else ""


@router.get("/frame-policy", include_in_schema=False)
async def embed_frame_policy(
    request: Request,
    response: Response,
    token: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Return the per-token frame-ancestors framing policy for the embed shell.

    Always 200; the framing decision is carried in the
    ``Content-Security-Policy`` and ``X-Embed-Frame-Ancestors`` headers.
    The edge sends the shell's raw query in ``X-Embed-Query``; when present it
    decides the token, and ``token`` is read only from an edge that predates it.
    """
    embed_token: str | None = token
    shell_query = request.headers.get("x-embed-query")
    if shell_query is not None:
        embed_token = embed_token_from_query(shell_query)
    if embed_token is None:
        frame_ancestors = build_embed_frame_ancestors(
            is_valid=False, allowed_origins=None
        )
    elif not embed_token:
        # No embed token: a plain share view or a public embed without domain
        # locking, so framing stays open. Fail-closed 'none' is reserved for a
        # token that is present but invalid/revoked/expired. Private data stays
        # protected at the tile layer (X-Embed-Token validation).
        frame_ancestors = ""
    else:
        token_hash = hashlib.sha256(embed_token.encode()).hexdigest()
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
    # The answer depends on X-Embed-Query, which a URL-keyed cache would miss.
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 200
    return response
