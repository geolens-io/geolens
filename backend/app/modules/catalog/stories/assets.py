"""Story image assets: their rows, stored objects, references and cleanup.

An asset belongs to one story. Image blocks and the story's cover name it by
id, and its object is written once under a key no other asset uses, so
deleting an object whose row is gone can't remove anything another row still
names. A block this server can't parse counts as using every id in it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.async_io import await_draining
from app.modules.catalog.maps.service import new_map_asset_key
from app.modules.catalog.stories.images import StoryImage
from app.modules.catalog.stories.models import Story, StoryAsset
from app.modules.catalog.widgets.schemas import (
    ImageWidget,
    KeptWidget,
    read_stored,
    to_store,
)
from app.platform.storage.publication import AssetPublication
from app.platform.storage.reap import MAX_DELETES_IN_FLIGHT, delete_objects_best_effort
from app.platform.storage.titiler_url import resolve_current_storage_key

logger = structlog.stdlib.get_logger(__name__)

MAX_STORY_ASSETS = 200
MAX_STORY_ASSET_BYTES = 250 * 1024 * 1024
# How long an image stays after nothing uses it: an upload until the save
# that places it, and a removed image long enough to undo the removal.
UNREFERENCED_GRACE = timedelta(days=7)
_KEY_PREFIX = "stories/assets"


def new_story_asset_key(story_id: uuid.UUID) -> str:
    return new_map_asset_key(_KEY_PREFIX, story_id, "webp")


def chapters_of(document: Any) -> list[dict[str, Any]]:
    chapters = document.get("chapters") if isinstance(document, dict) else None
    return [c for c in chapters or () if isinstance(c, dict)]


# Compact, canonical, braced and URN spellings.
_UUID_LENGTHS = frozenset({32, 36, 38, 45})


def _as_uuid(value: Any) -> uuid.UUID | None:
    if not isinstance(value, str) or len(value) not in _UUID_LENGTHS:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _uuid_values(node: Any, found: set[uuid.UUID]) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _uuid_values(value, found)
    elif isinstance(node, list):
        for value in node:
            _uuid_values(value, found)
    elif (parsed := _as_uuid(node)) is not None:
        found.add(parsed)


def mentioned_ids(*nodes: Any) -> set[uuid.UUID]:
    """Every string value in ``nodes`` that parses as a UUID, in any spelling."""
    found: set[uuid.UUID] = set()
    for node in nodes:
        _uuid_values(node, found)
    return found


def image_ids(*documents: Any) -> set[uuid.UUID]:
    """The images ``documents`` show: each image block's, and every id in a
    block this server can't parse."""
    found: set[uuid.UUID] = set()
    for document in documents:
        for chapter in chapters_of(document):
            stored = read_stored(chapter.get("blocks"), "story")
            found |= {b.asset_id for b in stored.widgets if isinstance(b, ImageWidget)}
            found |= mentioned_ids(*(kept.raw for kept in stored.unreadable))
    return found


async def get_story_asset(
    db: AsyncSession, story_id: uuid.UUID, asset_id: uuid.UUID
) -> tuple[Story, StoryAsset] | None:
    """The story, without its documents, and its asset; unguarded: callers
    check the story."""
    row = (
        await db.execute(
            select(Story, StoryAsset)
            .join(StoryAsset, StoryAsset.story_id == Story.id)
            .where(Story.id == story_id, StoryAsset.id == asset_id)
            .options(defer(Story.draft), defer(Story.published))
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def require_story_assets(
    db: AsyncSession, story_id: uuid.UUID, asset_ids: Iterable[uuid.UUID]
) -> None:
    """422 ``story_assets_not_found`` unless every id is an image of this story."""
    wanted = set(asset_ids)
    if not wanted:
        return
    found = set(
        await db.scalars(
            select(StoryAsset.id).where(
                StoryAsset.story_id == story_id, StoryAsset.id.in_(wanted)
            )
        )
    )
    if missing := sorted(wanted - found):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "story_assets_not_found",
                "message": "Some images weren't found in this story.",
                "asset_ids": [str(asset_id) for asset_id in missing],
            },
        )


# Images of each published document, by story and publish time: every
# publish, by any server version, sets a new published_at.
_PUBLISHED_IMAGES: OrderedDict[tuple[uuid.UUID, datetime], frozenset[uuid.UUID]] = (
    OrderedDict()
)
_PUBLISHED_IMAGES_KEPT = 256


async def _published_image_ids(
    db: AsyncSession, story_id: uuid.UUID
) -> frozenset[uuid.UUID]:
    row = (
        await db.execute(
            select(Story.published, Story.published_at).where(Story.id == story_id)
        )
    ).one_or_none()
    if row is None or row.published_at is None:
        return frozenset()
    key = (story_id, row.published_at)
    images = _PUBLISHED_IMAGES.get(key)
    if images is None:
        images = frozenset(image_ids(row.published))
        _PUBLISHED_IMAGES[key] = images
        if len(_PUBLISHED_IMAGES) > _PUBLISHED_IMAGES_KEPT:
            _PUBLISHED_IMAGES.popitem(last=False)
    return images


