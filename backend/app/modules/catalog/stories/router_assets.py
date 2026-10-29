"""Story images: uploads by the story's editors, reads under its read rules."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from starlette.datastructures import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import get_optional_user, require_permission
from app.modules.catalog.stories.assets import (
    add_story_asset,
    discard_story_asset_objects,
    get_story_asset,
    new_story_asset_key,
    reaches_readers,
)
from app.modules.catalog.stories.images import (
    MAX_UPLOAD_BYTES,
    prepare_story_image,
    upload_slot,
)
from app.modules.catalog.stories.schemas import StoryAssetResponse
from app.modules.catalog.stories.service import (
    ANONYMOUS_STORY_VISIBILITIES,
    STORY_NOT_FOUND,
    can_edit_story,
    check_story_access,
    check_story_ownership,
    get_story,
    lock_story,
)
from app.platform.binary_response import binary_response
from app.platform.http.ranges import stored_object_response
from app.platform.storage.publication import asset_publication
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    CONFLICT_RESPONSE,
    ERROR_RESPONSES_WRITE,
    PAYLOAD_TOO_LARGE_RESPONSE,
    PROBLEM_RESPONSE,
)

router = APIRouter(prefix="/stories", tags=["Stories"], responses=ERROR_RESPONSES_WRITE)

_IMAGE_NOT_FOUND = "Image not found"

# Declared by hand: a File() parameter would make FastAPI spool the body
# before the caller is authenticated or admitted.
_UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


def _not_found(detail: str) -> HTTPException:
    # A cached 404 would outlive the publish that makes the image readable.
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=detail,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/{story_id}/assets",
    response_model=StoryAssetResponse,
    status_code=status.HTTP_201_CREATED,
    openapi_extra=_UPLOAD_BODY,
    responses={
        409: {
            **CONFLICT_RESPONSE,
            "description": (
                "The story already holds its most images or bytes "
                "(`detail.code` `story_asset_limit`), or another change holds "
                "its lock."
            ),
        },
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        415: {**PROBLEM_RESPONSE, "description": "Not a PNG, JPEG or WebP image"},
        502: BAD_GATEWAY_RESPONSE,
        503: {
            **PROBLEM_RESPONSE,
            "description": (
                "Other images are being processed (`detail.code` "
                "`story_image_busy`); retry after `Retry-After` seconds."
            ),
        },
    },
)
async def upload_story_asset_endpoint(
    story_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryAssetResponse:
    """Upload an image, the multipart part `file`, for the story's blocks or
    cover (owner or admin).

    PNG, JPEG and WebP, told apart by their bytes. It's stored as sRGB WebP
    without its metadata. 400 `story_image_unreadable`, 413
    `story_image_too_large`, 415 `story_image_unsupported`, 409
    `story_asset_limit`, 503 `story_image_busy`. Readers get it once a
    published block or the cover uses it.
    """
    story = await get_story(db, story_id)
    if story is None:
        raise _not_found(STORY_NOT_FOUND)
    await check_story_ownership(db, story, user)

    from app.platform.storage.provider import get_storage

    async with (
        upload_slot(),
        request.form(max_files=1, max_fields=0) as form,
    ):
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "story_image_missing",
                    "message": "Send the image as the multipart file part `file`.",
                },
            )
        image = await prepare_story_image(await upload.read(MAX_UPLOAD_BYTES + 1))

        storage_key = new_story_asset_key(story_id)
        async with asset_publication() as publication:
            physical_key = resolve_current_storage_key(storage_key)
            publication.record(physical_key)
            try:
                await get_storage().put(physical_key, image.data)
            except Exception as exc:  # broad: varied storage SDK/I/O errors; 502
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Story image storage unavailable",
                ) from exc
            # Taken after the PUT, so a stalled backend can't hold the story lock.
            story, _ = await lock_story(db, story_id, user)
            asset, unused = await add_story_asset(
                db, story, storage_key, image, user.id
            )
            publication.committing()
            await db.commit()
            publication.settled()
        await discard_story_asset_objects(unused)
    await db.refresh(asset)
    return StoryAssetResponse.model_validate(asset, from_attributes=True)


@router.get(
    "/{story_id}/assets/{asset_id}",
    response_class=Response,
    responses={
        200: binary_response("The image", "image/webp"),
        304: {"description": "Your copy, named by `If-None-Match`, is current."},
    },
)
async def get_story_asset_endpoint(
    story_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve one of the story's images as WebP.

    Its owner and admins get any of them. Anyone else who can read the story
    gets the cover and the images its published document uses. 404 otherwise.
    """
    from app.platform.storage.provider import get_storage

    found = await get_story_asset(db, story_id, asset_id)
    if found is None:
        raise _not_found(_IMAGE_NOT_FOUND)
    story, asset = found
    try:
        roles = await check_story_access(db, story, user)
    except HTTPException as exc:
        raise _not_found(_IMAGE_NOT_FOUND) from exc
    readable = await reaches_readers(db, story, asset.id)
    if not (readable or can_edit_story(story, user, roles)):
        raise _not_found(_IMAGE_NOT_FOUND)

    # Revalidated on every use, since narrowing the story withholds it.
    anonymous = readable and story.visibility in ANONYMOUS_STORY_VISIBILITIES
    try:
        return await stored_object_response(
            request,
            lambda: get_storage().get(resolve_current_storage_key(asset.storage_key)),
            # The object under an asset's key never changes.
            etag=f'"{asset.id}"',
            media_type="image/webp",
            cache_control="public, no-cache" if anonymous else "private, no-cache",
        )
    except FileNotFoundError as exc:
        raise _not_found(_IMAGE_NOT_FOUND) from exc
