from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_mode_permission, require_permission
from app.modules.catalog.maps.schemas import MapIconListResponse, MapIconResponse
from app.modules.catalog.maps.sprites import (
    SpriteIndex,
    build_sprite_index,
    build_sprite_png,
    create_icon_asset,
    get_icon_content,
    list_icons,
)
from app.modules.catalog.maps.service import map_asset_publication
from app.standards.ogc.errors import ERROR_RESPONSES_PUBLIC, FORBIDDEN_RESPONSE

router = APIRouter()

require_icon_catalog_admin = require_mode_permission(
    single_tenant="edit_metadata", multi_tenant="manage_tenants"
)


@router.get("/icons", response_model=MapIconListResponse)
async def list_map_icons_endpoint(
    _user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapIconListResponse:
    """List reusable default and uploaded map icons."""
    return MapIconListResponse(icons=await list_icons(db))


@router.post(
    "/icons", response_model=MapIconResponse, status_code=status.HTTP_201_CREATED
)
async def upload_map_icon_endpoint(
    file: UploadFile = File(...),
    user: Identity = Depends(require_icon_catalog_admin),
    db: AsyncSession = Depends(get_db),
) -> MapIconResponse:
    """Upload a reusable SVG or PNG icon for symbol layers."""
    content = await file.read()
    # fix(#1778 round 4): the icon bytes and the row that names them are
    # published together. This is the third write-object-then-commit-row site in
    # the maps package, and the only one whose write and commit sit in different
    # functions, so the ledger is threaded through create_icon_asset.
    async with map_asset_publication() as publication:
        try:
            asset = await create_icon_asset(
                db,
                filename=file.filename,
                content_type=file.content_type,
                content=content,
                created_by=user.id,
                publication=publication,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await db.commit()
        # fix(#1778 round 5): settle on the commit, and keep the refresh below
        # outside the scope. A refresh that raises after a successful commit
        # would otherwise have deleted an icon the committed row references.
        publication.settled()
    await db.refresh(asset)
    return next(icon for icon in await list_icons(db) if icon.id == str(asset.id))


@router.get("/icons/{icon_id}/asset", responses={403: FORBIDDEN_RESPONSE})
async def get_map_icon_asset_endpoint(
    icon_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve an uploaded or bundled icon asset by stable icon ID.

    SEC-01 / M-63: SVG responses carry Content-Security-Policy
    ``default-src 'none'; sandbox`` so an uploaded SVG cannot fetch other
    origins, run scripts, or read auth cookies even if validation is bypassed
    in the future. Browsers (Chromium, Firefox) honor the sandbox directive on
    image/svg+xml responses. PNG responses use the global SecurityHeadersMiddleware
    default ``frame-ancestors 'self'``.
    """
    icon = await get_icon_content(db, icon_id)
    if icon is None:
        raise HTTPException(status_code=404, detail="Icon not found")
    content, media_type = icon
    headers = {"Cache-Control": "public, max-age=3600"}
    if media_type == "image/svg+xml":
        headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return Response(content=content, media_type=media_type, headers=headers)


# Sprites are anonymous, unauthenticated reads (MapLibre fetches them before any
# auth context exists). FastAPI's `responses=` merge is additive along the whole
# include chain — a route only ever gains keys from an ancestor router, never
# loses one — so nesting this router under `router` (in turn nested under the
# maps router's `responses=ERROR_RESPONSES_WRITE`) would still leak a 401/403/409
# these routes can never emit. `sprites_router` is therefore mounted directly on
# `api_router` in api/router.py, as a sibling of the maps router rather than a
# descendant, carrying its own `/maps` prefix so the published paths are
# unchanged.
sprites_router = APIRouter(
    prefix="/maps", tags=["Maps"], responses=ERROR_RESPONSES_PUBLIC
)


@sprites_router.get("/sprites/geolens.json")
async def get_geolens_sprite_index_endpoint(
    db: AsyncSession = Depends(get_db),
) -> SpriteIndex:
    """Serve the stable GeoLens sprite JSON index."""
    return await build_sprite_index(db)


@sprites_router.get("/sprites/geolens@2x.json", include_in_schema=False)
async def get_geolens_sprite_index_2x_endpoint(
    db: AsyncSession = Depends(get_db),
) -> SpriteIndex:
    """Serve the GeoLens sprite index for high-DPI MapLibre sprite requests."""
    return await build_sprite_index(db)


@sprites_router.get("/sprites/geolens.png")
async def get_geolens_sprite_png_endpoint(
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve the generated GeoLens sprite sheet for stable icon IDs."""
    return Response(
        content=await build_sprite_png(db),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@sprites_router.get("/sprites/geolens@2x.png", include_in_schema=False)
async def get_geolens_sprite_png_2x_endpoint(
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve the GeoLens sprite sheet for high-DPI MapLibre sprite requests."""
    return Response(
        content=await build_sprite_png(db),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )
