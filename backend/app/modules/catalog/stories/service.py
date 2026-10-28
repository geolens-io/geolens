"""Stories: access guards, draft saves, publishing and copies.

Readers get a story's published document; its owner and admins also read and
save the draft. Each read resolves every scene's map with the reader's own
identity, so a scene on a map they can't read is left out rather than shown.
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import Select, and_, delete, func, insert, literal, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import is_lock_conflict
from app.core.identity import Identity
from app.modules.catalog.authorization import (
    apply_map_visibility_filter,
    get_user_roles,
)
from app.modules.catalog.maps.models import Map
from app.modules.catalog.stories.models import Story, StoryMap
from app.modules.catalog.stories.schemas import (
    STORY_DOCUMENT_VERSION,
    BlockingMap,
    StoryChapter,
    StoryDocument,
    StoryDocumentInput,
    StoryScene,
)
from app.modules.catalog.widgets.schemas import read_stored, to_store
from app.modules.catalog.write_recheck import admit_writer, recheck_admitted_writer

logger = structlog.stdlib.get_logger(__name__)

STORY_NOT_FOUND = "Story not found"
STORY_WRITE_DENIED = "Only the story's owner or an admin can change it"

# Who may read a published story besides its owner and admins.
ANONYMOUS_STORY_VISIBILITIES = ("public",)
SIGNED_IN_STORY_VISIBILITIES = ("internal", "public")
# The map visibilities that reach everyone a story of each visibility reaches.
# A private story reaches only its owner and admins; see ``maps_blocking``.
_MAP_VISIBILITIES_FOR_STORY = {
    "public": ("public",),
    "internal": ("internal", "public"),
}

_LOCK_TIMEOUT = "2s"


def empty_document() -> dict[str, Any]:
    return {"version": STORY_DOCUMENT_VERSION, "chapters": []}


async def get_story(db: AsyncSession, story_id: uuid.UUID) -> Story | None:
    """The story row, unguarded: every caller passes it to a story guard."""
    return await db.get(Story, story_id)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=STORY_NOT_FOUND)


async def check_story_access(
    db: AsyncSession, story: Story, user: Identity | None
) -> set[str]:
    """Raise 404 unless ``user`` (None for anonymous) may read ``story``.

    Owners and admins may always read it. Anyone else needs a published story
    whose visibility admits them. Returns the caller's roles (empty for
    anonymous).
    """
    published = story.published_at is not None
    if user is None:
        roles: set[str] = set()
        allowed = published and story.visibility in ANONYMOUS_STORY_VISIBILITIES
    else:
        roles = await get_user_roles(db, user)
        allowed = (
            "admin" in roles
            or story.created_by == user.id
            or (published and story.visibility in SIGNED_IN_STORY_VISIBILITIES)
        )
    if not allowed:
        logger.warning(
            "story_read_denied",
            story_id=str(story.id),
            user_id=str(user.id) if user is not None else "anon",
        )
        raise _not_found()
    return roles


def can_edit_story(story: Story, user: Identity | None, roles: set[str]) -> bool:
    return user is not None and ("admin" in roles or story.created_by == user.id)


async def check_story_ownership(
    db: AsyncSession, story: Story, user: Identity
) -> set[str]:
    """Raise 404 unless ``user`` may read ``story``, and 403 unless they own it
    or are an admin. Returns the caller's roles.

    ``lock_story`` checks the writer again under the row lock.
    """
    roles = await check_story_access(db, story, user)
    if not can_edit_story(story, user, roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=STORY_WRITE_DENIED
        )
    admit_writer(db, ("story", story.id), user)
    return roles


def apply_story_visibility_filter(
    stmt: Select[Any], user_id: uuid.UUID | None, is_admin: bool
) -> Select[Any]:
    """Limit a Story query to the stories a caller may read; None is anonymous."""
    if is_admin:
        return stmt
    published = Story.published_at.is_not(None)
    if user_id is None:
        return stmt.where(published, Story.visibility.in_(ANONYMOUS_STORY_VISIBILITIES))
    return stmt.where(
        or_(
            Story.created_by == user_id,
            and_(published, Story.visibility.in_(SIGNED_IN_STORY_VISIBILITIES)),
        )
    )


async def lock_story(db: AsyncSession, story_id: uuid.UUID) -> Story:
    """Lock the story row for a write and return it as committed now.

    Re-checks the writer ``check_story_ownership`` admitted. A wait past the
    lock timeout answers 409.
    """
    await db.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": _LOCK_TIMEOUT},
    )
    try:
        story = await db.scalar(
            select(Story)
            .where(Story.id == story_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    except DBAPIError as exc:
        if not is_lock_conflict(exc):
            raise
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another change to this story is in progress. Retry shortly.",
        ) from exc
    await db.execute(text("RESET lock_timeout"))

    async def enforce(user: Identity, row: Any) -> None:
        if row is None:
            raise _not_found()
        if not row.active or (row.created_by != user.id and "admin" not in row.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=STORY_WRITE_DENIED
            )

    await recheck_admitted_writer(
        db, ("story", story_id), (Story.created_by,), Story.id == story_id, enforce
    )
    if story is None:
        raise _not_found()
    return story


async def list_stories(
    db: AsyncSession,
    user: Identity | None,
    roles: set[str],
    *,
    skip: int,
    limit: int,
    owned_only: bool,
) -> tuple[list[Story], int]:
    stmt = apply_story_visibility_filter(
        select(Story), user.id if user is not None else None, "admin" in roles
    )
    if owned_only:
        if user is None:
            return [], 0
        stmt = stmt.where(Story.created_by == user.id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    page = await db.scalars(
        stmt.order_by(Story.updated_at.desc(), Story.id).offset(skip).limit(limit)
    )
    return list(page), total


# Documents -----------------------------------------------------------------


def _chapters(document: Any) -> list[dict[str, Any]]:
    chapters = document.get("chapters") if isinstance(document, dict) else None
    return [c for c in chapters or () if isinstance(c, dict)]


def _scene(raw: Any) -> StoryScene | None:
    if raw is None:
        return None
    try:
        return StoryScene.model_validate(raw)
    except ValidationError:
        return None


def scene_map_ids(*documents: Any) -> set[uuid.UUID]:
    """The maps the scenes of ``documents`` use."""
    ids = set()
    for document in documents:
        for chapter in _chapters(document):
            scene = _scene(chapter.get("scene"))
            if scene is not None:
                ids.add(scene.map_id)
    return ids


async def readable_map_ids(
    db: AsyncSession,
    map_ids: Iterable[uuid.UUID],
    user_id: uuid.UUID | None,
    is_admin: bool,
) -> set[uuid.UUID]:
    """The maps among ``map_ids`` that the caller may read."""
    wanted = set(map_ids)
    if not wanted:
        return set()
    stmt = apply_map_visibility_filter(
        select(Map.id).where(Map.id.in_(wanted)), user_id, is_admin
    )
    return set((await db.scalars(stmt)).all())


async def _existing_map_ids(
    db: AsyncSession, map_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    wanted = set(map_ids)
    if not wanted:
        return set()
    return set((await db.scalars(select(Map.id).where(Map.id.in_(wanted)))).all())


def render_document(document: Any, readable: set[uuid.UUID]) -> StoryDocument:
    """A stored document as one reader sees it.

    A scene on a map outside ``readable`` (one the reader can't read, or one
    since deleted) is left out and the chapter marked ``scene_hidden``. Blocks
    this server can't parse are left out too.
    """
    chapters = []
    for raw in _chapters(document):
        try:
            chapter_id = uuid.UUID(str(raw.get("id")))
        except ValueError:
            continue
        scene = _scene(raw.get("scene"))
        hidden = scene is not None and scene.map_id not in readable
        title = raw.get("title")
        chapters.append(
            StoryChapter(
                id=chapter_id,
                title=title if isinstance(title, str) else None,
                scene=None if hidden else scene,
                scene_hidden=hidden,
                blocks=read_stored(raw.get("blocks"), "story").widgets,
            )
        )
    version = document.get("version") if isinstance(document, dict) else None
    return StoryDocument(
        version=version if isinstance(version, int) else STORY_DOCUMENT_VERSION,
        chapters=chapters,
    )


async def render_for(
    db: AsyncSession, document: Any, user: Identity | None, roles: set[str]
) -> StoryDocument:
    readable = await readable_map_ids(
        db,
        scene_map_ids(document),
        user.id if user is not None else None,
        "admin" in roles,
    )
    return render_document(document, readable)


class StoryMapsNotFoundError(Exception):
    """Scenes name maps the editor can't read, or that don't exist."""

    def __init__(self, map_ids: list[uuid.UUID]) -> None:
        super().__init__("story scenes use maps that weren't found")
        self.map_ids = map_ids


def _refuse_newer_document(stored: Any) -> None:
    """Refuse to overwrite a document a newer server wrote, which this one
    would save without the fields it doesn't know."""
    version = stored.get("version") if isinstance(stored, dict) else None
    if isinstance(version, int) and version > STORY_DOCUMENT_VERSION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This story was saved by a newer version of GeoLens and can't "
                "be changed here."
            ),
        )


