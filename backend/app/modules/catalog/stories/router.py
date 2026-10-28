"""Stories API: published reads, draft saves, publishing and copies."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import get_optional_user, require_permission
from app.modules.catalog.authorization import (
    check_public_visibility_allowed,
    get_user_roles,
)
from app.modules.catalog.stories.models import Story
from app.modules.catalog.stories.schemas import (
    StoryCreate,
    StoryDraftResponse,
    StoryDraftUpdate,
    StoryListResponse,
    StoryPublish,
    StoryResponse,
    StorySummary,
    StoryUpdate,
)
from app.modules.catalog.stories.service import (
    StoryMapsNotFoundError,
    StoryReachError,
    can_edit_story,
    check_story_access,
    check_story_ownership,
    check_visibility_change,
    create_story,
    delete_story,
    discard,
    duplicate_story,
    get_story,
    list_stories,
    lock_story,
    publish,
    refuse_stale_revision,
    render_for,
    save_draft,
)
from app.standards.ogc.errors import CONFLICT_RESPONSE, ERROR_RESPONSES_WRITE

router = APIRouter(prefix="/stories", tags=["Stories"], responses=ERROR_RESPONSES_WRITE)

_REACH_CONFLICT = {
    **CONFLICT_RESPONSE,
    "description": (
        "Maps the story uses are narrower than its visibility (`detail.code` "
        "`maps_narrower_than_story`, the maps under `detail.maps`), a stale "
        "draft revision (`stale_revision`), or another change holding the "
        "story's lock (no `detail.code`)."
    ),
}


def _summary(story: Story, can_edit: bool) -> dict:
    return {
        "id": story.id,
        "title": story.title,
        "summary": story.summary,
        "visibility": story.visibility,
        "created_by": story.created_by,
        "published_at": story.published_at,
        "created_at": story.created_at,
        "updated_at": story.updated_at,
        "can_edit": can_edit,
    }


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _readable_story(
    db: AsyncSession, story_id: uuid.UUID, user: Identity | None
) -> tuple[Story, set[str]]:
    story = await get_story(db, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Story not found"
        )
    roles = await check_story_access(db, story, user)
    return story, roles


async def _owned_story(
    db: AsyncSession, story_id: uuid.UUID, user: Identity
) -> tuple[Story, set[str]]:
    story = await get_story(db, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Story not found"
        )
    roles = await check_story_ownership(db, story, user)
    return await lock_story(db, story_id), roles


def _reach_conflict(exc: StoryReachError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "maps_narrower_than_story",
            "message": "Some maps this story uses can't be read by everyone the story reaches.",
            "maps": [m.model_dump(mode="json") for m in exc.maps],
            "unreadable_maps": exc.unreadable,
        },
    )


async def _draft_response(
    db: AsyncSession, story: Story, user: Identity, roles: set[str]
) -> StoryDraftResponse:
    return StoryDraftResponse(
        **_summary(story, True),
        revision=story.draft_revision,
        document=await render_for(db, story.draft, user, roles),
    )


@router.get("", response_model=StoryListResponse, include_in_schema=False)
@router.get("/", response_model=StoryListResponse)
async def list_stories_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    owned_only: bool = False,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> StoryListResponse:
    """List the stories the caller may read, most recently updated first.

    Anyone sees published public stories, signed-in users also published
    internal ones, owners their own (published or not), and admins all.
    """
    roles = await get_user_roles(db, user) if user is not None else set()
    stories, total = await list_stories(
        db, user, roles, skip=skip, limit=limit, owned_only=owned_only
    )
    return StoryListResponse(
        stories=[
            StorySummary(**_summary(s, can_edit_story(s, user, roles))) for s in stories
        ],
        total=total,
    )


@router.post(
    "",
    response_model=StoryDraftResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/", response_model=StoryDraftResponse, status_code=status.HTTP_201_CREATED
)
async def create_story_endpoint(
    body: StoryCreate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryDraftResponse:
    """Create a private, unpublished story with an empty draft."""
    story = await create_story(
        db, title=body.title, summary=body.summary, owner_id=user.id
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="story.create",
            resource_type="story",
            resource_id=story.id,
            details={"title": body.title},
            ip_address=_ip(request),
        ),
    )
    await db.commit()
    await db.refresh(story)
    return await _draft_response(db, story, user, await get_user_roles(db, user))


@router.get("/{story_id}", response_model=StoryResponse)
async def get_story_endpoint(
    story_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Read a story's published document.

    Scenes on maps the caller can't read come back without their scene. An
    unpublished story is readable only by its owner and admins, with a null
    document. 404 when the caller can't read the story.
    """
    story, roles = await _readable_story(db, story_id, user)
    document = (
        await render_for(db, story.published, user, roles)
        if story.published is not None
        else None
    )
    return StoryResponse(
        **_summary(story, can_edit_story(story, user, roles)), document=document
    )


