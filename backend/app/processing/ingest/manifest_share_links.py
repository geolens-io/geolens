"""The links a version 2 apply returns for a share link it minted.

The raw token exists only in the apply's result, so the app URL they are
built on is resolved before any map is written, and building them from it
is string work that can't fail.
"""

from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.public_urls import (
    get_configured_public_app_url,
    is_usable_public_origin,
    join_public_url,
    normalize_public_url,
)
from app.core.tenancy import is_multi_tenant
from app.processing.ingest.manifest_schemas import ManifestMapLinks


class ShareOriginUnavailable(Exception):
    """No origin a link's recipient could open is known for this request."""


async def share_base_url(db: AsyncSession, http_request: Request | None) -> str:
    """The web app origin a minted share link is built on.

    Only a configured origin counts: ``PUBLIC_APP_URL``, or a hosted
    tenant's validated public origin for a tenant-bound request, since a
    link on the fleet host would reach the recipient without the tenant
    context its token lookup needs. Nothing is derived from the request: a
    desktop client calls the API directly, and ``/m/{token}`` is served by
    the web app, not the API. Raises ``ShareOriginUnavailable`` when there is
    none, and on a failed lookup.
    """
    tenant_id = getattr(getattr(http_request, "state", None), "tenant_id", None)
    if is_multi_tenant() and tenant_id is not None:
        origin = normalize_public_url(
            getattr(http_request.state, "tenant_public_origin", None)
        )
        if origin is None or not is_usable_public_origin(origin):
            raise ShareOriginUnavailable
        return origin
    app_url = await get_configured_public_app_url(db)
    if app_url is None:
        raise ShareOriginUnavailable
    join_public_url(app_url, "/m/")
    return app_url


def _escape_attribute(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def embed_snippet(share_url: str, title: str) -> str:
    """The iframe snippet the web app's share panel copies for a share link
    with no embed token, both attribute values escaped."""
    src = _escape_attribute(f"{share_url}?embed=true")
    return (
        f'<iframe src="{src}" title="{_escape_attribute(title)}"'
        ' width="100%" height="600" sandbox="allow-scripts allow-same-origin"'
        ' style="border:none;"></iframe>'
    )


def minted_share_links(
    app_url: str, map_id: uuid.UUID, token: str, title: str
) -> ManifestMapLinks:
    """A map's links with the share link and embed code of a minted token."""
    share = join_public_url(app_url, f"/m/{token}")
    return ManifestMapLinks(
        viewer=join_public_url(app_url, f"/maps/{map_id}"),
        share=share,
        embed=embed_snippet(share, title),
    )
