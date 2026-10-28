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
from sqlalchemy.orm import defer

from app.core.db.sqlstate import is_lock_conflict
from app.core.identity import Identity
from app.modules.auth.permissions import get_user_roles as get_account_roles
from app.modules.auth.service import get_user_identity
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
# A private story reaches only its owner and admins; see ``check_reach``.
_MAP_VISIBILITIES_FOR_STORY = {
    "public": ("public",),
    "internal": ("internal", "public"),
}
# How far each visibility reaches; only a change to a wider one is checked.
_REACH_ORDER = {"private": 0, "restricted": 1, "internal": 2, "public": 3}

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


async def _bounded_lock(db: AsyncSession, stmt: Select[Any]) -> list[Any]:
    """Run a locking select, answering 409 when the wait outlasts the timeout."""
    await db.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": _LOCK_TIMEOUT},
    )
    try:
        rows = list((await db.scalars(stmt)).all())
    except DBAPIError as exc:
        if not is_lock_conflict(exc):
            raise
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another change to this story is in progress. Retry shortly.",
        ) from exc
    await db.execute(text("RESET lock_timeout"))
    return rows


async def lock_story(
    db: AsyncSession, story_id: uuid.UUID, user: Identity
) -> tuple[Story, set[str]]:
    """Lock the story row for a write; return it and ``user``'s roles as
    committed now.

    Re-checks the writer ``check_story_ownership`` admitted. Everything after
    the lock uses the roles returned here, since a role can change while the
    write waits. A wait past the lock timeout answers 409.
    """
    locked = await _bounded_lock(
        db,
        select(Story)
        .where(Story.id == story_id)
        .with_for_update()
        .execution_options(populate_existing=True),
    )
    story = locked[0] if locked else None

    rechecked: set[str] | None = None

    async def enforce(writer: Identity, row: Any) -> None:
        nonlocal rechecked
        if row is None:
            raise _not_found()
        if not row.active or (row.created_by != writer.id and "admin" not in row.roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=STORY_WRITE_DENIED
            )
        rechecked = set(row.roles)

    await recheck_admitted_writer(
        db, ("story", story_id), (Story.created_by,), Story.id == story_id, enforce
    )
    if story is None:
        raise _not_found()
    if rechecked is None:
        rechecked = await get_user_roles(db, user)
    return story, rechecked


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
        select(Story).options(defer(Story.draft), defer(Story.published)),
        user.id if user is not None else None,
        "admin" in roles,
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


def _scene_map_id(raw: Any) -> uuid.UUID | None:
    """The map a stored scene names. Read leniently, so a scene this server
    can't parse is still reach-checked and filtered."""
    if not isinstance(raw, dict):
        return None
    try:
        return uuid.UUID(str(raw.get("map_id")))
    except ValueError:
        return None


def scene_map_ids(*documents: Any) -> set[uuid.UUID]:
    """The maps the scenes of ``documents`` use."""
    ids = set()
    for document in documents:
        for chapter in _chapters(document):
            map_id = _scene_map_id(chapter.get("scene"))
            if map_id is not None:
                ids.add(map_id)
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
    since deleted), or one this server can't parse, is left out and the
    chapter marked ``scene_hidden``. Blocks and chapters this server can't
    parse are left out too.
    """
    chapters = []
    for raw in _chapters(document):
        try:
            chapter_id = uuid.UUID(str(raw.get("id")))
        except ValueError:
            continue
        stored_scene = raw.get("scene")
        scene = _scene(stored_scene)
        hidden = stored_scene is not None and (
            scene is None or scene.map_id not in readable
        )
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


def _unreadable_by_this_version() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "This story was saved by a newer version of GeoLens and can't be "
            "changed here."
        ),
    )


def _refuse_newer_document(stored: Any) -> None:
    """Refuse to overwrite a document a newer server wrote, or one holding
    chapters this server can't identify: a save would drop what it can't read."""
    version = stored.get("version") if isinstance(stored, dict) else None
    if isinstance(version, int) and version > STORY_DOCUMENT_VERSION:
        raise _unreadable_by_this_version()
    chapters = stored.get("chapters") if isinstance(stored, dict) else None
    for chapter in chapters or ():
        try:
            uuid.UUID(str(chapter.get("id")))
        except (AttributeError, ValueError):
            raise _unreadable_by_this_version() from None


async def merge_document(
    db: AsyncSession,
    sent: StoryDocumentInput,
    stored: Any,
    editor: Identity,
    roles: set[str],
) -> dict[str, Any]:
    """The document to store for a draft save.

    A sent scene must be on a map the editor can read. A chapter sent with
    ``scene_hidden`` keeps its stored scene as stored, so a save never drops a
    scene on a map the editor can no longer read, or one this server can't
    parse. Blocks the server can't parse go back
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
        elif chapter.scene_hidden and prior.get("scene") is not None:
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
    for chapter in _chapters(document):
        map_id = _scene_map_id(chapter.get("scene"))
        if map_id is not None and map_id not in existing:
            chapter["scene"] = None
    return document