async def merge_document(
    db: AsyncSession,
    sent: StoryDocumentInput,
    stored: Any,
    editor: Identity,
    roles: set[str],
) -> dict[str, Any]:
    """The document to store for a draft save.

    A sent scene must be on a map the editor can read. A chapter sent with
    ``scene_hidden`` keeps its stored scene, so a save never drops a scene on
    a map the editor can no longer read. Blocks the server can't parse go back
    where they were (``to_store``). Scenes on deleted maps are dropped.
    """
    _refuse_newer_document(stored)
    stored_by_id = {str(c.get("id")): c for c in _chapters(stored)}
    sent_maps = {c.scene.map_id for c in sent.chapters if c.scene is not None}
    readable = await readable_map_ids(db, sent_maps, editor.id, "admin" in roles)
    missing = sorted(sent_maps - readable)
    if missing:
        raise StoryMapsNotFoundError(missing)

    chapters: list[dict[str, Any]] = []
    for chapter in sent.chapters:
        prior = stored_by_id.get(str(chapter.id), {})
        scene: dict[str, Any] | None = None
        if chapter.scene is not None:
            scene = chapter.scene.model_dump(mode="json")
        elif chapter.scene_hidden and _scene(prior.get("scene")) is not None:
            scene = prior["scene"]
        kept = read_stored(prior.get("blocks"), "story").unreadable
        chapters.append(
            {
                "id": str(chapter.id),
                "title": chapter.title,
                "scene": scene,
                "blocks": to_store(chapter.blocks, kept),
            }
        )
    document = {"version": STORY_DOCUMENT_VERSION, "chapters": chapters}
    return await _without_deleted_maps(db, document)


