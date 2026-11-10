"""Story blocks that frame another site, checked against the hosts an admin approved."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.stories.assets import chapters_of
from app.modules.catalog.widgets.schemas import block_frame_host, read_stored
from app.platform.story_frames import approved_frame_hosts

FRAME_HOST_NOT_ALLOWED = "story_frame_host_not_allowed"


def document_blocks(document: Any) -> list[list[Any]]:
    """Each chapter's readable blocks in a stored story document."""
    return [
        read_stored(chapter.get("blocks"), "story").widgets
        for chapter in chapters_of(document)
    ]


async def refuse_unapproved_frames(
    db: AsyncSession, chapters: Iterable[Sequence[Any]]
) -> None:
    """422 ``story_frame_host_not_allowed`` naming each embed or video block
    whose host is not approved now, by chapter number, block id and host."""
    framed = [
        (number, block, host)
        for number, blocks in enumerate(chapters, start=1)
        for block in blocks
        if (host := block_frame_host(block)) is not None
    ]
    if not framed:
        return
    approved = {entry.host for entry in await approved_frame_hosts(db)}
    failing = [
        {"chapter": number, "block_id": str(block.id), "type": block.type, "host": host}
        for number, block, host in framed
        if host not in approved
    ]
    if failing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": FRAME_HOST_NOT_ALLOWED,
                "message": "Some embed or video blocks frame a site an admin "
                "hasn't approved for stories.",
                "blocks": failing,
            },
        )
