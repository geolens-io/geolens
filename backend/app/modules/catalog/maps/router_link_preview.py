"""Link-preview HTML that nginx serves to unfurl crawlers on ``/maps/<id>``."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.public_urls import get_shareable_app_url, join_public_url
from app.modules.catalog.authorization import check_map_access
from app.modules.catalog.link_preview import link_preview_response, preview_description
from app.modules.catalog.maps.service import get_map
from app.modules.catalog.maps.sharing import get_share_card_image_url

router = APIRouter(prefix="/maps", include_in_schema=False)


@router.get("/{map_id}/link-preview", response_class=HTMLResponse)
async def map_link_preview_endpoint(
    map_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Open Graph and Twitter tags for a map an anonymous caller may read.

    Crawlers are treated as anonymous whatever credentials the request
    carries. A private, internal or missing map answers 404 with the same
    body, and so does a deployment without a verified public app origin,
    since every URL here must be absolute and the request Host is not
    trusted to supply one. nginx serves the SPA shell for any 404.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    await check_map_access(db, map_obj, None)
    app_url = await get_shareable_app_url(db, request=request)
    if app_url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )

    return link_preview_response(
        page_url=join_public_url(app_url, f"/maps/{map_obj.id}"),
        image_url=await get_share_card_image_url(db, request, map_obj),
        title=map_obj.name or "GeoLens",
        description=preview_description(
            map_obj.description, "View this map on GeoLens"
        ),
    )