async def _without_deleted_maps(
    db: AsyncSession, document: dict[str, Any]
) -> dict[str, Any]:
    existing = await _existing_map_ids(db, scene_map_ids(document))
    for chapter in document["chapters"]:
        scene = _scene(chapter.get("scene"))
        if scene is not None and scene.map_id not in existing:
            chapter["scene"] = None
    return document


async def sync_story_maps(db: AsyncSession, story: Story) -> None:
    """Point ``story_maps`` at the maps the draft and published scenes use."""
    map_ids = scene_map_ids(story.draft, story.published)
    await db.execute(delete(StoryMap).where(StoryMap.story_id == story.id))
    if map_ids:
        # Selecting from maps skips one deleted since the document was read.
        await db.execute(
            insert(StoryMap).from_select(
                ["story_id", "map_id"],
                select(literal(story.id, Story.id.type), Map.id).where(
                    Map.id.in_(map_ids)
                ),
            )
        )


async def maps_blocking(
    db: AsyncSession,
    map_ids: set[uuid.UUID],
    visibility: str,
    owner_id: uuid.UUID | None,
    publisher: Identity,
    publisher_roles: set[str],
) -> list[BlockingMap]:
    """Maps narrower than the audience a story with ``visibility`` reaches.

    A private story reaches its owner and admins, so its maps must be ones
    the owner can read. Names are given only for maps the publisher can read.
    """
    if not map_ids:
        return []
    rows = (
        await db.execute(
            select(Map.id, Map.name, Map.visibility).where(Map.id.in_(map_ids))
        )
    ).all()
    allowed = _MAP_VISIBILITIES_FOR_STORY.get(visibility)
    if allowed is not None:
        blocking = {row.id for row in rows if row.visibility not in allowed}
    elif owner_id is None:
        blocking = set()
    else:
        # The owner's own admin role is known only when the owner publishes.
        owner_is_admin = owner_id == publisher.id and "admin" in publisher_roles
        owner_reads = await readable_map_ids(db, map_ids, owner_id, owner_is_admin)
        blocking = {row.id for row in rows} - owner_reads
    if not blocking:
        return []
    visible = await readable_map_ids(
        db, blocking, publisher.id, "admin" in publisher_roles
    )
    return [
        BlockingMap(id=row.id, name=row.name if row.id in visible else None)
        for row in sorted(rows, key=lambda r: str(r.id))
        if row.id in blocking
    ]


