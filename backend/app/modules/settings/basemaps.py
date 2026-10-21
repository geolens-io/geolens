"""Basemaps as clients may see them."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import BASEMAPS
from app.modules.settings.schemas import BasemapPublicResponse


async def list_public_basemaps(db: AsyncSession) -> list[BasemapPublicResponse]:
    """The configured basemaps, with ``{api_key}`` resolved server-side.

    A basemap whose URL needs a key that isn't configured is left out.
    """
    result: list[BasemapPublicResponse] = []
    for entry in await BASEMAPS.get(db):
        url = entry.get("url", "")
        key_value = entry.get("api_key")
        if "{api_key}" in url:
            if not key_value:
                continue
            entry = {**entry, "url": url.replace("{api_key}", key_value)}
        result.append(BasemapPublicResponse(**entry))
    return result