async def sync_story_maps(db: AsyncSession, story: Story) -> None:
    """Point ``story_maps`` at the maps the draft and published scenes use.

    Takes the maps involved FOR KEY SHARE, in id order, before touching
    ``story_maps``. A map delete locks its map row and then cascades into
    ``story_maps``; locking maps first keeps the two in one order.
    """
    map_ids = scene_map_ids(story.draft, story.published)
    listed = set(
        await db.scalars(select(StoryMap.map_id).where(StoryMap.story_id == story.id))
    )
    if map_ids | listed:
        await _bounded_lock(
            db,
            select(Map.id)
            .where(Map.id.in_(map_ids | listed))
            .order_by(Map.id)
            .with_for_update(read=True, key_share=True),
        )
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


class StoryReachError(Exception):
    """Maps the story uses are narrower than its visibility."""

    def __init__(self, maps: list[BlockingMap], unreadable: int) -> None:
        super().__init__("maps are narrower than the story's visibility")
        self.maps = maps
        self.unreadable = unreadable


async def _owner_reads(
    db: AsyncSession, map_ids: set[uuid.UUID], owner_id: uuid.UUID
) -> set[uuid.UUID] | None:
    """The maps the story's owner can read, or None when the owner can't sign
    in, which leaves a private story to admins."""
    owner = await get_user_identity(db, owner_id)
    if owner is None or not owner.is_active:
        return None
    is_admin = "admin" in await get_account_roles(db, owner)
    return await readable_map_ids(db, map_ids, owner_id, is_admin)


async def check_reach(
    db: AsyncSession,
    map_ids: set[uuid.UUID],
    visibility: str,
    owner_id: uuid.UUID | None,
    publisher: Identity,
    publisher_roles: set[str],
) -> None:
    """Raise ``StoryReachError`` for maps narrower than the audience a story
    with ``visibility`` reaches.

    A private story reaches its owner and admins, so its maps must be ones the
    owner can read. The error names only maps the publisher can read and
    counts the rest. A visibility this server has no rule for is refused.
    """
    allowed = _MAP_VISIBILITIES_FOR_STORY.get(visibility)
    if allowed is None and visibility != "private":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "visibility_unsupported",
                "message": f"Stories can't be published as {visibility} yet.",
            },
        )
    if not map_ids:
        return
    rows = (
        await db.execute(
            select(Map.id, Map.name, Map.visibility).where(Map.id.in_(map_ids))
        )
    ).all()
    if allowed is not None:
        blocking = {row.id for row in rows if row.visibility not in allowed}
    else:
        owner_reads = (
            await _owner_reads(db, map_ids, owner_id) if owner_id is not None else None
        )
        blocking = set() if owner_reads is None else {r.id for r in rows} - owner_reads
    if not blocking:
        return
    visible = await readable_map_ids(
        db, blocking, publisher.id, "admin" in publisher_roles
    )
    named = [
        BlockingMap(id=row.id, name=row.name)
        for row in sorted(rows, key=lambda r: str(r.id))
        if row.id in visible
    ]
    raise StoryReachError(named, len(blocking - visible))


def _refuse_unplaced_scenes(document: Any) -> None:
    """Refuse to publish a scene whose map can't be found in it, since its
    reach can't be checked."""
    for chapter in _chapters(document):
        raw = chapter.get("scene")
        if raw is not None and _scene_map_id(raw) is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "scenes_unreadable",
                    "message": (
                        "Some scenes were saved by a newer version of GeoLens "
                        "and can't be published here."
                    ),
                },
            )


async def publish(
    db: AsyncSession, story: Story, publisher: Identity, roles: set[str]
) -> None:
    """Copy the draft to the published document, if every map it uses reaches
    the story's audience. Call holding ``lock_story``."""
    _refuse_newer_document(story.draft)
    document = await _without_deleted_maps(db, copy.deepcopy(story.draft))
    _refuse_unplaced_scenes(document)
    await check_reach(
        db,
        scene_map_ids(document),
        story.visibility,
        story.created_by,
        publisher,
        roles,
    )
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
    """Refuse a wider visibility the published document's maps don't reach.

    A narrower one always passes, so a story can be pulled back after one of
    its maps is.
    """
    if story.published is None:
        return
    if _REACH_ORDER.get(visibility, 0) <= _REACH_ORDER.get(story.visibility, 0):
        return
    await check_reach(
        db,
        scene_map_ids(story.published),
        visibility,
        story.created_by,
        editor,
        roles,
    )


async def discard(db: AsyncSession, story: Story, revision: int) -> None:
    """Revert the draft to the published document, without scenes on maps
    deleted since. Call holding ``lock_story``; 409 on a stale revision."""
    refuse_stale_revision(story, revision)
    story.draft = (
        await _without_deleted_maps(db, copy.deepcopy(story.published))
        if story.published
        else empty_document()
    )
    story.draft_revision += 1
    await sync_story_maps(db, story)


def refuse_stale_revision(story: Story, revision: int) -> None:
    """409 ``stale_revision`` unless ``revision`` is the stored draft's."""
    if revision != story.draft_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_revision",
                "message": "The draft changed since you loaded it. Reload it and try again.",
                "revision": story.draft_revision,
            },
        )


async def save_draft(
    db: AsyncSession,
    story: Story,
    revision: int,
    sent: StoryDocumentInput,
    editor: Identity,
    roles: set[str],
) -> None:
    """Replace the draft. Call holding ``lock_story``; 409 on a stale revision."""
    refuse_stale_revision(story, revision)
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
        raw = chapter.get("scene")
        if raw is not None and _scene_map_id(raw) not in readable:
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