class StoryReachError(Exception):
    """Maps the story uses are narrower than its visibility."""

    def __init__(self, maps: list[BlockingMap]) -> None:
        super().__init__("maps are narrower than the story's visibility")
        self.maps = maps


async def publish(
    db: AsyncSession, story: Story, publisher: Identity, roles: set[str]
) -> None:
    """Copy the draft to the published document, if every map it uses reaches
    the story's audience. Call holding ``lock_story``."""
    _refuse_newer_document(story.draft)
    document = await _without_deleted_maps(db, copy.deepcopy(story.draft))
    blocking = await maps_blocking(
        db,
        scene_map_ids(document),
        story.visibility,
        story.created_by,
        publisher,
        roles,
    )
    if blocking:
        raise StoryReachError(blocking)
    story.draft = document
    story.published = copy.deepcopy(document)
    story.published_at = datetime.now(UTC)
    await sync_story_maps(db, story)


async def check_visibility_change(
    db: AsyncSession,
    story: Story,
    visibility: str,
    editor: Identity,
    roles: set[str],
) -> None:
    """Refuse a visibility the published document's maps don't reach."""
    if story.published is None:
        return
    blocking = await maps_blocking(
        db,
        scene_map_ids(story.published),
        visibility,
        story.created_by,
        editor,
        roles,
    )
    if blocking:
        raise StoryReachError(blocking)


def discard(story: Story) -> None:
    """Revert the draft to the published document. Call holding ``lock_story``."""
    story.draft = (
        copy.deepcopy(story.published) if story.published else empty_document()
    )
    story.draft_revision += 1


async def save_draft(
    db: AsyncSession,
    story: Story,
    revision: int,
    sent: StoryDocumentInput,
    editor: Identity,
    roles: set[str],
) -> None:
    """Replace the draft. Call holding ``lock_story``; 409 on a stale revision."""
    if revision != story.draft_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_revision",
                "message": "The draft changed since you loaded it. Reload it and try again.",
                "revision": story.draft_revision,
            },
        )
    story.draft = await merge_document(db, sent, story.draft, editor, roles)
    story.draft_revision += 1
    await sync_story_maps(db, story)


async def create_story(
    db: AsyncSession,
    *,
    title: str,
    summary: str | None,
    owner_id: uuid.UUID,
    draft: dict[str, Any] | None = None,
) -> Story:
    """Add a private, unpublished story. Does NOT commit."""
    story = Story(
        title=title,
        summary=summary,
        visibility="private",
        draft=draft if draft is not None else empty_document(),
        created_by=owner_id,
    )
    db.add(story)
    await db.flush()
    await sync_story_maps(db, story)
    return story


async def duplicate_story(
    db: AsyncSession,
    source: Story,
    user: Identity,
    roles: set[str],
) -> Story:
    """Copy a story the caller can read into a new private draft they own.

    An editor copies the draft; anyone else the published document. Scenes on
    maps the caller can't read are dropped, as ``duplicate_map`` drops layers.
    """
    document = (
        copy.deepcopy(
            source.draft if can_edit_story(source, user, roles) else source.published
        )
        or empty_document()
    )
    readable = await readable_map_ids(
        db, scene_map_ids(document), user.id, "admin" in roles
    )
    for chapter in _chapters(document):
        scene = _scene(chapter.get("scene"))
        if scene is not None and scene.map_id not in readable:
            chapter["scene"] = None
    return await create_story(
        db,
        title=f"{source.title} (copy)"[:200],
        summary=source.summary,
        owner_id=user.id,
        draft=document,
    )


async def delete_story(db: AsyncSession, story: Story) -> None:
    """Delete a story; its ``story_maps`` rows go with it. Does NOT commit."""
    await db.delete(story)
