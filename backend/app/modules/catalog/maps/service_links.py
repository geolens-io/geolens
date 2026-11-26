"""Revoking a map's share and embed links when a write narrows it.

An embed token's revocation writes a cache denial that a rollback leaves in
place, so a write revokes only once nothing can refuse it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.authorization import (
    ANONYMOUS_MAP_VISIBILITIES,
    RESTRICTED_MAP_VISIBILITY,
)
from app.modules.catalog.maps.service_public import revoke_share_token_by_map
from app.modules.embed_tokens.service import (
    revoke_embed_tokens_by_map,
    revoke_embed_tokens_for_dropped_datasets,
)

# Maps whose revocations a ``links_retired_last`` block holds: True for all
# links, False for embed tokens scoped to a dropped dataset.
_HELD_REVOCATIONS = "map_link_revocations_held"


async def retire_map_links(
    session: AsyncSession, map_id: uuid.UUID, current: str, new: str
) -> None:
    """Revoke the map's share and embed tokens when moving from ``current`` to
    ``new`` leaves public or enters restricted. Call it after every check that
    can refuse the write; inside ``links_retired_last`` the revocation waits
    for the end of the block."""
    leaves_public = (
        current in ANONYMOUS_MAP_VISIBILITIES and new not in ANONYMOUS_MAP_VISIBILITIES
    )
    enters_restricted = (
        new == RESTRICTED_MAP_VISIBILITY and current != RESTRICTED_MAP_VISIBILITY
    )
    if not (leaves_public or enters_restricted):
        return
    held = session.info.get(_HELD_REVOCATIONS)
    if held is not None:
        held[map_id] = True
        return
    await _revoke_links(session, map_id)


async def retire_dropped_embed_tokens(session: AsyncSession, map_id: uuid.UUID) -> None:
    """``revoke_embed_tokens_for_dropped_datasets``, held to the end of a
    ``links_retired_last`` block as ``retire_map_links`` is."""
    held = session.info.get(_HELD_REVOCATIONS)
    if held is not None:
        held.setdefault(map_id, False)
        return
    await revoke_embed_tokens_for_dropped_datasets(session, map_id)


@asynccontextmanager
async def links_retired_last(session: AsyncSession) -> AsyncIterator[None]:
    """Hold the link revocations asked for inside the block and make them,
    in the same transaction, when the block ends without raising.

    For a write that can still be refused after it narrows a map or drops a
    layer: run every refusing step inside the block, and commit after it."""
    if _HELD_REVOCATIONS in session.info:
        yield
        return
    held: dict[uuid.UUID, bool] = {}
    session.info[_HELD_REVOCATIONS] = held
    try:
        yield
    finally:
        del session.info[_HELD_REVOCATIONS]
    for map_id in sorted(held):
        if held[map_id]:
            await _revoke_links(session, map_id)
        else:
            await revoke_embed_tokens_for_dropped_datasets(session, map_id)


async def _revoke_links(session: AsyncSession, map_id: uuid.UUID) -> None:
    await revoke_share_token_by_map(session, map_id)
    await revoke_embed_tokens_by_map(session, map_id)