async def reaches_readers(db: AsyncSession, story: Story, asset_id: uuid.UUID) -> bool:
    """Whether readers of the published story get this asset: its cover, or
    an image of the published document as stored now, whichever server
    version wrote it."""
    if story.published_at is None:
        return False
    if asset_id == story.cover_asset_id:
        return True
    return asset_id in await _published_image_ids(db, story.id)


async def touch_story_assets(
    db: AsyncSession, story_id: uuid.UUID, asset_ids: Iterable[uuid.UUID | None]
) -> None:
    """Mark these assets as used now, restarting their grace period."""
    ids = {asset_id for asset_id in asset_ids if asset_id is not None}
    if ids:
        await db.execute(
            update(StoryAsset)
            .where(StoryAsset.story_id == story_id, StoryAsset.id.in_(ids))
            .values(last_used_at=func.now())
        )


async def prune_story_assets(
    db: AsyncSession,
    story: Story,
    *,
    draft_ids: set[uuid.UUID] | None = None,
    released: Iterable[uuid.UUID] = (),
) -> list[str]:
    """Delete the rows of assets nothing has used for the grace period.

    In use: the draft's images (``draft_ids`` when the caller has them), the
    cover and the published document's images. ``released`` are images this
    change stopped using, which start their grace period now. Returns the
    deleted rows' storage keys for after the commit. Call holding
    ``lock_story``.
    """
    used = image_ids(story.draft) if draft_ids is None else set(draft_ids)
    if story.cover_asset_id is not None:
        used.add(story.cover_asset_id)
    await touch_story_assets(db, story.id, set(released) - used)
    stale = set(
        await db.scalars(
            select(StoryAsset.id).where(
                StoryAsset.story_id == story.id,
                StoryAsset.last_used_at < func.now() - UNREFERENCED_GRACE,
                StoryAsset.id.not_in(used),
            )
        )
    )
    # Parsed only when something could go.
    stale -= image_ids(story.published) if stale else set()
    if not stale:
        return []
    deleted = await db.scalars(
        delete(StoryAsset)
        .where(StoryAsset.id.in_(stale))
        .returning(StoryAsset.storage_key)
    )
    return list(deleted)


async def discard_story_asset_objects(storage_keys: Iterable[str]) -> None:
    """Delete objects whose rows are committed gone, best effort."""
    await delete_objects_best_effort(
        [resolve_current_storage_key(key) for key in storage_keys],
        "story_asset_object_delete_failed",
    )


async def commit_pruning(
    db: AsyncSession,
    story: Story,
    *,
    draft_ids: set[uuid.UUID] | None = None,
    released: Iterable[uuid.UUID] = (),
) -> None:
    """Prune, commit, then delete the pruned assets' objects."""
    unused = await prune_story_assets(db, story, draft_ids=draft_ids, released=released)
    await db.commit()
    await discard_story_asset_objects(unused)


async def _usage(db: AsyncSession, story_id: uuid.UUID) -> tuple[int, int]:
    count, stored = (
        await db.execute(
            select(
                func.count(), func.coalesce(func.sum(StoryAsset.byte_size), 0)
            ).where(StoryAsset.story_id == story_id)
        )
    ).one()
    return count, stored


def _over_caps(usage: tuple[int, int], adding: int) -> bool:
    count, stored = usage
    return count >= MAX_STORY_ASSETS or stored + adding > MAX_STORY_ASSET_BYTES


async def add_story_asset(
    db: AsyncSession,
    story: Story,
    storage_key: str,
    image: StoryImage,
    user_id: uuid.UUID,
) -> tuple[StoryAsset, list[str]]:
    """Record a stored image, and the storage keys of assets pruned to make
    room for it.

    Call holding ``lock_story``, which keeps two uploads from both passing
    the caps; 409 ``story_asset_limit`` past them.
    """
    unused: list[str] = []
    if _over_caps(await _usage(db, story.id), len(image.data)):
        unused = await prune_story_assets(db, story)
        if _over_caps(await _usage(db, story.id), len(image.data)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "story_asset_limit",
                    "message": (
                        f"A story holds at most {MAX_STORY_ASSETS} images or "
                        f"{MAX_STORY_ASSET_BYTES // 2**20} MB of them."
                    ),
                },
            )
    asset = StoryAsset(
        id=uuid.uuid4(),
        story_id=story.id,
        storage_key=storage_key,
        byte_size=len(image.data),
        width=image.width,
        height=image.height,
        created_by=user_id,
    )
    db.add(asset)
    await db.flush()
    return asset, unused


