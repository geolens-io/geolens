"""Link-preview HTML that nginx serves to unfurl crawlers on catalog pages."""

import html

from fastapi import Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_urls import get_public_app_url, join_public_url

_DESCRIPTION_MAX_CHARS = 200


def preview_description(text: str | None, fallback: str) -> str:
    """``text`` on one line and cut to the length unfurlers show, or
    ``fallback`` when it is blank."""
    flat = " ".join((text or "").split())
    if not flat:
        return fallback
    if len(flat) <= _DESCRIPTION_MAX_CHARS:
        return flat
    return flat[: _DESCRIPTION_MAX_CHARS - 1].rstrip() + "…"


async def site_card_image_url(db: AsyncSession, request: Request) -> str:
    """The site's own card image, for a page that has none of its own."""
    app_base = await get_public_app_url(db, request=request)
    return join_public_url(app_base, "/og-image.png")


def link_preview_response(
    *, page_url: str, image_url: str, title: str, description: str
) -> HTMLResponse:
    """Open Graph and Twitter tags for one page; every argument is escaped."""
    page_url = html.escape(page_url, quote=True)
    image_url = html.escape(image_url, quote=True)
    title = html.escape(title)
    description = html.escape(description)
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
