"""The share link a version 2 publish gives a map it leaves public."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.processing_port import share_links_withheld
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.catalog.maps.service import create_share_token, get_active_share_token
from app.platform.request_credential import api_key_audit_details


class ShareMint(NamedTuple):
    """What a publish did about a public map's share link."""

    # The raw token of a link this publish minted.
    token: str | None
    # True when the map needed a new link and the publish withheld it.
    withheld: bool = False


async def _has_live_link(session: AsyncSession, map_id: uuid.UUID) -> bool:
    token_obj = await get_active_share_token(session, map_id)
    return token_obj is not None and (
        token_obj.expires_at is None
        or token_obj.expires_at >= datetime.now(timezone.utc)
    )


async def mint_share_link(
    session: AsyncSession,
    map_id: uuid.UUID,
    user: Identity,
    ip_address: str | None,
) -> ShareMint:
    """Give a public map a share link through the share service.

    The token is set only when this call minted the link, a new one or a
    revoked or expired one replaced. A live link is reused and gives none:
    links are stored hashed, so only the call that mints one can hand it
    out. No expiry is passed, so a live link keeps its own. Under
    ``withholding_share_links`` nothing is minted, and a map with no live
    link answers ``withheld``. Raises ``ValueError`` when the map isn't
    public. Does not commit.
    """
    if share_links_withheld(session):
        return ShareMint(None, withheld=not await _has_live_link(session, map_id))
    token_obj = await create_share_token(session, map_id, user.id)
    raw_token = getattr(token_obj, "_raw_token", None)
    if raw_token is None:
        return ShareMint(None)
    # The service leaves the raw token on the instance, which the session's
    # identity map can hand back to a later call in the same session.
    del token_obj._raw_token
    await audit_emit(
        session,
        AuditEvent(
            user_id=user.id,
            action="map.share",
            resource_type="map",
            resource_id=map_id,
            details={
                "token_hint": token_obj.token_hint,
                **api_key_audit_details(session),
            },
            ip_address=ip_address,
        ),
    )
    return ShareMint(raw_token)
