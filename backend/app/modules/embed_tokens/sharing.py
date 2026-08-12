"""Stable embed-token-owned query contracts for cross-domain consumers.

The mirror of ``app.modules.catalog.maps.sharing``. That module exists so
embed-token code can ask map questions without importing catalog ORM models;
this one exists so map code can ask embed-token questions without importing
``EmbedToken``. Keeping both directions on scalar/DTO/query helpers is what
keeps the maps-sharing and embed-token pair free of an import cycle.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Subquery, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.embed_tokens.models import EmbedToken


async def get_active_allowed_origins(
    session: AsyncSession, map_id: uuid.UUID
) -> list[str] | None:
    """``allowed_origins`` of the map's current active embed token.

    ``None`` when the map has no active token, ``[]`` when a token exists with
    no origins recorded — the public-map path turns this into a per-token
    ``frame-ancestors`` CSP directive, so those two cases are not
    interchangeable.

    SEC-S08 (Phase 1062-05). A share token and an embed token are distinct
    primitives: a map may have either without the other.

    CR-04 (Phase 1062 review): a non-expiring token has ``expires_at IS NULL``,
    and in PostgreSQL ``NULL > now()`` evaluates to NULL (falsy). The expiry
    predicate must admit NULL explicitly, or community-edition tokens — which
    default to no expiry — silently fall out, the header falls back to
    ``frame-ancestors 'self'``, and embed framing breaks.
    """
    stmt = (
        select(EmbedToken.allowed_origins)
        .where(
            EmbedToken.map_id == map_id,
            EmbedToken.is_active == True,  # noqa: E712
            or_(
                EmbedToken.expires_at.is_(None),
                EmbedToken.expires_at > func.now(),
            ),
        )
        .order_by(EmbedToken.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def active_embed_count_subquery() -> Subquery:
    """Per-map count of ACTIVE embed tokens, as a joinable subquery.

    Columns: ``map_id`` and ``embed_count``. A subquery rather than a scalar
    helper because the caller (the admin share-token listing) needs the count
    for a whole page of maps in one statement, in both the SELECT list and the
    ORDER BY. A map with no active token has no row here, so the caller
    coalesces the outer-joined value to 0.
    """
    return (
        select(
            EmbedToken.map_id,
            func.count().label("embed_count"),
        )
        .where(EmbedToken.is_active.is_(True))
        .group_by(EmbedToken.map_id)
        .subquery()
    )