@router.get(
    "/{story_id}/draft", response_model=StoryDraftResponse, include_in_schema=False
)
async def get_story_draft_endpoint(
    story_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryDraftResponse:
    """The draft, for the story's owner and admins only."""
    story = await get_story(db, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Story not found"
        )
    roles = await check_story_ownership(db, story, user)
    return await _draft_response(db, story, user, roles)


@router.put(
    "/{story_id}/draft",
    response_model=StoryDraftResponse,
    responses={409: _REACH_CONFLICT},
)
async def save_story_draft_endpoint(
    story_id: uuid.UUID,
    body: StoryDraftUpdate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryDraftResponse:
    """Replace the whole draft (owner or admin). Readers keep the published
    document until Publish.

    `revision` must match the stored draft's, or 409 `stale_revision`. 422
    for an unknown or invalid block, or for a scene on a map you can't read
    (`detail.code` `story_maps_not_found`). Blocks you can't see and scenes
    sent back with `scene_hidden` are kept as stored.
    """
    story, roles = await _owned_story(db, story_id, user)
    try:
        await save_draft(db, story, body.revision, body.document, user, roles)
    except StoryMapsNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "story_maps_not_found",
                "message": "Some scenes use maps that weren't found.",
                "map_ids": [str(map_id) for map_id in exc.map_ids],
            },
        ) from exc
    await db.commit()
    await db.refresh(story)
    return await _draft_response(db, story, user, roles)


@router.patch(
    "/{story_id}", response_model=StoryResponse, responses={409: _REACH_CONFLICT}
)
async def update_story_endpoint(
    story_id: uuid.UUID,
    body: StoryUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Change a story's title, summary or visibility (owner or admin).

    These apply at once, without Publish. A visibility wider than a map the
    published story uses answers 409 `maps_narrower_than_story`; a narrower
    one is always allowed.
    """
    story = await get_story(db, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Story not found"
        )
    roles = await check_story_ownership(db, story, user)
    visibility = body.visibility.value if body.visibility is not None else None
    roles = (
        await check_public_visibility_allowed(db, user, visibility, user_roles=roles)
        or roles
    )
    story = await lock_story(db, story_id)
    changes = body.model_dump(exclude_unset=True, mode="json")
    if visibility is not None and visibility != story.visibility:
        try:
            await check_visibility_change(db, story, visibility, user, roles)
        except StoryReachError as exc:
            raise _reach_conflict(exc) from exc
        story.visibility = visibility
    if "title" in changes and body.title is not None:
        story.title = body.title
    if "summary" in changes:
        story.summary = body.summary
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="story.update",
            resource_type="story",
            resource_id=story.id,
            details=changes,
            ip_address=_ip(request),
        ),
    )
    await db.commit()
    await db.refresh(story)
    document = (
        await render_for(db, story.published, user, roles)
        if story.published is not None
        else None
    )
    return StoryResponse(**_summary(story, True), document=document)


@router.post(
    "/{story_id}/publish",
    response_model=StoryResponse,
    responses={409: _REACH_CONFLICT},
)
async def publish_story_endpoint(
    story_id: uuid.UUID,
    body: StoryPublish,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryResponse:
    """Publish the draft (owner or admin): readers get it from now on.

    `revision` must match the stored draft's, or 409 `stale_revision`. 409
    `maps_narrower_than_story` when a map a scene uses can't be read by
    everyone the story's visibility reaches: `detail.maps` names the ones you
    can read and `detail.unreadable_maps` counts the rest.
    """
    story, roles = await _owned_story(db, story_id, user)
    refuse_stale_revision(story, body.revision)
    try:
        await publish(db, story, user, roles)
    except StoryReachError as exc:
        raise _reach_conflict(exc) from exc
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="story.publish",
            resource_type="story",
            resource_id=story.id,
            details={"visibility": story.visibility},
            ip_address=_ip(request),
        ),
    )
    await db.commit()
    await db.refresh(story)
    return StoryResponse(
        **_summary(story, True),
        document=await render_for(db, story.published, user, roles),
    )


@router.post("/{story_id}/discard", response_model=StoryDraftResponse)
async def discard_story_draft_endpoint(
    story_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryDraftResponse:
    """Revert the draft to the published document, or to an empty one for a
    story never published (owner or admin)."""
    story, roles = await _owned_story(db, story_id, user)
    discard(story)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="story.update",
            resource_type="story",
            resource_id=story.id,
            details={"discarded_draft": True},
            ip_address=_ip(request),
        ),
    )
    await db.commit()
    await db.refresh(story)
    return await _draft_response(db, story, user, roles)


@router.delete("/{story_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_story_endpoint(
    story_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a story (owner or admin). The maps it uses are untouched."""
    story, _ = await _owned_story(db, story_id, user)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="story.delete",
            resource_type="story",
            resource_id=story.id,
            details={"title": story.title},
            ip_address=_ip(request),
        ),
    )
    await delete_story(db, story)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{story_id}/duplicate",
    response_model=StoryDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_story_endpoint(
    story_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryDraftResponse:
    """Copy a story you can read into a new private draft you own.

    Its owner or an admin copies the draft; anyone else the published
    document. Scenes on maps you can't read are left out of the copy.
    """
    source, roles = await _readable_story(db, story_id, user)
    copy = await duplicate_story(db, source, user, roles)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="story.duplicate",
            resource_type="story",
            resource_id=copy.id,
            details={"source": str(source.id)},
            ip_address=_ip(request),
        ),
    )
    await db.commit()
    await db.refresh(copy)
    return await _draft_response(db, copy, user, roles)