async def story_asset_keys(db: AsyncSession, story_id: uuid.UUID) -> list[str]:
    return list(
        await db.scalars(
            select(StoryAsset.storage_key).where(StoryAsset.story_id == story_id)
        )
    )


def _renamed(node: Any, names: dict[uuid.UUID, uuid.UUID]) -> Any:
    """``node`` with every id in ``names`` replaced, in any spelling, by the
    canonical spelling of its new id."""
    if isinstance(node, dict):
        return {key: _renamed(value, names) for key, value in node.items()}
    if isinstance(node, list):
        return [_renamed(value, names) for value in node]
    parsed = _as_uuid(node)
    return str(names[parsed]) if parsed in names else node


def _copied_document(
    document: dict[str, Any],
    names: dict[uuid.UUID, uuid.UUID],
    uncopied: set[uuid.UUID],
) -> dict[str, Any]:
    """``document`` pointing at the copies, without the blocks whose images
    weren't copied. A new object: the story row still holds ``document``
    itself, and an in-place change would leave nothing for the ORM to write."""
    chapters = []
    for chapter in chapters_of(document):
        stored = read_stored(chapter.get("blocks"), "story")
        blocks = []
        for block in stored.widgets:
            if isinstance(block, ImageWidget):
                if block.asset_id not in names:
                    continue
                block = block.model_copy(update={"asset_id": names[block.asset_id]})
            blocks.append(block)
        kept = [
            KeptWidget(item.after, _renamed(item.raw, names))
            for item in stored.unreadable
            if not mentioned_ids(item.raw) & uncopied
        ]
        chapters.append({**chapter, "blocks": to_store(blocks, kept)})
    return {**document, "chapters": chapters}


async def copy_story_assets(
    db: AsyncSession,
    source: Story,
    target: Story,
    document: dict[str, Any],
    publication: AssetPublication,
    *,
    editor: bool,
) -> None:
    """Give ``target`` its own copy of each image ``document`` shows and of the
    source's cover, and point ``document`` at the copies as its draft.

    Anyone but the source's ``editor`` gets only what readers get: the cover
    and the images of the published document. The
    source isn't locked, so a save or delete can remove one of its images
    while this runs; a block whose image wasn't copied is left out. Each new
    object is recorded on ``publication`` before any is written, so a failure
    before the commit removes them, and a cancelled copy finishes first, so
    the removal can't run ahead of the writes.
    """
    from app.platform.storage.provider import get_storage

    wanted = image_ids(document)
    if source.cover_asset_id is not None:
        wanted.add(source.cover_asset_id)
    rows = list(
        await db.scalars(
            select(StoryAsset)
            .where(StoryAsset.story_id == source.id, StoryAsset.id.in_(wanted))
            .order_by(StoryAsset.id)
        )
    )
    readable = image_ids(source.published) | {source.cover_asset_id}
    allowed = [row for row in rows if editor or row.id in readable]
    uncopied = {row.id for row in rows} - {row.id for row in allowed}
    keys = [new_story_asset_key(target.id) for _ in allowed]
    for key in keys:
        publication.record(resolve_current_storage_key(key))

    storage = get_storage()
    gate = asyncio.Semaphore(MAX_DELETES_IN_FLIGHT)

    async def copy_one(row: StoryAsset, key: str) -> None:
        async with gate:
            await storage.copy(
                resolve_current_storage_key(row.storage_key),
                resolve_current_storage_key(key),
            )

    results = await await_draining(
        asyncio.gather(
            *(copy_one(row, key) for row, key in zip(allowed, keys)),
            return_exceptions=True,
        )
    )
    names: dict[uuid.UUID, uuid.UUID] = {}
    skipped: list[str] = []
    for row, key, result in zip(allowed, keys, results):
        if isinstance(result, FileNotFoundError):
            uncopied.add(row.id)
            skipped.append(key)
            continue
        if isinstance(result, BaseException):
            logger.error(
                "story_asset_copy_failed", storage_key=row.storage_key, exc_info=result
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Story image storage unavailable",
            ) from result
        copy = StoryAsset(
            id=uuid.uuid4(),
            story_id=target.id,
            storage_key=key,
            byte_size=row.byte_size,
            width=row.width,
            height=row.height,
            created_by=target.created_by,
        )
        db.add(copy)
        names[row.id] = copy.id
    # A source deleted mid-copy can leave part of a copy behind, and no row
    # will name it once the publication settles.
    await discard_story_asset_objects(skipped)
    # The rows exist before the story names one as its cover.
    await db.flush()
    target.draft = _copied_document(document, names, uncopied)
    target.cover_asset_id = names.get(source.cover_asset_id)
