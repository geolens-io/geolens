"""Link-preview HTML that nginx serves to unfurl crawlers on ``/maps/<id>``."""

import html
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.public_urls import get_shareable_app_url, join_public_url
from app.modules.catalog.authorization import check_map_access
from app.modules.catalog.maps.service import get_map
from app.modules.catalog.maps.sharing import get_share_card_image_url

router = APIRouter(prefix="/maps", include_in_schema=False)

_DESCRIPTION_MAX_CHARS = 200


def _preview_description(description: str | None) -> str:
    text = " ".join((description or "").split())
    if not text:
        return "View this map on GeoLens"
    if len(text) <= _DESCRIPTION_MAX_CHARS:
        return text
    return text[: _DESCRIPTION_MAX_CHARS - 1].rstrip() + "…"


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

    page_url = html.escape(join_public_url(app_url, f"/maps/{map_obj.id}"), quote=True)
    image_url = html.escape(
        await get_share_card_image_url(db, request, map_obj), quote=True
    )
    title = html.escape(map_obj.name or "GeoLens")
    description = html.escape(_preview_description(map_obj.description))
    # No meta refresh: a browser sent here by a crawler-like user agent would
    # be routed back to this page and loop.
    return HTMLResponse(
        content=(
            "<!doctype html>\n"
            '<html><head>\n<meta charset="UTF-8">\n'
            f"<title>{title}</title>\n"
            f'<meta name="description" content="{description}">\n'
            f'<link rel="canonical" href="{page_url}">\n'
            '<meta property="og:type" content="website">\n'
            f'<meta property="og:url" content="{page_url}">\n'
            f'<meta property="og:title" content="{title}">\n'
            f'<meta property="og:description" content="{description}">\n'
            f'<meta property="og:image" content="{image_url}">\n'
            '<meta name="twitter:card" content="summary_large_image">\n'
            f'<meta name="twitter:title" content="{title}">\n'
            f'<meta name="twitter:description" content="{description}">\n'
            f'<meta name="twitter:image" content="{image_url}">\n'
            f'</head><body><a href="{page_url}">{title}</a></body></html>\n'
        ),
        # Browsers get the SPA at the same URL, so no shared cache may keep this.
        headers={"Cache-Control": "no-store"},
    )
